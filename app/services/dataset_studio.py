"""Dataset Studio Service for Crawlbot.

Provides Stage-by-Stage Data Inspection, Chunk Review & Editor, Dataset Quality Reports,
Dataset Versioning & Semantic Diff, and Standard Export Manifests.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import get_settings
from app.jobs.manager import JobManager, get_job_manager
from app.schemas.chunks import DocumentChunk
from app.schemas.documents import ExtractedDocument, QualityStatus

logger = logging.getLogger(__name__)


class DatasetStudioService:
    """Core domain service for stage inspection, chunk management, quality auditing, and version diffing."""

    def __init__(self, job_manager: Optional[JobManager] = None) -> None:
        """Initialize DatasetStudioService with job manager and snapshot storage."""
        self._manager = job_manager
        # job_id -> list of snapshot dicts
        self._snapshots: dict[str, list[dict[str, Any]]] = {}

    @property
    def manager(self) -> JobManager:
        """Return the JobManager instance, resolving from global if not injected."""
        if self._manager is None:
            self._manager = get_job_manager()
        return self._manager

    # -----------------------------------------------------------------------
    # Section A: Stage Inspection
    # -----------------------------------------------------------------------

    def get_stages(
        self,
        job_id: str,
        url: Optional[str] = None,
        doc_index: int = 0,
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Inspect stage-by-stage progression for a job document."""
        job = self.manager.get_job(job_id, tenant_id=tenant_id)
        if not job:
            raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")

        docs = self.manager.get_documents(job_id, tenant_id=tenant_id)
        all_chunks = self.manager.get_chunks(job_id, tenant_id=tenant_id)
        rag_meta = self.manager.get_rag_metadata(job_id, tenant_id=tenant_id)

        target_doc: Optional[ExtractedDocument] = None
        if url:
            for d in docs:
                if d.url == url or d.final_url == url or d.source_url == url:
                    target_doc = d
                    break
        elif docs and 0 <= doc_index < len(docs):
            target_doc = docs[doc_index]

        # Filter chunks related to this document
        doc_chunks: list[DocumentChunk] = []
        if target_doc:
            doc_chunks = [
                c for c in all_chunks
                if c.source_url in (target_doc.url, target_doc.final_url, target_doc.source_url)
                or c.source_doc_id == target_doc.document_id
            ]
        elif all_chunks:
            doc_chunks = all_chunks[:10]

        stages: list[dict[str, Any]] = []

        # 1. Raw Source Stage
        raw_text = (
            (target_doc.raw_html if target_doc and getattr(target_doc, "raw_html", None) else None)
            or (target_doc.content_text if target_doc else None)
            or ""
        )
        stages.append({
            "stage_id": "raw_source",
            "stage_name": "متن خام منبع (Raw Source)",
            "available": bool(target_doc),
            "input_description": "دریافت سند از وب‌سایت یا بارگذاری فایل خام",
            "operations_applied": [
                "HTTP Fetch",
                "Redirect Resolution",
                "Status Code Validation",
            ],
            "item_count": 1 if target_doc else 0,
            "char_count": len(raw_text),
            "warnings": target_doc.quality_report.warnings if target_doc and target_doc.quality_report else [],
            "preview": raw_text[:1200] if raw_text else "",
        })

        # 2. Extracted Text Stage
        extracted_text = (target_doc.content_text or "") if target_doc else ""
        diff_raw_ext = ""
        if raw_text and extracted_text and raw_text != extracted_text:
            diff_raw_ext = self._make_diff(raw_text[:500], extracted_text[:500])

        stages.append({
            "stage_id": "extracted",
            "stage_name": "متن استخراج‌شده (Extracted Text)",
            "available": bool(extracted_text),
            "input_description": "خروجی موتور استخراج محتوا پس از حذف تگ‌های زائد",
            "operations_applied": [
                f"Engine: {getattr(target_doc, 'selected_engine', 'auto') if target_doc else 'auto'}",
                "HTML Parsing",
                "Boilerplate Strip",
            ],
            "item_count": 1 if extracted_text else 0,
            "char_count": len(extracted_text),
            "warnings": [],
            "preview": extracted_text[:1200] if extracted_text else "",
            "diff_with_previous": diff_raw_ext,
        })

        # 3. Cleaned and Normalized Stage
        cleaned_text = (target_doc.content_text or "") if target_doc else ""
        stages.append({
            "stage_id": "cleaned_normalized",
            "stage_name": "متن پاک‌سازی و نرمال‌شده (Cleaned & Normalized)",
            "available": bool(cleaned_text),
            "input_description": "یکپارچه‌سازی یونیکد، اصلاح نویسه‌های فارسی/عربی و مدیریت نیم‌فاصله (ZWNJ)",
            "operations_applied": [
                "Unicode NFC Normalization",
                "Arabic to Persian Character Unification",
                "Zero-Width Non-Joiner (ZWNJ) Affix Correction",
            ],
            "item_count": 1 if cleaned_text else 0,
            "char_count": len(cleaned_text),
            "warnings": [],
            "preview": cleaned_text[:1200] if cleaned_text else "",
        })

        # 4. Structured Markdown Stage
        md_text = (target_doc.content_markdown or "") if target_doc else ""
        diff_clean_md = ""
        if cleaned_text and md_text and cleaned_text != md_text:
            diff_clean_md = self._make_diff(cleaned_text[:500], md_text[:500])

        stages.append({
            "stage_id": "structured_markdown",
            "stage_name": "مارک‌داون ساختاریافته (Structured Markdown)",
            "available": bool(md_text),
            "input_description": "حفظ سلسله‌مراتب تیترها (H1-H6)، جدول‌ها، نقل‌قول‌ها و لیست‌ها",
            "operations_applied": [
                "Heading Hierarchy Extraction",
                "Table & List Formatting",
                "YAML Metadata Header Injection",
            ],
            "item_count": len(getattr(target_doc, "headings", [])) if target_doc else 1,
            "char_count": len(md_text),
            "warnings": [],
            "preview": md_text[:1200] if md_text else "",
            "diff_with_previous": diff_clean_md,
        })

        # 5. Generated Chunks Stage
        strategy_used = doc_chunks[0].metadata.get("strategy", "auto") if doc_chunks else "auto"
        stages.append({
            "stage_id": "chunks",
            "stage_name": "قطعات تولیدشده (Generated Chunks)",
            "available": bool(doc_chunks),
            "input_description": "تقطیع هوشمند با پنجره همپوشانی و حفظ زمینه تیتری",
            "operations_applied": [
                f"Chunking Strategy: {strategy_used}",
                "Overlap Window Allocation",
                "Heading Context Prepending",
            ],
            "item_count": len(doc_chunks),
            "char_count": sum(c.char_count for c in doc_chunks),
            "warnings": [flag for c in doc_chunks for flag in c.quality_flags][:5],
            "preview": doc_chunks[0].text[:1200] if doc_chunks else "",
        })

        # 6. Semantic Repaired Stage
        has_repaired = any(c.quality_flags or c.user_edited for c in doc_chunks)
        stages.append({
            "stage_id": "semantic_repaired",
            "stage_name": "خروجی پس از Semantic Repair",
            "available": bool(doc_chunks),
            "input_description": "ترمیم نشت بافت عناوین، تصحیح دسته‌بندی و پاک‌سازی آرتیفکت‌ها",
            "operations_applied": [
                "Heading Context Leakage Guard",
                "Category Verification",
                "Artifact Removal",
            ],
            "item_count": len(doc_chunks),
            "char_count": sum(c.char_count for c in doc_chunks),
            "warnings": [],
            "preview": doc_chunks[0].text[:1200] if doc_chunks else "",
        })

        # 7. Embedding & Vector Metadata Stage
        embedded_count = sum(1 for c in doc_chunks if c.embedding is not None)
        model_name = doc_chunks[0].embedding_model if (doc_chunks and doc_chunks[0].embedding_model) else None
        stages.append({
            "stage_id": "embeddings",
            "stage_name": "بردارهای جاسازی (Vector Embeddings)",
            "available": embedded_count > 0,
            "input_description": "تولید بردار معنایی متراکم جهت بازیابی ترکیبی در RAG",
            "operations_applied": [
                f"Embedding Model: {model_name or 'Pending'}",
                "Vector Normalization",
                "Vector Store Indexing",
            ],
            "item_count": embedded_count,
            "char_count": sum(c.char_count for c in doc_chunks if c.embedding is not None),
            "warnings": [] if embedded_count > 0 else ["هنوز بردار برای این قطعات تولید نشده است."],
            "preview": (
                f"مدل: {model_name}, تعداد قطعات دارای بردار: {embedded_count}/{len(doc_chunks)}, "
                f"ابعاد بردار: {len(doc_chunks[0].embedding) if (doc_chunks and doc_chunks[0].embedding) else 0}"
            ),
        })

        return {
            "job_id": job_id,
            "document": {
                "url": target_doc.url if target_doc else None,
                "title": target_doc.title if target_doc else None,
                "char_count": target_doc.character_count if target_doc else 0,
                "word_count": target_doc.word_count if target_doc else 0,
            } if target_doc else None,
            "total_documents": len(docs),
            "stages": stages,
        }

    # -----------------------------------------------------------------------
    # Section B: Chunk Review & Editor
    # -----------------------------------------------------------------------

    def query_chunks(
        self,
        job_id: str,
        query: Optional[str] = None,
        quality: Optional[str] = None,
        category: Optional[str] = None,
        source_url: Optional[str] = None,
        language: Optional[str] = None,
        user_edited: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Search and filter chunks with pagination."""
        if tenant_id:
            job = self.manager.get_job(job_id, tenant_id=tenant_id)
            if not job:
                raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")
        all_chunks = self.manager.get_chunks(job_id, tenant_id=tenant_id)
        if not all_chunks:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

        filtered: list[DocumentChunk] = []
        q_clean = query.strip().lower() if query else None

        for c in all_chunks:
            # Query text match
            if q_clean:
                text_match = q_clean in c.text.lower()
                heading_match = bool(c.heading_context and q_clean in c.heading_context.lower())
                id_match = q_clean in c.chunk_id.lower()
                title_match = bool(c.title and q_clean in c.title.lower())
                if not (text_match or heading_match or id_match or title_match):
                    continue

            # Quality filter
            if quality and quality != "all":
                if quality == "flagged" and not c.quality_flags:
                    continue
                elif quality == "clean" and c.quality_flags:
                    continue
                elif quality == "low_quality" and "low_quality" not in c.quality_flags and c.char_count >= 100:
                    continue
                elif quality not in ("flagged", "clean", "low_quality") and quality not in c.quality_flags:
                    continue

            # Category filter
            if category and (c.category or "").lower() != category.strip().lower():
                continue

            # Source URL filter
            if source_url and source_url.lower() not in c.source_url.lower():
                continue

            # Language filter
            if language and (c.language or "").lower() != language.strip().lower():
                continue

            # User edited filter
            if user_edited is not None and bool(c.user_edited) != user_edited:
                continue

            filtered.append(c)

        total = len(filtered)
        p = max(1, page)
        ps = max(1, min(page_size, 100))
        total_pages = math.ceil(total / ps) if total > 0 else 1
        start_idx = (p - 1) * ps
        end_idx = start_idx + ps
        page_items = filtered[start_idx:end_idx]

        return {
            "items": [c.model_dump() for c in page_items],
            "total": total,
            "page": p,
            "page_size": ps,
            "total_pages": total_pages,
        }

    def update_chunk(
        self,
        job_id: str,
        chunk_id: str,
        text: Optional[str] = None,
        heading_context: Optional[str] = None,
        category: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update a chunk's content or metadata with history and selective vector invalidation."""
        if tenant_id:
            job = self.manager.get_job(job_id, tenant_id=tenant_id)
            if not job:
                raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")
        all_chunks = self.manager.get_chunks(job_id, tenant_id=tenant_id)
        target_chunk: Optional[DocumentChunk] = None

        for c in all_chunks:
            if c.chunk_id == chunk_id:
                target_chunk = c
                break

        if not target_chunk:
            raise ValueError(f"قطعه با شناسه '{chunk_id}' یافت نشد.")

        # Record current state in audit history for undo/revert
        history_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "edit",
            "old_text": target_chunk.text,
            "old_heading_context": target_chunk.heading_context,
            "old_category": target_chunk.category,
            "old_content_hash": target_chunk.content_hash,
            "old_embedding": target_chunk.embedding,
            "old_embedding_model": target_chunk.embedding_model,
        }
        target_chunk.edit_history.append(history_entry)

        embedding_invalidated = False

        # If text changed: recalculate hashes and invalidate vector embedding
        if text is not None and text.strip() != target_chunk.text.strip():
            clean_text = text.strip()
            target_chunk.text = clean_text
            target_chunk.char_count = len(clean_text)
            target_chunk.word_count = len(clean_text.split())
            target_chunk.content_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
            target_chunk.embedding = None
            target_chunk.embedding_model = None
            embedding_invalidated = True
            logger.info("Chunk %s text updated. Vector embedding invalidated.", chunk_id)

        # Update metadata without invalidating embeddings
        if heading_context is not None:
            target_chunk.heading_context = heading_context.strip() or None
        if category is not None:
            target_chunk.category = category.strip() or None
        if metadata:
            target_chunk.metadata.update(metadata)

        target_chunk.user_edited = True
        self.manager.store_chunks(job_id, all_chunks)

        return {
            "chunk": target_chunk.model_dump(),
            "embedding_invalidated": embedding_invalidated,
            "re_embed_needed": embedding_invalidated,
        }

    def merge_chunks(
        self,
        job_id: str,
        chunk_ids: list[str],
        separator: str = "\n\n",
        heading_context: Optional[str] = None,
        category: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Merge two or more chunks into a single unified chunk."""
        if len(chunk_ids) < 2:
            raise ValueError("برای ادغام، حداقل انتخاب دو قطعه الزامی است.")

        if tenant_id:
            job = self.manager.get_job(job_id, tenant_id=tenant_id)
            if not job:
                raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")
        all_chunks = self.manager.get_chunks(job_id, tenant_id=tenant_id)
        id_to_chunk = {c.chunk_id: c for c in all_chunks}

        selected: list[DocumentChunk] = []
        for cid in chunk_ids:
            if cid not in id_to_chunk:
                raise ValueError(f"قطعه با شناسه '{cid}' برای ادغام یافت نشد.")
            selected.append(id_to_chunk[cid])

        # Preserve relative order as they appear in the original chunk sequence
        selected.sort(key=lambda c: all_chunks.index(c))
        first_chunk = selected[0]

        combined_text = separator.join(c.text for c in selected)
        new_chunk_id = f"merged_{uuid.uuid4().hex[:10]}"
        final_heading = heading_context or first_chunk.heading_context
        final_category = category or first_chunk.category

        merged_chunk = DocumentChunk(
            chunk_id=new_chunk_id,
            source_url=first_chunk.source_url,
            chunk_index=first_chunk.chunk_index,
            total_chunks=max(1, len(all_chunks) - len(selected) + 1),
            text=combined_text,
            char_count=len(combined_text),
            word_count=len(combined_text.split()),
            heading_context=final_heading,
            title=first_chunk.title,
            source_title=first_chunk.source_title,
            language=first_chunk.language,
            category=final_category,
            content_hash=hashlib.sha256(combined_text.encode("utf-8")).hexdigest(),
            source_doc_id=first_chunk.source_doc_id,
            source_doc_hash=first_chunk.source_doc_hash,
            processed_at=datetime.now(timezone.utc).isoformat(),
            quality_flags=["merged_chunk"],
            user_edited=True,
            edit_history=[{
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "merge",
                "source_chunk_ids": chunk_ids,
            }],
        )

        # Replace selected chunks with the merged chunk
        new_list: list[DocumentChunk] = []
        merged_inserted = False
        for c in all_chunks:
            if c.chunk_id in chunk_ids:
                if not merged_inserted:
                    new_list.append(merged_chunk)
                    merged_inserted = True
            else:
                new_list.append(c)

        self.manager.store_chunks(job_id, new_list)
        return {
            "merged_chunk": merged_chunk.model_dump(),
            "removed_chunk_ids": chunk_ids,
            "total_chunks_remaining": len(new_list),
        }

    def split_chunk(
        self,
        job_id: str,
        chunk_id: str,
        split_points: Optional[list[int]] = None,
        separator: Optional[str] = None,
        max_chars: Optional[int] = None,
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Split a chunk into multiple smaller chunks."""
        if tenant_id:
            job = self.manager.get_job(job_id, tenant_id=tenant_id)
            if not job:
                raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")
        all_chunks = self.manager.get_chunks(job_id, tenant_id=tenant_id)
        target: Optional[DocumentChunk] = None
        target_idx = -1

        for i, c in enumerate(all_chunks):
            if c.chunk_id == chunk_id:
                target = c
                target_idx = i
                break

        if not target or target_idx == -1:
            raise ValueError(f"قطعه با شناسه '{chunk_id}' جهت تفکیک یافت نشد.")

        text = target.text
        pieces: list[str] = []

        if split_points:
            sorted_pts = sorted([p for p in split_points if 0 < p < len(text)])
            start = 0
            for pt in sorted_pts:
                pieces.append(text[start:pt].strip())
                start = pt
            pieces.append(text[start:].strip())
        elif separator and separator in text:
            pieces = [p.strip() for p in text.split(separator) if p.strip()]
        elif max_chars and max_chars > 0 and len(text) > max_chars:
            words = text.split()
            cur: list[str] = []
            cur_len = 0
            for w in words:
                if cur_len + len(w) + 1 > max_chars and cur:
                    pieces.append(" ".join(cur))
                    cur = [w]
                    cur_len = len(w)
                else:
                    cur.append(w)
                    cur_len += len(w) + 1
            if cur:
                pieces.append(" ".join(cur))
        else:
            # Default fallback: split cleanly in half at closest paragraph or newline
            mid = len(text) // 2
            split_idx = text.rfind("\n\n", 0, mid + 100)
            if split_idx == -1 or split_idx < mid // 2:
                split_idx = text.rfind(". ", 0, mid + 50)
                if split_idx != -1:
                    split_idx += 1
            if split_idx == -1 or split_idx <= 0 or split_idx >= len(text):
                split_idx = mid
            pieces = [text[:split_idx].strip(), text[split_idx:].strip()]

        pieces = [p for p in pieces if p]
        if len(pieces) < 2:
            raise ValueError("امکان تفکیک متن به قطعات مجزا با شرایط داده‌شده وجود ندارد.")

        new_sub_chunks: list[DocumentChunk] = []
        for idx, piece in enumerate(pieces, 1):
            sub_id = f"{target.chunk_id}_s{idx}"
            sc = DocumentChunk(
                chunk_id=sub_id,
                source_url=target.source_url,
                chunk_index=target.chunk_index + idx - 1,
                total_chunks=target.total_chunks + len(pieces) - 1,
                text=piece,
                char_count=len(piece),
                word_count=len(piece.split()),
                heading_context=target.heading_context,
                title=target.title,
                source_title=target.source_title,
                language=target.language,
                category=target.category,
                content_hash=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                source_doc_id=target.source_doc_id,
                source_doc_hash=target.source_doc_hash,
                processed_at=datetime.now(timezone.utc).isoformat(),
                quality_flags=["split_chunk"],
                user_edited=True,
                edit_history=[{
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": "split",
                    "original_chunk_id": target.chunk_id,
                }],
            )
            new_sub_chunks.append(sc)

        all_chunks[target_idx:target_idx + 1] = new_sub_chunks
        self.manager.store_chunks(job_id, all_chunks)

        return {
            "original_chunk_id": chunk_id,
            "split_chunks": [c.model_dump() for c in new_sub_chunks],
            "total_chunks_after_split": len(all_chunks),
        }

    def revert_chunk(self, job_id: str, chunk_id: str, tenant_id: Optional[str] = None) -> dict[str, Any]:
        """Undo the last manual edit and restore previous chunk state."""
        if tenant_id:
            job = self.manager.get_job(job_id, tenant_id=tenant_id)
            if not job:
                raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")
        all_chunks = self.manager.get_chunks(job_id, tenant_id=tenant_id)
        target: Optional[DocumentChunk] = None

        for c in all_chunks:
            if c.chunk_id == chunk_id:
                target = c
                break

        if not target:
            raise ValueError(f"قطعه با شناسه '{chunk_id}' یافت نشد.")

        if not target.edit_history:
            raise ValueError("هیچ تاریخچه ویرایشی برای این قطعه موجود نیست.")

        last_entry = target.edit_history.pop()
        action = last_entry.get("action")

        if action == "edit":
            target.text = last_entry.get("old_text", target.text)
            target.char_count = len(target.text)
            target.word_count = len(target.text.split())
            target.heading_context = last_entry.get("old_heading_context")
            target.category = last_entry.get("old_category")
            target.content_hash = last_entry.get("old_content_hash")
            target.embedding = last_entry.get("old_embedding")
            target.embedding_model = last_entry.get("old_embedding_model")

        if not target.edit_history:
            target.user_edited = False

        self.manager.store_chunks(job_id, all_chunks)
        return {
            "chunk": target.model_dump(),
            "remaining_history_depth": len(target.edit_history),
        }

    # -----------------------------------------------------------------------
    # Section C: Data Quality Report
    # -----------------------------------------------------------------------

    def generate_quality_report(self, job_id: str, tenant_id: Optional[str] = None) -> dict[str, Any]:
        """Generate comprehensive deterministic and estimated dataset telemetry."""
        job = self.manager.get_job(job_id, tenant_id=tenant_id)
        if not job:
            raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")

        docs = self.manager.get_documents(job_id, tenant_id=tenant_id)
        chunks = self.manager.get_chunks(job_id, tenant_id=tenant_id)

        # 1. Crawl / URL Telemetry (Deterministic)
        pages = job.pages or []
        total_urls = job.total
        crawled_urls = job.completed
        failed_urls = job.failed
        status_codes: dict[int, int] = {}
        for p in pages:
            sc = p.get("status")
            if isinstance(sc, int):
                status_codes[sc] = status_codes.get(sc, 0) + 1

        # 2. Document Quality Telemetry (Deterministic)
        total_docs = len(docs)
        empty_docs = sum(1 for d in docs if not d.has_content)
        suspicious_low_content = sum(1 for d in docs if d.has_content and d.character_count < 200)
        duplicates = sum(1 for d in docs if getattr(d, "quality_status", None) == QualityStatus.DUPLICATE)

        quality_distribution = {
            "high": sum(1 for d in docs if getattr(d, "quality_status", None) == QualityStatus.SUCCESS and d.character_count >= 500),
            "medium": sum(1 for d in docs if getattr(d, "quality_status", None) == QualityStatus.SUCCESS and d.character_count < 500),
            "low": sum(1 for d in docs if getattr(d, "quality_status", None) == QualityStatus.LOW_QUALITY or suspicious_low_content),
            "empty": empty_docs,
            "duplicate": duplicates,
        }

        # 3. Content Volume & Deltas (Deterministic + Estimated)
        raw_chars = sum(len(getattr(d, "raw_html", "") or d.content_text or "") for d in docs)
        cleaned_markdown_chars = sum(len(d.content_markdown or d.content_text or "") for d in docs)
        chunked_chars = sum(c.char_count for c in chunks)
        total_words = sum(d.word_count for d in docs)

        # Estimation: token count approx (Persian / English mixed heuristic: ~3.5 chars per token)
        estimated_tokens = int(cleaned_markdown_chars / 3.5) if cleaned_markdown_chars > 0 else 0

        # Heuristic Boilerplate / Noise ratio
        noise_ratio = (
            round(((raw_chars - cleaned_markdown_chars) / raw_chars) * 100, 1)
            if raw_chars > 0 and raw_chars > cleaned_markdown_chars
            else 0.0
        )

        raw_to_md_delta = (
            round(((cleaned_markdown_chars - raw_chars) / raw_chars) * 100, 1)
            if raw_chars > 0 else 0.0
        )

        # 4. Chunk Telemetry (Deterministic)
        total_chunks = len(chunks)
        user_edited_chunks = sum(1 for c in chunks if getattr(c, "user_edited", False))
        avg_chunk_size = int(chunked_chars / total_chunks) if total_chunks > 0 else 0

        flags_breakdown: dict[str, int] = {}
        size_histogram = {"<300": 0, "300-800": 0, "800-1500": 0, ">1500": 0}
        for c in chunks:
            for f in c.quality_flags:
                flags_breakdown[f] = flags_breakdown.get(f, 0) + 1
            if c.char_count < 300:
                size_histogram["<300"] += 1
            elif c.char_count <= 800:
                size_histogram["300-800"] += 1
            elif c.char_count <= 1500:
                size_histogram["800-1500"] += 1
            else:
                size_histogram[">1500"] += 1

        # 5. Embedding Telemetry (Deterministic)
        embedded_chunks = sum(1 for c in chunks if c.embedding is not None)
        pending_embeddings = total_chunks - embedded_chunks
        model_name = chunks[0].embedding_model if (chunks and chunks[0].embedding_model) else None

        # 6. Actionable Warnings
        warnings: list[dict[str, str]] = []
        if total_docs > 0 and (empty_docs / total_docs) > 0.1:
            warnings.append({
                "severity": "high",
                "category": "استخراج محتوا",
                "message": f"{empty_docs} سند از {total_docs} سند ({round(empty_docs / total_docs * 100)}%) فاقد محتوا هستند.",
                "action": "تنظیمات انتخابگرهای CSS یا استفاده از موتور Playwright برای صفحات جاوااسکریپتی بررسی شود.",
            })
        if total_chunks > 0 and size_histogram["<300"] / total_chunks > 0.25:
            warnings.append({
                "severity": "medium",
                "category": "تقطیع",
                "message": f"بیش از ۲۵٪ قطعات کمتر از ۳۰۰ کاراکتر هستند ({size_histogram['<300']} قطعه).",
                "action": "افزایش chunk_size یا تغییر استراتژی تقطیع به semantic_heading پیشنهاد می‌شود.",
            })
        if pending_embeddings > 0:
            warnings.append({
                "severity": "info",
                "category": "جاسازی وکتور",
                "message": f"{pending_embeddings} قطعه فاقد بردار Embedding هستند.",
                "action": "عملیات تولید بردار (/api/ai/embed) را برای پوشش کامل فراخوانی نمایید.",
            })

        return {
            "job_id": job_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "crawl_telemetry": {
                "total_urls": total_urls,
                "crawled_urls": crawled_urls,
                "failed_urls": failed_urls,
                "status_codes": status_codes,
            },
            "document_quality": {
                "total_documents": total_docs,
                "empty_documents": empty_docs,
                "suspicious_low_content": suspicious_low_content,
                "duplicate_documents": duplicates,
                "quality_distribution": quality_distribution,
            },
            "content_volume": {
                "raw_characters": raw_chars,
                "cleaned_markdown_characters": cleaned_markdown_chars,
                "chunked_characters": chunked_chars,
                "total_words": total_words,
                "estimated_tokens": estimated_tokens,
                "estimated_noise_ratio_percent": noise_ratio,
                "volume_delta_percent": raw_to_md_delta,
            },
            "chunk_telemetry": {
                "total_chunks": total_chunks,
                "average_chunk_size": avg_chunk_size,
                "user_edited_chunks": user_edited_chunks,
                "quality_flags_breakdown": flags_breakdown,
                "size_histogram": size_histogram,
            },
            "embedding_telemetry": {
                "total_chunks": total_chunks,
                "embedded_chunks": embedded_chunks,
                "pending_embeddings": pending_embeddings,
                "embedding_model": model_name,
            },
            "actionable_warnings": warnings,
            "metrics_legend": {
                "deterministic": [
                    "تعداد صفحات، کدهای وضعیت HTTP، تعداد کلمات و کاراکترها",
                    "تعداد دقیق اسناد، قطعات و هشدارهای ساختاری",
                    "اثرانگشت SHA-256 محتوا و وضعیت وجود بردار",
                ],
                "estimated": [
                    "تعداد تقریبی توکن‌ها (بر مبنای میانگین ۳.۵ کاراکتر به ازای هر توکن)",
                    "نسبت نویز منبع (بر مبنای مقایسه اندازه HTML اولیه و متن استخراجی)",
                ],
            },
        }

    # -----------------------------------------------------------------------
    # Section D: Dataset Versioning & Semantic Diff
    # -----------------------------------------------------------------------

    def create_snapshot(
        self,
        job_id: str,
        version_label: Optional[str] = None,
        description: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a persistent immutable snapshot of the current chunks."""
        job = self.manager.get_job(job_id, tenant_id=tenant_id)
        if not job:
            raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")

        chunks = self.manager.get_chunks(job_id)
        existing_snapshots = self._snapshots.setdefault(job_id, [])

        if not version_label:
            version_label = f"v{len(existing_snapshots) + 1}"

        # Calculate aggregate SHA-256 fingerprint
        sorted_hashes = sorted(c.content_hash or "" for c in chunks)
        aggregate_hash = hashlib.sha256("".join(sorted_hashes).encode("utf-8")).hexdigest()

        snapshot_record = {
            "version": version_label,
            "description": description or f"Snapshot {version_label}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "chunk_count": len(chunks),
            "aggregate_hash": aggregate_hash,
            "chunks": [copy.deepcopy(c) for c in chunks],
        }

        existing_snapshots.append(snapshot_record)
        logger.info("Created dataset snapshot %s for job %s with %d chunks.", version_label, job_id, len(chunks))

        return {
            "version": version_label,
            "description": snapshot_record["description"],
            "created_at": snapshot_record["created_at"],
            "chunk_count": len(chunks),
            "aggregate_hash": aggregate_hash,
        }

    def list_snapshots(self, job_id: str, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        """List summary of all snapshots created for a job."""
        if tenant_id:
            job = self.manager.get_job(job_id, tenant_id=tenant_id)
            if not job:
                raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")
        snaps = self._snapshots.get(job_id, [])
        return [
            {
                "version": s["version"],
                "description": s["description"],
                "created_at": s["created_at"],
                "chunk_count": s["chunk_count"],
                "aggregate_hash": s["aggregate_hash"],
            }
            for s in snaps
        ]

    def diff_snapshots(
        self,
        job_id: str,
        v1_label: str,
        v2_label: str = "current",
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Compare two snapshots or a snapshot against current state."""
        if tenant_id:
            job = self.manager.get_job(job_id, tenant_id=tenant_id)
            if not job:
                raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")
        snaps = self._snapshots.get(job_id, [])
        v1_snap = next((s for s in snaps if s["version"] == v1_label), None)
        if not v1_snap:
            raise ValueError(f"نسخه مبدا '{v1_label}' یافت نشد.")

        if v2_label.lower() in ("current", "live"):
            v2_chunks = self.manager.get_chunks(job_id)
        else:
            v2_snap = next((s for s in snaps if s["version"] == v2_label), None)
            if not v2_snap:
                raise ValueError(f"نسخه مقصد '{v2_label}' یافت نشد.")
            v2_chunks = v2_snap["chunks"]

        v1_chunks: list[DocumentChunk] = v1_snap["chunks"]

        v1_map = {c.chunk_id: c for c in v1_chunks}
        v2_map = {c.chunk_id: c for c in v2_chunks}

        added: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        modified: list[dict[str, Any]] = []
        unchanged_count = 0

        re_embedding_needed_count = 0
        cost_saving_retained_count = 0

        # Check for additions and modifications
        for cid, c2 in v2_map.items():
            if cid not in v1_map:
                added.append({
                    "chunk_id": cid,
                    "title": c2.title,
                    "char_count": c2.char_count,
                    "category": c2.category,
                    "preview": c2.text[:200],
                })
                re_embedding_needed_count += 1
            else:
                c1 = v1_map[cid]
                text_changed = (c1.content_hash != c2.content_hash) or (c1.text != c2.text)
                meta_changed = (
                    c1.category != c2.category
                    or c1.heading_context != c2.heading_context
                    or c1.metadata != c2.metadata
                )

                if text_changed or meta_changed:
                    if text_changed:
                        re_embedding_needed_count += 1
                    else:
                        cost_saving_retained_count += 1

                    modified.append({
                        "chunk_id": cid,
                        "text_changed": text_changed,
                        "metadata_changed": meta_changed,
                        "old_category": c1.category,
                        "new_category": c2.category,
                        "old_heading": c1.heading_context,
                        "new_heading": c2.heading_context,
                        "diff": self._make_diff(c1.text[:300], c2.text[:300]) if text_changed else None,
                    })
                else:
                    unchanged_count += 1

        # Check for deletions
        for cid, c1 in v1_map.items():
            if cid not in v2_map:
                removed.append({
                    "chunk_id": cid,
                    "title": c1.title,
                    "char_count": c1.char_count,
                    "category": c1.category,
                    "preview": c1.text[:200],
                })

        return {
            "v1": v1_label,
            "v2": v2_label,
            "summary": {
                "v1_chunks": len(v1_chunks),
                "v2_chunks": len(v2_chunks),
                "added_count": len(added),
                "removed_count": len(removed),
                "modified_count": len(modified),
                "unchanged_count": unchanged_count,
                "re_embedding_needed_count": re_embedding_needed_count,
                "cost_saving_retained_embeddings_count": cost_saving_retained_count,
            },
            "added_chunks": added,
            "removed_chunks": removed,
            "modified_chunks": modified,
        }

    # -----------------------------------------------------------------------
    # Section F: Export Manifest
    # -----------------------------------------------------------------------

    def generate_manifest(
        self,
        job_id: str,
        version_label: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate a standard RAG dataset export manifest.json."""
        job = self.manager.get_job(job_id, tenant_id=tenant_id)
        if not job:
            raise ValueError(f"کار با شناسه '{job_id}' یافت نشد.")

        chunks = self.manager.get_chunks(job_id, tenant_id=tenant_id)
        docs = self.manager.get_documents(job_id, tenant_id=tenant_id)
        settings = get_settings()

        sorted_hashes = sorted(c.content_hash or "" for c in chunks)
        aggregate_hash = hashlib.sha256("".join(sorted_hashes).encode("utf-8")).hexdigest()

        total_chars = sum(c.char_count for c in chunks)
        estimated_tokens = int(total_chars / 3.5) if total_chars > 0 else 0

        manifest = {
            "schema_version": "2.0",
            "dataset_id": job_id,
            "version": version_label or "latest",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "job_type": job.job_type.value if hasattr(job.job_type, "value") else str(job.job_type),
                "root_url": job.config.get("root_url") or (job.config.get("urls", [""])[0] if job.config.get("urls") else None),
                "created_at": job.started_at.isoformat() if hasattr(job.started_at, "isoformat") else str(job.started_at or ""),
            },
            "configuration": {
                "chunk_strategy": job.config.get("strategy", "auto"),
                "chunk_size": job.config.get("chunk_size", 1000),
                "overlap": job.config.get("overlap", 150),
                "normalizer": "PersianNormalizer(NFC, ZWNJ)",
            },
            "stats": {
                "total_documents": len(docs),
                "total_chunks": len(chunks),
                "user_edited_chunks": sum(1 for c in chunks if getattr(c, "user_edited", False)),
                "total_characters": total_chars,
                "total_tokens_approx": estimated_tokens,
            },
            "embedding_specification": {
                "model": settings.embedding_model,
                "dimensions": 1536 if "small" in settings.embedding_model else 3072,
                "embedded_chunks_count": sum(1 for c in chunks if c.embedding is not None),
                "provider": "openai",
            },
            "integrity": {
                "aggregate_sha256": aggregate_hash,
                "algorithm": "sha256_over_sorted_chunk_hashes",
            },
            "quality_summary": {
                "flagged_chunks_count": sum(1 for c in chunks if c.quality_flags),
                "empty_documents_count": sum(1 for d in docs if not d.has_content),
            },
            "warnings": [
                "این مانیفست برای احراز اصالت و بازتولیدپذیری پایگاه دانش RAG تهیه شده است."
            ],
        }

        return manifest

    # -----------------------------------------------------------------------
    # Helper Utilities
    # -----------------------------------------------------------------------

    def _make_diff(self, a: str, b: str) -> str:
        """Create a compact unified diff string."""
        diff = difflib.unified_diff(
            a.splitlines(keepends=True),
            b.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
            n=1,
        )
        return "".join(diff)[:2000]


# Singleton instance
dataset_studio = DatasetStudioService()
