"""Nexora High-Performance Studio Runner.

Ensures proper Windows ProactorEventLoop configuration for Chromium / Playwright
headless browser subprocesses, starts the FastAPI server, and prints access info.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Critical for Windows: enforce ProactorEventLoop so Playwright & Crawl4AI can spawn Chromium subprocesses
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import uvicorn
from app.core.config import get_settings


def main() -> None:
    """Launch the Nexora Studio application."""
    settings = get_settings()
    print("=" * 60)
    print("  🚀 NEXORA STUDIO — RAG Data Intelligence & Crawler")
    print(f"  🌐 Local GUI:  http://{settings.host}:{settings.port}/")
    print(f"  📚 API Docs:   http://{settings.host}:{settings.port}/docs")
    print(f"  ⚙️  Environment: {settings.app_env}")
    print("=" * 60)

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        loop="asyncio",
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
