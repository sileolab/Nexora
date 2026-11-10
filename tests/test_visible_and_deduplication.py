"""Tests for visible-only content extraction and comprehensive deduplication across exports, RAG, and file processing."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.documents import ExtractedDocument, QualityStatus
from app.schemas.requests import ExportRequest, ExtractionRequest, SingleExtractRequest
from app.services.export_service import ExportService
from app.services.extractors.playwright_engine import PlaywrightEngine
from app.services.file_processor import FileProcessorService


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Tests for Playwright Visible-Only DOM Pruning
# ---------------------------------------------------------------------------

class TestPlaywrightVisibleOnlyPruning:
    """Verifies that 'visible_only' extracts solely what the user sees after page load."""

    MOCK_SPA_HTML = """<!DOCTYPE html>
    <html lang="fa">
    <head><title>وب‌سایت نمونه مهندس</title></head>
    <body>
        <nav class="navbar">
            <a href="/about">درباره من</a>
            <a href="/resume">رزومه</a>
            <a href="/services">خدمات</a>
        </nav>
        <main id="main-content">
            <!-- Active Tab: About -->
            <div id="tab-about" class="tab-pane active" style="display: block;">
                <h1>درباره من - یونس ابراهیمی</h1>
                <p>درود، من توسعه‌دهنده نرم‌افزار و هوش مصنوعی هستم.</p>
                <div class="stats"><span>۵ پروژه موفق</span></div>
            </div>

            <!-- Inactive Hidden Tab: Resume -->
            <div id="tab-resume" class="tab-pane" style="display: none;">
                <h2>رزومه و سوابق کاری</h2>
                <p>توسعه‌دهنده پایتون و بک‌اند از سال ۱۴۰۲ تاکنون.</p>
            </div>

            <!-- Inactive Hidden Tab: Services -->
            <div id="tab-services" class="tab-pane" style="visibility: hidden;">
                <h2>خدمات هوشمندسازی</h2>
                <p>ارائه راهکارهای هوش مصنوعی و اتوماسیون وب‌سایت.</p>
            </div>

            <!-- Inactive Tab with aria-hidden -->
            <div id="tab-skills" aria-hidden="true">
                <h2>مهارت‌ها</h2>
                <p>FastAPI, Docker, PyTorch</p>
            </div>

            <!-- Element with hidden attribute -->
            <div id="popup-modal" hidden>
                <p>پنجره تخفیف ویژه پنهان</p>
            </div>
        </main>
    </body>
    </html>
    """

    def test_visible_only_prunes_hidden_tabs_and_styles(self):
        """When visible_only=True, inactive tabs and display:none elements must be removed."""
        engine = PlaywrightEngine(headless=True)
        result = engine._extract_internal.__wrapped__ if hasattr(engine._extract_internal, "__wrapped__") else None

        # Test static DOM parser with visible_only=True
        from app.services.extractors.base import EngineResult
        res = EngineResult(engine="playwright", success=False)
        engine._parse_static_html(
            html=self.MOCK_SPA_HTML,
            url="https://younesebrahimi.ir/fa/about",
            result=res,
            visible_only=True,
        )

        assert res.success is True
        text = res.text or ""
        markdown = res.markdown or ""

        # Visible active tab content must be present
        assert "درباره من - یونس ابراهیمی" in text
        assert "توسعه‌دهنده نرم‌افزار و هوش مصنوعی" in text

        # Hidden elements must be pruned completely
        assert "رزومه و سوابق کاری" not in text
        assert "خدمات هوشمندسازی" not in text
        assert "FastAPI, Docker, PyTorch" not in text
        assert "پنجره تخفیف ویژه پنهان" not in text

        # Also verified in markdown
        assert "FastAPI" not in markdown
        assert "رزومه" not in markdown

    def test_visible_only_false_preserves_full_dom_backward_compatible(self):
        """When visible_only=False (default), entire DOM is parsed as before."""
        engine = PlaywrightEngine(headless=True)
        from app.services.extractors.base import EngineResult
        res = EngineResult(engine="playwright", success=False)
        engine._parse_static_html(
            html=self.MOCK_SPA_HTML,
            url="https://younesebrahimi.ir/fa/about",
            result=res,
            visible_only=False,
        )

        assert res.success is True
        text = res.text or ""
        # All tabs present when visible_only is False
        assert "درباره من" in text
        assert "رزومه و سوابق کاری" in text
        assert "خدمات هوشمندسازی" in text


# ---------------------------------------------------------------------------
# 2. Tests for Extraction and Export Deduplication
# ---------------------------------------------------------------------------

class TestExportDeduplication:
    """Verifies that ExportService and /api/export/download properly omit duplicate documents."""

    def _create_mock_docs(self) -> list[ExtractedDocument]:
        content1 = "# صفحه اصلی\n\nاین یک متن تستی درباره خدمات هوش مصنوعی است."
        content2 = "# صفحه تماس\n\nجهت ارتباط با ما ایمیل بزنید: test@example.com"
        # Duplicate of content1 with different URL
        content3 = content1

        h1 = hashlib.sha256(content1.encode("utf-8")).hexdigest()
        h2 = hashlib.sha256(content2.encode("utf-8")).hexdigest()
        h3 = h1

        doc1 = ExtractedDocument(
            url="https://example.com/page1",
            source_url="https://example.com/page1",
            title="صفحه اصلی",
            content_markdown=content1,
            content_text=content1,
            content_hash=h1,
            word_count=len(content1.split()),
            quality_status=QualityStatus.SUCCESS,
        )
        doc2 = ExtractedDocument(
            url="https://example.com/contact",
            source_url="https://example.com/contact",
            title="تماس",
            content_markdown=content2,
            content_text=content2,
            content_hash=h2,
            word_count=len(content2.split()),
            quality_status=QualityStatus.SUCCESS,
        )
        doc3 = ExtractedDocument(
            url="https://example.com/duplicate_page",
            source_url="https://example.com/duplicate_page",
            title="صفحه کپی",
            content_markdown=content3,
            content_text=content3,
            content_hash=h3,
            word_count=len(content3.split()),
            quality_status=QualityStatus.DUPLICATE,
        )
        return [doc1, doc2, doc3]

    def test_export_json_deduplicates(self, tmp_path):
        service = ExportService(output_dir=tmp_path)
        docs = self._create_mock_docs()

        # Without dedup: 3 documents
        p_all = service.export_json(docs, job_id="job_all", deduplicate=False)
        with open(p_all, "r", encoding="utf-8") as f:
            data_all = json.load(f)
        assert len(data_all) == 3

        # With dedup: 2 documents
        p_dedup = service.export_json(docs, job_id="job_dedup", deduplicate=True)
        with open(p_dedup, "r", encoding="utf-8") as f:
            data_dedup = json.load(f)
        assert len(data_dedup) == 2
        urls = [d["url"] for d in data_dedup]
        assert "https://example.com/duplicate_page" not in urls
        assert "https://example.com/page1" in urls
        assert "https://example.com/contact" in urls

    def test_export_jsonl_deduplicates(self, tmp_path):
        service = ExportService(output_dir=tmp_path)
        docs = self._create_mock_docs()

        p_dedup = service.export_jsonl(docs, job_id="job_jsonl", deduplicate=True)
        with open(p_dedup, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 2

    def test_export_markdown_deduplicates(self, tmp_path):
        service = ExportService(output_dir=tmp_path)
        docs = self._create_mock_docs()

        folder = service.export_markdown(docs, job_id="job_md", deduplicate=True)
        md_files = list(folder.glob("*.md"))
        assert len(md_files) == 2

    def test_export_text_deduplicates(self, tmp_path):
        service = ExportService(output_dir=tmp_path)
        docs = self._create_mock_docs()

        folder = service.export_text(docs, job_id="job_txt", deduplicate=True)
        txt_files = list(folder.glob("*.txt"))
        assert len(txt_files) == 2

    def test_export_request_schema_supports_deduplicate(self):
        req = ExportRequest(job_id="test_job", format="json", deduplicate=True)
        assert req.deduplicate is True

        req_default = ExportRequest(job_id="test_job")
        assert req_default.deduplicate is False

    def test_api_export_download_endpoint_with_deduplicate(self, client):
        from app.api.routes_exports import get_manager
        mgr = get_manager()
        job = mgr.create_extraction_job(["https://example.com/p1", "https://example.com/p2"], config={})
        docs = self._create_mock_docs()
        mgr._documents[job.job_id] = docs
        job.documents = [d.model_dump(mode="json") for d in docs]

        # Request with deduplicate=True
        resp_dedup = client.post("/api/export/download", json={
            "job_id": job.job_id,
            "format": "json",
            "deduplicate": True
        })
        assert resp_dedup.status_code == 200
        data_dedup = resp_dedup.json()
        assert len(data_dedup) == 2

        # Request with deduplicate=False
        resp_all = client.post("/api/export/download", json={
            "job_id": job.job_id,
            "format": "json",
            "deduplicate": False
        })
        assert resp_all.status_code == 200
        data_all = resp_all.json()
        assert len(data_all) == 3


# ---------------------------------------------------------------------------
# 3. Tests for File Processing Studio Deduplication Operation
# ---------------------------------------------------------------------------

class TestFileProcessingDeduplication:
    """Verifies that FileProcessorService provides dedicated deduplication on files."""

    def test_op_deduplicate_on_json_list(self):
        service = FileProcessorService()
        items = [
            {"id": 1, "text": "محتوای مقاله اول", "content_hash": "hash_1", "url": "https://a.com"},
            {"id": 2, "text": "محتوای مقاله دوم", "content_hash": "hash_2", "url": "https://b.com"},
            {"id": 3, "text": "محتوای مقاله اول", "content_hash": "hash_1", "url": "https://c.com"},
            {"id": 4, "text": "محتوای مقاله سوم", "content_hash": "hash_3", "url": "https://d.com"},
        ]

        result, stats = service._op_deduplicate(items, "json", {})
        assert len(result) == 3
        assert stats["duplicates_removed"] == 1
        assert stats["unique_records"] == 3
        # Alternate sources provenance recorded
        assert "https://c.com" in result[0].get("alternate_sources", [])

    def test_op_deduplicate_on_jsonl_string(self):
        service = FileProcessorService()
        jsonl_str = (
            '{"id": 1, "text": "متن تکراری A"}\n'
            '{"id": 2, "text": "متن یکتا B"}\n'
            '{"id": 1, "text": "متن تکراری A"}\n'
        )

        result, stats = service._op_deduplicate(jsonl_str, "jsonl", {})
        lines = [line for line in result.splitlines() if line.strip()]
        assert len(lines) == 2
        assert stats["duplicates_removed"] == 1

    def test_file_process_pipeline_with_deduplicate(self, tmp_path):
        service = FileProcessorService(base_dir=str(tmp_path))
        raw_json = json.dumps([
            {"title": "Doc 1", "content": "پروژه هوش مصنوعی با پایتون و فست‌ای‌پی‌آی", "url": "https://u1.com"},
            {"title": "Doc 2", "content": "پروژه متفاوت وب‌اسکرپینگ", "url": "https://u2.com"},
            {"title": "Doc 3", "content": "پروژه هوش مصنوعی با پایتون و فست‌ای‌پی‌آی", "url": "https://u3.com"},
        ], ensure_ascii=False)

        upload_res = service.upload_file("test_data.json", raw_json.encode("utf-8"))
        file_id = upload_res["file_id"]

        result = service.process_sync(
            file_id=file_id,
            operations=["normalize", "deduplicate"],
            options={},
        )

        assert "deduplicate" in result["telemetry"]["operations_applied"]
        assert result["telemetry"]["duplicates_removed"] == 1
        assert result["telemetry"]["records_out"] == 2

    def test_file_process_pipeline_deduplicate_and_chunk(self, tmp_path):
        service = FileProcessorService(base_dir=str(tmp_path))
        raw_json = json.dumps([
            {"title": "Page A", "text": "# تیتر اول\n\nتوضیحات مفصل درباره خدمات مهندسی RAG.", "url": "https://u1.com"},
            {"title": "Page B", "text": "# تیتر اول\n\nتوضیحات مفصل درباره خدمات مهندسی RAG.", "url": "https://u2.com"},
        ], ensure_ascii=False)

        upload_res = service.upload_file("docs.json", raw_json.encode("utf-8"))
        file_id = upload_res["file_id"]

        result = service.process_sync(
            file_id=file_id,
            operations=["deduplicate", "chunk"],
            options={"chunk_size": 500, "overlap": 50},
        )

        assert result["telemetry"]["chunks_produced"] > 0
        assert result["telemetry"]["duplicates_removed"] == 1

    def test_api_files_process_endpoint_deduplicate(self, client):
        raw_json = json.dumps([
            {"id": "doc1", "content": "تست یکپارچه API"},
            {"id": "doc2", "content": "تست یکپارچه API"},
        ], ensure_ascii=False)

        # Upload
        up_resp = client.post(
            "/api/files/upload",
            files={"file": ("api_test.json", raw_json.encode("utf-8"), "application/json")},
        )
        assert up_resp.status_code == 200
        file_id = up_resp.json()["data"]["file_id"]

        # Process with deduplicate
        proc_resp = client.post(
            "/api/files/process",
            json={"file_id": file_id, "operations": ["deduplicate"]},
        )
        assert proc_resp.status_code == 200
        proc_data = proc_resp.json()["data"]
        assert proc_data["telemetry"]["duplicates_removed"] == 1
        assert proc_data["telemetry"]["records_out"] == 1


# ---------------------------------------------------------------------------
# 4. Tests for Request Aliases and Visible-Only Schemas
# ---------------------------------------------------------------------------

class TestExtractionRequestVisibleOnly:
    """Verifies that ExtractionRequest and SingleExtractRequest carry visible_only configuration."""

    def test_extraction_request_accepts_visible_only(self):
        req = ExtractionRequest(
            urls=["https://example.com/test"],
            visible_only=True,
        )
        assert req.visible_only is True

    def test_extraction_request_alias_extract_visible_only(self):
        req = ExtractionRequest.model_validate({
            "urls": ["https://example.com/test"],
            "extract_visible_only": True,
        })
        assert req.visible_only is True

    def test_single_extract_request_visible_only(self):
        req = SingleExtractRequest(
            url="https://example.com/about",
            visible_only=True,
        )
        assert req.visible_only is True
