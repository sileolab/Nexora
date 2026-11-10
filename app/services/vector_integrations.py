"""Vector Database Integrations and Exporters for Crawlbot RAG Pipeline.

Primary Integration:
1. Qdrant HTTP REST Connector (Self-hosted or Qdrant Cloud via httpx).
   - Zero mandatory native C++ dependencies.
   - Deterministic UUIDs from chunk IDs (idempotent upserts, zero duplicates).
   - Rich metadata preservation (source_url, title, heading, category, quality, word_count).
   - Safe collection creation and batching.

Export Adapters:
2. Chroma DB Format Exporter (ids, embeddings, documents, metadatas).
3. Pinecone Format Exporter (vectors with id, values, and metadata).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional
import httpx
from pydantic import BaseModel, Field

from app.schemas.chunks import DocumentChunk

logger = logging.getLogger(__name__)


class VectorSyncResult(BaseModel):
    """Result summary of a vector database sync operation."""

    target: str = "qdrant"
    collection_name: str
    points_synced: int = 0
    points_skipped: int = 0
    success: bool = True
    message: str = ""
    errors: list[str] = Field(default_factory=list)


class QdrantSyncService:
    """Manages synchronization of document chunks with Qdrant vector database via HTTP REST API."""

    def __init__(
        self,
        base_url: str = "http://localhost:6333",
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        return headers

    def check_health(self) -> bool:
        """Check if Qdrant service is reachable."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(f"{self.base_url}/healthz", headers=self._get_headers())
                if resp.status_code == 200:
                    return True
                # Fallback to root / check
                resp = client.get(f"{self.base_url}/", headers=self._get_headers())
                return resp.status_code == 200
        except Exception as e:
            logger.warning("Qdrant health check failed: %s", e)
            return False

    def ensure_collection(
        self,
        collection_name: str,
        vector_size: int = 1536,
        distance: str = "Cosine",
    ) -> bool:
        """Ensure collection exists in Qdrant, create if not present."""
        headers = self._get_headers()
        with httpx.Client(timeout=self.timeout) as client:
            # Check if collection exists
            resp = client.get(f"{self.base_url}/collections/{collection_name}", headers=headers)
            if resp.status_code == 200:
                return True

            # Create collection
            payload = {
                "vectors": {
                    "size": vector_size,
                    "distance": distance,
                }
            }
            create_resp = client.put(
                f"{self.base_url}/collections/{collection_name}",
                headers=headers,
                json=payload,
            )
            if create_resp.status_code in (200, 201):
                logger.info("Created Qdrant collection: %s (dim=%d, distance=%s)", collection_name, vector_size, distance)
                return True
            else:
                logger.error("Failed to create Qdrant collection: %s (status %d)", create_resp.text, create_resp.status_code)
                return False

    def sync_chunks(
        self,
        collection_name: str,
        chunks: list[DocumentChunk],
        batch_size: int = 64,
        vector_size: Optional[int] = None,
    ) -> VectorSyncResult:
        """Upsert document chunks into Qdrant collection in batches."""
        # Filter chunks that have embeddings
        valid_chunks = [c for c in chunks if c.embedding and len(c.embedding) > 0]
        if not valid_chunks:
            return VectorSyncResult(
                target="qdrant",
                collection_name=collection_name,
                points_synced=0,
                points_skipped=len(chunks),
                success=True,
                message="No chunks with valid embeddings to sync.",
            )

        inferred_dim = vector_size or len(valid_chunks[0].embedding)
        if not self.ensure_collection(collection_name, vector_size=inferred_dim):
            return VectorSyncResult(
                target="qdrant",
                collection_name=collection_name,
                success=False,
                message=f"Failed to access or create collection '{collection_name}' in Qdrant.",
                errors=["Collection creation failed"],
            )

        points = []
        for c in valid_chunks:
            # Deterministic UUID5 based on chunk_id prevents duplicates on repeat syncs
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"crawlbot:{c.chunk_id}"))
            points.append({
                "id": point_id,
                "vector": c.embedding,
                "payload": {
                    "chunk_id": c.chunk_id,
                    "source_url": c.source_url,
                    "title": c.title,
                    "heading_context": c.heading_context,
                    "chunk_index": c.chunk_index,
                    "total_chunks": c.total_chunks,
                    "char_count": c.char_count,
                    "word_count": c.word_count,
                    "category": c.category,
                    "page_type": getattr(c, "page_type", "article"),
                    "quality_score": getattr(c, "quality_score", 0.0),
                    "content": c.text,
                    "content_hash": c.content_hash,
                },
            })

        total_synced = 0
        errors = []
        headers = self._get_headers()

        with httpx.Client(timeout=self.timeout) as client:
            for i in range(0, len(points), batch_size):
                batch = points[i : i + batch_size]
                try:
                    resp = client.put(
                        f"{self.base_url}/collections/{collection_name}/points?wait=true",
                        headers=headers,
                        json={"points": batch},
                    )
                    if resp.status_code in (200, 201):
                        total_synced += len(batch)
                    else:
                        err_msg = f"Batch {i//batch_size + 1} failed: {resp.status_code} - {resp.text}"
                        logger.error(err_msg)
                        errors.append(err_msg)
                except Exception as e:
                    err_msg = f"Batch {i//batch_size + 1} connection error: {e}"
                    logger.error(err_msg)
                    errors.append(err_msg)

        success = len(errors) == 0
        return VectorSyncResult(
            target="qdrant",
            collection_name=collection_name,
            points_synced=total_synced,
            points_skipped=len(chunks) - len(valid_chunks),
            success=success,
            message=f"Synced {total_synced}/{len(valid_chunks)} chunks to Qdrant collection '{collection_name}'.",
            errors=errors,
        )


def export_to_chroma_format(chunks: list[DocumentChunk]) -> dict[str, Any]:
    """Convert chunks with embeddings to standard ChromaDB batch dictionary."""
    ids = []
    embeddings = []
    documents = []
    metadatas = []

    for c in chunks:
        if not c.embedding:
            continue
        ids.append(c.chunk_id)
        embeddings.append(c.embedding)
        documents.append(c.text)
        metadatas.append({
            "source_url": c.source_url,
            "title": c.title or "",
            "heading_context": c.heading_context or "",
            "category": c.category or "general",
            "page_type": getattr(c, "page_type", "article"),
            "quality_score": float(getattr(c, "quality_score", 0.0) or 0.0),
            "chunk_index": int(c.chunk_index),
            "word_count": int(c.word_count),
        })

    return {
        "ids": ids,
        "embeddings": embeddings,
        "documents": documents,
        "metadatas": metadatas,
        "total_records": len(ids),
    }


def export_to_pinecone_format(chunks: list[DocumentChunk], namespace: str = "") -> dict[str, Any]:
    """Convert chunks with embeddings to standard Pinecone upsert vectors payload."""
    vectors = []
    for c in chunks:
        if not c.embedding:
            continue
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"crawlbot:{c.chunk_id}"))
        vectors.append({
            "id": point_id,
            "values": c.embedding,
            "metadata": {
                "chunk_id": c.chunk_id,
                "text": c.text,
                "source_url": c.source_url,
                "title": c.title or "",
                "heading_context": c.heading_context or "",
                "category": c.category or "general",
                "page_type": getattr(c, "page_type", "article"),
                "quality_score": float(getattr(c, "quality_score", 0.0) or 0.0),
                "word_count": int(c.word_count),
            },
        })

    res: dict[str, Any] = {"vectors": vectors, "total_records": len(vectors)}
    if namespace:
        res["namespace"] = namespace
    return res
