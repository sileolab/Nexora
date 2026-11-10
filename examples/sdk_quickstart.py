"""Nexora Python SDK - Quickstart Example.

Demonstrates end-to-end RAG data preparation:
1. Initialize client
2. Extract a URL
3. Chunk and embed content
4. Hybrid search
5. Export to Qdrant/Chroma
"""

from __future__ import annotations

import os
import sys

# Ensure root workspace is in sys.path when running as a standalone script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from nexora import NexoraClient, NexoraError


def main() -> None:
    # 1. Initialize client (reads NEXORA_BASE_URL and NEXORA_API_KEY from env if omitted)
    base_url = os.getenv("NEXORA_BASE_URL", os.getenv("CRAWLBOT_BASE_URL", "http://127.0.0.1:8000"))
    api_key = os.getenv("NEXORA_API_KEY", os.getenv("CRAWLBOT_API_KEY"))

    with NexoraClient(base_url=base_url, api_key=api_key) as client:
        print(f"Connecting to Nexora at {base_url}...")
        health = client.health()
        print(f"Server operational: {health['status']} (v{health['version']})")

        # 2. Extract a single web page
        url = "https://example.com"
        print(f"\nExtracting clean text from {url}...")
        try:
            doc = client.extract_url(url=url, strategy="trafilatura")
            print(f"Title: {doc.title}")
            print(f"Word Count: {doc.word_count}")
            print(f"Content Preview: {doc.text[:120]}...")
        except NexoraError as e:
            print(f"Extraction notice: {e}")

        # 3. Check existing jobs
        jobs = client.list_jobs(limit=5)
        print(f"\nRecent jobs found: {len(jobs)}")
        for j in jobs:
            print(f" - Job {j.job_id}: state={j.state}, docs={j.documents_count}")


if __name__ == "__main__":
    main()
