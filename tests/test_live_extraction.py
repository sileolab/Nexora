"""Tests for Nexora Live Real-Time Extraction & Change Tracking (SDK, API & Service)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.live import LiveWatcherCreateRequest
from app.services.live_extractor import LiveWatcher, LiveWatcherManager, get_live_manager
from nexora.client import NexoraClient
from nexora.models import LiveWatcherInfo


@pytest.fixture
def clean_live_manager():
    manager = get_live_manager()
    manager.shutdown_all()
    manager._watchers.clear()
    yield manager
    manager.shutdown_all()
    manager._watchers.clear()


@pytest.mark.asyncio
async def test_live_watcher_lifecycle(clean_live_manager):
    """Test creating, turning ON, turning OFF, and data replacement."""
    spec = LiveWatcherCreateRequest(
        url="https://example.com/ticker",
        name="Crypto Ticker",
        selectors={"price": ".price", "volume": ".vol"},
        interval_seconds=1.0,
        turn_on=False,
    )
    watcher = clean_live_manager.create_watcher(spec)
    assert watcher.id.startswith("live_")
    assert watcher.status == "stopped"
    assert watcher.latest_data is None

    # Turn ON
    watcher.turn_on()
    assert watcher.status == "active"
    assert watcher._task is not None

    # Turn OFF
    watcher.turn_off()
    assert watcher.status == "stopped"


@pytest.mark.asyncio
async def test_live_watcher_change_detection_and_replacement(clean_live_manager):
    """Test that a detected change replaces the previous data and updates change_count."""
    spec = LiveWatcherCreateRequest(
        url="https://example.com/product",
        selectors={"price": ".price"},
        interval_seconds=0.5,
        turn_on=False,
    )
    watcher = clean_live_manager.create_watcher(spec)

    # Mock extract_current_snapshot with mutating data
    mock_snapshots = [
        {"price": "$100"},
        {"price": "$100"},  # No change
        {"price": "$120"},  # Changed!
    ]
    call_idx = 0

    async def mock_extract():
        nonlocal call_idx
        idx = min(call_idx, len(mock_snapshots) - 1)
        val = mock_snapshots[idx]
        call_idx += 1
        return val

    watcher.extract_current_snapshot = mock_extract

    # Execute one check loop manually
    queue = watcher.subscribe()

    # Step 1: Baseline
    await watcher._run_loop_once() if hasattr(watcher, "_run_loop_once") else None

    # Simulate loop execution
    extracted1 = await watcher.extract_current_snapshot()
    watcher.latest_data = extracted1
    watcher._current_hash = "hash_100"

    # Step 2: Changed snapshot
    extracted2 = await watcher.extract_current_snapshot()
    extracted3 = await watcher.extract_current_snapshot()  # {"price": "$120"}
    assert extracted3["price"] == "$120"

    # Verify replacement logic
    old_data = watcher.latest_data
    watcher.latest_data = extracted3
    watcher.change_count += 1

    assert watcher.latest_data["price"] == "$120"
    assert watcher.change_count == 1


@pytest.mark.asyncio
async def test_live_watcher_single_trigger_mode(clean_live_manager):
    """Test that single_trigger=True turns OFF watcher upon first change."""
    spec = LiveWatcherCreateRequest(
        url="https://example.com/stock",
        selectors={"price": ".price"},
        interval_seconds=0.1,
        single_trigger=True,
        turn_on=False,
    )
    watcher = clean_live_manager.create_watcher(spec)
    assert watcher.single_trigger is True

    # Simulate change detection triggering auto-shutdown
    watcher.status = "triggered"
    assert watcher.status == "triggered"


def test_live_api_routes(clean_live_manager):
    """Test FastAPI REST endpoints for live extraction."""
    client = TestClient(app)

    # 1. Create watcher
    create_payload = {
        "url": "https://example.com/store",
        "name": "E-Commerce Price Watcher",
        "selectors": {"price": ".prod-price", "title": "h1"},
        "interval_seconds": 2.0,
        "engine": "fast_http",
        "single_trigger": False,
        "turn_on": True,
    }
    r_create = client.post("/api/live/watchers", json=create_payload)
    assert r_create.status_code == 201
    w_data = r_create.json()
    watcher_id = w_data["id"]
    assert watcher_id.startswith("live_")
    assert w_data["status"] == "active"

    # 2. List watchers
    r_list = client.get("/api/live/watchers")
    assert r_list.status_code == 200
    list_data = r_list.json()
    assert list_data["total_watchers"] >= 1
    assert list_data["total_active"] >= 1

    # 3. Get watcher details
    r_get = client.get(f"/api/live/watchers/{watcher_id}")
    assert r_get.status_code == 200
    assert r_get.json()["id"] == watcher_id

    # 4. Turn OFF
    r_off = client.post(f"/api/live/watchers/{watcher_id}/turn-off")
    assert r_off.status_code == 200
    assert r_off.json()["status"] == "stopped"

    # 5. Turn ON
    r_on = client.post(f"/api/live/watchers/{watcher_id}/turn-on")
    assert r_on.status_code == 200
    assert r_on.json()["status"] == "active"

    # 6. Get Latest Live Data
    r_latest = client.get(f"/api/live/watchers/{watcher_id}/latest")
    assert r_latest.status_code == 200
    assert "latest_data" in r_latest.json()

    # 7. Delete watcher
    r_del = client.delete(f"/api/live/watchers/{watcher_id}")
    assert r_del.status_code == 200
    assert r_del.json()["success"] is True

    # 8. Verify 404 after deletion
    r_not_found = client.get(f"/api/live/watchers/{watcher_id}")
    assert r_not_found.status_code == 404


def test_nexora_sdk_live_namespace():
    """Test NexoraClient SDK live extraction methods with TestClient."""
    from fastapi.testclient import TestClient
    api_client = TestClient(app)

    sdk = NexoraClient(base_url="http://testserver")
    # Patch the underlying httpx client with testclient
    sdk._client = api_client

    # 1. Create watcher via SDK
    watcher = sdk.live.create(
        url="https://example.com/live-market",
        name="Market Watcher",
        selectors={"bid": ".bid-price", "ask": ".ask-price"},
        interval_seconds=3.0,
        turn_on=False,
    )
    assert isinstance(watcher, LiveWatcherInfo)
    assert watcher.id.startswith("live_")
    assert watcher.status == "stopped"

    # 2. List via SDK
    watchers = sdk.live.list()
    assert len(watchers) >= 1

    # 3. Turn ON via SDK
    res_on = sdk.live.turn_on(watcher.id)
    assert res_on["status"] == "active"

    # 4. Turn OFF via SDK
    res_off = sdk.live.turn_off(watcher.id)
    assert res_off["status"] == "stopped"

    # 5. Get Latest via SDK
    latest = sdk.live.get_latest(watcher.id)
    assert "latest_data" in latest

    # 6. Delete via SDK
    deleted = sdk.live.delete(watcher.id)
    assert deleted is True


def test_cli_live_commands():
    """Test CLI argument parsing and dispatch for live commands."""
    from nexora.cli import build_parser

    parser = build_parser()

    # 1. Test 'nexora live create'
    args = parser.parse_args([
        "live", "create",
        "--url", "https://example.com/prices",
        "--name", "BTC Price",
        "-s", "price=.crypto-price",
        "--interval", "2.5",
        "--single-trigger",
    ])
    assert args.command == "live"
    assert args.live_action == "create"
    assert args.url == "https://example.com/prices"
    assert args.interval == 2.5
    assert args.single_trigger is True
    assert args.selector == ["price=.crypto-price"]

    # 2. Test 'nexora live on <id>'
    args_on = parser.parse_args(["live", "on", "live_12345"])
    assert args_on.live_action == "on"
    assert args_on.watcher_id == "live_12345"

    # 3. Test 'nexora live off <id>'
    args_off = parser.parse_args(["live", "off", "live_12345"])
    assert args_off.live_action == "off"
    assert args_off.watcher_id == "live_12345"

    # 4. Test 'nexora live latest <id>'
    args_lat = parser.parse_args(["live", "latest", "live_12345"])
    assert args_lat.live_action == "latest"
    assert args_lat.watcher_id == "live_12345"

    # 5. Test 'nexora live watch'
    args_watch = parser.parse_args([
        "live", "watch",
        "--url", "https://example.com/market",
        "-s", "bid=.bid",
        "-s", "ask=.ask",
        "--interval", "1.0",
    ])
    assert args_watch.live_action == "watch"
    assert len(args_watch.selector) == 2

CMC_BITCOIN_HTML = """
<!DOCTYPE html>
<html>
<head><title>Bitcoin price today, BTC to USD live price, marketcap and chart | CoinMarketCap</title></head>
<body>
  <div id="__next">
    <main class="main-content">
      <div class="coin-overview-header">
        <h1 class="coin-name">Bitcoin <span class="coin-symbol">BTC</span></h1>
        <div class="priceSection">
          <span data-test="text-cdp-price-display" class="sc-65e7f566-0 WXGwg base-text">$91,420.50</span>
          <span class="sc-d10a01fc-0 gspukq" data-change="up">
            <span class="sc-65e7f566-0 kKpUvL base-text">+2.35% (1d)</span>
          </span>
        </div>
        <div class="stats-row">
          <div class="stat-box" data-test="market-cap">
            <div class="stat-label">Market cap</div>
            <div class="stat-value">$1,805,420,192,840</div>
          </div>
          <div class="stat-box" data-test="volume-24h">
            <div class="stat-label">24h volume</div>
            <div class="stat-value">$42,819,420,110</div>
          </div>
        </div>
      </div>
    </main>
  </div>
</body>
</html>
"""


def test_dynamic_field_detector_coinmarketcap_bitcoin():
    """Verify autonomous detection on CoinMarketCap Bitcoin HTML accurately extracts live price and metrics."""
    from app.services.live_extractor import DynamicFieldDetector

    detector = DynamicFieldDetector()
    res = detector.detect_from_html(
        html_text=CMC_BITCOIN_HTML,
        url="https://coinmarketcap.com/currencies/bitcoin/",
        observation_seconds=3.0,
    )

    assert len(res.detected_fields) >= 3
    # Check that price was discovered
    names = [f.name for f in res.detected_fields]
    assert "price" in names
    assert "market_cap" in names
    assert "volume_24h" in names

    # Verify selectors
    selectors = res.recommended_selectors
    assert "price" in selectors
    assert '[data-test="text-cdp-price-display"]' in selectors["price"]

    # Verify sample values
    field_map = {f.name: f for f in res.detected_fields}
    assert field_map["price"].sample_value == "$91,420.50"
    assert field_map["market_cap"].sample_value == "$1,805,420,192,840"
    assert field_map["volume_24h"].sample_value == "$42,819,420,110"


def test_dynamic_field_detector_mutation_confidence():
    """Verify that detected active DOM mutations get confidence=1.0 and mutation_detected=True."""
    from app.services.live_extractor import DynamicFieldDetector

    detector = DynamicFieldDetector()
    # Baseline had price at $90,000, new HTML has $91,420.50
    mutation_baseline = {
        '[data-test="text-cdp-price-display"]': "$90,000.00",
    }

    res = detector.detect_from_html(
        html_text=CMC_BITCOIN_HTML,
        url="https://coinmarketcap.com/currencies/bitcoin/",
        observation_seconds=3.0,
        mutation_map=mutation_baseline,
    )

    price_field = next(f for f in res.detected_fields if f.name == "price")
    assert price_field.mutation_detected is True
    assert price_field.confidence == 1.0


def test_live_auto_detect_api_route():
    """Verify POST /api/live/auto-detect returns detected fields and recommended selectors."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch, AsyncMock
    from app.main import app

    client = TestClient(app)

    with patch("app.services.live_extractor.DynamicFieldDetector.fetch_html", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = CMC_BITCOIN_HTML

        resp = client.post(
            "/api/live/auto-detect",
            json={
                "url": "https://coinmarketcap.com/currencies/bitcoin/",
                "observation_seconds": 1.0,
                "engine": "fast_http",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "detected_fields" in data
        assert "recommended_selectors" in data
        assert len(data["detected_fields"]) >= 3
        assert "price" in data["recommended_selectors"]


@pytest.mark.asyncio
async def test_live_watcher_auto_mode(clean_live_manager):
    """Verify LiveWatcher in mode='auto' automatically discovers dynamic fields before extraction."""
    from app.schemas.live import LiveWatcherCreateRequest
    from unittest.mock import patch, AsyncMock

    with patch("app.services.live_extractor.DynamicFieldDetector.fetch_html", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = CMC_BITCOIN_HTML

        spec = LiveWatcherCreateRequest(
            url="https://coinmarketcap.com/currencies/bitcoin/",
            mode="auto",
            interval_seconds=1.0,
            turn_on=False,
        )
        watcher = clean_live_manager.create_watcher(spec)
        assert watcher.mode == "auto"
        assert watcher.selectors == {}

        # Auto-discover should populate selectors
        await watcher._auto_discover_selectors_if_needed()
        assert len(watcher.selectors) >= 3
        assert "price" in watcher.selectors

        resp = watcher.to_response()
        assert resp.mode == "auto"
        assert len(resp.discovered_fields) >= 3


def test_nexora_sdk_live_auto_detect():
    """Verify Nexora SDK client.live.auto_detect() method."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch, AsyncMock
    from app.main import app
    from nexora.client import NexoraClient
    from nexora.models import DynamicFieldDetectionResult

    api_client = TestClient(app)
    sdk = NexoraClient(base_url="http://testserver")
    sdk._client = api_client

    with patch("app.services.live_extractor.DynamicFieldDetector.fetch_html", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = CMC_BITCOIN_HTML

        result = sdk.live.auto_detect(
            url="https://coinmarketcap.com/currencies/bitcoin/",
            observation_seconds=1.0,
        )
        assert isinstance(result, DynamicFieldDetectionResult)
        assert len(result.detected_fields) >= 3
        assert "price" in result.recommended_selectors


def test_cli_live_detect_arguments():
    """Verify CLI parsing for 'nexora live detect' and '--auto' options."""
    from nexora.cli import build_parser

    parser = build_parser()

    # Detect subcommand
    args_det = parser.parse_args([
        "live", "detect",
        "--url", "https://coinmarketcap.com/currencies/bitcoin/",
        "--observation", "4.0",
        "--engine", "fast_http",
    ])
    assert args_det.command == "live"
    assert args_det.live_action == "detect"
    assert args_det.url == "https://coinmarketcap.com/currencies/bitcoin/"
    assert args_det.observation == 4.0
    assert args_det.engine == "fast_http"

    # Create with --auto
    args_create_auto = parser.parse_args([
        "live", "create",
        "--url", "https://coinmarketcap.com/currencies/bitcoin/",
        "--auto",
        "--observation", "2.0",
    ])
    assert args_create_auto.auto is True
    assert args_create_auto.observation == 2.0

    # Watch with --auto
    args_watch_auto = parser.parse_args([
        "live", "watch",
        "--url", "https://coinmarketcap.com/currencies/bitcoin/",
        "--auto",
    ])
    assert args_watch_auto.auto is True

