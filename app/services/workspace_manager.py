"""Workspace Manager — Persistent multi-tenant workspace lifecycle management.

Workspaces are stored as JSON files under data/workspaces/{workspace_id}.json
No heavy database required for a single-server deployment.
Each workspace has a unique API key used for per-tenant authentication.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.schemas.workspace import PlanConfig, WorkspaceCreate, WorkspaceInfo
from app.core.security import is_safe_identifier, validate_path_containment

logger = logging.getLogger(__name__)

_WORKSPACE_DIR = Path("data/workspaces")
_PLANS_FILE = Path("data/plans.json")


def _load_plans() -> dict[str, PlanConfig]:
    """Load plan configurations from plans.json."""
    if not _PLANS_FILE.exists():
        logger.warning("plans.json not found — using built-in defaults.")
        return {
            "trial": PlanConfig(
                name="trial", display_name="Trial",
                max_pages_per_month=100, max_file_mb=5.0,
                max_concurrent_jobs=1, max_chunks_per_month=5000,
                max_embeddings_per_month=2000,
            ),
            "developer": PlanConfig(
                name="developer", display_name="Developer",
                max_pages_per_month=2000, max_file_mb=25.0,
                max_concurrent_jobs=3, max_chunks_per_month=100000,
                max_embeddings_per_month=50000,
            ),
            "professional": PlanConfig(
                name="professional", display_name="Professional",
                max_pages_per_month=20000, max_file_mb=100.0,
                max_concurrent_jobs=10, max_chunks_per_month=1000000,
                max_embeddings_per_month=500000,
            ),
        }
    with open(_PLANS_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    return {p["name"]: PlanConfig(**p) for p in raw}


_PLANS: dict[str, PlanConfig] = {}


def get_plan(name: str) -> PlanConfig:
    """Return a PlanConfig by name, falling back to 'trial'."""
    global _PLANS
    if not _PLANS:
        _PLANS = _load_plans()
    return _PLANS.get(name, _PLANS.get("trial", list(_PLANS.values())[0]))


def get_all_plans() -> list[PlanConfig]:
    """Return all available plan configs."""
    global _PLANS
    if not _PLANS:
        _PLANS = _load_plans()
    return list(_PLANS.values())


def _generate_api_key() -> str:
    """Generate a secure random API key with prefix 'cbk_'."""
    return "cbk_" + secrets.token_urlsafe(32)


def _hash_api_key(api_key: str) -> str:
    """Compute SHA-256 hash of API key for secure disk persistence."""
    return hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()


_SAFE_WORKSPACE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{3,64}$")


def _is_safe_workspace_id(workspace_id: str) -> bool:
    """Validate workspace_id to prevent directory traversal attacks."""
    return is_safe_identifier(workspace_id)


def _workspace_path(workspace_id: str) -> Path:
    if not _is_safe_workspace_id(workspace_id):
        return _WORKSPACE_DIR / "__invalid__.json"
    return _WORKSPACE_DIR / f"{workspace_id}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspaceManager:
    """
    Manages workspace lifecycle with JSON-file persistence.

    Each workspace is stored in data/workspaces/{workspace_id}.json.
    API keys are hashed (SHA-256) on disk; raw keys are never persisted.
    Only the first 8 characters (prefix) are stored for identification.
    """

    def __init__(self, workspace_dir: Path | str = _WORKSPACE_DIR) -> None:
        self._dir = Path(workspace_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        # In-memory index: api_key_hash -> workspace_id (for fast lookup)
        self._key_index: dict[str, str] = {}
        self._load_index()

    def _load_index(self) -> None:
        """Rebuild api_key_hash -> workspace_id index from disk."""
        self._key_index.clear()
        for p in self._dir.glob("*.json"):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                wid = data.get("workspace_id")
                if not wid:
                    continue

                # Preferred: api_key_hash
                key_hash = data.get("api_key_hash")
                if key_hash:
                    self._key_index[key_hash] = wid

                # Backward compatibility: migrate plaintext _api_key_raw if found
                raw_key = data.get("_api_key_raw")
                if raw_key:
                    k_hash = _hash_api_key(raw_key)
                    self._key_index[k_hash] = wid
                    data["api_key_hash"] = k_hash
                    data["api_key_prefix"] = raw_key[:8]
                    data.pop("_api_key_raw", None)
                    self._write_workspace(wid, data)
            except Exception as e:
                logger.warning("Failed to load workspace %s: %s", p, e)

    def _workspace_path(self, workspace_id: str) -> Path:
        if not _is_safe_workspace_id(workspace_id):
            return self._dir / "__invalid__.json"
        target = (self._dir / f"{workspace_id}.json").resolve()
        if not validate_path_containment(self._dir, target):
            return self._dir / "__invalid__.json"
        return target

    def _read_workspace_raw(self, workspace_id: str) -> Optional[dict[str, Any]]:
        if not _is_safe_workspace_id(workspace_id):
            return None
        path = self._workspace_path(workspace_id)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error reading workspace %s: %s", workspace_id, e)
            return None

    def _write_workspace(self, workspace_id: str, data: dict[str, Any]) -> None:
        if not _is_safe_workspace_id(workspace_id):
            raise ValueError(f"Cannot write workspace with unsafe ID: {workspace_id}")
        # Enforce that raw keys are NEVER written to disk
        data.pop("_api_key_raw", None)
        data.pop("api_key", None)
        path = self._workspace_path(workspace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)

    def _to_workspace_info(self, raw: dict[str, Any]) -> WorkspaceInfo:
        """Convert raw stored dict to public WorkspaceInfo (masks key)."""
        prefix = raw.get("api_key_prefix")
        if not prefix:
            raw_key = raw.get("_api_key_raw", "")
            prefix = raw_key[:8] if raw_key else "????????"
        plan_name = raw.get("plan", "trial")
        plan = get_plan(plan_name)
        return WorkspaceInfo(
            workspace_id=raw["workspace_id"],
            name=raw["name"],
            plan=plan_name,
            description=raw.get("description"),
            api_key_prefix=prefix,
            created_at=raw["created_at"],
            updated_at=raw["updated_at"],
            quota=plan.model_dump(),
            usage_this_month=raw.get("usage_this_month", {}),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_workspace(self, req: WorkspaceCreate) -> tuple[WorkspaceInfo, str]:
        """
        Create a new workspace.

        Returns:
            (WorkspaceInfo, raw_api_key) — the raw API key is returned ONCE only.
        """
        plan_name = req.plan if req.plan in (_PLANS or _load_plans()) else "trial"
        workspace_id = str(uuid.uuid4())
        api_key = _generate_api_key()
        key_hash = _hash_api_key(api_key)
        prefix = api_key[:8]
        now = _now_iso()
        data: dict[str, Any] = {
            "workspace_id": workspace_id,
            "name": req.name,
            "plan": plan_name,
            "description": req.description,
            "api_key_hash": key_hash,
            "api_key_prefix": prefix,
            "created_at": now,
            "updated_at": now,
            "usage_this_month": {},
        }
        self._write_workspace(workspace_id, data)
        self._key_index[key_hash] = workspace_id
        info = self._to_workspace_info(data)
        logger.info("Created workspace '%s' (id=%s, plan=%s)", req.name, workspace_id, plan_name)
        return info, api_key

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        """Get workspace by ID (no secret exposure)."""
        if not _is_safe_workspace_id(workspace_id):
            return None
        raw = self._read_workspace_raw(workspace_id)
        if raw is None:
            return None
        return self._to_workspace_info(raw)

    def list_workspaces(self) -> list[WorkspaceInfo]:
        """List all workspaces (no secret exposure)."""
        result = []
        for p in self._dir.glob("*.json"):
            try:
                with open(p, encoding="utf-8") as f:
                    raw = json.load(f)
                result.append(self._to_workspace_info(raw))
            except Exception as e:
                logger.warning("Skipping workspace %s: %s", p.stem, e)
        return sorted(result, key=lambda w: w.created_at)

    def resolve_workspace_by_key(self, api_key: str) -> Optional[str]:
        """
        Resolve a raw API key to its workspace_id via SHA-256 hash lookup with constant-time comparison.

        Returns workspace_id or None if key is invalid.
        """
        if not api_key:
            return None
        incoming_hash = _hash_api_key(api_key)
        for key_hash, wid in list(self._key_index.items()):
            if hmac.compare_digest(incoming_hash, key_hash):
                return wid
        # Fallback: scan disk
        self._load_index()
        for key_hash, wid in list(self._key_index.items()):
            if hmac.compare_digest(incoming_hash, key_hash):
                return wid
        return None

    def verify_workspace_key(self, workspace_id: str, api_key: str) -> bool:
        """Verify an API key for a specific workspace using constant-time hash comparison."""
        if not api_key or not _is_safe_workspace_id(workspace_id):
            return False
        raw = self._read_workspace_raw(workspace_id)
        if not raw:
            return False
        stored_hash = raw.get("api_key_hash")
        if not stored_hash:
            return False
        incoming_hash = _hash_api_key(api_key)
        return hmac.compare_digest(incoming_hash, stored_hash)

    def rotate_api_key(self, workspace_id: str) -> Optional[tuple[WorkspaceInfo, str]]:
        """
        Generate and persist a new API key for the workspace.

        Returns (WorkspaceInfo, new_raw_key) or None if workspace not found.
        """
        if not _is_safe_workspace_id(workspace_id):
            return None
        raw = self._read_workspace_raw(workspace_id)
        if raw is None:
            return None
        old_hash = raw.get("api_key_hash")
        if old_hash and old_hash in self._key_index:
            del self._key_index[old_hash]
        old_raw = raw.get("_api_key_raw")
        if old_raw and _hash_api_key(old_raw) in self._key_index:
            del self._key_index[_hash_api_key(old_raw)]

        new_key = _generate_api_key()
        new_hash = _hash_api_key(new_key)
        raw["api_key_hash"] = new_hash
        raw["api_key_prefix"] = new_key[:8]
        raw.pop("_api_key_raw", None)
        raw["updated_at"] = _now_iso()
        self._write_workspace(workspace_id, raw)
        self._key_index[new_hash] = workspace_id
        logger.info("Rotated API key for workspace %s", workspace_id)
        return self._to_workspace_info(raw), new_key

    def delete_workspace(self, workspace_id: str) -> bool:
        """
        Delete workspace and all associated disk artifacts safely.

        Removes: workspace JSON, output artifacts, manifests, usage logs, job persistence.
        Returns True if deleted, False if not found or invalid ID.
        """
        if not _is_safe_workspace_id(workspace_id):
            logger.warning("Attempted deletion of invalid/unsafe workspace ID: %s", workspace_id)
            return False

        raw = self._read_workspace_raw(workspace_id)
        if raw is None:
            return False

        key_hash = raw.get("api_key_hash")
        if key_hash and key_hash in self._key_index:
            del self._key_index[key_hash]
        old_raw = raw.get("_api_key_raw")
        if old_raw and _hash_api_key(old_raw) in self._key_index:
            del self._key_index[_hash_api_key(old_raw)]

        # Remove workspace JSON
        self._workspace_path(workspace_id).unlink(missing_ok=True)

        # Remove all tenant-scoped data directories with strict path containment
        import shutil
        for subdir in ["output", "data/manifests", "data/usage", "data/jobs"]:
            base_dir = Path(subdir).resolve()
            tenant_dir = (Path(subdir) / workspace_id).resolve()
            if not validate_path_containment(base_dir, tenant_dir):
                logger.error("Path traversal detected attempting to delete %s", tenant_dir)
                continue
            if tenant_dir.exists():
                shutil.rmtree(tenant_dir, ignore_errors=True)
                logger.info("Removed tenant data at %s", tenant_dir)

        logger.info("Deleted workspace %s ('%s')", workspace_id, raw.get("name"))
        return True

    def update_plan(self, workspace_id: str, new_plan: str) -> Optional[WorkspaceInfo]:
        """Change the plan for a workspace."""
        if not _is_safe_workspace_id(workspace_id):
            return None
        raw = self._read_workspace_raw(workspace_id)
        if raw is None:
            return None
        valid_plans = [p.name for p in get_all_plans()]
        raw["plan"] = new_plan if new_plan in valid_plans else raw.get("plan", "trial")
        raw["updated_at"] = _now_iso()
        self._write_workspace(workspace_id, raw)
        return self._to_workspace_info(raw)

    def workspace_exists(self, workspace_id: str) -> bool:
        if not _is_safe_workspace_id(workspace_id):
            return False
        return self._workspace_path(workspace_id).exists()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: Optional[WorkspaceManager] = None


def get_workspace_manager() -> WorkspaceManager:
    global _instance
    if _instance is None:
        _instance = WorkspaceManager()
    return _instance
