# VT Trades — Polymarket Trading Skill

A Polymarket prediction market trading skill for OpenClaw. Scans for arbitrage, executes trades via split + CLOB strategy, manages limit orders, tracks positions with P&L, runs a continuous trading engine, and discovers hedge opportunities through LLM analysis.

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
# Or: pip install -r requirements.txt
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
uv run python scripts/polyclaw.py markets trending [--limit N] [--json]
uv run python scripts/polyclaw.py markets search "election" [--limit N] [--json]
uv run python scripts/polyclaw.py markets detail <condition_id> [--json]
```

### Wallet
```bash
uv run python scripts/polyclaw.py wallet status
uv run python scripts/polyclaw.py wallet swap <amount> [--slippage N] [--dry-run]
uv run python scripts/polyclaw.py wallet swap-back <amount> [--slippage N] [--dry-run]
uv run python scripts/polyclaw.py wallet approve
```

### Buy a Position
```bash
uv run python scripts/polyclaw.py buy <condition_id> YES 50 [--skip-sell] [--dry-run]
uv run python scripts/polyclaw.py buy <condition_id> NO 25 [--dry-run]
```

### Sell / Exit a Position
```bash
uv run python scripts/polyclaw.py sell <condition_id> YES 50 [--price 0.85] [--order-type GTC] [--dry-run]
uv run python scripts/polyclaw.py sell <condition_id> NO 25 [--price 0.40] [--dry-run]
```

### Limit Orders (Direct CLOB)
```bash
uv run python scripts/polyclaw.py order place <token_id> BUY 100 0.45 [--type GTC|GTD|FOK] [--post-only]
uv run python scripts/polyclaw.py order place <token_id> SELL 50 0.80 --post-only
uv run python scripts/polyclaw.py order list
uv run python scripts/polyclaw.py order cancel <order_id>
uv run python scripts/polyclaw.py order cancel-all
```
Use `--post-only` for maker orders (0% fee instead of 0.1% taker fee).

### Positions & P&L
```bash
uv run python scripts/polyclaw.py positions [--json]
uv run python scripts/polyclaw.py pnl [--json]
uv run python scripts/polyclaw.py export [--output trade_history.csv]
uv run python scripts/polyclaw.py sync
```

### Arbitrage Scanner
```bash
uv run python scripts/polyclaw.py scan [--limit 50] [--query Q] [--json]
uv run python scripts/polyclaw.py scan --auto [--dry-run]
uv run python scripts/polyclaw.py scan --continuous --auto --interval 10 [--dry-run]
```
- `--auto` executes the top 3 opportunities found
- `--continuous` runs in a loop at the given interval
- `--dry-run` logs trades but doesn't execute (DRY_RUN env also controls this)

### Risk Management
```bash
uv run python scripts/polyclaw.py risk
```
Shows kill switch status, open positions, total exposure, daily loss, and top market exposures.

### Trading Engine (Daemon Mode)
```bash
uv run python scripts/polyclaw.py run [--strategies arb,endgame] [--interval 10] [--dry-run] [--ws] [--limit 50] [--query Q]
```
- `--strategies` comma-separated: `arb` (pair-cost arbitrage), `endgame` (near-resolution)
- `--ws` enables WebSocket real-time price feed
- `--interval` seconds between scan cycles
- Ctrl+C for graceful shutdown

### Hedge Discovery
```bash
uv run python scripts/polyclaw.py hedge scan [--limit 10] [--query Q] [--model M]
uv run python scripts/polyclaw.py hedge analyze <condition_id_1> <condition_id_2> [--model M]
```

## Natural Language Prompts

When connected to OpenClaw, use these prompts:

- "What's trending on Polymarket?"
- "Show my wallet balance"
- "Buy $50 YES on market <id>"
- "Sell 100 YES on market <id> at $0.85"
- "Place a limit buy order for 50 tokens at $0.45 on token <token_id>"
- "List my open orders"
- "Cancel all orders"
- "Show my positions"
- "Show my P&L"
- "Export trade history to CSV"
- "Sync positions with on-chain balances"
- "Scan for arbitrage"
- "Scan for arbitrage and auto-execute"
- "Run continuous scan every 10 seconds with auto-execute"
- "Show risk summary"
- "Start the trading engine with arb strategy"
- "Start the engine with arb and endgame strategies, dry run, with websocket"
- "Find hedging opportunities"
- "Swap $50 USDC to USDC.e"
- "Swap $50 USDC.e back to USDC"

## Trading Strategies

### Pair-Cost Arbitrage (arb)
In a binary market, YES + NO pays $1. When the combined cost is < $1 (after fees), buying both sides guarantees profit.

### Endgame
Markets resolving within 1-72 hours where one side is priced at 95%+ probability. Thin per-trade profit but extremely high annualized returns.

### Combinatorial Arbitrage
Multi-outcome neg_risk markets where N outcomes should sum to $1. When the total cost of buying all YES outcomes is below $1, it's guaranteed profit.

## Risk Limits

| Parameter | Default | Env Variable |
|---|---|---|
| Max drawdown | 20% | `MAX_DRAWDOWN_PCT` |
| Daily loss limit | $50 | `MAX_DAILY_LOSS` |
| Per-trade max | $50 | `MAX_POSITION_SIZE` |
| Max market exposure | $150 | `MAX_MARKET_EXPOSURE` |
| Total exposure cap | $500 | `MAX_TOTAL_EXPOSURE` |
| Max concurrent positions | 10 | `MAX_CONCURRENT_POSITIONS` |
| Max trades/hour | 20 | `MAX_TRADES_PER_HOUR` |

Kill switch activates automatically if daily loss or max drawdown is hit. All trading halts until manually deactivated.

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
| `DRY_RUN` | No | Set `false` to enable live trading (default: true) |
| `MAX_DRAWDOWN_PCT` | No | Kill switch drawdown % (default: 20) |
| `MAX_DAILY_LOSS` | No | Daily loss limit in USD (default: 50) |
| `MAX_POSITION_SIZE` | No | Per-trade max in USD (default: 50) |
| `MAX_TOTAL_EXPOSURE` | No | Portfolio exposure cap in USD (default: 500) |
