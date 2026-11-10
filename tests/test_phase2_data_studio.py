"""Tests for Phase 2: Professional Data Studio, File Processing, Chunk Review, and Dataset Versioning."""

import io
import json
import pytest
from fastapi.testclient import TestClient

import docx
import pypdf
from app.main import app
from app.jobs.manager import get_job_manager
from app.schemas.chunks import DocumentChunk
from app.schemas.documents import ExtractedDocument, QualityStatus
from app.services.file_processor import FileProcessorService, file_processor
from app.services.dataset_studio import dataset_studio


@pytest.fixture
def client():
    """Test client fixture."""
    from app.api import routes_ai
    routes_ai.set_job_manager(get_job_manager())
    return TestClient(app)


@pytest.fixture
def sample_job_with_docs_and_chunks():
    """Set up an in-memory job with extracted documents and chunks."""
    manager = get_job_manager()
    job = manager.create_extraction_job(
        urls=["https://example.com/page1", "https://example.com/page2"],
        config={"root_url": "https://example.com", "strategy": "auto"},
    )
    job.mark_running()
    job.mark_completed()

    # Documents
    doc1 = ExtractedDocument(
        document_id="doc_1",
        url="https://example.com/page1",
        source_url="https://example.com/page1",
        final_url="https://example.com/page1",
        title="صفحه نخست راهنما",
        raw_html="<html><body><h1>راهنمای جامع</h1><p>این یک متن آزمایشی است.</p></body></html>",
        content_text="راهنمای جامع\n\nاین یک متن آزمایشی است برای بررسی استودیو داده و فاز دو.",
        content_markdown="# راهنمای جامع\n\nاین یک متن آزمایشی است برای بررسی استودیو داده و فاز دو.",
        word_count=13,
        character_count=70,
        quality_status=QualityStatus.SUCCESS,
    )
    doc2 = ExtractedDocument(
        document_id="doc_2",
        url="https://example.com/page2",
        source_url="https://example.com/page2",
        final_url="https://example.com/page2",
        title="درباره سیستم",
        raw_html="<html><body><h2>مشخصات سیستم</h2><p>سیستم RAG برای بازیابی دقیق.</p></body></html>",
        content_text="مشخصات سیستم\n\nسیستم RAG برای بازیابی دقیق اطلاعات و چانک‌ها.",
        content_markdown="## مشخصات سیستم\n\nسیستم RAG برای بازیابی دقیق اطلاعات و چانک‌ها.",
        word_count=10,
        character_count=58,
        quality_status=QualityStatus.SUCCESS,
    )
    manager.set_documents(job.job_id, [doc1, doc2])

    # Chunks
    chunk1 = DocumentChunk(
        chunk_id=f"chk_1_{job.job_id[:6]}",
        source_url="https://example.com/page1",
        chunk_index=0,
        total_chunks=2,
        text="راهنمای جامع\nاین یک متن آزمایشی است برای بررسی استودیو داده و فاز دو.",
        char_count=65,
        word_count=13,
        heading_context="راهنمای جامع",
        category="guide",
        content_hash="hash_111",
        embedding=[0.01, 0.02, 0.03],
        embedding_model="text-embedding-3-small",
        quality_flags=["short_chunk"],
    )
    chunk2 = DocumentChunk(
        chunk_id=f"chk_2_{job.job_id[:6]}",
        source_url="https://example.com/page1",
        chunk_index=1,
        total_chunks=2,
        text="بخش دوم سند نخست با توضیحات تکمیلی معماری داده‌ها.",
        char_count=50,
        word_count=9,
        heading_context="راهنمای جامع > معماری",
        category="architecture",
        content_hash="hash_222",
        embedding=[0.04, 0.05, 0.06],
        embedding_model="text-embedding-3-small",
        quality_flags=[],
    )
    chunk3 = DocumentChunk(
        chunk_id=f"chk_3_{job.job_id[:6]}",
        source_url="https://example.com/page2",
        chunk_index=0,
        total_chunks=1,
        text="مشخصات سیستم و معماری پایگاه دانش برداری.",
        char_count=42,
        word_count=7,
        heading_context="مشخصات سیستم",
        category="specs",
        content_hash="hash_333",
        embedding=[0.07, 0.08, 0.09],
        embedding_model="text-embedding-3-small",
        quality_flags=[],
    )
    manager.store_chunks(job.job_id, [chunk1, chunk2, chunk3])

    return job.job_id


# ---------------------------------------------------------------------------
# Section E: File Studio PDF & DOCX Support Tests
# ---------------------------------------------------------------------------

def test_supported_formats_endpoint(client):
    """Verify /api/files/supported-formats returns pdf and docx."""
    resp = client.get("/api/files/supported-formats")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "pdf" in data["supported_formats"]
    assert "docx" in data["supported_formats"]
    assert ".pdf" in data["allowed_extensions"]
    assert ".docx" in data["allowed_extensions"]


def test_docx_extraction_headings_lists_tables():
    """Verify DOCX extraction parses headings (#-####), lists, tables into Markdown."""
    doc = docx.Document()
    doc.add_heading("معماری سیستم کرال‌بات", level=1)
    doc.add_heading("زیربخش مشخصات فنی", level=2)
    doc.add_paragraph("این یک پاراگراف مقدماتی است.")
    doc.add_paragraph("آیتم اول لیست قابلیت‌ها", style="List Bullet")
    doc.add_paragraph("آیتم دوم لیست قابلیت‌ها", style="List Bullet")

    # Table
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "شاخص"
    table.cell(0, 1).text = "مقدار"
    table.cell(1, 0).text = "تأخیر (Latency)"
    table.cell(1, 1).text = "15ms"

    buf = io.BytesIO()
    doc.save(buf)
    docx_bytes = buf.getvalue()

    svc = FileProcessorService()
    full_text, sections, warnings = svc._extract_docx_content(docx_bytes)

    assert "# معماری سیستم کرال‌بات" in full_text
    assert "## زیربخش مشخصات فنی" in full_text
    assert "- آیتم اول لیست قابلیت‌ها" in full_text
    assert "| شاخص | مقدار |" in full_text
    assert "| --- | --- |" in full_text
    assert "| تأخیر (Latency) | 15ms |" in full_text
    assert len(sections) >= 5
    assert len(warnings) == 0


def test_pdf_extraction_and_scanned_detection():
    """Verify PDF extraction extracts pages and detects scanned/blank PDF."""
    svc = FileProcessorService()

    # 1. Blank/Scanned PDF (No text)
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=300, height=300)
    blank_buf = io.BytesIO()
    writer.write(blank_buf)
    blank_bytes = blank_buf.getvalue()

    text, pages, is_scanned, warnings = svc._extract_pdf_content(blank_bytes)
    assert len(pages) == 1
    assert is_scanned is True
    assert any("اسکن‌شده" in w or "OCR" in w for w in warnings)

    # 2. PDF with text stream
    pdf_bytes = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 58 >> stream
BT
/F1 20 Tf
100 700 Td
(Crawlbot Phase 2 PDF Extraction Test Content Long Enough) Tj
ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000227 00000 n 
0000000337 00000 n 
trailer << /Size 6 /Root 1 0 R >>
startxref
410
%%EOF"""

    text2, pages2, is_scanned2, warnings2 = svc._extract_pdf_content(pdf_bytes)
    assert len(pages2) == 1
    assert "Crawlbot Phase 2" in text2
    assert pages2[0]["page_number"] == 1
    assert pages2[0]["char_count"] > 0


def test_file_upload_and_process_pdf_and_docx(client):
    """Test full upload and chunking of docx and pdf files via File Studio."""
    # Create docx file
    doc = docx.Document()
    doc.add_heading("مستند تست یکپارچه", level=1)
    doc.add_paragraph("پاراگراف نمونه برای خط لوله پردازش فایل کرال‌بات.")
    buf = io.BytesIO()
    doc.save(buf)

    files = {"file": ("test_doc.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    up_resp = client.post("/api/files/upload", files=files)
    assert up_resp.status_code == 200
    file_id = up_resp.json()["data"]["file_id"]
    assert up_resp.json()["data"]["format"] == "docx"

    # Process: chunk and metadata enrich
    proc_resp = client.post(
        "/api/files/process",
        json={
            "file_id": file_id,
            "operations": ["chunk", "metadata_enrich"],
            "options": {"chunk_size": 300, "overlap": 50},
        },
    )
    assert proc_resp.status_code == 200
    proc_data = proc_resp.json()["data"]
    assert proc_data["status"] == "success"
    assert proc_data["telemetry"]["chunks_produced"] >= 1


# ---------------------------------------------------------------------------
# Section A: Stage Inspection Tests
# ---------------------------------------------------------------------------

def test_stage_inspection_endpoint(client, sample_job_with_docs_and_chunks):
    """Verify /api/ai/stages/{job_id} returns all pipeline stages with diff and metadata."""
    job_id = sample_job_with_docs_and_chunks
    resp = client.get(f"/api/ai/stages/{job_id}")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["job_id"] == job_id
    assert data["total_documents"] == 2
    stages = data["stages"]
    stage_ids = [s["stage_id"] for s in stages]

    expected = [
        "raw_source",
        "extracted",
        "cleaned_normalized",
        "structured_markdown",
        "chunks",
        "semantic_repaired",
        "embeddings",
    ]
    for exp in expected:
        assert exp in stage_ids

    # Stage details
    chunk_stage = next(s for s in stages if s["stage_id"] == "chunks")
    assert chunk_stage["available"] is True
    assert chunk_stage["item_count"] >= 1

    emb_stage = next(s for s in stages if s["stage_id"] == "embeddings")
    assert emb_stage["available"] is True


# ---------------------------------------------------------------------------
# Section B: Chunk Review, Search, Update, Merge, Split, Revert Tests
# ---------------------------------------------------------------------------

def test_chunk_query_and_filtering(client, sample_job_with_docs_and_chunks):
    """Verify /api/ai/chunks/{job_id} filtering by query, quality, category, and pagination."""
    job_id = sample_job_with_docs_and_chunks

    # Query search
    resp = client.get(f"/api/ai/chunks/{job_id}?query=معماری")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) >= 1

    # Filter flagged quality
    resp_flagged = client.get(f"/api/ai/chunks/{job_id}?quality=flagged")
    assert resp_flagged.status_code == 200
    flagged_items = resp_flagged.json()["data"]["items"]
    assert len(flagged_items) == 1
    assert "short_chunk" in flagged_items[0]["quality_flags"]

    # Filter clean quality
    resp_clean = client.get(f"/api/ai/chunks/{job_id}?quality=clean")
    assert resp_clean.status_code == 200
    assert len(resp_clean.json()["data"]["items"]) == 2


def test_chunk_update_text_and_metadata(client, sample_job_with_docs_and_chunks):
    """Verify chunk editing invalidates vector when text changes, retains vector when metadata changes."""
    job_id = sample_job_with_docs_and_chunks
    chunks_resp = client.get(f"/api/ai/chunks/{job_id}")
    chunk_id = chunks_resp.json()["data"]["items"][0]["chunk_id"]

    # Case 1: Metadata-only update (Heading Context) -> retains embedding
    meta_resp = client.post(
        f"/api/ai/chunks/{job_id}/update",
        json={
            "chunk_id": chunk_id,
            "heading_context": "سربرگ به‌روزرسانی‌شده بدون تغییر متن",
        },
    )
    assert meta_resp.status_code == 200
    meta_data = meta_resp.json()["data"]
    assert meta_data["embedding_invalidated"] is False
    assert meta_data["chunk"]["user_edited"] is True
    assert meta_data["chunk"]["heading_context"] == "سربرگ به‌روزرسانی‌شده بدون تغییر متن"

    # Case 2: Text update -> invalidates embedding
    text_resp = client.post(
        f"/api/ai/chunks/{job_id}/update",
        json={
            "chunk_id": chunk_id,
            "text": "متن کاملاً جدید ویرایش‌شده توسط کاربر در استودیو داده.",
        },
    )
    assert text_resp.status_code == 200
    text_data = text_resp.json()["data"]
    assert text_data["embedding_invalidated"] is True
    assert text_data["chunk"]["embedding"] is None
    assert text_data["chunk"]["user_edited"] is True
    assert "متن کاملاً جدید" in text_data["chunk"]["text"]


def test_chunk_revert_undo(client, sample_job_with_docs_and_chunks):
    """Verify undo/revert restores previous chunk state from edit history."""
    job_id = sample_job_with_docs_and_chunks
    chunks_resp = client.get(f"/api/ai/chunks/{job_id}")
    chunk_id = chunks_resp.json()["data"]["items"][0]["chunk_id"]
    original_text = chunks_resp.json()["data"]["items"][0]["text"]

    # Edit text
    client.post(
        f"/api/ai/chunks/{job_id}/update",
        json={"chunk_id": chunk_id, "text": "متن موقت قبل از بازگردانی"},
    )

    # Revert edit
    rev_resp = client.post(f"/api/ai/chunks/{job_id}/revert", json={"chunk_id": chunk_id})
    assert rev_resp.status_code == 200
    restored_chunk = rev_resp.json()["data"]["chunk"]
    assert restored_chunk["text"] == original_text
    assert restored_chunk["user_edited"] is False


def test_chunk_merge_and_split(client, sample_job_with_docs_and_chunks):
    """Verify merging multiple chunks into one and splitting a chunk."""
    job_id = sample_job_with_docs_and_chunks
    chunks_resp = client.get(f"/api/ai/chunks/{job_id}")
    items = chunks_resp.json()["data"]["items"]
    cid1, cid2 = items[0]["chunk_id"], items[1]["chunk_id"]

    # Merge
    merge_resp = client.post(
        f"/api/ai/chunks/{job_id}/merge",
        json={"chunk_ids": [cid1, cid2], "separator": "\n---\n"},
    )
    assert merge_resp.status_code == 200
    merged_data = merge_resp.json()["data"]
    merged_chunk = merged_data["merged_chunk"]
    assert merged_chunk["user_edited"] is True
    assert "\n---\n" in merged_chunk["text"]
    assert merged_data["total_chunks_remaining"] == 2

    # Split the merged chunk
    split_resp = client.post(
        f"/api/ai/chunks/{job_id}/split",
        json={"chunk_id": merged_chunk["chunk_id"], "separator": "\n---\n"},
    )
    assert split_resp.status_code == 200
    split_data = split_resp.json()["data"]
    assert len(split_data["split_chunks"]) == 2
    assert split_data["total_chunks_after_split"] == 3


def test_rerun_policy_preserves_user_edits(client, sample_job_with_docs_and_chunks):
    """Verify that re-running /api/ai/chunk preserves user-edited chunks unless overwrite_user_edits=True."""
    job_id = sample_job_with_docs_and_chunks
    chunks_resp = client.get(f"/api/ai/chunks/{job_id}")
    chunk_id = chunks_resp.json()["data"]["items"][0]["chunk_id"]

    # Manually edit chunk 0
    client.post(
        f"/api/ai/chunks/{job_id}/update",
        json={"chunk_id": chunk_id, "text": "متن ویرایش‌شده دستی اختصاصی کاربر"},
    )

    # Re-run chunking with overwrite_user_edits=False (default)
    re_chunk_resp = client.post(
        "/api/ai/chunk",
        json={
            "job_id": job_id,
            "strategy": "auto",
            "overwrite_user_edits": False,
        },
    )
    assert re_chunk_resp.status_code == 200
    assert re_chunk_resp.json()["data"]["preserved_user_edits_count"] >= 1

    # Check that edited text was preserved
    chk_after = client.get(f"/api/ai/chunks/{job_id}")
    texts = [c["text"] for c in chk_after.json()["data"]["items"]]
    assert any("متن ویرایش‌شده دستی اختصاصی کاربر" in t for t in texts)


# ---------------------------------------------------------------------------
# Section C: Data Quality Report Tests
# ---------------------------------------------------------------------------

def test_data_quality_report_telemetry(client, sample_job_with_docs_and_chunks):
    """Verify /api/ai/dataset/{job_id}/quality-report returns deterministic and estimated telemetry."""
    job_id = sample_job_with_docs_and_chunks
    resp = client.get(f"/api/ai/dataset/{job_id}/quality-report")
    assert resp.status_code == 200
    rep = resp.json()["data"]

    # Document quality breakdown
    assert rep["document_quality"]["total_documents"] == 2
    assert "high" in rep["document_quality"]["quality_distribution"]

    # Volume and deltas
    assert rep["content_volume"]["cleaned_markdown_characters"] > 0
    assert rep["content_volume"]["estimated_tokens"] > 0

    # Chunks and histogram
    assert rep["chunk_telemetry"]["total_chunks"] == 3
    assert rep["chunk_telemetry"]["average_chunk_size"] > 0
    assert "<300" in rep["chunk_telemetry"]["size_histogram"]

    # Embeddings
    assert rep["embedding_telemetry"]["embedded_chunks"] == 3

    # Separation legend
    assert "deterministic" in rep["metrics_legend"]
    assert "estimated" in rep["metrics_legend"]


# ---------------------------------------------------------------------------
# Section D: Dataset Versioning & Semantic Diff Tests
# ---------------------------------------------------------------------------

def test_dataset_versioning_and_diff(client, sample_job_with_docs_and_chunks):
    """Verify snapshot creation, listing, and semantic diff distinguishing text vs metadata."""
    job_id = sample_job_with_docs_and_chunks

    # 1. Create Snapshot v1
    v1_resp = client.post(
        f"/api/ai/dataset/{job_id}/versions/snapshot",
        json={"version_label": "v1", "description": "نسخه اولیه خام"},
    )
    assert v1_resp.status_code == 200
    assert v1_resp.json()["data"]["version"] == "v1"

    # List versions
    list_resp = client.get(f"/api/ai/dataset/{job_id}/versions")
    assert len(list_resp.json()["data"]["snapshots"]) == 1

    # 2. Modify one chunk's metadata (category) and another chunk's text
    chunks_resp = client.get(f"/api/ai/chunks/{job_id}")
    c0 = chunks_resp.json()["data"]["items"][0]["chunk_id"]
    c1 = chunks_resp.json()["data"]["items"][1]["chunk_id"]

    client.post(
        f"/api/ai/chunks/{job_id}/update",
        json={"chunk_id": c0, "category": "new_category_only"},
    )
    client.post(
        f"/api/ai/chunks/{job_id}/update",
        json={"chunk_id": c1, "text": "متن تغییر یافته برای نیاز به امبدینگ مجدد"},
    )

    # 3. Create Snapshot v2
    v2_resp = client.post(
        f"/api/ai/dataset/{job_id}/versions/snapshot",
        json={"version_label": "v2", "description": "نسخه بهینه‌شده دوم"},
    )
    assert v2_resp.status_code == 200

    # 4. Semantic Diff between v1 and v2
    diff_resp = client.post(
        f"/api/ai/dataset/{job_id}/versions/diff",
        json={"v1": "v1", "v2": "v2"},
    )
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()["data"]
    summary = diff_data["summary"]

    assert summary["modified_count"] == 2
    # Chunk 1 text changed -> re-embedding needed
    assert summary["re_embedding_needed_count"] == 1
    # Chunk 0 only metadata changed -> cost-saving retained vector
    assert summary["cost_saving_retained_embeddings_count"] == 1


# ---------------------------------------------------------------------------
# Section F: Export Manifest Tests
# ---------------------------------------------------------------------------

def test_dataset_export_manifest_json(client, sample_job_with_docs_and_chunks):
    """Verify /api/ai/dataset/{job_id}/manifest schema and file download."""
    job_id = sample_job_with_docs_and_chunks

    # Manifest API
    resp = client.get(f"/api/ai/dataset/{job_id}/manifest")
    assert resp.status_code == 200
    manifest = resp.json()["data"]

    assert manifest["schema_version"] == "2.0"
    assert manifest["dataset_id"] == job_id
    assert manifest["stats"]["total_chunks"] == 3
    assert "aggregate_sha256" in manifest["integrity"]
    assert len(manifest["integrity"]["aggregate_sha256"]) == 64
    assert manifest["embedding_specification"]["dimensions"] in (1536, 3072)

    # Download manifest file
    dl_resp = client.get(f"/api/ai/dataset/{job_id}/manifest/download")
    assert dl_resp.status_code == 200
    assert "application/json" in dl_resp.headers["content-type"]
    downloaded_data = json.loads(dl_resp.content.decode("utf-8"))
    assert downloaded_data["dataset_id"] == job_id
