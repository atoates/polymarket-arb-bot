"""
WebSocket price feed — real-time orderbook and price updates from Polymarket CLOB.

Connects to wss://ws-subscriptions-clob.polymarket.com/ws/market
and maintains an in-memory price cache for subscribed tokens.
"""
import asyncio
import json
import time
from collections import defaultdict
from typing import Callable

import websockets

from utils.logger import get_logger

logger = get_logger("ws_feed")

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
PING_INTERVAL = 20
RECONNECT_DELAY_BASE = 1
RECONNECT_DELAY_MAX = 60


class PriceCache:
    """Thread-safe in-memory price cache updated by WebSocket feed."""

    def __init__(self):
        self._prices: dict[str, dict] = {}
        self._updated_at: dict[str, float] = {}

    def update(self, token_id: str, data: dict):
        if token_id not in self._prices:
            self._prices[token_id] = {}
        self._prices[token_id].update(data)
        self._updated_at[token_id] = time.time()

    def get(self, token_id: str) -> dict | None:
        return self._prices.get(token_id)

    def get_price(self, token_id: str) -> float | None:
        entry = self._prices.get(token_id)
        if not entry:
            return None
        return entry.get("price") or entry.get("best_bid")

    def get_best_bid_ask(self, token_id: str) -> tuple[float | None, float | None]:
        entry = self._prices.get(token_id)
        if not entry:
            return None, None
        return entry.get("best_bid"), entry.get("best_ask")

    def age(self, token_id: str) -> float | None:
        ts = self._updated_at.get(token_id)
        if ts is None:
            return None
        return time.time() - ts

    def all_prices(self) -> dict[str, dict]:
        return dict(self._prices)

    def clear(self):
        self._prices.clear()
        self._updated_at.clear()


# Global price cache
price_cache = PriceCache()


class MarketFeed:
    """
    WebSocket client for Polymarket CLOB market data.

    Subscribes to token IDs and pushes updates to a PriceCache
    and optional callback functions.
    """

    def __init__(
        self,
        asset_ids: list[str],
        cache: PriceCache | None = None,
        on_price_change: Callable | None = None,
        on_book_update: Callable | None = None,
    ):
        self._asset_ids = list(asset_ids)
        self._cache = cache or price_cache
        self._on_price_change = on_price_change
        self._on_book_update = on_book_update
        self._ws = None
        self._running = False
        self._reconnect_delay = RECONNECT_DELAY_BASE

    async def start(self):
        """Connect and process messages forever with auto-reconnect."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except (
                websockets.exceptions.ConnectionClosed,
                ConnectionRefusedError,
                OSError,
            ) as e:
                if not self._running:
                    break
                logger.warning(
                    f"WS disconnected: {e} — reconnecting in "
                    f"{self._reconnect_delay}s"
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, RECONNECT_DELAY_MAX
                )
            except Exception as e:
                logger.error(f"WS unexpected error: {e}")
                if not self._running:
                    break
                await asyncio.sleep(self._reconnect_delay)

    async def stop(self):
        self._running = False
        if self._ws:
            await self._ws.close()

    def subscribe(self, asset_ids: list[str]):
        """Add tokens to subscription (takes effect on next reconnect or via live sub)."""
        new_ids = [aid for aid in asset_ids if aid not in self._asset_ids]
        self._asset_ids.extend(new_ids)

    async def _connect_and_listen(self):
        async with websockets.connect(
            WS_URL, ping_interval=PING_INTERVAL
        ) as ws:
            self._ws = ws
            self._reconnect_delay = RECONNECT_DELAY_BASE

            sub_msg = {
                "auth": {},
                "type": "market",
                "assets_ids": self._asset_ids,
            }
            await ws.send(json.dumps(sub_msg))
            logger.info(f"WS subscribed to {len(self._asset_ids)} tokens")

            async for raw in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw)
                    await self._handle_message(msg)
                except json.JSONDecodeError:
                    logger.warning(f"WS non-JSON message: {raw[:100]}")

    async def _handle_message(self, msg: list | dict):
        if isinstance(msg, list):
            for item in msg:
                await self._process_event(item)
        else:
            await self._process_event(msg)

    async def _process_event(self, event: dict):
        event_type = event.get("event_type", "")

        if event_type == "price_change":
            changes = event.get("changes", [])
            for change in changes:
                token_id = change.get("asset_id", "")
                if not token_id:
                    continue
                data = {
                    "price": _safe_float(change.get("price")),
                    "best_bid": _safe_float(change.get("best_bid")),
                    "best_ask": _safe_float(change.get("best_ask")),
                }
                self._cache.update(token_id, data)
                if self._on_price_change:
                    try:
                        self._on_price_change(token_id, data)
                    except Exception as e:
                        logger.error(f"price_change callback error: {e}")

        elif event_type == "book":
            token_id = event.get("asset_id", "")
            if token_id:
                book_data = {
                    "bids": event.get("bids", []),
                    "asks": event.get("asks", []),
                    "best_bid": _best_level(event.get("bids", []), "price"),
                    "best_ask": _best_level(event.get("asks", []), "price"),
                }
                self._cache.update(token_id, book_data)
                if self._on_book_update:
                    try:
                        self._on_book_update(token_id, book_data)
                    except Exception as e:
                        logger.error(f"book callback error: {e}")

        elif event_type == "last_trade_price":
            token_id = event.get("asset_id", "")
            if token_id:
                self._cache.update(token_id, {
                    "last_trade_price": _safe_float(event.get("price")),
                })


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _best_level(levels: list, key: str = "price") -> float | None:
    if not levels:
        return None
    try:
        return float(levels[0].get(key, 0))
    except (ValueError, TypeError, IndexError):
        return None
