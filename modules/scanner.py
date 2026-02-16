"""
Arbitrage scanner — finds mispriced binary markets on Polymarket.

Strategy: In a binary market, YES + NO should sum to ~$1.00.
When YES + NO < 1.0 (minus fees), there's an arbitrage opportunity:
buy both sides, guaranteed $1.00 payout regardless of outcome.
"""
import asyncio
from config import (
    MIN_PROFIT_THRESHOLD,
    MAX_POSITION_SIZE,
    TAKER_FEE_RATE,
    MIN_LIQUIDITY,
)
from modules.markets import fetch_trending, search_markets
from utils.logger import get_logger, log_opportunity
from utils.notifier import notify_opportunity

logger = get_logger("scanner")


async def scan_for_arbitrage(
    markets: list[dict] | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    Scan markets for pair-cost arbitrage opportunities.

    A binary market pays $1 for the winning side. If you can buy
    YES + NO for less than $1 (after fees), you profit regardless
    of outcome.
    """
    if markets is None:
        markets = await fetch_trending(limit=limit)

    opportunities = []

    for market in markets:
        yes_price = market.get("yes_price")
        no_price = market.get("no_price")

        if yes_price is None or no_price is None:
            continue

        if market.get("liquidity", 0) < MIN_LIQUIDITY:
            continue

        total_cost = yes_price + no_price
        fee = TAKER_FEE_RATE * 2  # Fee on both legs
        net_cost = total_cost + fee
        guaranteed_payout = 1.0
        net_profit = guaranteed_payout - net_cost
        net_profit_pct = net_profit / net_cost if net_cost > 0 else 0

        if net_profit_pct >= MIN_PROFIT_THRESHOLD:
            opp = {
                "strategy": "pair_cost_arb",
                "condition_id": market["condition_id"],
                "market_question": market["question"],
                "yes_price": yes_price,
                "no_price": no_price,
                "total_cost": net_cost,
                "net_profit": net_profit,
                "net_profit_pct": net_profit_pct,
                "liquidity": market.get("liquidity", 0),
                "max_size": min(MAX_POSITION_SIZE, market.get("liquidity", 0) * 0.1),
            }
            opportunities.append(opp)
            log_opportunity(logger, opp)
            notify_opportunity(opp)

    opportunities.sort(key=lambda x: x["net_profit_pct"], reverse=True)
    logger.info(
        f"Scan complete: {len(opportunities)} opportunities "
        f"from {len(markets)} markets"
    )
    return opportunities


async def scan_with_query(query: str, limit: int = 50) -> list[dict]:
    """Scan markets matching a search query for arbitrage."""
    markets = await search_markets(query, limit=limit)
    return await scan_for_arbitrage(markets=markets)


async def continuous_scan(interval: int = 10, limit: int = 50):
    """Run the scanner continuously at a given interval."""
    logger.info(f"Starting continuous scan (interval={interval}s)")
    while True:
        try:
            opps = await scan_for_arbitrage(limit=limit)
            if opps:
                logger.info(f"Found {len(opps)} opportunities this cycle")
        except Exception as e:
            logger.error(f"Scan error: {e}")
        await asyncio.sleep(interval)
