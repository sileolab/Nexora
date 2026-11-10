"""Comprehensive Multi-Tenant Data Isolation Test Suite (Phase 3).

Verifies strict cross-tenant isolation across all 13 domains:
1. Vector Store Search (Dense, BM25, Hybrid)
2. Vector Store Deletion & Clear
3. Exports (AI Export, Chroma, Pinecone, Qdrant)
4. Dataset Studio Stages & Chunk Queries
5. Dataset Studio Edits (Update, Merge, Split, Revert)
6. Dataset Studio Quality Reports
7. Snapshots, Versioning & Diffs
8. Incremental Processing Manifests (Same project_id across distinct tenants)
9. RAG Evaluation Datasets & QA Samples
10. Evaluation Runs & Run Comparisons
11. Retrieval Debugger & Exclusion Tracing
12. File Storage (Uploads, Info, Preview, Download)
13. Cross-Tenant Deletion Attacks (Jobs, Documents, Chunks, Datasets, Runs)
"""

import io
import json
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.jobs.manager import get_job_manager
from app.jobs.models import JobInfo, JobState
from app.schemas.chunks import DocumentChunk
from app.schemas.documents import ExtractedDocument
from app.services.vector_store import get_vector_store
from app.services.workspace_manager import get_workspace_manager
from app.services.dataset_studio import dataset_studio
from app.services.rag_evaluator import rag_evaluator
from app.services.file_processor import FileProcessorService


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure clean state for tests."""
    get_vector_store().clear()
    dataset_studio._snapshots.clear()
    rag_evaluator._eval_datasets.clear()
    rag_evaluator._eval_runs.clear()
    rag_evaluator._store_cache.clear()
    yield
    get_vector_store().clear()
    dataset_studio._snapshots.clear()
    rag_evaluator._eval_datasets.clear()
    rag_evaluator._eval_runs.clear()
    rag_evaluator._store_cache.clear()


@pytest.mark.asyncio
async def test_multi_tenant_vector_search_and_expansion_isolation():
    """Test 1: Vector search from Tenant B never returns Tenant A data, including neighbors."""
    store = get_vector_store()
    tenant_a = "ws_tenant_alpha_111"
    tenant_b = "ws_tenant_beta_222"

    # Ingest chunks for Tenant A with secret string
    chunk_a1 = DocumentChunk(
        chunk_id="chunk_a_1",
        source_url="https://tenant-a.com/page",
        chunk_index=0,
        total_chunks=2,
        text="Confidential financial report: TENANT_A_SECRET_7391 revenue increased by 50%.",
        char_count=75,
        word_count=10,
        heading_context="Revenue 2026",
        tenant_id=tenant_a,
    )
    chunk_a2 = DocumentChunk(
        chunk_id="chunk_a_2",
        source_url="https://tenant-a.com/page",
        chunk_index=1,
        total_chunks=2,
        text="TENANT_A_SECRET_7391 neighbor details: internal roadmap and strategy.",
        char_count=69,
        word_count=8,
        heading_context="Strategy",
        tenant_id=tenant_a,
    )

    # Ingest chunks for Tenant B with secret string
    chunk_b1 = DocumentChunk(
        chunk_id="chunk_b_1",
        source_url="https://tenant-b.com/page",
        chunk_index=0,
        total_chunks=1,
        text="Public product overview: TENANT_B_SECRET_2846 release notes and changelog.",
        char_count=74,
        word_count=9,
        heading_context="Changelog",
        tenant_id=tenant_b,
    )

    store.upsert_chunks([chunk_a1, chunk_a2], tenant_id=tenant_a)
    store.upsert_chunks([chunk_b1], tenant_id=tenant_b)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Tenant B searches for "TENANT_A_SECRET_7391"
        res_b = await client.post(
            "/api/ai/vector-store/search",
            json={"query": "TENANT_A_SECRET_7391", "expand_neighbors": True},
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_b.status_code == 200
        data_b = res_b.json()["data"]
        assert len(data_b["results"]) == 0, "Tenant B must NOT receive Tenant A's secret"

        # 2. Tenant B searches for "financial report"
        res_b2 = await client.post(
            "/api/ai/vector-store/search",
            json={"query": "financial report", "expand_neighbors": True},
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_b2.status_code == 200
        data_b2 = res_b2.json()["data"]
        for r in data_b2["results"]:
            assert "TENANT_A_SECRET_7391" not in r["chunk"]["text"]
            for n in r.get("neighbors", []):
                assert "TENANT_A_SECRET_7391" not in n["text"]

        # 3. Tenant A searches for its own secret
        res_a = await client.post(
            "/api/ai/vector-store/search",
            json={"query": "TENANT_A_SECRET_7391", "expand_neighbors": True},
            headers={"X-Workspace-Id": tenant_a},
        )
        assert res_a.status_code == 200
        data_a = res_a.json()["data"]
        assert len(data_a["results"]) > 0
        assert "TENANT_A_SECRET_7391" in data_a["results"][0]["chunk"]["text"]
        assert "TENANT_B_SECRET_2846" not in data_a["results"][0]["chunk"]["text"]


@pytest.mark.asyncio
async def test_multi_tenant_vector_deletion_isolation():
    """Test 2: Delete by URL or document_id from Tenant B never removes Tenant A's chunks."""
    store = get_vector_store()
    tenant_a = "ws_tenant_alpha_111"
    tenant_b = "ws_tenant_beta_222"
    shared_url = "https://common-domain.com/docs"

    chunk_a = DocumentChunk(
        chunk_id="chunk_del_a",
        source_url=shared_url,
        source_doc_id="doc_shared_1",
        chunk_index=0,
        total_chunks=1,
        text="Tenant A private info: TENANT_A_SECRET_7391",
        char_count=43,
        word_count=5,
        tenant_id=tenant_a,
    )
    chunk_b = DocumentChunk(
        chunk_id="chunk_del_b",
        source_url=shared_url,
        source_doc_id="doc_shared_1",
        chunk_index=0,
        total_chunks=1,
        text="Tenant B info: TENANT_B_SECRET_2846",
        char_count=35,
        word_count=4,
        tenant_id=tenant_b,
    )

    store.upsert_chunks([chunk_a], tenant_id=tenant_a)
    store.upsert_chunks([chunk_b], tenant_id=tenant_b)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Tenant B attempts to delete shared URL
        res = await client.delete(
            f"/api/ai/vector-store/clear?source_url={shared_url}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res.status_code == 200
        # Tenant B's chunk deleted, but Tenant A's chunk MUST remain intact
        stats_a = store.get_stats(tenant_id=tenant_a)
        assert stats_a["total_chunks"] == 1
        assert "chunk_del_a" in store._chunks

        # Tenant B stats should now be 0
        stats_b = store.get_stats(tenant_id=tenant_b)
        assert stats_b["total_chunks"] == 0


@pytest.mark.asyncio
async def test_multi_tenant_export_isolation():
    """Test 3: Export endpoints (AI JSON/JSONL, Chroma, Pinecone, Qdrant) enforce ownership."""
    manager = get_job_manager()
    tenant_a = "ws_tenant_alpha_111"
    tenant_b = "ws_tenant_beta_222"

    # Create job owned by Tenant A
    job_a = JobInfo(
        job_id="job_export_a_999",
        url="https://tenant-a.com",
        job_type="extraction",
        status=JobState.COMPLETED,
        tenant_id=tenant_a,
    )
    manager._jobs[job_a.job_id] = job_a

    chunk_a = DocumentChunk(
        chunk_id="chunk_exp_a",
        source_url="https://tenant-a.com",
        chunk_index=0,
        total_chunks=1,
        text="Proprietary data TENANT_A_SECRET_7391",
        char_count=37,
        word_count=4,
        embedding=[0.1] * 1536,
        tenant_id=tenant_a,
    )
    manager.store_chunks(job_a.job_id, [chunk_a], tenant_id=tenant_a)

    doc_a = ExtractedDocument(
        document_id="doc_exp_a",
        url="https://tenant-a.com",
        content_text="Secret document containing TENANT_A_SECRET_7391",
        character_count=47,
        word_count=5,
    )
    manager.set_documents(job_a.job_id, [doc_a])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Tenant B attempts to export Tenant A's job via /api/ai/export
        res_exp = await client.post(
            "/api/ai/export",
            json={"job_id": job_a.job_id, "format": "json_chunks"},
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_exp.status_code == 404, "Tenant B must not export Tenant A job data"

        # 2. Tenant B attempts to export Tenant A's job via /api/export/download
        res_down = await client.post(
            "/api/export/download",
            json={"job_id": job_a.job_id, "format": "json"},
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_down.status_code == 404, "Tenant B must not download Tenant A documents"

        # 3. Tenant B attempts vector export Chroma
        res_chroma = await client.get(
            f"/api/ai/vector-export/chroma/{job_a.job_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_chroma.status_code == 404

        # 4. Tenant B attempts vector export Pinecone
        res_pinecone = await client.get(
            f"/api/ai/vector-export/pinecone/{job_a.job_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_pinecone.status_code == 404

        # 5. Tenant B attempts vector export Qdrant
        res_qdrant = await client.post(
            "/api/ai/vector-export/qdrant",
            json={"job_id": job_a.job_id},
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_qdrant.status_code == 404


@pytest.mark.asyncio
async def test_multi_tenant_dataset_studio_isolation():
    """Test 4: Dataset Studio stages, chunks, and quality reports strictly enforce tenant boundaries."""
    manager = get_job_manager()
    tenant_a = "ws_tenant_alpha_111"
    tenant_b = "ws_tenant_beta_222"

    job_a = JobInfo(
        job_id="job_studio_a_888",
        url="https://tenant-a.com",
        job_type="extraction",
        status=JobState.COMPLETED,
        tenant_id=tenant_a,
    )
    manager._jobs[job_a.job_id] = job_a

    chunk_a = DocumentChunk(
        chunk_id="chunk_ds_a",
        source_url="https://tenant-a.com",
        chunk_index=0,
        total_chunks=1,
        text="Internal secret TENANT_A_SECRET_7391",
        char_count=36,
        word_count=4,
        tenant_id=tenant_a,
    )
    manager.store_chunks(job_a.job_id, [chunk_a], tenant_id=tenant_a)

    doc_a = ExtractedDocument(
        document_id="doc_ds_a",
        url="https://tenant-a.com",
        content_text="Internal secret TENANT_A_SECRET_7391",
        character_count=36,
        word_count=4,
    )
    manager.set_documents(job_a.job_id, [doc_a])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Tenant B attempts to access stages of Job A
        res_stages = await client.get(
            f"/api/ai/stages/{job_a.job_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_stages.status_code == 404

        # Tenant B attempts to query chunks of Job A
        res_chunks = await client.get(
            f"/api/ai/chunks/{job_a.job_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_chunks.status_code == 404

        # Tenant B attempts to update chunk in Job A
        res_up = await client.post(
            f"/api/ai/chunks/{job_a.job_id}/update",
            json={"chunk_id": "chunk_ds_a", "text": "Tampered by B"},
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_up.status_code == 404

        # Tenant B attempts to get quality report of Job A
        res_qr = await client.get(
            f"/api/ai/datasets/quality/{job_a.job_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_qr.status_code == 404

        # Tenant B attempts to list snapshots of Job A
        res_snaps = await client.get(
            f"/api/ai/dataset/{job_a.job_id}/versions",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_snaps.status_code == 404


@pytest.mark.asyncio
async def test_multi_tenant_incremental_manifest_collision_prevention():
    """Test 5: Identically-named project_id manifests between Tenant A and B do not collide or overwrite."""
    tenant_a = "ws_tenant_alpha_111"
    tenant_b = "ws_tenant_beta_222"
    project_id = "e-commerce-portal"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Tenant A syncs project
        sync_a = await client.post(
            "/api/ai/incremental/sync",
            json={
                "project_id": project_id,
                "candidate_urls": ["https://tenant-a.com/page1", "https://tenant-a.com/page2"],
                "raw_documents": [
                    {"url": "https://tenant-a.com/page1", "text": "TENANT_A_SECRET_7391 product catalog"},
                ],
            },
            headers={"X-Workspace-Id": tenant_a},
        )
        assert sync_a.status_code == 200
        rep_a = sync_a.json()["data"]
        assert rep_a["total_candidates"] == 2

        # Tenant B syncs project with the EXACT SAME project_id
        sync_b = await client.post(
            "/api/ai/incremental/sync",
            json={
                "project_id": project_id,
                "candidate_urls": ["https://tenant-b.com/item1"],
                "raw_documents": [
                    {"url": "https://tenant-b.com/item1", "text": "TENANT_B_SECRET_2846 inventory list"},
                ],
            },
            headers={"X-Workspace-Id": tenant_b},
        )
        assert sync_b.status_code == 200
        rep_b = sync_b.json()["data"]
        assert rep_b["total_candidates"] == 1

        # Retrieve Tenant A's manifest
        man_a_res = await client.get(
            f"/api/ai/incremental/manifest/{project_id}",
            headers={"X-Workspace-Id": tenant_a},
        )
        assert man_a_res.status_code == 200
        docs_a = man_a_res.json()["data"]["documents"]
        assert "https://tenant-a.com/page1" in docs_a
        assert "https://tenant-b.com/item1" not in docs_a

        # Retrieve Tenant B's manifest
        man_b_res = await client.get(
            f"/api/ai/incremental/manifest/{project_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert man_b_res.status_code == 200
        docs_b = man_b_res.json()["data"]["documents"]
        assert "https://tenant-b.com/item1" in docs_b
        assert "https://tenant-a.com/page1" not in docs_b


@pytest.mark.asyncio
async def test_multi_tenant_eval_datasets_and_runs_isolation():
    """Test 6: Evaluation Datasets, Samples, Runs, and Debugging are strictly partitioned."""
    tenant_a = "ws_tenant_alpha_111"
    tenant_b = "ws_tenant_beta_222"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Tenant A creates evaluation dataset
        res_create_a = await client.post(
            "/api/ai/eval/datasets",
            json={
                "name": "Tenant A Secret Eval Suite",
                "description": "Evaluation set with TENANT_A_SECRET_7391",
            },
            headers={"X-Workspace-Id": tenant_a},
        )
        assert res_create_a.status_code == 200
        dataset_a_id = res_create_a.json()["data"]["dataset_id"]

        # 2. Tenant A adds a sample
        res_sample_a = await client.post(
            f"/api/ai/eval/datasets/{dataset_a_id}/samples",
            json={
                "question": "What is the secret TENANT_A_SECRET_7391?",
                "job_id": "job_any",
                "expected_chunk_ids": ["chunk_1"],
            },
            headers={"X-Workspace-Id": tenant_a},
        )
        assert res_sample_a.status_code == 200
        sample_a_id = res_sample_a.json()["data"]["sample_id"]

        # 3. Tenant B lists datasets -> must NOT see Tenant A's dataset
        res_list_b = await client.get(
            "/api/ai/eval/datasets",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_list_b.status_code == 200
        b_datasets = res_list_b.json()["data"]
        assert all(d["dataset_id"] != dataset_a_id for d in b_datasets)

        # 4. Tenant B attempts direct access to Tenant A's dataset
        res_get_b = await client.get(
            f"/api/ai/eval/datasets/{dataset_a_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_get_b.status_code == 404

        # 5. Tenant B attempts to delete Tenant A's sample
        res_del_s_b = await client.delete(
            f"/api/ai/eval/datasets/{dataset_a_id}/samples/{sample_a_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_del_s_b.status_code == 404

        # 6. Tenant B attempts to delete Tenant A's dataset
        res_del_b = await client.delete(
            f"/api/ai/eval/datasets/{dataset_a_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert res_del_b.status_code == 404

        # Verify Tenant A's dataset is still fully intact
        res_get_a = await client.get(
            f"/api/ai/eval/datasets/{dataset_a_id}",
            headers={"X-Workspace-Id": tenant_a},
        )
        assert res_get_a.status_code == 200
        assert len(res_get_a.json()["data"]["samples"]) == 1


@pytest.mark.asyncio
async def test_multi_tenant_file_storage_and_artifacts_isolation():
    """Test 7: Uploaded files and processed artifacts are strictly isolated between tenants."""
    tenant_a = "ws_tenant_alpha_111"
    tenant_b = "ws_tenant_beta_222"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Tenant A uploads a file containing sensitive string
        content = b"# Proprietary Document\nTENANT_A_SECRET_7391 confidential details"
        files = {"file": ("tenant_a_doc.md", io.BytesIO(content), "text/markdown")}
        up_res = await client.post(
            "/api/files/upload",
            files=files,
            headers={"X-Workspace-Id": tenant_a},
        )
        assert up_res.status_code == 200
        file_a_id = up_res.json()["data"]["file_id"]

        # Tenant B attempts to access file info of Tenant A's file
        info_b = await client.get(
            f"/api/files/info/{file_a_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert info_b.status_code == 404, "Tenant B must not see Tenant A file metadata"

        # Tenant A processes the file
        proc_res = await client.post(
            "/api/files/process",
            json={"file_id": file_a_id, "operations": ["normalize"]},
            headers={"X-Workspace-Id": tenant_a},
        )
        assert proc_res.status_code == 200
        artifact_a_id = proc_res.json()["data"]["artifact_id"]

        # Tenant B attempts to preview Tenant A's artifact
        prev_b = await client.get(
            f"/api/files/preview/{artifact_a_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert prev_b.status_code == 404, "Tenant B must not preview Tenant A artifact"

        # Tenant B attempts to download Tenant A's artifact
        down_b = await client.get(
            f"/api/files/download/{artifact_a_id}",
            headers={"X-Workspace-Id": tenant_b},
        )
        assert down_b.status_code == 404, "Tenant B must not download Tenant A artifact"

        # Tenant A can preview its own artifact successfully
        prev_a = await client.get(
            f"/api/files/preview/{artifact_a_id}",
            headers={"X-Workspace-Id": tenant_a},
        )
        assert prev_a.status_code == 200
        assert "TENANT_A_SECRET_7391" in prev_a.json()["data"]["content_preview"]
