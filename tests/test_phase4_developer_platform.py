"""Unit and Integration Tests for Phase 4: Developer Platform, API, SDK, CLI,
Incremental Processing and Vector Database Integrations.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.jobs.manager import JobManager
from app.main import create_app
from app.schemas.chunks import DocumentChunk
from app.schemas.incremental import IncrementalSyncRequest
from app.services.incremental_processor import IncrementalProcessor, compute_content_hash
from app.services.vector_integrations import (
    QdrantSyncService,
    export_to_chroma_format,
    export_to_pinecone_format,
)
from crawlbot import CrawlbotClient
from crawlbot.cli import build_parser as crawlbot_build_parser
from crawlbot.exceptions import (
    CrawlbotAPIError,
    CrawlbotAuthenticationError,
    CrawlbotNotFoundError,
)
from nexora import NexoraClient, NexoraError
from nexora.cli import build_parser as nexora_build_parser
from nexora.exceptions import (
    NexoraAPIError,
    NexoraAuthenticationError,
    NexoraNotFoundError,
    NexoraTimeoutError,
)


@pytest.fixture
def temp_manifest_dir():
    """Create isolated temporary directory for manifest state testing."""
    tmp = tempfile.mkdtemp(prefix="crawlbot_manifest_test_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def mock_app_and_client():
    """Create a test client backed by fresh application instance."""
    app = create_app()
    client = TestClient(app)
    return app, client


# ==============================================================================
# 1. API CONTRACT, VERSIONING & HEALTH TESTS
# ==============================================================================

def test_api_health_and_v1_endpoints(mock_app_and_client):
    _, client = mock_app_and_client

    # Test /health, /api/health, and /api/v1/health
    for path in ("/health", "/api/health", "/api/v1/health"):
        resp = client.get(path)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("ok", "healthy")
        if "version" in data:
            assert data["version"] == "4.0.0"
            assert data["features"]["incremental_sync"] is True
            assert data["features"]["qdrant_sync"] is True


def test_api_v1_aliasing(mock_app_and_client):
    _, client = mock_app_and_client

    # Verify that /api/v1/jobs/list transparently aliases to /api/jobs/list
    r1 = client.get("/api/jobs/list")
    r2 = client.get("/api/v1/jobs/list")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_jobs_list_pagination(mock_app_and_client):
    app, client = mock_app_and_client

    # Inject mock jobs into manager
    manager = app.state.job_manager if hasattr(app.state, "job_manager") else None
    # Test pagination query params
    resp = client.get("/api/v1/jobs/list?limit=2&offset=0")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_key_security_enforcement(mock_app_and_client):
    _, client = mock_app_and_client
    settings = get_settings()

    try:
        settings.api_key = "secret-token-test-xyz"

        # 1. Public route works without authentication
        pub_resp = client.get("/api/health")
        assert pub_resp.status_code == 200

        # 2. Protected route rejected with HTTP 401
        unauth_resp = client.get("/api/jobs/list")
        assert unauth_resp.status_code == 401
        assert "Unauthorized" in unauth_resp.json().get("message", "")

        # 3. Protected route accepted with X-API-Key
        auth_x_resp = client.get("/api/jobs/list", headers={"X-API-Key": "secret-token-test-xyz"})
        assert auth_x_resp.status_code == 200

        # 4. Protected route accepted with Bearer Authorization
        auth_b_resp = client.get("/api/v1/jobs/list", headers={"Authorization": "Bearer secret-token-test-xyz"})
        assert auth_b_resp.status_code == 200

    finally:
        # Reset API key to open local dev mode
        settings.api_key = None


# ==============================================================================
# 2. INCREMENTAL PROCESSING & CONTENT HASHING TESTS
# ==============================================================================

def test_content_hashing():
    h1 = compute_content_hash("Hello World RAG")
    h2 = compute_content_hash("Hello World RAG")
    h3 = compute_content_hash("Different Content")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # Valid SHA-256


def test_incremental_sync_cycle(temp_manifest_dir):
    proc = IncrementalProcessor(manifest_dir=temp_manifest_dir)
    project_id = "test_wiki_project"

    # Step 1: Initial Crawl with 3 documents
    req1 = IncrementalSyncRequest(
        project_id=project_id,
        candidate_urls=["https://example.com/p1", "https://example.com/p2", "https://example.com/p3"],
        raw_documents=[
            {"url": "https://example.com/p1", "text": "Content of Page 1", "chunk_count": 2},
            {"url": "https://example.com/p2", "text": "Content of Page 2", "chunk_count": 3},
            {"url": "https://example.com/p3", "text": "Content of Page 3", "chunk_count": 1},
        ],
        chunk_size=500,
        chunk_overlap=50,
    )
    rep1 = proc.process_sync(req1)
    assert len(rep1.new_urls) == 3
    assert len(rep1.modified_urls) == 0
    assert len(rep1.unchanged_urls) == 0
    assert len(rep1.deleted_urls) == 0
    assert rep1.reprocessed_chunks == 6

    # Verify manifest persisted
    manifest = proc.load_manifest(project_id)
    assert len(manifest.documents) == 3

    # Step 2: Second Crawl with 1 unchanged, 1 modified, 1 deleted, 1 new
    # candidate URLs: p1 (unchanged), p2 (modified text), p4 (new). p3 is deleted.
    req2 = IncrementalSyncRequest(
        project_id=project_id,
        candidate_urls=["https://example.com/p1", "https://example.com/p2", "https://example.com/p4"],
        raw_documents=[
            {"url": "https://example.com/p1", "text": "Content of Page 1", "chunk_count": 2},  # identical
            {"url": "https://example.com/p2", "text": "UPDATED text for page 2", "chunk_count": 4},  # modified
            {"url": "https://example.com/p4", "text": "Brand new page 4", "chunk_count": 2},  # new
        ],
        chunk_size=500,
        chunk_overlap=50,
    )
    rep2 = proc.process_sync(req2)
    assert rep2.unchanged_urls == ["https://example.com/p1"]
    assert rep2.modified_urls == ["https://example.com/p2"]
    assert rep2.new_urls == ["https://example.com/p4"]
    assert rep2.deleted_urls == ["https://example.com/p3"]
    assert rep2.reused_chunks == 2  # p1 chunks preserved!

    # Step 3: Config Change Test (e.g. chunk size changes from 500 to 250)
    req3 = IncrementalSyncRequest(
        project_id=project_id,
        candidate_urls=["https://example.com/p1", "https://example.com/p2", "https://example.com/p4"],
        raw_documents=[
            {"url": "https://example.com/p1", "text": "Content of Page 1", "chunk_count": 2},
            {"url": "https://example.com/p2", "text": "UPDATED text for page 2", "chunk_count": 4},
            {"url": "https://example.com/p4", "text": "Brand new page 4", "chunk_count": 2},
        ],
        chunk_size=250,  # Configuration changed!
        chunk_overlap=25,
    )
    rep3 = proc.process_sync(req3)
    assert rep3.config_invalidated is True
    # All active documents flagged for re-chunking due to signature shift
    assert len(rep3.modified_urls) == 3


def test_incremental_sync_api_route(mock_app_and_client):
    _, client = mock_app_and_client
    unique_proj = f"api_test_proj_{uuid.uuid4().hex[:8]}"
    payload = {
        "project_id": unique_proj,
        "candidate_urls": ["https://example.com/a", "https://example.com/b"],
        "chunk_size": 400,
        "chunk_overlap": 40,
    }
    resp = client.post("/api/v1/ai/incremental/sync", json=payload)
    assert resp.status_code == 200
    res_data = resp.json()["data"]
    assert res_data["project_id"] == unique_proj
    assert len(res_data["new_urls"]) == 2

    # Fetch manifest
    man_resp = client.get(f"/api/v1/ai/incremental/manifest/{unique_proj}")
    assert man_resp.status_code == 200
    assert len(man_resp.json()["data"]["documents"]) == 2


# ==============================================================================
# 3. VECTOR DATABASE INTEGRATION TESTS (QDRANT, CHROMA, PINECONE)
# ==============================================================================

def test_chroma_and_pinecone_export_formats():
    c1 = DocumentChunk(
        chunk_id="chunk_001",
        source_url="https://example.com/docs",
        chunk_index=0,
        total_chunks=1,
        text="Sample text for vector indexing.",
        char_count=32,
        word_count=5,
        category="docs",
        quality_score=0.95,
        embedding=[0.1, 0.2, 0.3, 0.4],
    )
    c2 = DocumentChunk(
        chunk_id="chunk_002",
        source_url="https://example.com/api",
        chunk_index=0,
        total_chunks=1,
        text="No embedding chunk.",
        char_count=19,
        word_count=3,
        embedding=None,  # skipped
    )

    # 1. Chroma Format
    chroma = export_to_chroma_format([c1, c2])
    assert chroma["total_records"] == 1
    assert chroma["ids"] == ["chunk_001"]
    assert chroma["embeddings"] == [[0.1, 0.2, 0.3, 0.4]]
    assert chroma["metadatas"][0]["category"] == "docs"

    # 2. Pinecone Format
    pinecone = export_to_pinecone_format([c1, c2], namespace="dev-ns")
    assert pinecone["total_records"] == 1
    assert pinecone["namespace"] == "dev-ns"
    vec = pinecone["vectors"][0]
    assert vec["values"] == [0.1, 0.2, 0.3, 0.4]
    assert vec["metadata"]["chunk_id"] == "chunk_001"


def test_qdrant_sync_service_deterministic_ids():
    sync = QdrantSyncService(base_url="http://127.0.0.1:9999", timeout=1.0)
    # When no chunks with embeddings exist
    c_empty = DocumentChunk(
        chunk_id="c_empty",
        source_url="https://example.com",
        chunk_index=0,
        total_chunks=1,
        text="Empty embedding",
        char_count=15,
        word_count=2,
    )
    res = sync.sync_chunks("test_col", [c_empty])
    assert res.points_synced == 0
    assert res.success is True


# ==============================================================================
# 4. PYTHON SDK CLIENT TESTS
# ==============================================================================

def test_sdk_instantiation_and_headers():
    # Nexora primary client
    client = NexoraClient(base_url="http://127.0.0.1:8000", api_key="test-key-xyz")
    assert client.base_url == "http://127.0.0.1:8000"
    assert client.api_key == "test-key-xyz"
    assert client._client.headers["X-API-Key"] == "test-key-xyz"
    assert "Nexora-Python-SDK" in client._client.headers["User-Agent"]
    client.close()

    # Crawlbot compatibility alias
    assert CrawlbotClient is NexoraClient
    compat_client = CrawlbotClient(base_url="http://127.0.0.1:8000", api_key="test-key-123")
    assert compat_client.api_key == "test-key-123"
    compat_client.close()


def test_sdk_context_manager():
    with NexoraClient(base_url="http://127.0.0.1:8000") as client:
        assert client.base_url == "http://127.0.0.1:8000"
        assert not client._client.is_closed
    assert client._client.is_closed

    with CrawlbotClient(base_url="http://127.0.0.1:8000") as client:
        assert not client._client.is_closed
    assert client._client.is_closed


def test_sdk_exception_hierarchy():
    err = NexoraAuthenticationError("Invalid API key")
    assert isinstance(err, NexoraAPIError)
    assert isinstance(err, NexoraError)
    assert err.status_code == 401

    nf = NexoraNotFoundError("Job not found")
    assert isinstance(nf, NexoraAPIError)
    assert nf.status_code == 404

    # Backward compatibility aliases
    assert CrawlbotAuthenticationError is NexoraAuthenticationError
    assert CrawlbotAPIError is NexoraAPIError
    compat_err = CrawlbotAuthenticationError("Compat key")
    assert isinstance(compat_err, CrawlbotAPIError)


# ==============================================================================
# 5. CLI PARSER & COMMAND TESTS
# ==============================================================================

def test_cli_parser_commands():
    # Both nexora and crawlbot CLI parsers must return the nexora parser
    for parser_builder in (nexora_build_parser, crawlbot_build_parser):
        parser = parser_builder()
        assert parser.prog == "nexora"

        # Test 'ping'
        args = parser.parse_args(["ping", "-v"])
        assert args.command == "ping"
        assert args.verbose is True

        # Test 'extract'
        args = parser.parse_args(["extract", "https://example.com", "--strategy", "playwright", "-o", "out.md"])
        assert args.command == "extract"
        assert args.url == "https://example.com"
        assert args.strategy == "playwright"
        assert args.output == "out.md"

        # Test 'crawl'
        args = parser.parse_args(["crawl", "https://example.com", "--max-pages", "20", "--wait"])
        assert args.command == "crawl"
        assert args.max_pages == 20
        assert args.wait is True

        # Test 'sync'
        args = parser.parse_args(["sync", "proj_1", "https://a.com", "https://b.com", "--size", "600"])
        assert args.command == "sync"
        assert args.project_id == "proj_1"
        assert len(args.urls) == 2
        assert args.size == 600

        # Test 'vector-export'
        args = parser.parse_args(["vector-export", "job_123", "--target", "qdrant", "--collection", "my_docs"])
        assert args.command == "vector-export"
        assert args.target == "qdrant"
        assert args.collection == "my_docs"
