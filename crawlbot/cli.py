"""Crawlbot Command Line Interface (Compatibility Layer - Powered by Nexora)."""

from __future__ import annotations

from nexora.cli import (
    build_parser,
    cmd_chunk,
    cmd_crawl,
    cmd_discover,
    cmd_embed,
    cmd_export,
    cmd_extract,
    cmd_file,
    cmd_ping,
    cmd_quality,
    cmd_search,
    cmd_status,
    cmd_sync,
    cmd_vector_export,
    cmd_wait,
    get_client,
    main,
    print_error,
    print_json,
    print_success,
)

__all__ = [
    "build_parser",
    "main",
    "get_client",
    "cmd_ping",
    "cmd_extract",
    "cmd_discover",
    "cmd_crawl",
    "cmd_status",
    "cmd_wait",
    "cmd_chunk",
    "cmd_embed",
    "cmd_search",
    "cmd_export",
    "cmd_file",
    "cmd_quality",
    "cmd_sync",
    "cmd_vector_export",
    "print_json",
    "print_success",
    "print_error",
]

if __name__ == "__main__":
    main()
