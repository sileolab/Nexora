"""Text Chunking Service for Crawlbot RAG Data Intelligence.

Splits extracted document content into structured, overlapping chunks suitable
for vector embedding, semantic retrieval, and RAG ingestion.

Features:
- ``auto``: Deterministically analyzes document properties (headings, markdown quality,
  paragraph distribution, page classification, language) to select the optimal strategy.
- ``semantic_heading``: Hierarchical splitting at Markdown headings (H1-H6), preserving
  full parent-child context stacks, attaching dates/subtitles to child items, coalescing
  micro leaf values (percentages, credentials), and preventing orphan headings.
- ``paragraph``: Split on paragraph boundaries (double newlines) with sub-splitting of oversized paragraphs.
- ``sentence``: Multilingual sentence-boundary splitting protecting decimals (3.14), URLs, and abbreviations.
- ``fixed_size``: Character window splitting conscious of word boundaries and Persian half-spaces (\\u200c).
- Standardized Category Taxonomy: Maps categories to clean, consistent slugs (never "unknown").
- Provenance-Preserving Deduplication: Identifies duplicate chunks across documents, merging
  source URLs into alternate_sources to eliminate index bloat while maintaining full traceability.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Final, Optional
from urllib.parse import urlsplit

from ..schemas.chunks import ChunkingResult, ChunkingStrategy, DocumentChunk
from ..schemas.documents import ExtractedDocument
from .normalizer import PersianNormalizer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns for multilingual protection and normalization
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.IGNORECASE)
_DECIMAL_RE = re.compile(r"\b\d+(?:\.\d+)+\b")
_ABBR_RE = re.compile(
    r"\b(?:e\.g\.|i\.e\.|etc\.|vs\.|al\.|Dr\.|Mr\.|Mrs\.|Ms\.|Prof\.|approx\.|dept\.|est\.|fig\.|inc\.|ltd\.|no\.)",
    re.IGNORECASE,
)
_PERSIAN_ABBR_RE = re.compile(r"(?:\b|\s)(?:ص|ش|ق|م|هـ|د)\.\s*")

_UI_NOISE_RE = re.compile(
    r"(?:استفاده از کوکی|پذیرش کوکی|کوکی‌ها|cookie policy|use cookies|accept cookies|"
    r"تمامی حقوق محفوظ است|کلیه حقوق محفوظ|all rights reserved|"
    r"ورود / ثبت‌نام|ورود یا عضویت|رمز عبور خود را فراموش|log in / sign up|sign in to your account|"
    r"صفحه نخست >|خانه >|home >)",
    re.IGNORECASE,
)

# Pattern detecting isolated micro-body content (e.g. percentages, years, dates, short status)
_MICRO_BODY_RE = re.compile(
    r"^(?:\d{1,3}[%٪]|\d{4}|[۰-۹]{4}|[۰-۹]{4}\s*[-—–]\s*(?:[۰-۹]{4}|تاکنون|اکنون)|\d{4}\s*[-—–]\s*(?:\d{4}|present|current)|\$?\d+(?:\.\d+)?|yes|no|بله|خیر|true|false)$",
    re.IGNORECASE,
)

_DATE_RANGE_RE = re.compile(
    r"^(?:\d{4}|[۰-۹]{4})(?:\s*[-—–/]\s*(?:\d{4}|[۰-۹]{4}|تاکنون|اکنون|present|current))?$",
    re.IGNORECASE,
)


def _is_date_prefix(text: str) -> bool:
    """Return True if text is a single date, year, or date range."""
    clean = text.strip()
    if not clean:
        return False
    if _DATE_RANGE_RE.match(clean):
        return True
    words = clean.split()
    if len(words) <= 3 and any(re.search(r"\b(19\d\d|20\d\d|[1۱][34][0-9]{2})\b", w) for w in words):
        return True
    return False

# Standardized Category Taxonomy Mapping
CATEGORY_TAXONOMY: Final[list[tuple[re.Pattern, str]]] = [
    (re.compile(r"resume|cv|curriculum|سوابق|رزومه|experience|career|job|شغل|تحصیلات", re.I), "resume"),
    (re.compile(r"skills?|technologies|ابزار|فناوری|مهارت|stack|languages?|زبان", re.I), "skills"),
    (re.compile(r"services?|solutions?|خدمات|سرویس|پشتیبانی", re.I), "services"),
    (re.compile(r"portfolio|projects?|works?|نمونه-کار|نمونه‌کار|پروژه", re.I), "portfolio"),
    (re.compile(r"contact|تماس|ارتباط|فرم تماس|reach", re.I), "contact"),
    (re.compile(r"about|درباره|بیو|bio|profile|معرفی", re.I), "about"),
    (re.compile(r"faq|سوالات|پرسش|qna|help", re.I), "faq"),
    (re.compile(r"docs?|documentation|guide|راهنما|مستند|api", re.I), "docs"),
    (re.compile(r"articles?|blog|posts?|مقاله|وبلاگ|news|اخبار", re.I), "article"),
    (re.compile(r"products?|pricing|قیمت|محصول|shop|store", re.I), "product"),
    (re.compile(r"policy|terms|privacy|قوانین|حریم", re.I), "policy"),
]


def resolve_chunk_category(
    requested_category: Optional[str],
    heading_ctx: Optional[str],
    doc_page_type: Optional[str],
    doc_title: Optional[str] = None,
    source_url: Optional[str] = None,
) -> str:
    """Map page type and heading context to a standardized, clean taxonomy slug (never 'unknown')."""
    # 1. User-requested category has highest precedence
    if requested_category and requested_category.strip().lower() not in ("unknown", "none", "null", ""):
        return requested_category.strip().lower()

    # 2. Check heading context keywords
    if heading_ctx:
        for pat, slug in CATEGORY_TAXONOMY:
            if pat.search(heading_ctx):
                return slug

    # 3. Check document page type
    if doc_page_type and doc_page_type.lower() not in ("unknown", "none", "null", "", "general"):
        p = doc_page_type.lower().strip()
        for pat, slug in CATEGORY_TAXONOMY:
            if pat.search(p):
                return slug
        return p

    # 4. Check URL path
    if source_url:
        try:
            path = urlsplit(source_url).path
            for pat, slug in CATEGORY_TAXONOMY:
                if pat.search(path):
                    return slug
        except Exception:
            pass

    # 5. Check Document Title
    if doc_title:
        for pat, slug in CATEGORY_TAXONOMY:
            if pat.search(doc_title):
                return slug

    return "general"


def _is_micro_body(text: str) -> bool:
    """Return True if text is a single metric, percentage, date, or tiny label (< 3 words and <= 25 chars)."""
    clean = text.strip()
    if not clean:
        return True
    if _MICRO_BODY_RE.match(clean):
        return True
    words = clean.split()
    return len(words) <= 2 and len(clean) <= 22


def detect_chunk_quality_flags(text: str, heading_ctx: Optional[str] = None) -> list[str]:
    """Detect non-destructive quality flags such as UI noise, boilerplate, or low-information content."""
    flags: list[str] = []
    clean = text.strip()
    words = clean.split()

    # Preserve structured contact details, links, tables, or code blocks from being mislabeled low_info
    has_contact = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+|t\.me/|tel:|mailto:|telegram:|email:", clean, re.I))
    has_code_or_table = "|" in clean or "```" in clean or "`" in clean

    if (len(words) < 5 or len(clean) < 25) and not (has_contact or has_code_or_table):
        flags.append("low_info")

    if _UI_NOISE_RE.search(clean):
        flags.append("ui_noise")
        flags.append("boilerplate")
    elif heading_ctx and any(k in heading_ctx.lower() for k in ["footer", "فوتر", "منو", "navigation", "nav"]):
        flags.append("ui_noise")

    return flags


# ---------------------------------------------------------------------------
# Helper – chunk ID generation
# ---------------------------------------------------------------------------

def _make_chunk_id(source_url: str, chunk_index: int, content_hash: Optional[str] = None) -> str:
    """Generate a stable, unique chunk identifier incorporating URL, index, and content hash."""
    raw = f"{source_url}::{chunk_index}"
    if content_hash:
        raw += f"::{content_hash[:8]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Protection helpers for sentence splitting
# ---------------------------------------------------------------------------

def _protect_text_for_sentence_split(text: str) -> tuple[str, dict[str, str]]:
    """Mask URLs, decimals, and abbreviations so sentence splitting never breaks them."""
    placeholders: dict[str, str] = {}
    counter = 0

    def repl(m: re.Match) -> str:
        nonlocal counter
        token = f"«__PRTK_{counter}__»"
        placeholders[token] = m.group(0)
        counter += 1
        return token

    text = _URL_RE.sub(repl, text)
    text = _DECIMAL_RE.sub(repl, text)
    text = _ABBR_RE.sub(repl, text)
    text = _PERSIAN_ABBR_RE.sub(repl, text)

    return text, placeholders


def _restore_protected_text(text: str, placeholders: dict[str, str]) -> str:
    """Restore masked tokens back to their original text."""
    for token, orig in placeholders.items():
        text = text.replace(token, orig)
    return text


def _extract_sentences(text: str) -> list[str]:
    """Split text into sentences while protecting decimals, abbreviations, and URLs."""
    if not text or not text.strip():
        return []
    protected, placeholders = _protect_text_for_sentence_split(text)
    pattern = re.compile(r"(?<=[.!?؟])\s+")
    parts = [p.strip() for p in pattern.split(protected) if p.strip()]
    if not parts:
        parts = [protected.strip()]
    return [_restore_protected_text(p, placeholders) for p in parts if p.strip()]


def _extract_overlap_tail(text: str, overlap: int) -> str:
    """Extract a clean tail of text for chunk overlap, preserving word boundaries."""
    if not text or overlap <= 0:
        return ""
    clean = text.strip()
    if len(clean) <= overlap:
        return clean
    tail = clean[-overlap:]
    space_idx = tail.find(" ")
    if space_idx != -1 and space_idx < len(tail) // 2:
        tail = tail[space_idx + 1:].strip()
    tail = tail.lstrip("\u200c")
    return tail


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

def _merge_segments(
    segments: list[str],
    chunk_size: int,
    overlap: int,
    is_sentence_level: bool = False,
) -> list[str]:
    """Merge short segments into chunks of approximately ``chunk_size`` characters."""
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for raw_seg in segments:
        seg = raw_seg.strip()
        if not seg:
            continue
        seg_len = len(seg)

        # If a single segment is longer than chunk_size, sub-split it
        if seg_len > chunk_size:
            if current_parts:
                chunk_text = "\n\n".join(current_parts).strip()
                if chunk_text:
                    chunks.append(chunk_text)
                current_parts = []
                current_len = 0

            is_code_or_table = seg.startswith("```") or (seg.startswith("|") and "\n|" in seg)
            if is_sentence_level or is_code_or_table:
                chunks.extend(_split_fixed(seg, chunk_size, overlap))
            else:
                sub_chunks = _split_sentence(seg, chunk_size, overlap)
                for sc in sub_chunks:
                    if len(sc) > chunk_size:
                        chunks.extend(_split_fixed(sc, chunk_size, overlap))
                    else:
                        chunks.append(sc)
            continue

        if current_len + seg_len + (2 if current_parts else 0) > chunk_size and current_parts:
            chunk_text = "\n\n".join(current_parts).strip()
            if chunk_text:
                chunks.append(chunk_text)

            if overlap > 0 and current_parts:
                prev_text = "\n\n".join(current_parts)
                overlap_text = _extract_overlap_tail(prev_text, overlap)
                if overlap_text:
                    current_parts = [overlap_text, seg]
                    current_len = len(overlap_text) + seg_len + 2
                else:
                    current_parts = [seg]
                    current_len = seg_len
            else:
                current_parts = [seg]
                current_len = seg_len
        else:
            current_parts.append(seg)
            current_len += seg_len + (2 if len(current_parts) > 1 else 0)

    if current_parts:
        final_chunk = "\n\n".join(current_parts).strip()
        if final_chunk:
            chunks.append(final_chunk)

    return chunks


def _split_paragraph(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text by paragraph boundaries (double newlines)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []
    return _merge_segments(paragraphs, chunk_size, overlap, is_sentence_level=False)


def _split_sentence(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into sentences then group them into chunks."""
    sentences = _extract_sentences(text)
    if not sentences:
        return []
    return _merge_segments(sentences, chunk_size, overlap, is_sentence_level=True)


def _split_fixed(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into fixed-size character windows with overlap."""
    if not text:
        return []

    text_len = len(text)
    if text_len <= chunk_size:
        return [text.strip()] if text.strip() else []

    chunks: list[str] = []
    step = max(1, chunk_size - overlap)
    start = 0

    while start < text_len:
        target_end = min(text_len, start + chunk_size)

        if target_end >= text_len:
            actual_end = text_len
        else:
            slack = max(10, int(chunk_size * 0.15))
            search_start = max(start + 1, target_end - slack)
            candidate = -1

            p_idx = text.rfind("\n\n", search_start, target_end)
            if p_idx != -1:
                candidate = p_idx
            else:
                for m in re.finditer(r"[.!?؟][\s\r\n]", text[search_start:target_end]):
                    candidate = search_start + m.end()

                if candidate == -1:
                    s_idx = text.rfind(" ", search_start, target_end)
                    if s_idx != -1:
                        candidate = s_idx

            if candidate != -1:
                actual_end = candidate
            else:
                actual_end = target_end

        if actual_end < text_len:
            if text[actual_end] == "\u200c":
                actual_end += 1
            elif actual_end > 0 and text[actual_end - 1] == "\u200c":
                space_after = text.find(" ", actual_end)
                if space_after != -1 and space_after - actual_end < 15:
                    actual_end = space_after
                else:
                    actual_end = max(start + 1, actual_end - 2)

        chunk = text[start:actual_end].strip()
        if chunk:
            chunks.append(chunk)

        if actual_end >= text_len:
            break

        if overlap > 0 and actual_end > start:
            next_start = max(start + 1, actual_end - overlap)
            if next_start < actual_end:
                space_pos = text.find(" ", next_start, min(text_len, next_start + 20))
                if space_pos != -1:
                    next_start = space_pos + 1
        else:
            next_start = actual_end

        if next_start <= start:
            next_start = start + step

        start = next_start

    return chunks


def _split_semantic_heading_with_context(
    text: str,
    chunk_size: int,
    overlap: int,
    coalesce_micro_items: bool = True,
) -> list[tuple[str, Optional[str]]]:
    """Split Markdown text at heading boundaries (H1 to H6), preserving context and hierarchy.

    Features:
    - Maintains full parent-child context stacks.
    - Prevents orphan headings without body content.
    - Glues date/subtitle headers directly to their child entities instead of creating 3-word chunks.
    - Coalesces sequential micro leaf items (percentages, tool tags) under their parent section.
    - Sub-splits oversized sections cleanly.
    """
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    matches = list(heading_pattern.finditer(text))

    if not matches:
        raw = _split_paragraph(text, chunk_size, overlap)
        return [(c, None) for c in raw]

    chunks_with_ctx: list[tuple[str, Optional[str]]] = []

    # 1. Preamble: Content before the first heading
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            if len(preamble) <= chunk_size:
                chunks_with_ctx.append((preamble, None))
            else:
                for sub in _split_paragraph(preamble, chunk_size, overlap):
                    chunks_with_ctx.append((sub, None))

    # 2. Parse Raw Sections and Hierarchy
    raw_sections: list[dict[str, Any]] = []
    heading_stack: list[tuple[int, str]] = []

    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        heading_line = m.group(0).strip()

        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, title))
        current_context = " > ".join(t for _, t in heading_stack)

        start_pos = m.start()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_raw = text[start_pos:end_pos].strip()

        if section_raw.startswith(heading_line):
            body_text = section_raw[len(heading_line):].strip()
        else:
            body_text = section_raw.replace(heading_line, "", 1).strip()

        raw_sections.append({
            "level": level,
            "title": title,
            "heading_line": heading_line,
            "body_text": body_text,
            "section_raw": section_raw,
            "context": current_context,
            "parent_context": " > ".join(t for _, t in heading_stack[:-1]) if len(heading_stack) > 1 else None,
        })

    # 3. Process Sections with Coalescing & Glue
    pending_prefix = ""
    accumulated_chunk_text = ""
    accumulated_context: Optional[str] = None
    accumulated_root_level: int = 0

    def flush_accumulated():
        nonlocal accumulated_chunk_text, accumulated_context, accumulated_root_level
        if accumulated_chunk_text.strip():
            text_to_save = accumulated_chunk_text.strip()
            if len(text_to_save) <= chunk_size:
                chunks_with_ctx.append((text_to_save, accumulated_context))
            else:
                for sc in _split_paragraph(text_to_save, chunk_size, overlap):
                    chunks_with_ctx.append((sc, accumulated_context))
            accumulated_chunk_text = ""
            accumulated_context = None
            accumulated_root_level = 0

    for i, sec in enumerate(raw_sections):
        level = sec["level"]
        body_text = sec["body_text"]
        section_raw = sec["section_raw"]
        current_context = sec["context"]
        parent_ctx = sec["parent_context"]
        next_sec = raw_sections[i + 1] if i + 1 < len(raw_sections) else None

        # A: Empty body: Carry forward heading container into prefix
        if not body_text:
            if next_sec:
                pending_prefix = (pending_prefix + "\n\n" + section_raw).strip()
            continue

        # B: Date/Timeline prefix heading: Glue to following entity instead of creating an isolated 3-word chunk
        if coalesce_micro_items and _is_date_prefix(body_text) and next_sec:
            pending_prefix = (pending_prefix + "\n\n" + section_raw).strip()
            continue

        # Attach any pending prefix (e.g. date or container heading)
        if pending_prefix:
            section_raw = (pending_prefix + "\n\n" + section_raw).strip()
            pending_prefix = ""

        # C: Micro-item coalescing (skills, percentages, metrics)
        if coalesce_micro_items:
            # 1. An active group chunk exists: does this section belong to it?
            if accumulated_chunk_text:
                is_child_of_group = (level > accumulated_root_level) or (parent_ctx and parent_ctx == accumulated_context)
                if is_child_of_group and (_is_micro_body(body_text) or len(section_raw) < 150):
                    test_len = len(accumulated_chunk_text) + len(section_raw) + 2
                    if test_len <= chunk_size:
                        accumulated_chunk_text += "\n\n" + section_raw
                        continue
                flush_accumulated()

            # 2. Can this section start a micro-items group?
            # A container heading whose next section is a deeper micro-item (e.g. #### ابزارها و پلتفرم‌ها with ##### FastAPI)
            if next_sec and next_sec["level"] > level and _is_micro_body(next_sec["body_text"]):
                accumulated_chunk_text = section_raw
                accumulated_context = current_context
                accumulated_root_level = level
                continue

            # 3. Standalone micro leaf item under a parent
            if _is_micro_body(body_text) and level >= 4:
                accumulated_chunk_text = section_raw
                accumulated_context = parent_ctx or current_context
                accumulated_root_level = level - 1
                continue

        # D: Substantive Section
        flush_accumulated()
        if len(section_raw) <= chunk_size:
            chunks_with_ctx.append((section_raw, current_context))
        else:
            sub_chunks = _split_paragraph(section_raw, chunk_size, overlap)
            for sc in sub_chunks:
                chunks_with_ctx.append((sc, current_context))

    # Flush any remaining accumulated chunk
    flush_accumulated()

    # Flush any leftover prefix
    if pending_prefix and pending_prefix.strip():
        text_to_save = pending_prefix.strip()
        last_ctx = raw_sections[-1]["context"] if raw_sections else None
        if len(text_to_save) <= chunk_size:
            chunks_with_ctx.append((text_to_save, last_ctx))
        else:
            for sc in _split_paragraph(text_to_save, chunk_size, overlap):
                chunks_with_ctx.append((sc, last_ctx))

    # Fallback if no chunks were produced
    if not chunks_with_ctx and text.strip():
        raw = _split_paragraph(text, chunk_size, overlap)
        return [(c, None) for c in raw]

    return chunks_with_ctx


def _split_semantic_heading(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split Markdown text at heading boundaries, returning chunk text strings only."""
    tuples = _split_semantic_heading_with_context(text, chunk_size, overlap)
    return [chunk for chunk, _ in tuples]


# ---------------------------------------------------------------------------
# Heading context tracker for non-heading strategies
# ---------------------------------------------------------------------------

def _extract_heading_contexts(text: str) -> list[tuple[int, str]]:
    """Return a list of (char_position, hierarchical_heading_context) tuples from Markdown text."""
    pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    stack: list[tuple[int, str]] = []
    contexts: list[tuple[int, str]] = []

    for m in pattern.finditer(text):
        level = len(m.group(1))
        title = m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        full_ctx = " > ".join(t for _, t in stack)
        contexts.append((m.start(), full_ctx))

    return contexts


def _find_heading_context(char_pos: int, heading_contexts: list[tuple[int, str]]) -> Optional[str]:
    """Return the nearest heading context that precedes ``char_pos``."""
    context = None
    for pos, heading in heading_contexts:
        if pos <= char_pos:
            context = heading
        else:
            break
    return context


# ---------------------------------------------------------------------------
# Auto strategy selector
# ---------------------------------------------------------------------------

def select_auto_strategy(doc: ExtractedDocument, text: str) -> tuple[str, str]:
    """Deterministically analyze document characteristics and select the best strategy."""
    clean_text = text.strip()
    if not clean_text:
        return "paragraph", "Empty document defaulted to paragraph strategy"

    ptype = (doc.page_type or "").lower()

    heading_pattern = re.compile(r"^(#{1,6})\s+\S+", re.MULTILINE)
    md_headings = heading_pattern.findall(clean_text)
    heading_count = len(md_headings)
    if heading_count == 0 and doc.headings:
        heading_count = len(doc.headings)

    if ptype == "faq":
        if heading_count >= 2:
            return "semantic_heading", f"FAQ page with {heading_count} structured Q&A headings"
        return "paragraph", "FAQ page without headings; paragraph boundaries preserve question-answer pairs"

    if ptype in {"policy", "terms", "legal", "privacy"}:
        if heading_count >= 3:
            return "semantic_heading", f"Policy/legal document with {heading_count} structured section headings"
        return "sentence", "Dense policy/legal content segmented by granular sentence boundaries"

    if ptype in {"product", "pricing"}:
        if heading_count >= 2:
            return "semantic_heading", f"Product/pricing page with {heading_count} structured feature headings"
        return "paragraph", "Product specifications and features grouped into paragraph blocks"

    if ptype in {"resume", "skills", "services", "portfolio"}:
        if heading_count >= 2:
            return "semantic_heading", f"Structured {ptype} document with {heading_count} headings preserving hierarchy"
        return "paragraph", f"{ptype} content segmented by logical paragraphs"

    if heading_count >= 2:
        return (
            "semantic_heading",
            f"Document contains {heading_count} structured Markdown headings (H1-H6) forming a clear hierarchy",
        )

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean_text) if p.strip()]
    if len(paragraphs) >= 2:
        avg_para_len = sum(len(p) for p in paragraphs) / len(paragraphs)
        if avg_para_len >= 60:
            return (
                "paragraph",
                f"Document has {len(paragraphs)} well-formed paragraphs with average length of {int(avg_para_len)} characters",
            )

    raw_sentences = _extract_sentences(clean_text)
    if len(raw_sentences) >= 2:
        return (
            "sentence",
            f"Content lacks distinct paragraph breaks; segmented across {len(raw_sentences)} natural sentences",
        )

    return "paragraph", "Default fallback to paragraph strategy for standard prose flow"


# ---------------------------------------------------------------------------
# Public API – ChunkerService
# ---------------------------------------------------------------------------

class ChunkerService:
    """Splits extracted documents into structured chunks for RAG pipelines."""

    STRATEGIES = {"auto", "paragraph", "sentence", "fixed_size", "semantic_heading"}

    def __init__(
        self,
        strategy: str = "auto",
        chunk_size: int = 1000,
        overlap: int = 150,
        normalize: bool = True,
        normalizer: Optional[PersianNormalizer] = None,
        min_chunk_size: int = 100,
        coalesce_micro_items: bool = True,
    ) -> None:
        """Initialize the chunker service.

        Args:
            strategy: Splitting strategy name.
            chunk_size: Target chunk size in characters (min 50).
            overlap: Number of characters to repeat at the start of each new chunk.
            normalize: Whether to apply Persian & Unicode normalization prior to chunking (default: True).
            normalizer: Optional custom PersianNormalizer instance.
            min_chunk_size: Minimum character size for independent chunks.
            coalesce_micro_items: Whether to consolidate micro headings (e.g. percentages, skill badges) into parent sections.
        """
        if strategy not in self.STRATEGIES:
            raise ValueError(
                f"Unknown chunking strategy '{strategy}'. "
                f"Allowed: {sorted(self.STRATEGIES)}"
            )
        self.strategy = strategy
        self.chunk_size = max(50, chunk_size)
        self.overlap = max(0, min(overlap, self.chunk_size // 2))
        self.normalize = normalize
        self.normalizer = normalizer
        self.min_chunk_size = min_chunk_size
        self.coalesce_micro_items = coalesce_micro_items

    def chunk_document(
        self,
        doc: ExtractedDocument,
        category: Optional[str] = None,
    ) -> ChunkingResult:
        """Chunk a single ExtractedDocument into DocumentChunk objects."""
        text = doc.content_markdown or doc.content_text or ""
        text = text.strip()

        norm_applied = False
        norm_report: dict[str, Any] = {}

        if self.normalize:
            active_norm = self.normalizer or PersianNormalizer()
            norm_text, norm_rep = active_norm.normalize_with_report(text)
            text = norm_text
            norm_applied = True
            norm_report = norm_rep
        elif hasattr(doc, "metadata") and isinstance(doc.metadata, dict):
            norm_applied = bool(doc.metadata.get("normalized", False))

        if not text:
            logger.debug("Document %s has no content to chunk.", doc.url)
            return ChunkingResult(
                source_url=doc.url,
                total_chunks=0,
                strategy=self.strategy,
                applied_strategy=self.strategy,
                chunks=[],
                metadata={"reason": "Document has no content to chunk"},
            )

        # Resolve strategy
        if self.strategy == "auto":
            applied_strategy, reason = select_auto_strategy(doc, text)
        else:
            applied_strategy = self.strategy
            reason = f"Explicitly requested strategy: {self.strategy}"

        # Split text and capture heading contexts
        if applied_strategy == "semantic_heading":
            raw_tuples = _split_semantic_heading_with_context(
                text=text,
                chunk_size=self.chunk_size,
                overlap=self.overlap,
                coalesce_micro_items=self.coalesce_micro_items,
            )
        else:
            if applied_strategy == "paragraph":
                raw_texts = _split_paragraph(text, self.chunk_size, self.overlap)
            elif applied_strategy == "sentence":
                raw_texts = _split_sentence(text, self.chunk_size, self.overlap)
            elif applied_strategy == "fixed_size":
                raw_texts = _split_fixed(text, self.chunk_size, self.overlap)
            else:
                raw_texts = _split_paragraph(text, self.chunk_size, self.overlap)

            heading_contexts = _extract_heading_contexts(text)
            raw_tuples = []
            running_pos = 0
            for ct in raw_texts:
                chunk_start = text.find(ct[:50].strip(), running_pos)
                if chunk_start == -1:
                    chunk_start = running_pos
                running_pos = chunk_start + len(ct)
                ctx = _find_heading_context(chunk_start, heading_contexts)
                raw_tuples.append((ct, ctx))

        raw_tuples = [(t.strip(), ctx) for t, ctx in raw_tuples if t and t.strip()]

        total = len(raw_tuples)
        doc_chunks: list[DocumentChunk] = []

        for idx, (chunk_text, heading_ctx) in enumerate(raw_tuples):
            chunk_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            chunk_id = _make_chunk_id(doc.url, idx, chunk_hash)

            words = chunk_text.split()
            word_count = len(words)
            char_count = len(chunk_text)
            # RAG token budgeting estimate (~1.3x for English, ~1.45x for Persian/Arabic)
            token_approx = int(word_count * 1.35)

            resolved_category = resolve_chunk_category(
                requested_category=category,
                heading_ctx=heading_ctx,
                doc_page_type=getattr(doc, "page_type", None),
                doc_title=doc.title,
                source_url=doc.url,
            )

            breadcrumbs = [b.strip() for b in heading_ctx.split(" > ")] if heading_ctx else []
            parent_heading = breadcrumbs[-2] if len(breadcrumbs) >= 2 else (breadcrumbs[0] if breadcrumbs else None)

            q_flags = detect_chunk_quality_flags(chunk_text, heading_ctx)

            dc = DocumentChunk(
                chunk_id=chunk_id,
                source_url=doc.url,
                chunk_index=idx,
                total_chunks=total,
                text=chunk_text,
                char_count=char_count,
                word_count=word_count,
                heading_context=heading_ctx,
                title=doc.title,
                source_title=doc.title,
                language=doc.language or ("fa" if re.search(r"[\u0600-\u06FF]", chunk_text) else "en"),
                category=resolved_category,
                content_hash=chunk_hash,
                source_doc_id=getattr(doc, "document_id", None),
                source_doc_hash=getattr(doc, "content_hash", None),
                processed_at=datetime.now(timezone.utc).isoformat(),
                quality_flags=q_flags,
                normalization_applied=norm_applied,
                parent_heading=parent_heading,
                breadcrumbs=breadcrumbs,
                token_count_approx=token_approx,
                alternate_sources=[],
                metadata={
                    "source_doc_hash": doc.content_hash,
                    "content_hash": chunk_hash,
                    "http_status": doc.http_status,
                    "fetched_at": doc.fetched_at.isoformat() if doc.fetched_at else None,
                    "strategy": applied_strategy,
                    "selection_reason": reason if self.strategy == "auto" else None,
                    "quality_flags": q_flags,
                    "normalization_report": norm_report if norm_report else None,
                },
            )
            doc_chunks.append(dc)

        logger.info(
            "Chunked %s into %d chunks (strategy=%s, applied=%s, size=%d, overlap=%d).",
            doc.url,
            total,
            self.strategy,
            applied_strategy,
            self.chunk_size,
            self.overlap,
        )

        return ChunkingResult(
            source_url=doc.url,
            total_chunks=total,
            strategy=self.strategy,
            applied_strategy=applied_strategy,
            chunks=doc_chunks,
            metadata={
                "selected_strategy": applied_strategy,
                "selection_reason": reason,
                "requested_strategy": self.strategy,
                "chunk_size": self.chunk_size,
                "overlap": self.overlap,
            },
        )

    def chunk_documents(
        self,
        docs: list[ExtractedDocument],
        category: Optional[str] = None,
        deduplicate_chunks: bool = False,
    ) -> list[DocumentChunk]:
        """Chunk multiple documents with optional provenance-preserving chunk deduplication.

        If deduplicate_chunks=True, identical chunks across documents share a single vector chunk,
        with all duplicate source URLs and documents recorded in alternate_sources.
        """
        all_chunks: list[DocumentChunk] = []
        seen_chunks: dict[str, DocumentChunk] = {}

        for doc in docs:
            result = self.chunk_document(doc, category=category)
            for chunk in result.chunks:
                h = chunk.content_hash
                if deduplicate_chunks and h and h in seen_chunks:
                    existing = seen_chunks[h]
                    alt_entry = {
                        "source_url": chunk.source_url,
                        "source_doc_id": chunk.source_doc_id,
                        "title": chunk.title,
                        "chunk_id": chunk.chunk_id,
                        "chunk_index": chunk.chunk_index,
                    }
                    if alt_entry not in existing.alternate_sources:
                        existing.alternate_sources.append(alt_entry)
                else:
                    if h:
                        seen_chunks[h] = chunk
                    all_chunks.append(chunk)

        logger.info(
            "Multi-doc chunking produced %d total chunks across %d docs (deduped=%s).",
            len(all_chunks), len(docs), deduplicate_chunks,
        )
        return all_chunks

    def _split(self, text: str) -> list[str]:
        """Dispatch to the configured strategy (returns string chunks)."""
        if self.strategy == "paragraph":
            return _split_paragraph(text, self.chunk_size, self.overlap)
        elif self.strategy == "sentence":
            return _split_sentence(text, self.chunk_size, self.overlap)
        elif self.strategy == "fixed_size":
            return _split_fixed(text, self.chunk_size, self.overlap)
        elif self.strategy == "semantic_heading":
            return _split_semantic_heading(text, self.chunk_size, self.overlap)
        elif self.strategy == "auto":
            heading_pattern = re.compile(r"^(#{1,6})\s+\S+", re.MULTILINE)
            if len(heading_pattern.findall(text)) >= 2:
                return _split_semantic_heading(text, self.chunk_size, self.overlap)
            return _split_paragraph(text, self.chunk_size, self.overlap)
        else:
            return _split_paragraph(text, self.chunk_size, self.overlap)
