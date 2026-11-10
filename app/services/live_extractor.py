"""Nexora Live Real-Time Extraction & Change Tracking Engine.

Monitors dynamic e-commerce, financial markets, news feeds, and live web applications.
Features Autonomous Dynamic Field Detection ("Auto-Detect") to discover mutating fields
(e.g. Bitcoin price, market cap, stock availability, dynamic metrics) without requiring manual CSS/JSON selectors.
Detects DOM/data changes in real-time, replaces previous stale data with new live data,
dispatches event notifications via SSE/webhooks, and provides fine-grained Turn ON / Turn OFF controls.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional
import uuid

from bs4 import BeautifulSoup
import httpx

from app.schemas.live import (
    ChangeEvent,
    DiscoveredDynamicField,
    DynamicFieldDetectionResponse,
    LiveWatcherCreateRequest,
    LiveWatcherResponse,
)

logger = logging.getLogger(__name__)

PRICE_REGEX = re.compile(
    r'(\$[\d,]+(\.\d+)?|€[\d,]+(\.\d+)?|£[\d,]+(\.\d+)?|¥[\d,]+|'
    r'[\d,]+(\.\d+)?\s*(USD|USDT|BTC|ETH|EUR|IRR|تومان|ریال))',
    re.IGNORECASE,
)
PERCENT_REGEX = re.compile(r'([+\-]?\d+(\.\d+)?%)')


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_data_hash(data: Dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DynamicFieldDetector:
    """Autonomous engine for discovering dynamic and mutating fields on live webpages."""

    def __init__(self):
        self.default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def fetch_html(
        self,
        url: str,
        engine: str = "auto",
        headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Fetch raw HTML using HTTP or Playwright according to engine strategy."""
        req_headers = dict(self.default_headers)
        if headers:
            req_headers.update(headers)

        if engine in ("fast_http", "auto"):
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    resp = await client.get(url, headers=req_headers)
                    resp.raise_for_status()
                    return resp.text
            except Exception as e:
                if engine == "auto":
                    logger.info(f"Fast HTTP fetch failed on {url} ({e}); falling back to Playwright")
                    return await self._fetch_playwright(url, req_headers)
                raise
        else:
            return await self._fetch_playwright(url, req_headers)

    async def _fetch_playwright(self, url: str, headers: Dict[str, str]) -> str:
        """Fetch rendered HTML via Playwright Chromium."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(extra_http_headers=headers)
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(1000)
                return await page.content()
            finally:
                await context.close()
                await browser.close()

    def generate_selector(self, el, soup: BeautifulSoup) -> str:
        """Generate a stable CSS selector for an element."""
        # 1. Direct data-test / data-qa / itemprop attributes
        for attr in ("data-test", "data-qa", "data-testid", "data-cy", "itemprop"):
            val = el.get(attr)
            if val:
                sel = f'[{attr}="{val}"]'
                try:
                    if len(soup.select(sel)) == 1:
                        return sel
                except Exception:
                    pass

        # 2. Check id if not dynamic / hashed
        el_id = el.get("id")
        if el_id and re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]{2,40}$", el_id):
            sel = f"#{el_id}"
            try:
                if len(soup.select(sel)) == 1:
                    return sel
            except Exception:
                pass

        # 3. Parent container with data-test
        parent = el.parent
        if parent:
            for attr in ("data-test", "data-qa", "data-testid", "itemprop"):
                pval = parent.get(attr)
                if pval:
                    classes = [c for c in el.get("class", []) if not self._is_hash_class(c)]
                    child_selector = f".{classes[0]}" if classes else el.name
                    sel = f'[{attr}="{pval}"] > {child_selector}'
                    try:
                        if soup.select(sel):
                            return sel
                    except Exception:
                        pass

        # 4. Semantic classes
        classes = [c for c in el.get("class", []) if not self._is_hash_class(c)]
        if classes:
            sel = f"{el.name}.{'.'.join(classes[:2])}"
            try:
                matches = soup.select(sel)
                if len(matches) == 1:
                    return sel
            except Exception:
                pass

        # 5. Parent semantic class + child
        if parent:
            p_classes = [c for c in parent.get("class", []) if not self._is_hash_class(c)]
            if p_classes:
                sel = f".{p_classes[0]} > {el.name}"
                try:
                    if soup.select(sel):
                        return sel
                except Exception:
                    pass

        # 6. Fallback tag
        return el.name

    def _is_hash_class(self, c: str) -> bool:
        if not c or len(c) < 3:
            return True
        if c.startswith(("sc-", "css-", "_", "jsx-", "tw-")):
            return True
        if re.match(r"^[a-zA-Z0-9]{5,10}$", c) and any(char.isupper() for char in c) and any(char.islower() for char in c):
            return True
        return False

    def infer_field_name(self, el, text: str, category: str, existing_names: set) -> str:
        """Infer a clean, semantic field name based on tag attributes and parent context."""
        direct_attrs = f"{el.get('data-test', '')} {el.get('id', '')} {' '.join(el.get('class', []))}".lower()
        parent = el.parent
        parent_attrs = ""
        sibling_label = ""
        if parent:
            parent_attrs = f"{parent.get('data-test', '')} {parent.get('id', '')} {' '.join(parent.get('class', []))}".lower()
            prev = el.find_previous_sibling()
            if prev:
                sibling_label = prev.get_text(separator=" ", strip=True).lower()
            else:
                lbl = parent.find(class_=re.compile(r"label|title|header|name", re.I))
                if lbl and lbl != el:
                    sibling_label = lbl.get_text(separator=" ", strip=True).lower()

        search_pool = f"{direct_attrs} | {parent_attrs} | {sibling_label}".lower()

        base_name = category
        if "market-cap" in search_pool or "market cap" in search_pool:
            base_name = "market_cap"
        elif "volume" in search_pool:
            base_name = "volume_24h"
        elif "change" in search_pool or "%" in text:
            base_name = "price_change_percentage"
        elif "high" in search_pool:
            base_name = "high_24h"
        elif "low" in search_pool:
            base_name = "low_24h"
        elif "price" in search_pool or category == "price":
            base_name = "price"
        elif "stock" in search_pool:
            base_name = "stock_status"

        candidate = base_name
        counter = 2
        while candidate in existing_names:
            candidate = f"{base_name}_{counter}"
            counter += 1
        existing_names.add(candidate)
        return candidate

    def detect_from_html(
        self,
        html_text: str,
        url: str = "",
        observation_seconds: float = 3.0,
        mutation_map: Optional[Dict[str, str]] = None,
    ) -> DynamicFieldDetectionResponse:
        """Analyze DOM tree to extract changing, mutating, or financial/price elements."""
        soup = BeautifulSoup(html_text, "html.parser")
        discovered: List[DiscoveredDynamicField] = []
        existing_names: set = set()
        seen_selectors: set = set()

        for el in soup.find_all(["span", "div", "p", "strong", "b", "h1", "h2", "h3", "td"]):
            if len(el.find_all()) > 0:
                continue
            text = el.get_text(strip=True)
            if not text or len(text) > 80:
                continue

            sel = self.generate_selector(el, soup)
            if sel in seen_selectors:
                continue

            field_type = None
            confidence = 0.85
            is_mutation = False

            if mutation_map and sel in mutation_map and mutation_map[sel] != text:
                is_mutation = True
                confidence = 1.0

            if PRICE_REGEX.search(text):
                field_type = "price"
                confidence = 1.0 if is_mutation else 0.95
            elif PERCENT_REGEX.search(text):
                field_type = "percentage"
                confidence = 1.0 if is_mutation else 0.92
            elif is_mutation:
                field_type = "dynamic_text"
                confidence = 1.0
            elif any(k in text.lower() for k in ("in stock", "out of stock", "موجود", "ناموجود")):
                field_type = "stock_status"
                confidence = 0.90

            if field_type:
                name = self.infer_field_name(el, text, field_type, existing_names)
                seen_selectors.add(sel)
                discovered.append(
                    DiscoveredDynamicField(
                        name=name,
                        selector=sel,
                        sample_value=text,
                        confidence=confidence,
                        field_type=field_type,
                        mutation_detected=is_mutation,
                    )
                )

        discovered.sort(key=lambda f: (f.mutation_detected, f.confidence), reverse=True)
        recommended = {f.name: f.selector for f in discovered}
        summary = (
            f"Autonomous detection identified {len(discovered)} dynamic fields on target page."
            if discovered
            else "No obvious dynamic fields detected. Full page fallback will be used."
        )

        return DynamicFieldDetectionResponse(
            url=url,
            observation_seconds=observation_seconds,
            detected_fields=discovered,
            recommended_selectors=recommended,
            summary=summary,
        )

    async def detect(
        self,
        url: str,
        observation_seconds: float = 3.0,
        engine: str = "auto",
        headers: Optional[Dict[str, str]] = None,
    ) -> DynamicFieldDetectionResponse:
        """Scan target page across an observation window to discover active mutations."""
        t0_html = await self.fetch_html(url=url, engine=engine, headers=headers)

        mutation_map: Dict[str, str] = {}
        if observation_seconds > 0.1:
            # Build baseline selector map from T0
            soup_t0 = BeautifulSoup(t0_html, "html.parser")
            for el in soup_t0.find_all(["span", "div", "p", "strong", "b", "h1", "h2", "h3", "td"]):
                if len(el.find_all()) == 0 and el.get_text(strip=True):
                    sel = self.generate_selector(el, soup_t0)
                    mutation_map[sel] = el.get_text(strip=True)

            # Observe for changes
            await asyncio.sleep(min(observation_seconds, 15.0))

            try:
                t1_html = await self.fetch_html(url=url, engine=engine, headers=headers)
                return self.detect_from_html(
                    t1_html,
                    url=url,
                    observation_seconds=observation_seconds,
                    mutation_map=mutation_map,
                )
            except Exception as e:
                logger.warning(f"Second observation fetch failed ({e}); using initial snapshot")

        return self.detect_from_html(
            t0_html,
            url=url,
            observation_seconds=observation_seconds,
            mutation_map=None,
        )


class LiveWatcher:
    """Individual real-time watcher instance."""

    def __init__(
        self,
        watcher_id: str,
        spec: LiveWatcherCreateRequest,
        workspace_id: Optional[str] = None,
    ):
        self.id = watcher_id
        self.name = spec.name or f"Live-Watcher-{watcher_id[:8]}"
        self.url = str(spec.url)
        self.selectors = spec.selectors or {}
        self.interval_seconds = max(0.1, float(spec.interval_seconds))
        self.engine = spec.engine
        self.single_trigger = spec.single_trigger
        self.mode = spec.mode
        self.observation_seconds = max(0.5, float(spec.observation_seconds))
        self.webhook_url = str(spec.webhook_url) if spec.webhook_url else None
        self.headers = spec.headers or {}
        self.workspace_id = workspace_id

        self.discovered_fields: List[DiscoveredDynamicField] = []
        self.status: str = "stopped"
        self.created_at: str = _now_iso()
        self.last_checked_at: Optional[str] = None
        self.last_changed_at: Optional[str] = None
        self.change_count: int = 0
        self.error_message: Optional[str] = None

        self.latest_data: Optional[Dict[str, Any]] = None
        self._current_hash: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._subscribers: List[asyncio.Queue] = []

    def to_response(self) -> LiveWatcherResponse:
        return LiveWatcherResponse(
            id=self.id,
            name=self.name,
            url=self.url,
            status=self.status,
            selectors=self.selectors,
            interval_seconds=self.interval_seconds,
            engine=self.engine,
            single_trigger=self.single_trigger,
            mode=self.mode,
            discovered_fields=self.discovered_fields,
            last_checked_at=self.last_checked_at,
            last_changed_at=self.last_changed_at,
            change_count=self.change_count,
            latest_data=self.latest_data,
            created_at=self.created_at,
            error_message=self.error_message,
        )

    def turn_on(self) -> None:
        """Turn ON watcher and initiate live monitoring loop."""
        if self.status == "active" and self._task and not self._task.done():
            return

        self._stop_event.clear()
        self.status = "active"
        self.error_message = None
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"LiveWatcher {self.id} turned ON for {self.url} (mode: {self.mode}, interval: {self.interval_seconds}s)")

    def turn_off(self) -> None:
        """Turn OFF watcher and halt monitoring."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
        self.status = "stopped"
        logger.info(f"LiveWatcher {self.id} turned OFF")

    async def _auto_discover_selectors_if_needed(self) -> None:
        """If configured in auto mode with no selectors, autonomously discover dynamic fields."""
        if self.mode == "auto" and not self.selectors:
            detector = DynamicFieldDetector()
            resp = await detector.detect(
                url=self.url,
                observation_seconds=min(self.observation_seconds, 3.0),
                engine=self.engine,
                headers=self.headers,
            )
            if resp.recommended_selectors:
                self.selectors = resp.recommended_selectors
                self.discovered_fields = resp.detected_fields
                logger.info(
                    f"LiveWatcher {self.id} auto-detected {len(self.selectors)} dynamic fields: {list(self.selectors.keys())}"
                )

    async def extract_current_snapshot(self) -> Dict[str, Any]:
        """Perform a single extraction pass according to configured engine."""
        if self.mode == "auto" and not self.selectors:
            try:
                await self._auto_discover_selectors_if_needed()
            except Exception as e:
                logger.warning(f"LiveWatcher {self.id} auto-detect pass note: {e}")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
        }
        if self.headers:
            headers.update(self.headers)

        if self.engine in ("fast_http", "auto"):
            try:
                return await self._extract_http(headers)
            except Exception as e:
                if self.engine == "auto":
                    logger.warning(f"Fast HTTP extraction failed on {self.url} ({e}); falling back to Playwright")
                    return await self._extract_playwright(headers)
                raise
        else:
            return await self._extract_playwright(headers)

    async def _extract_http(self, headers: Dict[str, str]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(self.url, headers=headers)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").lower()
            text = resp.text

            # Check if target is a JSON API endpoint
            if "application/json" in content_type or (text.strip().startswith("{") and text.strip().endswith("}")):
                try:
                    json_data = resp.json()
                    if isinstance(json_data, dict):
                        if self.selectors:
                            extracted = {}
                            for k, selector in self.selectors.items():
                                extracted[k] = json_data.get(selector, json_data.get(k))
                            return extracted
                        return json_data
                except Exception:
                    pass

            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(text, "html.parser")

            data: Dict[str, Any] = {}
            if self.selectors:
                for field_name, selector in self.selectors.items():
                    try:
                        elements = soup.select(selector)
                        if elements:
                            if len(elements) == 1:
                                val = elements[0].get_text(strip=True)
                            else:
                                val = [el.get_text(strip=True) for el in elements]
                            data[field_name] = val
                        else:
                            data[field_name] = None
                    except Exception:
                        data[field_name] = None
            else:
                # Default whole page summary snapshot
                title = soup.title.string.strip() if soup.title and soup.title.string else ""
                for s in soup(["script", "style", "noscript"]):
                    s.decompose()
                body_text = soup.get_text(separator=" ", strip=True)
                data = {
                    "title": title,
                    "text_preview": body_text[:300] if body_text else "",
                    "text_length": len(body_text),
                }

            return data

    async def _extract_playwright(self, headers: Dict[str, str]) -> Dict[str, Any]:
        """Extract live data using headless Chromium browser."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(extra_http_headers=headers)
            page = await context.new_page()
            try:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(1000)

                data: Dict[str, Any] = {}
                if self.selectors:
                    for field_name, selector in self.selectors.items():
                        try:
                            elements = await page.query_selector_all(selector)
                            if elements:
                                if len(elements) == 1:
                                    txt = await elements[0].inner_text()
                                    data[field_name] = txt.strip()
                                else:
                                    texts = [await el.inner_text() for el in elements]
                                    data[field_name] = [t.strip() for t in texts]
                            else:
                                data[field_name] = None
                        except Exception:
                            data[field_name] = None
                else:
                    title = await page.title()
                    body_text = await page.evaluate("() => document.body.innerText")
                    data = {
                        "title": title,
                        "text_preview": body_text[:300] if body_text else "",
                        "text_length": len(body_text) if body_text else 0,
                    }

                return data
            finally:
                await context.close()
                await browser.close()

    async def _run_loop(self) -> None:
        """Main monitoring loop executing at configured intervals."""
        try:
            # Auto-discover dynamic fields if in auto mode without explicit selectors
            if self.mode == "auto" and not self.selectors:
                try:
                    await self._auto_discover_selectors_if_needed()
                except Exception as e:
                    logger.warning(f"LiveWatcher {self.id} auto-detection exception: {e}")

            while not self._stop_event.is_set():
                try:
                    extracted = await self.extract_current_snapshot()
                    self.last_checked_at = _now_iso()
                    new_hash = _compute_data_hash(extracted)

                    if self._current_hash is None:
                        # First baseline run: store current data
                        self._current_hash = new_hash
                        self.latest_data = extracted
                        logger.debug(f"LiveWatcher {self.id} baseline recorded: {extracted}")
                    elif new_hash != self._current_hash:
                        # Change detected!
                        old_data = self.latest_data
                        diff: Dict[str, Any] = {}
                        all_keys = set(list((old_data or {}).keys()) + list(extracted.keys()))
                        for k in all_keys:
                            old_v = (old_data or {}).get(k)
                            new_v = extracted.get(k)
                            if old_v != new_v:
                                diff[k] = {"old": old_v, "new": new_v}

                        self.change_count += 1
                        self.last_changed_at = _now_iso()
                        self._current_hash = new_hash

                        # Replace previous data with latest live data
                        self.latest_data = extracted

                        event = ChangeEvent(
                            watcher_id=self.id,
                            timestamp=self.last_changed_at,
                            previous_data=old_data,
                            latest_data=self.latest_data,
                            diff=diff,
                            change_count=self.change_count,
                        )

                        logger.info(f"LiveWatcher {self.id} CHANGE DETECTED (#{self.change_count}): {diff}")
                        await self._broadcast_event(event)

                        if self.webhook_url:
                            asyncio.create_task(self._send_webhook(event))

                        if self.single_trigger:
                            self.status = "triggered"
                            self._stop_event.set()
                            logger.info(f"LiveWatcher {self.id} single-trigger satisfied. Turning OFF.")
                            break

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.error_message = str(e)
                    logger.debug(f"LiveWatcher {self.id} check pass note: {e}")

                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
                except asyncio.TimeoutError:
                    pass

        except asyncio.CancelledError:
            pass
        finally:
            if self._stop_event.is_set() and self.status != "triggered":
                self.status = "stopped"

    async def _broadcast_event(self, event: ChangeEvent) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                pass

    async def _send_webhook(self, event: ChangeEvent) -> None:
        if not self.webhook_url:
            return
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(self.webhook_url, json=event.model_dump())
        except Exception as e:
            logger.warning(f"Failed to dispatch webhook to {self.webhook_url}: {e}")

    def subscribe(self) -> asyncio.Queue:
        """Register a queue to receive live ChangeEvents."""
        q = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)


class LiveWatcherManager:
    """Singleton service to manage all active live watchers."""

    _instance: Optional[LiveWatcherManager] = None

    def __init__(self):
        self._watchers: Dict[str, LiveWatcher] = {}

    @classmethod
    def get_instance(cls) -> LiveWatcherManager:
        if cls._instance is None:
            cls._instance = LiveWatcherManager()
        return cls._instance

    def create_watcher(
        self,
        spec: LiveWatcherCreateRequest,
        workspace_id: Optional[str] = None,
    ) -> LiveWatcher:
        watcher_id = f"live_{uuid.uuid4().hex[:10]}"
        watcher = LiveWatcher(watcher_id=watcher_id, spec=spec, workspace_id=workspace_id)
        self._watchers[watcher_id] = watcher

        if spec.turn_on:
            watcher.turn_on()

        return watcher

    def get_watcher(self, watcher_id: str) -> Optional[LiveWatcher]:
        return self._watchers.get(watcher_id)

    def list_watchers(self, workspace_id: Optional[str] = None) -> List[LiveWatcher]:
        watchers = list(self._watchers.values())
        if workspace_id:
            watchers = [w for w in watchers if w.workspace_id in (None, workspace_id)]
        return watchers

    def turn_on(self, watcher_id: str) -> Optional[LiveWatcher]:
        watcher = self.get_watcher(watcher_id)
        if watcher:
            watcher.turn_on()
        return watcher

    def turn_off(self, watcher_id: str) -> Optional[LiveWatcher]:
        watcher = self.get_watcher(watcher_id)
        if watcher:
            watcher.turn_off()
        return watcher

    def delete_watcher(self, watcher_id: str) -> bool:
        watcher = self._watchers.pop(watcher_id, None)
        if watcher:
            watcher.turn_off()
            return True
        return False

    def shutdown_all(self) -> None:
        """Stop all background watcher tasks gracefully."""
        for watcher in self._watchers.values():
            watcher.turn_off()


def get_live_manager() -> LiveWatcherManager:
    return LiveWatcherManager.get_instance()
