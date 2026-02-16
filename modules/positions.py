"""
Positions module — track open positions with P&L calculations.

Positions are stored in a local JSON file for simplicity.
"""
import json
import os
import time
from pathlib import Path
from modules.markets import get_market_detail
from utils.logger import get_logger

logger = get_logger("positions")

POSITIONS_FILE = Path(os.getenv("POSITIONS_FILE", "positions.json"))


def _load_positions() -> list[dict]:
    """Load positions from disk."""
    if not POSITIONS_FILE.exists():
        return []
    try:
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_positions(positions: list[dict]):
    """Save positions to disk."""
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2)


def record_position(
    condition_id: str,
    side: str,
    size: float,
    entry_price: float,
) -> dict:
    """Record a new position."""
    positions = _load_positions()

    position = {
        "id": f"{condition_id}_{side}_{int(time.time())}",
        "condition_id": condition_id,
        "side": side.upper(),
        "size": size,
        "entry_price": entry_price,
        "opened_at": time.time(),
        "closed": False,
    }

    positions.append(position)
    _save_positions(positions)
    logger.info(f"Recorded position: {side} {size} @ {entry_price:.4f} on {condition_id}")
    return position


async def get_positions_with_pnl() -> list[dict]:
    """Load all open positions and compute current P&L."""
    positions = _load_positions()
    open_positions = [p for p in positions if not p.get("closed")]

    results = []
    for pos in open_positions:
        market = await get_market_detail(pos["condition_id"])
        if not market:
            pos["current_price"] = None
            pos["pnl_usd"] = None
            pos["pnl_pct"] = None
            results.append(pos)
            continue

        if pos["side"] == "YES":
            current = market.get("yes_price", 0) or 0
        else:
            current = market.get("no_price", 0) or 0

        entry = pos["entry_price"]
        size = pos["size"]

        pnl_per_token = current - entry
        pnl_usd = pnl_per_token * size
        pnl_pct = (pnl_per_token / entry * 100) if entry > 0 else 0

        pos["current_price"] = current
        pos["pnl_usd"] = round(pnl_usd, 4)
        pos["pnl_pct"] = round(pnl_pct, 2)
        pos["market_question"] = market.get("question", "")
        pos["current_value"] = round(current * size, 4)
        results.append(pos)

    return results


def close_position(position_id: str) -> bool:
    """Mark a position as closed."""
    positions = _load_positions()
    for p in positions:
        if p["id"] == position_id:
            p["closed"] = True
            p["closed_at"] = time.time()
            _save_positions(positions)
            logger.info(f"Closed position {position_id}")
            return True
    return False
