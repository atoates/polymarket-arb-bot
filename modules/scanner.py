"""
Arbitrage scanner — finds mispriced binary markets on Polymarket.

Strategy: In a binary market, YES + NO should sum to ~$1.00.
When YES + NO < 1.0 (minus fees), there's an arbitrage opportunity:
buy both sides, guaranteed $1.00 payout regardless of outcome.
"""
import asyncio
import time as _time
from config import (
    MIN_PROFIT_THRESHOLD,
    MAX_POSITION_SIZE,
    TAKER_FEE_RATE,
    MIN_LIQUIDITY,
    DRY_RUN,
    MAX_TRADES_PER_HOUR,
)
from modules.markets import fetch_trending, search_markets, get_market_detail
from utils.logger import get_logger, log_opportunity
from utils.notifier import notify_opportunity

logger = get_logger("scanner")

# Track recent trades to enforce rate limits
_recent_trades: list[float] = []


def _trades_in_last_hour() -> int:
    cutoff = _time.time() - 3600
    return sum(1 for t in _recent_trades if t > cutoff)


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
        fee = TAKER_FEE_RATE * 2
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
                "yes_token_id": market.get("yes_token_id"),
                "no_token_id": market.get("no_token_id"),
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


async def execute_opportunity(opp: dict, dry_run: bool = True) -> dict | None:
    """
    Execute a single arbitrage opportunity by buying both YES and NO.

    Returns trade results or None if skipped.
    """
    from modules.trading import buy

    if _trades_in_last_hour() >= MAX_TRADES_PER_HOUR:
        logger.warning("Rate limit reached — skipping execution")
        return None

    condition_id = opp["condition_id"]
    size = min(opp["max_size"], MAX_POSITION_SIZE)
    if size <= 0:
        return None

    # Refresh market data to avoid stale prices
    market = await get_market_detail(condition_id)
    if not market:
        logger.warning(f"Market {condition_id} not found on refresh")
        return None

    yes_price = market.get("yes_price") or 0
    no_price = market.get("no_price") or 0
    refreshed_cost = yes_price + no_price + (TAKER_FEE_RATE * 2)
    if refreshed_cost >= 1.0:
        logger.info(f"Opportunity gone after refresh: cost={refreshed_cost:.4f}")
        return None

    logger.info(
        f"Executing arb on {opp['market_question'][:60]} — "
        f"size=${size:.2f}, profit={opp['net_profit_pct']:.2%}"
    )

    yes_result = buy(
        condition_id=market.get("condition_id", condition_id),
        side="YES",
        amount_usdc=size / 2,
        current_price=yes_price,
        yes_token_id=market.get("yes_token_id"),
        no_token_id=market.get("no_token_id"),
        skip_sell=True,
        dry_run=dry_run,
    )

    no_result = buy(
        condition_id=market.get("condition_id", condition_id),
        side="NO",
        amount_usdc=size / 2,
        current_price=no_price,
        yes_token_id=market.get("yes_token_id"),
        no_token_id=market.get("no_token_id"),
        skip_sell=True,
        dry_run=dry_run,
    )

    if not dry_run:
        _recent_trades.append(_time.time())

    return {
        "condition_id": condition_id,
        "market": opp["market_question"],
        "size": size,
        "yes_result": yes_result,
        "no_result": no_result,
        "profit_pct": opp["net_profit_pct"],
    }


async def continuous_scan(
    interval: int = 10,
    limit: int = 50,
    auto_execute: bool = False,
    max_concurrent: int = 3,
    dry_run: bool = True,
    query: str | None = None,
):
    """
    Run the scanner continuously at a given interval.

    Args:
        interval: Seconds between scans
        auto_execute: If True, automatically trade found opportunities
        max_concurrent: Max opportunities to execute per cycle
        dry_run: If True, log trades but don't execute
        query: Optional search filter
    """
    logger.info(
        f"Starting continuous scan (interval={interval}s, "
        f"auto_execute={auto_execute}, dry_run={dry_run})"
    )
    cycle = 0
    while True:
        cycle += 1
        try:
            if query:
                opps = await scan_with_query(query, limit=limit)
            else:
                opps = await scan_for_arbitrage(limit=limit)

            if opps:
                logger.info(f"Cycle {cycle}: found {len(opps)} opportunities")

            if auto_execute and opps:
                for opp in opps[:max_concurrent]:
                    try:
                        result = await execute_opportunity(opp, dry_run=dry_run)
                        if result:
                            logger.info(
                                f"Executed: {result['market'][:50]} "
                                f"profit={result['profit_pct']:.2%}"
                            )
                    except Exception as e:
                        logger.error(f"Execution error: {e}")

        except Exception as e:
            logger.error(f"Scan error: {e}")

        await asyncio.sleep(interval)
