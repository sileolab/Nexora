<div align="center">

<img src="docs/images/nexora_banner.svg" alt="Nexora Studio Banner" width="100%"/>

<br/>

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Engine-Playwright%20Chromium-45BA4B?style=for-the-badge&logo=playwright&logoColor=white)](https://playwright.dev/python/)
[![Crawl4AI](https://img.shields.io/badge/Engine-Crawl4AI-FF5722?style=for-the-badge)](https://crawl4ai.com/)
[![Tests Passing](https://img.shields.io/badge/Tests-474%20Passing%20(100%25)-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](tests/)
[![API Docs](https://img.shields.io/badge/API%20Portal-Interactive%20%2Fdocs-06b6d4?style=for-the-badge&logo=openapi-initiative&logoColor=white)](http://localhost:8000/docs)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

<br/>

**Nexora** is an enterprise-grade, asynchronous web crawling, content extraction, and data intelligence platform engineered specifically for **Retrieval-Augmented Generation (RAG)**, LLM knowledge grounding, and production semantic search systems.

[Live Studio Tour](#-live-studio-tour--visual-showcase) •
[System Pipeline](#-animated-pipeline-architecture) •
[Interactive Terminal](#-animated-developer-cli-experience) •
[4-Engine Comparison](#-4-engine-extraction-matrix) •
[IR Evaluation](#-information-retrieval-ir-evaluation-studio) •
[Interactive API Docs](#-bespoke-interactive-api-documentation-portal) •
[Python SDK & CLI](#-python-sdk--developer-cli) •
[Quickstart](#-quickstart-guide) •
[Production Deployment](#-production-deployment-docker--systemd)

</div>

---

## ⚡ Animated Developer CLI Experience

Experience autonomous multi-depth web discovery, Playwright headless extraction, Persian/multilingual semantic chunking, and IR benchmark evaluation executed directly from the terminal:

<div align="center">
  <img src="docs/images/nexora_terminal_animated.svg" alt="Nexora Terminal Experience" width="100%"/>
</div>

---

## 🔄 Animated Pipeline Architecture

Nexora transforms messy, unstructured, dynamic web pages and multi-format documents into clean, deduplicated, verified semantic chunks ready for production vector databases:

<div align="center">
  <img src="docs/images/nexora_pipeline_animated.svg" alt="Nexora Data Pipeline" width="100%"/>
</div>

---

## 📸 Live Studio Tour & Visual Showcase

Nexora features a modern, dark-themed glassmorphic Studio interface (`#0b0f17`) built with responsive desktop controls, real-time job telemetry, and instant visual inspection.

### 1. URL Discovery Studio
Autonomous recursive web crawler with XML sitemap auto-detection, robots.txt parser, regex pattern white/blacklisting, query-string retention, and live page metrics.
<div align="center">
  <img src="docs/images/dashboard_desktop_en.png" alt="URL Discovery Studio" width="100%"/>
</div>

<br/>

### 2. 4-Engine Content Extraction Studio
Autonomous page classification (Article, Docs, SPA, Product, FAQ) with an intelligent fallback cascade: Smart Auto, Playwright Chromium headless rendering, Crawl4AI, and Trafilatura.
<div align="center">
  <img src="docs/images/tab_extract.png" alt="Content Extraction Studio" width="100%"/>
</div>

<br/>

### 3. AI & RAG Structuring Studio
Persian & multilingual unicode normalization, semantic sentence-boundary chunking, automated markdown repair, multi-provider embedding generation (OpenAI, Gemini, Local), and hybrid dense search.
<div align="center">
  <img src="docs/images/tab_ai.png" alt="AI and RAG Structuring Studio" width="100%"/>
</div>

<br/>

### 4. Information Retrieval (IR) Evaluation Studio
Scientific retrieval benchmark laboratory computing Recall@K, MRR, and nDCG@K. Compare 3 algorithmic methods (Dense vs BM25 vs Hybrid) and inspect candidate exclusions with step-by-step pipeline tracing.
<div align="center">
  <img src="docs/images/tab_eval.png" alt="Information Retrieval Evaluation Studio" width="100%"/>
</div>

<br/>

### 5. Multi-Format File Processing Studio
Ingest PDF, DOCX, TXT, MD, JSON, and CSV documents directly. Automatic text extraction, structural normalization, semantic chunking, and instant vector store indexing.
<div align="center">
  <img src="docs/images/tab_files.png" alt="File Processing Studio" width="100%"/>
</div>

<br/>

### 6. AI Settings & Bring-Your-Own-Key (BYOK) Management
Configure your AI providers (OpenAI, Google Gemini, Ollama, DeepSeek) directly from the Studio. Secure secret encryption, custom Base URLs, and model selection.
<div align="center">
  <img src="docs/images/modal_ai_settings.png" alt="AI Provider Settings and BYOK" width="80%"/>
</div>

---

## 📖 Bespoke Interactive API Documentation Portal

Rather than relying on generic Swagger UI, Nexora includes a custom-designed, dark-themed developer documentation portal hosted at `/docs` (and aliased at `/api-docs`):

<div align="center">
  <img src="docs/images/api_docs_hero.png" alt="Interactive API Portal Hero" width="100%"/>
</div>

<br/>

<div align="center">
  <img src="docs/images/api_docs_endpoint_view.png" alt="Interactive API Endpoint View" width="100%"/>
</div>

### Key API Portal Highlights:
- **Complete Endpoint Coverage**: All **76 platform endpoints** categorized across 12 distinct functional modules.
- **Instant Search (`Ctrl + K`)**: Real-time fuzzy filtering across paths, summaries, HTTP methods, and parameter schemas.
- **Method Filter Pills**: Instant one-click filtering by `ALL`, `GET`, `POST`, `PUT`, `DELETE`.
- **4-Language Code Generator**: Copy-paste ready snippets in **cURL**, **Python (requests)**, **Python (Nexora SDK)**, and **JavaScript (fetch)**.
- **In-Browser "Try It Live" Console**: Test endpoints interactively against your local server with configurable headers, payloads, live status badges, latency timers, and formatted JSON output.

---

## ⚖️ 4-Engine Extraction Matrix

Nexora integrates 4 autonomous extraction engines to achieve maximum recall and throughput across arbitrary website architectures:

| Engine | Primary Technology | Best Used For | JS Execution | Throughput | Memory Overhead | Fallback Rank |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **🚀 Smart Auto** | Adaptive Cascade Router | General web crawling; detects page type and routes dynamically | Adaptive | High | Moderate | Default (Auto) |
| **🎭 Playwright Chromium** | Headless Browser Automation | Single Page Apps (React, Vue, Next.js), complex dynamic hydration | Full Headless | Moderate | Higher | Priority 1 (JS) |
| **🕷️ Crawl4AI** | Async Headless Pipeline | Structured article scraping, content blocks, markdown extraction | Headless | High | Moderate | Priority 2 (DOM) |
| **⚡ Trafilatura** | Fast HTTP DOM Stripper | High-speed static blogs, news articles, academic papers | None (Fast HTTP) | Ultra-High | Minimal | Priority 3 (Static) |

---

## 🔬 Information Retrieval (IR) Evaluation Studio

Nexora treats RAG ingestion not as an afterthought, but as an empirical science. The built-in IR Evaluation Studio allows teams to objectively benchmark search performance before deploying to production:

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                      MATHEMATICAL RETRIEVAL BENCHMARKS                        │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  1. Recall@K:                                                                 │
│     Recall@K = | Relevant Chunks in Top K | / | Total Relevant Ground Truth | │
│                                                                               │
│  2. Mean Reciprocal Rank (MRR):                                               │
│     MRR = (1 / |Q|) * ∑ ( 1 / rank_i )                                        │
│                                                                               │
│  3. Discounted Cumulative Gain (nDCG@K):                                      │
│     DCG@K = ∑ ( (2^(rel_i) - 1) / log2(i + 1) )                               │
│     nDCG@K = DCG@K / IDCG@K                                                   │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Algorithmic Comparison: 3 Retrieval Modes
1. **Dense Vector Search**: Cosine similarity against 1536-dimensional embeddings (OpenAI `text-embedding-3-small`, Gemini, or Local).
2. **BM25 Lexical Search**: Full-text inverted index with Okapi BM25 scoring for exact keyword and entity recall.
3. **Hybrid RRF Fusion**: Reciprocal Rank Fusion ($RRF\_Score = \sum \frac{1}{60 + rank}$) combining dense semantic understanding with lexical precision.

### Pipeline Exclusion Diagnostics
Inspect why specific documents failed to rank with the Step-by-Step Retrieval Debugger:
- **Step 1: Query Analysis & Tokenization**: Linguistic stem filtering.
- **Step 2: Metadata Filtering**: Workspace, domain, and category restriction.
- **Step 3: Score Cutoff**: Rejection below minimum similarity threshold.
- **Step 4: Context Expansion**: Neighbor window chunk attachment.

---

## 🏛️ Comprehensive Architecture Diagram

```mermaid
flowchart TD
    subgraph DISCOVERY ["1. Discovery & Ingestion Layer"]
        U["Target URLs / Root Domain"] --> R["Robots.txt Parser & Compliance"]
        U --> S["Sitemap XML Parser (Recursive)"]
        R & S --> D["Multi-Algorithm Crawler (BFS / DFS / Regex Filter)"]
        F["Document Files (PDF, DOCX, TXT, CSV)"] --> FP["File Processor & Converter"]
    end

    subgraph EXTRACTION ["2. Autonomous Multi-Engine Extraction Layer"]
        D --> PC["Page Classifier (Article / Docs / SPA / Product)"]
        PC --> ENG{"Engine Selector"}
        ENG -->|Static Text| E1["Trafilatura Engine"]
        ENG -->|Dynamic SPA| E2["Playwright Chromium Headless"]
        ENG -->|Browser Crawl| E3["Crawl4AI Engine"]
        ENG -->|Auto Mode| E4["Smart Auto Fallback Cascade"]
        E1 & E2 & E3 & E4 --> AB["Anti-Loader & Hydration Bypass Engine"]
        AB --> VP["Visible-Only DOM Pruning Filter"]
    end

    subgraph RAG_CLEANING ["3. Semantic Processing & Repair Layer"]
        VP & FP --> NORM["Persian / Arabic & Unicode Normalizer"]
        NORM --> CHK["Semantic Sentence Boundary Chunker (Size / Overlap)"]
        CHK --> REP["Automated Markdown Repair Service (Unclosed tags/tables)"]
        REP --> EMB["Embedding Service (OpenAI, Gemini, Local)"]
    end

    subgraph HYBRID_STORAGE ["4. Storage, Indexing & Evaluation Studio"]
        EMB --> VS[("In-Memory Hybrid Vector Store (Dense + BM25)")]
        VS --> INC["Differential Incremental Sync (SHA-256 Hashing)"]
        VS --> EVAL["IR Retrieval Benchmark Suite (Recall@K, MRR, nDCG)"]
        EVAL --> TRACE["Candidate Exclusion Tracing Debugger"]
    end

    subgraph PLATFORM_API ["5. API, Security & Multi-Tenancy Layer"]
        VS & EVAL --> REST["FastAPI Platform REST API (76 Endpoints)"]
        REST --> SEC["Multi-Tenant Isolation & BYOK Secrets Manager"]
        SEC --> METER["Usage Metering & Token Quota Enforcer"]
        REST --> UI["Nexora Studio Glassmorphic Dark UI"]
        REST --> DOCS["Interactive API Portal (/docs & /api-docs)"]
        REST --> SDK["Nexora Python SDK (NexoraClient)"]
        REST --> CLI["Nexora Developer CLI (nexora)"]
    end
```

---

## 💻 Python SDK & Developer CLI

### Official Python SDK (`NexoraClient`)

Install the client library:

```bash
pip install nexora
```

Execute an end-to-end extraction, semantic chunking, and hybrid search workflow in Python:

```python
from nexora import NexoraClient

# 1. Initialize client with base URL and API key
client = NexoraClient(
    base_url="http://localhost:8000",
    api_key="your_workspace_or_admin_key"
)

# 2. Check platform readiness
health = client.health()
print(f"Status: {health['status']} | Active Jobs: {health['active_jobs_count']}")

# 3. Trigger autonomous website discovery
discovery_job = client.discovery.start(
    root_url="https://docs.example.com",
    max_depth=3,
    max_pages=50,
    keep_query_params=False
)
print(f"Started Discovery Job: {discovery_job.id}")

# 4. Extract structured markdown using Playwright Chromium
extract_job = client.extraction.start(
    urls=["https://docs.example.com/guide"],
    engine="playwright",
    crawl_mode="single"
)

# 5. Semantic sentence-boundary chunking
chunks = client.rag.chunk_text(
    text="# Enterprise RAG Ingestion\n\nNexora delivers high-precision grounding...",
    chunk_size=500,
    chunk_overlap=50
)
for chunk in chunks:
    print(f"Chunk {chunk.id}: {chunk.token_count} tokens")

# 6. Execute Hybrid Search (Dense + BM25 RRF)
matches = client.vector_store.search(
    query="autonomous web crawling and semantic chunking",
    top_k=5,
    hybrid=True
)
for match in matches:
    print(f"Score {match.score:.3f} | {match.text[:90]}...")
```

### Developer CLI (`nexora`)

Nexora includes a complete developer CLI for automation, cron jobs, and terminal workflows:

```bash
# Display help and available command groups
nexora --help

# 1. Autonomous Web Crawler
nexora crawl --url https://example.com --max-depth 3 --max-pages 100 --concurrency 5

# 2. 4-Engine Content Extraction
nexora extract --url https://example.com/article --engine playwright --output ./output.md

# 3. File Processing & Ingestion
nexora files process --path ./manual.pdf --chunk --embed

# 4. Information Retrieval Benchmarking
nexora eval run --dataset prod_benchmark_v1 --top-k 5

# 5. Hybrid Vector Store Search
nexora search --query "dynamic hydration bypass" --top-k 3 --hybrid
```

---

## 🛠️ Quickstart Guide

### Prerequisites
- **Python**: 3.10, 3.11, or 3.12
- **Git**
- **Operating System**: Linux, macOS, or Windows (Windows Proactor Event Loop supported out-of-the-box)

### Step 1: Clone the Repository

```bash
git clone https://github.com/your-username/nexora.git
cd nexora
```

### Step 2: Setup Virtual Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate
```

### Step 3: Install Dependencies & Headless Browsers

```bash
# Install core platform requirements
pip install -r requirements.txt

# Install Playwright Chromium headless browser binaries
playwright install chromium
```

### Step 4: Configure Environment Variables

```bash
# Copy template configuration
cp .env.example .env
```

Key environment configuration options in `.env`:

```ini
APP_ENV=development
HOST=127.0.0.1
PORT=8000
LOG_LEVEL=INFO

# Master Secret (leave blank for local open development)
API_KEY=cbk_master_secret_key

# Optional: AI Provider Keys for RAG and Vector Embeddings
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIzaSy...
```

### Step 5: Launch Nexora Studio

```bash
python run.py
```

Access the platform:
- 🌐 **Nexora Studio UI**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- 📚 **Interactive API Portal**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- ⚙️ **OpenAPI JSON Spec**: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)
- 🛠️ **Raw Swagger UI**: [http://127.0.0.1:8000/swagger](http://127.0.0.1:8000/swagger)

---

## 🧪 Rigorous Testing & Quality Assurance

Nexora enforces strict code quality with a comprehensive suite of **474 automated tests** covering anti-bot evasion, SSRF security, vector math, IR evaluation, and multi-tenant data isolation:

```bash
# Run the complete test suite
pytest -q
```

```
================= 474 passed, 7 warnings in 69.81s (0:01:09) ==================
```

<details>
<summary><b>🔍 Click to expand the 28 Test Modules Breakdown</b></summary>

| Test Suite Module | Focus Area | Status |
| :--- | :--- | :---: |
| `test_phase1_antibot_core.py` | Anti-bot fingerprinting, anti-loader bypass | ✅ PASS |
| `test_phase1_security_hardening.py` | SSRF prevention, private IP blocking, DNS rebinding | ✅ PASS |
| `test_phase1_stabilization.py` | Concurrency limits, watchdog timeouts | ✅ PASS |
| `test_phase2_byok_security.py` | Customer secret encryption, BYOK credential rotation | ✅ PASS |
| `test_phase2_data_studio.py` | Stage inspection, chunk merging, splitting | ✅ PASS |
| `test_phase2_response_classification.py` | Page type classifier, HTML fallback router | ✅ PASS |
| `test_phase3_rag_evaluation.py` | Recall@K, MRR, nDCG metrics, comparative runs | ✅ PASS |
| `test_phase3_tenant_data_isolation.py` | Multi-tenant storage boundary enforcement | ✅ PASS |
| `test_phase4_developer_platform.py` | Incremental sync, API v1 routing, OpenAPI integrity | ✅ PASS |
| `test_phase4_usage_metering_and_quotas.py` | Token quotas, request rate limiting | ✅ PASS |
| `test_semantic_repair.py` | Markdown tag closing, table alignment repair | ✅ PASS |
| `test_multi_algorithm_discovery.py` | BFS vs DFS vs Sitemap crawler routing | ✅ PASS |
| `test_normalizer.py` | Persian/Arabic unicode normalization, half-spaces | ✅ PASS |
| `test_playwright_engine.py` | Chromium headless lifecycle, dynamic SPA wait | ✅ PASS |
| `test_rag_pipeline_and_deduplication.py` | Sentence chunking, SHA-256 deduplication | ✅ PASS |

</details>

---

## 🐳 Production Deployment (Docker & Systemd)

### Docker & Docker Compose

Deploy the complete Nexora platform using Docker:

```yaml
version: "3.9"

services:
  nexora:
    build: .
    container_name: nexora-studio
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - APP_ENV=production
      - HOST=0.0.0.0
      - PORT=8000
      - API_KEY=${NEXORA_MASTER_SECRET}
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
```

```bash
# Build and run containers
docker compose up -d --build
```

### Linux Systemd Service

```ini
[Unit]
Description=Nexora Web Intelligence & RAG Platform
After=network.target

[Service]
Type=simple
User=nexora
WorkingDirectory=/opt/nexora
ExecStart=/opt/nexora/.venv/bin/python run.py
Restart=always
RestartSec=5
Environment=APP_ENV=production

[Install]
WantedBy=multi-user.target
```

---

## 🚀 Pushing to GitHub (Step-by-Step Guide)

To publish your Nexora repository to GitHub:

### 1. Stage Cleaned Files and Commit
All temporary files (`scratch/`, `data/`, `.env`) are automatically excluded by our `.gitignore`:

```bash
git add .
git commit -m "feat(nexora): launch Nexora Studio v5.0 with 4-engine crawler, IR evaluation, interactive API docs, and multi-tenant SDK"
```

### 2. Connect to your GitHub Repository
Create a new empty repository named `Nexora` on GitHub (without initializing README/license):

```bash
# Rename branch to main
git branch -M main

# Set remote origin URL (replace with your GitHub username)
git remote set-url origin https://github.com/<YOUR_USERNAME>/Nexora.git

# Push code to GitHub
git push -u origin main
```

---

## 🤝 Contributing

Contributions are welcomed! Please follow these guidelines:

1. Fork the Project on GitHub.
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`).
3. Verify test passing (`pytest -q`).
4. Commit your Changes (`git commit -m 'feat: add amazing feature'`).
5. Push to the Branch (`git push origin feature/AmazingFeature`).
6. Open a Pull Request.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

<div align="center">
  <sub>Built with ❤️ by the Nexora Intelligence Team. Engineered for production RAG & Agentic AI workflows.</sub>
</div>
