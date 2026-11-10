"""Comprehensive test suite for SemanticRepairService and RAG Semantic Repair Pipeline.

Covers:
1. Category and heading misclassification repair.
2. Disconnected dates, percentages, and broken semantic links across adjacent chunks.
3. Residual HTML artifacts and JS injection placeholders stripping.
4. Invalid LLM output, API disconnection, and anti-hallucination verification.
5. Preservation of IDs, URLs, schema, and original text in unnecessary repairs.
6. Non-modification in ambiguous or low-confidence conditions.
7. Selective embedding invalidation (preventing duplicate embedding of unchanged data).
8. API route /api/ai/repair and FileProcessor integration.
"""

from __future__ import annotations

import copy
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.routes_ai import router, set_job_manager
from app.core.config import get_settings
from app.jobs.manager import JobManager
from app.main import app
from app.schemas.chunks import DocumentChunk
from app.schemas.documents import ExtractedDocument
from app.services.chunker import ChunkerService
from app.services.content_cleaner import ContentCleaner
from app.services.file_processor import FileProcessorService
from app.services.semantic_repair import (
    RepairAction,
    SemanticRepairReport,
    SemanticRepairService,
)


@pytest.fixture
def mock_job_manager():
    mgr = JobManager()
    set_job_manager(mgr)
    return mgr


@pytest.fixture
def sample_resume_chunks():
    """Chunks simulating a CV extracted under a portfolio page title."""
    c0 = DocumentChunk(
        chunk_id="chunk_001",
        source_url="https://example.com/portfolio",
        chunk_index=0,
        total_chunks=3,
        text="### شرکت مهندسی نرم‌افزار رایان | توسعه‌دهنده ارشد پایتون (۱۳۹۹ - ۱۴۰۲)\nمسئول طراحی میکروسرویس‌ها و بهینه‌سازی پایگاه داده با FastAPI و Postgres.",
        char_count=135,
        word_count=20,
        heading_context="پروژه‌ها > نمونه‌کارها",
        title="نمونه‌کارها و پروژه‌ها",
        category="portfolio",  # Misclassified due to page title
        content_hash="hash_001",
    )
    c1 = DocumentChunk(
        chunk_id="chunk_002",
        source_url="https://example.com/portfolio",
        chunk_index=1,
        total_chunks=3,
        text="- پیاده‌سازی صف‌های پردازش ناهمگام با Celery و RabbitMQ\n- ارتقای کارایی و سرعت پاسخ‌دهی سیستم تا ۹۰ درصد",
        char_count=107,
        word_count=17,
        heading_context="پروژه‌ها > نمونه‌کارها",
        title="نمونه‌کارها و پروژه‌ها",
        category="portfolio",
        content_hash="hash_002",
    )
    c2 = DocumentChunk(
        chunk_id="chunk_003",
        source_url="https://example.com/portfolio",
        chunk_index=2,
        total_chunks=3,
        text="تحصیلات:\nکارشناسی مهندسی کامپیوتر دانشگاه تهران (۱۳۹۴ - ۱۳۹۸)\nمعدل: ۱۸.۵",
        char_count=73,
        word_count=11,
        heading_context="پروژه‌ها > نمونه‌کارها > سوابق شغلی",  # Stale heading context
        title="نمونه‌کارها و پروژه‌ها",
        category="portfolio",  # Misclassified
        content_hash="hash_003",
    )
    return [c0, c1, c2]


class TestCategoryAndHeadingRepair:
    @pytest.mark.asyncio
    async def test_resume_category_correction_from_portfolio(self, sample_resume_chunks):
        """Resume content should be reclassified to 'resume' instead of 'portfolio'."""
        service = SemanticRepairService(api_key=None)  # deterministic
        repaired, report = await service.repair_chunks(sample_resume_chunks, apply_llm=False)

        assert repaired[0].category == "resume"
        assert repaired[2].category == "resume"
        assert report.category_repairs_count >= 1

    @pytest.mark.asyncio
    async def test_heading_context_correction_on_semantic_shift(self, sample_resume_chunks):
        """Education section inheriting 'سوابق شغلی' should be updated to 'تحصیلات'."""
        service = SemanticRepairService(api_key=None)
        repaired, report = await service.repair_chunks(sample_resume_chunks, apply_llm=False)

        chunk_edu = repaired[2]
        assert "تحصیلات" in (chunk_edu.heading_context or "")
        assert report.heading_repairs_count >= 1

    @pytest.mark.asyncio
    async def test_skills_category_disambiguation(self):
        """Skills list should be classified as 'skills'."""
        chunk = DocumentChunk(
            chunk_id="c_skills",
            source_url="https://example.com/cv",
            chunk_index=0,
            total_chunks=1,
            text="مهارت‌های تخصصی:\nپایتون، داکر، کوبرنتیز، گیت، لینوکس، FastAPI, Redis",
            char_count=65,
            word_count=9,
            category="general",
            heading_context="درباره من",
        )
        service = SemanticRepairService(api_key=None)
        repaired, report = await service.repair_chunks([chunk], apply_llm=False)

        assert repaired[0].category == "skills"
        assert report.category_repairs_count == 1


class TestBrokenSemanticLinksAndAdjacentChunks:
    @pytest.mark.asyncio
    async def test_adjacent_chunk_entity_link(self, sample_resume_chunks):
        """Chunk starting with bullet points should link to predecessor entity."""
        service = SemanticRepairService(api_key=None)
        repaired, report = await service.repair_chunks(sample_resume_chunks, apply_llm=False)

        c1 = repaired[1]
        assert c1.semantic_link is not None
        assert c1.semantic_link["parent_chunk_id"] == sample_resume_chunks[0].chunk_id
        assert "توسعه‌دهنده" in c1.semantic_link["entity"] or "رایان" in c1.semantic_link["entity"]
        assert report.semantic_links_count >= 1

    @pytest.mark.asyncio
    async def test_isolated_percentage_link(self):
        """Micro metric chunk (e.g. 95%) should link to predecessor skill."""
        c0 = DocumentChunk(
            chunk_id="c0",
            source_url="https://example.com",
            chunk_index=0,
            total_chunks=2,
            text="#### مهارت برنامه‌نویسی پایتون",
            char_count=30,
            word_count=4,
        )
        c1 = DocumentChunk(
            chunk_id="c1",
            source_url="https://example.com",
            chunk_index=1,
            total_chunks=2,
            text="۹۵٪",
            char_count=3,
            word_count=1,
        )
        service = SemanticRepairService(api_key=None)
        repaired, report = await service.repair_chunks([c0, c1], apply_llm=False)

        assert repaired[1].semantic_link is not None
        assert repaired[1].semantic_link["parent_chunk_id"] == "c0"
        assert "پایتون" in repaired[1].semantic_link["entity"]


class TestArtifactStrippingAndContentCleaner:
    @pytest.mark.asyncio
    async def test_strip_js_injection_placeholder_from_chunk(self):
        """Chunk with JS injection placeholder should have artifact removed and embedding invalidated."""
        chunk = DocumentChunk(
            chunk_id="c_art",
            source_url="https://example.com",
            chunk_index=0,
            total_chunks=1,
            text="محتوای فرم توسط JS در اینجا تزریق می‌شود\nارتباط مستقیم: info@example.com",
            char_count=70,
            word_count=8,
            embedding=[0.1, 0.2, 0.3],
            content_hash="old_hash",
        )
        service = SemanticRepairService(api_key=None)
        repaired, report = await service.repair_chunks([chunk], apply_llm=False)

        assert "محتوای فرم توسط JS" not in repaired[0].text
        assert "info@example.com" in repaired[0].text
        assert repaired[0].embedding is None  # Invalidated because text changed
        assert repaired[0].metadata.get("embedding_invalidated") is True
        assert report.artifacts_removed_count >= 1
        assert report.embeddings_invalidated_count == 1

    def test_content_cleaner_removes_placeholder_elements(self):
        """ContentCleaner should remove placeholder elements without affecting genuine content."""
        cleaner = ContentCleaner()
        html = """
        <main>
            <h1>تماس با ما</h1>
            <div class="form-placeholder">محتوای فرم توسط JS در اینجا تزریق می‌شود</div>
            <p>جهت هرگونه پرسش با ما تماس بگیرید.</p>
        </main>
        """
        cleaned = cleaner.clean(html)
        assert "محتوای فرم توسط JS" not in cleaned
        assert "تماس با ما" in cleaned
        assert "جهت هرگونه پرسش با ما تماس بگیرید" in cleaned

    def test_content_cleaner_clean_text_artifacts(self):
        """clean_text_artifacts should strip placeholder lines safely."""
        raw = "سلام\nمحتوای فرم توسط JS در اینجا تزریق میشود\nخداحافظ"
        cleaned, removed = ContentCleaner.clean_text_artifacts(raw)
        assert len(removed) == 1
        assert "سلام\nخداحافظ" == cleaned


class TestSelectiveEmbeddingInvalidation:
    @pytest.mark.asyncio
    async def test_unchanged_text_keeps_embedding(self):
        """Chunk whose text was NOT modified must preserve its existing embedding."""
        dummy_vector = [0.05] * 128
        chunk = DocumentChunk(
            chunk_id="c_embed_keep",
            source_url="https://example.com",
            chunk_index=0,
            total_chunks=1,
            text="سوابق کاری توسعه‌دهنده در شرکت الف (۱۳۹۹ - ۱۴۰۲)",
            char_count=48,
            word_count=8,
            category="portfolio",  # Will change to resume
            embedding=copy.copy(dummy_vector),
            content_hash="hash_keep",
        )
        service = SemanticRepairService(api_key=None)
        repaired, report = await service.repair_chunks([chunk], apply_llm=False)

        assert repaired[0].category == "resume"
        # Text did not change! Embedding MUST be preserved
        assert repaired[0].embedding == dummy_vector
        assert repaired[0].metadata.get("embedding_invalidated") is not True
        assert report.embeddings_invalidated_count == 0

    @pytest.mark.asyncio
    async def test_changed_text_invalidates_embedding(self):
        """Chunk whose text changed MUST invalidate its embedding."""
        dummy_vector = [0.05] * 128
        chunk = DocumentChunk(
            chunk_id="c_embed_drop",
            source_url="https://example.com",
            chunk_index=0,
            total_chunks=1,
            text="محتوای فرم توسط JS در اینجا تزریق می‌شود\nتلفن: ۰۲۱۲۳۴۵۶",
            char_count=55,
            word_count=6,
            embedding=dummy_vector,
            content_hash="hash_old",
        )
        service = SemanticRepairService(api_key=None)
        repaired, report = await service.repair_chunks([chunk], apply_llm=False)

        assert repaired[0].embedding is None
        assert repaired[0].metadata.get("embedding_invalidated") is True
        assert report.embeddings_invalidated_count == 1
        assert "c_embed_drop" in report.invalidated_chunk_ids


class TestLLMRepairAndSafeguards:
    @pytest.mark.asyncio
    async def test_llm_low_confidence_rejected(self):
        """LLM proposal with confidence lower than threshold must be rejected."""
        chunk = DocumentChunk(
            chunk_id="c_llm_1",
            source_url="https://example.com",
            chunk_index=0,
            total_chunks=1,
            text="متن معمولی بدون ابهام درباره پروژه نمونه",
            char_count=40,
            word_count=7,
            category="portfolio",
        )
        service = SemanticRepairService(api_key="mock-key", confidence_threshold=0.80)

        # Mock LLM returning low confidence proposal
        mock_response = {
            "repairs": [
                {
                    "chunk_id": "c_llm_1",
                    "field": "category",
                    "proposed_value": "resume",
                    "reason": "حدس ضعیف",
                    "confidence": 0.60,  # Below 0.80
                }
            ]
        }

        with patch.object(service, "_call_llm", AsyncMock(return_value=(mock_response, None))):
            repaired, report = await service.repair_chunks([chunk], apply_llm=True)

        assert repaired[0].category == "portfolio"  # Preserved!
        assert report.repairs_rejected_count >= 1
        rejected_action = next(a for a in report.actions if not a.applied)
        assert "below threshold" in rejected_action.rejection_reason.lower()

    @pytest.mark.asyncio
    async def test_llm_anti_hallucination_number_rejected(self):
        """LLM proposal injecting an unverified number into text must be rejected."""
        chunk = DocumentChunk(
            chunk_id="c_hallucinate",
            source_url="https://example.com",
            chunk_index=0,
            total_chunks=1,
            text="توسعه‌دهنده سیستم در شرکت داده‌ورز",
            char_count=35,
            word_count=5,
            category="resume",
        )
        service = SemanticRepairService(api_key="mock-key", confidence_threshold=0.75)

        # LLM tries to invent salary 5000000 or year 1405
        mock_response = {
            "repairs": [
                {
                    "chunk_id": "c_hallucinate",
                    "field": "text",
                    "proposed_value": "توسعه‌دهنده با حقوق ماهیانه ۵۰۰۰۰۰۰ تومان در شرکت داده‌ورز",
                    "reason": "افزودن جزئیات حدسی",
                    "confidence": 0.95,
                }
            ]
        }

        with patch.object(service, "_call_llm", AsyncMock(return_value=(mock_response, None))):
            repaired, report = await service.repair_chunks([chunk], apply_llm=True)

        assert "۵۰۰۰۰۰۰" not in repaired[0].text
        assert report.repairs_rejected_count >= 1

    @pytest.mark.asyncio
    async def test_llm_api_failure_fallback_deterministic(self):
        """API failure should gracefully fall back to deterministic repair without crashing."""
        chunk = DocumentChunk(
            chunk_id="c_fallback",
            source_url="https://example.com",
            chunk_index=0,
            total_chunks=1,
            text="محتوای فرم توسط JS در اینجا تزریق می‌شود\nتحصیلات: کارشناسی ارشد نرم‌افزار",
            char_count=68,
            word_count=9,
            category="portfolio",
        )
        service = SemanticRepairService(api_key="mock-key")

        with patch.object(service, "_call_llm", AsyncMock(side_effect=Exception("API Connection Refused"))):
            repaired, report = await service.repair_chunks([chunk], apply_llm=True)

        assert report.execution_mode == "fallback_deterministic"
        assert len(report.errors) >= 1
        # Deterministic repair still cleaned the artifact and fixed category!
        assert "محتوای فرم توسط JS" not in repaired[0].text
        assert repaired[0].category == "resume"


class TestPreservationOfIdentitiesAndSchema:
    @pytest.mark.asyncio
    async def test_preservation_when_repair_not_needed(self):
        """Clean valid chunk must preserve IDs, hashes, URL, and text completely."""
        chunk = DocumentChunk(
            chunk_id="stable_123",
            source_url="https://example.com/docs/api",
            chunk_index=5,
            total_chunks=10,
            text="راهنمای استفاده از API سرویس برای برنامه‌نویسان پایتون.",
            char_count=56,
            word_count=8,
            category="docs",
            heading_context="مستندات > API",
            content_hash="exact_hash_123",
        )
        original_dump = chunk.model_dump()

        service = SemanticRepairService(api_key=None)
        repaired, report = await service.repair_chunks([chunk], apply_llm=False)

        assert repaired[0].chunk_id == "stable_123"
        assert repaired[0].source_url == "https://example.com/docs/api"
        assert repaired[0].chunk_index == 5
        assert repaired[0].category == "docs"
        assert repaired[0].heading_context == "مستندات > API"
        assert repaired[0].text == "راهنمای استفاده از API سرویس برای برنامه‌نویسان پایتون."
        assert repaired[0].content_hash == "exact_hash_123"
        assert report.repairs_applied_count == 0


class TestApiRouteAndFileProcessorIntegration:
    def test_api_repair_endpoint_with_direct_chunks(self, mock_job_manager):
        """POST /api/ai/repair should accept chunks list and return repair report."""
        client = TestClient(app)
        chunks_payload = [
            {
                "chunk_id": "api_c1",
                "source_url": "https://example.com",
                "chunk_index": 0,
                "total_chunks": 1,
                "text": "محتوای فرم توسط JS در اینجا تزریق می‌شود\nارتباط: admin@test.com",
                "char_count": 65,
                "word_count": 8,
                "category": "portfolio",
                "content_hash": "h1",
            }
        ]

        resp = client.post(
            "/api/ai/repair",
            json={"chunks": chunks_payload, "apply_llm": False, "re_embed": False},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["report"]["artifacts_removed_count"] >= 1
        assert "admin@test.com" in data["chunks"][0]["text"]
        assert "محتوای فرم توسط JS" not in data["chunks"][0]["text"]

    def test_api_chunk_endpoint_with_semantic_repair_flag(self, mock_job_manager):
        """POST /api/ai/chunk with semantic_repair=True should auto-repair chunks."""
        client = TestClient(app)

        # Create a mock job with an extracted document
        doc = ExtractedDocument(
            url="https://example.com/cv",
            content_text="سوابق شغلی:\nتوسعه‌دهنده نرم‌افزار در شرکت فناور (۱۳۹۸ - ۱۴۰۱)\nتحصیلات: دانشگاه علم و صنعت",
            word_count=15,
            character_count=85,
        )
        job = mock_job_manager.create_extraction_job(
            urls=["https://example.com/cv"],
            config={},
        )
        mock_job_manager.set_documents(job.job_id, [doc])

        resp = client.post(
            "/api/ai/chunk",
            json={
                "job_id": job.job_id,
                "category": "portfolio",  # Intentional misclassification
                "semantic_repair": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["semantic_repair_applied"] is True

        stored_chunks = mock_job_manager.get_chunks(job.job_id)
        assert len(stored_chunks) >= 1
        assert stored_chunks[0].category == "resume"  # Successfully repaired!

    @pytest.mark.asyncio
    async def test_file_processor_operation_semantic_repair(self, tmp_path):
        """FileProcessorService should support 'semantic_repair' in pipeline."""
        processor = FileProcessorService(base_dir=str(tmp_path / "files"))
        raw_text = (
            "محتوای فرم توسط JS در اینجا تزریق می‌شود\n\n"
            "سوابق کاری مهندس داده در شرکت آروان (۱۴۰۱ - اکنون)\n"
            "- مدیریت کلاسترهای اسپارک و پایپ‌لاین‌های کافکا"
        )
        upload_rec = processor.upload_file(
            filename="test_cv.txt",
            content_bytes=raw_text.encode("utf-8"),
        )

        result = await processor.process(
            file_id=upload_rec["file_id"],
            operations=["chunk", "semantic_repair"],
            options={"category": "portfolio"},
        )

        assert "semantic_repair" in result["telemetry"]["operations_applied"]
        artifact = processor.get_artifact(result["artifact_id"])
        assert artifact is not None
        # Verify output artifact parsed chunks no longer have the JS injection placeholder in their text
        import json as json_mod
        chunks_data = json_mod.loads(result["output_preview"])
        assert len(chunks_data) >= 1
        assert "محتوای فرم توسط JS" not in chunks_data[0]["text"]
        assert "سوابق کاری" in chunks_data[0]["text"]
        assert chunks_data[0]["category"] == "resume"
