"""Unit and Integration Tests for Phase 5: Production SaaS Platform,
Multi-Tenant Isolation, Usage Metering, Quota Enforcement, BYOK & Operations.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import SlidingWindowRateLimiter
from app.jobs.manager import JobManager
from app.jobs.models import JobInfo, JobState, JobType
from app.main import create_app
from app.schemas.workspace import WorkspaceCreate
from app.services.job_watchdog import JobWatchdog
from app.services.quota_enforcer import QuotaEnforcer
from app.services.secrets_manager import SecretsManager
from app.services.usage_meter import UsageMeter
from app.services.workspace_manager import WorkspaceManager, get_all_plans, get_plan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_env_dir():
    """Create isolated temporary base directory for tests."""
    tmp = tempfile.mkdtemp(prefix="crawlbot_saas_test_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def mock_app_and_client():
    """Create fresh app and TestClient."""
    app = create_app()
    client = TestClient(app)
    return app, client


# ==============================================================================
# 1. PLANS & WORKSPACE LIFECYCLE TESTS
# ==============================================================================

def test_plan_configuration_loaded():
    """Verify that plans are loaded dynamically from plans.json and not hardcoded."""
    plans = get_all_plans()
    assert len(plans) >= 3
    plan_names = [p.name for p in plans]
    assert "trial" in plan_names
    assert "developer" in plan_names
    assert "professional" in plan_names

    trial = get_plan("trial")
    assert trial.max_pages_per_month == 100
    assert trial.max_file_mb == 5.0

    dev = get_plan("developer")
    assert dev.max_pages_per_month == 2000
    assert dev.allow_byok is True


def test_workspace_crud_lifecycle(temp_env_dir):
    """Test full workspace CRUD: create, read, list, key rotation, and deletion."""
    ws_dir = os.path.join(temp_env_dir, "workspaces")
    wm = WorkspaceManager(workspace_dir=ws_dir)

    # 1. Create workspace
    req = WorkspaceCreate(name="Acme Corp", plan="developer", description="Primary Workspace")
    info, raw_key = wm.create_workspace(req)
    assert info.name == "Acme Corp"
    assert info.plan == "developer"
    assert raw_key.startswith("cbk_")
    assert info.api_key_prefix == raw_key[:8]

    # 2. Key resolution
    resolved_id = wm.resolve_workspace_by_key(raw_key)
    assert resolved_id == info.workspace_id

    # 3. Read workspace
    fetched = wm.get_workspace(info.workspace_id)
    assert fetched is not None
    assert fetched.name == "Acme Corp"

    # 4. List workspaces
    all_ws = wm.list_workspaces()
    assert any(w.workspace_id == info.workspace_id for w in all_ws)

    # 5. Rotate API key
    rotate_res = wm.rotate_api_key(info.workspace_id)
    assert rotate_res is not None
    updated_info, new_raw_key = rotate_res
    assert new_raw_key.startswith("cbk_")
    assert new_raw_key != raw_key

    # Old key must no longer resolve; new key must resolve
    assert wm.resolve_workspace_by_key(raw_key) is None
    assert wm.resolve_workspace_by_key(new_raw_key) == info.workspace_id

    # 6. Change plan
    upgraded = wm.update_plan(info.workspace_id, "professional")
    assert upgraded is not None
    assert upgraded.plan == "professional"

    # 7. Delete workspace
    deleted = wm.delete_workspace(info.workspace_id)
    assert deleted is True
    assert wm.get_workspace(info.workspace_id) is None
    assert wm.resolve_workspace_by_key(new_raw_key) is None


# ==============================================================================
# 2. MULTI-TENANT ISOLATION TESTS
# ==============================================================================

def test_job_manager_multi_tenant_isolation():
    """Verify that jobs belonging to Tenant A cannot be seen, fetched, or cancelled by Tenant B."""
    manager = JobManager()
    tenant_a = "tenant-aaa-" + uuid.uuid4().hex[:6]
    tenant_b = "tenant-bbb-" + uuid.uuid4().hex[:6]

    # Tenant A creates a discovery job and an extraction job
    job_a1 = manager.create_discovery_job({
        "root_url": "https://example.com/a",
        "tenant_id": tenant_a,
    })
    job_a2 = manager.create_extraction_job(
        urls=["https://example.com/a/p1"],
        config={"tenant_id": tenant_a},
    )

    # Tenant B creates an extraction job
    job_b = manager.create_extraction_job(
        urls=["https://example.com/b/p1"],
        config={"tenant_id": tenant_b},
    )

    # 1. Listing jobs with tenant filter
    jobs_a = manager.list_jobs(tenant_id=tenant_a)
    jobs_b = manager.list_jobs(tenant_id=tenant_b)
    assert len(jobs_a) == 2
    assert len(jobs_b) == 1
    assert job_b.job_id not in [j.job_id for j in jobs_a]
    assert job_a1.job_id not in [j.job_id for j in jobs_b]

    # 2. Tenant B attempting to read Tenant A's job directly
    read_by_b = manager.get_job(job_a1.job_id, tenant_id=tenant_b)
    assert read_by_b is None  # Isolated!

    # Tenant A can read own job
    read_by_a = manager.get_job(job_a1.job_id, tenant_id=tenant_a)
    assert read_by_a is not None
    assert read_by_a.job_id == job_a1.job_id

    # 3. Tenant B attempting to cancel Tenant A's job
    cancel_by_b = manager.cancel_job(job_a1.job_id, tenant_id=tenant_b)
    assert cancel_by_b is False

    # 4. Tenant B attempting to delete Tenant A's job
    delete_by_b = manager.delete_job(job_a1.job_id, tenant_id=tenant_b)
    assert delete_by_b is False

    # 5. Tenant A deletes own job
    delete_by_a = manager.delete_job(job_a1.job_id, tenant_id=tenant_a)
    assert delete_by_a is True
    assert manager.get_job(job_a1.job_id) is None


def test_api_routes_multi_tenant_isolation(mock_app_and_client):
    """Integration test verifying tenant isolation across HTTP routes."""
    app, client = mock_app_and_client
    tenant_a = "tenant-alpha-" + uuid.uuid4().hex[:6]
    tenant_b = "tenant-beta-" + uuid.uuid4().hex[:6]

    # Create job for tenant A via header
    resp_a = client.post(
        "/api/extraction/start",
        json={"urls": ["https://example.com/doc1"]},
        headers={"X-Workspace-Id": tenant_a},
    )
    assert resp_a.status_code == 200
    job_id_a = resp_a.json()["data"]["job_id"]

    # Tenant B tries to get Tenant A's job status -> 404
    resp_b_get = client.get(
        f"/api/jobs/{job_id_a}",
        headers={"X-Workspace-Id": tenant_b},
    )
    assert resp_b_get.status_code == 404

    # Tenant A gets own job status -> 200
    resp_a_get = client.get(
        f"/api/jobs/{job_id_a}",
        headers={"X-Workspace-Id": tenant_a},
    )
    assert resp_a_get.status_code == 200
    assert resp_a_get.json()["job_id"] == job_id_a

    # Tenant B lists jobs -> should not see Tenant A's job
    resp_b_list = client.get(
        "/api/jobs/list",
        headers={"X-Workspace-Id": tenant_b},
    )
    assert resp_b_list.status_code == 200
    b_job_ids = [j["job_id"] for j in resp_b_list.json()]
    assert job_id_a not in b_job_ids


# ==============================================================================
# 3. USAGE METERING & QUOTA ENFORCEMENT TESTS
# ==============================================================================

def test_usage_meter_and_aggregation(temp_env_dir):
    """Test append-only event recording and monthly aggregation."""
    usage_dir = os.path.join(temp_env_dir, "usage")
    meter = UsageMeter(usage_dir=usage_dir)
    wid = "ws-meter-test"

    # Record various usage events
    meter.record(wid, "pages_crawled", 15, job_id="job-1")
    meter.record(wid, "pages_crawled", 25, job_id="job-2")
    meter.record(wid, "files_processed", 3, job_id="file-1")
    meter.record(wid, "chunks_created", 120, job_id="job-1")
    meter.record(wid, "embeddings_generated", 120, job_id="job-1")
    meter.record(wid, "llm_tokens", 4500, metadata={"model": "gpt-4o-mini"})
    meter.record(wid, "job_created", 2)

    # Current month summary
    summary = meter.get_current_month(wid)
    assert summary.pages_crawled == 40
    assert summary.files_processed == 3
    assert summary.chunks_created == 120
    assert summary.embeddings_generated == 120
    assert summary.llm_tokens_used == 4500
    assert summary.job_count == 2
    assert summary.events_count == 7

    # Metric total helper
    assert meter.get_metric_total(wid, "pages_crawled") == 40.0
    assert meter.get_metric_total(wid, "llm_tokens") == 4500.0

    # Full report
    report = meter.get_report(wid, months=3)
    assert report.workspace_id == wid
    assert report.current_period.pages_crawled == 40


def test_quota_enforcer_limits(temp_env_dir):
    """Test that QuotaEnforcer blocks operations exceeding plan allowances."""
    ws_dir = os.path.join(temp_env_dir, "workspaces")
    usage_dir = os.path.join(temp_env_dir, "usage")
    wm = WorkspaceManager(workspace_dir=ws_dir)
    meter = UsageMeter(usage_dir=usage_dir)

    # Create workspace with trial plan (limit: 100 pages, 5MB file, 1 concurrent)
    req = WorkspaceCreate(name="Quota Test", plan="trial")
    info, _ = wm.create_workspace(req)
    wid = info.workspace_id

    # Inject into singletons
    import app.services.workspace_manager as wm_mod
    import app.services.usage_meter as um_mod
    old_wm, old_um = wm_mod._instance, um_mod._instance
    wm_mod._instance, um_mod._instance = wm, meter

    try:
        enforcer = QuotaEnforcer()

        # Under limit: 60 pages allowed
        enforcer.check_pages(wid, count=60)

        # Simulate 80 pages consumed
        meter.record(wid, "pages_crawled", 80)

        # 15 more pages -> 95 <= 100: allowed
        enforcer.check_pages(wid, count=15)

        # 30 more pages -> 110 > 100: BLOCKED with ValueError
        with pytest.raises(ValueError, match="Page quota exceeded"):
            enforcer.check_pages(wid, count=30)

        # File size limit (trial max: 5.0 MB)
        # 3 MB: allowed
        enforcer.check_file_size(wid, file_bytes=3 * 1024 * 1024)
        # 8 MB: BLOCKED
        with pytest.raises(ValueError, match="exceeds plan limit"):
            enforcer.check_file_size(wid, file_bytes=8 * 1024 * 1024)

        # Concurrent job limit (trial max: 1)
        enforcer.check_concurrent_jobs(wid, active_count=0)
        with pytest.raises(ValueError, match="Concurrent job limit reached"):
            enforcer.check_concurrent_jobs(wid, active_count=1)

        # Quota status report check
        status = enforcer.get_quota_status(wid)
        assert status.workspace_id == wid
        assert status.plan == "trial"
        assert status.metrics["pages_crawled"]["used"] == 80
        assert status.metrics["pages_crawled"]["remaining"] == 20
        assert "pages_crawled" in status.near_limit  # 80% used triggers near_limit

    finally:
        wm_mod._instance, um_mod._instance = old_wm, old_um


# ==============================================================================
# 4. SECRETS MANAGEMENT & BYOK (BRING YOUR OWN KEY)
# ==============================================================================

def test_secrets_manager_encryption_and_masking(temp_env_dir):
    """Test AES-encrypted secret storage, masking in API display, and deletion."""
    sec_dir = os.path.join(temp_env_dir, "secrets")
    sm = SecretsManager(secrets_dir=sec_dir)
    wid = "ws-secret-test"

    raw_key = "sk-proj-abc123xyz789SECRETKEY000000000"

    # Store secret
    sm.set_secret(wid, "openai_api_key", raw_key)
    assert sm.has_secret(wid, "openai_api_key") is True

    # Decrypt: exact match
    decrypted = sm.get_secret(wid, "openai_api_key")
    assert decrypted == raw_key

    # Masked representation: never shows full key
    masked = sm.get_secret_masked(wid, "openai_api_key")
    assert masked.startswith("sk-p")
    assert masked.endswith("0000")
    assert "SECRETKEY" not in masked
    assert "*" in masked

    # List secrets: values must be masked
    secrets_list = sm.list_secrets(wid)
    assert len(secrets_list) == 1
    assert secrets_list[0]["key_name"] == "openai_api_key"
    assert "SECRETKEY" not in secrets_list[0]["masked_value"]

    # Delete secret
    deleted = sm.delete_secret(wid, "openai_api_key")
    assert deleted is True
    assert sm.has_secret(wid, "openai_api_key") is False
    assert sm.get_secret(wid, "openai_api_key") is None


# ==============================================================================
# 5. JOB WATCHDOG & RELIABILITY
# ==============================================================================

def test_job_watchdog_detects_stuck_jobs():
    """Verify watchdog detects and cancels jobs exceeding max runtime."""
    manager = JobManager()
    watchdog = JobWatchdog(max_runtime_minutes=30)

    # Job 1: Running for 5 minutes (healthy)
    healthy_job = manager.create_extraction_job(["https://example.com/1"], {})
    healthy_job.mark_running()

    # Job 2: Running for 45 minutes (stuck)
    stuck_job = manager.create_extraction_job(["https://example.com/2"], {})
    stuck_job.mark_running()
    from datetime import datetime, timedelta, timezone
    stuck_job.started_at = datetime.now(timezone.utc) - timedelta(minutes=45)

    cancelled = watchdog.check_stuck_jobs(manager)
    assert stuck_job.job_id in cancelled
    assert healthy_job.job_id not in cancelled
    assert stuck_job.state == JobState.CANCELLED
    assert any("watchdog" in err for err in stuck_job.errors)


def test_job_persistence_and_restore(temp_env_dir):
    """Test job state disk serialization for server restart recovery."""
    watchdog = JobWatchdog()
    watchdog._jobs_dir = tempfile.Path(os.path.join(temp_env_dir, "jobs")) if hasattr(tempfile, "Path") else None
    from pathlib import Path
    watchdog._jobs_dir = Path(temp_env_dir) / "jobs"
    watchdog._jobs_dir.mkdir(parents=True, exist_ok=True)

    job = JobInfo(
        job_type=JobType.EXTRACTION,
        state=JobState.COMPLETED,
        total=5,
        completed=5,
        tenant_id="tenant-persist",
    )

    watchdog.persist_job("tenant-persist", job)

    restored = watchdog.restore_jobs("tenant-persist")
    assert len(restored) == 1
    assert restored[0]["job_id"] == job.job_id
    assert restored[0]["completed"] == 5


# ==============================================================================
# 6. RATE LIMITING & SECURITY TESTS
# ==============================================================================

def test_sliding_window_rate_limiter():
    """Test that SlidingWindowRateLimiter throttles requests exceeding capacity."""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=2.0)
    key = "client-rate-test-1"

    # First 5 requests allowed
    for _ in range(5):
        allowed, _ = limiter.is_allowed(key)
        assert allowed is True

    # 6th request rejected
    allowed, retry_after = limiter.is_allowed(key)
    assert allowed is False
    assert retry_after > 0

    # Reset allows again
    limiter.reset(key)
    allowed, _ = limiter.is_allowed(key)
    assert allowed is True


def test_workspace_api_key_authentication(mock_app_and_client):
    """Verify that a workspace API key authenticates against protected endpoints."""
    app, client = mock_app_and_client
    settings = get_settings()

    # Create workspace through WorkspaceManager
    from app.services.workspace_manager import get_workspace_manager
    wm = get_workspace_manager()
    info, raw_key = wm.create_workspace(WorkspaceCreate(name="Auth Test Corp", plan="developer"))

    try:
        settings.api_key = "master-secret-key-xyz"

        # 1. Unauthenticated request to protected route -> 401
        res_unauth = client.get("/api/jobs/list")
        assert res_unauth.status_code == 401

        # 2. Authenticated using workspace API key via X-API-Key -> 200
        res_ws_key = client.get("/api/jobs/list", headers={"X-API-Key": raw_key})
        assert res_ws_key.status_code == 200

        # 3. Authenticated using workspace API key via Bearer token -> 200
        res_bearer = client.get("/api/v1/jobs/list", headers={"Authorization": f"Bearer {raw_key}"})
        assert res_bearer.status_code == 200

    finally:
        settings.api_key = None
        wm.delete_workspace(info.workspace_id)


# ==============================================================================
# 7. WORKSPACE REST API ENDPOINTS
# ==============================================================================

def test_workspace_rest_api_endpoints(mock_app_and_client):
    """Test /api/workspaces/ endpoints via HTTP."""
    _, client = mock_app_and_client

    # 1. List available plans
    plans_res = client.get("/api/workspaces/plans")
    assert plans_res.status_code == 200
    plans = plans_res.json()["plans"]
    assert len(plans) >= 3

    # 2. Create workspace via API
    create_res = client.post(
        "/api/workspaces/",
        json={"name": "Test Workspace via API", "plan": "developer", "description": "API Test"},
    )
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert created_data["success"] is True
    ws_id = created_data["workspace"]["workspace_id"]
    api_key = created_data["api_key"]
    assert api_key.startswith("cbk_")

    ws_headers = {"X-API-Key": api_key}
    new_key = None
    try:
        # 3. Get workspace info
        get_res = client.get(f"/api/workspaces/{ws_id}", headers=ws_headers)
        assert get_res.status_code == 200
        assert get_res.json()["workspace"]["name"] == "Test Workspace via API"

        # 4. Get quota status
        quota_res = client.get(f"/api/workspaces/{ws_id}/quota", headers=ws_headers)
        assert quota_res.status_code == 200
        assert quota_res.json()["quota"]["plan"] == "developer"

        # 5. Get usage report
        usage_res = client.get(f"/api/workspaces/{ws_id}/usage", headers=ws_headers)
        assert usage_res.status_code == 200

        # 6. Store secret (BYOK)
        sec_res = client.post(
            f"/api/workspaces/{ws_id}/secrets",
            json={"key_name": "openai_api_key", "value": "sk-byok-test-key-123456789"},
            headers=ws_headers,
        )
        assert sec_res.status_code == 201

        # 7. List secrets (masked)
        sec_list = client.get(f"/api/workspaces/{ws_id}/secrets", headers=ws_headers)
        assert sec_list.status_code == 200
        secrets = sec_list.json()["secrets"]
        assert len(secrets) == 1
        assert "123456789" not in secrets[0]["masked_value"]

        # 8. Rotate API key
        rot_res = client.post(f"/api/workspaces/{ws_id}/rotate-key", headers=ws_headers)
        assert rot_res.status_code == 200
        new_key = rot_res.json()["data"]["new_api_key"]
        assert new_key != api_key

    finally:
        # 9. Delete workspace
        del_headers = {"X-API-Key": new_key if new_key else api_key}
        del_res = client.delete(f"/api/workspaces/{ws_id}", headers=del_headers)
        assert del_res.status_code == 200
        assert client.get(f"/api/workspaces/{ws_id}", headers=del_headers).status_code in (401, 404)


# ==============================================================================
# 8. ADMIN & OPERATIONS ENDPOINTS
# ==============================================================================

def test_admin_endpoints(mock_app_and_client):
    """Test /api/admin/ endpoints."""
    _, client = mock_app_and_client
    settings = get_settings()
    old_key = settings.api_key
    try:
        settings.api_key = "admin-secret-key-phase5"
        admin_headers = {"X-API-Key": "admin-secret-key-phase5"}

        # 1. Admin health
        health_res = client.get("/api/admin/health", headers=admin_headers)
        assert health_res.status_code == 200
        data = health_res.json()
        assert data["status"] == "ok"
        assert "disk_usage" in data
        assert "workspaces_count" in data

        # 2. Admin usage summary
        usage_res = client.get("/api/admin/usage-summary", headers=admin_headers)
        assert usage_res.status_code == 200
        assert "workspaces" in usage_res.json()

        # 3. Watchdog status
        wd_res = client.get("/api/admin/watchdog/status", headers=admin_headers)
        assert wd_res.status_code == 200
        assert wd_res.json()["max_runtime_minutes"] > 0

        # 4. Trigger watchdog scan
        run_res = client.post("/api/admin/watchdog/run", headers=admin_headers)
        assert run_res.status_code == 200
        assert run_res.json()["success"] is True

        # 5. Cleanup expired artifacts (safe dry-run on empty)
        cleanup_res = client.post("/api/admin/cleanup?max_history_days=30", headers=admin_headers)
        assert cleanup_res.status_code == 200
        assert cleanup_res.json()["success"] is True
    finally:
        settings.api_key = old_key
