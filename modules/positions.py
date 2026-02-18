"""
Positions module — track open positions with P&L calculations.

Positions are stored in a local JSON file for simplicity.
Includes on-chain CTF token balance reconciliation.
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


def close_position(position_id: str, exit_price: float | None = None) -> bool:
    """Mark a position as closed with optional exit price for P&L."""
    positions = _load_positions()
    for p in positions:
        if p["id"] == position_id:
            p["closed"] = True
            p["closed_at"] = time.time()
            if exit_price is not None:
                p["exit_price"] = exit_price
                p["realized_pnl"] = round(
                    (exit_price - p["entry_price"]) * p["size"], 4
                )
            _save_positions(positions)
            logger.info(f"Closed position {position_id} at {exit_price}")
            return True
    return False


def close_position_by_market(
    condition_id: str, side: str, exit_price: float | None = None
) -> bool:
    """Close the most recent open position matching condition_id + side."""
    positions = _load_positions()
    side = side.upper()
    for p in reversed(positions):
        if (
            p["condition_id"] == condition_id
            and p["side"] == side
            and not p.get("closed")
        ):
            p["closed"] = True
            p["closed_at"] = time.time()
            if exit_price is not None:
                p["exit_price"] = exit_price
                p["realized_pnl"] = round(
                    (exit_price - p["entry_price"]) * p["size"], 4
                )
            _save_positions(positions)
            logger.info(
                f"Closed position {p['id']} at {exit_price}"
            )
            return True
    return False


def get_trade_history() -> list[dict]:
    """Get all positions (open and closed) for reporting."""
    return _load_positions()


def get_pnl_summary() -> dict:
    """
    Compute portfolio-level P&L summary.

    Returns realized P&L (from closed positions), count of open/closed,
    and per-day breakdown.
    """
    positions = _load_positions()
    open_pos = [p for p in positions if not p.get("closed")]
    closed_pos = [p for p in positions if p.get("closed")]

    realized_pnl = sum(p.get("realized_pnl", 0) for p in closed_pos)
    total_invested = sum(p["size"] * p["entry_price"] for p in closed_pos)
    total_open_cost = sum(p["size"] * p["entry_price"] for p in open_pos)

    winning = [p for p in closed_pos if p.get("realized_pnl", 0) > 0]
    losing = [p for p in closed_pos if p.get("realized_pnl", 0) < 0]

    daily: dict[str, float] = {}
    for p in closed_pos:
        if p.get("closed_at"):
            from datetime import datetime, timezone
            day = datetime.fromtimestamp(p["closed_at"], tz=timezone.utc).strftime("%Y-%m-%d")
            daily[day] = daily.get(day, 0) + p.get("realized_pnl", 0)

    return {
        "total_trades": len(positions),
        "open": len(open_pos),
        "closed": len(closed_pos),
        "winning": len(winning),
        "losing": len(losing),
        "win_rate": (len(winning) / len(closed_pos) * 100) if closed_pos else 0,
        "realized_pnl": round(realized_pnl, 4),
        "total_invested": round(total_invested, 2),
        "open_exposure": round(total_open_cost, 2),
        "daily_pnl": {k: round(v, 4) for k, v in sorted(daily.items())},
    }


def export_to_csv(filepath: str = "trade_history.csv") -> str:
    """Export all positions to CSV for reporting/taxes."""
    import csv
    from pathlib import Path

    positions = _load_positions()
    output = Path(filepath)

    fieldnames = [
        "id", "condition_id", "side", "size", "entry_price",
        "exit_price", "realized_pnl", "opened_at", "closed_at",
        "closed", "sync_note",
    ]

    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for p in positions:
            row = {k: p.get(k, "") for k in fieldnames}
            if row.get("opened_at"):
                from datetime import datetime, timezone
                row["opened_at"] = datetime.fromtimestamp(
                    float(row["opened_at"]), tz=timezone.utc
                ).isoformat()
            if row.get("closed_at") and row["closed_at"]:
                from datetime import datetime, timezone
                row["closed_at"] = datetime.fromtimestamp(
                    float(row["closed_at"]), tz=timezone.utc
                ).isoformat()
            writer.writerow(row)

    logger.info(f"Exported {len(positions)} positions to {output}")
    return str(output)


# ── On-Chain Sync ────────────────────────────────────────────────────

# ERC-1155 balanceOf ABI (Conditional Tokens is ERC-1155)
_CTF_BALANCE_ABI = [
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_id", "type": "uint256"},
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    }
]


def _token_id_to_uint256(token_id: str) -> int:
    """Convert a hex token ID to uint256 for ERC-1155 balanceOf."""
    tid = token_id.strip()
    if tid.startswith("0x"):
        tid = tid[2:]
    return int(tid, 16)


def get_onchain_balance(token_id: str) -> float:
    """Query CTF contract for actual token balance of a specific outcome."""
    from modules.wallet import _get_web3, _get_account, CTF_CONTRACT

    w3 = _get_web3()
    account = _get_account(w3)
    ctf = w3.eth.contract(address=CTF_CONTRACT, abi=_CTF_BALANCE_ABI)

    try:
        token_uint = _token_id_to_uint256(token_id)
        raw = ctf.functions.balanceOf(account.address, token_uint).call()
        return raw / 1e6
    except Exception as e:
        logger.error(f"On-chain balance query failed for {token_id}: {e}")
        return 0.0


async def sync_positions_with_chain() -> dict:
    """
    Reconcile local position tracker with on-chain CTF balances.

    Returns a summary of discrepancies found and corrections made.
    """
    positions = _load_positions()
    open_positions = [p for p in positions if not p.get("closed")]

    discrepancies = []
    synced = 0

    for pos in open_positions:
        market = await get_market_detail(pos["condition_id"])
        if not market:
            continue

        token_id = (
            market.get("yes_token_id")
            if pos["side"] == "YES"
            else market.get("no_token_id")
        )
        if not token_id:
            continue

        onchain_balance = get_onchain_balance(token_id)
        local_size = pos["size"]

        if abs(onchain_balance - local_size) > 0.01:
            discrepancies.append({
                "position_id": pos["id"],
                "condition_id": pos["condition_id"],
                "side": pos["side"],
                "local_size": local_size,
                "onchain_balance": onchain_balance,
                "diff": round(onchain_balance - local_size, 4),
            })

            if onchain_balance == 0:
                pos["closed"] = True
                pos["closed_at"] = time.time()
                pos["sync_note"] = "closed_by_chain_sync"
                logger.info(
                    f"Position {pos['id']} has 0 on-chain balance — marking closed"
                )
            else:
                pos["size"] = onchain_balance
                pos["sync_note"] = "size_adjusted_by_chain_sync"
                logger.info(
                    f"Position {pos['id']} adjusted: "
                    f"{local_size} → {onchain_balance}"
                )
            synced += 1

    if synced > 0:
        _save_positions(positions)

    result = {
        "positions_checked": len(open_positions),
        "discrepancies": len(discrepancies),
        "synced": synced,
        "details": discrepancies,
    }
    logger.info(
        f"Chain sync: checked={len(open_positions)}, "
        f"discrepancies={len(discrepancies)}, synced={synced}"
    )
    return result
