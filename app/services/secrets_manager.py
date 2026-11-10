"""Secrets Manager — secure storage of per-workspace BYOK (Bring Your Own Key) credentials.

Keys are stored AES-encrypted with Fernet symmetric encryption under:
    data/secrets/{workspace_id}.json

Security Architecture:
  - Cryptographic Workspace Binding: Each ciphertext is authenticated and bound to its
    specific workspace_id. Ciphertext transferred to another tenant's directory cannot be decrypted.
  - Fail-Closed Master Encryption Key: If the master key is missing in production or corrupted,
    the system NEVER silently regenerates a new key (which would permanently destroy all existing
    encrypted secrets). Instead, an explicit, secure RuntimeError is raised.
  - Master Key Backup & Recovery: Dedicated backup and recovery functions with strict permissions.
  - Masking: Only masked strings (first 4 + last 4 characters) are exposed in API responses.
  - Path Traversal Containment: All workspace_id and key_name inputs are validated against strict regex
    and resolved paths are verified to reside strictly within the secrets directory.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from app.core.security import is_safe_identifier, validate_path_containment

logger = logging.getLogger(__name__)

_SAFE_WS_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{3,64}$")
_SECRETS_DIR = Path("data/secrets")
_MASTER_KEY_FILE = Path("data/.secret_key")


def _load_or_generate_master_key(master_key_file: Path | str = _MASTER_KEY_FILE) -> bytes:
    """Load the Fernet master key from CRAWLBOT_SECRET_KEY env var or from key file.

    Security Policies:
    - Never silently regenerate an invalid or corrupt key file, as doing so permanently
      destroys all existing customer encrypted secrets.
    - If CRAWLBOT_SECRET_KEY is provided but cannot initialize a valid Fernet instance,
      raise RuntimeError.
    - If the key file exists but is corrupted or invalid, raise RuntimeError.
    - In production mode, CRAWLBOT_SECRET_KEY is strictly required; raising an error if missing.
    - Only in development/test mode when no key exists at all, generate an initial key.
    """
    from app.core.config import get_settings
    settings = get_settings()
    key_path = Path(master_key_file)

    # 1. Environment variable NEXORA_SECRET_KEY / CRAWLBOT_SECRET_KEY
    from_env = (
        os.environ.get("NEXORA_SECRET_KEY", "").strip()
        or os.environ.get("CRAWLBOT_SECRET_KEY", "").strip()
        or (settings.secret_key or "").strip()
    )
    if from_env:
        try:
            # Check if it's already a valid Fernet key (44 chars urlsafe base64)
            Fernet(from_env.encode())
            return from_env.encode()
        except Exception:
            try:
                # Check if it's 32 raw bytes that were base64url encoded
                raw_bytes = base64.urlsafe_b64decode(from_env.encode())
                if len(raw_bytes) == 32:
                    encoded = base64.urlsafe_b64encode(raw_bytes)
                    Fernet(encoded)
                    return encoded
            except Exception:
                pass
            raise RuntimeError(
                "Invalid NEXORA_SECRET_KEY / Invalid CRAWLBOT_SECRET_KEY configuration: Value must be a valid 32-byte urlsafe base64 Fernet key. "
                "Automatic key regeneration is disabled to prevent permanent loss of encrypted customer secrets."
            )

    # 2. Key file on disk
    if key_path.exists():
        try:
            key_bytes = key_path.read_bytes().strip()
            # Validate valid Fernet key
            Fernet(key_bytes)
            return key_bytes
        except Exception as exc:
            raise RuntimeError(
                f"Master encryption key file at '{key_path}' exists but is corrupt or invalid: {exc}. "
                "Automatic key regeneration is strictly disabled to prevent permanent data loss. "
                "Please restore the key from backup or configure NEXORA_SECRET_KEY."
            ) from exc

    # 3. Neither exists: check environment
    is_prod = str(getattr(settings, "app_env", "development")).lower() in ("production", "prod")
    if is_prod:
        raise RuntimeError(
            "NEXORA_SECRET_KEY / CRAWLBOT_SECRET_KEY environment variable is required in production environment. "
            "Set NEXORA_SECRET_KEY to a secure 32-byte base64url Fernet key."
        )

    # Initial development bootstrap only
    new_key = Fernet.generate_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(new_key)
    try:
        key_path.chmod(0o600)
    except Exception:
        pass
    logger.info("Initialized initial development Fernet key at %s", key_path)
    return new_key


def backup_master_key(dest_path: Path | str, source_path: Path | str = _MASTER_KEY_FILE) -> Path:
    """Safely backup the Fernet master encryption key to a destination file.

    Verifies key validity before writing and enforces 0o600 permissions.
    """
    src = Path(source_path)
    dest = Path(dest_path)
    if not src.exists():
        raise FileNotFoundError(f"Source master key file '{src}' does not exist.")
    key_bytes = src.read_bytes().strip()
    Fernet(key_bytes)  # validate before backing up
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(key_bytes)
    try:
        dest.chmod(0o600)
    except Exception:
        pass
    logger.info("Master encryption key safely backed up to %s", dest)
    return dest


def restore_master_key(backup_path: Path | str, target_path: Path | str = _MASTER_KEY_FILE) -> bool:
    """Restore Fernet master encryption key from a backup file after verifying validity."""
    backup = Path(backup_path)
    target = Path(target_path)
    if not backup.exists():
        raise FileNotFoundError(f"Backup file '{backup}' does not exist.")
    key_bytes = backup.read_bytes().strip()
    Fernet(key_bytes)  # validate that backup is a valid Fernet key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(key_bytes)
    try:
        target.chmod(0o600)
    except Exception:
        pass
    logger.info("Restored master encryption key from %s to %s", backup, target)
    return True


def _mask_key(raw: str) -> str:
    """Show only first 4 and last 4 characters of a key."""
    if not raw or len(raw) <= 8:
        return "****"
    return f"{raw[:4]}{'*' * (len(raw) - 8)}{raw[-4:]}"


class SecretsManager:
    """
    Manages per-workspace encrypted secret storage.

    Supported secret keys:
      openai_api_key  — user's own OpenAI key (BYOK)
      (extendable to other LLM providers)
    """

    def __init__(
        self,
        secrets_dir: Path | str = _SECRETS_DIR,
        master_key_file: Path | str = _MASTER_KEY_FILE,
        master_key: Optional[bytes] = None,
    ) -> None:
        self._dir = Path(secrets_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        if master_key:
            self._fernet = Fernet(master_key)
        else:
            self._fernet = Fernet(_load_or_generate_master_key(master_key_file=master_key_file))

    def _secrets_path(self, workspace_id: str) -> Path:
        if not is_safe_identifier(workspace_id):
            return self._dir / "__invalid_ws_id__.json"
        target = (self._dir / f"{workspace_id}.json").resolve()
        if not validate_path_containment(self._dir, target):
            return self._dir / "__invalid_ws_id__.json"
        return target

    def _read_raw(self, workspace_id: str) -> dict[str, str]:
        path = self._secrets_path(workspace_id)
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error reading secrets for workspace %s: %s", workspace_id, e)
            return {}

    def _write_raw(self, workspace_id: str, data: dict[str, str]) -> None:
        path = self._secrets_path(workspace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except Exception:
            pass

    def _encrypt(self, workspace_id: str, plaintext: str) -> str:
        """Encrypt a secret string with cryptographic workspace binding."""
        payload = f"{workspace_id}:{plaintext}"
        return self._fernet.encrypt(payload.encode("utf-8")).decode("utf-8")

    def _decrypt(self, workspace_id: str, ciphertext: str) -> Optional[str]:
        """Decrypt a secret, verifying that it cryptographically belongs to the requesting workspace."""
        try:
            decrypted = self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
            if ":" in decrypted:
                bound_ws, _, val = decrypted.partition(":")
                if bound_ws != workspace_id:
                    logger.error(
                        "Cross-tenant secret tampering detected: secret bound to '%s' accessed by '%s'",
                        bound_ws,
                        workspace_id,
                    )
                    return None
                return val
            # Backward compatibility with legacy un-prefixed secrets
            return decrypted
        except (InvalidToken, Exception) as e:
            logger.error("Decryption failed for workspace %s: %s", workspace_id, e)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_secret(self, workspace_id: str, key_name: str, value: str) -> None:
        """
        Store an encrypted secret for a workspace.

        Args:
            workspace_id: Target workspace.
            key_name: Logical name (e.g. 'openai_api_key').
            value: Plaintext secret value. Never logged.
        """
        if not is_safe_identifier(workspace_id):
            raise ValueError(f"Invalid workspace ID format: '{workspace_id}'.")
        if not is_safe_identifier(key_name):
            raise ValueError(f"Invalid key_name format: '{key_name}'.")
        if not value or not value.strip():
            raise ValueError(f"Secret value for '{key_name}' must not be empty.")
        raw = self._read_raw(workspace_id)
        raw[key_name] = self._encrypt(workspace_id, value.strip())
        self._write_raw(workspace_id, raw)
        logger.info("Set secret '%s' for workspace %s (value masked)", key_name, workspace_id)

    def get_secret(self, workspace_id: str, key_name: str) -> Optional[str]:
        """
        Retrieve and decrypt a secret for a workspace.

        Returns the plaintext value or None if not found/decryption failed.
        Callers must NOT log or expose this value.
        """
        if not is_safe_identifier(workspace_id):
            return None
        raw = self._read_raw(workspace_id)
        ciphertext = raw.get(key_name)
        if not ciphertext:
            return None
        return self._decrypt(workspace_id, ciphertext)

    def get_secret_masked(self, workspace_id: str, key_name: str) -> Optional[str]:
        """Return a masked representation of the secret for display in APIs."""
        raw_val = self.get_secret(workspace_id, key_name)
        if raw_val is None:
            return None
        return _mask_key(raw_val)

    def list_secrets(self, workspace_id: str) -> list[dict[str, str]]:
        """
        List secret key names and masked values for a workspace.

        Never returns decrypted values.
        """
        if not is_safe_identifier(workspace_id):
            return []
        raw = self._read_raw(workspace_id)
        result = []
        for key_name, ciphertext in raw.items():
            plaintext = self._decrypt(workspace_id, ciphertext)
            result.append({
                "key_name": key_name,
                "masked_value": _mask_key(plaintext) if plaintext else "****",
                "is_set": True,
            })
        return result

    def delete_secret(self, workspace_id: str, key_name: str) -> bool:
        """Delete a specific secret. Returns True if it existed."""
        if not is_safe_identifier(workspace_id):
            return False
        raw = self._read_raw(workspace_id)
        if key_name not in raw:
            return False
        del raw[key_name]
        self._write_raw(workspace_id, raw)
        logger.info("Deleted secret '%s' for workspace %s", key_name, workspace_id)
        return True

    def delete_all_secrets(self, workspace_id: str) -> None:
        """Delete all secrets for a workspace (e.g. on workspace deletion)."""
        if not is_safe_identifier(workspace_id):
            return
        path = self._secrets_path(workspace_id)
        if validate_path_containment(self._dir, path) and path.exists():
            path.unlink()
            logger.info("Deleted all secrets for workspace %s", workspace_id)

    def has_secret(self, workspace_id: str, key_name: str) -> bool:
        """Check if a secret exists without decrypting it."""
        if not is_safe_identifier(workspace_id):
            return False
        raw = self._read_raw(workspace_id)
        return key_name in raw


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: SecretsManager | None = None


def get_secrets_manager() -> SecretsManager:
    global _instance
    if _instance is None:
        _instance = SecretsManager()
    return _instance
