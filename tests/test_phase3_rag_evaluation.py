"""Unit and Integration Tests for Phase 3: RAG Retrieval Evaluation, Playground & Debugging.

Covers:
1. Evaluation Dataset & Sample Management (CRUD, provenance, human review).
2. Synthetic QA Importer (LLM origin, unreviewed status, no auto-ground-truth).
3. Retrieval Playground with explicit score labeling (Dense, BM25, Hybrid).
4. Multi-Method Side-by-Side Comparison.
5. Strict Information Retrieval Metrics (Recall@K, Precision@K, MRR, nDCG@K, Hit Rate).
6. Missing Ground Truth Handling (never masks absence with fake scores).
7. Evaluation Runs and Pipeline Version Comparison (metric deltas, query transitions).
8. Deterministic Retrieval Debugging Trace (candidate filtering, exclusion reasons, actionable warnings).
9. Edge cases: empty query, zero-results, over-strict min_score, small dataset, missing embeddings.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.jobs.manager import JobManager
from app.main import app
from app.schemas.chunks import DocumentChunk
from app.schemas.eval import EvalDataset, EvalRunConfig, EvalSample
from app.services.dataset_studio import DatasetStudioService
from app.services.rag_evaluator import RAGEvaluatorService


@pytest.fixture
def temp_eval_dir():
    """Create a temporary directory for isolated evaluation persistence."""
    tmp = tempfile.mkdtemp(prefix="crawlbot_eval_test_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def mock_job_manager():
    """Create a JobManager populated with test chunks and metadata."""
    manager = JobManager()
    job_id = "test-job-eval-001"
    manager._jobs[job_id] = {
        "job_id": job_id,
        "state": "completed",
        "job_type": "crawl",
    }

    # Chunks with sample text, some with mock embeddings
    c1 = DocumentChunk(
        chunk_id="chunk_1",
        source_url="https://example.com/ai/rag",
        chunk_index=0,
        total_chunks=3,
        text="سامانه‌های RAG بازیابی اطلاعات را با مدل‌های زبانی ترکیب می‌کنند.",
        char_count=65,
        word_count=10,
        heading_context="معماری RAG > مقدمه",
        title="مقدمه‌ای بر RAG",
        category="rag",
        language="fa",
        embedding=[0.1] * 1536,
        embedding_model="text-embedding-3-small",
        content_hash="hash_c1",
    )
    c2 = DocumentChunk(
        chunk_id="chunk_2",
        source_url="https://example.com/ai/rag",
        chunk_index=1,
        total_chunks=3,
        text="استراتژی قطعه‌بندی یا Chunking تأثیر مستقیمی بر کیفیت بازیابی دارد.",
        char_count=67,
        word_count=10,
        heading_context="معماری RAG > قطعه‌بندی",
        title="مقدمه‌ای بر RAG",
        category="rag",
        language="fa",
        embedding=[0.2] * 1536,
        embedding_model="text-embedding-3-small",
        content_hash="hash_c2",
    )
    c3 = DocumentChunk(
        chunk_id="chunk_3",
        source_url="https://example.com/ai/rag",
        chunk_index=2,
        total_chunks=3,
        text="ترکیب جست‌وجوی متنی BM25 و معنایی Dense را جست‌وجوی Hybrid می‌نامند.",
        char_count=67,
        word_count=10,
        heading_context="معماری RAG > جست‌وجوی ترکیبی",
        title="مقدمه‌ای بر RAG",
        category="rag",
        language="fa",
        embedding=[0.3] * 1536,
        embedding_model="text-embedding-3-small",
        content_hash="hash_c3",
    )
    c4 = DocumentChunk(
        chunk_id="chunk_4",
        source_url="https://example.com/python/async",
        chunk_index=0,
        total_chunks=1,
        text="برنامه‌نویسی ناهمگام در پایتون با کتابخانه asyncio پیاده‌سازی می‌شود.",
        char_count=68,
        word_count=9,
        heading_context="پایتون پیشرفته > Async",
        title="پایتون ناهمگام",
        category="python",
        language="fa",
        embedding=[0.05] * 1536,
        embedding_model="text-embedding-3-small",
        content_hash="hash_c4",
    )

    manager.store_chunks(job_id, [c1, c2, c3, c4])
    manager.store_rag_metadata(job_id, [
        {
            "qa_pairs": [
                {
                    "question": "سامانه‌های RAG چه کاری انجام می‌دهند؟",
                    "answer": "بازیابی اطلاعات را با تولید متن ترکیب می‌کنند.",
                },
                {
                    "question": "جست‌وجوی هیبرید چیست؟",
                    "answer": "ترکیب BM25 و Dense.",
                },
            ],
        }
    ])

    return manager


@pytest.fixture
def eval_service(mock_job_manager, temp_eval_dir):
    """Instantiate RAGEvaluatorService with temporary storage and mock data."""
    ds_file = os.path.join(temp_eval_dir, "eval_datasets.json")
    runs_file = os.path.join(temp_eval_dir, "eval_runs.json")
    return RAGEvaluatorService(
        job_manager=mock_job_manager,
        datasets_file=ds_file,
        runs_file=runs_file,
    )


# ===========================================================================
# 1. Dataset & Sample Management (CRUD & Provenance)
# ===========================================================================

def test_eval_dataset_crud(eval_service):
    """Verify evaluation dataset creation, retrieval, listing, and deletion."""
    ds = eval_service.create_dataset(
        name="مجموعه آزمون بازیابی عمومی",
        description="تست کیفیت جست‌وجوی مستندات RAG",
        job_id="test-job-eval-001",
    )
    assert ds.dataset_id.startswith("eval_")
    assert ds.name == "مجموعه آزمون بازیابی عمومی"
    assert len(ds.samples) == 0

    # Retrieve
    retrieved = eval_service.get_dataset(ds.dataset_id)
    assert retrieved.name == ds.name

    # List
    summary_list = eval_service.list_datasets()
    assert len(summary_list) == 1
    assert summary_list[0]["dataset_id"] == ds.dataset_id

    # Add Sample
    sample = eval_service.add_sample(
        dataset_id=ds.dataset_id,
        question="ترکیب BM25 و Dense چه نام دارد؟",
        job_id="test-job-eval-001",
        expected_chunk_ids=["chunk_3"],
        relevance_labels={"chunk_3": 2},
        notes="سؤال استاندارد برای تست تطابق کلمه کلیدی",
        origin="manual",
        human_reviewed=True,
    )
    assert sample.sample_id.startswith("s_")
    assert sample.origin == "manual"
    assert sample.human_reviewed is True
    assert sample.relevance_labels["chunk_3"] == 2

    # Update Sample
    updated = eval_service.update_sample(
        dataset_id=ds.dataset_id,
        sample_id=sample.sample_id,
        notes="یادداشت به‌روزرسانی‌شده",
        human_reviewed=True,
    )
    assert updated.notes == "یادداشت به‌روزرسانی‌شده"

    # Delete Sample
    del_ok = eval_service.delete_sample(ds.dataset_id, sample.sample_id)
    assert del_ok is True
    assert len(eval_service.get_dataset(ds.dataset_id).samples) == 0

    # Delete Dataset
    assert eval_service.delete_dataset(ds.dataset_id) is True
    with pytest.raises(ValueError):
        eval_service.get_dataset(ds.dataset_id)


# ===========================================================================
# 2. Synthetic QA Importer (Safe Provenance Tracking)
# ===========================================================================

def test_import_synthetic_qa_safe_provenance(eval_service):
    """Verify synthetic QA import marks origin as llm_generated and unreviewed."""
    ds = eval_service.create_dataset(
        name="مجموعه سوالات هوش مصنوعی",
        job_id="test-job-eval-001",
    )
    imported = eval_service.import_synthetic_qa(
        dataset_id=ds.dataset_id,
        job_id="test-job-eval-001",
        max_samples=5,
    )
    assert len(imported) == 2
    for s in imported:
        # Crucial rule verification:
        assert s.origin == "llm_generated"
        assert s.human_reviewed is False
        assert s.relevance_labels == {}
        assert "نیازمند بازبینی انسانی" in (s.notes or "")


# ===========================================================================
# 3. Retrieval Playground (Score Scale Labeling & BM25)
# ===========================================================================

@pytest.mark.asyncio
async def test_playground_search_bm25_score_labeling(eval_service):
    """Verify BM25 playground search returns explicit score typing and ranking."""
    res = await eval_service.search_playground(
        job_id="test-job-eval-001",
        query="جست‌وجوی هیبرید و ترکیبی",
        method="bm25",
        top_k=2,
    )
    assert res.total_returned > 0
    assert res.results[0].rank == 1
    assert "BM25" in res.results[0].score_type
    assert res.results[0].search_method == "bm25"
    # Chunk 3 contains "ترکیب" and "Hybrid"
    assert res.results[0].chunk_id == "chunk_3"


@pytest.mark.asyncio
async def test_playground_context_expansion(eval_service):
    """Verify context expansion correctly retrieves neighboring chunks."""
    res = await eval_service.search_playground(
        job_id="test-job-eval-001",
        query="قطعه‌بندی",
        method="bm25",
        top_k=1,
        expand_neighbors=True,
    )
    assert res.total_returned == 1
    top_item = res.results[0]
    assert top_item.chunk_id == "chunk_2"
    # Neighbors of chunk_2 (index 1) should be chunk_1 (index 0) and chunk_3 (index 2)
    assert top_item.neighbors_count >= 1
    assert len(top_item.neighbors_previews) >= 1


# ===========================================================================
# 4. Multi-Method Side-by-Side Comparison
# ===========================================================================

@pytest.mark.asyncio
async def test_compare_methods_side_by_side(eval_service):
    """Verify comparison returns results for all methods with distinct score descriptions."""
    comp = await eval_service.compare_methods(
        job_id="test-job-eval-001",
        query="RAG و بازیابی اطلاعات",
        top_k=3,
        alpha=0.6,
    )
    assert len(comp.bm25_results) > 0
    assert len(comp.hybrid_results) > 0
    assert "به معنای برتری ذاتی یا مطلق هیچ‌کدام از روش‌ها نیست" in comp.comparison_notice


# ===========================================================================
# 5. Strict Information Retrieval Metrics (Recall, Precision, MRR, nDCG, Hit Rate)
# ===========================================================================

def test_metrics_calculation_grounded(eval_service):
    """Verify mathematical correctness of IR metrics when valid ground truth exists."""
    sample = EvalSample(
        sample_id="s1",
        question="سؤال تست",
        job_id="j1",
        expected_chunk_ids=["chunk_1", "chunk_2"],
        relevance_labels={"chunk_1": 2, "chunk_2": 1, "chunk_3": 0},
        origin="manual",
        human_reviewed=True,
        created_at="2026-10-29T00:00:00Z",
    )

    retrieved = [
        DocumentChunk(chunk_id="chunk_3", source_url="u", chunk_index=0, total_chunks=1, text="c3", char_count=2, word_count=1),
        DocumentChunk(chunk_id="chunk_1", source_url="u", chunk_index=1, total_chunks=1, text="c1", char_count=2, word_count=1),
        DocumentChunk(chunk_id="chunk_4", source_url="u", chunk_index=2, total_chunks=1, text="c4", char_count=2, word_count=1),
    ]

    metrics = eval_service._compute_sample_metrics(sample, retrieved, k=3)
    assert metrics.has_ground_truth is True
    # 1 of 2 expected was retrieved in top 3 -> Recall@3 = 0.5
    assert metrics.recall_at_k == 0.5
    # 1 of 3 retrieved is relevant -> Precision@3 = 1/3 ≈ 0.3333
    assert metrics.precision_at_k == round(1 / 3, 4)
    # First relevant is at rank 2 -> MRR = 1/2 = 0.5
    assert metrics.mrr == 0.5
    assert metrics.first_relevant_rank == 2
    assert metrics.hit_rate == 1.0
    # nDCG calculation check: chunk_3 (grade 0, rank 1), chunk_1 (grade 2, rank 2)
    # DCG = (2^2 - 1) / log2(3) = 3 / 1.58496 ≈ 1.89278
    # IDCG = (2^2 - 1) / log2(2) + (2^1 - 1) / log2(3) = 3 + 1/1.58496 ≈ 3.6309
    assert metrics.ndcg_at_k is not None
    assert 0.0 < metrics.ndcg_at_k < 1.0


def test_missing_ground_truth_policy(eval_service):
    """Verify that samples without ground truth NEVER produce fake or misleading metrics."""
    sample = EvalSample(
        sample_id="s_no_gt",
        question="یک سؤال بدون برچسب",
        job_id="j1",
        expected_chunk_ids=[],
        expected_source_urls=[],
        relevance_labels={},
        origin="llm_generated",
        human_reviewed=False,
        created_at="2026-10-29T00:00:00Z",
    )

    retrieved = [
        DocumentChunk(chunk_id="chunk_1", source_url="u", chunk_index=0, total_chunks=1, text="c1", char_count=2, word_count=1),
    ]

    metrics = eval_service._compute_sample_metrics(sample, retrieved, k=5)
    assert metrics.has_ground_truth is False
    assert metrics.recall_at_k is None
    assert metrics.precision_at_k is None
    assert metrics.mrr is None
    assert metrics.ndcg_at_k is None
    assert metrics.hit_rate is None
    assert "برچسب حقیقت مرجع (Ground Truth) برای این نمونه ثبت نشده است" in metrics.warning


# ===========================================================================
# 6. Evaluation Run Execution & Pipeline Version Comparison
# ===========================================================================

@pytest.mark.asyncio
async def test_execute_evaluation_run_and_comparison(eval_service):
    """Verify execution of full evaluation run and delta comparison between runs."""
    ds = eval_service.create_dataset(
        name="مجموعه بنچمارک RAG",
        job_id="test-job-eval-001",
    )
    # Sample with valid GT
    eval_service.add_sample(
        dataset_id=ds.dataset_id,
        question="سامانه‌های RAG چگونه کار می‌کنند؟",
        job_id="test-job-eval-001",
        expected_chunk_ids=["chunk_1"],
        relevance_labels={"chunk_1": 2},
        origin="manual",
        human_reviewed=True,
    )
    # Sample with missing GT
    eval_service.add_sample(
        dataset_id=ds.dataset_id,
        question="پایتون ناهمگام چگونه است؟",
        job_id="test-job-eval-001",
        expected_chunk_ids=[],
        relevance_labels={},
        origin="llm_generated",
        human_reviewed=False,
    )

    # Run A: BM25 with top_k=2
    run_a = await eval_service.execute_run(
        dataset_id=ds.dataset_id,
        job_id="test-job-eval-001",
        method="bm25",
        top_k=2,
    )
    assert run_a.total_samples == 2
    assert run_a.samples_with_ground_truth == 1
    assert run_a.insufficient_ground_truth is False
    assert "recall_at_2" in run_a.aggregate_metrics
    assert run_a.ground_truth_warning is not None

    # Run B: BM25 with top_k=5
    run_b = await eval_service.execute_run(
        dataset_id=ds.dataset_id,
        job_id="test-job-eval-001",
        method="bm25",
        top_k=5,
    )

    # Compare Runs
    comp = eval_service.compare_runs(run_a.run_id, run_b.run_id)
    assert comp.run_id_a == run_a.run_id
    assert comp.run_id_b == run_b.run_id
    assert "مقایسه اجرای" in comp.summary_message


# ===========================================================================
# 7. Retrieval Debugging Trace (Candidate Filtering & Exclusion Diagnostics)
# ===========================================================================

@pytest.mark.asyncio
async def test_retrieval_debugging_trace_and_exclusions(eval_service):
    """Verify debugging trace surfaces query tokens, language, and exclusion reasons."""
    # Test with over-restrictive min_score to verify exclusion instrumentation
    trace = await eval_service.debug_retrieval(
        job_id="test-job-eval-001",
        query="برنامه‌نویسی ناهمگام پایتون",
        method="bm25",
        top_k=3,
        min_score=0.99,  # Very high threshold
    )
    assert trace.query == "برنامه‌نویسی ناهمگام پایتون"
    assert "Persian" in trace.detected_language
    assert len(trace.tokens) >= 3
    assert trace.total_chunks_in_dataset == 4
    # With min_score=0.99, candidates should be excluded by score
    assert trace.excluded_by_min_score > 0
    assert len(trace.min_score_exclusion_sample) > 0
    assert "کمتر از حداقل آستانه مجاز" in trace.min_score_exclusion_sample[0]["reason"]
    # Check actionable warnings
    assert any("بیش از حد سخت‌گیرانه است" in w for w in trace.actionable_warnings)


@pytest.mark.asyncio
async def test_retrieval_debugging_metadata_filter_exclusion(eval_service):
    """Verify metadata filtering exclusions are reported in debugging trace."""
    trace = await eval_service.debug_retrieval(
        job_id="test-job-eval-001",
        query="RAG",
        category="non_existent_category",
    )
    assert trace.excluded_by_metadata == 4
    assert len(trace.metadata_exclusion_sample) > 0
    assert "دسته‌بندی" in trace.metadata_exclusion_sample[0]["reasons"][0]
    assert any("فیلترهای متادیتا" in w for w in trace.actionable_warnings)


# ===========================================================================
# 8. Edge Cases: Empty Query, Invalid Input, Small Dataset
# ===========================================================================

@pytest.mark.asyncio
async def test_empty_query_handling(eval_service):
    """Verify empty query raises ValueError."""
    with pytest.raises(ValueError, match="نمی‌تواند خالی باشد"):
        await eval_service.search_playground(job_id="test-job-eval-001", query="   ")


@pytest.mark.asyncio
async def test_small_dataset_actionable_warning(eval_service):
    """Verify small dataset (< 5 chunks) triggers an explicit advisory warning."""
    trace = await eval_service.debug_retrieval(
        job_id="test-job-eval-001",
        query="RAG",
    )
    assert any("مجموعه داده بسیار کوچک است" in w for w in trace.actionable_warnings)


# ===========================================================================
# 9. API Routes Integration Tests
# ===========================================================================

def test_api_routes_eval(mock_job_manager):
    """Verify FastAPI routes for evaluation endpoints."""
    from app.api import routes_ai
    routes_ai.set_job_manager(mock_job_manager)
    client = TestClient(app)

    # 1. Create Dataset
    res = client.post("/api/ai/eval/datasets", json={"name": "API Test Set", "job_id": "test-job-eval-001"})
    assert res.status_code == 200
    ds_data = res.json()["data"]
    ds_id = ds_data["dataset_id"]

    # 2. Add Sample
    res_sample = client.post(
        f"/api/ai/eval/datasets/{ds_id}/samples",
        json={
            "question": "پرسش تستی API",
            "job_id": "test-job-eval-001",
            "expected_chunk_ids": ["chunk_1"],
            "relevance_labels": {"chunk_1": 2},
            "origin": "manual",
            "human_reviewed": True,
        },
    )
    assert res_sample.status_code == 200

    # 3. Playground Search Endpoint
    res_pg = client.post(
        "/api/ai/eval/playground",
        json={"job_id": "test-job-eval-001", "query": "RAG", "method": "bm25"},
    )
    assert res_pg.status_code == 200
    assert res_pg.json()["data"]["total_returned"] > 0

    # 4. Compare Methods Endpoint
    res_cmp = client.post(
        "/api/ai/eval/playground/compare",
        json={"job_id": "test-job-eval-001", "query": "RAG"},
    )
    assert res_cmp.status_code == 200

    # 5. Debug Retrieval Endpoint
    res_dbg = client.post(
        "/api/ai/eval/playground/debug",
        json={"job_id": "test-job-eval-001", "query": "RAG", "method": "bm25"},
    )
    assert res_dbg.status_code == 200
    assert "tokens" in res_dbg.json()["data"]

    # 6. Execute Run Endpoint
    res_run = client.post(
        "/api/ai/eval/runs",
        json={"dataset_id": ds_id, "job_id": "test-job-eval-001", "method": "bm25"},
    )
    assert res_run.status_code == 200
    run_id = res_run.json()["data"]["run_id"]

    # 7. Get Run
    res_get_run = client.get(f"/api/ai/eval/runs/{run_id}")
    assert res_get_run.status_code == 200

    # 8. Clean up Dataset
    del_res = client.delete(f"/api/ai/eval/datasets/{ds_id}")
    assert del_res.status_code == 200
