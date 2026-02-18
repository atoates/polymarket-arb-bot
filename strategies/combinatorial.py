"""
Combinatorial arbitrage — multi-outcome neg_risk markets.

In neg_risk markets with N outcomes that should sum to $1.00,
buy all outcomes when the total cost is below $1.00 for guaranteed profit.
"""
import asyncio
import httpx
from config import (
    TAKER_FEE_RATE,
    MIN_PROFIT_THRESHOLD,
    MAX_POSITION_SIZE,
    MIN_LIQUIDITY,
)
from utils.logger import get_logger, log_opportunity
from utils.notifier import notify_opportunity

logger = get_logger("combinatorial")

GAMMA_API = "https://gamma-api.polymarket.com"


async def fetch_neg_risk_events(limit: int = 30) -> list[dict]:
    """
    Fetch multi-outcome events (neg_risk) from the Gamma API.

    These are events with 3+ outcomes where buying all outcomes
    guarantees a $1 payout. The neg_risk exchange handles settlement.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GAMMA_API}/events",
            params={
                "limit": limit,
                "active": True,
                "closed": False,
                "order": "volume24hr",
                "ascending": False,
            },
        )
        resp.raise_for_status()
        events = resp.json()

    multi_outcome = []
    for event in events:
        markets = event.get("markets", [])
        if len(markets) >= 3 and event.get("negRisk", False):
            multi_outcome.append(event)

    logger.info(f"Found {len(multi_outcome)} neg_risk events from {len(events)} total")
    return multi_outcome


def analyze_event(event: dict) -> dict | None:
    """
    Analyze a neg_risk event for arbitrage.

    For each market (outcome) in the event, find the cheapest YES price.
    If sum of all YES prices < $1.00 (after fees), it's profitable.
    """
    markets = event.get("markets", [])
    outcomes = []
    total_cost = 0.0
    min_liquidity = float("inf")

    for m in markets:
        tokens = m.get("tokens", [])
        yes_price = None
        yes_token_id = None

        for t in tokens:
            if t.get("outcome", "").upper() == "YES":
                yes_price = float(t.get("price", 0) or 0)
                yes_token_id = t.get("token_id", "")
                break

        if not yes_price or yes_price <= 0:
            outcome_prices = m.get("outcomePrices")
            if outcome_prices:
                try:
                    import json as _json
                    prices = _json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                    if prices and len(prices) >= 1:
                        yes_price = float(prices[0])
                except (ValueError, IndexError):
                    pass

        if not yes_price or yes_price <= 0:
            return None

        liquidity = float(m.get("liquidityNum", 0) or 0)
        min_liquidity = min(min_liquidity, liquidity)

        outcomes.append({
            "condition_id": m.get("conditionId", ""),
            "question": m.get("question", ""),
            "yes_price": yes_price,
            "yes_token_id": yes_token_id,
            "liquidity": liquidity,
        })
        total_cost += yes_price

    if min_liquidity < MIN_LIQUIDITY:
        return None

    fee = TAKER_FEE_RATE * len(outcomes)
    net_cost = total_cost + fee
    net_profit = 1.0 - net_cost
    net_profit_pct = net_profit / net_cost if net_cost > 0 else 0

    if net_profit_pct < MIN_PROFIT_THRESHOLD:
        return None

    return {
        "strategy": "combinatorial_arb",
        "event_id": event.get("id", ""),
        "event_title": event.get("title", ""),
        "num_outcomes": len(outcomes),
        "outcomes": outcomes,
        "total_cost": round(net_cost, 6),
        "net_profit": round(net_profit, 6),
        "net_profit_pct": net_profit_pct,
        "min_liquidity": min_liquidity,
        "max_size": min(MAX_POSITION_SIZE, min_liquidity * 0.1),
    }


async def scan_combinatorial(limit: int = 30) -> list[dict]:
    """Scan neg_risk events for combinatorial arbitrage opportunities."""
    events = await fetch_neg_risk_events(limit=limit)
    opportunities = []

    for event in events:
        opp = analyze_event(event)
        if opp:
            opportunities.append(opp)
            log_opportunity(logger, opp)
            notify_opportunity(opp)

    opportunities.sort(key=lambda x: x["net_profit_pct"], reverse=True)
    logger.info(f"Combinatorial scan: {len(opportunities)} opps from {len(events)} events")
    return opportunities


async def execute_combinatorial(opp: dict, dry_run: bool = True) -> dict | None:
    """
    Execute a combinatorial arb by buying YES on all outcomes.

    Each outcome gets an equal share of the position size.
    """
    from modules.trading import buy

    size = opp["max_size"]
    per_outcome = size / opp["num_outcomes"]
    results = []

    for outcome in opp["outcomes"]:
        if not outcome.get("condition_id"):
            continue

        result = buy(
            condition_id=outcome["condition_id"],
            side="YES",
            amount_usdc=per_outcome,
            current_price=outcome["yes_price"],
            yes_token_id=outcome.get("yes_token_id"),
            skip_sell=True,
            dry_run=dry_run,
        )
        results.append(result)

    return {
        "event": opp["event_title"],
        "outcomes_traded": len(results),
        "total_size": size,
        "profit_pct": opp["net_profit_pct"],
        "results": results,
    }
