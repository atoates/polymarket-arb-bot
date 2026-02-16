# VT Trades — Polymarket Trading Skill

A Polymarket prediction market trading skill for OpenClaw. Browse markets, execute trades via split + CLOB strategy, track positions with P&L, and discover hedging opportunities through LLM analysis.

## Setup

### Prerequisites
- Python 3.11+ with `uv` package manager
- Polygon RPC node (Chainstack recommended)
- Wallet with USDC.e on Polygon
- OpenRouter API key (for hedge discovery)

### Install
```bash
cd /path/to/polymarket-arb-bot
uv sync
cp .env.example .env
# Edit .env with your credentials
```

### First-time wallet approval
```bash
uv run python scripts/polyclaw.py wallet approve
```

## Commands

### Browse Markets
```bash
uv run python scripts/polyclaw.py markets trending
uv run python scripts/polyclaw.py markets search "election"
uv run python scripts/polyclaw.py markets detail <condition_id>
```

### Check Wallet
```bash
uv run python scripts/polyclaw.py wallet status
```

### Trade
```bash
uv run python scripts/polyclaw.py buy <condition_id> YES 50
uv run python scripts/polyclaw.py buy <condition_id> NO 25
```

### Positions
```bash
uv run python scripts/polyclaw.py positions
```

### Arbitrage Scanner
```bash
uv run python scripts/polyclaw.py scan
```

### Hedge Discovery
```bash
uv run python scripts/polyclaw.py hedge scan --limit 10
uv run python scripts/polyclaw.py hedge analyze <condition_id_1> <condition_id_2>
```

## Natural Language Prompts

When connected to OpenClaw, use these prompts:

- "What's trending on Polymarket?"
- "Buy $50 YES on market <id>"
- "Show my positions"
- "Find hedging opportunities"
- "Scan for arbitrage"
- "What's my wallet balance?"

## Configuration

| Variable | Required | Description |
|---|---|---|
| `CHAINSTACK_NODE` | Yes (trading) | Polygon RPC URL |
| `POLYCLAW_PRIVATE_KEY` | Yes (trading) | EVM private key (hex) |
| `POLYMARKET_API_KEY` | Yes (trading) | CLOB API key |
| `POLYMARKET_API_SECRET` | Yes (trading) | CLOB API secret |
| `POLYMARKET_PASSPHRASE` | Yes (trading) | CLOB passphrase |
| `OPENROUTER_API_KEY` | Yes (hedge) | OpenRouter API key |
| `HTTPS_PROXY` | Recommended | Residential proxy for CLOB |
| `WEBHOOK_URL` | No | Discord/Slack notification webhook |
| `DRY_RUN` | No | Set `true` to log without trading (default: true) |
