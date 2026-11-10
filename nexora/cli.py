"""Nexora Command Line Interface (CLI).

Provides developer command-line automation for:
1. Health & Ping
2. Single URL extraction
3. Website discovery & crawl jobs
4. Job monitoring & polling
5. Chunking, repairing & embedding
6. Hybrid RAG search
7. Document export (JSONL, CSV, Markdown)
8. Local file processing
9. Incremental sync
10. Vector database export (Qdrant, Chroma, Pinecone)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

from nexora.client import NexoraClient
from nexora.exceptions import NexoraError


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def print_json(data: Any) -> None:
    """Print formatted JSON output to stdout."""
    try:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except UnicodeEncodeError:
        print(json.dumps(data, indent=2, ensure_ascii=True))


def print_success(msg: str) -> None:
    try:
        print(f"\033[92m[OK] {msg}\033[0m")
    except UnicodeEncodeError:
        print(f"[OK] {msg.encode('ascii', errors='replace').decode('ascii')}")


def print_error(msg: str) -> None:
    try:
        print(f"\033[91m[ERROR] {msg}\033[0m", file=sys.stderr)
    except UnicodeEncodeError:
        print(f"[ERROR] {msg.encode('ascii', errors='replace').decode('ascii')}", file=sys.stderr)


def get_client(args: argparse.Namespace) -> NexoraClient:
    url = (
        getattr(args, "url_base", None)
        or os.getenv("NEXORA_BASE_URL")
        or os.getenv("CRAWLBOT_BASE_URL", "http://127.0.0.1:8000")
    )
    key = (
        getattr(args, "api_key", None)
        or os.getenv("NEXORA_API_KEY")
        or os.getenv("CRAWLBOT_API_KEY")
    )
    return NexoraClient(base_url=url, api_key=key, timeout=getattr(args, "timeout", 60.0))


def cmd_ping(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        health = client.health()
        print_success(f"Nexora API is healthy (version: {health.get('version', 'unknown')})")
        if args.verbose:
            print_json(health)
        return 0
    except Exception as e:
        print_error(f"Failed to connect to Nexora: {e}")
        return 1


def cmd_extract(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        res = client.extract_url(
            url=args.url,
            strategy=args.strategy,
            loading_delay=getattr(args, "delay", 0.0),
            visible_only=getattr(args, "visible_only", False),
        )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(res.markdown or res.text)
            print_success(f"Saved extracted text to {args.output}")
        else:
            print_json(res.model_dump())
        return 0
    except Exception as e:
        print_error(f"Extraction failed: {e}")
        return 1


def cmd_discover(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        print(
            f"Starting discovery for {args.url} "
            f"(max_pages={args.max_pages}, max_depth={args.max_depth}, browser_fallback={args.browser_fallback})..."
        )
        res = client.start_discovery(
            root_url=args.url,
            max_depth=args.max_depth,
            max_pages=args.max_pages,
            enable_browser_fallback=args.browser_fallback,
            wait=args.wait,
            wait_timeout=args.wait_timeout,
        )
        if args.wait:
            print_success(f"Discovery completed! State: {res.state}, total: {res.total_urls}")
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    pages_data = [p.model_dump() if hasattr(p, "model_dump") else p for p in (res.pages or [])]
                    json.dump(pages_data, f, ensure_ascii=False, indent=2)
                print_success(f"Saved {len(pages_data)} discovered URLs to {args.output}")
            else:
                print_json(res.model_dump())
        else:
            print_success(f"Discovery job launched successfully! Job ID: {res}")
        return 0
    except Exception as e:
        print_error(f"Discovery failed: {e}")
        return 1


def cmd_crawl(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        print(f"Starting crawl for {args.url} (max_pages={args.max_pages}, max_depth={args.max_depth})...")
        res = client.start_crawl(
            url=args.url,
            max_depth=args.max_depth,
            max_pages=args.max_pages,
            strategy=args.strategy,
            wait=args.wait,
            wait_timeout=args.wait_timeout,
        )
        if args.wait:
            print_success(f"Crawl completed! State: {res.state}, crawled: {res.urls_crawled}")
            print_json(res.model_dump())
        else:
            print_success(f"Job launched successfully! Job ID: {res}")
        return 0
    except Exception as e:
        print_error(f"Crawl start failed: {e}")
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        job = client.get_job(args.job_id)
        print_json(job.model_dump())
        return 0
    except Exception as e:
        print_error(f"Failed to get job status: {e}")
        return 1


def cmd_wait(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        print(f"Waiting for job {args.job_id} to finish (timeout={args.timeout}s)...")
        job = client.wait_for_job(args.job_id, timeout=args.timeout)
        print_success(f"Job finished with state: {job.state}")
        print_json(job.model_dump())
        return 0 if job.state == "completed" else 1
    except Exception as e:
        print_error(f"Wait failed: {e}")
        return 1


def cmd_chunk(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        res = client.chunk_job(job_id=args.job_id, chunk_size=args.size, chunk_overlap=args.overlap)
        print_success(f"Chunking completed for job {args.job_id}")
        print_json(res)
        return 0
    except Exception as e:
        print_error(f"Chunking failed: {e}")
        return 1


def cmd_embed(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        res = client.embed_chunks(job_id=args.job_id, model=args.model)
        print_success(f"Embedding completed for job {args.job_id}")
        print_json(res)
        return 0
    except Exception as e:
        print_error(f"Embedding failed: {e}")
        return 1


def cmd_search(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        results = client.search(
            job_id=args.job_id,
            query=args.query,
            top_k=args.top_k,
            method=args.method,
            alpha=args.alpha,
            min_score=args.min_score,
        )
        print_success(f"Found {len(results)} matching chunks for '{args.query}' (method: {args.method}):")
        for i, hit in enumerate(results):
            score_str = f"{hit.score:.4f}" if hit.score is not None else "N/A"
            print(f"\n[{i+1}] Score: {score_str} | Source: {hit.source_url}")
            if hit.heading_context:
                print(f"    Context: {hit.heading_context}")
            print(f"    Text: {hit.text[:180]}...")
        return 0
    except Exception as e:
        print_error(f"Search failed: {e}")
        return 1


def cmd_export(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        out = client.export_job(job_id=args.job_id, export_format=args.format, output_file=args.output)
        if args.output:
            print_success(f"Exported job {args.job_id} ({args.format}) to {args.output}")
        else:
            if isinstance(out, bytes):
                print(out.decode("utf-8", errors="replace"))
            else:
                print(out)
        return 0
    except Exception as e:
        print_error(f"Export failed: {e}")
        return 1


def cmd_file(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        res = client.process_file(file_path=args.filepath, strategy=args.strategy)
        print_success(f"Processed file {args.filepath}")
        print_json(res)
        return 0
    except Exception as e:
        print_error(f"File processing failed: {e}")
        return 1


def cmd_quality(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        report = client.get_quality_report(job_id=args.job_id)
        print_json(report.model_dump())
        return 0
    except Exception as e:
        print_error(f"Quality report fetch failed: {e}")
        return 1


def cmd_sync(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        report = client.sync_incremental(
            project_id=args.project_id,
            candidate_urls=args.urls,
            chunk_size=args.size,
            chunk_overlap=args.overlap,
            force_reprocess=args.force,
        )
        print_success(f"Incremental sync completed for project {args.project_id}")
        print_json(report.model_dump())
        return 0
    except Exception as e:
        print_error(f"Incremental sync failed: {e}")
        return 1


def cmd_vector_export(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        target = args.target.lower()
        if target == "qdrant":
            res = client.export_to_qdrant(
                job_id=args.job_id,
                collection_name=args.collection,
                qdrant_url=args.url,
            )
            print_success(f"Synced to Qdrant collection: {args.collection}")
            print_json(res)
        elif target == "chroma":
            res = client.export_to_chroma(job_id=args.job_id)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(res, f, ensure_ascii=False, indent=2)
                print_success(f"Chroma payload saved to {args.output}")
            else:
                print_json(res)
        elif target == "pinecone":
            res = client.export_to_pinecone(job_id=args.job_id)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(res, f, ensure_ascii=False, indent=2)
                print_success(f"Pinecone payload saved to {args.output}")
            else:
                print_json(res)
        else:
            print_error(f"Unsupported vector database target: {args.target}")
            return 1
        return 0
    except Exception as e:
        print_error(f"Vector export failed: {e}")
        return 1


def _parse_cli_selectors(selectors_raw: Optional[list[str]]) -> dict[str, str]:
    """Parse key=value selector arguments into a dictionary."""
    result = {}
    if not selectors_raw:
        return result
    for item in selectors_raw:
        if "=" in item:
            k, v = item.split("=", 1)
            result[k.strip()] = v.strip()
        else:
            result[item.strip()] = item.strip()
    return result


def cmd_live(args: argparse.Namespace) -> int:
    """Handle live extraction CLI commands."""
    client = get_client(args)
    action = getattr(args, "live_action", "list")

    try:
        if action == "detect":
            print_success(f"Scanning target for dynamic/mutating fields: {args.url}")
            print(f"Observation window: {args.observation}s | Engine: {args.engine} ...")
            result = client.live.auto_detect(
                url=args.url,
                observation_seconds=args.observation,
                engine=args.engine,
            )
            print_success(f"Detection Complete! Found {len(result.detected_fields)} dynamic fields:")
            for f in result.detected_fields:
                mut_flag = "\033[92m[ACTIVE MUTATION]\033[0m " if f.mutation_detected else ""
                print(f" • {f.name:22} ({f.field_type:10}) -> Selector: {f.selector:35} Sample: '{f.sample_value}' {mut_flag}[conf: {f.confidence:.2f}]")
            print("\nRecommended Selectors for Live Watching:")
            print_json(result.recommended_selectors)
            return 0

        elif action == "create":
            is_auto = getattr(args, "auto", False)
            selectors = _parse_cli_selectors(getattr(args, "selector", None))
            effective_mode = "auto" if (is_auto or not selectors) else "manual"
            watcher = client.live.create(
                url=args.url,
                name=args.name,
                selectors=selectors,
                mode=effective_mode,
                observation_seconds=getattr(args, "observation", 3.0),
                interval_seconds=args.interval,
                engine=args.engine,
                single_trigger=args.single_trigger,
                turn_on=not args.turn_off,
            )
            print_success(f"Live watcher created: {watcher.id} (Mode: {watcher.mode}, Status: {watcher.status})")
            print_json(watcher.model_dump())
            return 0

        elif action == "list":
            watchers = client.live.list()
            if not watchers:
                print("No live watchers registered.")
                return 0
            print_success(f"Active Live Watchers ({len(watchers)} total):")
            for w in watchers:
                status_color = "\033[92m" if w.status == "active" else "\033[93m"
                print(f" • [{w.id}] {status_color}{w.status.upper()}\033[0m | {w.name} | {w.url} | Changes: {w.change_count} | Interval: {w.interval_seconds}s")
                if w.selectors:
                    print(f"   Selectors: {w.selectors}")
                if w.latest_data:
                    preview = json.dumps(w.latest_data, ensure_ascii=False)
                    if len(preview) > 100:
                        preview = preview[:97] + "..."
                    print(f"   Latest Data: {preview}")
            return 0

        elif action == "on":
            res = client.live.turn_on(args.watcher_id)
            print_success(f"Watcher {args.watcher_id} turned ON.")
            print_json(res)
            return 0

        elif action == "off":
            res = client.live.turn_off(args.watcher_id)
            print_success(f"Watcher {args.watcher_id} turned OFF.")
            print_json(res)
            return 0

        elif action == "latest":
            latest = client.live.get_latest(args.watcher_id)
            print_success(f"Latest live data for watcher {args.watcher_id}:")
            print_json(latest)
            return 0

        elif action == "delete":
            deleted = client.live.delete(args.watcher_id)
            if deleted:
                print_success(f"Deleted live watcher {args.watcher_id}")
                return 0
            else:
                print_error(f"Failed to delete watcher {args.watcher_id}")
                return 1

        elif action == "watch":
            is_auto = getattr(args, "auto", False)
            selectors = _parse_cli_selectors(getattr(args, "selector", None))
            effective_mode = "auto" if (is_auto or not selectors) else "manual"
            print_success(f"Starting real-time live watch on: {args.url}")
            mode_desc = f"Auto-Detect ({getattr(args, 'observation', 3.0)}s window)" if effective_mode == "auto" else "Manual Selectors"
            print(f"Mode: {mode_desc} | Interval: {args.interval}s | Engine: {args.engine}")
            if selectors:
                print(f"Selectors: {selectors}")
            print("Press Ctrl+C to stop.\n" + "-" * 60)

            for event in client.live.watch(
                url=args.url,
                selectors=selectors,
                mode=effective_mode,
                observation_seconds=getattr(args, "observation", 3.0),
                interval_seconds=args.interval,
                engine=args.engine,
                single_trigger=args.single_trigger,
            ):
                print(f"\n\033[96m[LIVE CHANGE #{event.change_count}]\033[0m {event.timestamp}")
                print("\033[93mDiff (Changed fields):\033[0m")
                print_json(event.diff)
                print("\033[92mCurrent Live State (Previous replaced):\033[0m")
                print_json(event.latest_data)
                print("-" * 60)
            return 0

        else:
            print_error(f"Unknown live action: {action}")
            return 1

    except KeyboardInterrupt:
        print("\nLive watching stopped by user.")
        return 0
    except Exception as e:
        print_error(f"Live operation failed: {e}")
        return 1



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nexora",
        description="Nexora Studio CLI - Developer automation for crawling, extraction & RAG",
    )
    parser.add_argument("--url-base", help="Nexora server base URL (default: http://127.0.0.1:8000)")
    parser.add_argument("--api-key", help="Nexora API key")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP request timeout in seconds")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # ping / health
    p_ping = subparsers.add_parser("ping", help="Check server connection and health")
    p_ping.add_argument("-v", "--verbose", action="store_true", help="Show full health JSON")
    p_ping.set_defaults(func=cmd_ping)

    # extract
    p_ext = subparsers.add_parser("extract", help="Extract text from a single URL")
    p_ext.add_argument("url", help="Target page URL")
    p_ext.add_argument(
        "--strategy",
        default="auto",
        choices=["auto", "trafilatura", "bs4", "beautifulsoup", "playwright", "crawl4ai"],
        help="Extraction strategy (default: auto)",
    )
    p_ext.add_argument("--delay", type=float, default=0.0, help="Initial loading screen delay in seconds")
    p_ext.add_argument("--visible-only", action="store_true", help="Extract visible content only")
    p_ext.add_argument("-o", "--output", help="Save extracted markdown/text to file")
    p_ext.set_defaults(func=cmd_extract)

    # discover (matches Web UI discovery tab)
    p_disc = subparsers.add_parser("discover", help="Discover and map website URLs (matches UI discovery tab)")
    p_disc.add_argument("url", help="Starting root URL")
    p_disc.add_argument("--max-pages", type=int, default=50, help="Maximum pages to discover")
    p_disc.add_argument("--max-depth", type=int, default=2, help="Maximum crawl depth")
    p_disc.add_argument(
        "--browser-fallback",
        dest="browser_fallback",
        action="store_true",
        default=True,
        help="Auto-resolve anti-bot challenges and SPAs with browser",
    )
    p_disc.add_argument(
        "--no-browser-fallback",
        dest="browser_fallback",
        action="store_false",
        help="Disable browser fallback",
    )
    p_disc.add_argument("--wait", action="store_true", help="Block until discovery completes")
    p_disc.add_argument("--wait-timeout", type=float, default=300.0, help="Max wait time in seconds")
    p_disc.add_argument("-o", "--output", help="Save discovered URLs to JSON file")
    p_disc.set_defaults(func=cmd_discover)

    # crawl
    p_crawl = subparsers.add_parser("crawl", help="Start background crawl discovery on website")
    p_crawl.add_argument("url", help="Starting website URL")
    p_crawl.add_argument("--max-pages", type=int, default=50)
    p_crawl.add_argument("--max-depth", type=int, default=2)
    p_crawl.add_argument(
        "--strategy",
        default="auto",
        choices=["auto", "trafilatura", "bs4", "beautifulsoup", "playwright", "crawl4ai"],
        help="Crawl extraction strategy (default: auto)",
    )
    p_crawl.add_argument("--wait", action="store_true", help="Block until crawl finishes")
    p_crawl.add_argument("--wait-timeout", type=float, default=300.0)
    p_crawl.set_defaults(func=cmd_crawl)

    # status
    p_stat = subparsers.add_parser("status", help="Get status of a job")
    p_stat.add_argument("job_id", help="Job ID")
    p_stat.set_defaults(func=cmd_status)

    # wait
    p_wait = subparsers.add_parser("wait", help="Block until a job reaches terminal state")
    p_wait.add_argument("job_id", help="Job ID")
    p_wait.set_defaults(func=cmd_wait)

    # chunk
    p_chunk = subparsers.add_parser("chunk", help="Segment job documents into RAG chunks")
    p_chunk.add_argument("job_id", help="Job ID")
    p_chunk.add_argument("--size", type=int, default=500)
    p_chunk.add_argument("--overlap", type=int, default=50)
    p_chunk.set_defaults(func=cmd_chunk)

    # embed
    p_embed = subparsers.add_parser("embed", help="Generate vector embeddings for job chunks")
    p_embed.add_argument("job_id", help="Job ID")
    p_embed.add_argument("--model", help="Embedding model name")
    p_embed.set_defaults(func=cmd_embed)

    # search
    p_search = subparsers.add_parser("search", help="Execute search query across job chunks")
    p_search.add_argument("job_id", help="Job ID")
    p_search.add_argument("query", help="Query text")
    p_search.add_argument("--top-k", type=int, default=5)
    p_search.add_argument("--method", default="hybrid", choices=["hybrid", "dense", "bm25"])
    p_search.add_argument("--alpha", type=float, default=0.7)
    p_search.add_argument("--min-score", type=float, default=0.0)
    p_search.set_defaults(func=cmd_search)

    # export
    p_exp = subparsers.add_parser("export", help="Download job documents in JSONL/CSV/Markdown")
    p_exp.add_argument("job_id", help="Job ID")
    p_exp.add_argument("--format", default="jsonl", choices=["jsonl", "json", "csv", "markdown"])
    p_exp.add_argument("-o", "--output", help="Output file path")
    p_exp.set_defaults(func=cmd_export)

    # file
    p_file = subparsers.add_parser("file", help="Upload and process local file")
    p_file.add_argument("filepath", help="Path to local file")
    p_file.add_argument("--strategy", default="balanced")
    p_file.set_defaults(func=cmd_file)

    # quality
    p_qual = subparsers.add_parser("quality", help="Get dataset quality report")
    p_qual.add_argument("job_id", help="Job ID")
    p_qual.set_defaults(func=cmd_quality)

    # sync
    p_sync = subparsers.add_parser("sync", help="Run incremental crawl synchronization")
    p_sync.add_argument("project_id", help="Project identifier")
    p_sync.add_argument("urls", nargs="+", help="Candidate URLs")
    p_sync.add_argument("--size", type=int, default=500)
    p_sync.add_argument("--overlap", type=int, default=50)
    p_sync.add_argument("--force", action="store_true")
    p_sync.set_defaults(func=cmd_sync)

    # vector-export
    p_vexp = subparsers.add_parser("vector-export", help="Export chunks to vector database")
    p_vexp.add_argument("job_id", help="Job ID")
    p_vexp.add_argument("--target", default="qdrant", choices=["qdrant", "chroma", "pinecone"])
    p_vexp.add_argument("--collection", default="nexora_chunks")
    p_vexp.add_argument("--url", default="http://localhost:6333")
    p_vexp.add_argument("-o", "--output", help="Output file for chroma/pinecone JSON payloads")
    p_vexp.set_defaults(func=cmd_vector_export)

    # live (real-time extraction & change tracking)
    p_live = subparsers.add_parser("live", help="Real-time live extraction, change detection & monitoring")
    live_sub = p_live.add_subparsers(dest="live_action", help="Live actions")

    # live detect (autonomous dynamic field discovery)
    pl_detect = live_sub.add_parser("detect", help="Auto-detect dynamic and mutating fields on target page")
    pl_detect.add_argument("--url", required=True, help="Target URL to scan")
    pl_detect.add_argument("--observation", type=float, default=3.0, help="Observation window in seconds (default: 3.0)")
    pl_detect.add_argument("--engine", default="auto", choices=["auto", "fast_http", "playwright"])
    pl_detect.set_defaults(func=cmd_live)

    # live create
    pl_create = live_sub.add_parser("create", help="Create a new live watcher")
    pl_create.add_argument("--url", required=True, help="Target URL to monitor")
    pl_create.add_argument("--name", help="Watcher label")
    pl_create.add_argument("-s", "--selector", action="append", help="Field selectors (e.g. -s price=.price -s title=h1)")
    pl_create.add_argument("--auto", action="store_true", help="Auto-discover dynamic fields without manual CSS selectors")
    pl_create.add_argument("--observation", type=float, default=3.0, help="Observation window in seconds for auto-detection")
    pl_create.add_argument("--interval", type=float, default=5.0, help="Check interval in seconds (default: 5.0)")
    pl_create.add_argument("--engine", default="auto", choices=["auto", "fast_http", "playwright"], help="Extraction engine")
    pl_create.add_argument("--single-trigger", action="store_true", help="Auto turn OFF after first change detected")
    pl_create.add_argument("--turn-off", action="store_true", help="Do not turn on immediately upon creation")
    pl_create.set_defaults(func=cmd_live)

    # live list
    pl_list = live_sub.add_parser("list", help="List all registered live watchers")
    pl_list.set_defaults(func=cmd_live)

    # live on
    pl_on = live_sub.add_parser("on", help="Turn ON a live watcher")
    pl_on.add_argument("watcher_id", help="Watcher ID")
    pl_on.set_defaults(func=cmd_live)

    # live off
    pl_off = live_sub.add_parser("off", help="Turn OFF a live watcher")
    pl_off.add_argument("watcher_id", help="Watcher ID")
    pl_off.set_defaults(func=cmd_live)

    # live latest
    pl_latest = live_sub.add_parser("latest", help="Fetch latest live data snapshot")
    pl_latest.add_argument("watcher_id", help="Watcher ID")
    pl_latest.set_defaults(func=cmd_live)

    # live delete
    pl_del = live_sub.add_parser("delete", help="Delete a live watcher")
    pl_del.add_argument("watcher_id", help="Watcher ID")
    pl_del.set_defaults(func=cmd_live)

    # live watch (interactive terminal streaming)
    pl_watch = live_sub.add_parser("watch", help="Interactively watch a URL and stream changes live to terminal")
    pl_watch.add_argument("--url", required=True, help="Target URL to monitor")
    pl_watch.add_argument("-s", "--selector", action="append", help="Field selectors (e.g. -s price=.price)")
    pl_watch.add_argument("--auto", action="store_true", help="Auto-discover dynamic fields without manual CSS selectors")
    pl_watch.add_argument("--observation", type=float, default=3.0, help="Observation window in seconds for auto-detection")
    pl_watch.add_argument("--interval", type=float, default=3.0, help="Check interval in seconds (default: 3.0)")
    pl_watch.add_argument("--engine", default="auto", choices=["auto", "fast_http", "playwright"])
    pl_watch.add_argument("--single-trigger", action="store_true", help="Stop after first detected change")
    pl_watch.set_defaults(func=cmd_live)

    p_live.set_defaults(func=cmd_live)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command or not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)
    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
