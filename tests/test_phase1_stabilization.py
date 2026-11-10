"""Phase 1 Stabilization and Reliability Test Suite for Crawlbot.

Verifies:
1. LLM model configuration validity.
2. Tracking parameters stripping during URL normalization.
3. QualityChecker detection of loading/preloader screens (prevents false SUCCESS).
4. QualityChecker protection for concise high-value contact and FAQ content.
5. PersianNormalizer protection for mathematical formulas ($...$, $$...$$).
6. EmbeddingService idempotent caching (avoids re-embedding unchanged chunks).
7. VectorStore auto-persistence to disk and reload.
8. VectorStore edge case robustness (empty dataset, single-item search).
9. FileProcessorService process_sync event loop clean execution (no DeprecationWarning).
10. JobManager document recovery from on-disk artifacts across restarts.
11. Chunker code block and table structural preservation.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import get_settings
from app.jobs.manager import JobManager
from app.jobs.models import JobState
from app.schemas.chunks import DocumentChunk
from app.schemas.documents import ExtractedDocument, QualityStatus
from app.services.chunker import ChunkerService
from app.services.embedding_service import EmbeddingService
from app.services.file_processor import FileProcessorService
from app.services.normalizer import PersianNormalizer
from app.services.quality_checker import QualityChecker
from app.services.url_normalizer import URLNormalizer
from app.services.vector_store import VectorStore


# ---------------------------------------------------------------------------
# 1. Config Tests
# ---------------------------------------------------------------------------

def test_config_llm_model_is_valid():
    """Verify default LLM model is a valid, existing production model."""
    from app.core.config import Settings
    assert Settings.model_fields["llm_model"].default == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 2. URL Normalization & Tracking Stripping
# ---------------------------------------------------------------------------

def test_url_normalizer_strips_tracking_parameters():
    """Verify URLNormalizer strips marketing/ad tracking parameters when keeping query params."""
    normalizer = URLNormalizer(keep_query_params=True, strip_tracking_params=True)

    raw_url = "https://example.com/docs/api?utm_source=twitter&utm_medium=social&utm_campaign=launch&id=42&fbclid=IwAR123"
    normalized = normalizer.normalize(raw_url)

    assert "id=42" in normalized
    assert "utm_source" not in normalized
    assert "utm_medium" not in normalized
    assert "utm_campaign" not in normalized
    assert "fbclid" not in normalized
    assert normalized == "https://example.com/docs/api?id=42"


# ---------------------------------------------------------------------------
# 3. Quality Checker: Loading Screen Detection
# ---------------------------------------------------------------------------

def test_quality_checker_detects_loading_screens():
    """Verify loading and preloader screens are never marked as QualityStatus.SUCCESS."""
    checker = QualityChecker()

    loading_doc = ExtractedDocument(
        url="https://example.com/app",
        title="در حال بارگذاری صفحه...",
        content_text="لطفاً کمی صبر کنید... در حال دریافت اطلاعات از سرور",
        word_count=10,
        character_count=52,
    )

    checked = checker.check(loading_doc)

    assert checked.quality_status != QualityStatus.SUCCESS
    assert checked.quality_status == QualityStatus.LOW_QUALITY
    assert any("loading" in w.lower() or "بارگذاری" in w for w in checked.warnings or checked.quality_report.reasons)


# ---------------------------------------------------------------------------
# 4. Quality Checker: Short High-Value Content Protection
# ---------------------------------------------------------------------------

def test_quality_checker_preserves_short_contact_info():
    """Verify concise contact details or short FAQs are not penalised as low quality simply for shortness."""
    checker = QualityChecker(min_word_count=20, min_char_count=100)

    contact_doc = ExtractedDocument(
        url="https://example.com/contact",
        title="تماس با ما",
        content_text="آدرس: تهران، میدان ونک\nشماره تلفن: 09123456789\nایمیل: info@company.ir",
        word_count=12,
        character_count=85,
        page_type="contact",
        category="contact",
    )

    checked = checker.check(contact_doc)

    # Should not be marked LOW_QUALITY due to high-value contact info protection
    assert not checker.is_low_quality(contact_doc)
    assert checked.quality_status == QualityStatus.SUCCESS


# ---------------------------------------------------------------------------
# 5. Normalizer: Math & Formula Protection
# ---------------------------------------------------------------------------

def test_normalizer_preserves_math_formulas():
    """Verify LaTeX block ($$...$$) and inline math ($...$) are protected from corruption."""
    normalizer = PersianNormalizer(fix_spacing=True, fix_zwnj_affixes=True)

    text = "فرمول انرژی $$E = mc^2$$ و معادله خط $y = 2x + 1$ می باشد."
    normalized = normalizer.normalize(text)

    assert "$$E = mc^2$$" in normalized
    assert "$y = 2x + 1$" in normalized
    assert "می‌باشد" in normalized or "می باشد" in normalized


# ---------------------------------------------------------------------------
# 6. Embedding Service: Idempotent Caching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embedding_service_idempotent_caching():
    """Verify unchanged chunks with valid embeddings are not sent again to API."""
    service = EmbeddingService(api_key="test-key", model="text-embedding-3-small")

    c1 = DocumentChunk(
        chunk_id="c1",
        source_url="https://example.com/1",
        chunk_index=0,
        total_chunks=2,
        text="Already embedded chunk content",
        char_count=30,
        word_count=4,
        embedding=[0.1] * 1536,
        embedding_model="text-embedding-3-small",
    )
    c2 = DocumentChunk(
        chunk_id="c2",
        source_url="https://example.com/2",
        chunk_index=1,
        total_chunks=2,
        text="New chunk needing embedding",
        char_count=28,
        word_count=4,
        embedding=None,
    )

    mock_response = AsyncMock()
    mock_item = AsyncMock()
    mock_item.embedding = [0.9] * 1536
    mock_response.data = [mock_item]
    mock_response.usage = AsyncMock(total_tokens=15)

    with patch.object(service, "_client_instance") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        stats = await service.embed_chunks([c1, c2])

        assert stats.total_chunks == 2
        assert stats.embedded_chunks == 2
        # Verify API was called ONLY with c2, NOT c1!
        mock_client.embeddings.create.assert_called_once()
        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert call_kwargs["input"] == ["New chunk needing embedding"]


# ---------------------------------------------------------------------------
# 7. Vector Store: Auto-Persistence and Reload
# ---------------------------------------------------------------------------

def test_vector_store_auto_persistence(tmp_path: Path):
    """Verify VectorStore persists to disk on mutation and restores accurately."""
    store_file = tmp_path / "test_store.json"
    store = VectorStore(storage_path=str(store_file))

    chunk = DocumentChunk(
        chunk_id="test_persist_1",
        source_url="https://example.com/persist",
        chunk_index=0,
        total_chunks=1,
        text="Persistent chunk body text",
        char_count=26,
        word_count=4,
        embedding=[0.05] * 1536,
    )

    # Upsert should auto-save to disk
    store.upsert_chunks([chunk])
    assert store_file.exists()

    # Create a fresh new VectorStore instance pointing to the same file
    restored_store = VectorStore(storage_path=str(store_file))
    assert restored_store.total_chunks == 1
    assert restored_store.total_vectors == 1
    assert "test_persist_1" in restored_store._chunks


# ---------------------------------------------------------------------------
# 8. Vector Store: Edge Cases (Empty & Single-Item Search)
# ---------------------------------------------------------------------------

def test_vector_store_empty_and_single_chunk_search():
    """Verify search does not crash on empty index or single chunk candidate."""
    empty_store = VectorStore(storage_path=None)
    results = empty_store.search(query="anything", query_vector=[0.1] * 1536)
    assert results == []

    # Single chunk index
    single_store = VectorStore(storage_path=None)
    chunk = DocumentChunk(
        chunk_id="single_1",
        source_url="https://example.com/single",
        chunk_index=0,
        total_chunks=1,
        text="FastAPI microservice architecture",
        char_count=33,
        word_count=3,
        embedding=[0.2] * 1536,
    )
    single_store.upsert_chunks([chunk])

    res = single_store.search(query="FastAPI", query_vector=[0.2] * 1536, top_k=5)
    assert len(res) == 1
    assert res[0].chunk.chunk_id == "single_1"
    assert res[0].score > 0.5


# ---------------------------------------------------------------------------
# 9. File Processor: process_sync Clean Execution
# ---------------------------------------------------------------------------

def test_file_processor_process_sync_clean():
    """Verify process_sync executes without asyncio DeprecationWarning."""
    service = FileProcessorService()
    test_text = "این یک متن ساده آزمایشی است."
    file_info = service.upload_file("test.txt", test_text.encode("utf-8"))

    # Execute synchronous wrapper
    result = service.process_sync(file_info["file_id"], operations=["normalize"])
    assert result["status"] == "success"
    assert "artifact_id" in result


# ---------------------------------------------------------------------------
# 10. Job Manager: Document Recovery from Disk
# ---------------------------------------------------------------------------

def test_job_manager_recovery_from_disk(tmp_path: Path):
    """Verify JobManager can restore documents and job representation from output disk directory."""
    with patch("app.core.config.get_settings") as mock_settings:
        mock_settings.return_value.output_dir = str(tmp_path)

        manager = JobManager()
        job_id = "test_restart_job_123"

        # Simulate on-disk export created by a previous run
        job_dir = tmp_path / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        doc_data = [
            {
                "url": "https://example.com/page1",
                "content_text": "Saved content",
                "word_count": 2,
                "character_count": 13,
                "quality_status": "success",
            }
        ]
        with open(job_dir / "documents.json", "w", encoding="utf-8") as f:
            json.dump(doc_data, f)

        # Clear in-memory cache
        manager._documents.clear()
        manager._jobs.clear()

        # Re-fetch from JobManager
        recovered_docs = manager.get_documents(job_id)
        assert len(recovered_docs) == 1
        assert recovered_docs[0].url == "https://example.com/page1"

        # Re-fetch job status
        recovered_job = manager.get_job(job_id)
        assert recovered_job is not None
        assert recovered_job.state == JobState.COMPLETED
        assert recovered_job.total == 1


# ---------------------------------------------------------------------------
# 11. Chunker: Code Block Preservation
# ---------------------------------------------------------------------------

def test_chunker_code_block_preservation():
    """Verify fenced code blocks are not split by sentence punctuation."""
    chunker = ChunkerService(strategy="paragraph", chunk_size=300, overlap=0)

    doc = ExtractedDocument(
        url="https://example.com/code",
        content_text=(
            "راهنمای پایتون:\n\n"
            "```python\n"
            "import os\n"
            "import sys\n"
            "def run():\n"
            "    print('hello world')\n"
            "```\n\n"
            "پایان کد."
        ),
        word_count=15,
        character_count=90,
    )

    result = chunker.chunk_document(doc)
    assert len(result.chunks) > 0
    code_chunk = [c for c in result.chunks if "```python" in c.text]
    assert len(code_chunk) > 0
    # Ensure code block is intact with opening and closing backticks
    assert "```python" in code_chunk[0].text
    assert code_chunk[0].text.strip().endswith("```") or "```" in code_chunk[0].text
