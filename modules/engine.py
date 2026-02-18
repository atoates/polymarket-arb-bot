"""
Trading engine — orchestrates strategies, WebSocket feeds, and risk management.

Usage:
  engine = TradingEngine(strategies=["arb", "endgame"], dry_run=True)
  await engine.run()
"""
import asyncio
import signal
import time
from typing import Any

from config import (
    DRY_RUN,
    SCAN_INTERVAL_SECONDS,
    MAX_POSITION_SIZE,
    MAX_TRADES_PER_HOUR,
)
from modules.ws_feed import MarketFeed, price_cache
from modules.markets import fetch_trending
from utils.logger import get_logger

logger = get_logger("engine")

STRATEGY_REGISTRY: dict[str, type] = {}


def register_strategy(name: str):
    """Decorator to register a strategy class."""
    def decorator(cls):
        STRATEGY_REGISTRY[name] = cls
        return cls
    return decorator


class BaseStrategy:
    """Interface for pluggable strategies."""

    name: str = "base"

    def __init__(self, engine: "TradingEngine"):
        self.engine = engine
        self.logger = get_logger(f"strategy.{self.name}")

    async def on_tick(self, markets: list[dict]):
        """Called each scan cycle with current market data."""
        raise NotImplementedError

    async def on_price_change(self, token_id: str, data: dict):
        """Called on real-time price update (optional)."""
        pass


@register_strategy("arb")
class ArbStrategy(BaseStrategy):
    """Pair-cost arbitrage: buy YES + NO when total < $1.00."""

    name = "arb"

    async def on_tick(self, markets: list[dict]):
        from modules.scanner import scan_for_arbitrage, execute_opportunity

        opps = await scan_for_arbitrage(markets=markets)
        if not opps:
            return

        self.logger.info(f"Found {len(opps)} arb opportunities")
        for opp in opps[:3]:
            try:
                result = await execute_opportunity(
                    opp, dry_run=self.engine.dry_run
                )
                if result:
                    self.logger.info(
                        f"{'[DRY]' if self.engine.dry_run else '[LIVE]'} "
                        f"Arb executed: {result['market'][:50]}"
                    )
            except Exception as e:
                self.logger.error(f"Arb execution error: {e}")


@register_strategy("endgame")
class EndgameStrategy(BaseStrategy):
    """Buy near-certain outcomes approaching resolution."""

    name = "endgame"

    async def on_tick(self, markets: list[dict]):
        from strategies.endgame import find_endgame_opportunities

        try:
            opps = find_endgame_opportunities(markets)
            if opps:
                self.logger.info(f"Found {len(opps)} endgame opportunities")
        except Exception as e:
            self.logger.error(f"Endgame scan error: {e}")


class TradingEngine:
    """
    Main trading loop that coordinates:
    - Market data fetching (HTTP polling + optional WebSocket)
    - Strategy execution on each tick
    - Risk management checks
    - Graceful shutdown
    """

    def __init__(
        self,
        strategies: list[str] | None = None,
        interval: int | None = None,
        dry_run: bool | None = None,
        use_ws: bool = False,
        limit: int = 50,
        query: str | None = None,
    ):
        self.interval = interval or SCAN_INTERVAL_SECONDS
        self.dry_run = dry_run if dry_run is not None else DRY_RUN
        self.use_ws = use_ws
        self.limit = limit
        self.query = query
        self._running = False
        self._cycle = 0
        self._started_at = 0.0
        self._ws_feed: MarketFeed | None = None

        strategy_names = strategies or ["arb"]
        self.strategies: list[BaseStrategy] = []
        for name in strategy_names:
            cls = STRATEGY_REGISTRY.get(name)
            if cls:
                self.strategies.append(cls(self))
            else:
                logger.warning(f"Unknown strategy: {name}")

    async def run(self):
        """Main run loop with signal handling."""
        self._running = True
        self._started_at = time.time()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
            except NotImplementedError:
                pass

        logger.info(
            f"Engine starting — strategies={[s.name for s in self.strategies]}, "
            f"interval={self.interval}s, dry_run={self.dry_run}, ws={self.use_ws}"
        )

        tasks = [asyncio.create_task(self._poll_loop())]

        if self.use_ws:
            tasks.append(asyncio.create_task(self._start_ws_feed()))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

        logger.info(
            f"Engine stopped after {self._cycle} cycles "
            f"({time.time() - self._started_at:.0f}s)"
        )

    async def stop(self):
        logger.info("Shutting down engine...")
        self._running = False
        if self._ws_feed:
            await self._ws_feed.stop()

    async def _poll_loop(self):
        while self._running:
            self._cycle += 1
            try:
                markets = await self._fetch_markets()
                for strategy in self.strategies:
                    try:
                        await strategy.on_tick(markets)
                    except Exception as e:
                        logger.error(f"Strategy {strategy.name} error: {e}")
            except Exception as e:
                logger.error(f"Poll cycle error: {e}")

            await asyncio.sleep(self.interval)

    async def _fetch_markets(self) -> list[dict]:
        if self.query:
            from modules.markets import search_markets
            return await search_markets(self.query, limit=self.limit)
        return await fetch_trending(limit=self.limit)

    async def _start_ws_feed(self):
        """Start WebSocket feed for subscribed tokens."""
        markets = await self._fetch_markets()
        token_ids = []
        for m in markets:
            if m.get("yes_token_id"):
                token_ids.append(m["yes_token_id"])
            if m.get("no_token_id"):
                token_ids.append(m["no_token_id"])

        if not token_ids:
            logger.warning("No token IDs to subscribe to WS")
            return

        def on_price_change(token_id: str, data: dict):
            for strategy in self.strategies:
                try:
                    asyncio.create_task(strategy.on_price_change(token_id, data))
                except Exception:
                    pass

        self._ws_feed = MarketFeed(
            asset_ids=token_ids[:500],
            on_price_change=on_price_change,
        )
        await self._ws_feed.start()
