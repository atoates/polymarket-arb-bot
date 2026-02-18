"""
Risk management module — enforces position limits, drawdown protection,
and daily loss caps.

All checks are stateless reads from positions.json + wallet balance.
The engine should call check_risk_limits() before every trade.
"""
import os
import time
from config import MAX_POSITION_SIZE
from utils.logger import get_logger

logger = get_logger("risk")

MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", "20"))
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "50.0"))
MAX_MARKET_EXPOSURE = float(os.getenv("MAX_MARKET_EXPOSURE", str(MAX_POSITION_SIZE * 3)))
MAX_TOTAL_EXPOSURE = float(os.getenv("MAX_TOTAL_EXPOSURE", "500.0"))
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "10"))

_kill_switch_active = False
_initial_portfolio_value: float | None = None


class RiskLimitExceeded(Exception):
    """Raised when a trade would violate risk limits."""
    pass


def set_initial_portfolio_value(value: float):
    global _initial_portfolio_value
    _initial_portfolio_value = value
    logger.info(f"Initial portfolio value set: ${value:.2f}")


def activate_kill_switch(reason: str = ""):
    global _kill_switch_active
    _kill_switch_active = True
    logger.critical(f"KILL SWITCH ACTIVATED: {reason}")
    from utils.notifier import notify_error
    notify_error(f"KILL SWITCH ACTIVATED: {reason}")


def deactivate_kill_switch():
    global _kill_switch_active
    _kill_switch_active = False
    logger.info("Kill switch deactivated")


def is_kill_switch_active() -> bool:
    return _kill_switch_active


def check_risk_limits(
    proposed_size: float,
    condition_id: str = "",
    side: str = "",
) -> dict:
    """
    Pre-trade risk check. Returns a dict with pass/fail and reasons.

    Checks:
      1. Kill switch is not active
      2. Proposed size within per-trade limit
      3. Market exposure within cap
      4. Total exposure within cap
      5. Concurrent positions within limit
      6. Daily loss within cap
      7. Drawdown within limit
    """
    from modules.positions import _load_positions

    violations = []

    if _kill_switch_active:
        violations.append("Kill switch is active — all trading halted")
        return {"allowed": False, "violations": violations}

    if proposed_size > MAX_POSITION_SIZE:
        violations.append(
            f"Size ${proposed_size:.2f} exceeds per-trade limit ${MAX_POSITION_SIZE:.2f}"
        )

    positions = _load_positions()
    open_positions = [p for p in positions if not p.get("closed")]

    if len(open_positions) >= MAX_CONCURRENT_POSITIONS:
        violations.append(
            f"At max concurrent positions ({MAX_CONCURRENT_POSITIONS})"
        )

    if condition_id:
        market_exposure = sum(
            p["size"] * p["entry_price"]
            for p in open_positions
            if p["condition_id"] == condition_id
        )
        if market_exposure + proposed_size > MAX_MARKET_EXPOSURE:
            violations.append(
                f"Market exposure ${market_exposure + proposed_size:.2f} "
                f"exceeds cap ${MAX_MARKET_EXPOSURE:.2f}"
            )

    total_exposure = sum(p["size"] * p["entry_price"] for p in open_positions)
    if total_exposure + proposed_size > MAX_TOTAL_EXPOSURE:
        violations.append(
            f"Total exposure ${total_exposure + proposed_size:.2f} "
            f"exceeds cap ${MAX_TOTAL_EXPOSURE:.2f}"
        )

    daily_loss = _compute_daily_loss(positions)
    if daily_loss >= MAX_DAILY_LOSS:
        violations.append(
            f"Daily loss ${daily_loss:.2f} exceeds limit ${MAX_DAILY_LOSS:.2f}"
        )
        activate_kill_switch(f"Daily loss limit hit: ${daily_loss:.2f}")

    if _initial_portfolio_value and _initial_portfolio_value > 0:
        current_value = _initial_portfolio_value - daily_loss
        drawdown_pct = (
            (_initial_portfolio_value - current_value)
            / _initial_portfolio_value
            * 100
        )
        if drawdown_pct >= MAX_DRAWDOWN_PCT:
            violations.append(
                f"Drawdown {drawdown_pct:.1f}% exceeds limit {MAX_DRAWDOWN_PCT:.1f}%"
            )
            activate_kill_switch(f"Max drawdown hit: {drawdown_pct:.1f}%")

    result = {
        "allowed": len(violations) == 0,
        "violations": violations,
        "open_positions": len(open_positions),
        "total_exposure": round(total_exposure, 2),
        "daily_loss": round(daily_loss, 2),
    }

    if violations:
        logger.warning(f"Risk check FAILED: {violations}")
    else:
        logger.info(
            f"Risk check passed: size=${proposed_size:.2f}, "
            f"exposure=${total_exposure:.2f}, daily_loss=${daily_loss:.2f}"
        )

    return result


def _compute_daily_loss(positions: list[dict]) -> float:
    """Sum realized losses from positions closed today."""
    day_start = _today_start_ts()
    daily_loss = 0.0

    for p in positions:
        if not p.get("closed"):
            continue
        closed_at = p.get("closed_at", 0)
        if closed_at < day_start:
            continue
        realized = p.get("realized_pnl", 0)
        if realized < 0:
            daily_loss += abs(realized)

    return daily_loss


def _today_start_ts() -> float:
    """Midnight UTC timestamp for today."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


def get_risk_summary() -> dict:
    """Get current risk metrics for display."""
    from modules.positions import _load_positions

    positions = _load_positions()
    open_positions = [p for p in positions if not p.get("closed")]

    total_exposure = sum(p["size"] * p["entry_price"] for p in open_positions)
    daily_loss = _compute_daily_loss(positions)

    per_market: dict[str, float] = {}
    for p in open_positions:
        cid = p["condition_id"]
        per_market[cid] = per_market.get(cid, 0) + p["size"] * p["entry_price"]

    return {
        "kill_switch": _kill_switch_active,
        "open_positions": len(open_positions),
        "total_exposure": round(total_exposure, 2),
        "max_total_exposure": MAX_TOTAL_EXPOSURE,
        "daily_loss": round(daily_loss, 2),
        "max_daily_loss": MAX_DAILY_LOSS,
        "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        "top_markets": sorted(
            per_market.items(), key=lambda x: x[1], reverse=True
        )[:5],
    }
