"""Incremental Website and Document Processing Service.

Detects:
1. New documents (URLs discovered for the first time).
2. Modified documents (content hash changed).
3. Unchanged documents (content hash identical and config unchanged -> skips extraction/embedding).
4. Deleted documents (URLs no longer present in target website).
5. Config changes (chunking/embedding parameter changes that require re-chunking without re-crawling).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
from typing import Any, Optional

from app.core.config import get_settings
from app.schemas.incremental import (
    DocumentHashState,
    IncrementalManifest,
    IncrementalSyncReport,
    IncrementalSyncRequest,
    PipelineConfigSignature,
)

logger = logging.getLogger(__name__)


def compute_content_hash(content: str | bytes) -> str:
    """Compute deterministic SHA-256 hex digest for document content."""
    if isinstance(content, str):
        content = content.encode("utf-8", errors="replace")
    return hashlib.sha256(content).hexdigest()


class IncrementalProcessor:
    """Manages incremental synchronization state manifests for projects and domains."""

    def __init__(self, manifest_dir: Optional[str] = None):
        settings = get_settings()
        self.manifest_dir = manifest_dir or settings.incremental_manifest_dir
        os.makedirs(self.manifest_dir, exist_ok=True)

    def _get_manifest_path(self, project_id: str, tenant_id: Optional[str] = None) -> str:
        safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in project_id)
        if tenant_id:
            safe_tenant = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in tenant_id)
            tenant_dir = os.path.join(self.manifest_dir, safe_tenant)
            os.makedirs(tenant_dir, exist_ok=True)
            return os.path.join(tenant_dir, f"{safe_id}_manifest.json")
        return os.path.join(self.manifest_dir, f"{safe_id}_manifest.json")

    def load_manifest(self, project_id: str, tenant_id: Optional[str] = None) -> IncrementalManifest:
        """Load stored manifest for project_id or create a new empty one."""
        path = self._get_manifest_path(project_id, tenant_id=tenant_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                loaded = IncrementalManifest.model_validate(data)
                if tenant_id and not loaded.tenant_id:
                    loaded.tenant_id = tenant_id
                return loaded
            except Exception as e:
                logger.warning("Failed to load manifest %s, recreating new: %s", path, e)

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return IncrementalManifest(
            manifest_id=f"man_{project_id}_{int(datetime.datetime.now().timestamp())}",
            project_id=project_id,
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
            pipeline_signature=PipelineConfigSignature(),
            documents={},
        )

    def save_manifest(self, manifest: IncrementalManifest, tenant_id: Optional[str] = None) -> None:
        """Persist manifest state to disk atomically."""
        manifest.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        effective_tenant = tenant_id or getattr(manifest, "tenant_id", None)
        path = self._get_manifest_path(manifest.project_id, tenant_id=effective_tenant)
        tmp_path = f"{path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(manifest.model_dump_json(indent=2))
            os.replace(tmp_path, path)
            logger.info("Saved incremental manifest for project %s (%d docs)", manifest.project_id, len(manifest.documents))
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            logger.error("Failed to save manifest to %s: %s", path, e)
            raise

    def process_sync(self, req: IncrementalSyncRequest, tenant_id: Optional[str] = None) -> IncrementalSyncReport:
        """Execute incremental analysis, detect deltas, update manifest, and generate sync report."""
        effective_tenant = tenant_id or getattr(req, "tenant_id", None)
        manifest = self.load_manifest(req.project_id, tenant_id=effective_tenant)
        manifest.tenant_id = effective_tenant
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        current_sig = PipelineConfigSignature(
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            embedding_model=req.embedding_model,
            extraction_strategy=req.extraction_strategy,
        )
        current_config_hash = current_sig.compute_hash()
        stored_config_hash = manifest.pipeline_signature.compute_hash()

        config_invalidated = (current_config_hash != stored_config_hash) and not req.force_reprocess
        manifest.pipeline_signature = current_sig

        candidate_set = set(req.candidate_urls)
        stored_urls = set(manifest.documents.keys())

        # Map optional provided raw documents by URL for instant hash checking
        provided_docs: dict[str, dict[str, Any]] = {}
        if req.raw_documents:
            for doc in req.raw_documents:
                url = doc.get("url")
                if url:
                    provided_docs[url] = doc

        new_urls: list[str] = []
        modified_urls: list[str] = []
        unchanged_urls: list[str] = []
        deleted_urls: list[str] = sorted(list(stored_urls - candidate_set))

        reused_chunks = 0
        reused_embeddings = 0
        reprocessed_chunks = 0

        for url in req.candidate_urls:
            prior_doc = manifest.documents.get(url)

            if req.force_reprocess or not prior_doc:
                new_urls.append(url)
                # Compute hash if doc content provided
                raw_info = provided_docs.get(url, {})
                content = raw_info.get("text") or raw_info.get("html") or url
                c_hash = compute_content_hash(content)
                manifest.set_document(
                    DocumentHashState(
                        url=url,
                        content_hash=c_hash,
                        lastmod=raw_info.get("lastmod"),
                        etag=raw_info.get("etag"),
                        status_code=raw_info.get("status_code", 200),
                        chunk_count=raw_info.get("chunk_count", 1),
                        embedding_count=raw_info.get("embedding_count", 1),
                        config_hash=current_config_hash,
                        processed_at=now_iso,
                    )
                )
                reprocessed_chunks += raw_info.get("chunk_count", 1)
            else:
                raw_info = provided_docs.get(url)
                if raw_info:
                    content = raw_info.get("text") or raw_info.get("html") or url
                    new_hash = compute_content_hash(content)
                    content_changed = (new_hash != prior_doc.content_hash)
                else:
                    content_changed = False
                    new_hash = prior_doc.content_hash

                if content_changed:
                    modified_urls.append(url)
                    manifest.set_document(
                        DocumentHashState(
                            url=url,
                            content_hash=new_hash,
                            lastmod=raw_info.get("lastmod") if raw_info else prior_doc.lastmod,
                            etag=raw_info.get("etag") if raw_info else prior_doc.etag,
                            status_code=raw_info.get("status_code", 200) if raw_info else prior_doc.status_code,
                            chunk_count=raw_info.get("chunk_count", prior_doc.chunk_count) if raw_info else prior_doc.chunk_count,
                            embedding_count=raw_info.get("embedding_count", prior_doc.embedding_count) if raw_info else prior_doc.embedding_count,
                            config_hash=current_config_hash,
                            processed_at=now_iso,
                        )
                    )
                    reprocessed_chunks += prior_doc.chunk_count or 1
                elif config_invalidated:
                    # Content unchanged, but config changed -> reprocess chunks/embeddings only
                    modified_urls.append(url)
                    prior_doc.config_hash = current_config_hash
                    prior_doc.processed_at = now_iso
                    reprocessed_chunks += prior_doc.chunk_count or 1
                else:
                    # Truly unchanged -> reuse prior chunks & embeddings
                    unchanged_urls.append(url)
                    reused_chunks += prior_doc.chunk_count
                    reused_embeddings += prior_doc.embedding_count

        # Cleanly prune deleted URLs from manifest
        for del_url in deleted_urls:
            manifest.remove_document(del_url)

        # Save manifest
        self.save_manifest(manifest)

        report = IncrementalSyncReport(
            project_id=req.project_id,
            tenant_id=effective_tenant,
            total_candidates=len(req.candidate_urls),
            new_urls=new_urls,
            modified_urls=modified_urls,
            unchanged_urls=unchanged_urls,
            deleted_urls=deleted_urls,
            config_invalidated=config_invalidated,
            reused_chunks=reused_chunks,
            reused_embeddings=reused_embeddings,
            reprocessed_chunks=reprocessed_chunks,
            synced_at=now_iso,
            status="completed",
        )
        logger.info(
            "Incremental sync for %s complete: %d new, %d modified, %d unchanged, %d deleted (saved %d chunks)",
            req.project_id,
            len(new_urls),
            len(modified_urls),
            len(unchanged_urls),
            len(deleted_urls),
            reused_chunks,
        )
        return report
