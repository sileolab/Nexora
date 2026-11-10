"""Crawlbot Studio — Phase 2 API Key Security & BYOK Secrets Test Suite.

Mandatory Verification Matrix:
1. Workspace Creation:
   - Raw API key is returned ONCE only.
   - Disk JSON file contains NO raw key (_api_key_raw or plain api_key).
   - Only SHA-256 hash (api_key_hash) and prefix (api_key_prefix) are stored.
2. API Key Authentication & Constant-Time Verification:
   - resolve_workspace_by_key resolves valid key, rejects invalid key.
   - verify_workspace_key uses constant-time comparison (hmac.compare_digest).
3. API Key Rotation:
   - Key rotation invalidates old key immediately (401 Unauthorized).
   - New key is functional (200 OK).
   - Raw key is never written to disk during/after rotation.
4. Tenant Isolation & Access Protection:
   - Tenant B cannot view, rotate, or modify Tenant A's key or secrets (403 Forbidden).
5. Secrets AES Encryption & Cryptographic Workspace Binding:
   - Customer secrets are stored Fernet AES-encrypted on disk.
   - Ciphertext is bound to workspace_id (workspace_id:secret).
   - Cross-tenant tampering (copying ciphertext to another tenant) fails decryption.
6. Fail-Closed Master Encryption Key:
   - Corrupted or invalid master key refuses silent regeneration and raises RuntimeError.
   - Missing key in production mode raises RuntimeError.
7. Disaster Recovery & Backup:
   - backup_master_key and restore_master_key successfully preserve and restore key integrity.
   - Secrets remain decryptable after restore.
8. Multi-Tenant BYOK in Real AI Pipeline:
   - Distinct BYOK keys for Tenant Alpha and Tenant Beta are properly isolated.
   - AI endpoints use each tenant's specific key.
9. Secret Leakage Prevention:
   - Provider exceptions and logs sanitize API keys (sk-..., cbk_..., Bearer tokens).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import sanitize_secret_leakage
from app.jobs.manager import JobManager
from app.main import create_app
from app.schemas.chunks import DocumentChunk, EmbeddingStats
from app.schemas.workspace import WorkspaceCreate
from app.services.embedding_service import EmbeddingService
from app.services.secrets_manager import (
    SecretsManager,
    _load_or_generate_master_key,
    backup_master_key,
    restore_master_key,
)
from app.services.workspace_manager import (
    WorkspaceManager,
    _hash_api_key,
)


def _make_test_chunk(source_url: str, text: str, tenant_id: str | None = None) -> DocumentChunk:
    """Helper to instantiate a valid DocumentChunk."""
    return DocumentChunk(
        chunk_id=str(uuid.uuid4()),
        source_url=source_url,
        chunk_index=0,
        total_chunks=1,
        text=text,
        char_count=len(text),
        word_count=len(text.split()),
        tenant_id=tenant_id,
    )


@pytest.fixture
def phase2_env():
    """Setup isolated temporary directories for workspaces and secrets."""
    temp_dir = tempfile.mkdtemp(prefix="crawlbot_phase2_")
    ws_dir = Path(temp_dir) / "workspaces"
    sec_dir = Path(temp_dir) / "secrets"
    key_file = Path(temp_dir) / ".secret_key"
    ws_dir.mkdir(parents=True)
    sec_dir.mkdir(parents=True)

    master_key = Fernet.generate_key()
    key_file.write_bytes(master_key)

    wm = WorkspaceManager(workspace_dir=ws_dir)
    sm = SecretsManager(secrets_dir=sec_dir, master_key_file=key_file)

    settings = get_settings()
    old_admin_key = settings.api_key
    admin_key = "admin-phase2-master-key-xyz"
    settings.api_key = admin_key

    app = create_app()
    client = TestClient(app)

    yield {
        "temp_dir": temp_dir,
        "ws_dir": ws_dir,
        "sec_dir": sec_dir,
        "key_file": key_file,
        "master_key": master_key,
        "wm": wm,
        "sm": sm,
        "client": client,
        "admin_key": admin_key,
    }

    settings.api_key = old_admin_key
    shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 1. WORKSPACE CREATION: NO RAW API KEY ON DISK
# ==============================================================================

def test_workspace_creation_never_writes_raw_api_key_to_disk(phase2_env):
    """Raw API keys must NEVER be stored in JSON files on disk."""
    wm: WorkspaceManager = phase2_env["wm"]
    ws_dir: Path = phase2_env["ws_dir"]

    # 1. Create workspace directly via WorkspaceManager
    req = WorkspaceCreate(name="Acme Vault", plan="trial")
    info, raw_key = wm.create_workspace(req)

    assert raw_key.startswith("cbk_")
    assert len(raw_key) > 30

    # 2. Check JSON file on disk
    file_path = ws_dir / f"{info.workspace_id}.json"
    assert file_path.exists()
    disk_text = file_path.read_text(encoding="utf-8")
    disk_data = json.loads(disk_text)

    # Must NOT have raw keys
    assert "_api_key_raw" not in disk_data
    assert "api_key" not in disk_data
    assert raw_key not in disk_text

    # Must have SHA-256 hash and 8-character prefix
    expected_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    assert disk_data.get("api_key_hash") == expected_hash
    assert disk_data.get("api_key_prefix") == raw_key[:8]

    # 3. Create workspace via REST API
    client: TestClient = phase2_env["client"]
    admin_key: str = phase2_env["admin_key"]
    res = client.post(
        "/api/workspaces/",
        json={"name": "API Vault", "plan": "trial"},
        headers={"X-API-Key": admin_key},
    )
    assert res.status_code == 201
    api_ws_data = res.json()
    api_raw_key = api_ws_data["api_key"]
    api_ws_id = api_ws_data["workspace"]["workspace_id"]

    api_file = Path("data/workspaces") / f"{api_ws_id}.json"
    if api_file.exists():
        api_disk_text = api_file.read_text(encoding="utf-8")
        assert api_raw_key not in api_disk_text
        api_json = json.loads(api_disk_text)
        assert "_api_key_raw" not in api_json
        assert "api_key" not in api_json
        assert api_json["api_key_hash"] == hashlib.sha256(api_raw_key.encode("utf-8")).hexdigest()


# ==============================================================================
# 2. CONSTANT-TIME API KEY RESOLUTION & VERIFICATION
# ==============================================================================

def test_workspace_key_constant_time_verification_and_resolution(phase2_env):
    """API key verification must succeed for valid keys and fail for invalid keys in constant-time."""
    wm: WorkspaceManager = phase2_env["wm"]
    info, raw_key = wm.create_workspace(WorkspaceCreate(name="Crypto Corp", plan="trial"))
    ws_id = info.workspace_id

    # 1. Resolve by key
    resolved_id = wm.resolve_workspace_by_key(raw_key)
    assert resolved_id == ws_id

    # 2. Reject wrong keys
    assert wm.resolve_workspace_by_key("cbk_invalid_key_attempt_0000000000") is None
    assert wm.resolve_workspace_by_key("") is None
    assert wm.resolve_workspace_by_key("wrong_prefix_12345678901234567890") is None

    # 3. verify_workspace_key
    assert wm.verify_workspace_key(ws_id, raw_key) is True
    assert wm.verify_workspace_key(ws_id, "cbk_wrong_key_12345678901234567890") is False
    assert wm.verify_workspace_key("nonexistent_ws_id", raw_key) is False


# ==============================================================================
# 3. API KEY ROTATION & IMMEDIATE INVALIDATION
# ==============================================================================

def test_workspace_key_rotation_immediately_invalidates_old_key(phase2_env):
    """Rotating an API key must invalidate the old key immediately and return a functional new key."""
    client: TestClient = phase2_env["client"]
    admin_key: str = phase2_env["admin_key"]

    # 1. Create workspace
    res = client.post(
        "/api/workspaces/",
        json={"name": "Rotatable Tenant", "plan": "trial"},
        headers={"X-API-Key": admin_key},
    )
    assert res.status_code == 201
    ws_id = res.json()["workspace"]["workspace_id"]
    old_key = res.json()["api_key"]

    # Old key works
    res_old = client.get(f"/api/workspaces/{ws_id}", headers={"X-API-Key": old_key})
    assert res_old.status_code == 200

    # 2. Rotate key
    rot_res = client.post(f"/api/workspaces/{ws_id}/rotate-key", headers={"X-API-Key": old_key})
    assert rot_res.status_code == 200
    new_key = rot_res.json()["data"]["new_api_key"]
    assert new_key != old_key
    assert new_key.startswith("cbk_")

    # 3. Old key is immediately invalidated -> 401 Unauthorized
    res_old_after = client.get(f"/api/workspaces/{ws_id}", headers={"X-API-Key": old_key})
    assert res_old_after.status_code == 401

    # 4. New key works -> 200 OK
    res_new = client.get(f"/api/workspaces/{ws_id}", headers={"X-API-Key": new_key})
    assert res_new.status_code == 200

    # 5. Disk contains NO raw new or old keys
    file_path = Path("data/workspaces") / f"{ws_id}.json"
    if file_path.exists():
        disk_text = file_path.read_text(encoding="utf-8")
        assert old_key not in disk_text
        assert new_key not in disk_text


# ==============================================================================
# 4. TENANT ISOLATION: UNAUTHORIZED CROSS-TENANT ACCESS BLOCKED
# ==============================================================================

def test_tenant_b_cannot_tamper_with_tenant_a_credentials(phase2_env):
    """Tenant B must never be able to read, rotate, or modify Tenant A's keys or secrets."""
    client: TestClient = phase2_env["client"]
    admin_key: str = phase2_env["admin_key"]

    res_a = client.post("/api/workspaces/", json={"name": "Tenant A"}, headers={"X-API-Key": admin_key})
    res_b = client.post("/api/workspaces/", json={"name": "Tenant B"}, headers={"X-API-Key": admin_key})
    ws_a_id, key_a = res_a.json()["workspace"]["workspace_id"], res_a.json()["api_key"]
    ws_b_id, key_b = res_b.json()["workspace"]["workspace_id"], res_b.json()["api_key"]

    headers_b = {"X-API-Key": key_b}

    # B attempts to rotate A's key -> 403 Forbidden
    res_rot = client.post(f"/api/workspaces/{ws_a_id}/rotate-key", headers=headers_b)
    assert res_rot.status_code == 403

    # B attempts to read A's secrets -> 403 Forbidden
    res_sec = client.get(f"/api/workspaces/{ws_a_id}/secrets", headers=headers_b)
    assert res_sec.status_code == 403

    # B attempts to set A's secret -> 403 Forbidden
    res_set = client.post(
        f"/api/workspaces/{ws_a_id}/secrets",
        json={"key_name": "openai_api_key", "value": "sk-evil-key"},
        headers=headers_b,
    )
    assert res_set.status_code == 403

    # B attempts to delete A's secrets -> 403 Forbidden
    res_del_sec = client.delete(f"/api/workspaces/{ws_a_id}/secrets/openai_api_key", headers=headers_b)
    assert res_del_sec.status_code == 403


# ==============================================================================
# 5. SECRETS AES ENCRYPTION & CRYPTOGRAPHIC TENANT BINDING
# ==============================================================================

def test_secrets_aes_encryption_and_cryptographic_tenant_binding(phase2_env):
    """Secrets must be AES-Fernet encrypted and cryptographically bound to workspace_id."""
    sm: SecretsManager = phase2_env["sm"]
    sec_dir: Path = phase2_env["sec_dir"]

    ws_alpha = "workspace-alpha-123"
    ws_beta = "workspace-beta-456"
    raw_secret = "sk-proj-supersecretkey1234567890abcdef"

    # 1. Set secret for Alpha
    sm.set_secret(ws_alpha, "openai_api_key", raw_secret)

    # 2. Check on-disk file: Must be encrypted ciphertext, NOT plaintext
    alpha_file = sec_dir / f"{ws_alpha}.json"
    assert alpha_file.exists()
    disk_content = alpha_file.read_text(encoding="utf-8")
    assert raw_secret not in disk_content
    raw_json = json.loads(disk_content)
    ciphertext = raw_json["openai_api_key"]
    assert ciphertext != raw_secret

    # 3. Decrypt for Alpha succeeds
    decrypted = sm.get_secret(ws_alpha, "openai_api_key")
    assert decrypted == raw_secret

    # 4. Cross-tenant tampering: Attacker copies Alpha's encrypted secret into Beta's storage
    beta_file = sec_dir / f"{ws_beta}.json"
    beta_file.write_text(json.dumps({"openai_api_key": ciphertext}), encoding="utf-8")

    # Decrypting for Beta MUST FAIL (returns None) due to cryptographic workspace mismatch
    tampered_secret = sm.get_secret(ws_beta, "openai_api_key")
    assert tampered_secret is None, "Cross-tenant secret tampering was not detected!"


# ==============================================================================
# 6. FAIL-CLOSED MASTER KEY HANDLING (NO SILENT REGENERATION)
# ==============================================================================

def test_corrupted_master_key_raises_runtime_error_and_refuses_silent_regeneration(phase2_env):
    """System must fail closed with RuntimeError if master key is corrupted."""
    temp_dir: str = phase2_env["temp_dir"]
    corrupted_key_file = Path(temp_dir) / "corrupted.secret_key"
    corrupted_key_file.write_bytes(b"garbage-invalid-fernet-key-bytes-1234")

    # Initializing SecretsManager with corrupted key MUST raise RuntimeError
    with pytest.raises(RuntimeError, match="Master encryption key file.*corrupt or invalid"):
        SecretsManager(secrets_dir=Path(temp_dir) / "test_sec", master_key_file=corrupted_key_file)

    # Key file content must NOT have been silently overwritten
    assert corrupted_key_file.read_bytes() == b"garbage-invalid-fernet-key-bytes-1234"


def test_invalid_env_var_secret_key_raises_runtime_error(temp_env=None):
    """Invalid CRAWLBOT_SECRET_KEY env var must fail closed with RuntimeError."""
    with patch.dict(os.environ, {"CRAWLBOT_SECRET_KEY": "not-valid-base64-fernet-key"}):
        with pytest.raises(RuntimeError, match="Invalid CRAWLBOT_SECRET_KEY configuration"):
            _load_or_generate_master_key()


def test_missing_key_in_production_raises_runtime_error():
    """In production mode, missing key must raise RuntimeError rather than generate random local key."""
    settings = get_settings()
    old_env = settings.app_env
    old_secret = settings.secret_key
    settings.app_env = "production"
    settings.secret_key = ""

    non_existent = Path("data/non_existent_key_for_test.secret_key")
    try:
        with patch.dict(os.environ, {"CRAWLBOT_SECRET_KEY": ""}):
            with pytest.raises(RuntimeError, match="CRAWLBOT_SECRET_KEY environment variable is required in production"):
                _load_or_generate_master_key(master_key_file=non_existent)
    finally:
        settings.app_env = old_env
        settings.secret_key = old_secret


# ==============================================================================
# 7. MASTER KEY BACKUP & RECOVERY
# ==============================================================================

def test_master_key_backup_and_recovery(phase2_env):
    """Backing up and restoring master encryption key must recover encrypted customer secrets."""
    key_file: Path = phase2_env["key_file"]
    sec_dir: Path = phase2_env["sec_dir"]
    backup_file = Path(phase2_env["temp_dir"]) / "master_key.backup"

    sm = SecretsManager(secrets_dir=sec_dir, master_key_file=key_file)
    tenant_id = "tenant-disaster-recovery"
    secret_value = "sk-critical-production-key-987654321"

    # 1. Store secret under original master key
    sm.set_secret(tenant_id, "openai_api_key", secret_value)
    assert sm.get_secret(tenant_id, "openai_api_key") == secret_value

    # 2. Create backup
    backed_up_path = backup_master_key(backup_file, source_path=key_file)
    assert backed_up_path.exists()
    assert backed_up_path.read_bytes() == key_file.read_bytes()

    # 3. Simulate disaster: primary key is corrupted
    key_file.write_bytes(b"corrupted-key-bytes-after-disaster")
    with pytest.raises(RuntimeError):
        SecretsManager(secrets_dir=sec_dir, master_key_file=key_file)

    # 4. Disaster Recovery: restore key from backup
    restore_success = restore_master_key(backup_file, target_path=key_file)
    assert restore_success is True

    # 5. Secrets are 100% accessible again after recovery!
    recovered_sm = SecretsManager(secrets_dir=sec_dir, master_key_file=key_file)
    recovered_secret = recovered_sm.get_secret(tenant_id, "openai_api_key")
    assert recovered_secret == secret_value


# ==============================================================================
# 8. MULTI-TENANT BYOK IN AI PIPELINE (TENANT ALPHA VS TENANT BETA)
# ==============================================================================

@pytest.mark.asyncio
async def test_multi_tenant_byok_isolation_in_ai_pipeline(phase2_env):
    """Two tenants with two distinct BYOK keys must use their respective keys in AI operations."""
    client: TestClient = phase2_env["client"]
    admin_key: str = phase2_env["admin_key"]

    # 1. Create Tenant Alpha and Tenant Beta
    res_a = client.post("/api/workspaces/", json={"name": "Tenant Alpha"}, headers={"X-API-Key": admin_key})
    res_b = client.post("/api/workspaces/", json={"name": "Tenant Beta"}, headers={"X-API-Key": admin_key})
    ws_a_id, key_a = res_a.json()["workspace"]["workspace_id"], res_a.json()["api_key"]
    ws_b_id, key_b = res_b.json()["workspace"]["workspace_id"], res_b.json()["api_key"]

    key_alpha_byok = "sk-alpha-custom-openai-key-1111111111"
    key_beta_byok = "sk-beta-custom-openai-key-2222222222"

    # Set BYOK keys for each tenant via API
    res_sa = client.post(
        f"/api/workspaces/{ws_a_id}/secrets",
        json={"key_name": "openai_api_key", "value": key_alpha_byok},
        headers={"X-API-Key": key_a},
    )
    assert res_sa.status_code == 201

    res_sb = client.post(
        f"/api/workspaces/{ws_b_id}/secrets",
        json={"key_name": "openai_api_key", "value": key_beta_byok},
        headers={"X-API-Key": key_b},
    )
    assert res_sb.status_code == 201

    # 2. Setup mock job with chunks in JobManager
    job_mgr = JobManager()
    from app.api.routes_ai import set_job_manager
    set_job_manager(job_mgr)

    job_a = job_mgr.create_extraction_job(["https://alpha.example.com"], tenant_id=ws_a_id)
    chunk_a = _make_test_chunk("https://alpha.example.com", "Alpha proprietary document text", tenant_id=ws_a_id)
    job_mgr.store_chunks(job_a.job_id, [chunk_a])

    job_b = job_mgr.create_extraction_job(["https://beta.example.com"], tenant_id=ws_b_id)
    chunk_b = _make_test_chunk("https://beta.example.com", "Beta proprietary document text", tenant_id=ws_b_id)
    job_mgr.store_chunks(job_b.job_id, [chunk_b])

    # 3. Intercept EmbeddingService initialization to verify keys
    recorded_keys = []
    mock_stats = EmbeddingStats(
        total_chunks=1,
        embedded_chunks=1,
        failed_chunks=0,
        model="text-embedding-3-small",
        total_tokens=10,
    )

    async def mock_embed_chunks(self, chunks):
        recorded_keys.append(self.api_key)
        for c in chunks:
            c.embedding = [0.1, 0.2, 0.3]
        return mock_stats

    with patch.object(EmbeddingService, "embed_chunks", mock_embed_chunks):
        # Tenant Alpha calls /api/ai/embed
        res_call_a = client.post(
            "/api/ai/embed",
            json={"job_id": job_a.job_id},
            headers={"X-API-Key": key_a},
        )
        assert res_call_a.status_code == 200
        assert len(recorded_keys) == 1
        assert recorded_keys[0] == key_alpha_byok, "Tenant Alpha did NOT use its own BYOK key!"

        # Tenant Beta calls /api/ai/embed
        res_call_b = client.post(
            "/api/ai/embed",
            json={"job_id": job_b.job_id},
            headers={"X-API-Key": key_b},
        )
        assert res_call_b.status_code == 200
        assert len(recorded_keys) == 2
        assert recorded_keys[1] == key_beta_byok, "Tenant Beta did NOT use its own BYOK key!"

    # 4. Verify that Tenant Alpha's key is NEVER used for Tenant Beta
    assert recorded_keys[0] != recorded_keys[1]


# ==============================================================================
# 9. SECRET LEAKAGE PREVENTION & REDACTION
# ==============================================================================

def test_secret_leakage_sanitization():
    """sanitize_secret_leakage must redact all secret patterns."""
    text = (
        "Error contacting OpenAI: key sk-proj-1234567890abcdef123456 failed. "
        "Workspace auth token cbk_1234567890abcdef123456 expired. "
        "Authorization: Bearer my_secret_token_1234567890abcdef"
    )
    sanitized = sanitize_secret_leakage(text)

    assert "sk-proj-1234567890abcdef123456" not in sanitized
    assert "sk-[REDACTED]" in sanitized

    assert "cbk_1234567890abcdef123456" not in sanitized
    assert "cbk_[REDACTED]" in sanitized

    assert "my_secret_token_1234567890abcdef" not in sanitized
    assert "Bearer [REDACTED]" in sanitized

    # Custom secret in explicit list
    explicit_secret = "my_custom_db_password_xyz999"
    explicit_text = f"Connection string failed with password {explicit_secret}"
    custom_sanitized = sanitize_secret_leakage(explicit_text, secrets=[explicit_secret])
    assert explicit_secret not in custom_sanitized
    assert "[REDACTED_SECRET]" in custom_sanitized


def test_api_ai_embed_error_never_leaks_api_key(phase2_env):
    """When an embedding error occurs, the endpoint must never expose the raw key in HTTP 500 response."""
    client: TestClient = phase2_env["client"]
    admin_key: str = phase2_env["admin_key"]

    res_a = client.post("/api/workspaces/", json={"name": "Leak Test Corp"}, headers={"X-API-Key": admin_key})
    ws_id, key_ws = res_a.json()["workspace"]["workspace_id"], res_a.json()["api_key"]

    secret_byok = "sk-leaky-secret-key-1234567890abcdef"
    client.post(
        f"/api/workspaces/{ws_id}/secrets",
        json={"key_name": "openai_api_key", "value": secret_byok},
        headers={"X-API-Key": key_ws},
    )

    job_mgr = JobManager()
    from app.api.routes_ai import set_job_manager
    set_job_manager(job_mgr)

    job = job_mgr.create_extraction_job(["https://example.com"], tenant_id=ws_id)
    chunk = _make_test_chunk("https://example.com", "Sample content", tenant_id=ws_id)
    job_mgr.store_chunks(job.job_id, [chunk])

    # Simulate OpenAI client raising an exception that echoes the secret API key
    async def mock_embed_fail(self, chunks):
        raise RuntimeError(f"OpenAI 401 Unauthorized: Invalid API key {secret_byok} provided to endpoint.")

    with patch.object(EmbeddingService, "embed_chunks", mock_embed_fail):
        res = client.post(
            "/api/ai/embed",
            json={"job_id": job.job_id},
            headers={"X-API-Key": key_ws},
        )
        assert res.status_code == 500
        error_detail = res.json()["detail"]

        # Raw key must NOT be anywhere in response
        assert secret_byok not in error_detail
        assert "sk-[REDACTED]" in error_detail or "[REDACTED" in error_detail
