"""
Markets module — browse and search Polymarket prediction markets.

Uses the Gamma API for market metadata and the CLOB API for orderbook data.
"""
import httpx
from utils.logger import get_logger

logger = get_logger("markets")

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


async def fetch_trending(limit: int = 20) -> list[dict]:
    """Fetch trending markets sorted by 24h volume."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GAMMA_API}/markets",
            params={
                "limit": limit,
                "active": True,
                "closed": False,
                "order": "volume24hr",
                "ascending": False,
            },
        )
        resp.raise_for_status()
        markets = resp.json()

    results = []
    for m in markets:
        results.append(_normalize_market(m))
    logger.info(f"Fetched {len(results)} trending markets")
    return results


async def search_markets(query: str, limit: int = 20) -> list[dict]:
    """Search markets by keyword."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GAMMA_API}/markets",
            params={
                "limit": limit,
                "active": True,
                "closed": False,
                "tag_label": query,
            },
        )
        resp.raise_for_status()
        markets = resp.json()

    if not markets:
        # Fallback: search in question text
        resp2 = await _search_by_question(query, limit)
        markets = resp2

    results = [_normalize_market(m) for m in markets]
    logger.info(f"Search '{query}' returned {len(results)} markets")
    return results


async def _search_by_question(query: str, limit: int) -> list[dict]:
    """Fallback search by scanning questions."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GAMMA_API}/markets",
            params={"limit": 100, "active": True, "closed": False},
        )
        resp.raise_for_status()
        all_markets = resp.json()

    query_lower = query.lower()
    matched = [
        m for m in all_markets
        if query_lower in m.get("question", "").lower()
    ]
    return matched[:limit]


async def get_market_detail(condition_id: str) -> dict | None:
    """Get full details for a single market by condition ID."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GAMMA_API}/markets",
            params={"condition_id": condition_id},
        )
        resp.raise_for_status()
        markets = resp.json()

    if not markets:
        return None

    market = _normalize_market(markets[0])

    # Enrich with orderbook data
    try:
        book = await get_orderbook(condition_id)
        market["orderbook"] = book
    except Exception as e:
        logger.warning(f"Could not fetch orderbook: {e}")

    return market


async def get_orderbook(condition_id: str) -> dict:
    """Fetch CLOB orderbook for a market."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{CLOB_API}/book",
            params={"token_id": condition_id},
        )
        resp.raise_for_status()
        return resp.json()


def _normalize_market(raw: dict) -> dict:
    """Extract key fields from a raw Gamma API market."""
    tokens = raw.get("tokens", [])
    yes_price = None
    no_price = None
    for t in tokens:
        outcome = t.get("outcome", "").upper()
        if outcome == "YES":
            yes_price = float(t.get("price", 0))
        elif outcome == "NO":
            no_price = float(t.get("price", 0))

    return {
        "condition_id": raw.get("conditionId", raw.get("condition_id", "")),
        "question": raw.get("question", ""),
        "description": raw.get("description", ""),
        "yes_price": yes_price,
        "no_price": no_price,
        "volume_24h": float(raw.get("volume24hr", 0)),
        "liquidity": float(raw.get("liquidityNum", 0)),
        "end_date": raw.get("endDate", ""),
        "category": raw.get("category", ""),
        "tokens": tokens,
        "active": raw.get("active", True),
        "closed": raw.get("closed", False),
    }
