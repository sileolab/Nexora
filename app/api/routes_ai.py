from __future__ import annotations
import time
"""API endpoints for AI-powered features: Chunking, Embedding, and RAG Enhancement.



All endpoints are optional — they activate only when CRAWLBOT_OPENAI_API_KEY is set.

Chunking works without an API key; Embedding and RAG Enhancement require one.

"""






import logging

from typing import Any, Optional



from fastapi import APIRouter, HTTPException, Request



from app.core.config import get_settings
from app.core.security import sanitize_secret_leakage

from app.jobs.manager import JobManager

from app.schemas.documents import QualityStatus

from app.schemas.responses import ApiResponse

from app.services.chunker import ChunkerService

from app.services.embedding_service import EmbeddingService

from app.services.rag_enhancer import RAGEnhancer

from app.services.semantic_repair import SemanticRepairService

from app.services.vector_store import get_vector_store

from app.services.dataset_studio import dataset_studio

from app.services.rag_evaluator import rag_evaluator



logger = logging.getLogger(__name__)



router = APIRouter(prefix="/api/ai", tags=["ai"])



job_manager: Optional[JobManager] = None





def set_job_manager(manager: JobManager) -> None:

    """Inject JobManager dependency."""

    global job_manager

    job_manager = manager

    dataset_studio._manager = manager

    rag_evaluator._manager = manager





def get_manager() -> JobManager:

    """Ensure JobManager is initialized."""

    if job_manager is None:

        raise HTTPException(status_code=500, detail="Job manager not initialized")

    return job_manager





def _require_api_key(tenant_id: Optional[str] = None, allow_system_fallback: bool = True) -> str:
    """Return the OpenAI API key (checking workspace BYOK first, then settings) or raise HTTP 400.

    Tenant isolation:
    1. If tenant_id is provided, strictly lookup that tenant's 'openai_api_key' in SecretsManager.
    2. If found, returns tenant's BYOK key.
    3. If not found:
       - If allow_system_fallback is True, check global settings.openai_api_key.
       - If neither exists, raise HTTPException(status_code=400).
    """
    if tenant_id:
        try:
            from app.services.secrets_manager import get_secrets_manager
            byok = get_secrets_manager().get_secret(tenant_id, "openai_api_key")
            if byok and byok.strip():
                return byok.strip()
        except Exception as e:
            logger.warning("Error fetching BYOK for tenant %s: %s", tenant_id, e)

    if allow_system_fallback:
        settings = get_settings()
        key = (settings.openai_api_key or "").strip()
        if key:
            return key

    raise HTTPException(
        status_code=400,
        detail=(
            "کلید API هوش مصنوعی تنظیم نشده است. "
            "لطفاً کلید اختصاصی خود (BYOK) را در تنظیمات Workspace ذخیره کنید "
            "یا NEXORA_OPENAI_API_KEY را تنظیم نمایید."
        ),
    )


def _get_api_key_optional(tenant_id: Optional[str] = None, allow_system_fallback: bool = True) -> Optional[str]:
    """Return OpenAI API key if available for tenant or system, else None."""
    try:
        return _require_api_key(tenant_id=tenant_id, allow_system_fallback=allow_system_fallback)
    except HTTPException:
        return None





# ---------------------------------------------------------------------------

# GET /api/ai/status

# ---------------------------------------------------------------------------



@router.get("/status", response_model=ApiResponse)

async def get_ai_status() -> ApiResponse:

    """Return AI service availability and configuration status."""

    settings = get_settings()

    api_key_set = bool(settings.openai_api_key.strip())

    return ApiResponse.ok(

        data={

            "chunking_available": True,

            "embedding_available": api_key_set,

            "rag_enhancement_available": api_key_set,

            "embedding_model": settings.embedding_model,

            "llm_model": settings.llm_model,

            "api_key_configured": api_key_set,

            "base_url": settings.openai_base_url or None,

        },

        message="AI services status",
    )


# ---------------------------------------------------------------------------
# AI Settings & .env Configuration Endpoints
# ---------------------------------------------------------------------------

@router.get("/config", response_model=ApiResponse)
async def get_ai_config() -> ApiResponse:
    """Return detailed AI configuration, current settings, and provider presets."""
    from app.services.env_manager import read_env_dict
    settings = get_settings()
    env = read_env_dict()

    api_key = env.get("NEXORA_OPENAI_API_KEY") or env.get("CRAWLBOT_OPENAI_API_KEY") or settings.openai_api_key or ""
    base_url = env.get("NEXORA_OPENAI_BASE_URL") or env.get("CRAWLBOT_OPENAI_BASE_URL") or settings.openai_base_url or ""
    llm_model = env.get("NEXORA_LLM_MODEL") or env.get("CRAWLBOT_LLM_MODEL") or settings.llm_model or "gpt-4o-mini"
    embedding_model = env.get("NEXORA_EMBEDDING_MODEL") or env.get("CRAWLBOT_EMBEDDING_MODEL") or settings.embedding_model or "text-embedding-3-small"

    masked_key = ""
    if api_key:
        if len(api_key) > 10:
            masked_key = f"{api_key[:6]}...{api_key[-4:]}"
        else:
            masked_key = "********"

    presets = [
        {"name": "OpenAI Direct", "base_url": "", "default_model": "gpt-4o-mini"},
        {"name": "AvalAI", "base_url": "https://api.avalai.ir/v1", "default_model": "gpt-6-luna"},
        {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "default_model": "openai/gpt-4o-mini"},
        {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat"},
        {"name": "Groq", "base_url": "https://api.groq.com/openai/v1", "default_model": "llama-3.3-70b-versatile"},
        {"name": "Local Ollama / vLLM", "base_url": "http://localhost:11434/v1", "default_model": "llama3"},
    ]

    available_llms = [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-6-luna",
        "claude-3-5-sonnet",
        "deepseek-chat",
        "gemini-1.5-flash",
        "llama-3.3-70b-versatile",
    ]

    available_embeddings = [
        "text-embedding-3-small",
        "text-embedding-3-large",
        "text-embedding-ada-002",
        "bge-m3",
    ]

    return ApiResponse.ok(
        data={
            "api_key_configured": bool(api_key.strip()),
            "masked_api_key": masked_key,
            "api_key": api_key,
            "base_url": base_url,
            "llm_model": llm_model,
            "embedding_model": embedding_model,
            "presets": presets,
            "available_llms": available_llms,
            "available_embeddings": available_embeddings,
        },
        message="Current AI configuration",
    )


@router.post("/config", response_model=ApiResponse)
async def update_ai_config(payload: dict[str, Any]) -> ApiResponse:
    """Save AI configuration directly to .env file and apply to runtime."""
    from app.services.env_manager import update_env_file

    updates: dict[str, Optional[str]] = {}

    if "api_key" in payload:
        updates["NEXORA_OPENAI_API_KEY"] = str(payload["api_key"]).strip()
    if "base_url" in payload:
        raw_url = str(payload["base_url"]).strip() if payload["base_url"] else ""
        updates["NEXORA_OPENAI_BASE_URL"] = raw_url
    if "llm_model" in payload and payload["llm_model"]:
        updates["NEXORA_LLM_MODEL"] = str(payload["llm_model"]).strip()
    if "embedding_model" in payload and payload["embedding_model"]:
        updates["NEXORA_EMBEDDING_MODEL"] = str(payload["embedding_model"]).strip()

    if not updates:
        raise HTTPException(status_code=400, detail="No configuration parameters provided.")

    success = update_env_file(updates)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to write configuration to .env file.")

    settings = get_settings()
    api_key_set = bool(settings.openai_api_key.strip())

    return ApiResponse.ok(
        data={
            "api_key_configured": api_key_set,
            "base_url": settings.openai_base_url or None,
            "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model,
        },
        message="AI configuration successfully saved to .env and applied to runtime.",
    )


@router.post("/test-connection", response_model=ApiResponse)
async def test_ai_connection(payload: dict[str, Any]) -> ApiResponse:
    """Test connectivity and authentication with an AI provider."""
    import time
    import httpx
    settings = get_settings()

    api_key = str(payload.get("api_key", "")).strip() or settings.openai_api_key
    base_url = str(payload.get("base_url", "")).strip() or settings.openai_base_url or "https://api.openai.com/v1"
    base_url = base_url.rstrip("/")
    test_url = f"{base_url}/models"

    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required to test connection.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            resp = await client.get(test_url, headers=headers)
            latency_ms = round((time.time() - start) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                models_count = len(data.get("data", [])) if isinstance(data, dict) else 0
                return ApiResponse.ok(
                    data={
                        "connected": True,
                        "status_code": 200,
                        "latency_ms": latency_ms,
                        "models_count": models_count,
                    },
                    message=f"Connected successfully to {base_url} in {latency_ms}ms.",
                )
            elif resp.status_code == 401:
                return ApiResponse.ok(
                    data={"connected": False, "status_code": 401, "latency_ms": latency_ms},
                    message="Authentication failed (HTTP 401): Invalid API key.",
                )
            else:
                return ApiResponse.ok(
                    data={"connected": False, "status_code": resp.status_code, "latency_ms": latency_ms},
                    message=f"Provider returned HTTP {resp.status_code}: {resp.text[:120]}",
                )
    except Exception as exc:
        latency_ms = round((time.time() - start) * 1000)
        return ApiResponse.ok(
            data={"connected": False, "error": str(exc), "latency_ms": latency_ms},
            message=f"Connection failed: {str(exc)}",
        )





# ---------------------------------------------------------------------------

# POST /api/ai/chunk

# ---------------------------------------------------------------------------



@router.post("/chunk", response_model=ApiResponse)
async def chunk_documents(request: dict[str, Any], req: Request) -> ApiResponse:
    """Chunk the extracted documents of a job.

    Request body:
        job_id (str): Extraction job identifier.
        strategy (str): One of paragraph|sentence|fixed_size|semantic_heading.
        chunk_size (int): Target chunk size in characters (default 1000).
        overlap (int): Overlap in characters (default 150).
        category (str|null): Optional document category tag.
    """

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    manager = get_manager()
    settings = get_settings()



    job_id = request.get("job_id", "").strip()

    if not job_id:

        raise HTTPException(status_code=400, detail="job_id is required.")



    job = manager.get_job(job_id)

    if not job:

        raise HTTPException(status_code=404, detail="Job with this ID not found.")



    if tenant_id:
        from app.services.quota_enforcer import get_quota_enforcer
        try:
            get_quota_enforcer().check_chunks(tenant_id, 1)
        except ValueError as q_err:
            raise HTTPException(status_code=429, detail=str(q_err))

    documents = manager.get_documents(job_id)

    if not documents:

        raise HTTPException(

            status_code=400,

            detail="This job has no extracted documents yet. Perform extraction first.",

        )



    strategy = str(request.get("strategy", "auto")).strip().lower()

    try:

        chunk_size = int(request.get("chunk_size", 1000))

        overlap = int(request.get("overlap", 150))

    except (ValueError, TypeError):

        raise HTTPException(

            status_code=400,

            detail="chunk_size and overlap must be valid integers.",

        )

    category = request.get("category") or None



    # Validate strategy

    allowed = {"auto", "paragraph", "sentence", "fixed_size", "semantic_heading"}

    if strategy not in allowed:

        raise HTTPException(

            status_code=400,

            detail=f"Invalid strategy '{strategy}'. Allowed: {', '.join(sorted(allowed))}",

        )



    # Validate chunk size bounds

    if chunk_size < 100 or chunk_size > 8000:

        raise HTTPException(

            status_code=400,

            detail=f"Chunk size must be between 100 and 8000 characters. Provided: {chunk_size}",

        )



    # Validate overlap bounds

    if overlap < 0 or overlap > 500:

        raise HTTPException(

            status_code=400,

            detail=f"Overlap must be between 0 and 500 characters. Provided: {overlap}",

        )



    if overlap >= chunk_size:

        raise HTTPException(

            status_code=400,

            detail=f"Overlap ({overlap}) cannot be greater than or equal to chunk size ({chunk_size}).",

        )



    try:

        normalize = bool(request.get("normalize", True))

        deduplicate_docs = bool(request.get("deduplicate_docs", True))

        deduplicate_chunks = bool(request.get("deduplicate_chunks", False))



        chunker = ChunkerService(

            strategy=strategy,

            chunk_size=chunk_size,

            overlap=overlap,

            normalize=normalize,

        )



        # Filter only successfully extracted docs with content and apply document-level deduplication

        if deduplicate_docs:

            eligible = []

            seen_hashes = set()

            for d in documents:

                if not d.has_content:

                    continue

                if getattr(d, "quality_status", None) == QualityStatus.DUPLICATE:

                    continue

                h = d.content_hash

                if h and h in seen_hashes:

                    continue

                if h:

                    seen_hashes.add(h)

                eligible.append(d)



            # Fallback if all documents were marked duplicate: process at least one canonical doc

            if not eligible and any(d.has_content for d in documents):

                first_with_content = next(d for d in documents if d.has_content)

                eligible = [first_with_content]

        else:

            eligible = [d for d in documents if d.has_content]



        if not eligible:

            raise HTTPException(

                status_code=400,

                detail="No successful documents with content found for chunking.",

            )



        all_chunks = chunker.chunk_documents(

            eligible,

            category=category,

            deduplicate_chunks=deduplicate_chunks,

        )



        repair_report_dict = None

        if bool(request.get("semantic_repair", False)):

            repair_api_key = _get_api_key_optional(tenant_id)

            repair_service = SemanticRepairService(

                api_key=repair_api_key,

                base_url=settings.openai_base_url or None,

                model=settings.llm_model,

                concurrency=settings.ai_concurrency,

            )

            all_chunks, repair_rep = await repair_service.repair_chunks(

                all_chunks,

                apply_llm=bool(repair_api_key),

            )

            repair_report_dict = repair_rep.model_dump()



        # Re-run Policy: Preserve manual user edits unless overwrite_user_edits=True

        overwrite_user_edits = bool(request.get("overwrite_user_edits", False))

        existing_chunks = manager.get_chunks(job_id)

        user_edited = [c for c in existing_chunks if getattr(c, "user_edited", False)]

        preserved_edits_count = 0



        if not overwrite_user_edits and user_edited:

            user_edited_ids = {c.chunk_id for c in user_edited}

            preserved_chunks = []

            for c in all_chunks:

                if c.chunk_id in user_edited_ids:

                    user_chunk = next(uc for uc in user_edited if uc.chunk_id == c.chunk_id)

                    preserved_chunks.append(user_chunk)

                else:

                    preserved_chunks.append(c)

            present_ids = {c.chunk_id for c in preserved_chunks}

            for uc in user_edited:

                if uc.chunk_id not in present_ids:

                    preserved_chunks.append(uc)

            all_chunks = preserved_chunks

            preserved_edits_count = len(user_edited)

            logger.info("Preserved %d user-edited chunks for job %s during re-chunking.", preserved_edits_count, job_id)



        # Store chunks on the job for later embedding/export
        manager.store_chunks(job_id, all_chunks)

        if tenant_id and len(all_chunks) > 0:
            from app.services.quota_enforcer import get_quota_enforcer
            try:
                get_quota_enforcer().check_chunks(tenant_id, len(all_chunks))
            except ValueError as q_err:
                raise HTTPException(status_code=429, detail=str(q_err))

            try:
                from app.services.usage_meter import get_usage_meter
                get_usage_meter().record(
                    tenant_id,
                    "chunks_created",
                    len(all_chunks),
                    job_id=job_id,
                    idempotency_key=f"chunks_created:{job_id}",
                )
            except Exception as u_err:
                logger.warning("Could not record chunks usage: %s", u_err)



        applied_set = list({c.metadata.get("strategy") for c in all_chunks if c.metadata.get("strategy")})

        applied_strategy = applied_set[0] if len(applied_set) == 1 else (", ".join(applied_set) if applied_set else strategy)



        chunk_stats = {

            "total_chunks": len(all_chunks),

            "total_docs_chunked": len(eligible),

            "strategy": strategy,

            "applied_strategy": applied_strategy,

            "chunk_size": chunk_size,

            "overlap": overlap,

            "semantic_repair_applied": repair_report_dict is not None,

            "semantic_repair_report": repair_report_dict,

            "preserved_user_edits_count": preserved_edits_count,

            "avg_chunk_chars": (

                int(sum(c.char_count for c in all_chunks) / len(all_chunks))

                if all_chunks else 0

            ),

        }

        logger.info(

            "Chunked job %s: %d chunks from %d docs (requested=%s, applied=%s).",

            job_id,

            len(all_chunks),

            len(eligible),

            strategy,

            applied_strategy,

        )



        return ApiResponse.ok(

            data={"job_id": job_id, **chunk_stats},

            message=f"تقطیع با موفقیت انجام شد. {len(all_chunks)} قطعه از {len(eligible)} سند تولید شد (استراتژی: {applied_strategy}).",

        )



    except HTTPException:

        raise

    except Exception as exc:

        logger.exception("Chunking failed for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"Error during chunking: {str(exc)}")





# ---------------------------------------------------------------------------

# POST /api/ai/repair

# ---------------------------------------------------------------------------



@router.post("/repair", response_model=ApiResponse)

async def repair_job_chunks(request: dict[str, Any], req: Request) -> ApiResponse:

    """Audit and repair semantic inconsistencies in chunks of a job or a provided chunk list.



    Corrects:

    - Misclassified categories (e.g. resume vs portfolio)

    - Heading context inheritance leakage

    - Residual JS injection placeholders and HTML artifacts

    - Broken semantic links to predecessor entities

    - Selectively invalidates vector embeddings only for modified chunk text, with optional re-embedding

    """



    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    manager = get_manager()

    settings = get_settings()



    job_id = str(request.get("job_id", "")).strip()

    chunks_raw = request.get("chunks")

    apply_llm = bool(request.get("apply_llm", True))

    re_embed = bool(request.get("re_embed", True))

    try:

        confidence_threshold = float(request.get("confidence_threshold", 0.75))

    except (TypeError, ValueError):

        confidence_threshold = 0.75



    from app.schemas.chunks import DocumentChunk



    chunks: list[DocumentChunk] = []

    if job_id:

        chunks = manager.get_chunks(job_id, tenant_id=tenant_id)

        if not chunks:

            raise HTTPException(

                status_code=400,

                detail="This job has no chunks yet. Perform chunking (/api/ai/chunk) first.",

            )

    elif isinstance(chunks_raw, list):

        chunks = [DocumentChunk.model_validate(c) for c in chunks_raw]

    else:

        raise HTTPException(

            status_code=400,

            detail="Either job_id or chunks list is required.",

        )



    repair_api_key = _get_api_key_optional(tenant_id)

    repair_service = SemanticRepairService(

        api_key=repair_api_key,

        base_url=settings.openai_base_url or None,

        model=settings.llm_model,

        concurrency=settings.ai_concurrency,

        confidence_threshold=confidence_threshold,
    )


    repaired_chunks, report = await repair_service.repair_chunks(

        chunks,

        apply_llm=apply_llm and bool(repair_api_key),
    )



    # If job_id was provided, update manager with repaired chunks

    if job_id:

        manager.store_chunks(job_id, repaired_chunks)



    # Selective Re-embedding: Recompute vector embeddings ONLY for chunks whose text was modified

    re_embedded_count = 0

    if re_embed and repair_api_key and report.invalidated_chunk_ids:

        invalidated_chunks = [c for c in repaired_chunks if c.chunk_id in report.invalidated_chunk_ids]

        if invalidated_chunks:

            try:

                embedder = EmbeddingService(

                    api_key=repair_api_key,

                    base_url=settings.openai_base_url or None,

                    model=settings.embedding_model,

                )

                await embedder.embed_chunks(invalidated_chunks)

                re_embedded_count = len(invalidated_chunks)

                if job_id:

                    manager.store_chunks(job_id, repaired_chunks)

            except Exception as exc:

                logger.warning("Re-embedding invalidated chunks failed: %s", exc)



    return ApiResponse.ok(

        data={

            "job_id": job_id or None,

            "report": report.model_dump(),

            "re_embedded_count": re_embedded_count,

            "total_chunks": len(repaired_chunks),

            "chunks": [c.model_dump() for c in repaired_chunks] if not job_id else None,

        },

        message=(

            f"ترمیم معنایی با موفقیت انجام شد: {report.repaired_chunks_count} قطعه از {report.total_chunks} قطعه "

            f"اصلاح شد ({report.repairs_applied_count} عملیات اعمال شد، {re_embedded_count} بردار مجدداً تولید شد)."

        ),
    )





# ---------------------------------------------------------------------------

# POST /api/ai/embed

# ---------------------------------------------------------------------------



@router.post("/embed", response_model=ApiResponse)
async def embed_chunks(request: dict[str, Any], req: Request) -> ApiResponse:
    """Generate embeddings for the chunks of a job using OpenAI.

    Requires NEXORA_OPENAI_API_KEY to be set or workspace BYOK.

    Request body:
        job_id (str): Job identifier (must have chunks stored first via /chunk).
    """

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    api_key = _require_api_key(tenant_id)
    manager = get_manager()
    settings = get_settings()



    job_id = request.get("job_id", "").strip()

    if not job_id:

        raise HTTPException(status_code=400, detail="job_id is required.")



    chunks = manager.get_chunks(job_id)

    if not chunks:

        raise HTTPException(

            status_code=400,

            detail=(

                "این کار هنوز قطعه‌ای ندارد. "

                "ابتدا عملیات تقطیع (/api/ai/chunk) را انجام دهید."

            ),

        )



    if tenant_id:
        from app.services.quota_enforcer import get_quota_enforcer
        try:
            get_quota_enforcer().check_embeddings(tenant_id, len(chunks))
        except ValueError as q_err:
            raise HTTPException(status_code=429, detail=str(q_err))

    try:

        embedder = EmbeddingService(

            api_key=api_key,

            base_url=settings.openai_base_url or None,

            model=settings.embedding_model,

        )

        stats = await embedder.embed_chunks(chunks)



        # Persist updated chunks (with embeddings) back into manager
        manager.store_chunks(job_id, chunks)

        # Record usage metering
        if tenant_id and stats.embedded_chunks > 0:
            try:
                from app.services.usage_meter import get_usage_meter
                get_usage_meter().record(
                    tenant_id,
                    "embeddings_generated",
                    stats.embedded_chunks,
                    job_id=job_id,
                    idempotency_key=f"embeddings_generated:{job_id}",
                )
            except Exception as u_err:
                logger.warning("Could not record embeddings usage: %s", u_err)



        return ApiResponse.ok(

            data={

                "job_id": job_id,

                "total_chunks": stats.total_chunks,

                "embedded_chunks": stats.embedded_chunks,

                "failed_chunks": stats.failed_chunks,

                "model": stats.model,

                "total_tokens": stats.total_tokens,

            },

            message=f"جاسازی بردار با موفقیت انجام شد: {stats.embedded_chunks} قطعه از {stats.total_chunks}.",

        )



    except HTTPException:

        raise

    except Exception as exc:

        safe_msg = sanitize_secret_leakage(str(exc), secrets=[api_key])

        logger.exception("Embedding failed for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در عملیات جاسازی بردار: {safe_msg}")





# ---------------------------------------------------------------------------

# POST /api/ai/enhance

# ---------------------------------------------------------------------------



@router.post("/enhance", response_model=ApiResponse)
async def enhance_documents(request: dict[str, Any], req: Request) -> ApiResponse:
    """Enrich extracted documents with LLM-generated RAG metadata.

    Requires NEXORA_OPENAI_API_KEY to be set or workspace BYOK.

    Request body:
        job_id (str): Extraction job identifier.
    """

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    api_key = _require_api_key(tenant_id)
    manager = get_manager()
    settings = get_settings()



    job_id = request.get("job_id", "").strip()

    if not job_id:

        raise HTTPException(status_code=400, detail="job_id is required.")



    documents = manager.get_documents(job_id)

    if not documents:

        raise HTTPException(

            status_code=400,

            detail="This job has no extracted documents yet. Perform extraction first.",

        )



    eligible = [d for d in documents if d.has_content]

    if not eligible:

        raise HTTPException(

            status_code=400,

            detail="هیچ سند موفق و دارای محتوایی برای بهبود RAG پیدا نشد.",

        )



    try:

        enhancer = RAGEnhancer(

            api_key=api_key,

            base_url=settings.openai_base_url or None,

            model=settings.llm_model,

            concurrency=settings.ai_concurrency,

        )

        results = await enhancer.enhance_documents(eligible)



        # Store RAG metadata on the job for export

        manager.store_rag_metadata(job_id, results)

        total_tokens = sum(
            int((r.get("usage") or {}).get("prompt_tokens", 0)) + int((r.get("usage") or {}).get("completion_tokens", 0))
            for r in results
            if isinstance(r, dict)
        )
        if tenant_id and total_tokens > 0:
            try:
                from app.services.usage_meter import get_usage_meter
                get_usage_meter().record(
                    tenant_id,
                    "llm_tokens",
                    total_tokens,
                    job_id=job_id,
                    idempotency_key=f"llm_tokens:{job_id}",
                )
            except Exception as u_err:
                logger.warning("Could not record llm_tokens usage: %s", u_err)



        success_count = sum(1 for r in results if r.get("success"))

        failed_count = len(results) - success_count



        return ApiResponse.ok(

            data={

                "job_id": job_id,

                "total_docs": len(eligible),

                "enhanced_docs": success_count,

                "failed_docs": failed_count,

                "model": settings.llm_model,

            },

            message=f"بهبود RAG با موفقیت انجام شد: {success_count} سند از {len(eligible)} پردازش شد.",

        )



    except HTTPException:

        raise

    except Exception as exc:

        safe_msg = sanitize_secret_leakage(str(exc), secrets=[api_key])

        logger.exception("RAG enhancement failed for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در بهبود RAG: {safe_msg}")





# ---------------------------------------------------------------------------

# POST /api/ai/export

# ---------------------------------------------------------------------------



@router.post("/export")

async def export_ai_data(request: dict[str, Any], req: Request):

    """Export chunks and/or RAG-enhanced data for a job.



    Request body:

        job_id (str): Job identifier.

        format (str): 'jsonl_chunks' | 'json_chunks' | 'json_enhanced'

    """

    import io

    import json as json_lib

    from fastapi.responses import Response





    manager = get_manager()

    settings = get_settings()

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)



    job_id = request.get("job_id", "").strip()

    fmt = request.get("format", "jsonl_chunks").strip().lower()

    if not job_id:

        raise HTTPException(status_code=400, detail="job_id is required.")

    if tenant_id:

        job = manager.get_job(job_id, tenant_id=tenant_id)

        if not job:

            raise HTTPException(status_code=404, detail="Job not found.")



    if fmt in {"jsonl_chunks", "json_chunks"}:

        chunks = manager.get_chunks(job_id)

        if not chunks:

            raise HTTPException(

                status_code=400,

                detail="قطعه‌ای برای این کار وجود ندارد. ابتدا تقطیع انجام دهید.",

            )

        records = [c.model_dump() for c in chunks]



        if fmt == "jsonl_chunks":

            content = "\n".join(json_lib.dumps(r, ensure_ascii=False) for r in records)

            media_type = "application/x-ndjson"

            filename = f"nexora_chunks_{job_id[:8]}.jsonl"

        else:

            content = json_lib.dumps(records, ensure_ascii=False, indent=2)

            media_type = "application/json"

            filename = f"nexora_chunks_{job_id[:8]}.json"



        return Response(

            content=content.encode("utf-8"),

            media_type=media_type,

            headers={"Content-Disposition": f"attachment; filename={filename}"},

        )



    elif fmt in {"json_enhanced", "jsonl_enhanced"}:

        rag_data = manager.get_rag_metadata(job_id, tenant_id=tenant_id)

        if not rag_data:

            raise HTTPException(

                status_code=400,

                detail="داده RAG برای این کار وجود ندارد. ابتدا عملیات بهبود RAG را انجام دهید.",

            )

        documents = manager.get_documents(job_id)

        rag_by_url = {r.get("source_url"): r for r in rag_data if r.get("source_url")}

        

        enhanced_docs = []

        for doc in documents:

            meta = rag_by_url.get(doc.url, {})

            enhanced_docs.append({

                "url": doc.url,

                "final_url": doc.final_url,

                "title": doc.title,

                "summary": meta.get("summary"),

                "keywords": meta.get("keywords", []),

                "topics": meta.get("topics", []),

                "qa_pairs": meta.get("qa_pairs", []),

                "verification_summary": meta.get("verification_summary", {}),

                "content_markdown": doc.content_markdown,

                "content_text": doc.content_text,

                "word_count": doc.word_count,

                "character_count": doc.character_count,

                "language": doc.language,

                "fetched_at": doc.fetched_at.isoformat() if doc.fetched_at else None,

                "rag_enhanced": bool(meta.get("success")),

            })



        if fmt == "jsonl_enhanced":

            content = "\n".join(json_lib.dumps(d, ensure_ascii=False) for d in enhanced_docs)

            media_type = "application/x-ndjson"

            filename = f"nexora_rag_enhanced_{job_id[:8]}.jsonl"

        else:

            content = json_lib.dumps(enhanced_docs, ensure_ascii=False, indent=2)

            media_type = "application/json"

            filename = f"nexora_rag_enhanced_{job_id[:8]}.json"



        return Response(

            content=content.encode("utf-8"),

            media_type=media_type,

            headers={"Content-Disposition": f"attachment; filename={filename}"},

        )



    elif fmt in {"markdown_enhanced", "md_enhanced"}:

        import zipfile

        from urllib.parse import urlparse

        rag_data = manager.get_rag_metadata(job_id)

        if not rag_data:

            raise HTTPException(

                status_code=400,

                detail="داده RAG برای این کار وجود ندارد. ابتدا عملیات بهبود RAG را انجام دهید.",

            )

        documents = manager.get_documents(job_id)

        rag_by_url = {r.get("source_url"): r for r in rag_data if r.get("source_url")}



        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

            for idx, doc in enumerate(documents):

                meta = rag_by_url.get(doc.url, {})

                md_content = _build_enhanced_markdown(doc, meta)

                try:

                    host = urlparse(doc.url).netloc.replace(":", "_")

                    path_slug = urlparse(doc.url).path.strip("/").replace("/", "_")

                    base = f"{host}_{path_slug}" if path_slug else f"{host}_page"

                except Exception:

                    base = f"doc_{idx}"

                clean_name = "".join(c for c in base if c.isalnum() or c in "._-")[:60]

                zf.writestr(f"{clean_name}_{idx}.md", md_content)



        zip_buffer.seek(0)

        return Response(

            content=zip_buffer.getvalue(),

            media_type="application/zip",

            headers={

                "Content-Disposition": f"attachment; filename=crawlbot_rag_markdown_{job_id[:8]}.zip"

            },

        )



    else:

        raise HTTPException(

            status_code=400,

            detail=f"فرمت '{fmt}' نامعتبر است. موارد مجاز: jsonl_chunks, json_chunks, json_enhanced, jsonl_enhanced, markdown_enhanced",

        )





def _build_enhanced_markdown(doc, rag_meta: dict) -> str:

    """Build a structured Markdown document with YAML frontmatter and LLM RAG sections."""

    lines = ["---"]

    lines.append(f'url: "{doc.url}"')

    if doc.final_url:

        lines.append(f'final_url: "{doc.final_url}"')

    if doc.title:

        escaped_title = doc.title.replace('\\', '\\\\').replace('"', '\\"')

        lines.append(f'title: "{escaped_title}"')

    if rag_meta.get("summary"):

        escaped_sum = rag_meta["summary"].replace('\\', '\\\\').replace('"', '\\"')

        lines.append(f'summary: "{escaped_sum}"')

    if rag_meta.get("keywords"):

        kws = ", ".join(f'"{k}"' for k in rag_meta["keywords"])

        lines.append(f'keywords: [{kws}]')

    if rag_meta.get("topics"):

        tps = ", ".join(f'"{t}"' for t in rag_meta["topics"])

        lines.append(f'topics: [{tps}]')

    lines.append(f'word_count: {doc.word_count}')

    lines.append("---")

    lines.append("")



    if doc.title:

        lines.append(f"# {doc.title}\n")

    if rag_meta.get("summary"):

        lines.append(f"> **خلاصه محتوا:** {rag_meta['summary']}\n")

    if rag_meta.get("topics"):

        lines.append(f"> **موضوعات:** {', '.join(rag_meta['topics'])}\n")

    if rag_meta.get("keywords"):

        lines.append(f"> **کلیدواژه‌ها:** {', '.join(rag_meta['keywords'])}\n")



    lines.append("\n## متن مستند\n")

    lines.append(doc.content_markdown or doc.content_text or "")



    qa_pairs = rag_meta.get("qa_pairs", [])

    if qa_pairs:

        lines.append("\n\n## پرسش و پاسخ‌های تحلیلی راستی‌آزمایی‌شده (Verified RAG Q&A)\n")

        for i, pair in enumerate(qa_pairs, 1):

            q = pair.get("question", "")

            a = pair.get("answer", "")

            ev = pair.get("evidence", "")

            ver = pair.get("verification", {})

            status_tag = "✅ راستی‌آزمایی شده با متن منبع" if ver.get("status") == "verified" else "⚠️ نیازمند بررسی"

            if q and a:

                lines.append(f"### {i}. {q}\n")

                lines.append(f"{a}\n")

                if ev:

                    lines.append(f"> 🔍 **مستند منبع (Evidence):** «{ev}»\n")

                lines.append(f"> **وضعیت راستی‌آزمایی:** {status_tag}\n")



    return "\n".join(lines)





# ---------------------------------------------------------------------------

# Vector Store Endpoints (Index & Retrieval)

# ---------------------------------------------------------------------------



@router.post("/vector-store/upsert", response_model=ApiResponse)
async def upsert_to_vector_store(request: dict[str, Any], req: Request) -> ApiResponse:
    """Index chunks of a job or direct chunk list into the Vector Store."""
    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    manager = get_manager()
    store = get_vector_store()


    job_id = request.get("job_id", "").strip()
    chunks_data = request.get("chunks")

    chunks_to_upsert = []
    if job_id:
        chunks_to_upsert = manager.get_chunks(job_id)
        if not chunks_to_upsert:
            raise HTTPException(
                status_code=400,
                detail="این کار هنوز قطعه‌ای ندارد. ابتدا عملیات تقطیع را انجام دهید.",
            )
    elif isinstance(chunks_data, list):
        from app.schemas.chunks import DocumentChunk
        chunks_to_upsert = [DocumentChunk.model_validate(c) for c in chunks_data]
    else:
        raise HTTPException(status_code=400, detail="Either job_id or chunks list is required.")

    count = store.upsert_chunks(chunks_to_upsert, tenant_id=tenant_id)
    stats = store.get_stats()

    return ApiResponse.ok(
        data={"upserted_count": count, "store_stats": stats},
        message=f"{count} قطعه با موفقیت در پایگاه دانش برداری (Vector Store) ذخیره و ایندکس شد.",
    )


@router.post("/vector-store/search", response_model=ApiResponse)
async def search_vector_store(request: dict[str, Any], req: Request) -> ApiResponse:
    """Execute semantic, sparse, or hybrid vector search across indexed chunks."""
    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    store = get_vector_store()
    settings = get_settings()

    query = str(request.get("query", "")).strip()

    if not query:

        raise HTTPException(status_code=400, detail="متن پرسش (query) الزامی است.")



    top_k = int(request.get("top_k", 5))

    category = request.get("category") or None

    source_url = request.get("source_url") or None

    min_score = float(request.get("min_score")) if request.get("min_score") is not None else 0.001

    hybrid = bool(request.get("hybrid", True))

    alpha = float(request.get("alpha", 0.7))

    expand_neighbors = bool(request.get("expand_neighbors", False))



    start_time = time.perf_counter()

    query_vector = None



    # If OpenAI API key is set and hybrid/dense search is requested, compute query embedding

    api_key = _get_api_key_optional(tenant_id)

    if api_key and hybrid and store.total_vectors > 0:

        try:

            embedder = EmbeddingService(

                api_key=api_key,

                base_url=settings.openai_base_url or None,

                model=settings.embedding_model,

            )

            from app.schemas.chunks import DocumentChunk

            temp_chunk = DocumentChunk(

                chunk_id="q",

                source_url="",

                chunk_index=0,

                total_chunks=1,

                text=query,

                char_count=len(query),

                word_count=len(query.split()),

            )

            await embedder.embed_chunks([temp_chunk])

            query_vector = temp_chunk.embedding

        except Exception as exc:

            logger.warning("Could not compute dense query vector, falling back to lexical BM25: %s", exc)



    results = store.search(
        query=query,
        query_vector=query_vector,
        top_k=top_k,
        category=category,
        source_url=source_url,
        min_score=min_score,
        hybrid=hybrid,
        alpha=alpha,
        expand_neighbors=expand_neighbors,
        tenant_id=tenant_id,
    )

    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)



    return ApiResponse.ok(

        data={

            "query": query,

            "total_results": len(results),

            "latency_ms": latency_ms,

            "dense_enabled": query_vector is not None,

            "results": [r.model_dump(mode="json") for r in results],

        },

        message=f"{len(results)} نتیجه بازیابی شد (زمان: {latency_ms}ms).",
    )





@router.get("/vector-store/stats", response_model=ApiResponse)

async def get_vector_store_stats() -> ApiResponse:

    """Return vector store statistics, total vectors, and category distribution."""

    store = get_vector_store()

    return ApiResponse.ok(

        data=store.get_stats(),

        message="آمار پایگاه دانش برداری (Vector Store)",
    )





@router.delete("/vector-store/clear", response_model=ApiResponse)
async def clear_vector_store(
    req: Request,
    document_id: Optional[str] = None,
    source_url: Optional[str] = None,
) -> ApiResponse:
    """Delete chunks from vector store by document_id, source_url, or clear all for tenant."""
    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    store = get_vector_store()


    if source_url:
        deleted = store.delete_by_url(source_url, tenant_id=tenant_id)
        return ApiResponse.ok(
            data={"deleted_count": deleted},
            message=f"{deleted} قطعه متعلق به آدرس {source_url} حذف شد.",
        )
    if document_id:
        deleted = store.delete_by_document_id(document_id, tenant_id=tenant_id)
        return ApiResponse.ok(
            data={"deleted_count": deleted},
            message=f"{deleted} قطعه متعلق به سند {document_id} حذف شد.",
        )

    deleted = store.clear(tenant_id=tenant_id)
    return ApiResponse.ok(
        data={"deleted_count": deleted},
        message="پایگاه دانش برداری با موفقیت پاکسازی شد.",
    )







# ---------------------------------------------------------------------------

# Section A: Stage Inspection Endpoints

# ---------------------------------------------------------------------------



@router.get("/stages/{job_id}", response_model=ApiResponse)

async def get_job_stages(

    job_id: str,

    req: Request,

    url: Optional[str] = None,

    doc_index: int = 0,

) -> ApiResponse:

    """Retrieve stage-by-stage progression and diffs for a job's documents."""

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

    try:

        data = dataset_studio.get_stages(job_id, url=url, doc_index=doc_index, tenant_id=tenant_id)

        return ApiResponse.ok(data=data, message="وضعیت مراحل پردازش دریافت شد.")

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed getting stages for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در دریافت مراحل پردازش: {str(exc)}")





# ---------------------------------------------------------------------------

# Section B: Chunk Review & Editor Endpoints

# ---------------------------------------------------------------------------



@router.get("/chunks/{job_id}", response_model=ApiResponse)

async def get_job_chunks(

    job_id: str,

    req: Request,

    query: Optional[str] = None,

    quality: Optional[str] = None,

    category: Optional[str] = None,

    source_url: Optional[str] = None,

    language: Optional[str] = None,

    user_edited: Optional[bool] = None,

    page: int = 1,

    page_size: int = 20,

) -> ApiResponse:

    """Search, filter, and paginate chunks of a dataset."""

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

    try:

        result = dataset_studio.query_chunks(

            job_id=job_id,

            query=query,

            quality=quality,

            category=category,

            source_url=source_url,

            language=language,

            user_edited=user_edited,

            page=page,

            page_size=page_size,

            tenant_id=tenant_id,

        )

        return ApiResponse.ok(data=result, message="قطعات با موفقیت دریافت شدند.")

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))





@router.post("/chunks/{job_id}/update", response_model=ApiResponse)

async def update_job_chunk(job_id: str, request: dict[str, Any], req: Request) -> ApiResponse:

    """Update text, heading_context, category, or metadata of a single chunk."""

    chunk_id = str(request.get("chunk_id", "")).strip()

    if not chunk_id:

        raise HTTPException(status_code=400, detail="شناسه قطعه (chunk_id) الزامی است.")



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

        result = dataset_studio.update_chunk(

            job_id=job_id,

            chunk_id=chunk_id,

            text=request.get("text"),

            heading_context=request.get("heading_context"),

            category=request.get("category"),

            metadata=request.get("metadata"),

            tenant_id=tenant_id,

        )

        msg = "قطعه با موفقیت به‌روزرسانی شد."

        if result.get("embedding_invalidated"):

            msg += " به دلیل تغییر متن، بردار این قطعه نامعتبر شد و نیازمند جاسازی مجدد است."

        else:

            msg += " از آنجا که تنها متاداده تغییر کرد، بردار فعلی حفظ گردید (صرفه‌جویی در هزینه)."

        return ApiResponse.ok(data=result, message=msg)

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to update chunk %s", chunk_id)

        raise HTTPException(status_code=500, detail=f"خطا در ویرایش قطعه: {str(exc)}")





@router.post("/chunks/{job_id}/merge", response_model=ApiResponse)

async def merge_job_chunks(job_id: str, request: dict[str, Any], req: Request) -> ApiResponse:

    """Merge two or more chunks into a single unified chunk."""

    chunk_ids = request.get("chunk_ids", [])

    if not isinstance(chunk_ids, list) or len(chunk_ids) < 2:

        raise HTTPException(status_code=400, detail="ارسال حداقل دو شناسه قطعه برای ادغام الزامی است.")



    separator = str(request.get("separator", "\n\n"))

    heading_context = request.get("heading_context")

    category = request.get("category")



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

        result = dataset_studio.merge_chunks(

            job_id=job_id,

            chunk_ids=chunk_ids,

            separator=separator,

            heading_context=heading_context,

            category=category,

            tenant_id=tenant_id,

        )

        return ApiResponse.ok(data=result, message=f"{len(chunk_ids)} قطعه با موفقیت ادغام شدند.")

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to merge chunks for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در ادغام قطعات: {str(exc)}")





@router.post("/chunks/{job_id}/split", response_model=ApiResponse)

async def split_job_chunk(job_id: str, request: dict[str, Any], req: Request) -> ApiResponse:

    """Split a single chunk into multiple smaller chunks."""

    chunk_id = str(request.get("chunk_id", "")).strip()

    if not chunk_id:

        raise HTTPException(status_code=400, detail="شناسه قطعه (chunk_id) الزامی است.")



    split_points = request.get("split_points")

    separator = request.get("separator")

    max_chars = request.get("max_chars")



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

        result = dataset_studio.split_chunk(

            job_id=job_id,

            chunk_id=chunk_id,

            split_points=split_points,

            separator=separator,

            max_chars=max_chars,

            tenant_id=tenant_id,

        )

        return ApiResponse.ok(

            data=result,

            message=f"قطعه {chunk_id} با موفقیت به {len(result['split_chunks'])} قطعه مجزا تفکیک شد.",

        )

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to split chunk %s", chunk_id)

        raise HTTPException(status_code=500, detail=f"خطا در تفکیک قطعه: {str(exc)}")





@router.post("/chunks/{job_id}/revert", response_model=ApiResponse)

async def revert_job_chunk(job_id: str, request: dict[str, Any], req: Request) -> ApiResponse:

    """Undo the last edit for a chunk and restore its previous state."""

    chunk_id = str(request.get("chunk_id", "")).strip()

    if not chunk_id:

        raise HTTPException(status_code=400, detail="شناسه قطعه (chunk_id) الزامی است.")



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
        result = dataset_studio.revert_chunk(job_id=job_id, chunk_id=chunk_id, tenant_id=tenant_id)

        return ApiResponse.ok(data=result, message="آخرین ویرایش قطعه با موفقیت بازگردانی (Undo) شد.")

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to revert chunk %s", chunk_id)

        raise HTTPException(status_code=500, detail=f"خطا در بازگردانی قطعه: {str(exc)}")





# ---------------------------------------------------------------------------

# Section C: Comprehensive Data Quality Report

# ---------------------------------------------------------------------------



@router.get("/dataset/{job_id}/quality-report", response_model=ApiResponse)

async def get_dataset_quality_report(job_id: str, req: Request) -> ApiResponse:

    """Generate detailed telemetry and quality assessment report for a dataset."""

    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
        report = dataset_studio.generate_quality_report(job_id, tenant_id=tenant_id)

        return ApiResponse.ok(data=report, message="گزارش جامع کیفیت داده با موفقیت تهیه شد.")

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed generating quality report for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در تولید گزارش کیفیت: {str(exc)}")





# ---------------------------------------------------------------------------

# Section D: Dataset Versioning & Semantic Diff

# ---------------------------------------------------------------------------



@router.get("/dataset/{job_id}/versions", response_model=ApiResponse)

async def list_dataset_versions(job_id: str, req: Request) -> ApiResponse:

    """List all version snapshots created for a dataset."""

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

    try:

        snapshots = dataset_studio.list_snapshots(job_id, tenant_id=tenant_id)

        return ApiResponse.ok(data={"snapshots": snapshots}, message="لیست نسخه‌های ذخیره‌شده")

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))





@router.post("/dataset/{job_id}/versions/snapshot", response_model=ApiResponse)

async def create_dataset_snapshot(job_id: str, request: dict[str, Any], req: Request) -> ApiResponse:

    """Create a persistent immutable version snapshot for current chunks."""

    version_label = request.get("version_label")

    description = request.get("description")



    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

    try:

        snapshot = dataset_studio.create_snapshot(

            job_id=job_id,

            version_label=version_label,

            description=description,

            tenant_id=tenant_id,

        )

        return ApiResponse.ok(

            data=snapshot,

            message=f"نسخه {snapshot['version']} با موفقیت ثبت شد (اثرانگشت: {snapshot['aggregate_hash'][:8]}).",

        )

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed creating snapshot for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در ثبت نسخه داده: {str(exc)}")





@router.post("/dataset/{job_id}/versions/diff", response_model=ApiResponse)

async def diff_dataset_versions(job_id: str, request: dict[str, Any], req: Request) -> ApiResponse:

    """Compare two version snapshots or a snapshot against current state."""

    v1 = str(request.get("v1", "")).strip()

    v2 = str(request.get("v2", "current")).strip()



    if not v1:

        raise HTTPException(status_code=400, detail="نسخه مبدا (v1) الزامی است.")



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
        diff_result = dataset_studio.diff_snapshots(job_id=job_id, v1_label=v1, v2_label=v2, tenant_id=tenant_id)

        summary = diff_result["summary"]

        msg = (

            f"مقایسه نسخه {v1} و {v2}: {summary['modified_count']} تغییر یافته "

            f"({summary['re_embedding_needed_count']} نیازمند بردار جدید، "

            f"{summary['cost_saving_retained_embeddings_count']} بردار بدون تغییر و حفظ‌شده)."

        )

        return ApiResponse.ok(data=diff_result, message=msg)

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to diff versions for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در مقایسه نسخه‌ها: {str(exc)}")





# ---------------------------------------------------------------------------

# Section F: Export Manifest Endpoints

# ---------------------------------------------------------------------------



@router.get("/dataset/{job_id}/manifest", response_model=ApiResponse)

async def get_dataset_manifest(job_id: str, req: Request, version: Optional[str] = None) -> ApiResponse:

    """Retrieve standard manifest.json metadata for dataset export."""

    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
        manifest = dataset_studio.generate_manifest(job_id, version_label=version, tenant_id=tenant_id)

        return ApiResponse.ok(data=manifest, message="مانیفست مجموعه داده با موفقیت تهیه شد.")

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to generate manifest for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در تولید مانیفست: {str(exc)}")





@router.get("/dataset/{job_id}/manifest/download")

async def download_dataset_manifest(job_id: str, req: Request, version: Optional[str] = None):

    """Download manifest.json as a standalone JSON file."""

    import json as json_lib

    from fastapi.responses import Response



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
        manifest = dataset_studio.generate_manifest(job_id, version_label=version, tenant_id=tenant_id)

        content = json_lib.dumps(manifest, default=str, ensure_ascii=False, indent=2)

        filename = f"manifest_{job_id[:8]}.json"

        return Response(

            content=content.encode("utf-8"),

            media_type="application/json",

            headers={"Content-Disposition": f"attachment; filename={filename}"},

        )

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to download manifest for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در دانلود مانیفست: {str(exc)}")





# ---------------------------------------------------------------------------

# Section G: Phase 3 - RAG Evaluation, Playground & Debugging Endpoints

# ---------------------------------------------------------------------------



@router.post("/eval/playground", response_model=ApiResponse)

async def eval_search_playground(request: dict[str, Any], req: Request) -> ApiResponse:

    """Execute interactive retrieval playground search with score scale transparency."""

    job_id = str(request.get("job_id", "")).strip()

    query = str(request.get("query", "")).strip()

    if not job_id:

        raise HTTPException(status_code=400, detail="job_id is required.")

    if not query:

        raise HTTPException(status_code=400, detail="متن پرسش (query) الزامی است.")



    method = request.get("method", "hybrid")

    if method not in ("dense", "bm25", "hybrid"):

        raise HTTPException(status_code=400, detail="روش جست‌وجو باید یکی از dense، bm25 یا hybrid باشد.")



    top_k = int(request.get("top_k", 5))

    alpha = float(request.get("alpha", 0.7))

    min_score = float(request.get("min_score", 0.0))

    category = request.get("category") or None

    source_url = request.get("source_url") or None

    language = request.get("language") or None

    expand_neighbors = bool(request.get("expand_neighbors", False))

    version_label = request.get("version_label") or None



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

        result = await rag_evaluator.search_playground(

            job_id=job_id,

            query=query,

            method=method,

            top_k=top_k,

            alpha=alpha,

            min_score=min_score,

            category=category,

            source_url=source_url,

            language=language,

            expand_neighbors=expand_neighbors,

            version_label=version_label,

            tenant_id=tenant_id,

        )

        return ApiResponse.ok(

            data=result.model_dump(mode="json"),

            message=f"{result.total_returned} نتیجه بازیابی شد (زمان: {result.latency_ms}ms).",

        )

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Playground search failed for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در جست‌وجوی آزمایشی: {str(exc)}")





@router.post("/eval/playground/compare", response_model=ApiResponse)

async def eval_compare_methods(request: dict[str, Any], req: Request) -> ApiResponse:

    """Execute side-by-side comparison of Dense, BM25, and Hybrid for a query."""

    job_id = str(request.get("job_id", "")).strip()

    query = str(request.get("query", "")).strip()

    if not job_id:

        raise HTTPException(status_code=400, detail="job_id is required.")

    if not query:

        raise HTTPException(status_code=400, detail="متن پرسش (query) الزامی است.")



    top_k = int(request.get("top_k", 5))

    alpha = float(request.get("alpha", 0.7))

    version_label = request.get("version_label") or None



    try:

        result = await rag_evaluator.compare_methods(

            job_id=job_id,

            query=query,

            top_k=top_k,

            alpha=alpha,

            version_label=version_label,

        )

        return ApiResponse.ok(

            data=result.model_dump(mode="json"),

            message="مقایسه خروجی روش‌های بازیابی با موفقیت انجام شد.",

        )

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Method comparison failed for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در مقایسه روش‌های بازیابی: {str(exc)}")





@router.post("/eval/playground/debug", response_model=ApiResponse)

async def eval_debug_retrieval(request: dict[str, Any], req: Request) -> ApiResponse:

    """Perform step-by-step retrieval debugging and trace candidate filtering."""

    job_id = str(request.get("job_id", "")).strip()

    query = str(request.get("query", "")).strip()

    if not job_id:

        raise HTTPException(status_code=400, detail="job_id is required.")

    if not query:

        raise HTTPException(status_code=400, detail="متن پرسش (query) الزامی است.")



    method = request.get("method", "hybrid")

    top_k = int(request.get("top_k", 5))

    alpha = float(request.get("alpha", 0.7))

    min_score = float(request.get("min_score", 0.0))

    category = request.get("category") or None

    source_url = request.get("source_url") or None

    language = request.get("language") or None

    expand_neighbors = bool(request.get("expand_neighbors", False))

    version_label = request.get("version_label") or None



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

        trace = await rag_evaluator.debug_retrieval(

            job_id=job_id,

            query=query,

            method=method,

            top_k=top_k,

            alpha=alpha,

            min_score=min_score,

            category=category,

            source_url=source_url,

            language=language,

            expand_neighbors=expand_neighbors,

            version_label=version_label,

            tenant_id=tenant_id,

        )

        return ApiResponse.ok(

            data=trace.model_dump(mode="json"),

            message="ردیابی و عیب‌یابی مسیر بازیابی با موفقیت ثبت شد.",

        )

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Retrieval debugging failed for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"خطا در عیب‌یابی بازیابی: {str(exc)}")





@router.post("/eval/datasets", response_model=ApiResponse)

async def create_eval_dataset(request: dict[str, Any], req: Request) -> ApiResponse:

    """Create a new evaluation dataset container."""

    name = str(request.get("name", "")).strip()

    if not name:

        raise HTTPException(status_code=400, detail="نام مجموعه ارزیابی (name) الزامی است.")



    description = request.get("description")

    job_id = request.get("job_id")



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
        dataset = rag_evaluator.create_dataset(name=name, description=description, job_id=job_id, tenant_id=tenant_id)

        return ApiResponse.ok(

            data=dataset.model_dump(mode="json"),

            message=f"مجموعه ارزیابی '{dataset.name}' با موفقیت ساخته شد.",

        )

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to create eval dataset")

        raise HTTPException(status_code=500, detail=f"خطا در ساخت مجموعه ارزیابی: {str(exc)}")





@router.get("/eval/datasets", response_model=ApiResponse)

async def list_eval_datasets(req: Request) -> ApiResponse:

    """List all evaluation datasets."""

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

    datasets = rag_evaluator.list_datasets(tenant_id=tenant_id)

    return ApiResponse.ok(data=datasets, message=f"{len(datasets)} مجموعه ارزیابی دریافت شد.")





@router.get("/eval/datasets/{dataset_id}", response_model=ApiResponse)

async def get_eval_dataset(dataset_id: str, req: Request) -> ApiResponse:

    """Retrieve full evaluation dataset with its samples."""

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

    try:

        dataset = rag_evaluator.get_dataset(dataset_id, tenant_id=tenant_id)

        return ApiResponse.ok(data=dataset.model_dump(mode="json"), message="اطلاعات مجموعه ارزیابی دریافت شد.")

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))





@router.delete("/eval/datasets/{dataset_id}", response_model=ApiResponse)

async def delete_eval_dataset(dataset_id: str, req: Request) -> ApiResponse:

    """Delete an evaluation dataset."""

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

    try:

        deleted = rag_evaluator.delete_dataset(dataset_id, tenant_id=tenant_id)

        if not deleted:

            raise HTTPException(status_code=404, detail="Evaluation dataset not found.")

        return ApiResponse.ok(data={"deleted": True}, message="مجموعه ارزیابی با موفقیت حذف شد.")

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))





@router.post("/eval/datasets/{dataset_id}/samples", response_model=ApiResponse)

async def add_eval_sample(dataset_id: str, request: dict[str, Any], req: Request) -> ApiResponse:

    """Add a query sample to an evaluation dataset."""

    question = str(request.get("question", "")).strip()

    job_id = str(request.get("job_id", "")).strip()

    if not question:

        raise HTTPException(status_code=400, detail="متن پرسش (question) الزامی است.")

    if not job_id:

        raise HTTPException(status_code=400, detail="شناسه کار مرتبط (job_id) الزامی است.")



    version_label = request.get("version_label") or None

    expected_chunk_ids = request.get("expected_chunk_ids") or []

    expected_source_urls = request.get("expected_source_urls") or []

    relevance_labels = request.get("relevance_labels") or {}

    notes = request.get("notes")

    origin = request.get("origin", "manual")

    human_reviewed = bool(request.get("human_reviewed", False))



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

        sample = rag_evaluator.add_sample(

            dataset_id=dataset_id,

            question=question,

            job_id=job_id,

            version_label=version_label,

            expected_chunk_ids=expected_chunk_ids,

            expected_source_urls=expected_source_urls,

            relevance_labels=relevance_labels,

            notes=notes,

            origin=origin,

            human_reviewed=human_reviewed,

            tenant_id=tenant_id,

        )

        return ApiResponse.ok(data=sample.model_dump(mode="json"), message="نمونه ارزیابی با موفقیت اضافه شد.")

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to add sample to dataset %s", dataset_id)

        raise HTTPException(status_code=500, detail=f"خطا در افزودن نمونه ارزیابی: {str(exc)}")





@router.put("/eval/datasets/{dataset_id}/samples/{sample_id}", response_model=ApiResponse)

async def update_eval_sample(dataset_id: str, sample_id: str, request: dict[str, Any], req: Request) -> ApiResponse:

    """Update labels or human review status for an evaluation sample."""

    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

        sample = rag_evaluator.update_sample(

            dataset_id=dataset_id,

            sample_id=sample_id,

            expected_chunk_ids=request.get("expected_chunk_ids"),

            expected_source_urls=request.get("expected_source_urls"),

            relevance_labels=request.get("relevance_labels"),

            notes=request.get("notes"),

            human_reviewed=request.get("human_reviewed"),

            tenant_id=tenant_id,

        )

        return ApiResponse.ok(data=sample.model_dump(mode="json"), message="نمونه ارزیابی به‌روزرسانی شد.")

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to update sample %s", sample_id)

        raise HTTPException(status_code=500, detail=f"خطا در به‌روزرسانی نمونه: {str(exc)}")





@router.delete("/eval/datasets/{dataset_id}/samples/{sample_id}", response_model=ApiResponse)

async def delete_eval_sample(dataset_id: str, sample_id: str, req: Request) -> ApiResponse:

    """Delete a sample from an evaluation dataset."""

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

    try:

        deleted = rag_evaluator.delete_sample(dataset_id, sample_id, tenant_id=tenant_id)

        if not deleted:

            raise HTTPException(status_code=404, detail="نمونه ارزیابی یافت نشد.")

        return ApiResponse.ok(data={"deleted": True}, message="نمونه ارزیابی حذف شد.")

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))





@router.post("/eval/datasets/{dataset_id}/import-synthetic-qa", response_model=ApiResponse)

async def import_synthetic_qa(dataset_id: str, request: dict[str, Any], req: Request) -> ApiResponse:

    """Import synthetic QA pairs from job metadata with explicit unreviewed LLM origin."""

    job_id = str(request.get("job_id", "")).strip()

    if not job_id:

        raise HTTPException(status_code=400, detail="job_id is required.")

    max_samples = int(request.get("max_samples", 10))



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

        imported = rag_evaluator.import_synthetic_qa(

            dataset_id=dataset_id,

            job_id=job_id,

            max_samples=max_samples,

            tenant_id=tenant_id,

        )

        return ApiResponse.ok(

            data={"imported_count": len(imported), "samples": [s.model_dump(mode="json") for s in imported]},

            message=f"{len(imported)} پرسش تولیدشده با هوش مصنوعی (RAG Enhancer) وارد شد. لطفاً پیش از ارزیابی، برچسب‌های مرجع را بازبینی انسانی کنید.",

        )

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to import synthetic QA for job %s", job_id)

        raise HTTPException(status_code=500, detail=f"Error importing synthetic questions: {str(exc)}")





@router.post("/eval/runs", response_model=ApiResponse)

async def execute_eval_run(request: dict[str, Any], req: Request) -> ApiResponse:

    """Execute a formal evaluation run for an entire dataset."""

    dataset_id = str(request.get("dataset_id", "")).strip()

    job_id = str(request.get("job_id", "")).strip()

    if not dataset_id:

        raise HTTPException(status_code=400, detail="dataset_id is required.")

    if not job_id:

        raise HTTPException(status_code=400, detail="job_id is required.")



    version_label = request.get("version_label") or None

    method = request.get("method", "hybrid")

    top_k = int(request.get("top_k", 5))

    alpha = float(request.get("alpha", 0.7))

    min_score = float(request.get("min_score", 0.0))

    category_filter = request.get("category_filter") or None

    source_url_filter = request.get("source_url_filter") or None

    language_filter = request.get("language_filter") or None

    expand_neighbors = bool(request.get("expand_neighbors", False))



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

        run_result = await rag_evaluator.execute_run(

            dataset_id=dataset_id,

            job_id=job_id,

            version_label=version_label,

            method=method,

            top_k=top_k,

            alpha=alpha,

            min_score=min_score,

            category_filter=category_filter,

            source_url_filter=source_url_filter,

            language_filter=language_filter,

            expand_neighbors=expand_neighbors,

            tenant_id=tenant_id,

        )

        return ApiResponse.ok(

            data=run_result.model_dump(mode="json"),

            message=f"اجرای ارزیابی {run_result.run_id} با {run_result.total_samples} نمونه به پایان رسید.",

        )

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Evaluation run failed for dataset %s", dataset_id)

        raise HTTPException(status_code=500, detail=f"Error running evaluation: {str(exc)}")





@router.get("/eval/runs", response_model=ApiResponse)

async def list_eval_runs(req: Request) -> ApiResponse:

    """List summary of all executed evaluation runs."""

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

    runs = rag_evaluator.list_runs(tenant_id=tenant_id)

    return ApiResponse.ok(data=runs, message=f"{len(runs)} اجرای ارزیابی دریافت شد.")





@router.get("/eval/runs/{run_id}", response_model=ApiResponse)

async def get_eval_run(run_id: str, req: Request) -> ApiResponse:

    """Retrieve full evaluation run result with sample metrics."""

    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)

    try:

        run = rag_evaluator.get_run(run_id, tenant_id=tenant_id)

        return ApiResponse.ok(data=run.model_dump(mode="json"), message="Evaluation run results retrieved.")

    except ValueError as ve:

        raise HTTPException(status_code=404, detail=str(ve))





@router.post("/eval/runs/compare", response_model=ApiResponse)

async def compare_eval_runs(request: dict[str, Any], req: Request) -> ApiResponse:

    """Compare two evaluation runs to detect metric deltas and improved/regressed queries."""

    run_id_a = str(request.get("run_id_a", "")).strip()

    run_id_b = str(request.get("run_id_b", "")).strip()

    if not run_id_a or not run_id_b:

        raise HTTPException(status_code=400, detail="Both run_id_a and run_id_b are required.")



    try:

        tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)



        comparison = rag_evaluator.compare_runs(run_id_a, run_id_b, tenant_id=tenant_id)

        return ApiResponse.ok(

            data=comparison.model_dump(mode="json"),

            message="Comparison of two evaluation runs completed successfully.",

        )

    except ValueError as ve:

        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as exc:

        logger.exception("Failed to compare runs %s and %s", run_id_a, run_id_b)

        raise HTTPException(status_code=500, detail=f"Error comparing runs: {str(exc)}")


# ==============================================================================
# PHASE 4: INCREMENTAL PROCESSING & VECTOR DATABASE INTEGRATIONS
# ==============================================================================

from app.schemas.incremental import IncrementalSyncRequest
from app.services.incremental_processor import IncrementalProcessor
from app.services.vector_integrations import QdrantSyncService, export_to_chroma_format, export_to_pinecone_format

incremental_processor = IncrementalProcessor()


@router.post("/incremental/sync", response_model=ApiResponse)
async def sync_incremental_project(request: IncrementalSyncRequest, req: Request) -> ApiResponse:
    """Execute an incremental crawl sync: identify new, modified, unchanged and deleted documents."""
    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    try:
        report = incremental_processor.process_sync(request, tenant_id=tenant_id)
        return ApiResponse.ok(
            data=report.model_dump(mode="json"),
            message=f"همگام‌سازی افزایشی برای پروژه '{request.project_id}' با موفقیت انجام شد.",
        )
    except Exception as exc:
        logger.exception("Incremental sync failed for project %s", request.project_id)
        raise HTTPException(status_code=500, detail=f"Error in incremental sync: {str(exc)}")


@router.get("/incremental/manifest/{project_id}", response_model=ApiResponse)
async def get_incremental_manifest(project_id: str, req: Request) -> ApiResponse:
    """Retrieve the stored incremental state manifest for a project."""
    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    try:
        manifest = incremental_processor.load_manifest(project_id, tenant_id=tenant_id)
        return ApiResponse.ok(
            data=manifest.model_dump(mode="json"),
            message="Incremental status manifest retrieved.",
        )
    except Exception as exc:
        logger.exception("Failed to load incremental manifest for %s", project_id)
        raise HTTPException(status_code=500, detail=f"Error fetching incremental manifest: {str(exc)}")


@router.post("/vector-export/qdrant", response_model=ApiResponse)
async def export_to_qdrant(request: dict[str, Any], req: Request) -> ApiResponse:
    """Export and synchronize job chunks with embeddings directly to Qdrant vector database."""
    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    job_id = str(request.get("job_id", "")).strip()
    collection_name = str(request.get("collection_name", "nexora_chunks")).strip()
    qdrant_url = str(request.get("qdrant_url", "")).strip() or None
    api_key = str(request.get("api_key", "")).strip() or None
    batch_size = int(request.get("batch_size", 64))

    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required.")

    if tenant_id:
        job = job_manager.get_job(job_id, tenant_id=tenant_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    chunks = job_manager.get_job_chunks(job_id, tenant_id=tenant_id)
    if not chunks:
        raise HTTPException(status_code=404, detail=f"No chunks found for job '{job_id}'.")

    settings = get_settings()
    sync_service = QdrantSyncService(
        base_url=qdrant_url or settings.qdrant_url,
        api_key=api_key or settings.qdrant_api_key,
    )

    result = sync_service.sync_chunks(
        collection_name=collection_name,
        chunks=chunks,
        batch_size=batch_size,
    )

    if not result.success:
        return ApiResponse.error(
            message=result.message,
            data=result.model_dump(mode="json"),
        )

    return ApiResponse.ok(
        data=result.model_dump(mode="json"),
        message=result.message,
    )


@router.get("/vector-export/chroma/{job_id}", response_model=ApiResponse)
async def export_to_chroma(job_id: str, req: Request) -> ApiResponse:
    """Export job chunks formatted for standard ChromaDB collection.add() payload."""
    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    if tenant_id:
        job = job_manager.get_job(job_id, tenant_id=tenant_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    chunks = job_manager.get_job_chunks(job_id, tenant_id=tenant_id)
    if not chunks:
        raise HTTPException(status_code=404, detail=f"No chunks found for job '{job_id}'.")

    chroma_data = export_to_chroma_format(chunks)
    return ApiResponse.ok(
        data=chroma_data,
        message=f"خروجی استاندارد ChromaDB برای {chroma_data['total_records']} چانک تولید شد.",
    )


@router.get("/vector-export/pinecone/{job_id}", response_model=ApiResponse)
async def export_to_pinecone(job_id: str, req: Request, namespace: Optional[str] = None) -> ApiResponse:
    """Export job chunks formatted for standard Pinecone index.upsert() payload."""
    tenant_id = getattr(req.state, "authenticated_workspace_id", None) or getattr(req.state, "tenant_id", None) or getattr(req.state, "workspace_id", None)
    if tenant_id:
        job = job_manager.get_job(job_id, tenant_id=tenant_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    chunks = job_manager.get_job_chunks(job_id, tenant_id=tenant_id)
    if not chunks:
        raise HTTPException(status_code=404, detail=f"No chunks found for job '{job_id}'.")

    pinecone_data = export_to_pinecone_format(chunks, namespace=namespace or "")
    return ApiResponse.ok(
        data=pinecone_data,
        message=f"خروجی استاندارد Pinecone برای {pinecone_data['total_records']} چانک تولید شد.",
    )
