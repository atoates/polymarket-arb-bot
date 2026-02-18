"""
Markets module — browse and search Polymarket prediction markets.

Uses the Gamma API for market metadata and the CLOB API for orderbook data.

Key distinction:
  - condition_id: identifies the market condition (used for CTF contract splits)
  - clob_token_id: identifies a specific outcome token on the CLOB (used for orders)
  Each binary market has TWO clob_token_ids: one for YES, one for NO.
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

    results = [_normalize_market(m) for m in markets]
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
        markets = await _search_by_question(query, limit)

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


async def get_market_detail(market_id: str) -> dict | None:
    """
    Get full details for a single market by condition ID or numeric Gamma ID.

    Supports:
      - Hex condition_id (e.g. "0x5e5c9dfaf...")
      - Numeric Gamma market ID (e.g. "1198423")
      - Slug (e.g. "will-bitcoin-hit-100k")

    Filters to active, non-closed markets to avoid matching old/expired ones.
    """
    market_id = market_id.strip()

    # Determine lookup strategy
    is_numeric = market_id.isdigit()
    is_slug = not is_numeric and not market_id.startswith("0x") and len(market_id) < 40

    if is_numeric:
        # Look up by Gamma numeric ID
        markets = await _lookup_by_gamma_id(market_id)
    elif is_slug:
        # Try slug lookup first
        result = await get_market_by_slug(market_id)
        if result:
            return result
        markets = []
    else:
        # Condition ID lookup (hex)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GAMMA_API}/markets",
                params={
                    "condition_id": market_id,
                    "active": True,
                    "closed": False,
                },
            )
            resp.raise_for_status()
            markets = resp.json()

    if not markets:
        # Retry without active filter
        async with httpx.AsyncClient(timeout=15) as client:
            params = {}
            if is_numeric:
                params["id"] = market_id
            else:
                params["condition_id"] = market_id
            resp = await client.get(f"{GAMMA_API}/markets", params=params)
            resp.raise_for_status()
            markets = resp.json()

    if not markets:
        return None

    market = _normalize_market(markets[0])

    # Enrich with orderbook data using the YES CLOB token ID
    yes_token_id = market.get("yes_token_id")
    if yes_token_id:
        try:
            book = await get_orderbook(yes_token_id)
            market["orderbook"] = book

            # Update prices from live CLOB data if available
            if book.get("market"):
                clob_tokens = book["market"].get("tokens", [])
                for ct in clob_tokens:
                    if ct.get("outcome") == "Yes":
                        market["yes_price"] = float(ct.get("price", 0))
                    elif ct.get("outcome") == "No":
                        market["no_price"] = float(ct.get("price", 0))
        except Exception as e:
            logger.warning(f"Could not fetch orderbook: {e}")

    return market


async def _lookup_by_gamma_id(gamma_id: str) -> list[dict]:
    """Look up a market by its numeric Gamma API ID."""
    async with httpx.AsyncClient(timeout=15) as client:
        # Try the direct /markets/{id} endpoint first
        resp = await client.get(f"{GAMMA_API}/markets/{gamma_id}")
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return [data] if isinstance(data, dict) else data

        # Fallback: query by id parameter
        resp = await client.get(
            f"{GAMMA_API}/markets",
            params={"id": gamma_id},
        )
        resp.raise_for_status()
        return resp.json()


async def get_market_by_slug(slug: str) -> dict | None:
    """Get market by its URL slug (e.g. 'will-bitcoin-hit-100k')."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{GAMMA_API}/markets/{slug}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()

    if not data:
        return None

    return _normalize_market(data)


async def get_orderbook(token_id: str) -> dict:
    """
    Fetch CLOB orderbook for a token.

    Args:
        token_id: The CLOB token ID (long integer string), NOT the condition_id.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{CLOB_API}/book",
            params={"token_id": token_id},
        )
        resp.raise_for_status()
        return resp.json()


async def get_clob_market(token_id: str) -> dict | None:
    """Fetch market info directly from the CLOB by token ID."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{CLOB_API}/markets/{token_id}",
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


def _normalize_market(raw: dict) -> dict:
    """
    Extract key fields from a raw Gamma API market response.

    Handles multiple price sources:
      1. tokens[].price — from the tokens array
      2. outcomePrices — JSON string like "[0.185, 0.815]"
      3. bestBid/bestAsk — from CLOB data if available
    """
    tokens = raw.get("tokens", [])

    # Extract CLOB token IDs and prices from tokens array
    yes_price = None
    no_price = None
    yes_token_id = None
    no_token_id = None

    for t in tokens:
        outcome = t.get("outcome", "").upper()
        token_id = t.get("token_id", "")
        price = t.get("price")

        if outcome == "YES":
            yes_token_id = token_id
            if price is not None:
                yes_price = float(price)
        elif outcome == "NO":
            no_token_id = token_id
            if price is not None:
                no_price = float(price)

    # Fallback: use outcomePrices field if tokens didn't have prices
    if yes_price is None or no_price is None:
        outcome_prices = raw.get("outcomePrices")
        if outcome_prices:
            try:
                if isinstance(outcome_prices, str):
                    import json
                    prices = json.loads(outcome_prices)
                else:
                    prices = outcome_prices
                if isinstance(prices, list) and len(prices) >= 2:
                    if yes_price is None:
                        yes_price = float(prices[0]) if prices[0] else None
                    if no_price is None:
                        no_price = float(prices[1]) if prices[1] else None
            except (ValueError, IndexError):
                pass

    # Also extract clobTokenIds if tokens array didn't have them
    if not yes_token_id or not no_token_id:
        clob_ids = raw.get("clobTokenIds")
        if clob_ids:
            try:
                if isinstance(clob_ids, str):
                    import json
                    clob_ids = json.loads(clob_ids)
                if isinstance(clob_ids, list) and len(clob_ids) >= 2:
                    if not yes_token_id:
                        yes_token_id = str(clob_ids[0])
                    if not no_token_id:
                        no_token_id = str(clob_ids[1])
            except (ValueError, IndexError):
                pass

    return {
        "id": raw.get("id", ""),  # Numeric Gamma market ID
        "condition_id": raw.get("conditionId", raw.get("condition_id", "")),
        "question": raw.get("question", ""),
        "description": raw.get("description", ""),
        "market_slug": raw.get("slug", raw.get("market_slug", "")),
        "yes_price": yes_price,
        "no_price": no_price,
        "yes_token_id": yes_token_id,
        "no_token_id": no_token_id,
        "volume_24h": float(raw.get("volume24hr", 0) or 0),
        "liquidity": float(raw.get("liquidityNum", 0) or 0),
        "end_date": raw.get("endDate", ""),
        "category": raw.get("category", ""),
        "tokens": tokens,
        "active": raw.get("active", True),
        "closed": raw.get("closed", False),
    }
