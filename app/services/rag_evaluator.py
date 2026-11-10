"""RAG Retrieval Evaluation, Search Playground, and Debugging Service.

This service powers Phase 3 of Crawlbot Studio:
1. Retrieval Playground (Dense, BM25, Hybrid search with strict score labeling).
2. Multi-Method Side-by-Side Comparison.
3. Standard Evaluation Datasets (with human review tracking and safe synthetic QA imports).
4. Strict, Grounded Information Retrieval Metrics (Recall@K, Precision@K, MRR, nDCG@K, Hit Rate).
5. Pipeline Version & Retrieval Config Comparison (metric deltas, query transitions).
6. Deterministic Retrieval Debugging & Candidate Exclusion Tracing.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from app.core.config import get_settings
from app.jobs.manager import JobManager, get_job_manager
from app.schemas.chunks import DocumentChunk
from app.schemas.eval import (
    EvalDataset,
    EvalRunConfig,
    EvalRunResult,
    EvalSample,
    MethodComparisonResult,
    PlaygroundSearchResult,
    RetrievalDebugTrace,
    RetrievalItemTrace,
    RunComparisonResult,
    SampleMetrics,
)
from app.services.dataset_studio import dataset_studio
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore, tokenize_for_search

logger = logging.getLogger(__name__)

# Check for Persian characters in query
_PERSIAN_CHAR_RE = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")


class RAGEvaluatorService:
    """Core domain service for RAG evaluation, playground search, and retrieval debugging."""

    def __init__(
        self,
        job_manager: Optional[JobManager] = None,
        datasets_file: Optional[str] = os.path.join("output", "eval_datasets.json"),
        runs_file: Optional[str] = os.path.join("output", "eval_runs.json"),
    ) -> None:
        self._manager = job_manager
        self.datasets_file = datasets_file
        self.runs_file = runs_file

        self._eval_datasets: dict[str, EvalDataset] = {}
        self._eval_runs: dict[str, EvalRunResult] = {}
        # Cache of isolated VectorStore instances: (job_id, version_label, chunk_hash) -> VectorStore
        self._store_cache: dict[tuple[str, Optional[str], str], VectorStore] = {}

        self._load_state()

    @property
    def manager(self) -> JobManager:
        if self._manager is None:
            self._manager = get_job_manager()
        return self._manager

    # -----------------------------------------------------------------------
    # State Persistence
    # -----------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist evaluation datasets and runs to disk."""
        try:
            if self.datasets_file:
                os.makedirs(os.path.dirname(os.path.abspath(self.datasets_file)), exist_ok=True)
                data = {k: v.model_dump(mode="json") for k, v in self._eval_datasets.items()}
                with open(self.datasets_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

            if self.runs_file:
                os.makedirs(os.path.dirname(os.path.abspath(self.runs_file)), exist_ok=True)
                data = {k: v.model_dump(mode="json") for k, v in self._eval_runs.items()}
                with open(self.runs_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Could not persist evaluation state to disk: %s", exc)

    def _load_state(self) -> None:
        """Load persisted evaluation datasets and runs from disk."""
        try:
            if self.datasets_file and os.path.exists(self.datasets_file):
                with open(self.datasets_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    self._eval_datasets[k] = EvalDataset.model_validate(v)

            if self.runs_file and os.path.exists(self.runs_file):
                with open(self.runs_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    self._eval_runs[k] = EvalRunResult.model_validate(v)
        except Exception as exc:
            logger.warning("Could not load evaluation state from disk: %s", exc)

    # -----------------------------------------------------------------------
    # Dataset & Version Resolution (Isolated VectorStore)
    # -----------------------------------------------------------------------

    def get_dataset_chunks(
        self,
        job_id: str,
        version_label: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[DocumentChunk]:
        """Resolve chunk list for a job, optionally targeted at an immutable snapshot version."""
        if tenant_id:
            job = self.manager.get_job(job_id, tenant_id=tenant_id)
            if not job:
                raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")

        if version_label and version_label.lower() not in ("current", "live"):
            snaps = dataset_studio._snapshots.get(job_id, [])
            snap = next((s for s in snaps if s.get("version") == version_label), None)
            if snap:
                return snap.get("chunks", [])
            logger.warning("Snapshot version '%s' not found for job '%s'; falling back to current chunks", version_label, job_id)

        return self.manager.get_chunks(job_id, tenant_id=tenant_id)

    def get_isolated_store(
        self,
        job_id: str,
        version_label: Optional[str] = None,
        chunks: Optional[list[DocumentChunk]] = None,
        tenant_id: Optional[str] = None,
    ) -> VectorStore:
        """Return or create an isolated, in-memory VectorStore for the specific dataset version."""
        if chunks is None:
            chunks = self.get_dataset_chunks(job_id, version_label, tenant_id=tenant_id)

        sorted_hashes = sorted(c.content_hash or "" for c in chunks)
        chunk_hash = hashlib.sha256("".join(sorted_hashes).encode("utf-8")).hexdigest()
        cache_key = (job_id, version_label, chunk_hash, tenant_id)

        if cache_key in self._store_cache:
            return self._store_cache[cache_key]

        # Create fresh isolated store with no file persistence
        store = VectorStore(expected_dim=1536, storage_path=None)
        if chunks:
            store.upsert_chunks(chunks, tenant_id=tenant_id)

        self._store_cache[cache_key] = store
        return store

    async def _compute_query_vector(self, query: str) -> Optional[list[float]]:
        """Compute query embedding vector if OpenAI API key is configured."""
        settings = get_settings()
        api_key = settings.openai_api_key.strip()
        if not api_key:
            return None

        try:
            embedder = EmbeddingService(
                api_key=api_key,
                base_url=settings.openai_base_url or None,
                model=settings.embedding_model,
            )
            temp_chunk = DocumentChunk(
                chunk_id="eval_q",
                source_url="",
                chunk_index=0,
                total_chunks=1,
                text=query,
                char_count=len(query),
                word_count=len(query.split()),
            )
            await embedder.embed_chunks([temp_chunk])
            return temp_chunk.embedding
        except Exception as exc:
            logger.warning("Failed to compute query vector: %s", exc)
            return None

    # -----------------------------------------------------------------------
    # Section A: Retrieval Playground
    # -----------------------------------------------------------------------

    async def search_playground(
        self,
        job_id: str,
        query: str,
        method: Literal["dense", "bm25", "hybrid"] = "hybrid",
        top_k: int = 5,
        alpha: float = 0.7,
        min_score: float = 0.0,
        category: Optional[str] = None,
        source_url: Optional[str] = None,
        language: Optional[str] = None,
        expand_neighbors: bool = False,
        version_label: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> PlaygroundSearchResult:
        """Execute interactive retrieval with explicit score labeling and neighbor context."""
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("متن پرسش (query) نمی‌تواند خالی باشد.")

        chunks = self.get_dataset_chunks(job_id, version_label, tenant_id=tenant_id)
        if not chunks:
            return PlaygroundSearchResult(
                query=cleaned_query,
                job_id=job_id,
                version_label=version_label,
                method=method,
                top_k=top_k,
                alpha=alpha,
                min_score=min_score,
                filters_applied={"category": category, "source_url": source_url, "language": language},
                latency_ms=0.0,
                total_candidates_considered=0,
                total_returned=0,
                results=[],
                score_scale_warning="هیچ قطعه‌ای برای این کار یا نسخه یافت نشد.",
            )

        store = self.get_isolated_store(job_id, version_label, chunks, tenant_id=tenant_id)
        start_time = time.perf_counter()

        query_vector = None
        if method in ("dense", "hybrid"):
            query_vector = await self._compute_query_vector(cleaned_query)

        hybrid_flag = (method == "hybrid")
        search_alpha = alpha if method == "hybrid" else (1.0 if method == "dense" else 0.0)

        # Execute search via isolated vector store
        raw_results = store.search(
            query=cleaned_query,
            query_vector=query_vector,
            top_k=top_k,
            category=category,
            source_url=source_url,
            min_score=min_score,
            hybrid=hybrid_flag,
            alpha=search_alpha,
            expand_neighbors=expand_neighbors,
            tenant_id=tenant_id,
        )
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Convert to detailed trace items with explicit score labeling
        traces: list[RetrievalItemTrace] = []
        for rank_idx, item in enumerate(raw_results, 1):
            chunk = item.chunk
            if method == "dense":
                score_type = "Cosine Similarity [0.0 - 1.0] (معنایی)"
                display_score = item.dense_score if item.dense_score is not None else item.score
            elif method == "bm25":
                score_type = "BM25 Normalized [0.0 - 1.0] (لغوی)"
                display_score = item.sparse_score if item.sparse_score is not None else item.score
            else:
                score_type = f"Hybrid Weighted Score [α={alpha:.2f}]"
                display_score = item.score

            neighbor_previews = [
                f"[قطعه {n.chunk_index + 1}/{n.total_chunks}]: {n.text[:120]}..."
                for n in item.neighbors
            ]

            traces.append(
                RetrievalItemTrace(
                    chunk_id=chunk.chunk_id,
                    source_url=chunk.source_url,
                    heading_context=chunk.heading_context,
                    title=chunk.title or chunk.source_title,
                    category=chunk.category,
                    language=chunk.language,
                    rank=rank_idx,
                    score=round(display_score or 0.0, 4),
                    raw_dense_score=item.dense_score,
                    raw_sparse_score=item.sparse_score,
                    score_type=score_type,
                    search_method=method,
                    text_preview=chunk.text,
                    char_count=chunk.char_count,
                    neighbors_count=len(item.neighbors),
                    neighbors_previews=neighbor_previews,
                )
            )

        filters = {"category": category, "source_url": source_url, "language": language}
        return PlaygroundSearchResult(
            query=cleaned_query,
            job_id=job_id,
            version_label=version_label,
            method=method,
            top_k=top_k,
            alpha=alpha,
            min_score=min_score,
            filters_applied={k: v for k, v in filters.items() if v is not None},
            latency_ms=latency_ms,
            total_candidates_considered=len(chunks),
            total_returned=len(traces),
            results=traces,
        )

    # -----------------------------------------------------------------------
    # Section B: Multi-Method Comparison
    # -----------------------------------------------------------------------

    async def compare_methods(
        self,
        job_id: str,
        query: str,
        top_k: int = 5,
        alpha: float = 0.7,
        version_label: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> MethodComparisonResult:
        """Run Dense, BM25, and Hybrid search side-by-side for factual evaluation."""
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("متن پرسش نمی‌تواند خالی باشد.")

        chunks = self.get_dataset_chunks(job_id, version_label, tenant_id=tenant_id)
        has_vectors = any(c.embedding is not None for c in chunks)
        settings = get_settings()
        api_key_set = bool(settings.openai_api_key.strip())

        dense_supported = has_vectors and api_key_set
        if not api_key_set:
            dense_status = "کلید OpenAI تنظیم نشده است؛ جست‌وجوی معنایی Dense غیرفعال است."
        elif not has_vectors:
            dense_status = "قطعات دارای بردار امبدینگ نیستند؛ ابتدا در بخش AI عملیات Embedding را اجرا کنید."
        else:
            dense_status = "جست‌وجوی معنایی Dense با مدل امبدینگ فعال است."

        # 1. BM25 Search (Always works offline)
        bm25_res = await self.search_playground(
            job_id=job_id,
            query=cleaned_query,
            method="bm25",
            top_k=top_k,
            version_label=version_label,
            tenant_id=tenant_id,
        )

        # 2. Dense Search (if supported)
        dense_results: list[RetrievalItemTrace] = []
        if dense_supported:
            dense_res = await self.search_playground(
                job_id=job_id,
                query=cleaned_query,
                method="dense",
                top_k=top_k,
                version_label=version_label,
                tenant_id=tenant_id,
            )
            dense_results = dense_res.results

        # 3. Hybrid Search
        hybrid_res = await self.search_playground(
            job_id=job_id,
            query=cleaned_query,
            method="hybrid",
            top_k=top_k,
            alpha=alpha,
            version_label=version_label,
            tenant_id=tenant_id,
        )

        return MethodComparisonResult(
            query=cleaned_query,
            job_id=job_id,
            version_label=version_label,
            top_k=top_k,
            alpha=alpha,
            dense_results=dense_results,
            bm25_results=bm25_res.results,
            hybrid_results=hybrid_res.results,
            dense_supported=dense_supported,
            dense_status_message=dense_status,
        )

    # -----------------------------------------------------------------------
    # Section C: Evaluation Datasets & QA Samples
    # -----------------------------------------------------------------------

    def create_dataset(
        self,
        name: str,
        description: Optional[str] = None,
        job_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> EvalDataset:
        """Create a new evaluation dataset container."""
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("نام مجموعه ارزیابی الزامی است.")

        if tenant_id and job_id:
            job = self.manager.get_job(job_id, tenant_id=tenant_id)
            if not job:
                raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")

        dataset_id = f"eval_{uuid.uuid4().hex[:8]}"
        dataset = EvalDataset(
            dataset_id=dataset_id,
            name=cleaned_name,
            description=description,
            job_id=job_id,
            tenant_id=tenant_id,
            samples=[],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._eval_datasets[dataset_id] = dataset
        self._save_state()
        return dataset

    def list_datasets(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        """List all evaluation datasets with summary statistics."""
        summaries = []
        if tenant_id:
            ds_list = [d for d in self._eval_datasets.values() if getattr(d, "tenant_id", None) == tenant_id]
        else:
            ds_list = list(self._eval_datasets.values())
        for d in ds_list:
            gt_count = sum(
                1 for s in d.samples
                if s.expected_chunk_ids or s.expected_source_urls or s.relevance_labels
            )
            reviewed_count = sum(1 for s in d.samples if s.human_reviewed)
            summaries.append({
                "dataset_id": d.dataset_id,
                "name": d.name,
                "description": d.description,
                "job_id": d.job_id,
                "total_samples": len(d.samples),
                "samples_with_ground_truth": gt_count,
                "human_reviewed_samples": reviewed_count,
                "created_at": d.created_at,
            })
        return summaries

    def get_dataset(self, dataset_id: str, tenant_id: Optional[str] = None) -> EvalDataset:
        """Retrieve evaluation dataset by ID, verifying tenant ownership."""
        if dataset_id not in self._eval_datasets:
            raise ValueError(f"مجموعه ارزیابی با شناسه '{dataset_id}' یافت نشد.")
        ds = self._eval_datasets[dataset_id]
        if tenant_id and getattr(ds, "tenant_id", None) != tenant_id:
            raise ValueError(f"مجموعه ارزیابی با شناسه '{dataset_id}' یافت نشد.")
        return ds

    def delete_dataset(self, dataset_id: str, tenant_id: Optional[str] = None) -> bool:
        """Delete an evaluation dataset."""
        ds = self.get_dataset(dataset_id, tenant_id=tenant_id)
        if ds and ds.dataset_id in self._eval_datasets:
            del self._eval_datasets[ds.dataset_id]
            self._save_state()
            return True
        return False

    def add_sample(
        self,
        dataset_id: str,
        question: str,
        job_id: str,
        version_label: Optional[str] = None,
        expected_chunk_ids: Optional[list[str]] = None,
        expected_source_urls: Optional[list[str]] = None,
        relevance_labels: Optional[dict[str, int]] = None,
        notes: Optional[str] = None,
        origin: Literal["manual", "real", "llm_generated"] = "manual",
        human_reviewed: bool = False,
        tenant_id: Optional[str] = None,
    ) -> EvalSample:
        """Add an evaluation query sample to a dataset."""
        dataset = self.get_dataset(dataset_id, tenant_id=tenant_id)
        cleaned_q = question.strip()
        if not cleaned_q:
            raise ValueError("متن پرسش نمی‌تواند خالی باشد.")

        sample_id = f"s_{uuid.uuid4().hex[:8]}"
        sample = EvalSample(
            sample_id=sample_id,
            question=cleaned_q,
            job_id=job_id,
            version_label=version_label,
            expected_chunk_ids=expected_chunk_ids or [],
            expected_source_urls=expected_source_urls or [],
            relevance_labels=relevance_labels or {},
            notes=notes,
            origin=origin,
            human_reviewed=human_reviewed,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        dataset.samples.append(sample)
        self._save_state()
        return sample

    def update_sample(
        self,
        dataset_id: str,
        sample_id: str,
        expected_chunk_ids: Optional[list[str]] = None,
        expected_source_urls: Optional[list[str]] = None,
        relevance_labels: Optional[dict[str, int]] = None,
        notes: Optional[str] = None,
        human_reviewed: Optional[bool] = None,
        tenant_id: Optional[str] = None,
    ) -> EvalSample:
        """Update ground truth labels or review status of a sample."""
        dataset = self.get_dataset(dataset_id, tenant_id=tenant_id)
        sample = next((s for s in dataset.samples if s.sample_id == sample_id), None)
        if not sample:
            raise ValueError(f"نمونه با شناسه '{sample_id}' یافت نشد.")

        if expected_chunk_ids is not None:
            sample.expected_chunk_ids = expected_chunk_ids
        if expected_source_urls is not None:
            sample.expected_source_urls = expected_source_urls
        if relevance_labels is not None:
            sample.relevance_labels = relevance_labels
        if notes is not None:
            sample.notes = notes
        if human_reviewed is not None:
            sample.human_reviewed = human_reviewed

        self._save_state()
        return sample

    def delete_sample(self, dataset_id: str, sample_id: str, tenant_id: Optional[str] = None) -> bool:
        """Remove a sample from an evaluation dataset."""
        dataset = self.get_dataset(dataset_id, tenant_id=tenant_id)
        orig_len = len(dataset.samples)
        dataset.samples = [s for s in dataset.samples if s.sample_id != sample_id]
        if len(dataset.samples) < orig_len:
            self._save_state()
            return True
        return False

    def import_synthetic_qa(
        self,
        dataset_id: str,
        job_id: str,
        max_samples: int = 10,
        tenant_id: Optional[str] = None,
    ) -> list[EvalSample]:
        """Import synthetic QA pairs from RAGEnhancer job metadata.

        RULE: Questions are marked as `origin='llm_generated'` and `human_reviewed=False`.
        They are NEVER auto-labeled as verified Ground Truth until human review.
        """
        dataset = self.get_dataset(dataset_id, tenant_id=tenant_id)
        rag_meta = self.manager.get_rag_metadata(job_id, tenant_id=tenant_id)

        qa_pairs = []
        if isinstance(rag_meta, dict):
            qa_pairs = rag_meta.get("qa_pairs", [])
        elif isinstance(rag_meta, list):
            for item in rag_meta:
                if isinstance(item, dict):
                    if "qa_pairs" in item and isinstance(item["qa_pairs"], list):
                        qa_pairs.extend(item["qa_pairs"])
                    elif "question" in item:
                        qa_pairs.append(item)
                elif isinstance(item, str):
                    qa_pairs.append(item)

        # If not in rag_metadata, check documents
        if not qa_pairs:
            docs = self.manager.get_documents(job_id, tenant_id=tenant_id)
            for d in docs:
                if getattr(d, "qa_pairs", None):
                    qa_pairs.extend(d.qa_pairs)

        if not qa_pairs:
            raise ValueError(
                "هیچ پرسش و پاسخ مصنوعی (Synthetic QA) در این کار یافت نشد. "
                "ابتدا در تب AI و RAG عملیات RAG Enhancement را با فعال‌سازی ساخت پرسش اجرا کنید.",
            )

        imported: list[EvalSample] = []
        for pair in qa_pairs[:max_samples]:
            question = ""
            if isinstance(pair, dict):
                question = pair.get("question", "")
            elif isinstance(pair, str):
                question = pair

            if not question:
                continue

            sample = self.add_sample(
                dataset_id=dataset_id,
                question=question,
                job_id=job_id,
                version_label=None,
                expected_chunk_ids=[],
                expected_source_urls=[],
                relevance_labels={},
                notes="تولیدشده توسط مدل زبانی (RAG Enhancer). نیازمند بازبینی انسانی.",
                origin="llm_generated",
                human_reviewed=False,
            )
            imported.append(sample)

        return imported

    # -----------------------------------------------------------------------
    # Section D: Retrieval Metrics (Recall@K, Precision@K, MRR, nDCG@K, Hit Rate)
    # -----------------------------------------------------------------------

    def _compute_sample_metrics(
        self,
        sample: EvalSample,
        retrieved_chunks: list[DocumentChunk],
        k: int,
    ) -> SampleMetrics:
        """Compute strict IR metrics for a single sample.

        RULE: If ground truth labels are missing, DO NOT fake or estimate them.
        Mark `has_ground_truth=False` and report metrics as None.
        """
        # Determine known relevant chunk IDs or URLs
        expected_ids = set(sample.expected_chunk_ids)
        expected_urls = set(sample.expected_source_urls)
        graded_labels = sample.relevance_labels  # chunk_id -> grade (int)

        # Include any chunk with positive relevance in expected_ids
        for cid, grade in graded_labels.items():
            if grade > 0:
                expected_ids.add(cid)

        has_gt = bool(expected_ids or expected_urls)

        if not has_gt:
            return SampleMetrics(
                sample_id=sample.sample_id,
                question=sample.question,
                has_ground_truth=False,
                recall_at_k=None,
                precision_at_k=None,
                mrr=None,
                ndcg_at_k=None,
                hit_rate=None,
                first_relevant_rank=None,
                relevant_retrieved_count=0,
                total_relevant_expected=0,
                warning="برچسب حقیقت مرجع (Ground Truth) برای این نمونه ثبت نشده است. معیارها قابل محاسبه نیستند.",
            )

        top_k_chunks = retrieved_chunks[:k]
        relevant_retrieved = 0
        first_rel_rank: Optional[int] = None

        for rank, c in enumerate(top_k_chunks, 1):
            is_rel = (
                c.chunk_id in expected_ids
                or c.source_url in expected_urls
                or (graded_labels.get(c.chunk_id, 0) > 0)
            )
            if is_rel:
                relevant_retrieved += 1
                if first_rel_rank is None:
                    first_rel_rank = rank

        # 1. Recall@K
        total_rel = len(expected_ids) if expected_ids else len(expected_urls)
        recall = (relevant_retrieved / max(1, total_rel)) if total_rel > 0 else 0.0
        recall = min(1.0, round(recall, 4))

        # 2. Precision@K
        precision = round(relevant_retrieved / max(1, k), 4)

        # 3. MRR (Reciprocal Rank)
        mrr = round(1.0 / first_rel_rank, 4) if first_rel_rank is not None else 0.0

        # 4. Hit Rate (Binary)
        hit_rate = 1.0 if relevant_retrieved > 0 else 0.0

        # 5. nDCG@K (Only computed if graded relevance labels exist)
        ndcg: Optional[float] = None
        if graded_labels:
            dcg = 0.0
            for rank, c in enumerate(top_k_chunks, 1):
                rel = graded_labels.get(c.chunk_id, 0)
                if rel > 0:
                    dcg += (math.pow(2, rel) - 1.0) / math.log2(rank + 1)

            # Ideal DCG
            sorted_grades = sorted(graded_labels.values(), reverse=True)[:k]
            idcg = sum(
                (math.pow(2, g) - 1.0) / math.log2(r + 1)
                for r, g in enumerate(sorted_grades, 1)
                if g > 0
            )
            if idcg > 0:
                ndcg = min(1.0, round(dcg / idcg, 4))
            else:
                ndcg = 0.0

        return SampleMetrics(
            sample_id=sample.sample_id,
            question=sample.question,
            has_ground_truth=True,
            recall_at_k=recall,
            precision_at_k=precision,
            mrr=mrr,
            ndcg_at_k=ndcg,
            hit_rate=hit_rate,
            first_relevant_rank=first_rel_rank,
            relevant_retrieved_count=relevant_retrieved,
            total_relevant_expected=total_rel,
        )

    # -----------------------------------------------------------------------
    # Section E: Evaluation Runs & Pipeline Comparison
    # -----------------------------------------------------------------------

    async def execute_run(
        self,
        dataset_id: str,
        job_id: str,
        version_label: Optional[str] = None,
        method: Literal["dense", "bm25", "hybrid"] = "hybrid",
        top_k: int = 5,
        alpha: float = 0.7,
        min_score: float = 0.0,
        category_filter: Optional[str] = None,
        source_url_filter: Optional[str] = None,
        language_filter: Optional[str] = None,
        expand_neighbors: bool = False,
        tenant_id: Optional[str] = None,
    ) -> EvalRunResult:
        """Execute a formal evaluation run for an entire evaluation dataset."""
        dataset = self.get_dataset(dataset_id, tenant_id=tenant_id)
        if not dataset.samples:
            raise ValueError(f"مجموعه ارزیابی '{dataset.name}' فاقد نمونه پرسش است.")

        chunks = self.get_dataset_chunks(job_id, version_label, tenant_id=tenant_id)
        if not chunks:
            raise ValueError(f"هیچ قطعه‌ای برای کار '{job_id}' (نسخه: {version_label or 'current'}) یافت نشد.")

        run_id = f"run_{uuid.uuid4().hex[:8]}"
        config = EvalRunConfig(
            run_id=run_id,
            dataset_id=dataset_id,
            job_id=job_id,
            tenant_id=tenant_id,
            version_label=version_label,
            method=method,
            top_k=top_k,
            alpha=alpha,
            min_score=min_score,
            category_filter=category_filter,
            source_url_filter=source_url_filter,
            language_filter=language_filter,
            expand_neighbors=expand_neighbors,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        sample_results: list[SampleMetrics] = []
        samples_with_gt = 0

        for sample in dataset.samples:
            # Execute retrieval query for each sample
            search_res = await self.search_playground(
                job_id=job_id,
                query=sample.question,
                method=method,
                top_k=top_k,
                alpha=alpha,
                min_score=min_score,
                category=category_filter,
                source_url=source_url_filter,
                language=language_filter,
                expand_neighbors=expand_neighbors,
                version_label=version_label,
            )

            # Map results to DocumentChunk instances
            retrieved_chunks = [
                DocumentChunk(
                    chunk_id=r.chunk_id,
                    source_url=r.source_url,
                    chunk_index=0,
                    total_chunks=1,
                    text=r.text_preview,
                    char_count=r.char_count,
                    word_count=len(r.text_preview.split()),
                    heading_context=r.heading_context,
                    title=r.title,
                    category=r.category,
                    language=r.language,
                )
                for r in search_res.results
            ]

            metrics = self._compute_sample_metrics(sample, retrieved_chunks, top_k)
            if metrics.has_ground_truth:
                samples_with_gt += 1
            sample_results.append(metrics)

        # Compute aggregate metrics only over samples with ground truth
        aggregate: dict[str, Optional[float]] = {}
        insufficient_gt = (samples_with_gt == 0)
        gt_warning: Optional[str] = None

        if insufficient_gt:
            gt_warning = (
                "هیچ‌کدام از پرسش‌های ارزیابی دارای برچسب مرجع (Ground Truth) انسانی یا معتبر نیستند. "
                "معیارهای تجمیعی برای جلوگیری از نتیجه گمراه‌کننده محاسبه نشدند."
            )
        else:
            valid_samples = [s for s in sample_results if s.has_ground_truth]
            count = len(valid_samples)
            avg_recall = sum(s.recall_at_k or 0.0 for s in valid_samples) / count
            avg_precision = sum(s.precision_at_k or 0.0 for s in valid_samples) / count
            avg_mrr = sum(s.mrr or 0.0 for s in valid_samples) / count
            avg_hit_rate = sum(s.hit_rate or 0.0 for s in valid_samples) / count

            ndcg_samples = [s for s in valid_samples if s.ndcg_at_k is not None]
            avg_ndcg = (
                sum(s.ndcg_at_k for s in ndcg_samples) / len(ndcg_samples)
                if ndcg_samples
                else None
            )

            aggregate = {
                f"recall_at_{top_k}": round(avg_recall, 4),
                f"precision_at_{top_k}": round(avg_precision, 4),
                "mrr": round(avg_mrr, 4),
                "hit_rate": round(avg_hit_rate, 4),
                f"ndcg_at_{top_k}": round(avg_ndcg, 4) if avg_ndcg is not None else None,
            }

            if samples_with_gt < len(dataset.samples):
                gt_warning = (
                    f"توجه: فقط {samples_with_gt} از {len(dataset.samples)} نمونه دارای برچسب مرجع هستند. "
                    "معیارها صرفاً بر مبنای نمونه‌های برچسب‌دار محاسبه شده‌اند."
                )

        run_result = EvalRunResult(
            run_id=run_id,
            dataset_id=dataset_id,
            dataset_name=dataset.name,
            tenant_id=tenant_id,
            config=config,
            total_samples=len(dataset.samples),
            samples_with_ground_truth=samples_with_gt,
            insufficient_ground_truth=insufficient_gt,
            ground_truth_warning=gt_warning,
            aggregate_metrics=aggregate,
            sample_results=sample_results,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        self._eval_runs[run_id] = run_result
        self._save_state()
        return run_result

    def list_runs(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        """List summary of all executed evaluation runs."""
        summaries = []
        if tenant_id:
            runs_list = [r for r in self._eval_runs.values() if getattr(r, "tenant_id", None) == tenant_id or getattr(r.config, "tenant_id", None) == tenant_id]
        else:
            runs_list = list(self._eval_runs.values())
        for r in runs_list:
            summaries.append({
                "run_id": r.run_id,
                "dataset_id": r.dataset_id,
                "dataset_name": r.dataset_name,
                "job_id": r.config.job_id,
                "version_label": r.config.version_label or "current",
                "method": r.config.method,
                "top_k": r.config.top_k,
                "total_samples": r.total_samples,
                "samples_with_ground_truth": r.samples_with_ground_truth,
                "insufficient_ground_truth": r.insufficient_ground_truth,
                "aggregate_metrics": r.aggregate_metrics,
                "created_at": r.created_at,
            })
        return summaries

    def get_run(self, run_id: str, tenant_id: Optional[str] = None) -> EvalRunResult:
        """Retrieve evaluation run result by ID."""
        if run_id not in self._eval_runs:
            raise ValueError(f"اجرای ارزیابی با شناسه '{run_id}' یافت نشد.")
        run = self._eval_runs[run_id]
        if tenant_id and (getattr(run, "tenant_id", None) != tenant_id and getattr(run.config, "tenant_id", None) != tenant_id):
            raise ValueError(f"اجرای ارزیابی با شناسه '{run_id}' یافت نشد.")
        return run

    def compare_runs(self, run_id_a: str, run_id_b: str, tenant_id: Optional[str] = None) -> RunComparisonResult:
        """Compare two evaluation runs to detect metric deltas and query regressions/improvements."""
        run_a = self.get_run(run_id_a, tenant_id=tenant_id)
        run_b = self.get_run(run_id_b, tenant_id=tenant_id)

        # 1. Compute Metric Deltas (Run B minus Run A)
        metric_deltas: dict[str, Optional[float]] = {}
        all_metric_keys = set(run_a.aggregate_metrics.keys()).union(run_b.aggregate_metrics.keys())
        for k in all_metric_keys:
            val_a = run_a.aggregate_metrics.get(k)
            val_b = run_b.aggregate_metrics.get(k)
            if val_a is not None and val_b is not None:
                metric_deltas[k] = round(val_b - val_a, 4)
            else:
                metric_deltas[k] = None

        # 2. Per-query transitions
        a_map = {s.sample_id: s for s in run_a.sample_results}
        b_map = {s.sample_id: s for s in run_b.sample_results}

        improved: list[dict[str, Any]] = []
        regressed: list[dict[str, Any]] = []
        unchanged: list[dict[str, Any]] = []

        common_ids = set(a_map.keys()).intersection(b_map.keys())
        for sid in common_ids:
            sa = a_map[sid]
            sb = b_map[sid]

            if not sa.has_ground_truth or not sb.has_ground_truth:
                continue

            recall_a = sa.recall_at_k or 0.0
            recall_b = sb.recall_at_k or 0.0
            rank_a = sa.first_relevant_rank or 999
            rank_b = sb.first_relevant_rank or 999

            diff_entry = {
                "sample_id": sid,
                "question": sa.question,
                "run_a_first_rank": sa.first_relevant_rank,
                "run_b_first_rank": sb.first_relevant_rank,
                "run_a_recall": recall_a,
                "run_b_recall": recall_b,
                "recall_delta": round(recall_b - recall_a, 4),
            }

            if recall_b > recall_a or rank_b < rank_a:
                improved.append(diff_entry)
            elif recall_b < recall_a or rank_b > rank_a:
                regressed.append(diff_entry)
            else:
                unchanged.append(diff_entry)

        summary = (
            f"مقایسه اجرای {run_id_b} نسبت به {run_id_a}: "
            f"{len(improved)} پرسش بهبودیافته، {len(regressed)} پرسش افت‌کرده، و {len(unchanged)} پرسش بدون تغییر."
        )

        return RunComparisonResult(
            run_id_a=run_id_a,
            run_id_b=run_id_b,
            run_a_config=run_a.config,
            run_b_config=run_b.config,
            metric_deltas=metric_deltas,
            improved_queries=improved,
            regressed_queries=regressed,
            unchanged_queries=unchanged,
            summary_message=summary,
        )

    # -----------------------------------------------------------------------
    # Section F: Retrieval Debugging Trace
    # -----------------------------------------------------------------------

    async def debug_retrieval(
        self,
        job_id: str,
        query: str,
        method: Literal["dense", "bm25", "hybrid"] = "hybrid",
        top_k: int = 5,
        alpha: float = 0.7,
        min_score: float = 0.0,
        category: Optional[str] = None,
        source_url: Optional[str] = None,
        language: Optional[str] = None,
        expand_neighbors: bool = False,
        version_label: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> RetrievalDebugTrace:
        """Trace candidate filtering and scoring step-by-step with exclusion reasons."""
        cleaned_query = query.strip()
        tokens = tokenize_for_search(cleaned_query)
        is_persian = bool(_PERSIAN_CHAR_RE.search(cleaned_query))
        lang_detected = "Persian (fa)" if is_persian else "English/Multilingual"

        chunks = self.get_dataset_chunks(job_id, version_label, tenant_id=tenant_id)
        total_chunks = len(chunks)

        warnings: list[str] = []
        if total_chunks < 5:
            warnings.append(f"مجموعه داده بسیار کوچک است (تعداد قطعات: {total_chunks}). تنوع بازیابی ممکن است محدود باشد.")

        if not tokens:
            warnings.append("پرسش واردشده فاقد توکن‌های معنادار است.")

        # Check metadata filtering
        candidates_after_meta: list[DocumentChunk] = []
        meta_excluded: list[dict[str, Any]] = []

        for c in chunks:
            reasons = []
            if category and (c.category or "").lower() != category.lower():
                reasons.append(f"دسته‌بندی '{c.category or 'نامشخص'}' با فیلتر '{category}' همخوانی ندارد.")
            if source_url and c.source_url != source_url:
                reasons.append(f"آدرس منبع '{c.source_url}' با فیلتر '{source_url}' یکسان نیست.")
            if language and (c.language or "").lower() != language.lower():
                reasons.append(f"زبان '{c.language or 'نامشخص'}' با فیلتر '{language}' مطابقت ندارد.")

            if reasons:
                if len(meta_excluded) < 5:
                    meta_excluded.append({
                        "chunk_id": c.chunk_id,
                        "source_url": c.source_url,
                        "reasons": reasons,
                    })
            else:
                candidates_after_meta.append(c)

        excluded_by_meta_count = total_chunks - len(candidates_after_meta)
        if total_chunks > 0 and len(candidates_after_meta) == 0:
            warnings.append("فیلترهای متادیتا (دسته‌بندی/آدرس/زبان) بسیار سخت‌گیرانه هستند و تمام قطعات را حذف کردند.")

        # Compute scores via isolated store
        store = self.get_isolated_store(job_id, version_label, chunks, tenant_id=tenant_id)
        query_vector = None
        has_vectors = store.total_vectors > 0

        if method in ("dense", "hybrid"):
            if not has_vectors:
                warnings.append("هیچ‌کدام از قطعات این مجموعه دارای بردار امبدینگ نیستند؛ جست‌وجوی معنایی Dense خروجی نخواهد داشت.")
            query_vector = await self._compute_query_vector(cleaned_query)

        # Run search with min_score=0.0 first to see raw scores
        raw_items = store.search(
            query=cleaned_query,
            query_vector=query_vector,
            top_k=max(top_k, 50),
            category=category,
            source_url=source_url,
            min_score=0.0,
            hybrid=(method == "hybrid"),
            alpha=alpha if method == "hybrid" else (1.0 if method == "dense" else 0.0),
            expand_neighbors=expand_neighbors,
        )

        # Check min_score exclusions
        final_items = []
        min_score_excluded_sample: list[dict[str, Any]] = []
        excluded_by_score_count = 0

        for it in raw_items:
            if it.score < min_score:
                excluded_by_score_count += 1
                if len(min_score_excluded_sample) < 5:
                    min_score_excluded_sample.append({
                        "chunk_id": it.chunk.chunk_id,
                        "score": round(it.score, 4),
                        "min_score_threshold": min_score,
                        "reason": f"امتیاز ({it.score:.4f}) کمتر از حداقل آستانه مجاز ({min_score}) بود.",
                    })
            else:
                final_items.append(it)

        if min_score > 0.0 and len(raw_items) > 0:
            if len(final_items) == 0:
                warnings.append(
                    f"حد آستانه min_score={min_score} بیش از حد سخت‌گیرانه است؛ تمام {len(raw_items)} قطعه نامزد حذف شدند."
                )
            elif excluded_by_score_count >= max(1, int(len(raw_items) * 0.5)):
                warnings.append(
                    f"حد آستانه min_score={min_score} بیش از حد سخت‌گیرانه است؛ {excluded_by_score_count} از {len(raw_items)} قطعه به دلیل نمره کمتر حذف شدند."
                )

        # Format final traces
        traces: list[RetrievalItemTrace] = []
        neighbors_attached_count = 0

        for rank, it in enumerate(final_items[:top_k], 1):
            if it.neighbors:
                neighbors_attached_count += len(it.neighbors)

            score_type = (
                f"Hybrid [α={alpha:.2f}]"
                if method == "hybrid"
                else ("Cosine Similarity" if method == "dense" else "BM25 Normalized")
            )

            traces.append(
                RetrievalItemTrace(
                    chunk_id=it.chunk.chunk_id,
                    source_url=it.chunk.source_url,
                    heading_context=it.chunk.heading_context,
                    title=it.chunk.title,
                    category=it.chunk.category,
                    language=it.chunk.language,
                    rank=rank,
                    score=round(it.score, 4),
                    raw_dense_score=it.dense_score,
                    raw_sparse_score=it.sparse_score,
                    score_type=score_type,
                    search_method=method,
                    text_preview=it.chunk.text,
                    char_count=it.chunk.char_count,
                    neighbors_count=len(it.neighbors),
                    neighbors_previews=[f"[قطعه {n.chunk_index + 1}]: {n.text[:100]}..." for n in it.neighbors],
                )
            )

        return RetrievalDebugTrace(
            query=cleaned_query,
            tokens=tokens,
            detected_language=lang_detected,
            method=method,
            parameters={
                "top_k": top_k,
                "alpha": alpha,
                "min_score": min_score,
                "category": category,
                "source_url": source_url,
                "language": language,
                "expand_neighbors": expand_neighbors,
            },
            total_chunks_in_dataset=total_chunks,
            candidates_after_metadata_filter=len(candidates_after_meta),
            excluded_by_metadata=excluded_by_meta_count,
            metadata_exclusion_sample=meta_excluded,
            candidates_after_min_score=len(final_items),
            excluded_by_min_score=excluded_by_score_count,
            min_score_exclusion_sample=min_score_excluded_sample,
            final_results_count=len(traces),
            results=traces,
            context_expansion_status={
                "enabled": expand_neighbors,
                "total_neighbor_chunks_attached": neighbors_attached_count,
            },
            actionable_warnings=warnings,
        )


# Global singleton instance
rag_evaluator = RAGEvaluatorService()
