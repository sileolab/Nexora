"""Chunk schemas for Crawlbot AI pipeline.

Defines Pydantic models representing document chunks produced by the chunker service,
ready for embedding and RAG ingestion.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class ChunkingStrategy(str, Enum):
    """Supported chunking strategies for document processing."""

    AUTO = "auto"
    SEMANTIC_HEADING = "semantic_heading"
    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"
    FIXED_SIZE = "fixed_size"


class DocumentChunk(BaseModel):
    """A single chunk of text extracted from a document, ready for embedding."""

    model_config = ConfigDict(populate_by_name=True)

    chunk_id: str = Field(description="Unique identifier for this chunk (source_url + index + content_hash).")
    source_url: str = Field(description="Original URL of the document this chunk came from.")
    chunk_index: int = Field(ge=0, description="Zero-based sequential index of this chunk within its source document.")
    total_chunks: int = Field(ge=1, description="Total number of chunks produced from the source document.")
    text: str = Field(description="Plain text content of this chunk.")
    char_count: int = Field(ge=0, description="Number of characters in this chunk.")
    word_count: int = Field(ge=0, description="Approximate word count of this chunk.")
    heading_context: Optional[str] = Field(
        default=None,
        description="The hierarchical heading context (H1 > H2 > ... > H6) that precedes this chunk, if any.",
    )
    title: Optional[str] = Field(default=None, description="Title of the source document.")
    source_title: Optional[str] = Field(default=None, description="Same as title, for compatibility.")
    language: Optional[str] = Field(default=None, description="Language of the source document.")
    category: Optional[str] = Field(default=None, description="User-specified category/tag for the document.")
    tenant_id: Optional[str] = Field(
        default=None,
        description="Workspace or tenant identifier for multi-tenant isolation.",
    )
    embedding: Optional[list[float]] = Field(
        default=None,
        description="Vector embedding for this chunk produced by the embedding service.",
    )
    embedding_model: Optional[str] = Field(
        default=None,
        description="Name of the embedding model used to generate the vector.",
    )
    content_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 fingerprint hash of the chunk text.",
    )
    source_doc_id: Optional[str] = Field(
        default=None,
        description="Persistent identifier of the source document.",
    )
    source_doc_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 fingerprint hash of the source document.",
    )
    processed_at: Optional[Union[datetime, str]] = Field(
        default=None,
        description="ISO-8601 timestamp of processing.",
    )
    quality_flags: list[str] = Field(
        default_factory=list,
        description="Quality, noise, or structure flags attached to this chunk.",
    )
    normalization_applied: bool = Field(
        default=False,
        description="Whether text normalization was performed on this chunk.",
    )
    parent_heading: Optional[str] = Field(
        default=None,
        description="Immediate parent heading of this chunk.",
    )
    breadcrumbs: list[str] = Field(
        default_factory=list,
        description="List of hierarchical headings leading to this chunk.",
    )
    token_count_approx: int = Field(
        default=0,
        description="Approximate token count for RAG context budgeting.",
    )
    alternate_sources: list[dict] = Field(
        default_factory=list,
        description="Other duplicate source URLs/documents that contained this identical chunk.",
    )
    semantic_link: Optional[dict] = Field(
        default=None,
        description="Semantic connection linking this chunk to an entity or predecessor chunk.",
    )
    page_number: Optional[int] = Field(
        default=None,
        description="Page number for document formats like PDF.",
    )
    user_edited: bool = Field(
        default=False,
        description="Whether this chunk was manually edited in the Data Studio.",
    )
    edit_history: list[dict] = Field(
        default_factory=list,
        description="Audit history of manual edits for undo/revert.",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata attached to this chunk.",
    )


class ChunkingResult(BaseModel):
    """Result of chunking a single document."""

    model_config = ConfigDict(populate_by_name=True)

    source_url: str = Field(description="URL of the source document.")
    total_chunks: int = Field(ge=0, description="Number of chunks produced.")
    strategy: str = Field(description="Chunking strategy that was applied or requested.")
    applied_strategy: Optional[str] = Field(
        default=None,
        description="The concrete strategy applied to the document (useful when strategy='auto').",
    )
    chunks: list[DocumentChunk] = Field(default_factory=list, description="List of produced chunks.")
    metadata: dict = Field(
        default_factory=dict,
        description="Metadata about chunking execution, e.g. auto strategy selection reason.",
    )


class EmbeddingStats(BaseModel):
    """Statistics from an embedding run."""

    model_config = ConfigDict(populate_by_name=True)

    total_chunks: int = Field(ge=0)
    embedded_chunks: int = Field(ge=0)
    failed_chunks: int = Field(ge=0)
    model: str
    total_tokens: int = Field(ge=0, default=0)


class VectorSearchRequest(BaseModel):
    """Request schema for semantic / hybrid vector search."""

    model_config = ConfigDict(populate_by_name=True)

    query: str = Field(description="Search query string.")
    top_k: int = Field(default=5, ge=1, le=100, description="Maximum number of results to return.")
    category: Optional[str] = Field(default=None, description="Optional category filter (e.g. 'resume', 'skills').")
    source_url: Optional[str] = Field(default=None, description="Optional source URL filter.")
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum relevance score threshold.")
    hybrid: bool = Field(default=True, description="Whether to use hybrid search (dense vectors + sparse BM25).")
    alpha: float = Field(default=0.7, ge=0.0, le=1.0, description="Weight of dense vector search in hybrid score (1.0 = pure vector, 0.0 = pure lexical).")
    expand_neighbors: bool = Field(default=False, description="Whether to include adjacent preceding and succeeding chunks for context expansion.")


class VectorSearchResultItem(BaseModel):
    """A single search result item with scoring and neighboring context."""

    model_config = ConfigDict(populate_by_name=True)

    chunk: DocumentChunk
    score: float = Field(description="Combined relevance score.")
    dense_score: Optional[float] = Field(default=None, description="Cosine similarity score.")
    sparse_score: Optional[float] = Field(default=None, description="BM25 lexical similarity score.")
    neighbors: list[DocumentChunk] = Field(default_factory=list, description="Adjacent context chunks if requested.")


class VectorSearchResponse(BaseModel):
    """Response containing retrieved chunks and search telemetry."""

    model_config = ConfigDict(populate_by_name=True)

    query: str
    total_results: int
    results: list[VectorSearchResultItem]
    latency_ms: float = 0.0
