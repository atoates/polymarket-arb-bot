# VT Trades — Polymarket Arbitrage Bot

An OpenClaw skill for automated prediction market trading on [Polymarket](https://polymarket.com/). Scans for arbitrage, executes via split + CLOB strategy, tracks positions with P&L, and discovers hedge opportunities through LLM analysis.

**OpenClaw instance:** [vttrades.up.railway.app](https://vttrades.up.railway.app)

## Quick Start

```bash
# Clone
git clone https://github.com/<your-username>/polymarket-arb-bot.git
cd polymarket-arb-bot

# Install (using uv)
uv sync
# Or with pip
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your credentials

# One-time: approve Polymarket contracts
python scripts/polyclaw.py wallet approve

# Browse markets
python scripts/polyclaw.py markets trending

# Scan for arbitrage
python scripts/polyclaw.py scan

# Buy a position
python scripts/polyclaw.py buy <condition_id> YES 50
```

## Architecture

```
polymarket-arb-bot/
├── config.py              # Environment-driven configuration
├── SKILL.md               # OpenClaw skill manifest
├── scripts/
│   └── polyclaw.py        # CLI entry point
├── modules/
│   ├── markets.py         # Browse & search Polymarket markets
│   ├── wallet.py          # Wallet status & contract approvals
│   ├── trading.py         # Split + CLOB execution strategy
│   ├── positions.py       # Position tracking with P&L
│   ├── scanner.py         # Pair-cost arbitrage detection
│   └── hedge.py           # LLM-powered hedge discovery
├── strategies/            # Custom strategy implementations
├── utils/
│   ├── logger.py          # JSON structured logging
│   └── notifier.py        # Discord/Slack notifications
└── tests/
```

## Commands

| Command | Description |
|---|---|
| `markets trending` | Top markets by 24h volume |
| `markets search <query>` | Search by keyword |
| `markets detail <id>` | Full market details |
| `wallet status` | Address, POL, USDC.e balances |
| `wallet approve` | One-time contract approvals |
| `buy <id> YES/NO <amount>` | Buy via split + CLOB |
| `positions` | Open positions with P&L |
| `scan` | Pair-cost arbitrage scanner |
| `hedge scan` | LLM hedge discovery |
| `hedge analyze <id_a> <id_b>` | Analyze two markets for hedging |

## Trading Strategy

**Pair-cost arbitrage:** In a binary market, YES + NO pays $1. When the combined ask price is < $1 (after fees), buying both sides guarantees profit.

**Split + CLOB execution:**
1. Split USDC.e → YES + NO tokens via CTF contract
2. Sell the unwanted side on the CLOB order book
3. Net result: desired position at reduced cost

## OpenClaw Integration

This repo is structured as an OpenClaw skill. To link it to your instance:

1. Install the skill in your OpenClaw instance at `~/.openclaw/skills/` or workspace `/skills/`
2. The `SKILL.md` file provides the skill manifest with commands and prompts
3. Configure your OpenClaw instance to point to this repository

## Environment Variables

See [`.env.example`](.env.example) for all configuration options.

**Required for trading:**
- `CHAINSTACK_NODE` — Polygon RPC URL
- `POLYCLAW_PRIVATE_KEY` — Wallet private key
- `POLYMARKET_API_KEY` / `API_SECRET` / `PASSPHRASE` — CLOB credentials

**Required for hedge discovery:**
- `OPENROUTER_API_KEY` — OpenRouter API key

## Safety

- **DRY_RUN=true** by default — logs opportunities without trading
- Circuit breaker: max 20 trades/hour
- Minimum liquidity filter: skips thin markets
- Keep only small amounts in the trading wallet

## License

MIT
