"""
Configuration module — reads all settings from environment variables.
"""
import os
from dotenv import load_dotenv

load_dotenv()


# ── Wallet / RPC ────────────────────────────────────────────────────
CHAINSTACK_NODE = os.getenv("CHAINSTACK_NODE", "")
POLYCLAW_PRIVATE_KEY = os.getenv("POLYCLAW_PRIVATE_KEY", "")

# ── Polymarket CLOB Credentials ─────────────────────────────────────
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET = os.getenv("POLYMARKET_API_SECRET", "")
POLYMARKET_PASSPHRASE = os.getenv("POLYMARKET_PASSPHRASE", "")

# ── API Endpoints ───────────────────────────────────────────────────
CLOB_API_URL = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
GAMMA_API_URL = os.getenv("GAMMA_API_URL", "https://gamma-api.polymarket.com")
CHAIN_ID = int(os.getenv("CHAIN_ID", "137"))  # Polygon mainnet

# ── Trading Parameters ──────────────────────────────────────────────
MIN_PROFIT_THRESHOLD = float(os.getenv("MIN_PROFIT_THRESHOLD", "0.005"))
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "50.0"))
TAKER_FEE_RATE = float(os.getenv("TAKER_FEE_RATE", "0.001"))
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "10"))
MARKET_REFRESH_INTERVAL = int(os.getenv("MARKET_REFRESH_INTERVAL", "300"))

# ── Safety ──────────────────────────────────────────────────────────
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
MAX_TRADES_PER_HOUR = int(os.getenv("MAX_TRADES_PER_HOUR", "20"))
MIN_LIQUIDITY = float(os.getenv("MIN_LIQUIDITY", "100.0"))

# ── Notifications ───────────────────────────────────────────────────
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

# ── Signature Type ──────────────────────────────────────────────────
SIGNATURE_TYPE = int(os.getenv("SIGNATURE_TYPE", "1"))

# ── OpenClaw ────────────────────────────────────────────────────────
OPENCLAW_URL = os.getenv("OPENCLAW_URL", "https://vttrades.up.railway.app")

# ── LLM (Hedge Discovery) ──────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")


def validate_config(require_trading: bool = True) -> bool:
    """Check that required credentials are set."""
    missing = []
    if require_trading:
        if not CHAINSTACK_NODE:
            missing.append("CHAINSTACK_NODE")
        if not POLYCLAW_PRIVATE_KEY:
            missing.append("POLYCLAW_PRIVATE_KEY")
        if not POLYMARKET_API_KEY:
            missing.append("POLYMARKET_API_KEY")
        if not POLYMARKET_API_SECRET:
            missing.append("POLYMARKET_API_SECRET")
        if not POLYMARKET_PASSPHRASE:
            missing.append("POLYMARKET_PASSPHRASE")
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )
    return True
