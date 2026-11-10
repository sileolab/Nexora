# راهنمای جامع توسعه‌دهندگان Nexora Studio
## Developer API, Python SDK, CLI, Incremental Sync & Vector Integrations

نسخه: `4.0.0` | پایپ‌لاین آماده‌سازی و ارزیابی RAG

---

### فهرست سناریوها

1. [سناریو ۱: پردازش و استخراج مستقیم یک URL](#سناریو-۱-پردازش-و-استخراج-مستقیم-یک-url)
2. [سناریو ۲: پیمایش و استخراج خودکار وب‌سایت از طریق Sitemap و Crawler](#سناریو-۲-پیمایش-و-استخراج-خودکار-وبسایت-از-طریق-sitemap-و-crawler)
3. [سناریو ۳: پردازش و نرمال‌سازی فایل‌های محلی (PDF, DOCX, TXT, HTML)](#سناریو-۳-پردازش-و-نرمالسازی-فایلهای-محلی-pdf-docx-txt-html)
4. [سناریو ۴: تولید قطعات متنی هوشمند (Semantic Chunking)](#سناریو-۴-تولید-قطعات-متنی-هوشمند-semantic-chunking)
5. [سناریو ۵: تولید بردارها (Embeddings) و ترمیم معنایی مرز قطعات](#سناریو-۵-تولید-بردارها-embeddings-و-ترمیم-معنایی-مرز-قطعات)
6. [سناریو ۶: خروجی استاندارد و دانلود داده‌ها (JSONL, CSV, Markdown)](#سناریو-۶-خروجی-استاندارد-و-دانلود-دادهها-jsonl-csv-markdown)
7. [سناریو ۷: راهنمای کار با Python SDK رسمی (`nexora`)](#سناریو-۷-راهنمای-کار-با-python-sdk-رسمی-nexora)
8. [سناریو ۸: راهنمای استفاده از ابزار خط فرمان (CLI)](#سناریو-۸-راهنمای-استفاده-از-ابزار-خط-فرمان-cli)
9. [سناریو ۹: عیب‌یابی و پایش وضعیت کارها (Job Troubleshooting & Monitoring)](#سناریو-۹-عیبیابی-و-پایش-وضعیت-کارها-job-troubleshooting--monitoring)
10. [سناریو ۱۰: ادغام مستقیم خروجی در پروژه‌های RAG موجود (LangChain / LlamaIndex / Qdrant)](#سناریو-۱۰-ادغام-مستقیم-خروجی-در-پروژههای-rag-موجود-langchain--llamaindex--qdrant)
11. [بخش تکمیلی: پردازش افزایشی (Incremental Synchronization)](#بخش-تکمیلی-پردازش-افزایشی-incremental-synchronization)
12. [احراز هویت و امنیت API](#احراز-هویت-و-امنیت-api)

---

### احراز هویت و امنیت API

به صورت پیش‌فرض در محیط توسعه محلی (`NEXORA_API_KEY` یا `CRAWLBOT_API_KEY` تنظیم‌نشده)، دسترسی آزاد است. در صورتی که متغیر محیطی `NEXORA_API_KEY` یا `CRAWLBOT_API_KEY` در فایل `.env` یا سیستم مقداردهی شود، تمامی درخواست‌های اندپوینت‌های تحت `/api/*` و `/api/v1/*` نیازمند ارسال کلید در هدر درخواست خواهند بود:

```http
X-API-Key: your-secret-api-key
# یا
Authorization: Bearer your-secret-api-key
```

مسیرهای عمومی آزاد: `/`, `/static/*`, `/health`, `/api/health`, `/api/v1/health`, `/docs`, `/redoc`, `/openapi.json`.

---

### سناریو ۱: پردازش و استخراج مستقیم یک URL

#### با استفاده از cURL / REST API:
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/extraction/single" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://example.com/article",
       "strategy": "trafilatura"
     }'
```

#### با استفاده از Python SDK:
```python
from nexora import NexoraClient

with NexoraClient(base_url="http://127.0.0.1:8000") as client:
    doc = client.extract_url(
        url="https://example.com/article",
        strategy="trafilatura"  # 'trafilatura', 'bs4', یا 'playwright'
    )
    print(f"عنوان: {doc.title}")
    print(f"تعداد واژگان: {doc.word_count}")
    print(f"پیش‌نمایش Markdown:\n{doc.markdown[:200]}")
```

#### با استفاده از CLI:
```bash
nexora extract "https://example.com/article" --strategy trafilatura -o article.md
```

---

### سناریو ۲: پیمایش و استخراج خودکار وب‌سایت از طریق Sitemap و Crawler

#### با استفاده از cURL / REST API:
```bash
# ۱. شروع کار استخراج
curl -X POST "http://127.0.0.1:8000/api/v1/extraction/start" \
     -H "Content-Type: application/json" \
     -d '{
       "start_url": "https://docs.example.com",
       "max_depth": 2,
       "max_pages": 50,
       "strategy": "trafilatura"
     }'

# پاسخ: {"job_id": "job_abc123", "status": "pending"}
```

#### با استفاده از Python SDK:
```python
from nexora import NexoraClient

with NexoraClient() as client:
    # شروع کار و انتظار برای اتمام پردازش
    job = client.start_crawl(
        url="https://docs.example.com",
        max_depth=2,
        max_pages=50,
        wait=True,
        wait_timeout=180.0
    )
    print(f"وضعیت نهایی: {job.state}")
    print(f"تعداد صفحات استخراج‌شده: {job.documents_count}")
```

#### با استفاده از CLI:
```bash
# شروع کار و انتظار تا پایان عملیات
nexora crawl "https://docs.example.com" --max-pages 30 --max-depth 2 --wait
```

---

### سناریو ۳: پردازش و نرمال‌سازی فایل‌های محلی (PDF, DOCX, TXT, HTML)

#### با استفاده از Python SDK:
```python
from nexora import NexoraClient

client = NexoraClient()
result = client.process_file("data/user_manual.pdf", strategy="balanced")
print("نتیجه پردازش فایل محلی:")
print(f"شناسه سند: {result.get('file_id')}")
print(f"متن استخراج‌شده: {result.get('text')[:150]}...")
```

#### با استفاده از CLI:
```bash
nexora file "./contracts/terms.docx" --strategy fast
```

---

### سناریو ۴: تولید قطعات متنی هوشمند (Semantic Chunking)

تقطیع اسناد بر اساس طول نشانه‌ها (Token-aware)، ساختار تیترها (Heading context preservation) و عدم شکستن جملات کلیدی:

#### با استفاده از REST API:
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/ai/chunk" \
     -H "Content-Type: application/json" \
     -d '{
       "job_id": "job_abc123",
       "chunk_size": 500,
       "chunk_overlap": 50,
       "strategy": "token"
     }'
```

#### با استفاده از Python SDK:
```python
from nexora import NexoraClient

client = NexoraClient()
chunk_res = client.chunk_job(job_id="job_abc123", chunk_size=500, chunk_overlap=50)
print(f"قطعات تولید شده: {chunk_res.get('total_chunks')}")
```

#### با استفاده از CLI:
```bash
nexora chunk "job_abc123" --size 500 --overlap 50
```

---

### سناریو ۵: تولید بردارها (Embeddings) و ترمیم معنایی مرز قطعات

#### با استفاده از Python SDK:
```python
from nexora import NexoraClient

client = NexoraClient()

# ۱. ترمیم معنایی مرز چانک‌ها و پیوند جملات ناتمام
repair_res = client.repair_chunks(job_id="job_abc123")
print(f"چانک‌های ترمیم‌شده: {repair_res.get('repaired_count')}")

# ۲. وکتورسازی با مدل دلخواه
embed_res = client.embed_chunks(job_id="job_abc123", model="text-embedding-3-small")
print(f"بردارهای تولیدشده: {embed_res.get('embedded_count')}")
```

#### با استفاده از CLI:
```bash
nexora embed "job_abc123" --model text-embedding-3-small
```

---

### سناریو ۶: خروجی استاندارد و دانلود داده‌ها (JSONL, CSV, Markdown)

#### با استفاده از REST API:
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/export/download" \
     -H "Content-Type: application/json" \
     -d '{"job_id": "job_abc123", "format": "jsonl"}' \
     --output dataset.jsonl
```

#### با استفاده از Python SDK:
```python
from nexora import NexoraClient

client = NexoraClient()
client.export_job(
    job_id="job_abc123",
    export_format="jsonl",
    output_file="exports/clean_dataset.jsonl"
)
print("فایل خروجی با موفقیت در exports/clean_dataset.jsonl ذخیره شد.")
```

#### با استفاده از CLI:
```bash
nexora export "job_abc123" --format jsonl -o dataset.jsonl
```

---

### سناریو ۷: راهنمای کار با Python SDK رسمی (`nexora`)

نصب پکیج یا ایمپورت محلی (با پشتیبانی کامل از نام مستعار `crawlbot` جهت سازگاری به عقب):
```python
import os
from nexora import NexoraClient, NexoraError, NexoraTimeoutError

# تنظیمات اتصال (پشتیبانی خودکار از متغیرهای NEXORA_* و CRAWLBOT_*)
client = NexoraClient(
    base_url=os.getenv("NEXORA_BASE_URL", os.getenv("CRAWLBOT_BASE_URL", "http://127.0.0.1:8000")),
    api_key=os.getenv("NEXORA_API_KEY", os.getenv("CRAWLBOT_API_KEY", None)),
    timeout=60.0
)

try:
    # پایش سلامت سرور
    if client.ping():
        print("ارتباط با موتور Nexora برقرار است.")

    # اجرای جست‌وجوی آزمایشی RAG روی یک Job
    results = client.search(
        job_id="job_abc123",
        query="نحوه راه‌اندازی و اتصال API",
        top_k=3,
        method="hybrid",  # 'hybrid', 'dense', 'bm25'
        alpha=0.7,
        min_score=0.2
    )

    for hit in results:
        print(f"[{hit.score:.3f}] {hit.source_url} | {hit.text[:100]}...")

finally:
    client.close()
```

---

### سناریو ۸: راهنمای استفاده از ابزار خط فرمان (CLI)

اجرای ابزار خط فرمان مستقیم (`nexora`) یا از طریق ماژول پایتون (`python -m nexora.cli`):
```bash
# مشاهده راهنمای دستورات
nexora --help

# ۱. پایش وضعیت سرویس
nexora ping -v

# ۲. استخراج صفحه واحد
nexora extract "https://docs.python.org/3/tutorial/" -o tutorial.md

# ۳. کشف نشانی‌های وب‌سایت (هماهنگ با تب URL Discovery)
nexora discover "https://docs.python.org/3/" --max-pages 50 --max-depth 2 --wait -o urls.json

# ۴. بررسی وضعیت کار در حال اجرا
nexora status "job_12345"

# ۵. انتظار تا پایان کار
nexora wait "job_12345" --timeout 180

# ۶. اجرای جست‌وجوی ترکیبی RAG
nexora search "job_12345" "احراز هویت توکن" --method hybrid --top-k 5

# ۷. دریافت گزارش کیفیت دیتاست
nexora quality "job_12345"
```

---

### سناریو ۹: عیب‌یابی و پایش وضعیت کارها (Job Troubleshooting & Monitoring)

#### بررسی گام‌به‌گام وضعیت کار:
```python
from nexora import NexoraClient

client = NexoraClient()
job = client.get_job("job_abc123")

print(f"شناسه: {job.job_id}")
print(f"وضعیت: {job.state}") # pending, running, completed, failed, cancelled
if job.state == "failed":
    print(f"علت بروز خطا: {job.error}")

# بررسی مراحل تفکیک‌شده Pipeline
report = client.get_quality_report("job_abc123")
print(f"نمره کیفی پایپ‌لاین: {report.overall_score:.2f} / 100")
for rec in report.recommendations:
    print(f" - پیشنهاد بهینه‌سازی: {rec}")
```

---

### سناریو ۱۰: ادغام مستقیم خروجی در پروژه‌های RAG موجود (LangChain / LlamaIndex / Qdrant)

#### ۱. همگام‌سازی مستقیم با پایگاه داده برداری Qdrant:
```python
from nexora import NexoraClient

client = NexoraClient()
res = client.export_to_qdrant(
    job_id="job_abc123",
    collection_name="nexora_chunks",
    qdrant_url="http://localhost:6333",
    batch_size=64
)
print(f"تعداد {res['points_synced']} قطعه به کالکشن Qdrant منتقل شد.")
```

#### ۲. استفاده در پایپ‌لاین بازیابی LangChain:
```python
import json
from langchain_core.documents import Document
from langchain_community.vectorstores import Qdrant
from langchain_openai import OpenAIEmbeddings

# بارگذاری خروجی JSONL تولیدشده توسط Nexora
documents = []
with open("dataset.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        item = json.loads(line)
        doc = Document(
            page_content=item["text"],
            metadata={
                "source": item.get("source_url"),
                "title": item.get("title"),
                "heading": item.get("heading_context"),
                "quality_score": item.get("quality_score", 0.0),
            }
        )
        documents.append(doc)

print(f"آماده‌سازی {len(documents)} سند استاندارد برای زنجیره LangChain RAG.")
```

---

### بخش تکمیلی: پردازش افزایشی (Incremental Synchronization)

پایپ‌لاین Nexora تغییرات وب‌سایت را بر پایه **هش محتوای بدنه (SHA-256)** و ردپای تنظیمات تحلیل می‌کند:
* **اسناد دست‌نخورده (Unchanged):** بدون استخراج و Embedding مجدد، چانک‌ها و وکتورهای قبلی مستقیماً استفاده می‌شوند (صرفه‌جویی ۹۰٪ در زمان و هزینه API).
* **اسناد اصلاح‌شده (Modified):** تنها قطعات مربوط به همان صفحات مجدداً تقطیع و تعویض می‌شوند.
* **اسناد حذف‌شده (Deleted):** صفحات حذف‌شده از وب‌سایت، پس از موفقیت پردازش به صورت ایمن از وکتوراستور پاک می‌شوند.

```python
from nexora import NexoraClient

client = NexoraClient()
report = client.sync_incremental(
    project_id="my_docs_site",
    candidate_urls=[
        "https://docs.example.com/intro",
        "https://docs.example.com/api",
        "https://docs.example.com/new-feature"
    ],
    chunk_size=500,
    chunk_overlap=50
)

print(f"اسناد جدید: {len(report.new_urls)}")
print(f"اسناد بدون تغییر (Reused): {len(report.unchanged_urls)}")
print(f"تعداد قطعات بازاستفاده‌شده: {report.reused_chunks}")
```
