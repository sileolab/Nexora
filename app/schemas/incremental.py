"""Schemas for Phase 4: Incremental Website & Document Processing."""

from __future__ import annotations

import hashlib
from typing import Any, Optional
from pydantic import BaseModel, Field


class PipelineConfigSignature(BaseModel):
    """Configuration signature to detect when chunking/embedding settings require re-processing."""

    chunk_size: int = 500
    chunk_overlap: int = 50
    embedding_model: str = "text-embedding-3-small"
    extraction_strategy: str = "trafilatura"

    def compute_hash(self) -> str:
        """Compute deterministic SHA256 signature of the pipeline settings."""
        sig_str = f"{self.chunk_size}:{self.chunk_overlap}:{self.embedding_model}:{self.extraction_strategy}"
        return hashlib.sha256(sig_str.encode("utf-8")).hexdigest()[:16]


class DocumentHashState(BaseModel):
    """State record for a single document in the incremental manifest."""

    url: str
    content_hash: str = Field(description="SHA-256 hash of clean text or raw payload")
    lastmod: Optional[str] = Field(default=None, description="HTTP Last-Modified or sitemap lastmod hint")
    etag: Optional[str] = Field(default=None, description="HTTP ETag header")
    status_code: int = 200
    chunk_count: int = 0
    embedding_count: int = 0
    config_hash: str = Field(default="", description="Hash signature of the config when processed")
    processed_at: str = Field(default="", description="ISO timestamp of last successful processing")


class IncrementalManifest(BaseModel):
    """Persistent state manifest for a crawling project / domain."""

    manifest_id: str
    project_id: str
    tenant_id: Optional[str] = None
    tenant_id: Optional[str] = None
    created_at: str
    updated_at: str
    pipeline_signature: PipelineConfigSignature
    documents: dict[str, DocumentHashState] = Field(default_factory=dict)

    def get_document(self, url: str) -> Optional[DocumentHashState]:
        return self.documents.get(url)

    def set_document(self, state: DocumentHashState) -> None:
        self.documents[state.url] = state

    def remove_document(self, url: str) -> Optional[DocumentHashState]:
        return self.documents.pop(url, None)


class IncrementalSyncRequest(BaseModel):
    """Request payload to execute an incremental synchronization."""

    project_id: str = Field(description="Unique identifier for the project or domain")
    tenant_id: Optional[str] = None
    tenant_id: Optional[str] = None
    candidate_urls: list[str] = Field(description="Candidate URLs discovered on current crawl")
    raw_documents: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="Optional list of fetched raw documents with {url, text, html, lastmod, etag}",
    )
    chunk_size: int = 500
    chunk_overlap: int = 50
    embedding_model: str = "text-embedding-3-small"
    extraction_strategy: str = "trafilatura"
    force_reprocess: bool = Field(default=False, description="Bypass cache and force re-processing of all documents")


class IncrementalSyncReport(BaseModel):
    """Detailed change report generated after an incremental sync run."""

    project_id: str
    tenant_id: Optional[str] = None
    total_candidates: int
    new_urls: list[str] = Field(default_factory=list)
    modified_urls: list[str] = Field(default_factory=list)
    unchanged_urls: list[str] = Field(default_factory=list)
    deleted_urls: list[str] = Field(default_factory=list)
    config_invalidated: bool = False
    reused_chunks: int = 0
    reused_embeddings: int = 0
    reprocessed_chunks: int = 0
    synced_at: str
    status: str = "completed"
