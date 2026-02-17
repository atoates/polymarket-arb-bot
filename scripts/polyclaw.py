#!/usr/bin/env python3
"""
VT Trades — Polymarket CLI

Usage:
  polyclaw markets trending [--limit N] [--json]
  polyclaw markets search <query> [--limit N] [--json]
  polyclaw markets detail <condition_id> [--json]
  polyclaw wallet status
  polyclaw wallet approve
  polyclaw buy <condition_id> <side> <amount> [--skip-sell] [--dry-run]
  polyclaw positions [--json]
  polyclaw scan [--limit N] [--query Q] [--json]
  polyclaw hedge scan [--limit N] [--query Q] [--model M]
  polyclaw hedge analyze <id_a> <id_b> [--model M]
"""
import sys
import os
import asyncio
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def run_async(coro):
    """Run an async coroutine from sync click commands."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Markets ─────────────────────────────────────────────────────────

@click.group()
def cli():
    """VT Trades — Polymarket Trading Bot"""
    pass


@cli.group()
def markets():
    """Browse and search Polymarket markets."""
    pass


@markets.command("trending")
@click.option("--limit", default=20, help="Number of markets to fetch")
@click.option("--json-output", "--json", is_flag=True, help="Output as JSON")
def markets_trending(limit, json_output):
    """Show trending markets by 24h volume."""
    from modules.markets import fetch_trending

    results = run_async(fetch_trending(limit=limit))

    if json_output:
        click.echo(json.dumps(results, indent=2))
        return

    table = Table(title="Trending Markets", show_lines=True)
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Question", style="bold", max_width=50)
    table.add_column("YES", justify="right", style="green")
    table.add_column("NO", justify="right", style="red")
    table.add_column("Volume 24h", justify="right")
    table.add_column("Liquidity", justify="right")

    for m in results:
        table.add_row(
            m["condition_id"][:12] + "...",
            m["question"][:50],
            f"${m['yes_price']:.2f}" if m["yes_price"] else "—",
            f"${m['no_price']:.2f}" if m["no_price"] else "—",
            f"${m['volume_24h']:,.0f}",
            f"${m['liquidity']:,.0f}",
        )

    console.print(table)


@markets.command("search")
@click.argument("query")
@click.option("--limit", default=20, help="Number of results")
@click.option("--json-output", "--json", is_flag=True)
def markets_search(query, limit, json_output):
    """Search markets by keyword."""
    from modules.markets import search_markets

    results = run_async(search_markets(query, limit=limit))

    if json_output:
        click.echo(json.dumps(results, indent=2))
        return

    table = Table(title=f"Search: '{query}'", show_lines=True)
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Question", style="bold", max_width=50)
    table.add_column("YES", justify="right", style="green")
    table.add_column("NO", justify="right", style="red")

    for m in results:
        table.add_row(
            m["condition_id"][:12] + "...",
            m["question"][:50],
            f"${m['yes_price']:.2f}" if m["yes_price"] else "—",
            f"${m['no_price']:.2f}" if m["no_price"] else "—",
        )

    console.print(table)


@markets.command("detail")
@click.argument("condition_id")
@click.option("--json-output", "--json", is_flag=True)
def markets_detail(condition_id, json_output):
    """Get detailed info for a market."""
    from modules.markets import get_market_detail

    market = run_async(get_market_detail(condition_id))

    if not market:
        console.print("[red]Market not found[/red]")
        return

    if json_output:
        click.echo(json.dumps(market, indent=2))
        return

    yes_str = f"${market['yes_price']:.2f}" if market.get('yes_price') is not None else "N/A"
    no_str = f"${market['no_price']:.2f}" if market.get('no_price') is not None else "N/A"

    console.print(Panel(
        f"[bold]{market['question']}[/bold]\n\n"
        f"Condition ID: {market['condition_id']}\n"
        f"YES: [green]{yes_str}[/green]  "
        f"NO: [red]{no_str}[/red]\n"
        f"Volume 24h: ${market.get('volume_24h', 0):,.0f}\n"
        f"Liquidity: ${market.get('liquidity', 0):,.0f}\n"
        f"Category: {market.get('category', 'N/A')}\n"
        f"End date: {market.get('end_date', 'N/A')}",
        title="Market Detail",
    ))


# ── Wallet ──────────────────────────────────────────────────────────

@cli.group()
def wallet():
    """Manage wallet and contract approvals."""
    pass


@wallet.command("status")
def wallet_status():
    """Show wallet address, POL balance, and USDC.e balance."""
    from modules.wallet import get_wallet_status

    status = get_wallet_status()
    console.print(Panel(
        f"Address: [bold]{status['address']}[/bold]\n"
        f"POL:     {status['pol_balance']:.4f}\n"
        f"USDC.e:  [green]${status['usdc_balance']:.2f}[/green]",
        title="Wallet Status",
    ))


@wallet.command("approve")
def wallet_approve():
    """Set contract approvals for Polymarket (one-time)."""
    from modules.wallet import approve_contracts

    console.print("[yellow]Submitting approval transactions...[/yellow]")
    results = approve_contracts()
    for r in results:
        status_color = "green" if r["status"] in ("approved", "already_approved") else "red"
        tx_info = f" (tx: {r['tx']})" if r.get("tx") else ""
        console.print(f"  [{status_color}]{r['label']}: {r['status']}[/{status_color}]{tx_info}")


# ── Trading ─────────────────────────────────────────────────────────

@cli.command("buy")
@click.argument("condition_id")
@click.argument("side", type=click.Choice(["YES", "NO", "yes", "no"]))
@click.argument("amount", type=float)
@click.option("--skip-sell", is_flag=True, help="Skip selling unwanted side on CLOB")
@click.option("--dry-run", is_flag=True, help="Log only, don't execute")
def buy_cmd(condition_id, side, amount, skip_sell, dry_run):
    """Buy a position via split + CLOB strategy."""
    from modules.markets import get_market_detail
    from modules.trading import buy
    from config import DRY_RUN

    market = run_async(get_market_detail(condition_id))
    if not market:
        console.print("[red]Market not found[/red]")
        return

    side = side.upper()
    current_price = market["yes_price"] if side == "YES" else market["no_price"]

    if current_price is None:
        console.print("[red]No price data available[/red]")
        return

    console.print(
        f"Buying [bold]{side}[/bold] on: {market['question']}\n"
        f"Current price: ${current_price:.2f} | Amount: ${amount:.2f}"
    )

    effective_dry_run = dry_run or DRY_RUN
    result = buy(
        condition_id=condition_id,
        side=side,
        amount_usdc=amount,
        current_price=current_price,
        skip_sell=skip_sell,
        dry_run=effective_dry_run,
    )

    if result["status"] == "dry_run":
        console.print("[yellow]DRY RUN — no trade executed[/yellow]")
    elif result["status"] == "executed":
        console.print(
            f"[green]Trade executed![/green]\n"
            f"  Entry price: ${result['entry_price']:.4f}\n"
            f"  Net cost:    ${result['net_cost']:.2f}\n"
            f"  Recovered:   ${result['recovered']:.2f}\n"
            f"  Split TX:    {result['split_tx']}"
        )
    else:
        console.print(f"[red]Trade failed: {result['status']}[/red]")


# ── Positions ───────────────────────────────────────────────────────

@cli.command("positions")
@click.option("--json-output", "--json", is_flag=True)
def positions_cmd(json_output):
    """Show all open positions with P&L."""
    from modules.positions import get_positions_with_pnl

    positions = run_async(get_positions_with_pnl())

    if json_output:
        click.echo(json.dumps(positions, indent=2, default=str))
        return

    if not positions:
        console.print("[dim]No open positions[/dim]")
        return

    table = Table(title="Open Positions", show_lines=True)
    table.add_column("Market", max_width=40)
    table.add_column("Side", justify="center")
    table.add_column("Size", justify="right")
    table.add_column("Entry", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("P&L ($)", justify="right")
    table.add_column("P&L (%)", justify="right")

    for p in positions:
        pnl_style = "green" if (p.get("pnl_usd") or 0) >= 0 else "red"
        table.add_row(
            p.get("market_question", p["condition_id"])[:40],
            p["side"],
            f"${p['size']:.2f}",
            f"${p['entry_price']:.4f}",
            f"${p['current_price']:.4f}" if p.get("current_price") else "—",
            f"[{pnl_style}]${p['pnl_usd']:+.2f}[/{pnl_style}]" if p.get("pnl_usd") is not None else "—",
            f"[{pnl_style}]{p['pnl_pct']:+.1f}%[/{pnl_style}]" if p.get("pnl_pct") is not None else "—",
        )

    console.print(table)


# ── Scanner ─────────────────────────────────────────────────────────

@cli.command("scan")
@click.option("--limit", default=50, help="Number of markets to scan")
@click.option("--query", default=None, help="Filter by search query")
@click.option("--json-output", "--json", is_flag=True)
def scan_cmd(limit, query, json_output):
    """Scan for pair-cost arbitrage opportunities."""
    from modules.scanner import scan_for_arbitrage, scan_with_query

    if query:
        opps = run_async(scan_with_query(query, limit=limit))
    else:
        opps = run_async(scan_for_arbitrage(limit=limit))

    if json_output:
        click.echo(json.dumps(opps, indent=2))
        return

    if not opps:
        console.print("[dim]No arbitrage opportunities found[/dim]")
        return

    table = Table(title="Arbitrage Opportunities", show_lines=True)
    table.add_column("Market", max_width=40)
    table.add_column("YES", justify="right", style="green")
    table.add_column("NO", justify="right", style="red")
    table.add_column("Total Cost", justify="right")
    table.add_column("Net Profit", justify="right", style="bold green")
    table.add_column("Profit %", justify="right", style="bold green")

    for o in opps:
        table.add_row(
            o["market_question"][:40],
            f"${o['yes_price']:.3f}",
            f"${o['no_price']:.3f}",
            f"${o['total_cost']:.4f}",
            f"${o['net_profit']:.4f}",
            f"{o['net_profit_pct']:.2%}",
        )

    console.print(table)


# ── Hedge ───────────────────────────────────────────────────────────

@cli.group()
def hedge():
    """Discover hedging opportunities via LLM analysis."""
    pass


@hedge.command("scan")
@click.option("--limit", default=10, help="Max pairs to check")
@click.option("--query", default=None, help="Filter markets by query")
@click.option("--model", default=None, help="LLM model override")
def hedge_scan(limit, query, model):
    """Scan for hedging opportunities across markets."""
    from modules.hedge import scan_for_hedges

    console.print("[yellow]Scanning for hedges (this may take a few minutes)...[/yellow]")
    hedges = run_async(scan_for_hedges(query=query, limit=limit, model=model))

    if not hedges:
        console.print("[dim]No hedging opportunities found[/dim]")
        return

    for h in hedges:
        tier = h.get("tier_label", "UNKNOWN")
        tier_color = {"HIGH": "green", "GOOD": "cyan", "MODERATE": "yellow", "LOW": "red"}.get(tier, "white")
        console.print(Panel(
            f"[{tier_color}]Tier: {tier}[/{tier_color}]\n"
            f"A: {h['market_a']['question']}\n"
            f"B: {h['market_b']['question']}\n"
            f"Relationship: {h.get('relationship', 'N/A')}",
            title=f"Hedge [{tier}]",
        ))


@hedge.command("analyze")
@click.argument("id_a")
@click.argument("id_b")
@click.option("--model", default=None, help="LLM model override")
def hedge_analyze(id_a, id_b, model):
    """Analyze two specific markets for hedging relationship."""
    from modules.markets import get_market_detail
    from modules.hedge import analyze_pair

    market_a = run_async(get_market_detail(id_a))
    market_b = run_async(get_market_detail(id_b))

    if not market_a or not market_b:
        console.print("[red]One or both markets not found[/red]")
        return

    console.print("[yellow]Analyzing pair...[/yellow]")
    result = run_async(analyze_pair(market_a, market_b, model=model))

    click.echo(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli()
