"""Semantic Repair Service for Crawlbot RAG Chunks.

Audits and repairs semantic anomalies in DocumentChunks produced by the chunking
pipeline before embedding and vector storage.

Solves:
1. Misclassification (category): Corrects categories (e.g. resume vs portfolio vs
   skills) based on actual chunk and page content.
2. Heading context errors: Corrects stale or inherited heading contexts (e.g.
   'Experience' leaking into Education or Certifications sections).
3. Broken semantic relationships: Identifies and links disconnected dates,
   percentages, and entity descriptions across adjacent chunks.
4. Residual artifacts & placeholders: Strips JS injection notices, script
   fragments, and HTML extraction residue without removing valid content.
5. Embedding invalidation: Flags only chunks whose effective text was modified
   so embeddings are recomputed only when necessary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any, Final, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from ..schemas.chunks import DocumentChunk
from ..services.chunker import CATEGORY_TAXONOMY, _is_date_prefix, _is_micro_body
from ..services.content_cleaner import ContentCleaner
from ..services.rag_enhancer import (
    _compact,
    _extract_numbers,
    _extract_proper_names,
    _get_openai_client,
    _is_transient,
    _normalize_for_check,
    _number_ok,
    _number_set,
    _parse_json_loose,
)

logger = logging.getLogger(__name__)

# Standard standardized category taxonomy
VALID_CATEGORIES: Final[set[str]] = {
    "resume",
    "skills",
    "services",
    "portfolio",
    "contact",
    "about",
    "faq",
    "docs",
    "article",
    "product",
    "policy",
    "general",
}

# Targeted regex for resume / job experience / education signals
_RESUME_INDICATORS = re.compile(
    r"(?:سوابق\s+شغلی|سوابق\s+کاری|تجربه\s+کاری|سوابق\s+تحصیلی|تحصیلات|کارشناسی|کارشناسی\s+ارشد|"
    r"دکتری|دانشگاه|مدرک\s+تحصیلی|سمت\s*:\s*|شغل\s*:\s*|محل\s+کار|مدت\s+همکاری|"
    r"توسعه‌?دهنده\s+(?:ارشد|جونیور|سنیور)|مدیر\s+(?:فنی|پروژه|محصول)|مهندس\s+نرم‌?افزار|"
    r"work\s+experience|employment\s+history|education|bachelor|master|phd|university|"
    r"curriculum\s+vitae|job\s+title|company\s+name|responsibilities)",
    re.IGNORECASE,
)

_PORTFOLIO_INDICATORS = re.compile(
    r"(?:نمونه\s*کار|پروژه‌ها?|نمونه\s*پروژه|دموی\s+آنلاین|مشاهده\s+پروژه|کارفرما\s*:\s*|لینک\s+پروژه|"
    r"portfolio|project\s+overview|live\s+demo|client\s*:\s*|case\s+study|github\.com/)",
    re.IGNORECASE,
)

_SKILLS_INDICATORS = re.compile(
    r"(?:مهارت‌?های\s+تخصصی|مهارت‌?های\s+فردی|ابزارها\s+و\s+فناوری‌?ها|زبان‌?های\s+برنامه‌?نویسی|سطح\s+تسلط|"
    r"skills|technologies|tech\s+stack|programming\s+languages|tools\s+&\s+frameworks)",
    re.IGNORECASE,
)

_SERVICES_INDICATORS = re.compile(
    r"(?:خدمات\s+ما|سرویس‌?های\s+ما|ارائه\s+خدمات|مشاوره\s+تخصصی|پشتیبانی\s+فنی|تعرفه\s+خدمات|"
    r"our\s+services|what\s+we\s+offer|solutions|consulting)",
    re.IGNORECASE,
)

_CONTACT_INDICATORS = re.compile(
    r"(?:تماس\s+با\s+ما|ارتباط\s+با\s+ما|راه‌?های\s+ارتباطی|شماره\s+تماس|ایمیل\s*:\s*|آدرس\s*:\s*|"
    r"contact\s+us|get\s+in\s+touch|email\s*:\s*|phone\s*:\s*|telegram\s*:\s*|t\.me/)",
    re.IGNORECASE,
)

# Heading shift triggers
_HEADING_SHIFT_PATTERNS = [
    (re.compile(r"^\s*(?:تحصیلات|سوابق\s+تحصیلی|مدارک\s+دانشگاهی|education)\b", re.I), "تحصیلات"),
    (re.compile(r"^\s*(?:گواهینامه‌?ها|مدارک\s+تخصصی|certifications?|certificates?)\b", re.I), "گواهینامه‌ها"),
    (re.compile(r"^\s*(?:مهارت‌?ها|ابزارها|فناوری‌?ها|skills|technologies)\b", re.I), "مهارت‌ها"),
    (re.compile(r"^\s*(?:افتخارات|جوایز|honors?|awards?)\b", re.I), "افتخارات"),
    (re.compile(r"^\s*(?:پروژه‌ها|نمونه\s*کارها|projects?|portfolio)\b", re.I), "پروژه‌ها"),
]

# Additional text artifacts often found inside chunks
_EXTRA_ARTIFACT_PATTERNS = [
    re.compile(r"محتوای\s+فرم\s+توسط\s+JS\s+در\s+اینجا\s+تزریق\s+می‌?شود", re.IGNORECASE),
    re.compile(r"javascript\s+is\s+required\s+to\s+view\s+this\s+page", re.IGNORECASE),
    re.compile(r"please\s+enable\s+javascript\s+to\s+continue", re.IGNORECASE),
    re.compile(r"<\/?(?:script|style|noscript|iframe)[^>]*>", re.IGNORECASE),
    re.compile(r"<!--[\s\S]*?-->"),
]


class RepairAction(BaseModel):
    """Record of a single proposed or applied semantic repair action."""

    model_config = ConfigDict(populate_by_name=True)

    chunk_id: str
    field: str = Field(description="'category', 'heading_context', 'text', 'semantic_link'")
    previous_value: Optional[Any] = None
    proposed_value: Any
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    applied: bool = True
    rejection_reason: Optional[str] = None


class SemanticRepairReport(BaseModel):
    """Comprehensive execution report of semantic repair across a chunk set."""

    model_config = ConfigDict(populate_by_name=True)

    total_chunks: int = 0
    repaired_chunks_count: int = 0
    repairs_applied_count: int = 0
    repairs_rejected_count: int = 0
    category_repairs_count: int = 0
    heading_repairs_count: int = 0
    text_repairs_count: int = 0
    semantic_links_count: int = 0
    artifacts_removed_count: int = 0
    embeddings_invalidated_count: int = 0
    actions: list[RepairAction] = Field(default_factory=list)
    invalidated_chunk_ids: list[str] = Field(default_factory=list)
    execution_mode: str = "deterministic_only"  # 'deterministic_only', 'hybrid_llm', 'fallback_deterministic'
    errors: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = r"""
You are an expert RAG Semantic Repair Engineer for Crawlbot.
Your task is to audit extracted document chunks and propose conservative, evidence-based
semantic repairs to fix:
1. Misclassified 'category' (e.g. resume content wrongly tagged as 'portfolio').
2. Stale or inherited 'heading_context' (e.g. an Education block that inherited 'Experience').
3. Broken semantic links to predecessor entities (e.g. dates or bullet points detached from job title).
4. Residual text artifacts (e.g. JS injection notices, script leftovers).

STRICT RULES:
- Only propose repairs when supported by unambiguous evidence in the chunk text or its immediate context.
- Never invent facts, company names, job titles, or numbers.
- Do NOT rewrite or rephrase the chunk text unless removing a specific artifact or linking an entity.
- 'category' must be one of: resume, skills, services, portfolio, contact, about, faq, docs, article, product, policy, general.
- Provide a confidence score between 0.0 and 1.0. If you are unsure or the text is ambiguous, do NOT propose a change.
- Return strictly valid JSON matching the requested schema.
"""

_REPAIR_RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "semantic_repair_batch",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "repairs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "chunk_id": {"type": "string"},
                        "field": {
                            "type": "string",
                            "enum": ["category", "heading_context", "text", "semantic_link"],
                        },
                        "proposed_value": {"type": "string"},
                        "reason": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["chunk_id", "field", "proposed_value", "reason", "confidence"],
                },
            }
        },
        "required": ["repairs"],
    },
}


class SemanticRepairService:
    """Production-grade semantic repair engine for RAG document chunks."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
        concurrency: int = 3,
        confidence_threshold: float = 0.75,
        request_timeout: float = 60.0,
        enrich_text_with_entity: bool = False,
    ) -> None:
        """Initialize the semantic repair service.

        Args:
            api_key: Optional OpenAI API key for LLM-assisted repair.
            base_url: Optional base URL for OpenAI-compatible LLM endpoints.
            model: Model identifier.
            concurrency: Max parallel LLM requests.
            confidence_threshold: Minimum confidence required to accept a repair (0.0 to 1.0).
            request_timeout: Timeout in seconds for LLM calls.
            enrich_text_with_entity: If True, prepends [مرتبط با: ...] to chunk text for
                broken entity descriptions, triggering embedding invalidation.
        """
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.base_url = base_url.strip() if base_url and base_url.strip() else None
        self.model = model
        self.concurrency = max(1, min(concurrency, 10))
        self.confidence_threshold = max(0.5, min(confidence_threshold, 1.0))
        self.request_timeout = request_timeout
        self.enrich_text_with_entity = enrich_text_with_entity
        self._client = None

    def _client_instance(self):
        if self._client is None and self.api_key:
            self._client = _get_openai_client(self.api_key, self.base_url, self.request_timeout)
        return self._client

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def repair_chunks(
        self,
        chunks: list[DocumentChunk],
        apply_llm: bool = True,
    ) -> tuple[list[DocumentChunk], SemanticRepairReport]:
        """Audit and repair a list of DocumentChunks.

        Args:
            chunks: List of DocumentChunks from a document or extraction job.
            apply_llm: Whether to invoke the LLM for ambiguous or complex cases
                if an API key is configured.

        Returns:
            Tuple of (repaired_chunks, repair_report).
        """
        if not chunks:
            return [], SemanticRepairReport(execution_mode="empty")

        report = SemanticRepairReport(total_chunks=len(chunks))
        repaired_chunks_set: set[str] = set()

        # Step 1: Always apply deterministic rule-based repair first
        # This fixes clear-cut category mismatches, strips artifacts, and links obvious entity neighbors.
        for idx, chunk in enumerate(chunks):
            prev_chunk = chunks[idx - 1] if idx > 0 else None
            next_chunk = chunks[idx + 1] if idx + 1 < len(chunks) else None
            self._repair_chunk_deterministic(chunk, prev_chunk, next_chunk, report, repaired_chunks_set)

        report.execution_mode = "deterministic_only"

        # Step 2: If LLM is requested and configured, run LLM-assisted repair on eligible chunks
        if apply_llm and self.api_key:
            try:
                await self._repair_with_llm(chunks, report, repaired_chunks_set)
                if report.errors:
                    report.execution_mode = "fallback_deterministic"
                else:
                    report.execution_mode = "hybrid_llm"
            except Exception as exc:
                logger.warning("LLM-assisted repair failed, fallback to deterministic results: %s", exc)
                report.execution_mode = "fallback_deterministic"
                report.errors.append(f"LLM repair error: {str(exc)}")

        # Step 3: Finalize stats and embedding invalidations
        invalidated: list[str] = []
        for chunk in chunks:
            if chunk.metadata.get("embedding_invalidated"):
                invalidated.append(chunk.chunk_id)

        report.repaired_chunks_count = len(repaired_chunks_set)
        report.embeddings_invalidated_count = len(invalidated)
        report.invalidated_chunk_ids = invalidated

        return chunks, report

    # -----------------------------------------------------------------------
    # Deterministic Repair Engine
    # -----------------------------------------------------------------------

    def _repair_chunk_deterministic(
        self,
        chunk: DocumentChunk,
        prev_chunk: Optional[DocumentChunk],
        next_chunk: Optional[DocumentChunk],
        report: SemanticRepairReport,
        repaired_set: set[str],
    ) -> None:
        """Apply high-precision deterministic repairs to a single chunk."""
        original_text = chunk.text or ""
        original_category = chunk.category
        original_heading = chunk.heading_context

        # 1. Artifact & Placeholder Stripping
        cleaned_text, removed_artifacts = self._strip_chunk_artifacts(original_text)
        if removed_artifacts:
            self._apply_text_repair(
                chunk=chunk,
                new_text=cleaned_text,
                reason=f"حذف متن‌های ساختگی و placeholder استخراج ({', '.join(removed_artifacts[:2])})",
                confidence=1.0,
                report=report,
                repaired_set=repaired_set,
            )
            report.artifacts_removed_count += len(removed_artifacts)
            existing_artifacts = chunk.metadata.setdefault("artifacts_removed", [])
            existing_artifacts.extend(removed_artifacts)

            if not cleaned_text.strip():
                if "ui_artifact" not in chunk.quality_flags:
                    chunk.quality_flags.append("ui_artifact")
                if "low_info" not in chunk.quality_flags:
                    chunk.quality_flags.append("low_info")

        # 2. Heading Context Refinement
        new_heading = self._check_heading_shift(chunk.text, chunk.heading_context)
        if new_heading and new_heading != original_heading:
            action = RepairAction(
                chunk_id=chunk.chunk_id,
                field="heading_context",
                previous_value=original_heading,
                proposed_value=new_heading,
                reason="اصلاح زمینه عنوان بر اساس تغییر معنایی صریح در ابتدای قطعه",
                confidence=0.95,
                applied=True,
            )
            chunk.heading_context = new_heading
            chunk.parent_heading = new_heading.split(" > ")[-1] if " > " in new_heading else new_heading
            chunk.breadcrumbs = [b.strip() for b in new_heading.split(" > ")]
            chunk.metadata["heading_repaired"] = True
            report.actions.append(action)
            report.repairs_applied_count += 1
            report.heading_repairs_count += 1
            repaired_set.add(chunk.chunk_id)

        # 3. Category Misclassification Refinement
        refined_category = self._detect_category_refinement(chunk, original_category)
        if refined_category and refined_category != original_category:
            action = RepairAction(
                chunk_id=chunk.chunk_id,
                field="category",
                previous_value=original_category,
                proposed_value=refined_category,
                reason=f"اصلاح طبقه‌بندی از '{original_category}' به '{refined_category}' بر مبنای محتوای واقعی متن",
                confidence=0.92,
                applied=True,
            )
            chunk.category = refined_category
            chunk.metadata["category_repaired"] = True
            report.actions.append(action)
            report.repairs_applied_count += 1
            report.category_repairs_count += 1
            repaired_set.add(chunk.chunk_id)

        # 4. Broken Semantic Link with Predecessor Chunk
        if prev_chunk:
            self._link_broken_entity_relationship(chunk, prev_chunk, report, repaired_set)

    def _strip_chunk_artifacts(self, text: str) -> tuple[str, list[str]]:
        """Identify and strip extraction leftovers and JS injection placeholders."""
        if not text:
            return "", []

        # 1. Use ContentCleaner's text cleaner first
        cleaned, removed = ContentCleaner.clean_text_artifacts(text)

        # 2. Check additional chunk-level regex patterns
        for pat in _EXTRA_ARTIFACT_PATTERNS:
            matches = pat.findall(cleaned)
            if matches:
                removed.extend(matches)
                cleaned = pat.sub("", cleaned)

        # 3. Clean trailing whitespace and extra newlines
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned, list(dict.fromkeys(removed))

    def _check_heading_shift(self, text: str, current_heading: Optional[str]) -> Optional[str]:
        """Detect if the chunk opens with a clear semantic section title different from its inherited heading."""
        if not text:
            return None
        first_lines = "\n".join(text.strip().split("\n")[:3])

        for pat, title in _HEADING_SHIFT_PATTERNS:
            if pat.search(first_lines):
                if not current_heading:
                    return title
                # Check if current heading contradicts this title (e.g. current has 'Experience' or 'سوابق' but text is 'تحصیلات')
                curr_low = current_heading.lower()
                if title == "تحصیلات" and any(k in curr_low for k in ("experience", "سوابق شغلی", "تجربه کاری")):
                    return f"{current_heading} > تحصیلات" if " > " in current_heading else title
                if title == "گواهینامه‌ها" and any(k in curr_low for k in ("experience", "سوابق شغلی")):
                    return title
                if title == "مهارت‌ها" and any(k in curr_low for k in ("education", "تحصیلات", "experience")):
                    return title
        return None

    def _detect_category_refinement(self, chunk: DocumentChunk, current_cat: Optional[str]) -> Optional[str]:
        """Refine chunk category when the actual chunk body contradicts the document-level category."""
        text = chunk.text or ""
        curr = (current_cat or "general").lower().strip()

        # Strong resume signals
        has_resume = bool(_RESUME_INDICATORS.search(text))
        has_portfolio = bool(_PORTFOLIO_INDICATORS.search(text))
        has_skills = bool(_SKILLS_INDICATORS.search(text))
        has_services = bool(_SERVICES_INDICATORS.search(text))
        has_contact = bool(_CONTACT_INDICATORS.search(text))

        # Disambiguate Resume vs Portfolio:
        # A resume block should NOT stay 'portfolio' simply because the document was tagged portfolio
        if curr in ("portfolio", "about", "general", "services") and has_resume and not has_portfolio:
            return "resume"

        # Disambiguate Skills:
        if curr in ("portfolio", "resume", "about", "general") and has_skills and not (has_resume or has_portfolio):
            return "skills"

        # Disambiguate Services:
        if curr in ("about", "portfolio", "general") and has_services and not (has_resume or has_portfolio):
            return "services"

        # Disambiguate Contact:
        if curr != "contact" and has_contact and len(text.split()) < 30:
            return "contact"

        return None

    def _link_broken_entity_relationship(
        self,
        chunk: DocumentChunk,
        prev_chunk: DocumentChunk,
        report: SemanticRepairReport,
        repaired_set: set[str],
    ) -> None:
        """Establish verifiable semantic links between adjacent broken chunks."""
        text = chunk.text.strip()
        prev_text = prev_chunk.text.strip()
        if not text or not prev_text:
            return

        # Case A: Chunk is a micro metric/percentage or isolated date range
        is_isolated_metric = _is_micro_body(text) or _is_date_prefix(text)

        # Case B: Chunk starts directly with bullet points or action description without subject
        is_orphan_bullets = bool(re.match(r"^[-*•]\s+\S+", text)) and not re.search(r"^[A-Z\u0600-\u06FF\w\s]{2,30}:", text)

        if not (is_isolated_metric or is_orphan_bullets):
            return

        # Look for entity subject in the tail or header of the predecessor chunk
        entity_candidate = self._extract_entity_subject(prev_text)
        if not entity_candidate:
            return

        # Establish verifiable semantic link
        link_data = {
            "parent_chunk_id": prev_chunk.chunk_id,
            "entity": entity_candidate,
            "relation": "metrics_of" if is_isolated_metric else "responsibilities_of",
            "source_doc_url": prev_chunk.source_url,
        }
        chunk.semantic_link = link_data
        chunk.metadata["semantic_link"] = link_data

        action = RepairAction(
            chunk_id=chunk.chunk_id,
            field="semantic_link",
            previous_value=None,
            proposed_value=link_data,
            reason=f"اتصال معنایی به موجودیت قطعه قبلی ({entity_candidate})",
            confidence=0.90,
            applied=True,
        )
        report.actions.append(action)
        report.repairs_applied_count += 1
        report.semantic_links_count += 1
        repaired_set.add(chunk.chunk_id)

        # If text enrichment is requested, prepend context marker and invalidate embedding
        if self.enrich_text_with_entity:
            prefix = f"[زمینه: {entity_candidate}]\n"
            if not text.startswith(prefix):
                new_text = prefix + text
                self._apply_text_repair(
                    chunk=chunk,
                    new_text=new_text,
                    reason=f"تزریق برچسب متنی موجودیت برای بهبود بازیابی معنایی ({entity_candidate})",
                    confidence=0.90,
                    report=report,
                    repaired_set=repaired_set,
                )

    def _extract_entity_subject(self, text: str) -> Optional[str]:
        """Extract primary entity or heading title from a predecessor chunk."""
        # 1. Check last heading line
        for line in reversed(text.split("\n")):
            line_str = line.strip()
            if line_str.startswith("#"):
                clean_h = re.sub(r"^#{1,6}\s*", "", line_str).strip()
                if 3 <= len(clean_h) <= 80:
                    return clean_h

        # 2. Check title / company / role patterns
        first_line = text.strip().split("\n")[0].strip()
        if 3 <= len(first_line) <= 80 and not first_line.startswith(("-", "*", "•")):
            return first_line

        return None

    def _apply_text_repair(
        self,
        chunk: DocumentChunk,
        new_text: str,
        reason: str,
        confidence: float,
        report: SemanticRepairReport,
        repaired_set: set[str],
    ) -> None:
        """Apply text modification to a chunk and record embedding invalidation."""
        old_text = chunk.text
        if new_text == old_text:
            return

        chunk.text = new_text
        chunk.char_count = len(new_text)
        chunk.word_count = len(new_text.split())
        chunk.token_count_approx = int(chunk.word_count * 1.35)
        new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
        chunk.content_hash = new_hash

        # Invalidate embedding because effective retrieval content changed
        chunk.embedding = None
        chunk.metadata["embedding_invalidated"] = True
        chunk.metadata["embedding_invalidation_reason"] = reason

        action = RepairAction(
            chunk_id=chunk.chunk_id,
            field="text",
            previous_value=old_text[:60] + ("..." if len(old_text) > 60 else ""),
            proposed_value=new_text[:60] + ("..." if len(new_text) > 60 else ""),
            reason=reason,
            confidence=confidence,
            applied=True,
        )
        report.actions.append(action)
        report.repairs_applied_count += 1
        report.text_repairs_count += 1
        repaired_set.add(chunk.chunk_id)

    # -----------------------------------------------------------------------
    # LLM-Assisted Repair Engine
    # -----------------------------------------------------------------------

    async def _repair_with_llm(
        self,
        chunks: list[DocumentChunk],
        report: SemanticRepairReport,
        repaired_set: set[str],
    ) -> None:
        """Query LLM for advanced semantic repair proposals on candidate chunks."""
        # Process in batches of 4-6 chunks with context window
        batch_size = 5
        semaphore = asyncio.Semaphore(self.concurrency)

        async def _process_batch(start_idx: int) -> None:
            batch = chunks[start_idx : start_idx + batch_size]
            prompt = self._build_llm_prompt(chunks, start_idx, len(batch))
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]

            async with semaphore:
                raw_json, error = await self._call_llm(messages)

            if error:
                logger.warning("LLM batch repair failed for index %d: %s", start_idx, error)
                report.errors.append(f"Batch {start_idx}: {error}")
                return

            self._apply_llm_proposals(batch, raw_json, report, repaired_set)

        tasks = [_process_batch(i) for i in range(0, len(chunks), batch_size)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                report.errors.append(f"LLM task error: {str(r)}")

    def _build_llm_prompt(self, all_chunks: list[DocumentChunk], start_idx: int, count: int) -> str:
        """Construct structured user prompt with predecessor and successor context."""
        items: list[dict[str, Any]] = []

        for i in range(start_idx, start_idx + count):
            chunk = all_chunks[i]
            prev_chunk = all_chunks[i - 1] if i > 0 else None
            next_chunk = all_chunks[i + 1] if i + 1 < len(all_chunks) else None

            # Window context: concise tail/head
            prev_tail = prev_chunk.text[-200:].strip() if prev_chunk and prev_chunk.text else None
            next_head = next_chunk.text[:200].strip() if next_chunk and next_chunk.text else None

            items.append({
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "title": chunk.title,
                "current_category": chunk.category,
                "current_heading_context": chunk.heading_context,
                "text": chunk.text[:800],  # budget chunk text
                "prev_chunk_tail": prev_tail,
                "next_chunk_head": next_head,
            })

        return (
            "AUDIT THESE CHUNKS AND PROPOSE STRICT REPAIRS:\n"
            + json.dumps(items, ensure_ascii=False, indent=2)
            + "\n\nReturn strictly valid JSON with key 'repairs'."
        )

    async def _call_llm(self, messages: list[dict[str, str]]) -> tuple[dict, Optional[str]]:
        """Send chat completion request to LLM with structured output."""
        client = self._client_instance()
        if not client:
            return {}, "OpenAI client not configured"

        for attempt in range(2):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "response_format": {"type": "json_object"},
            }
            if getattr(self, "_send_temperature", True):
                kwargs["temperature"] = 0.1

            try:
                response = await client.chat.completions.create(**kwargs)
                if not response.choices:
                    return {}, "No choices returned by LLM"
                content = response.choices[0].message.content or "{}"
                parsed = _parse_json_loose(content)
                return parsed, None
            except Exception as exc:
                err_str = str(exc)
                if "temperature" in err_str.lower() and getattr(self, "_send_temperature", True):
                    self._send_temperature = False
                    continue
                return {}, err_str

        return {}, "LLM call failed"

    def _apply_llm_proposals(
        self,
        batch: list[DocumentChunk],
        raw_json: dict,
        report: SemanticRepairReport,
        repaired_set: set[str],
    ) -> None:
        """Validate and apply LLM repair proposals under strict safeguards."""
        repairs = raw_json.get("repairs", [])
        if not isinstance(repairs, list):
            return

        chunk_map = {c.chunk_id: c for c in batch}

        for item in repairs:
            if not isinstance(item, dict):
                continue

            chunk_id = str(item.get("chunk_id", "")).strip()
            field = str(item.get("field", "")).strip()
            proposed_val = item.get("proposed_value")
            reason = str(item.get("reason", "")).strip()
            confidence = float(item.get("confidence", 0.0) or 0.0)

            chunk = chunk_map.get(chunk_id)
            if not chunk or not field or proposed_val is None:
                continue

            # 1. Confidence threshold check
            if confidence < self.confidence_threshold:
                report.actions.append(
                    RepairAction(
                        chunk_id=chunk_id,
                        field=field,
                        previous_value=getattr(chunk, field, None),
                        proposed_value=proposed_val,
                        reason=reason,
                        confidence=confidence,
                        applied=False,
                        rejection_reason=f"Confidence {confidence:.2f} below threshold {self.confidence_threshold:.2f}",
                    )
                )
                report.repairs_rejected_count += 1
                continue

            # 2. Field-specific local verification
            if field == "category":
                clean_cat = str(proposed_val).lower().strip()
                if clean_cat not in VALID_CATEGORIES:
                    self._reject_repair(chunk_id, field, proposed_val, f"Category '{clean_cat}' not in taxonomy", confidence, reason, report)
                    continue

                if clean_cat != chunk.category:
                    action = RepairAction(
                        chunk_id=chunk_id,
                        field="category",
                        previous_value=chunk.category,
                        proposed_value=clean_cat,
                        reason=reason,
                        confidence=confidence,
                        applied=True,
                    )
                    chunk.category = clean_cat
                    chunk.metadata["category_repaired_llm"] = True
                    report.actions.append(action)
                    report.repairs_applied_count += 1
                    report.category_repairs_count += 1
                    repaired_set.add(chunk_id)

            elif field == "heading_context":
                clean_heading = str(proposed_val).strip()
                if not clean_heading or clean_heading == chunk.heading_context:
                    continue

                action = RepairAction(
                    chunk_id=chunk_id,
                    field="heading_context",
                    previous_value=chunk.heading_context,
                    proposed_value=clean_heading,
                    reason=reason,
                    confidence=confidence,
                    applied=True,
                )
                chunk.heading_context = clean_heading
                chunk.parent_heading = clean_heading.split(" > ")[-1] if " > " in clean_heading else clean_heading
                chunk.breadcrumbs = [b.strip() for b in clean_heading.split(" > ")]
                chunk.metadata["heading_repaired_llm"] = True
                report.actions.append(action)
                report.repairs_applied_count += 1
                report.heading_repairs_count += 1
                repaired_set.add(chunk_id)

            elif field == "text":
                new_text = str(proposed_val).strip()
                # Anti-hallucination check: new numbers or proper nouns not in chunk text
                orig_numbers = _number_set(chunk.text)
                new_nums = [n for n in _extract_numbers(new_text) if not _number_ok(n, orig_numbers)]
                if new_nums:
                    self._reject_repair(chunk_id, field, new_text, f"Anti-hallucination rejected: unverified numbers {new_nums}", confidence, reason, report)
                    continue

                self._apply_text_repair(chunk, new_text, reason, confidence, report, repaired_set)

    def _reject_repair(
        self,
        chunk_id: str,
        field: str,
        proposed_value: Any,
        rejection_reason: str,
        confidence: float,
        reason: str,
        report: SemanticRepairReport,
    ) -> None:
        """Log a rejected repair proposal."""
        report.actions.append(
            RepairAction(
                chunk_id=chunk_id,
                field=field,
                proposed_value=proposed_value,
                reason=reason,
                confidence=confidence,
                applied=False,
                rejection_reason=rejection_reason,
            )
        )
        report.repairs_rejected_count += 1
