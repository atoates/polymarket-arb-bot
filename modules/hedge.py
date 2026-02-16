"""
Hedge module — discover hedging opportunities via LLM analysis.

Uses OpenRouter to analyze market pairs for logical implications.
If market A implies market B, then positions on opposite sides
form a covering portfolio (hedge).

Coverage tiers:
  Tier 1 (HIGH):     95%+ — near-arbitrage
  Tier 2 (GOOD):     90-95% — strong hedges
  Tier 3 (MODERATE): 85-90% — decent but noticeable risk
  Tier 4 (LOW):      <85% — speculative (filtered by default)
"""
import os
import json
import httpx
from modules.markets import fetch_trending, search_markets
from utils.logger import get_logger

logger = get_logger("hedge")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-nano-9b-v2:free"

ANALYSIS_PROMPT = """Analyze these two prediction markets for logical hedging relationships.

Market A: {question_a} (YES: ${price_a_yes:.2f}, NO: ${price_a_no:.2f})
Market B: {question_b} (YES: ${price_b_yes:.2f}, NO: ${price_b_no:.2f})

Determine if there is a logical implication between these markets.
For example, if "X wins election" implies "Y loses election", then:
  - YES on A + NO on B forms a covering portfolio
  - The contrapositive: NO on A + YES on B is also a hedge

Respond in JSON format:
{{
  "has_relationship": true/false,
  "relationship": "description of the logical link",
  "hedge_pairs": [
    {{
      "a_side": "YES/NO",
      "b_side": "YES/NO",
      "coverage_pct": 0-100,
      "reasoning": "why this combination hedges"
    }}
  ],
  "combined_cost": total cost of the hedge,
  "tier": 1-4
}}
"""


def _get_coverage_tier(pct: float) -> int:
    if pct >= 95:
        return 1
    elif pct >= 90:
        return 2
    elif pct >= 85:
        return 3
    return 4


def _tier_label(tier: int) -> str:
    return {1: "HIGH", 2: "GOOD", 3: "MODERATE", 4: "LOW"}.get(tier, "UNKNOWN")


async def analyze_pair(market_a: dict, market_b: dict, model: str | None = None) -> dict:
    """Analyze two markets for hedging relationship using LLM."""
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY not set")

    model = model or DEFAULT_MODEL

    prompt = ANALYSIS_PROMPT.format(
        question_a=market_a["question"],
        price_a_yes=market_a.get("yes_price", 0) or 0,
        price_a_no=market_a.get("no_price", 0) or 0,
        question_b=market_b["question"],
        price_b_yes=market_b.get("yes_price", 0) or 0,
        price_b_no=market_b.get("no_price", 0) or 0,
    )

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]

    try:
        # Extract JSON from response
        start = content.index("{")
        end = content.rindex("}") + 1
        result = json.loads(content[start:end])
    except (ValueError, json.JSONDecodeError):
        result = {"has_relationship": False, "error": "Failed to parse LLM response"}

    result["market_a"] = {
        "condition_id": market_a["condition_id"],
        "question": market_a["question"],
    }
    result["market_b"] = {
        "condition_id": market_b["condition_id"],
        "question": market_b["question"],
    }
    result["model_used"] = model

    return result


async def scan_for_hedges(
    query: str | None = None,
    limit: int = 10,
    min_tier: int = 3,
    model: str | None = None,
) -> list[dict]:
    """Scan markets for hedging opportunities."""
    if query:
        markets = await search_markets(query, limit=limit * 2)
    else:
        markets = await fetch_trending(limit=limit * 2)

    if len(markets) < 2:
        logger.info("Not enough markets to scan for hedges")
        return []

    hedges = []
    pairs_checked = 0

    # Check pairs (limit total pairs to avoid excessive API calls)
    max_pairs = min(limit * 3, len(markets) * (len(markets) - 1) // 2)

    for i in range(len(markets)):
        for j in range(i + 1, len(markets)):
            if pairs_checked >= max_pairs:
                break

            pairs_checked += 1
            try:
                result = await analyze_pair(markets[i], markets[j], model=model)
                if result.get("has_relationship"):
                    tier = result.get("tier", 4)
                    if tier <= min_tier:
                        result["tier_label"] = _tier_label(tier)
                        hedges.append(result)
                        logger.info(
                            f"Hedge found [{_tier_label(tier)}]: "
                            f"{markets[i]['question'][:50]} <-> {markets[j]['question'][:50]}"
                        )
            except Exception as e:
                logger.warning(f"Pair analysis failed: {e}")

        if pairs_checked >= max_pairs:
            break

    hedges.sort(key=lambda x: x.get("tier", 4))
    logger.info(f"Hedge scan complete: {len(hedges)} hedges from {pairs_checked} pairs")
    return hedges
