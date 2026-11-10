# 🚀 Nexora Python SDK Reference Manual

Official Python client documentation for the **Nexora Studio & Developer Platform**.

---

## 📋 Table of Contents
1. [Installation & Setup](#1-installation--setup)
2. [Client Initialization & Authentication](#2-client-initialization--authentication)
3. [Website Crawling & URL Discovery](#3-website-crawling--url-discovery)
4. [4-Engine Content Extraction](#4-4-engine-content-extraction)
5. [Anti-Bot Stealth Engine](#5-anti-bot-stealth-engine)
6. [Job Lifecycle & Polling](#6-job-lifecycle--polling)
7. [Multi-Format File Ingestion](#7-multi-format-file-ingestion)
8. [Semantic Chunking & AI Repair](#8-semantic-chunking--ai-repair)
9. [Hybrid Search & Vector Databases](#9-hybrid-search--vector-databases)
10. [Live Watchers & Autonomous Auto-Detect](#10-live-watchers--autonomous-auto-detect)
11. [Single-Trigger Auto-Stop Mode](#11-single-trigger-auto-stop-mode)
12. [Exception Hierarchy](#12-exception-hierarchy)
13. [Complete Production Blueprints](#13-complete-production-blueprints)

---

## 1. Installation & Setup

Install from the repository root:

```bash
pip install -e .

# Optional Playwright headless browser support:
pip install "nexora[playwright]"
playwright install chromium
```

---

## 2. Client Initialization & Authentication

```python
from nexora import NexoraClient

# Standard connection
client = NexoraClient(base_url="http://127.0.0.1:8000")

# Production connection with API Key and tenant isolation
client = NexoraClient(
    base_url="https://api.nexora.internal",
    api_key="nx_live_9f82a17b0c",
    workspace_id="ws_finance_prod",
    timeout=45.0
)

# Server health check
status = client.health()
print("Server status:", status["status"])
```

---

## 3. Website Crawling & URL Discovery

```python
# Instant recursive discovery
job = client.discover_urls(
    root_url="https://example.com",
    max_depth=3,
    max_pages=100,
    include_patterns=[r"^https://example\.com/blog/.*"],
    browser_fallback=True
)

# Wait for completion:
completed = client.wait_for_job(job.id, timeout=120.0)
print(f"Discovered {len(completed.discovered_urls)} URLs")
```

---

## 4. 4-Engine Content Extraction

Nexora offers 4 distinct extraction strategies:
- `auto`: Adaptive Cascade Router (detects dynamic/static pages automatically).
- `playwright`: Headless Chromium for single-page apps (React/Vue/Next.js) & dynamic DOMs.
- `crawl4ai`: Deep structured markdown and content block extraction.
- `trafilatura`: Ultra-fast static HTTP text stripper.

```python
doc = client.extract_content(
    url="https://en.wikipedia.org/wiki/Artificial_intelligence",
    strategy="auto",
    css_selector="#mw-content-text"
)
print("Title:", doc.title)
print("Text length:", len(doc.cleaned_text))
```

---

## 5. Anti-Bot Stealth Engine

The stealth system automatically resolves Cloudflare Turnstile, PerimeterX, synthetic loading screens, and human mouse/touch emulation without manual configuration.

---

## 6. Job Lifecycle & Polling

```python
# Check job status
job = client.get_job(job_id="job_12345")

# List all background jobs
jobs = client.list_jobs(limit=20, offset=0)

# Cancel an active job
client.cancel_job("job_12345")
```

---

## 7. Multi-Format File Ingestion

Process local files into RAG documents:

```python
result = client.process_file(
    file_path="./quarterly_report.pdf",
    strategy="balanced"  # 'fast', 'balanced', or 'deep_structural'
)
print("Document ID:", result["document_id"])
```

---

## 8. Semantic Chunking & AI Repair

```python
# 1. Segment into semantic chunks
client.chunk_job(job_id=job.id, chunk_size=500, chunk_overlap=50)

# 2. Repair cut-off sentences & grammatical boundaries
client.repair_chunks(job_id=job.id)

# 3. Generate dense vector embeddings
client.embed_chunks(job_id=job.id, model="text-embedding-3-small")
```

---

## 9. Hybrid Search & Vector Databases

Combine BM25 lexical search with vector similarity:

```python
results = client.search(
    job_id=job.id,
    query="What is the net profit margin?",
    top_k=5,
    method="hybrid",  # 'hybrid', 'dense', or 'bm25'
    alpha=0.7,
    expand_neighbors=True
)

for r in results:
    print(f"[{r.score:.4f}] {r.text[:100]}...")

# Sync directly to Qdrant, Chroma, or Pinecone:
client.export_to_qdrant(job.id, collection_name="company_kb")
```

---

## 10. Live Watchers & Autonomous Auto-Detect

### A. Autonomous Zero-Selector Mode:
```python
# Tested on CoinMarketCap Bitcoin, Binance tickers, and e-commerce feeds:
for event in client.live.watch(
    url="https://coinmarketcap.com/currencies/bitcoin/",
    auto_detect=True,           # Discovers price, cap, volume automatically
    observation_seconds=3.0,
    interval_seconds=2.0
):
    print(f"[{event.timestamp}] Live Mutation #{event.change_count}")
    print("Diff:", event.diff)
    print("New Live State (Previous Replaced):", event.latest_data)
```

### B. Discover Dynamic Fields & CSS Selectors:
```python
scan = client.live.auto_detect(
    url="https://coinmarketcap.com/currencies/bitcoin/",
    observation_seconds=3.0
)
for f in scan.detected_fields:
    print(f"• {f.name} -> {f.selector} ('{f.sample_value}')")
```

---

## 11. Single-Trigger Auto-Stop Mode

```python
# Automatically turns OFF once a change is detected and replaced:
for event in client.live.watch(
    url="https://tickets.example.com/event",
    selectors={"status": ".inventory-status"},
    single_trigger=True
):
    print("Ticket unlocked:", event.latest_data)
    break
```

---

## 12. Exception Hierarchy

```python
from nexora.exceptions import (
    NexoraError,               # Base SDK exception
    NexoraAPIError,            # 4xx/5xx HTTP errors
    NexoraAuthenticationError, # 401/403 Auth failures
    NexoraNotFoundError,       # 404 Not Found
    NexoraTimeoutError         # Job wait timeout
)
```

---

## 13. Complete Production Blueprints

### Blueprint 1: Crypto Arbitrage Alert Bot
```python
from nexora import NexoraClient

client = NexoraClient()
for event in client.live.watch("https://coinmarketcap.com/currencies/bitcoin/", auto_detect=True):
    diff = event.diff
    if "price" in diff:
        print(f"BTC moved: {diff['price']['old']} -> {diff['price']['new']}")
```

### Blueprint 2: Enterprise RAG Assistant
```python
from nexora import NexoraClient

client = NexoraClient()
job = client.crawl_website("https://docs.example.com", max_pages=30)
client.wait_for_job(job.id)
client.chunk_job(job.id, chunk_size=400)
client.repair_chunks(job.id)
client.embed_chunks(job.id)

hits = client.search(job.id, query="How do I configure SSL?", top_k=3, method="hybrid")
for h in hits:
    print(h.text)
```
