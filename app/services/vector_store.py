"""Vector Store and Hybrid Retrieval Service for Crawlbot RAG.

Provides deterministic in-memory / persistent vector search with:
1. Dense Vector Search (Cosine Similarity).
2. Sparse Lexical Search (BM25 for Persian & English).
3. Hybrid Search combining dense semantic embeddings and sparse keyword precision.
4. Multi-criteria Metadata Filtering (category, source_url, language, min_score).
5. Context Expansion (retrieving adjacent preceding/succeeding chunks).
6. Safe Document Updates and Deletions (prevents zombie chunks or index corruption).
7. Zero mandatory external database dependencies with 100% offline capability.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from typing import Any, Optional

from app.schemas.chunks import (
    DocumentChunk,
    VectorSearchRequest,
    VectorSearchResponse,
    VectorSearchResultItem,
)

logger = logging.getLogger(__name__)

# Check for numpy for vectorized math acceleration
try:
    import numpy as np  # type: ignore
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# Lexical Tokenizer & BM25 Helper
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[\w\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]+(?:[.\-][\w\u0600-\u06FF]+)*", re.UNICODE)


def tokenize_for_search(text: str) -> list[str]:
    """Tokenize text into lowercase words/terms supporting Persian & English, preserving digits and abbreviations."""
    if not text:
        return []
    # Replace zero-width non-joiner with standard space for tokenization
    clean = text.replace("\u200c", " ").lower()
    return _TOKEN_RE.findall(clean)


class BM25Index:
    """Lightweight in-memory BM25 index supporting Persian and multilingual text."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_len: dict[str, int] = {}  # chunk_id -> length
        self.avg_doc_len: float = 0.0
        self.doc_count: int = 0
        self.term_doc_freq: dict[str, int] = {}  # term -> count of docs containing term
        self.term_freqs: dict[str, dict[str, int]] = {}  # chunk_id -> {term: count}

    def add_document(self, chunk_id: str, tokens: list[str]) -> None:
        """Add a tokenized document to the BM25 index."""
        if not tokens:
            return

        # If already exists, remove first
        if chunk_id in self.doc_len:
            self.remove_document(chunk_id)

        length = len(tokens)
        self.doc_len[chunk_id] = length

        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1

        self.term_freqs[chunk_id] = tf

        for t in tf.keys():
            self.term_doc_freq[t] = self.term_doc_freq.get(t, 0) + 1

        self.doc_count = len(self.doc_len)
        self.avg_doc_len = sum(self.doc_len.values()) / max(1, self.doc_count)

    def remove_document(self, chunk_id: str) -> None:
        """Remove a document from the BM25 index."""
        if chunk_id not in self.doc_len:
            return

        del self.doc_len[chunk_id]
        tf = self.term_freqs.pop(chunk_id, {})

        for t in tf.keys():
            if t in self.term_doc_freq:
                self.term_doc_freq[t] -= 1
                if self.term_doc_freq[t] <= 0:
                    del self.term_doc_freq[t]

        self.doc_count = len(self.doc_len)
        self.avg_doc_len = sum(self.doc_len.values()) / max(1, self.doc_count) if self.doc_count > 0 else 0.0

    def score(self, query_tokens: list[str], chunk_id: str) -> float:
        """Compute BM25 score for query tokens against a specific document."""
        if chunk_id not in self.term_freqs or self.doc_count == 0:
            return 0.0

        score = 0.0
        doc_len = self.doc_len.get(chunk_id, 0)
        tf_dict = self.term_freqs.get(chunk_id, {})

        for token in query_tokens:
            if token not in tf_dict:
                continue

            tf = tf_dict[token]
            df = self.term_doc_freq.get(token, 0)

            # Robertson-Spärck Jones IDF
            idf = math.log((self.doc_count - df + 0.5) / (df + 0.5) + 1.0)
            idf = max(0.1, idf)

            denom = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / max(1.0, self.avg_doc_len)))
            term_score = idf * ((tf * (self.k1 + 1.0)) / max(1e-6, denom))
            score += term_score

        return score


# ---------------------------------------------------------------------------
# Vector Math Utilities
# ---------------------------------------------------------------------------

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0

    if _HAS_NUMPY:
        a = np.array(v1, dtype=np.float32)
        b = np.array(v2, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    dot = sum(x * y for x, y in zip(v1, v2))
    norm_v1 = math.sqrt(sum(x * x for x in v1))
    norm_v2 = math.sqrt(sum(x * x for x in v2))
    if norm_v1 == 0.0 or norm_v2 == 0.0:
        return 0.0
    return dot / (norm_v1 * norm_v2)


# ---------------------------------------------------------------------------
# Core Vector Store
# ---------------------------------------------------------------------------

class VectorStore:
    """In-memory and disk-serializable Vector Database with Hybrid Search."""

    def __init__(
        self,
        expected_dim: Optional[int] = 1536,
        storage_path: Optional[str] = None,
    ) -> None:
        self.expected_dim: Optional[int] = expected_dim
        self.storage_path: Optional[str] = storage_path
        self._chunks: dict[str, DocumentChunk] = {}  # chunk_id -> DocumentChunk
        self._vectors: dict[str, list[float]] = {}  # chunk_id -> vector
        self._doc_to_chunks: dict[str, list[str]] = {}  # source_doc_id -> [chunk_ids]
        self._url_to_chunks: dict[str, list[str]] = {}  # source_url -> [chunk_ids]
        self._tenant_to_chunks: dict[str, list[str]] = {}  # tenant_id -> [chunk_ids]
        self._bm25: BM25Index = BM25Index()

        if self.storage_path and os.path.exists(self.storage_path):
            try:
                self.load_from_file(self.storage_path)
            except Exception as load_err:
                logger.warning("Could not auto-load vector store from %s: %s", self.storage_path, load_err)

    @property
    def total_chunks(self) -> int:
        return len(self._chunks)

    @property
    def total_vectors(self) -> int:
        return len(self._vectors)

    def upsert_chunks(self, chunks: list[DocumentChunk], tenant_id: Optional[str] = None) -> int:
        """Add or update chunks in the vector store with optional tenant isolation.

        Validates vector dimensions if embeddings are present.
        Re-indexes BM25 tokens for hybrid lexical retrieval.

        Returns:
            Number of successfully upserted chunks.
        """
        upserted = 0
        for chunk in chunks:
            chunk_id = chunk.chunk_id
            if not chunk_id:
                continue

            # Multi-tenant assignment
            if tenant_id and not getattr(chunk, "tenant_id", None):
                chunk.tenant_id = tenant_id

            # Validate vector dimension if embedding is provided
            if chunk.embedding is not None:
                dim = len(chunk.embedding)
                if self.expected_dim and dim != self.expected_dim:
                    logger.warning(
                        "Chunk %s vector dimension %d does not match expected dimension %d; skipping vector",
                        chunk_id, dim, self.expected_dim,
                    )
                else:
                    self._vectors[chunk_id] = list(chunk.embedding)

            self._chunks[chunk_id] = chunk

            # Track doc mapping
            if chunk.source_doc_id:
                if chunk.source_doc_id not in self._doc_to_chunks:
                    self._doc_to_chunks[chunk.source_doc_id] = []
                if chunk_id not in self._doc_to_chunks[chunk.source_doc_id]:
                    self._doc_to_chunks[chunk.source_doc_id].append(chunk_id)

            # Track URL mapping
            if chunk.source_url:
                if chunk.source_url not in self._url_to_chunks:
                    self._url_to_chunks[chunk.source_url] = []
                if chunk_id not in self._url_to_chunks[chunk.source_url]:
                    self._url_to_chunks[chunk.source_url].append(chunk_id)

            # Track Tenant mapping
            c_tenant = getattr(chunk, "tenant_id", None)
            if c_tenant:
                if c_tenant not in self._tenant_to_chunks:
                    self._tenant_to_chunks[c_tenant] = []
                if chunk_id not in self._tenant_to_chunks[c_tenant]:
                    self._tenant_to_chunks[c_tenant].append(chunk_id)

            # Update BM25 index with heading context and chunk text
            tokens = tokenize_for_search(f"{chunk.heading_context or ''} {chunk.title or ''} {chunk.text}")
            self._bm25.add_document(chunk_id, tokens)
            upserted += 1

        if self.storage_path and upserted > 0:
            try:
                self.save_to_file(self.storage_path)
            except Exception as save_err:
                logger.warning("Could not auto-save vector store to %s: %s", self.storage_path, save_err)

        logger.info("Upserted %d chunks into VectorStore (total: %d, vectors: %d)", upserted, self.total_chunks, self.total_vectors)
        return upserted

    def delete_by_url(self, source_url: str, tenant_id: Optional[str] = None) -> int:
        """Delete chunks originating from a specific source URL, scoped to tenant if provided."""
        all_cids = list(self._url_to_chunks.get(source_url, []))
        if tenant_id:
            chunk_ids = [cid for cid in all_cids if getattr(self._chunks.get(cid), "tenant_id", None) == tenant_id]
            self._url_to_chunks[source_url] = [cid for cid in all_cids if cid not in chunk_ids]
            if not self._url_to_chunks[source_url]:
                self._url_to_chunks.pop(source_url, None)
        else:
            chunk_ids = list(self._url_to_chunks.pop(source_url, []))

        for cid in chunk_ids:
            chunk = self._chunks.pop(cid, None)
            self._vectors.pop(cid, None)
            self._bm25.remove_document(cid)
            if chunk and getattr(chunk, "tenant_id", None) in self._tenant_to_chunks:
                self._tenant_to_chunks[chunk.tenant_id] = [c for c in self._tenant_to_chunks[chunk.tenant_id] if c != cid]

        # Clean doc mappings
        for doc_id, cids in list(self._doc_to_chunks.items()):
            self._doc_to_chunks[doc_id] = [c for c in cids if c not in chunk_ids]
            if not self._doc_to_chunks[doc_id]:
                del self._doc_to_chunks[doc_id]

        if self.storage_path and chunk_ids:
            try:
                self.save_to_file(self.storage_path)
            except Exception as save_err:
                logger.warning("Could not auto-save vector store to %s: %s", self.storage_path, save_err)

        logger.info("Deleted %d chunks for URL %s (tenant=%s)", len(chunk_ids), source_url, tenant_id)
        return len(chunk_ids)

    def delete_by_document_id(self, source_doc_id: str, tenant_id: Optional[str] = None) -> int:
        """Delete chunks originating from a specific source document ID, scoped to tenant if provided."""
        all_cids = list(self._doc_to_chunks.get(source_doc_id, []))
        if tenant_id:
            chunk_ids = [cid for cid in all_cids if getattr(self._chunks.get(cid), "tenant_id", None) == tenant_id]
            self._doc_to_chunks[source_doc_id] = [cid for cid in all_cids if cid not in chunk_ids]
            if not self._doc_to_chunks[source_doc_id]:
                self._doc_to_chunks.pop(source_doc_id, None)
        else:
            chunk_ids = list(self._doc_to_chunks.pop(source_doc_id, []))

        for cid in chunk_ids:
            chunk = self._chunks.pop(cid, None)
            self._vectors.pop(cid, None)
            self._bm25.remove_document(cid)
            if chunk and getattr(chunk, "tenant_id", None) in self._tenant_to_chunks:
                self._tenant_to_chunks[chunk.tenant_id] = [c for c in self._tenant_to_chunks[chunk.tenant_id] if c != cid]

        # Clean URL mappings
        for url, cids in list(self._url_to_chunks.items()):
            self._url_to_chunks[url] = [c for c in cids if c not in chunk_ids]
            if not self._url_to_chunks[url]:
                del self._url_to_chunks[url]

        if self.storage_path and chunk_ids:
            try:
                self.save_to_file(self.storage_path)
            except Exception as save_err:
                logger.warning("Could not auto-save vector store to %s: %s", self.storage_path, save_err)

        return len(chunk_ids)

    def clear(self, tenant_id: Optional[str] = None) -> int:
        """Clear all or tenant-specific indexed data from the vector store."""
        if tenant_id:
            chunk_ids = list(self._tenant_to_chunks.pop(tenant_id, []))
            for cid, chunk in list(self._chunks.items()):
                if getattr(chunk, "tenant_id", None) == tenant_id and cid not in chunk_ids:
                    chunk_ids.append(cid)

            for cid in chunk_ids:
                self._chunks.pop(cid, None)
                self._vectors.pop(cid, None)
                self._bm25.remove_document(cid)

            # Clean URL and doc mappings
            for url, cids in list(self._url_to_chunks.items()):
                self._url_to_chunks[url] = [c for c in cids if c not in chunk_ids]
                if not self._url_to_chunks[url]:
                    del self._url_to_chunks[url]

            for doc_id, cids in list(self._doc_to_chunks.items()):
                self._doc_to_chunks[doc_id] = [c for c in cids if c not in chunk_ids]
                if not self._doc_to_chunks[doc_id]:
                    del self._doc_to_chunks[doc_id]

            if self.storage_path and chunk_ids:
                try:
                    self.save_to_file(self.storage_path)
                except Exception as save_err:
                    logger.warning("Could not auto-save vector store to %s: %s", self.storage_path, save_err)

            logger.info("Cleared %d chunks for tenant %s from VectorStore.", len(chunk_ids), tenant_id)
            return len(chunk_ids)

        # Clear all
        deleted = len(self._chunks)
        self._chunks.clear()
        self._vectors.clear()
        self._doc_to_chunks.clear()
        self._url_to_chunks.clear()
        self._tenant_to_chunks.clear()
        self._bm25 = BM25Index()

        if self.storage_path and os.path.exists(self.storage_path):
            try:
                self.save_to_file(self.storage_path)
            except Exception as save_err:
                logger.warning("Could not auto-save vector store to %s: %s", self.storage_path, save_err)

        logger.info("Cleared entire VectorStore (%d chunks).", deleted)
        return deleted

    def search(
        self,
        query: str,
        query_vector: Optional[list[float]] = None,
        top_k: int = 5,
        category: Optional[str] = None,
        source_url: Optional[str] = None,
        min_score: float = 0.0,
        hybrid: bool = True,
        alpha: float = 0.7,
        expand_neighbors: bool = False,
        tenant_id: Optional[str] = None,
    ) -> list[VectorSearchResultItem]:
        """Search chunks using dense vector similarity, BM25, or hybrid combination.

        Args:
            query: Query string.
            query_vector: Optional pre-computed query embedding vector.
            top_k: Number of results to return.
            category: Optional category filter.
            source_url: Optional source URL filter.
            min_score: Minimum combined score.
            hybrid: If True and query_vector is present, combines dense and sparse scores.
            alpha: Weight of dense vector search in hybrid score (0.0 to 1.0).
            expand_neighbors: If True, attaches preceding and succeeding chunks.
            tenant_id: Optional tenant identifier for multi-tenant isolation.

        Returns:
            Ranked list of VectorSearchResultItem objects.
        """
        if not self._chunks:
            return []

        query_tokens = tokenize_for_search(query)
        candidates: list[str] = []

        # 1. Apply Metadata Filters & Multi-Tenant Isolation
        for cid, chunk in self._chunks.items():
            if tenant_id:
                c_tenant = getattr(chunk, "tenant_id", None)
                if c_tenant != tenant_id:
                    continue
            if category and (chunk.category or "").lower() != category.lower():
                continue
            if source_url and chunk.source_url != source_url:
                continue
            candidates.append(cid)

        if not candidates:
            return []

        # 2. Compute Scores
        has_vectors = bool(query_vector and self._vectors)
        scores: list[tuple[str, float, Optional[float], Optional[float]]] = []

        # Calculate BM25 scores for all candidates
        raw_sparse_scores: dict[str, float] = {}
        for cid in candidates:
            raw_sparse_scores[cid] = self._bm25.score(query_tokens, cid)

        max_sparse = max(raw_sparse_scores.values()) if raw_sparse_scores else 0.0

        for cid in candidates:
            dense_score: Optional[float] = None
            sparse_score: Optional[float] = None

            # Normalized BM25 score in [0, 1]
            if max_sparse > 0:
                sparse_score = raw_sparse_scores[cid] / max_sparse
            else:
                sparse_score = 0.0

            if has_vectors and cid in self._vectors:
                dense_sim = cosine_similarity(query_vector, self._vectors[cid])
                # Shift cosine similarity from [-1, 1] to [0, 1]
                dense_score = max(0.0, min(1.0, (dense_sim + 1.0) / 2.0))

            # Combine scores
            if has_vectors and dense_score is not None:
                if hybrid:
                    final_score = (alpha * dense_score) + ((1.0 - alpha) * sparse_score)
                else:
                    final_score = dense_score
            else:
                # Sparse only fallback
                final_score = sparse_score

            if final_score >= min_score:
                scores.append((cid, final_score, dense_score, sparse_score))

        # Sort descending by score
        scores.sort(key=lambda x: x[1], reverse=True)
        top_results = scores[:top_k]

        # 3. Format Result Items and Optionally Expand Neighbors
        result_items: list[VectorSearchResultItem] = []
        for cid, score, d_score, s_score in top_results:
            target_chunk = self._chunks[cid]
            neighbors: list[DocumentChunk] = []

            if expand_neighbors and target_chunk.source_url in self._url_to_chunks:
                url_cids = self._url_to_chunks[target_chunk.source_url]
                # Sort URL chunks by index
                ordered_chunks = sorted(
                    [self._chunks[c] for c in url_cids if c in self._chunks and (not tenant_id or getattr(self._chunks[c], 'tenant_id', None) == tenant_id)],
                    key=lambda c: c.chunk_index,
                )
                curr_idx = target_chunk.chunk_index
                for oc in ordered_chunks:
                    if oc.chunk_index in (curr_idx - 1, curr_idx + 1):
                        neighbors.append(oc)

            result_items.append(
                VectorSearchResultItem(
                    chunk=target_chunk,
                    score=round(score, 4),
                    dense_score=round(d_score, 4) if d_score is not None else None,
                    sparse_score=round(s_score, 4) if s_score is not None else None,
                    neighbors=neighbors,
                )
            )

        return result_items

    def get_stats(self, tenant_id: Optional[str] = None) -> dict[str, Any]:
        """Return index statistics and distribution, optionally filtered by tenant."""
        if tenant_id:
            chunks = [c for c in self._chunks.values() if getattr(c, "tenant_id", None) == tenant_id]
            vectors_count = sum(1 for c in chunks if c.chunk_id in self._vectors)
            doc_ids = set(c.source_doc_id for c in chunks if c.source_doc_id)
            urls = set(c.source_url for c in chunks if c.source_url)
        else:
            chunks = list(self._chunks.values())
            vectors_count = self.total_vectors
            doc_ids = set(self._doc_to_chunks.keys())
            urls = set(self._url_to_chunks.keys())

        categories: dict[str, int] = {}
        for c in chunks:
            cat = c.category or "general"
            categories[cat] = categories.get(cat, 0) + 1

        languages: dict[str, int] = {}
        for c in chunks:
            lang = c.language or "unknown"
            languages[lang] = languages.get(lang, 0) + 1

        return {
            "total_chunks": len(chunks),
            "total_vectors": vectors_count,
            "total_documents": len(doc_ids),
            "total_urls": len(urls),
            "expected_dimension": self.expected_dim,
            "category_distribution": categories,
            "language_distribution": languages,
        }

    def save_to_file(self, filepath: str) -> None:
        """Serialize index data to a JSON file."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        data = {
            "expected_dim": self.expected_dim,
            "chunks": [c.model_dump(mode="json") for c in self._chunks.values()],
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Saved %d chunks to vector store file: %s", len(self._chunks), filepath)

    def load_from_file(self, filepath: str) -> int:
        """Load and restore index data from a JSON file."""
        if not os.path.exists(filepath):
            return 0
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        chunks_data = data.get("chunks", [])
        chunks = [DocumentChunk.model_validate(cd) for cd in chunks_data]
        return self.upsert_chunks(chunks)


# Global singleton instance with persistent storage
_DEFAULT_STORE_FILE = os.path.join("output", "vector_store.json")
_global_vector_store = VectorStore(storage_path=_DEFAULT_STORE_FILE)


def get_vector_store() -> VectorStore:
    """Return the global VectorStore singleton instance."""
    return _global_vector_store
