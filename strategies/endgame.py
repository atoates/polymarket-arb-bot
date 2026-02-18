"""
Endgame strategy — buy near-certain outcomes approaching resolution.

Targets markets resolving within 24-72 hours where one side is priced
at 95%+ probability. The annualized return on these "final stretch" trades
is extremely high even though per-trade profit is thin.

Risk management:
  - Only buy outcomes above MIN_CONFIDENCE threshold
  - Cap per-market exposure
  - Verify resolution timeline
"""
import time
from datetime import datetime, timezone
from config import MAX_POSITION_SIZE
from utils.logger import get_logger

logger = get_logger("endgame")

MIN_CONFIDENCE = float(0.95)
MAX_HOURS_TO_RESOLUTION = 72
MIN_HOURS_TO_RESOLUTION = 1
MAX_ENDGAME_EXPOSURE = float(MAX_POSITION_SIZE * 2)


def find_endgame_opportunities(
    markets: list[dict],
    min_confidence: float = MIN_CONFIDENCE,
    max_hours: float = MAX_HOURS_TO_RESOLUTION,
) -> list[dict]:
    """
    Scan markets for endgame opportunities.

    Criteria:
      1. Market resolves within max_hours
      2. One side is priced at min_confidence or above
      3. Market has reasonable liquidity
    """
    now = time.time()
    opportunities = []

    for market in markets:
        end_date_str = market.get("end_date", "")
        if not end_date_str:
            continue

        try:
            end_dt = _parse_end_date(end_date_str)
        except (ValueError, TypeError):
            continue

        hours_remaining = (end_dt.timestamp() - now) / 3600
        if hours_remaining < MIN_HOURS_TO_RESOLUTION:
            continue
        if hours_remaining > max_hours:
            continue

        yes_price = market.get("yes_price")
        no_price = market.get("no_price")
        if yes_price is None or no_price is None:
            continue

        high_side = None
        high_price = 0
        low_price = 0

        if yes_price >= min_confidence:
            high_side = "YES"
            high_price = yes_price
            low_price = no_price
        elif no_price >= min_confidence:
            high_side = "NO"
            high_price = no_price
            low_price = yes_price
        else:
            continue

        profit_per_token = 1.0 - high_price
        if profit_per_token <= 0:
            continue

        annualized_return = _annualize(profit_per_token / high_price, hours_remaining)
        max_size = min(MAX_ENDGAME_EXPOSURE, market.get("liquidity", 0) * 0.05)

        opp = {
            "strategy": "endgame",
            "condition_id": market["condition_id"],
            "market_question": market.get("question", ""),
            "recommended_side": high_side,
            "price": high_price,
            "profit_per_token": round(profit_per_token, 4),
            "hours_to_resolution": round(hours_remaining, 1),
            "annualized_return": round(annualized_return, 2),
            "max_size": max_size,
            "liquidity": market.get("liquidity", 0),
            "yes_token_id": market.get("yes_token_id"),
            "no_token_id": market.get("no_token_id"),
        }
        opportunities.append(opp)

    opportunities.sort(key=lambda x: x["annualized_return"], reverse=True)
    logger.info(f"Endgame scan: {len(opportunities)} opportunities")
    return opportunities


def _annualize(return_pct: float, hours: float) -> float:
    """Convert a return over N hours to annualized percentage."""
    if hours <= 0:
        return 0
    periods_per_year = 8760 / hours
    return return_pct * periods_per_year * 100


def _parse_end_date(date_str: str) -> datetime:
    """Parse various date formats from the Gamma API."""
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}")


async def execute_endgame(opp: dict, dry_run: bool = True) -> dict | None:
    """Execute an endgame trade — buy the high-confidence side."""
    from modules.trading import buy

    side = opp["recommended_side"]
    token_id = (
        opp.get("yes_token_id") if side == "YES" else opp.get("no_token_id")
    )

    result = buy(
        condition_id=opp["condition_id"],
        side=side,
        amount_usdc=opp["max_size"],
        current_price=opp["price"],
        yes_token_id=opp.get("yes_token_id"),
        no_token_id=opp.get("no_token_id"),
        skip_sell=True,
        dry_run=dry_run,
    )

    return {
        "market": opp["market_question"],
        "side": side,
        "price": opp["price"],
        "hours_left": opp["hours_to_resolution"],
        "annualized_return": opp["annualized_return"],
        "result": result,
    }
