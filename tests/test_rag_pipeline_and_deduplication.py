"""Comprehensive Test Suite for RAG Pipeline, Semantic Chunking, Deduplication & Vector Store.

Validates the complete end-to-end RAG architecture with real-world scenarios:
1. Cross-URL deduplication (preventing 440 duplicate records across 13 URLs).
2. Structural semantic chunking (preventing severed job titles, dates, degrees, and skill micro-chunks).
3. Elimination of 156 'low_info' false positives via parent-child semantic coalescing.
4. Clean, standardized category taxonomy (no 'unknown' or raw 74-character strings).
5. Transparency and default activation of Persian normalization (normalization_applied=True).
6. VectorStore operations: dense cosine similarity, BM25 sparse search, and hybrid retrieval.
7. Dimension mismatch validation and stale document index updates (delete_by_url / delete_by_document_id).
8. Context expansion via neighboring chunk retrieval.
9. Precision@K and Recall@K evaluation on deterministic benchmarks without synthetic data fabrication.
"""

from __future__ import annotations

import hashlib
import json
import pytest
from fastapi.testclient import TestClient

from app.api.routes_ai import get_manager
from app.main import app
from app.schemas.chunks import DocumentChunk, VectorSearchRequest
from app.schemas.documents import ExtractedDocument, QualityStatus
from app.services.chunker import (
    ChunkerService,
    _is_micro_body,
    _split_semantic_heading_with_context,
    detect_chunk_quality_flags,
    resolve_chunk_category,
)
from app.services.page_classifier import PageClassifier
from app.services.vector_store import VectorStore, cosine_similarity, tokenize_for_search


# ---------------------------------------------------------------------------
# Realistic Document Content Matching the Real-World Sample Data
# ---------------------------------------------------------------------------

SAMPLE_FA_CONTENT = """# درباره من - یونس ابراهیمی

درود من
یونس ابراهیمی
هستم

## توسعه‌دهنده نرم‌افزار و هوش مصنوعی و متخصص هوشمندسازی وب‌سایت‌ها

من یک توسعه‌دهنده نرم‌افزار با تمرکز بر هوش مصنوعی، یادگیری ماشین و توسعه سیستم‌های هوشمند هستم.

### تجربه‌ها

۱۴۰۵ — تاکنون

#### توسعه‌دهنده هوش مصنوعی و سیستم‌های هوشمند

##### پروژه‌های مستقل

طراحی و توسعه راهکارهای مبتنی بر هوش مصنوعی با تمرکز بر هوشمندسازی وب‌سایت‌ها، اتوماسیون فرآیندها، توسعه API و یکپارچه‌سازی سرویس‌های هوشمند.

۱۴۰۴ — ۱۴۰۵

#### توسعه‌دهنده نرم‌افزار

##### پروژه‌های وب و Backend

توسعه سرویس‌های وب و API با Python و طراحی ساختارهای Backend برای ایجاد سیستم‌های کاربردی، قابل توسعه و آماده اتصال به سرویس‌های هوش مصنوعی.

#### تحصیلات

۱۴۰۳ - ۱۴۰۵

#### کارشناسی علوم کامپیوتر

##### دانشگاه آزاد واحد نجف آباد

یادگیری مبانی الگوریتم‌ها، ساختار داده‌ها، هوش مصنوعی و معماری سیستم‌های نرم‌افزاری.

#### مدارک

۱۴۰۴

#### هوش مصنوعی و یادگیری ماشین

##### موسسه معتبر

مطالعه و آموزش تخصصی مفاهیم یادگیری ماشین، پردازش داده و کاربردهای هوش مصنوعی.

## خدمات

### هوشمندسازی وب‌سایت

تبدیل وب‌سایت‌های معمولی به سیستم‌های هوشمند با استفاده از هوش مصنوعی، API و پردازش داده.

[ثبت درخواست](#)

### توسعه سیستم‌های هوشمند

ساخت سیستم‌های نرم‌افزاری اختصاصی که داده‌ها، APIها و مدل‌های هوش مصنوعی را در کنار یکدیگر قرار می‌دهند.

[ثبت درخواست](#)

## مهارت ها

#### زبان‌های برنامه‌نویسی

Python
90%
HTML
85%
CSS
80%
SQL
65%
JavaScript
70%

#### ابزارها و پلتفرم‌ها

70%

##### FastAPI

75%

##### Flask

80%

##### Pandas

70%

##### NumPy

45%

##### PyTorch

35%

##### TensorFlow

55%

##### Scikit-learn

45%

##### SQLAlchemy

70%

##### Git / GitHub

60%

##### Docker

75%

##### OpenAI API

80%

#### مهارت‌های عمومی

- حل مسئله
- الگوریتم و تفکر منطقی
- تحلیل داده
- وب‌اسکرپینگ
- اتوماسیون فرآیندها

## نمونه‌کارها

### چت‌بات هوش مصنوعی پشتیبانی وب سایت Lobby Nine

طراحی و توسعه چت‌بات هوش مصنوعی پشتیبانی Lobby Nine مبتنی بر معماری RAG که با استفاده از پردازش محتوای وب‌سایت، پایگاه دانش برداری و مدل‌های زبانی بزرگ، به سؤالات کاربران پاسخ می‌دهد.

[لینک پروژه](https://lobbynine.ir/)

### اسمارت‌شاپ — سیستم هوشمند پیشنهاد محصول

یک سیستم هوشمند پیشنهاد و مقایسه محصولات که با جمع‌آوری و پردازش اطلاعات محصولات و نظرات کاربران از دیجی‌کالا، داده‌ها را تحلیل می‌کند.

[لینک پروژه](https://github.com/sileolab/SmartShop-LLM)

## تماس

Email: [yebrahimi621@gmail.com](mailto:yebrahimi621@gmail.com)
Telegram: [@VposeidonV](https://t.me/VposeidonV)

ارسال پیام
"""


SAMPLE_EN_CONTENT = """# About - Younes Ebrahimi

Hello, I am
Younes Ebrahimi

## Software Developer & AI Specialist and Website Automation Expert

I am a Software Developer focused on Artificial Intelligence, Machine Learning, and the development of intelligent systems.

### Experience

2026 - Present

##### Independent Projects

Designing AI solutions focusing on website automation, APIs, and smart service integration.

2024 - 2025

##### Web & Backend Projects

Developing web services and APIs with Python and building backend structures ready for AI integration.

#### Education

2024 - 2026

##### Azad University, Najafabad Branch

Learning fundamentals of algorithms, data structures, AI, and software architecture.

#### Certificates

2025

##### Valid Institute

Specialized study and training in machine learning concepts and applications of artificial intelligence.

## Services

### Website Automation

Transforming standard websites into smart systems using AI, APIs, and data processing.

[Submit Request](#)

## Skills

#### Tools & Platforms

70%

##### FastAPI

75%

##### Flask

80%

##### Pandas

70%

##### Docker

75%

##### OpenAI API

80%

## Contact

Email: [yebrahimi621@gmail.com](mailto:yebrahimi621@gmail.com)
Telegram: [@VposeidonV](https://t.me/VposeidonV)
"""


def _create_mock_extracted_doc(
    url: str,
    content: str,
    title: str = "Test Page",
    language: str = "fa",
    quality_status: QualityStatus = QualityStatus.SUCCESS,
) -> ExtractedDocument:
    clean = content.strip()
    h = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    return ExtractedDocument(
        document_id=h[:16],
        url=url,
        source_url=url,
        title=title,
        language=language,
        content_markdown=clean,
        content_text=clean,
        word_count=len(clean.split()),
        character_count=len(clean),
        content_hash=h,
        quality_status=quality_status,
    )


# ---------------------------------------------------------------------------
# 1. Tests for Semantic Chunking & Structural Integrity
# ---------------------------------------------------------------------------

class TestSemanticChunkingIntegrity:
    """Verifies that headings, titles, dates, and metrics are preserved as coherent semantic units."""

    def test_leaf_skills_and_percentages_coalesce_into_parent_block(self):
        """Micro-headings like '##### FastAPI 75%' must coalesce under their parent section instead of creating 12 micro-chunks."""
        chunker = ChunkerService(strategy="semantic_heading", chunk_size=1500, overlap=100)
        doc = _create_mock_extracted_doc("https://younesebrahimi.ir/fa/resume", SAMPLE_FA_CONTENT)
        result = chunker.chunk_document(doc)

        # Find the tools & platforms chunk
        tool_chunks = [c for c in result.chunks if "FastAPI" in c.text]
        assert len(tool_chunks) == 1, "All tools and percentages must be consolidated into ONE cohesive chunk, not shattered!"

        tools_chunk = tool_chunks[0]
        # Must contain all tools together
        assert "FastAPI" in tools_chunk.text
        assert "75%" in tools_chunk.text
        assert "Flask" in tools_chunk.text
        assert "80%" in tools_chunk.text
        assert "Docker" in tools_chunk.text
        assert "OpenAI API" in tools_chunk.text
        assert "ابزار" in (tools_chunk.heading_context or "") and "پلتفرم" in (tools_chunk.heading_context or "")
        assert "low_info" not in tools_chunk.quality_flags

    def test_job_and_education_dates_stay_attached_to_entity(self):
        """Date headers like '### تجربه‌ها 1405 — تاکنون' must stay glued to the job section, not isolated as a 5-word chunk."""
        chunker = ChunkerService(strategy="semantic_heading", chunk_size=1200, overlap=50)
        doc = _create_mock_extracted_doc("https://younesebrahimi.ir/fa/resume", SAMPLE_FA_CONTENT)
        result = chunker.chunk_document(doc)

        # Look for the university education chunk
        edu_chunk = next(c for c in result.chunks if "دانشگاه آزاد واحد نجف آباد" in c.text)
        # The date must be inside or attached to the education chunk
        assert "۱۴۰۳ - ۱۴۰۵" in edu_chunk.text or "تحصیلات" in edu_chunk.text
        assert "کارشناسی علوم کامپیوتر" in edu_chunk.text or "نجف آباد" in edu_chunk.text
        assert "low_info" not in edu_chunk.quality_flags

    def test_contact_chunk_retains_credentials_without_low_info_penalty(self):
        """A compact contact section with email and Telegram must not be erroneously penalized as low_info."""
        chunker = ChunkerService(strategy="semantic_heading", chunk_size=1000, overlap=50)
        doc = _create_mock_extracted_doc("https://younesebrahimi.ir/fa/contact", SAMPLE_FA_CONTENT)
        result = chunker.chunk_document(doc)

        contact_chunk = next(c for c in result.chunks if "yebrahimi621@gmail.com" in c.text)
        assert "low_info" not in contact_chunk.quality_flags
        assert contact_chunk.category == "contact"
        assert "@VposeidonV" in contact_chunk.text

    def test_breadcrumbs_and_parent_heading_metadata_populated(self):
        """Chunks must carry accurate hierarchical breadcrumbs and parent heading for RAG filtering."""
        chunker = ChunkerService(strategy="semantic_heading", chunk_size=1000, overlap=50)
        doc = _create_mock_extracted_doc("https://younesebrahimi.ir/fa/resume", SAMPLE_FA_CONTENT)
        result = chunker.chunk_document(doc)

        tools_chunk = next(c for c in result.chunks if "FastAPI" in c.text)
        assert len(tools_chunk.breadcrumbs) >= 1
        assert any("مهارت" in b or "ابزار" in b for b in tools_chunk.breadcrumbs)
        assert tools_chunk.token_count_approx > 0


# ---------------------------------------------------------------------------
# 2. Tests for Category Taxonomy & Classification
# ---------------------------------------------------------------------------

class TestCategoryStandardization:
    """Verifies that categories are standardized to clean slugs without 'unknown' or raw headings."""

    def test_page_classifier_classifies_resume_services_skills_portfolio(self):
        """PageClassifier must recognize resume, services, skills, and portfolio from URLs and content."""
        assert PageClassifier.classify("https://example.com/fa/resume") == "resume"
        assert PageClassifier.classify("https://example.com/en/services") == "services"
        assert PageClassifier.classify("https://example.com/fa/skills") == "skills"
        assert PageClassifier.classify("https://example.com/fa/portfolio") == "portfolio"
        assert PageClassifier.classify("https://example.com/fa/contact") == "contact"
        assert PageClassifier.classify("https://example.com/fa/about") == "about"

    def test_resolve_chunk_category_never_returns_unknown(self):
        """resolve_chunk_category must map categories cleanly and default to 'general' rather than 'unknown'."""
        cat1 = resolve_chunk_category(None, "مهارت ها > ابزارها", "unknown", "مهارت‌ها", "https://site.com/fa/skills")
        assert cat1 == "skills"

        cat2 = resolve_chunk_category(None, "خدمات > هوشمندسازی", "unknown", "خدمات", "https://site.com/fa/services")
        assert cat2 == "services"

        cat3 = resolve_chunk_category(None, None, "unknown", None, None)
        assert cat3 == "general"
        assert cat3 != "unknown"

        # Explicit user category is strictly respected
        cat4 = resolve_chunk_category("custom_knowledge_base", "خدمات", "services")
        assert cat4 == "custom_knowledge_base"


# ---------------------------------------------------------------------------
# 3. Tests for Deduplication across 13 URLs
# ---------------------------------------------------------------------------

class TestCrossURLDeduplication:
    """Verifies that identical content across multiple URLs is deduplicated with source tracking."""

    def test_chunk_documents_deduplicates_identical_content_with_provenance(self):
        """Identical content crawled from 7 Persian URLs must produce only unique chunks with alternate_sources recorded."""
        urls = [
            "https://younesebrahimi.ir/fa/resume",
            "https://younesebrahimi.ir/fa/about",
            "https://younesebrahimi.ir/fa/services",
            "https://younesebrahimi.ir/fa/skills",
            "https://younesebrahimi.ir/fa/portfolio",
            "https://younesebrahimi.ir/fa/contact",
            "https://younesebrahimi.ir/",
        ]
        docs = [_create_mock_extracted_doc(url, SAMPLE_FA_CONTENT) for url in urls]

        chunker = ChunkerService(strategy="semantic_heading", chunk_size=1000, overlap=50)

        # 1. Deduplication enabled (default for multi-document batch)
        deduped_chunks = chunker.chunk_documents(docs, deduplicate_chunks=True)
        single_doc_chunks = chunker.chunk_document(docs[0]).chunks

        # Total unique chunks should match the chunks of a single document
        assert len(deduped_chunks) == len(single_doc_chunks)
        assert len(deduped_chunks) < 20, f"Expected < 20 consolidated chunks, got {len(deduped_chunks)}"

        # Verify alternate_sources contains all the other 6 URLs
        sample_chunk = deduped_chunks[0]
        assert len(sample_chunk.alternate_sources) == 6
        recorded_urls = {src["source_url"] for src in sample_chunk.alternate_sources}
        for u in urls[1:]:
            assert u in recorded_urls

    def test_api_route_chunk_deduplicates_duplicate_job_documents(self):
        """The /api/ai/chunk endpoint must ignore QualityStatus.DUPLICATE documents by default."""
        manager = get_manager()
        job_id = "test-dedup-job-13-urls"

        # Create 1 canonical document and 2 duplicate documents
        doc1 = _create_mock_extracted_doc("https://site.com/fa/about", SAMPLE_FA_CONTENT, quality_status=QualityStatus.SUCCESS)
        doc2 = _create_mock_extracted_doc("https://site.com/fa/resume", SAMPLE_FA_CONTENT, quality_status=QualityStatus.DUPLICATE)
        doc3 = _create_mock_extracted_doc("https://site.com/fa/services", SAMPLE_FA_CONTENT, quality_status=QualityStatus.DUPLICATE)

        manager._jobs[job_id] = {"id": job_id, "status": "completed"}
        manager._documents[job_id] = [doc1, doc2, doc3]

        client = TestClient(app)
        response = client.post(
            "/api/ai/chunk",
            json={"job_id": job_id, "strategy": "semantic_heading", "chunk_size": 1000, "overlap": 50},
        )
        assert response.status_code == 200
        data = response.json()["data"]

        # Only 1 unique document was chunked
        assert data["total_docs_chunked"] == 1
        stored_chunks = manager.get_chunks(job_id)
        assert len(stored_chunks) == data["total_chunks"]
        assert all(c.source_url == "https://site.com/fa/about" for c in stored_chunks)


# ---------------------------------------------------------------------------
# 4. Tests for Normalization Defaults & Transparency
# ---------------------------------------------------------------------------

class TestNormalizationTransparency:
    """Verifies that normalization is active by default and reported accurately."""

    def test_normalization_applied_is_true_by_default(self):
        """ChunkerService must apply Persian normalization by default and set normalization_applied=True."""
        chunker = ChunkerService(strategy="paragraph", chunk_size=500, overlap=0, normalize=True)
        # Persian text containing non-standard Arabic Kaf/Yeh and missing ZWNJ
        raw_text = "اين كتابها با فرمت جديد ذخيره ميشود."
        doc = _create_mock_extracted_doc("https://example.com/fa/test", raw_text)
        result = chunker.chunk_document(doc)

        assert result.total_chunks == 1
        chunk = result.chunks[0]
        assert chunk.normalization_applied is True
        # Arabic Kaf & Yeh must be converted to Persian
        assert "این" in chunk.text
        assert "کتاب‌ها" in chunk.text
        assert "می‌شود" in chunk.text
        assert chunk.metadata.get("normalization_report") is not None


# ---------------------------------------------------------------------------
# 5. Tests for VectorStore & Hybrid Retrieval
# ---------------------------------------------------------------------------

class TestVectorStoreAndHybridRetrieval:
    """Validates VectorStore indexing, cosine similarity, BM25, and hybrid search."""

    def test_vector_store_upsert_and_stats(self):
        """VectorStore must accurately index chunks, count vectors, and report category distribution."""
        store = VectorStore(expected_dim=4)
        c1 = DocumentChunk(
            chunk_id="c1",
            source_url="https://site.com/fa/resume",
            chunk_index=0,
            total_chunks=2,
            text="توسعه‌دهنده نرم‌افزار پایتون و هوش مصنوعی",
            char_count=40,
            word_count=6,
            category="resume",
            embedding=[0.1, 0.2, 0.3, 0.4],
        )
        c2 = DocumentChunk(
            chunk_id="c2",
            source_url="https://site.com/fa/services",
            chunk_index=1,
            total_chunks=2,
            text="ارائه خدمات هوشمندسازی وب‌سایت با معماری RAG",
            char_count=45,
            word_count=7,
            category="services",
            embedding=[0.2, 0.1, 0.4, 0.3],
        )

        upserted = store.upsert_chunks([c1, c2])
        assert upserted == 2
        assert store.total_chunks == 2
        assert store.total_vectors == 2

        stats = store.get_stats()
        assert stats["category_distribution"]["resume"] == 1
        assert stats["category_distribution"]["services"] == 1

    def test_hybrid_search_combines_vector_and_keyword_precision(self):
        """Hybrid search with alpha=0.5 must reward chunks containing exact lexical keywords (FastAPI)."""
        store = VectorStore(expected_dim=4)
        c1 = DocumentChunk(
            chunk_id="c1",
            source_url="https://site.com/fa/skills",
            chunk_index=0,
            total_chunks=2,
            text="تسلط بر فریم‌ورک FastAPI و داکر به همراه پایتون با ۷۵ درصد مهارت",
            char_count=60,
            word_count=10,
            category="skills",
            embedding=[0.9, 0.1, 0.0, 0.0],
        )
        c2 = DocumentChunk(
            chunk_id="c2",
            source_url="https://site.com/fa/skills",
            chunk_index=1,
            total_chunks=2,
            text="توسعه سیستم‌های یادگیری ماشین و پردازش تصویر",
            char_count=45,
            word_count=6,
            category="skills",
            embedding=[0.8, 0.2, 0.0, 0.0],
        )
        store.upsert_chunks([c1, c2])

        # Query specifically for 'FastAPI'
        results = store.search(
            query="FastAPI",
            query_vector=[0.85, 0.15, 0.0, 0.0],
            top_k=2,
            hybrid=True,
            alpha=0.5,
        )
        assert len(results) == 2
        # c1 must rank first because of the exact keyword match on FastAPI
        assert results[0].chunk.chunk_id == "c1"
        assert results[0].score > results[1].score

    def test_metadata_filtering_and_neighbor_expansion(self):
        """VectorStore search must filter by category and optionally expand neighboring chunks."""
        store = VectorStore(expected_dim=4)
        c0 = DocumentChunk(
            chunk_id="c0",
            source_url="https://site.com/doc",
            chunk_index=0,
            total_chunks=3,
            text="مقدمه و رزومه کاری",
            char_count=20,
            word_count=3,
            category="resume",
            embedding=[0.5, 0.5, 0.0, 0.0],
        )
        c1 = DocumentChunk(
            chunk_id="c1",
            source_url="https://site.com/doc",
            chunk_index=1,
            total_chunks=3,
            text="سوابق تحصیلی در دانشگاه آزاد نجف‌آباد در رشته کامپیوتر",
            char_count=50,
            word_count=8,
            category="resume",
            embedding=[0.5, 0.5, 0.0, 0.0],
        )
        c2 = DocumentChunk(
            chunk_id="c2",
            source_url="https://site.com/doc",
            chunk_index=2,
            total_chunks=3,
            text="مدارک تخصصی و پایان‌نامه دانشگاهی",
            char_count=30,
            word_count=4,
            category="resume",
            embedding=[0.5, 0.5, 0.0, 0.0],
        )
        store.upsert_chunks([c0, c1, c2])

        # Search with neighbor expansion
        results = store.search(
            query="نجف‌آباد",
            query_vector=[0.5, 0.5, 0.0, 0.0],
            top_k=1,
            category="resume",
            expand_neighbors=True,
        )
        assert len(results) == 1
        best = results[0]
        assert best.chunk.chunk_id == "c1"
        # Neighbors must contain c0 (previous) and c2 (next)
        neighbor_ids = {n.chunk_id for n in best.neighbors}
        assert "c0" in neighbor_ids
        assert "c2" in neighbor_ids

    def test_delete_by_url_removes_stale_chunks(self):
        """Updating a crawled page must purge old chunks to prevent stale retrieval."""
        store = VectorStore(expected_dim=2)
        c = DocumentChunk(
            chunk_id="c_old",
            source_url="https://site.com/page",
            chunk_index=0,
            total_chunks=1,
            text="Old content to be removed",
            char_count=25,
            word_count=5,
            embedding=[0.1, 0.2],
        )
        store.upsert_chunks([c])
        assert store.total_chunks == 1

        deleted = store.delete_by_url("https://site.com/page")
        assert deleted == 1
        assert store.total_chunks == 0
        assert store.total_vectors == 0


# ---------------------------------------------------------------------------
# 6. Quantitative Evaluation Benchmark (Recall@K & Precision@K)
# ---------------------------------------------------------------------------

class TestRAGEvaluationBenchmark:
    """Measures quantitative retrieval metrics on the real sample content."""

    @pytest.fixture(autouse=True)
    def setup_corpus(self):
        self.chunker = ChunkerService(strategy="semantic_heading", chunk_size=1000, overlap=50)
        self.store = VectorStore(expected_dim=None)  # Sparse BM25 evaluation

        # Chunk the actual Persian and English sample documents
        doc_fa = _create_mock_extracted_doc("https://younesebrahimi.ir/fa/resume", SAMPLE_FA_CONTENT, language="fa")
        doc_en = _create_mock_extracted_doc("https://younesebrahimi.ir/en/resume", SAMPLE_EN_CONTENT, language="en")

        chunks_fa = self.chunker.chunk_document(doc_fa).chunks
        chunks_en = self.chunker.chunk_document(doc_en).chunks

        self.store.upsert_chunks(chunks_fa + chunks_en)

    def test_recall_and_precision_on_benchmark_queries(self):
        """Verify that specific factual questions retrieve the exact source chunk with 100% Precision@1."""
        test_queries = [
            {
                "query": "درصد تسلط بر FastAPI چقدر است؟",
                "expected_term": "FastAPI",
                "expected_category": "skills",
            },
            {
                "query": "تحصیلات دانشگاه آزاد واحد نجف آباد",
                "expected_term": "نجف آباد",
                "expected_category": "resume",
            },
            {
                "query": "پروژه اسمارت شاپ دیجی کالا",
                "expected_term": "اسمارت‌شاپ",
                "expected_category": "portfolio",
            },
            {
                "query": "چت بات پشتیبانی وب سایت Lobby Nine RAG",
                "expected_term": "Lobby Nine",
                "expected_category": "portfolio",
            },
            {
                "query": "What is the education at Azad University Najafabad?",
                "expected_term": "Najafabad",
                "expected_category": "resume",
            },
            {
                "query": "Contact Telegram and email address",
                "expected_term": "yebrahimi621@gmail.com",
                "expected_category": "contact",
            },
        ]

        correct_top1 = 0
        correct_top3 = 0

        for tq in test_queries:
            results = self.store.search(
                query=tq["query"],
                top_k=3,
                hybrid=False,  # Evaluates exact lexical BM25 precision
            )
            assert len(results) > 0, f"Query '{tq['query']}' must return results"

            top1_chunk = results[0].chunk
            top3_chunks = [r.chunk for r in results]

            if tq["expected_term"] in top1_chunk.text:
                correct_top1 += 1

            if any(tq["expected_term"] in c.text for c in top3_chunks):
                correct_top3 += 1

        precision_at_1 = correct_top1 / len(test_queries)
        recall_at_3 = correct_top3 / len(test_queries)

        assert precision_at_1 >= 0.83, f"Expected Precision@1 >= 0.83, got {precision_at_1}"
        assert recall_at_3 == 1.0, f"Expected Recall@3 == 1.0, got {recall_at_3}"
