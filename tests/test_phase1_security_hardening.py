"""Crawlbot Studio — Phase 1 Security Hardening & Authorization Test Suite.

Mandatory Verification Matrix:
1.  B cannot read A's workspace info (403 Forbidden).
2.  B cannot rotate A's API key (403 Forbidden).
3.  B cannot delete A's workspace (403 Forbidden).
4.  B cannot change A's plan (403 Forbidden).
5.  B cannot upgrade own plan without Master Admin (403 Forbidden).
6.  B cannot read, create, or delete A's secrets (403 Forbidden).
7.  B cannot list all workspaces (403 Forbidden).
8.  Neither tenant can access Admin API endpoints (403 Forbidden).
9.  Unauthenticated requests to Admin API fail closed (401 Unauthorized), even when master key is unset.
10. Path traversal attacks (.., ., absolute paths, invalid chars, malformed IDs) are safely neutralized.
11. Authorized Master Admin can perform all operations successfully.
12. Identity spoofing via X-Workspace-Id header without valid credentials is fully blocked.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import is_safe_identifier, validate_path_containment
from app.main import create_app
from app.schemas.workspace import WorkspaceCreate
from app.services.workspace_manager import get_workspace_manager
from app.services.secrets_manager import get_secrets_manager
from app.services.usage_meter import get_usage_meter
from app.services.job_watchdog import get_job_watchdog
from app.jobs.manager import JobManager


@pytest.fixture
def sec_env():
    """Setup isolated test environment with Tenant A, Tenant B, and Admin."""
    settings = get_settings()
    old_key = settings.api_key
    admin_key = "admin-secret-phase1-xyz789"
    settings.api_key = admin_key

    app = create_app()
    client = TestClient(app)

    admin_headers = {"X-API-Key": admin_key}

    # 1. Admin creates Tenant A
    res_a = client.post(
        "/api/workspaces/",
        json={"name": "Tenant Alpha Corp", "plan": "trial"},
        headers=admin_headers,
    )
    assert res_a.status_code == 201
    ws_a_id = res_a.json()["workspace"]["workspace_id"]
    ws_a_key = res_a.json()["api_key"]

    # 2. Admin creates Tenant B
    res_b = client.post(
        "/api/workspaces/",
        json={"name": "Tenant Beta LLC", "plan": "trial"},
        headers=admin_headers,
    )
    assert res_b.status_code == 201
    ws_b_id = res_b.json()["workspace"]["workspace_id"]
    ws_b_key = res_b.json()["api_key"]

    # Tenant headers
    headers_a = {"X-API-Key": ws_a_key}
    headers_b = {"X-API-Key": ws_b_key}

    context = {
        "client": client,
        "admin_key": admin_key,
        "admin_headers": admin_headers,
        "ws_a_id": ws_a_id,
        "ws_a_key": ws_a_key,
        "headers_a": headers_a,
        "ws_b_id": ws_b_id,
        "ws_b_key": ws_b_key,
        "headers_b": headers_b,
    }

    yield context

    # Teardown
    try:
        client.delete(f"/api/workspaces/{ws_a_id}", headers=admin_headers)
    except Exception:
        pass
    try:
        client.delete(f"/api/workspaces/{ws_b_id}", headers=admin_headers)
    except Exception:
        pass
    settings.api_key = old_key


# ==============================================================================
# 1. WORKSPACE READ ISOLATION
# ==============================================================================

def test_tenant_b_cannot_read_tenant_a_info(sec_env):
    """Tenant B must NOT be able to read Tenant A's workspace info."""
    client = sec_env["client"]
    ws_a_id = sec_env["ws_a_id"]
    headers_a = sec_env["headers_a"]
    headers_b = sec_env["headers_b"]

    # Tenant B tries to read Tenant A -> 403 Forbidden
    res_b = client.get(f"/api/workspaces/{ws_a_id}", headers=headers_b)
    assert res_b.status_code == 403

    # Tenant A reading own info -> 200 OK
    res_a = client.get(f"/api/workspaces/{ws_a_id}", headers=headers_a)
    assert res_a.status_code == 200
    assert res_a.json()["workspace"]["name"] == "Tenant Alpha Corp"


# ==============================================================================
# 2. KEY ROTATION ISOLATION
# ==============================================================================

def test_tenant_b_cannot_rotate_tenant_a_key(sec_env):
    """Tenant B must NOT be able to rotate Tenant A's API key."""
    client = sec_env["client"]
    ws_a_id = sec_env["ws_a_id"]
    headers_b = sec_env["headers_b"]
    headers_a = sec_env["headers_a"]

    # Tenant B tries to rotate A's key -> 403 Forbidden
    res = client.post(f"/api/workspaces/{ws_a_id}/rotate-key", headers=headers_b)
    assert res.status_code == 403

    # Tenant A's original key must still be valid
    verify_res = client.get(f"/api/workspaces/{ws_a_id}", headers=headers_a)
    assert verify_res.status_code == 200


# ==============================================================================
# 3. WORKSPACE DELETION ISOLATION
# ==============================================================================

def test_tenant_b_cannot_delete_tenant_a_workspace(sec_env):
    """Tenant B must NOT be able to delete Tenant A's workspace."""
    client = sec_env["client"]
    ws_a_id = sec_env["ws_a_id"]
    headers_b = sec_env["headers_b"]
    headers_a = sec_env["headers_a"]

    # Tenant B tries to delete A -> 403 Forbidden
    res = client.delete(f"/api/workspaces/{ws_a_id}", headers=headers_b)
    assert res.status_code == 403

    # Workspace A must still exist and be accessible by Tenant A
    verify_res = client.get(f"/api/workspaces/{ws_a_id}", headers=headers_a)
    assert verify_res.status_code == 200


# ==============================================================================
# 4. PLAN CHANGE ISOLATION (CROSS-TENANT)
# ==============================================================================

def test_tenant_b_cannot_change_tenant_a_plan(sec_env):
    """Tenant B must NOT be able to modify Tenant A's plan."""
    client = sec_env["client"]
    ws_a_id = sec_env["ws_a_id"]
    headers_b = sec_env["headers_b"]

    res = client.put(
        f"/api/workspaces/{ws_a_id}/plan",
        json={"plan": "professional"},
        headers=headers_b,
    )
    assert res.status_code == 403


# ==============================================================================
# 5. PLAN SELF-UPGRADE PROTECTION (TENANTS CANNOT SELF-UPGRADE)
# ==============================================================================

def test_tenant_cannot_self_upgrade_plan_without_admin(sec_env):
    """Tenants must NOT be able to upgrade their own plan without Admin rights."""
    client = sec_env["client"]
    ws_b_id = sec_env["ws_b_id"]
    headers_b = sec_env["headers_b"]

    # Tenant B attempts to self-upgrade to professional -> 403 Forbidden
    res = client.put(
        f"/api/workspaces/{ws_b_id}/plan",
        json={"plan": "professional"},
        headers=headers_b,
    )
    assert res.status_code == 403

    # Plan remains trial
    info = client.get(f"/api/workspaces/{ws_b_id}", headers=headers_b).json()
    assert info["workspace"]["plan"] == "trial"


# ==============================================================================
# 6. SECRETS ISOLATION & BYOK
# ==============================================================================

def test_tenant_b_cannot_view_or_modify_tenant_a_secrets(sec_env):
    """Tenant B must NOT be able to view, set, or delete Tenant A's secrets."""
    client = sec_env["client"]
    ws_a_id = sec_env["ws_a_id"]
    headers_a = sec_env["headers_a"]
    headers_b = sec_env["headers_b"]

    # Tenant A sets a secret
    set_res = client.post(
        f"/api/workspaces/{ws_a_id}/secrets",
        json={"key_name": "openai_api_key", "value": "sk-proj-alpha-secret-key-1234567890"},
        headers=headers_a,
    )
    assert set_res.status_code == 201

    # Tenant B tries to list Tenant A's secrets -> 403 Forbidden
    res_list = client.get(f"/api/workspaces/{ws_a_id}/secrets", headers=headers_b)
    assert res_list.status_code == 403

    # Tenant B tries to overwrite Tenant A's secret -> 403 Forbidden
    res_overwrite = client.post(
        f"/api/workspaces/{ws_a_id}/secrets",
        json={"key_name": "openai_api_key", "value": "sk-proj-malicious-key"},
        headers=headers_b,
    )
    assert res_overwrite.status_code == 403

    # Tenant B tries to delete Tenant A's secret -> 403 Forbidden
    res_del = client.delete(
        f"/api/workspaces/{ws_a_id}/secrets/openai_api_key",
        headers=headers_b,
    )
    assert res_del.status_code == 403


# ==============================================================================
# 7. WORKSPACE ENUMERATION PROTECTION
# ==============================================================================

def test_tenant_cannot_list_all_workspaces(sec_env):
    """Regular tenant API keys must NOT be able to list all workspaces."""
    client = sec_env["client"]
    headers_a = sec_env["headers_a"]
    headers_b = sec_env["headers_b"]

    res_a = client.get("/api/workspaces/", headers=headers_a)
    assert res_a.status_code == 403

    res_b = client.get("/api/workspaces/", headers=headers_b)
    assert res_b.status_code == 403


# ==============================================================================
# 8. ADMIN API ACCESS CONTROL (TENANTS BLOCKED)
# ==============================================================================

def test_tenants_cannot_access_admin_api(sec_env):
    """Standard workspace API keys must NEVER access /api/admin/* endpoints."""
    client = sec_env["client"]
    headers_a = sec_env["headers_a"]
    headers_b = sec_env["headers_b"]

    admin_endpoints = [
        ("GET", "/api/admin/health"),
        ("GET", "/api/admin/usage-summary"),
        ("GET", "/api/admin/watchdog/status"),
        ("POST", "/api/admin/watchdog/run"),
        ("POST", "/api/admin/cleanup"),
    ]

    for method, endpoint in admin_endpoints:
        # Tenant A
        res_a = client.request(method, endpoint, headers=headers_a)
        assert res_a.status_code == 403, f"Expected 403 on {method} {endpoint}, got {res_a.status_code}"

        # Tenant B
        res_b = client.request(method, endpoint, headers=headers_b)
        assert res_b.status_code == 403, f"Expected 403 on {method} {endpoint}, got {res_b.status_code}"


# ==============================================================================
# 9. FAIL-CLOSED ADMIN API AUTHENTICATION
# ==============================================================================

def test_unauthenticated_request_to_admin_fails_closed(sec_env):
    """Admin API must fail closed: 401 when key is missing, invalid, or unconfigured."""
    client = sec_env["client"]
    settings = get_settings()

    # Case 1: Configured key exists, but caller sends NO credentials -> 401
    res_no_auth = client.get("/api/admin/health")
    assert res_no_auth.status_code == 401

    # Case 2: Caller sends invalid credentials -> 401
    res_bad_auth = client.get("/api/admin/health", headers={"X-API-Key": "wrong-secret-key"})
    assert res_bad_auth.status_code == 401

    # Case 3: CRAWLBOT_API_KEY is unset/empty -> FAIL CLOSED (401, NOT public 200!)
    old_key = settings.api_key
    try:
        settings.api_key = None
        res_fail_closed = client.get("/api/admin/health")
        assert res_fail_closed.status_code == 401, f"Expected fail-closed 401, got {res_fail_closed.status_code}"

        res_fail_closed_with_key = client.get("/api/admin/health", headers={"X-API-Key": "random-token"})
        assert res_fail_closed_with_key.status_code == 401
    finally:
        settings.api_key = old_key


# ==============================================================================
# 10. PATH TRAVERSAL NEUTRALIZATION
# ==============================================================================

def test_path_traversal_payloads_safely_neutralized(sec_env):
    """Path traversal payloads (.., ., absolute paths, invalid chars) are neutralized across APIs and services."""
    client = sec_env["client"]
    admin_headers = sec_env["admin_headers"]
    headers_a = sec_env["headers_a"]
    ws_a_id = sec_env["ws_a_id"]

    # 1. API Route Level Neutralization
    malicious_ids = [
        "%2e%2e",
        "..%2F..",
        "invalid@id",
        "bad#workspace$id",
        "a" * 128,  # Excessive length
    ]

    for payload in malicious_ids:
        # GET workspace with malicious ID
        res_get = client.get(f"/api/workspaces/{payload}", headers=admin_headers)
        assert res_get.status_code in (400, 404, 405, 422), f"GET failed to neutralize {payload}: {res_get.status_code}"

        # DELETE workspace with malicious ID
        res_del = client.delete(f"/api/workspaces/{payload}", headers=admin_headers)
        assert res_del.status_code in (400, 404, 405, 422), f"DELETE failed to neutralize {payload}: {res_del.status_code}"

        # Rotate key with malicious ID
        res_rot = client.post(f"/api/workspaces/{payload}/rotate-key", headers=admin_headers)
        assert res_rot.status_code in (400, 404, 405, 422), f"Rotate failed to neutralize {payload}: {res_rot.status_code}"

        # Job get with malicious ID
        res_job = client.get(f"/api/jobs/{payload}", headers=admin_headers)
        assert res_job.status_code in (400, 404, 405, 422), f"Job get failed to neutralize {payload}: {res_job.status_code}"

    # Secret key name validation
    malicious_secret_keys = ["invalid@key", "bad#name", "a" * 128]
    for key_payload in malicious_secret_keys:
        res_sec_del = client.delete(
            f"/api/workspaces/{ws_a_id}/secrets/{key_payload}",
            headers=headers_a,
        )
        assert res_sec_del.status_code in (400, 404, 422)

    # 2. Service-Level Direct Containment Verification
    wm = get_workspace_manager()
    sm = get_secrets_manager()
    um = get_usage_meter()
    wd = get_job_watchdog()
    jm = JobManager()

    raw_traversals = [
        "..",
        ".",
        "../../etc/passwd",
        "..\\..\\windows\\win.ini",
        "C:\\Windows\\System32",
        "/etc/shadow",
        "null\x00byte",
    ]

    for raw in raw_traversals:
        # Validator function check
        assert is_safe_identifier(raw) is False

        # Workspace manager
        assert wm.get_workspace(raw) is None
        assert wm.delete_workspace(raw) is False
        assert wm.update_plan(raw, "developer") is None

        # Secrets manager
        assert sm.get_secret(raw, "key") is None
        assert sm.delete_secret(raw, "key") is False
        assert sm.list_secrets(raw) == []

        # Job watchdog
        assert wd.restore_jobs(raw) == []

        # Job manager
        assert jm.get_job(raw) is None
        assert jm.delete_job(raw) is False
        assert jm.get_chunks(raw) == []


# ==============================================================================
# 11. AUTHORIZED MASTER ADMIN CAPABILITIES
# ==============================================================================

def test_authorized_admin_can_perform_all_operations(sec_env):
    """Authorized Master Admin can perform all management and operational tasks."""
    client = sec_env["client"]
    admin_headers = sec_env["admin_headers"]
    ws_a_id = sec_env["ws_a_id"]

    # 1. Admin lists all workspaces -> 200 OK
    list_res = client.get("/api/workspaces/", headers=admin_headers)
    assert list_res.status_code == 200
    workspaces = list_res.json()["workspaces"]
    assert len(workspaces) >= 2

    # 2. Admin inspects workspace A -> 200 OK
    get_res = client.get(f"/api/workspaces/{ws_a_id}", headers=admin_headers)
    assert get_res.status_code == 200
    assert get_res.json()["workspace"]["name"] == "Tenant Alpha Corp"

    # 3. Admin upgrades workspace A plan -> 200 OK
    plan_res = client.put(
        f"/api/workspaces/{ws_a_id}/plan",
        json={"plan": "professional"},
        headers=admin_headers,
    )
    assert plan_res.status_code == 200
    assert plan_res.json()["workspace"]["plan"] == "professional"

    # 4. Admin queries quota -> 200 OK
    quota_res = client.get(f"/api/workspaces/{ws_a_id}/quota", headers=admin_headers)
    assert quota_res.status_code == 200
    assert quota_res.json()["quota"]["plan"] == "professional"

    # 5. Admin accesses system health -> 200 OK
    health_res = client.get("/api/admin/health", headers=admin_headers)
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "ok"

    # 6. Admin accesses aggregate usage -> 200 OK
    usage_res = client.get("/api/admin/usage-summary", headers=admin_headers)
    assert usage_res.status_code == 200
    assert "workspaces" in usage_res.json()

    # 7. Admin rotates key -> 200 OK
    rot_res = client.post(f"/api/workspaces/{ws_a_id}/rotate-key", headers=admin_headers)
    assert rot_res.status_code == 200
    assert "new_api_key" in rot_res.json()["data"]


# ==============================================================================
# 12. IDENTITY SPOOFING VIA X-WORKSPACE-ID HEADER BLOCKED
# ==============================================================================

def test_header_workspace_id_spoofing_blocked(sec_env):
    """Untrusted callers cannot spoof tenant identity via X-Workspace-Id header."""
    client = sec_env["client"]
    ws_a_id = sec_env["ws_a_id"]

    spoofed_headers = {"X-Workspace-Id": ws_a_id}

    # Reading workspace info with spoofed header but no key -> 401 Unauthorized
    res_get = client.get(f"/api/workspaces/{ws_a_id}", headers=spoofed_headers)
    assert res_get.status_code == 401

    # Deleting workspace with spoofed header -> 401 Unauthorized
    res_del = client.delete(f"/api/workspaces/{ws_a_id}", headers=spoofed_headers)
    assert res_del.status_code == 401

    # Reading secrets with spoofed header -> 401 Unauthorized
    res_sec = client.get(f"/api/workspaces/{ws_a_id}/secrets", headers=spoofed_headers)
    assert res_sec.status_code == 401
