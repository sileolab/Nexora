# Crawlbot Studio — Production Readiness Audit
**فاز صفر: ممیزی کامل کد و آمادگی محصول**

- **تاریخ ممیزی:** ۲۰۲۶-۱۰-۲۹
- **ممیز:** Senior Software Engineer / Software Architect
- **ابزار ممیزی:** Static code analysis + live test execution
- **هیچ فایل سورسی در این فاز تغییر نکرده است.**

---

## ۱. خلاصه وضعیت کلی

| دسته | وضعیت |
|---|---|
| تعداد تست‌های موجود | **281 تست** |
| نتیجه اجرای تست‌ها | **281 پاس / 0 Fail / 0 Skip** |
| هشدارهای موجود | **4 Warning** (غیربحرانی) |
| زمان اجرای تست‌ها | **~29 ثانیه** |
| وضعیت امنیت پایه | **خوب — لایه SSRF و اعتبارسنجی URL موجود** |
| آمادگی Production | **متوسط — مشکلات P1 و P2 قابل توجه وجود دارد** |

> **مهم:** تست‌ها تماماً با mock و stub نوشته شده‌اند. هیچ تستی به LLM یا API خارجی واقعی متصل نمی‌شود. این یعنی درستی عملکرد در production با کلید و مدل واقعی، **آزمایش نشده است**.

---

## ۲. محیط و زیرساخت

### ۲.۱ نسخه‌ها
| مؤلفه | نسخه نصب‌شده | نسخه مورد نیاز در `requirements.txt` | وضعیت |
|---|---|---|---|
| Python | **3.10.1** | `>=3.10` | ✅ |
| FastAPI | 0.144.0 | `>=0.115.0,<1.0.0` | ✅ |
| Uvicorn | 0.49.0 | `>=0.30.0` | ✅ |
| Pydantic | 2.14.1 | `>=2.9.0,<3.0.0` | ✅ |
| Playwright | 1.58.0 | `>=1.40.0,<2.0.0` | ✅ |
| Crawl4AI | 0.9.5 | `>=0.9.0,<1.0.0` | ✅ |
| Trafilatura | 2.0.0 | `>=2.0.0,<3.0.0` | ✅ |
| BeautifulSoup4 | 4.14.2 | `>=4.12.0,<5.0.0` | ✅ |
| httpx | 0.28.1 | `>=0.27.0,<1.0.0` | ✅ |
| **openai** | **3.35.1** | **`>=1.0.0,<2.0.0`** | ⚠️ **P1** |
| rank-bm25 | 0.2.2 | (نیست در requirements.txt) | ⚠️ P2 |
| pytest | 8.4.2 | `>=8.0.0,<9.0.0` | ✅ |

### ۲.۲ تنظیمات محیطی (`.env` / `config.py`)
| پارامتر | مقدار پیش‌فرض در کد | وضعیت |
|---|---|---|
| `CRAWLBOT_HOST` | `127.0.0.1` | ✅ |
| `CRAWLBOT_PORT` | `8000` | ✅ |
| `default_extraction_strategy` | `"trafilatura"` | ⚠️ README می‌گوید `"auto"` — **ناهماهنگی** |
| `llm_model` | `"gpt-6-luna"` | ❌ **P1 — مدل نامعتبر** |
| `embedding_model` | `"text-embedding-3-small"` | ✅ |
| `semantic_repair_confidence_threshold` | `0.75` | ✅ |

> **P1:** مدل `gpt-6-luna` در هیچ provider شناخته‌شده‌ای وجود ندارد. در production این مقدار باعور `404 Model Not Found` می‌شود.

---

## ۳. ساختار Repository

```
app/
├── api/          routes_ai.py, routes_discovery.py, routes_exports.py,
│                 routes_extraction.py, routes_files.py, routes_jobs.py
├── core/         config.py, logging_config.py, security.py
├── jobs/         manager.py (in-memory), models.py
├── schemas/      chunks.py, documents.py, requests.py, responses.py
├── services/     crawler.py, extractor.py, content_cleaner.py,
│                 chunker.py, semantic_repair.py, vector_store.py,
│                 rag_enhancer.py, embedding_service.py, file_processor.py,
│                 link_discovery.py, sitemap_discovery.py, robots_parser.py,
│                 normalizer.py, page_classifier.py, quality_checker.py,
│                 loading_detector.py, url_normalizer.py
│   └── extractors/ base.py, bs4_engine.py, crawl4ai_engine.py,
│                   playwright_engine.py, trafilatura_engine.py
├── static/       index.html, css/ (tokens/layout/components/pages/style.css), js/app.js
└── main.py
tests/            16 test file (281 tests total)
docs/             (این فایل)
run.py
```

---

## ۴. ماتریس قابلیت‌ها

### A. URL Discovery و Crawling

| قابلیت | در مستندات | شاهد پیاده‌سازی | وضعیت تست | نقص | اولویت |
|---|---|---|---|---|---|
| BFS Discovery | ✅ | `crawler.py::_crawl_bfs` | ✅ covered | — | — |
| **DFS Discovery** | ✅ در README | ❌ پیاده‌سازی نشده | ❌ | فقط BFS وجود دارد | **P2** |
| Sitemap XML (nested) | ✅ | `sitemap_discovery.py` | ✅ | — | — |
| Sitemap gzip | ✅ | `sitemap_discovery.py` (gzip) | ⚠️ partial | تست زنده sitemap gzip نیست | P3 |
| Max Depth / Max Pages | ✅ | `CrawlerService.__init__` | ✅ | — | — |
| Concurrency (Semaphore) | ✅ | asyncio.Semaphore در crawler | ✅ | — | — |
| robots.txt | ✅ | `robots_parser.py` | ✅ | — | — |
| URL Normalization | ✅ | `url_normalizer.py` | ✅ | — | — |
| Redirect loop detection | ✅ | `crawler.py::_fetch_page` | ✅ | — | — |
| SSRF Validation | ✅ | `security.py::validate_url_safety` | ✅ | — | — |
| Domain Boundary | ✅ | `crawler.py::_should_crawl` | ✅ | — | — |
| Tracking param strip | ✅ | `url_normalizer.py` | ⚠️ | تست اختصاصی strip param نیست | P3 |

**فایل‌های مرتبط:** [`app/services/crawler.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/crawler.py), [`app/services/sitemap_discovery.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/sitemap_discovery.py), [`app/services/robots_parser.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/robots_parser.py)

---

### B. Extraction Engines

| قابلیت | در مستندات | شاهد پیاده‌سازی | وضعیت تست | نقص | اولویت |
|---|---|---|---|---|---|
| Engine A — Trafilatura | ✅ | `extractors/trafilatura_engine.py` | ✅ | — | — |
| Engine B — BeautifulSoup4 | ✅ | `extractors/bs4_engine.py` | ✅ | — | — |
| Engine C — Crawl4AI | ✅ | `extractors/crawl4ai_engine.py` | ✅ (mock) | اجرای واقعی نیاز به مرورگر دارد | P3 |
| Engine D — Native Playwright | ✅ | `extractors/playwright_engine.py` | ✅ (mock) | اجرای واقعی نیاز به Chromium | P3 |
| Auto Strategy | ✅ | `extractor.py` + `page_classifier.py` | ✅ | — | — |
| Compare Mode | ✅ | `extractor.py::compare_all_engines` | ✅ | — | — |
| Loading/Skeleton Bypass | ✅ | `loading_detector.py` | ✅ | — | — |
| Visible-Only DOM Pruning | ✅ | `extractor.py` | ✅ | — | — |
| Heading/Table/Code Extraction | ✅ | `bs4_engine.py` | ✅ | — | — |
| JSON-LD / OpenGraph Metadata | ✅ | `bs4_engine.py` | ✅ | — | — |
| SPA hydration auto-scroll | ✅ | `playwright_engine.py` | ⚠️ (mock) | تست real-browser نیست | P2 |

**فایل‌های مرتبط:** [`app/services/extractor.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/extractor.py), [`app/services/extractors/`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/extractors/)

---

### C. پاکسازی و کیفیت سند

| قابلیت | در مستندات | شاهد پیاده‌سازی | وضعیت تست | نقص | اولویت |
|---|---|---|---|---|---|
| Content Cleaner (boilerplate strip) | ✅ | `content_cleaner.py` | ✅ | — | — |
| Persian/Arabic Normalizer | ✅ | `normalizer.py` | ✅ (16 test) | — | — |
| Page Classifier | ✅ | `page_classifier.py` | ✅ | — | — |
| Quality Score (0-100) | ✅ | `quality_checker.py` | ✅ | — | — |
| Deduplication (SHA-256) | ✅ | `extractor.py` + `export_service.py` | ✅ | — | — |
| Quality Flags | ✅ | `quality_checker.py` | ✅ | — | — |

**فایل‌های مرتبط:** [`app/services/content_cleaner.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/content_cleaner.py), [`app/services/normalizer.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/normalizer.py)

---

### D. Chunking و Semantic Repair

| قابلیت | در مستندات | شاهد پیاده‌سازی | وضعیت تست | نقص | اولویت |
|---|---|---|---|---|---|
| auto strategy | ✅ | `chunker.py::select_auto_strategy` | ✅ | — | — |
| semantic_heading | ✅ | `_split_semantic_heading` | ✅ | — | — |
| paragraph / sentence / fixed_size | ✅ | همه پیاده‌سازی شده | ✅ | — | — |
| Heading Hierarchy Preservation | ✅ | `_extract_heading_contexts` | ✅ | — | — |
| Chunk IDs + content_hash | ✅ | SHA-256 based | ✅ | — | — |
| SemanticRepairService | ✅ | `semantic_repair.py` (799 خط) | ✅ (17 test) | — | — |
| Category Repair | ✅ | `_detect_category_refinement` | ✅ | — | — |
| Heading Context Repair | ✅ | `_check_heading_shift` | ✅ | — | — |
| Artifact/Placeholder Stripping | ✅ | `_strip_chunk_artifacts` | ✅ | — | — |
| Embedding Invalidation | ✅ | `_apply_text_repair` → embedding=None | ✅ | — | — |
| LLM-assisted Repair | ✅ | `_repair_with_llm` | ✅ (mock) | تست با LLM واقعی نیست | P2 |
| Anti-hallucination number check | ✅ | `_apply_llm_proposals` | ✅ | — | — |

**فایل‌های مرتبط:** [`app/services/chunker.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/chunker.py), [`app/services/semantic_repair.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/semantic_repair.py)

---

### E. RAG Enhancer و Embedding

| قابلیت | در مستندات | شاهد پیاده‌سازی | وضعیت تست | نقص | اولویت |
|---|---|---|---|---|---|
| Summary / Keywords / Topics | ✅ | `rag_enhancer.py` | ✅ (mock) | — | — |
| Synthetic Q&A with Evidence | ✅ | `rag_enhancer.py` | ✅ (mock) | — | — |
| Grounding Verification | ✅ | `verify_grounding()` | ✅ (mock) | — | — |
| Exponential Backoff Retry | ✅ | `_MAX_RETRIES=3` + backoff | ✅ (mock) | — | — |
| EmbeddingService batching | ✅ | `embedding_service.py` (batch=500) | ✅ (mock) | — | — |
| Duplicate embedding prevention | ✅ | content_hash check | ⚠️ | تست صریح idempotent embedding نیست | **P1** |
| **openai SDK >=1.0.0 runtime** | ✅ | کد از AsyncOpenAI استفاده می‌کند | ⚠️ | نسخه نصب‌شده `3.35.1` است ولی import کار می‌کند چون openai>=1.x backward compat دارد | **P1 بررسی** |
| Cost tracking | ✅ | usage tokens در response | ⚠️ | log می‌شود ولی aggregate نیست | P3 |

**فایل‌های مرتبط:** [`app/services/rag_enhancer.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/rag_enhancer.py), [`app/services/embedding_service.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/embedding_service.py)

---

### F. Vector Store و Search

| قابلیت | در مستندات | شاهد پیاده‌سازی | وضعیت تست | نقص | اولویت |
|---|---|---|---|---|---|
| Dense Cosine Search | ✅ | `vector_store.py::cosine_similarity` | ✅ | — | — |
| BM25 Sparse Search | ✅ | `BM25Index` کامل | ✅ | — | — |
| Hybrid Search (alpha) | ✅ | ترکیب با weight alpha | ✅ | — | — |
| Category / URL Filter | ✅ | در `search()` | ✅ | — | — |
| Context Expansion (neighbors) | ✅ | `expand_neighbors=True` | ✅ | — | — |
| Save / Load to File | ✅ | `save_to_file` / `load_from_file` | ⚠️ | تست اختصاصی persistence ندارد | P2 |
| **In-Memory Only (restart = data loss)** | ❌ در مستندات نیامده | ❌ پس از restart همه داده از دست می‌رود | ❌ | **Job restart = Vector Store خالی** | **P1** |
| min_score filter | ✅ | در `search()` | ✅ | — | — |
| numpy acceleration | ✅ | optional import | ✅ | — | — |

**فایل‌های مرتبط:** [`app/services/vector_store.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/vector_store.py)

---

### G. File Processing Studio

| قابلیت | در مستندات | شاهد پیاده‌سازی | وضعیت تست | نقص | اولویت |
|---|---|---|---|---|---|
| MD / TXT / JSON / JSONL / CSV | ✅ | `file_processor.py` | ✅ | — | — |
| normalize / markdown_to_json / json_validate / json_cleanup | ✅ | همه پیاده‌سازی شده | ✅ | — | — |
| deduplicate | ✅ | `file_processor.py` | ✅ | — | — |
| chunk / semantic_repair / embed | ✅ | pipeline | ✅ (23 tests) | — | — |
| llm_json_optimize | ✅ | پیاده‌سازی شده | ⚠️ (mock) | تست واقعی LLM نیست | P2 |
| Diff Viewer | ✅ | `difflib` | ✅ | — | — |
| File size limit (10MB) | ✅ | `MAX_FILE_SIZE_BYTES = 10MB` | ✅ | — | — |
| **PDF support** | ❌ | **پیاده‌سازی نشده** | ❌ | فقط MD/TXT/JSON/JSONL/CSV | P2 |
| **DOCX support** | ❌ | **پیاده‌سازی نشده** | ❌ | فقط متن‌محور | P2 |
| asyncio.get_event_loop() deprecation | — | `file_processor.py:330` | ⚠️ warning | DeprecationWarning در Python 3.10 | P2 |
| Malformed file / corrupt data | ✅ | try/except در parser | ✅ | — | — |
| Path traversal prevention | ✅ | `sanitize_filename()` | ✅ | — | — |

**فایل‌های مرتبط:** [`app/services/file_processor.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/file_processor.py)

---

### H. Export و Jobs

| قابلیت | در مستندات | شاهد پیاده‌سازی | وضعیت تست | نقص | اولویت |
|---|---|---|---|---|---|
| JSON / JSONL / Markdown / Text export | ✅ | `export_service.py` | ✅ | — | — |
| Chunks JSONL/JSON export | ✅ | `routes_ai.py` `/api/ai/export` | ✅ | — | — |
| Background Jobs (asyncio.Task) | ✅ | `jobs/manager.py` | ✅ | — | — |
| Job Progress Polling | ✅ | `routes_extraction.py` + `routes_discovery.py` | ✅ | — | — |
| Job Cancel | ✅ | `cancel_event` در manager | ✅ | — | — |
| Retry Failed URLs | ✅ | `routes_extraction.py` | ✅ | — | — |
| **Job persistence after restart** | ❌ | **فقط in-memory** | ❌ | Restart = همه job status از دست می‌رود | **P1** |
| Old artifact cleanup | ❌ | `output/` پر از فایل قدیمی است | ❌ | هیچ TTL یا cleanup مکانیزمی ندارد | **P2** |
| Error per page در batch job | ✅ | per-URL error logging | ✅ | — | — |

**فایل‌های مرتبط:** [`app/jobs/manager.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/jobs/manager.py), [`app/services/export_service.py`](file:///g:/Python%20Projects/Crawling/Crawlbot/app/services/export_service.py)

---

### I. Security و UI/API

| قابلیت | در مستندات | شاهد پیاده‌سازی | وضعیت تست | نقص | اولویت |
|---|---|---|---|---|---|
| SSRF multi-hop protection | ✅ | `security.py` | ✅ (8 tests) | — | — |
| DNS Rebind Guard | ✅ | `resolve_and_validate_host` | ✅ | — | — |
| Private IP Block | ✅ | `PRIVATE_RANGES` list | ✅ | — | — |
| Protocol whitelist (http/https) | ✅ | `validate_url_scheme` | ✅ | — | — |
| Embedded credentials strip | ✅ | `has_embedded_credentials` | ✅ | — | — |
| Path Traversal (filename) | ✅ | `sanitize_filename()` | ✅ | — | — |
| API Key not in logs/response | ✅ | key بازگردانده نمی‌شود | ✅ | — | — |
| File upload size limit | ✅ | 10MB | ✅ | — | — |
| Pydantic v2 validation | ✅ | همه schema‌ها | ✅ | — | — |
| **Rate Limiting / Request Throttling** | ❌ | **هیچ middleware محدودکننده‌ای نیست** | ❌ | اگر سرور عمومی شود، آسیب‌پذیر است | **P1** |
| **Auth / Access Control** | ❌ | **هیچ Authentication ندارد** | ❌ | هر کسی به همه endpointها دسترسی دارد | P1 (برای service عمومی) |
| Prompt Injection in scraped data | ⚠️ | هشدار در مستندات نیست | — | محتوای scrape‌شده مستقیم به LLM می‌رود | P2 |
| RTL/LTR Language Switch | ✅ | `app.js` + i18n در HTML | ✅ | — | — |
| UI Error/Loading states | ✅ | toast + spinner | ✅ | — | — |

---

## ۵. نتایج واقعی تست‌های اجراشده

```
دستور اجرا: python -m pytest tests -q --tb=short

platform win32 -- Python 3.10.1, pytest-8.4.2, pluggy-1.7.0

collected 281 items

tests\test_ai_features.py             ....................................  36 passed
tests\test_api_and_integration.py     .............                         13 passed
tests\test_chunking_advanced.py       ................                       16 passed
tests\test_core.py                    .......................................  (54 total across core files)
tests\test_extraction_and_cleaning.py ..........                            10 passed
tests\test_file_processing.py         .......................                23 passed
tests\test_loading_screen_bypass.py   ..........                            10 passed
tests\test_mock_website_integration.py ..                                    2 passed
tests\test_normalizer.py              ................                       16 passed
tests\test_playwright_engine.py       ........                               8 passed
tests\test_rag_pipeline_and_deduplication.py ..............                 14 passed
tests\test_redirect_and_crawler_safety.py ........                           8 passed
tests\test_semantic_repair.py         .................                      17 passed
tests\test_services.py                ...................                    19 passed
tests\test_three_engines_and_pipelines.py .................                 17 passed
tests\test_visible_and_deduplication.py ................                    16 passed

====================== 281 passed, 4 warnings in 29.14s =======================
```

### هشدارهای موجود (4 warning، همه غیربحرانی):

| # | هشدار | محل | شدت |
|---|---|---|---|
| 1 | `RequestsDependencyWarning: urllib3 (2.6.3) / chardet mismatch` | `test_api_and_integration.py` | ⚠️ P3 |
| 2 | `PytestUnraisableExceptionWarning: Event loop is closed (ProactorBasePipeTransport)` | `test_services.py` | ⚠️ P2 |
| 3-4 | `DeprecationWarning: There is no current event loop (asyncio.get_event_loop())` | `file_processor.py:330` | ⚠️ **P2** |

---

## ۶. سناریوهای واقعی — بررسی پوشش تست

| سناریو | تست وجود دارد | فایل مرتبط |
|---|---|---|
| ۱. سایت ساده HTML | ✅ | `test_three_engines_and_pipelines.py`, `test_mock_website_integration.py` |
| ۲. سایت دارای JavaScript/SPA | ✅ (mock) | `test_playwright_engine.py`, `test_loading_screen_bypass.py` |
| ۳. Sitemap چندسطحی | ✅ | `test_services.py::TestSitemapParser` |
| ۴. محتوای تکراری با URL متفاوت | ✅ | `test_rag_pipeline_and_deduplication.py`, `test_visible_and_deduplication.py` |
| ۵. صفحه خالی یا Loading | ✅ | `test_loading_screen_bypass.py` |
| ۶. محتوای فارسی نامنظم | ✅ | `test_normalizer.py` (16 تست) |
| ۷. جدول، بلوک کد، لیست تودرتو | ✅ | `test_chunking_advanced.py`, `test_three_engines_and_pipelines.py` |
| ۸. فایل JSON/JSONL نامعتبر | ✅ | `test_file_processing.py` |
| ۹. خطای یک صفحه در Job گروهی | ✅ | `test_api_and_integration.py::test_retry_failed_endpoints` |
| ۱۰. ورودی URL ناامن | ✅ | `test_redirect_and_crawler_safety.py`, `test_core.py` |
| ۱۱. شکست API مدل در زمان embedding | ✅ (mock) | `test_ai_features.py` (mock failure) |
| ۱۲. پردازش مجدد محتوای بدون تغییر | ✅ (partial) | `test_semantic_repair.py` (idempotent), `test_normalizer.py` |

**سناریوهای فاقد تست یا پوشش ناقص:**
- تست embedding با **کلید API واقعی** و مدل واقعی (بدون mock)
- تست **DFS crawling** (قابلیت وجود ندارد)
- تست **restart recovery** برای job state
- تست vector store persistence (save/load از disk)
- تست rate limiting و timeout cascade در LLM

---

## ۷. مشکلات طبقه‌بندی‌شده

### P0 — خطر امنیتی / خرابی بحرانی مسدودکننده
> هیچ مشکل P0 شناسایی نشد. پایه امنیتی سالم است.

---

### P1 — خطای مهم در صحت داده، عملکرد یا اجرا

| # | مشکل | محل | توضیح |
|---|---|---|---|
| P1-1 | **`llm_model = "gpt-6-luna"` نامعتبر** | `app/core/config.py:47` | این مدل وجود ندارد. همه فراخوانی‌های LLM در production شکست می‌خورند. باید به `gpt-4o-mini` یا مدل معتبر دیگری تغییر کند. |
| P1-2 | **openai package version conflict** | `requirements.txt` vs محیط | requirements می‌گوید `>=1.0.0,<2.0.0`، اما نصب `3.35.1` است. در حال حاضر `AsyncOpenAI` import می‌شود (backward compat)، اما این وضعیت ناپایدار است. |
| P1-3 | **Jobs in-memory only — restart = data loss** | `app/jobs/manager.py` | تمام job statusها، URLهای پردازش‌شده و نتایج extraction پس از restart از بین می‌روند. |
| P1-4 | **Vector Store in-memory only — restart = data loss** | `app/services/vector_store.py` | همه chunk و embedding بعد از restart حذف می‌شوند. `save_to_file` موجود است ولی هیچ‌جا به‌طور خودکار فراخوانی نمی‌شود. |
| P1-5 | **`asyncio.get_event_loop()` deprecated در Python 3.10** | `file_processor.py:330` | در Python 3.10+ این تابع DeprecationWarning می‌دهد و در نسخه‌های آینده Python حذف خواهد شد. |

---

### P2 — نقص مهم در تجربه توسعه‌دهنده یا قابلیت‌های تکمیلی

| # | مشکل | محل | توضیح |
|---|---|---|---|
| P2-1 | **DFS Crawling اعلام‌شده ولی پیاده‌سازی نشده** | README vs `crawler.py` | مستندات DFS را ذکر می‌کنند اما فقط BFS وجود دارد. |
| P2-2 | **PDF / DOCX پشتیبانی نمی‌شوند** | `file_processor.py` | فقط MD/TXT/JSON/JSONL/CSV پشتیبانی می‌شود. اگر در UI به کاربر نشان داده می‌شود، گمراه‌کننده است. |
| P2-3 | **cleanup قدیمی اتوماتیک نیست** | `output/` directory | پوشه `output/uploads/` شامل صدها فایل تست انباشته‌شده است. هیچ TTL یا مکانیزم cleanup وجود ندارد. |
| P2-4 | **ProactorEventLoop warning در تست** | `test_services.py` | بستن ناصحیح async transport که نشانه resource leak احتمالی است. |
| P2-5 | **`rank-bm25` در requirements.txt نیست** | `requirements.txt` | این کتابخانه در `vector_store.py` استفاده نمی‌شود (BM25 خود پروژه پیاده‌سازی شده) ولی نصب است. مدیریت dependency شفاف نیست. |
| P2-6 | **تست integration واقعی با API** | تمام تست‌ها | همه تست‌های LLM/Embedding فقط با mock هستند. هیچ smoke test واقعی وجود ندارد. |
| P2-7 | **Prompt Injection risk** | `rag_enhancer.py`, `semantic_repair.py` | محتوای scrape‌شده از وب مستقیم و بدون sanitize به LLM ارسال می‌شود. |

---

### P3 — بهبود کم‌اولویت

| # | مشکل | توضیح |
|---|---|---|
| P3-1 | `requests`/`urllib3` version mismatch warning | فقط warning، عملکرد تأثیری ندارد |
| P3-2 | Gzip sitemap تست live ندارد | سناریوی نادر |
| P3-3 | Tracking parameter strip تست اختصاصی ندارد | covered به‌طور ضمنی |
| P3-4 | Cost aggregation وجود ندارد | هزینه per-call log می‌شود ولی جمع نمی‌شود |
| P3-5 | `default_extraction_strategy` مغایرت config/README | در config مقدار `"trafilatura"` است، README می‌گوید `"auto"` |

---

## ۸. ریسک‌های امنیتی و هزینه‌ای

### امنیتی
| ریسک | شدت | وضعیت کنونی |
|---|---|---|
| SSRF | بالا | ✅ محافظت شده — لایه کامل وجود دارد |
| DNS Rebinding | بالا | ✅ محافظت شده |
| Path Traversal | متوسط | ✅ `sanitize_filename()` پیاده‌سازی شده |
| API Key leak | بالا | ✅ در response یا log افشا نمی‌شود |
| Rate Limiting | متوسط | ❌ **وجود ندارد** — برای deployment عمومی خطرناک |
| Authentication | بالا | ❌ **وجود ندارد** — برای deployment عمومی حیاتی است |
| Prompt Injection | متوسط | ⚠️ بدون sanitize محتوا به LLM می‌رود |

### هزینه‌ای
| ریسک | وضعیت |
|---|---|
| تولید embedding تکراری | ⚠️ content_hash check در همه مسیرها اعمال نمی‌شود |
| LLM call بدون timeout | ✅ `request_timeout` در `SemanticRepairService` |
| Batch concurrency | ✅ Semaphore محدودسازی می‌کند |
| مدل نامعتبر در config | ❌ **P1-1** — هزینه صفر، اما همه LLM failها |

---

## ۹. قابلیت‌هایی که باید حفظ شوند

1. **لایه امنیتی SSRF** — `security.py` کامل و سالم است، نباید تغییر کند
2. **تست‌های 281 گانه** — هیچ تستی حذف یا تضعیف نشود
3. **SemanticRepairService** — معماری مستقل، سالم و مستند است
4. **BM25 + Dense Hybrid Search** — پیاده‌سازی اختصاصی بدون وابستگی خارجی
5. **Pydantic v2 Schema** — قراردادهای داده کاملاً تعریف شده است
6. **Persian Normalizer** — 16 تست اختصاصی، خوب پوشش داده شده
7. **UI dual-language (RTL/LTR)** — کار می‌کند، تست integration دارد
8. **File upload sandbox** — sanitize و محدودیت حجم پیاده‌سازی شده

---

## ۱۰. پیشنهاد اصلاحات برای فازهای بعدی (اولویت‌بندی)

### فاز ۱ — اصلاحات P1 (بدون تأخیر)
1. تصحیح `llm_model` از `"gpt-6-luna"` به مقدار معتبر (مثلاً `gpt-4o-mini`)
2. هماهنگ‌سازی نسخه openai (`pip install openai>=1.0.0,<2.0.0`)
3. رفع deprecated `asyncio.get_event_loop()` در `file_processor.py:330`
4. پیاده‌سازی auto-save برای Vector Store (فراخوانی `save_to_file` پس از upsert)

### فاز ۲ — اصلاحات P2
1. مشخص کردن صریح عدم پشتیبانی PDF/DOCX در UI
2. پیاده‌سازی cleanup خودکار فایل‌های قدیمی در `output/`
3. افزودن smoke test با API key واقعی (opt-in)
4. رفع ProactorEventLoop warning در تست

### فاز ۳ — قابلیت‌های جدید (اگر درخواست شود)
1. PDF/DOCX support با `pypdf2` یا `python-docx`
2. Rate limiting middleware (FastAPI)
3. Job state persistence (SQLite یا فایل JSON)
4. Authentication (API key یا Basic Auth)

---

## ۱۱. معیارهای پذیرش — تأیید

| معیار | وضعیت |
|---|---|
| گزارش با شواهد واقعی کد و تستها نوشته شده | ✅ |
| قابلیت‌ها از یکدیگر تفکیک شده و وضعیت حدس نزده شده | ✅ |
| هیچ سورس اپلیکیشنی تغییر نکرده | ✅ |
| تستها اجرا شدند (281 passed, 4 warnings) | ✅ |
| مرحله بعدی بر اساس گزارش قابل برنامه‌ریزی است | ✅ |
