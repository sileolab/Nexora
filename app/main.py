"""Universal Website Crawler & RAG Data Extraction Studio - Main Application.

Exposes REST API endpoints and serves the local RTL-friendly GUI.
"""

from __future__ import annotations

import asyncio
import os
import sys
import hmac
from app.core.security import is_safe_identifier
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure Windows ProactorEventLoop is active for subprocess spawning (Playwright, Chromium, Crawl4AI)
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes_discovery, routes_exports, routes_extraction, routes_jobs, routes_ai, routes_files
from app.api import routes_workspaces, routes_admin
from app.core.config import get_settings
from app.core.logging_config import get_logger, setup_logging
from app.jobs.manager import JobManager

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Application factory for Crawlbot."""
    settings = get_settings()
    setup_logging(settings.log_level)

    # Initialize shared JobManager singleton
    manager = JobManager()

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        stop_event = asyncio.Event()

        async def _watchdog_loop():
            while not stop_event.is_set():
                try:
                    await asyncio.sleep(60)
                    from app.services.job_watchdog import get_job_watchdog
                    get_job_watchdog().check_stuck_jobs(manager)
                except asyncio.CancelledError:
                    break
                except Exception as loop_err:
                    logger.warning("Periodic watchdog loop error: %s", loop_err)

        watchdog_task = asyncio.create_task(_watchdog_loop())
        try:
            yield
        finally:
            stop_event.set()
            watchdog_task.cancel()
            try:
                await watchdog_task
            except (asyncio.CancelledError, Exception):
                pass

    app = FastAPI(
        title=f"{settings.app_name} Studio & Developer API",
        description="Intelligent Web Discovery, Cleaning, Chunking, Vectorization, RAG Evaluation & Multi-Tenant SaaS Platform",
        version="5.0.0",
        docs_url="/swagger",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Allow local CORS for testing and development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware: Security Authentication, Tenant Resolution, Rate Limiting, V1 Aliasing & Cache Control
    @app.middleware("http")
    async def api_security_and_v1_middleware(request: Request, call_next):
        path = request.scope.get("path", "")

        # 1. Transparently alias /api/v1/* to /api/*
        if path.startswith("/api/v1/") and path not in ("/api/v1/health", "/api/v1/openapi.json"):
            request.scope["path"] = path.replace("/api/v1/", "/api/", 1)
            path = request.scope["path"]

        # 2. Extract auth credentials & resolve workspace
        x_key = request.headers.get("X-API-Key", "").strip()
        auth_header = request.headers.get("Authorization", "").strip()
        bearer_key = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        token = x_key or bearer_key

        admin_secret = (settings.api_key or "").strip()
        is_master = bool(admin_secret and token and hmac.compare_digest(token, admin_secret))
        request.state.is_master = is_master

        from app.services.workspace_manager import get_workspace_manager
        wm = get_workspace_manager()
        authenticated_ws = None
        if token:
            authenticated_ws = wm.resolve_workspace_by_key(token)

        header_ws = request.headers.get("X-Workspace-Id", "").strip() or None
        if header_ws and not is_safe_identifier(header_ws):
            header_ws = None



        workspace_id = authenticated_ws or header_ws
        request.state.authenticated_workspace_id = authenticated_ws
        request.state.workspace_id = workspace_id
        request.state.tenant_id = workspace_id
        is_workspace_valid = (authenticated_ws is not None)

        # 3. Apply rate limiting per workspace / IP
        from app.core.security import get_rate_limiter
        client_key = workspace_id or (request.client.host if request.client else "unknown")
        is_static = path == "/" or path.startswith("/static/") or path in ("/favicon.ico",)
        if not is_static:
            allowed, retry_after = get_rate_limiter().is_allowed(client_key)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                        "retry_after": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )

        # 4. Enforce Admin route security (SEC-03) - Fail Closed
        if path.startswith("/api/admin"):
            if not admin_secret:
                return JSONResponse(
                    status_code=401,
                    content={
                        "success": False,
                        "message": "Unauthorized: Master admin API key is not configured.",
                        "data": None,
                    },
                )
            if (is_workspace_valid or token.startswith("cbk_")) and not is_master:
                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "message": "Forbidden: Workspace API keys are not permitted to access admin endpoints.",
                        "data": None,
                    },
                )
            if not is_master:
                return JSONResponse(
                    status_code=401,
                    content={
                        "success": False,
                        "message": "Unauthorized: Master admin API key required.",
                        "data": None,
                    },
                )

        # 5. Check API Key security if configured in settings
        if settings.api_key and settings.api_key.strip():
            is_public = (
                path in ("/", "/favicon.ico", "/docs", "/api-docs", "/redoc", "/swagger", "/openapi.json", "/api/health", "/api/v1/health")
                or path.startswith("/static/")
            )
            if not is_public and (path.startswith("/api/") or path.startswith("/api/v1/")):
                if not is_master and not is_workspace_valid:
                    return JSONResponse(
                        status_code=401,
                        content={
                            "success": False,
                            "message": "Unauthorized: Invalid or missing API key. Provide a valid 'X-API-Key' or 'Bearer' token.",
                            "data": None,
                        },
                    )

        response = await call_next(request)
        if path in ("/", "/docs", "/api-docs") or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # Inject dependency into router modules
    routes_discovery.set_job_manager(manager)
    routes_extraction.set_job_manager(manager)
    routes_jobs.set_job_manager(manager)
    routes_exports.set_job_manager(manager)
    routes_ai.set_job_manager(manager)

    # Register routers
    app.include_router(routes_discovery.router)
    app.include_router(routes_extraction.router)
    app.include_router(routes_jobs.router)
    app.include_router(routes_exports.router)
    app.include_router(routes_ai.router)
    app.include_router(routes_files.router)
    app.include_router(routes_workspaces.router)
    app.include_router(routes_admin.router)

    # Inject job manager into admin router
    routes_admin.set_job_manager(manager)

    # Static files setup
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        """Serve the local GUI."""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(
                index_file,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        return {"message": "Nexora API is running, but GUI index.html was not found."}

    @app.get("/docs", include_in_schema=False)
    @app.get("/api-docs", include_in_schema=False)
    async def serve_api_docs():
        """Serve the custom interactive Nexora API Documentation."""
        docs_file = static_dir / "docs.html"
        if docs_file.exists():
            return FileResponse(
                docs_file,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        return {"message": "Nexora API docs.html was not found."}

    @app.get("/health", tags=["system"])
    @app.get("/api/health", tags=["system"])
    @app.get("/api/v1/health", tags=["system"])
    async def health_check():
        """Comprehensive system health and operational readiness status."""
        vstore = getattr(routes_ai, "vector_store", None)
        vstats = vstore.get_stats() if vstore else {"total_chunks": 0}
        
        def _is_active(j: Any) -> bool:
            state = getattr(j, "state", None)
            if state is None and isinstance(j, dict):
                state = j.get("state")
            if hasattr(state, "value"):
                state = state.value
            return str(state).lower() in ("pending", "running")

        active_jobs = [j for j in manager.list_jobs() if _is_active(j)]
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": "4.0.0",
            "env": settings.app_env,
            "active_jobs_count": len(active_jobs),
            "vector_store": vstats,
            "features": {
                "discovery": True,
                "extraction": True,
                "data_studio": True,
                "rag_evaluation": True,
                "incremental_sync": True,
                "qdrant_sync": True,
                "multi_tenant": True,
                "usage_metering": True,
                "byok": True,
            },
        }

    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
