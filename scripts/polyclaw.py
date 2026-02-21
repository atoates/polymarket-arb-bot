#!/usr/bin/env python3
"""
VT Trades — Polymarket CLI

Usage:
  polyclaw markets trending [--limit N] [--json]
  polyclaw markets search <query> [--limit N] [--json]
  polyclaw markets detail <condition_id> [--json]
  polyclaw wallet status
  polyclaw wallet swap <amount> [--slippage N] [--dry-run]
  polyclaw wallet swap-back <amount> [--slippage N] [--dry-run]
  polyclaw wallet approve
  polyclaw buy <condition_id> <side> <amount> [--skip-sell] [--dry-run]
  polyclaw sell <condition_id> <side> <amount> [--price P] [--order-type GTC|GTD|FOK] [--dry-run]
  polyclaw order place <token_id> <side> <size> <price> [--type GTC|GTD|FOK] [--post-only]
  polyclaw order list
  polyclaw order cancel <order_id>
  polyclaw order cancel-all
  polyclaw positions [--json]
  polyclaw pnl [--json]
  polyclaw export [--output FILE]
  polyclaw sync
  polyclaw scan [--limit N] [--query Q] [--json] [--auto] [--continuous] [--interval N] [--dry-run]
  polyclaw risk
  polyclaw run [--strategies S] [--interval N] [--dry-run] [--ws] [--limit N] [--query Q]
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
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return loop.run_until_complete(coro)
    return asyncio.run(coro)


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
    """Show wallet address, POL balance, USDC, and USDC.e balances."""
    from modules.swap import get_balances

    b = get_balances()
    console.print(Panel(
        f"Address: [bold]{b['address']}[/bold]\n"
        f"POL:     {b['pol_balance']:.4f}\n"
        f"USDC:    [green]${b['usdc_balance']:.2f}[/green]\n"
        f"USDC.e:  [green]${b['usdc_e_balance']:.2f}[/green]",
        title="Wallet Status",
    ))


@wallet.command("swap")
@click.argument("amount", type=float)
@click.option("--slippage", default=10, help="Slippage in basis points (default 10 = 0.1%)")
@click.option("--dry-run", is_flag=True, help="Build tx but don't send")
def wallet_swap(amount, slippage, dry_run):
    """Swap native USDC → USDC.e via Uniswap V3."""
    from modules.swap import swap_usdc_to_usdc_e

    console.print(
        f"Swapping [bold]${amount:.2f} USDC → USDC.e[/bold] "
        f"(slippage: {slippage}bps)"
    )

    result = swap_usdc_to_usdc_e(amount, slippage_bps=slippage, dry_run=dry_run)

    if result["status"] == "dry_run":
        console.print(
            f"[yellow]DRY RUN[/yellow] — would swap ${result['amount_in']:.2f} USDC "
            f"(min out: ${result['min_out']:.2f} USDC.e)"
        )
    elif result["status"] == "success":
        console.print(
            f"[green]Swap complete![/green]\n"
            f"  TX: {result['tx_hash']}\n"
            f"  In:  ${result['amount_in']:.2f} USDC\n"
            f"  Min: ${result['min_out']:.2f} USDC.e"
        )
    else:
        console.print(f"[red]Swap failed: {result['status']}[/red]")


@wallet.command("swap-back")
@click.argument("amount", type=float)
@click.option("--slippage", default=10, help="Slippage in basis points (default 10 = 0.1%)")
@click.option("--dry-run", is_flag=True, help="Build tx but don't send")
def wallet_swap_back(amount, slippage, dry_run):
    """Swap USDC.e → native USDC via Uniswap V3."""
    from modules.swap import swap_usdc_e_to_usdc

    console.print(
        f"Swapping [bold]${amount:.2f} USDC.e → USDC[/bold] "
        f"(slippage: {slippage}bps)"
    )

    result = swap_usdc_e_to_usdc(amount, slippage_bps=slippage, dry_run=dry_run)

    if result["status"] == "dry_run":
        console.print(
            f"[yellow]DRY RUN[/yellow] — would swap ${result['amount_in']:.2f} USDC.e "
            f"(min out: ${result['min_out']:.2f} USDC)"
        )
    elif result["status"] == "success":
        console.print(
            f"[green]Swap complete![/green]\n"
            f"  TX: {result['tx_hash']}\n"
            f"  In:  ${result['amount_in']:.2f} USDC.e\n"
            f"  Min: ${result['min_out']:.2f} USDC"
        )
    else:
        console.print(f"[red]Swap failed: {result['status']}[/red]")


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

    # Use the resolved hex condition_id from market data, NOT the user input
    # (user may have passed a numeric Gamma ID or slug)
    resolved_condition_id = market.get("condition_id", "")
    if not resolved_condition_id:
        console.print("[red]Market has no condition_id — cannot trade[/red]")
        return

    side = side.upper()
    current_price = market["yes_price"] if side == "YES" else market["no_price"]

    if current_price is None:
        console.print("[red]No price data available[/red]")
        return

    console.print(
        f"Buying [bold]{side}[/bold] on: {market['question']}\n"
        f"Condition ID: {resolved_condition_id}\n"
        f"Current price: ${current_price:.2f} | Amount: ${amount:.2f}"
    )

    effective_dry_run = dry_run or DRY_RUN
    result = buy(
        condition_id=resolved_condition_id,
        side=side,
        amount_usdc=amount,
        current_price=current_price,
        yes_token_id=market.get("yes_token_id"),
        no_token_id=market.get("no_token_id"),
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


# ── Sell / Exit ──────────────────────────────────────────────────────

@cli.command("sell")
@click.argument("condition_id")
@click.argument("side", type=click.Choice(["YES", "NO", "yes", "no"]))
@click.argument("amount", type=float)
@click.option("--price", type=float, default=None, help="Limit price (default: current market price)")
@click.option("--order-type", type=click.Choice(["GTC", "GTD", "FOK"]), default="GTC")
@click.option("--dry-run", is_flag=True)
def sell_cmd(condition_id, side, amount, price, order_type, dry_run):
    """Sell (exit) a position on the CLOB."""
    from modules.markets import get_market_detail
    from modules.trading import sell_position
    from config import DRY_RUN

    market = run_async(get_market_detail(condition_id))
    if not market:
        console.print("[red]Market not found[/red]")
        return

    resolved_condition_id = market.get("condition_id", "")
    side = side.upper()

    token_id = market.get("yes_token_id") if side == "YES" else market.get("no_token_id")
    if not token_id:
        console.print(f"[red]No CLOB token ID for {side} side[/red]")
        return

    if price is None:
        price = market.get("yes_price") if side == "YES" else market.get("no_price")
        if price is None:
            console.print("[red]No price data — specify --price manually[/red]")
            return

    console.print(
        f"Selling [bold]{amount:.2f} {side}[/bold] on: {market['question']}\n"
        f"Price: ${price:.4f} | Type: {order_type}"
    )

    effective_dry_run = dry_run or DRY_RUN
    result = sell_position(
        token_id=token_id,
        amount=amount,
        price=price,
        condition_id=resolved_condition_id,
        side=side,
        order_type=order_type,
        dry_run=effective_dry_run,
    )

    if result["status"] == "dry_run":
        console.print("[yellow]DRY RUN — no order placed[/yellow]")
    elif result["status"] == "sold":
        console.print(
            f"[green]Sell order placed![/green]\n"
            f"  Position closed: {result.get('position_closed', False)}"
        )
    else:
        console.print(f"[red]Sell failed: {result['status']}[/red]")


# ── Order Management ────────────────────────────────────────────────

@cli.group()
def order():
    """Manage CLOB orders."""
    pass


@order.command("place")
@click.argument("token_id")
@click.argument("side", type=click.Choice(["BUY", "SELL", "buy", "sell"]))
@click.argument("size", type=float)
@click.argument("price", type=float)
@click.option("--type", "order_type", type=click.Choice(["GTC", "GTD", "FOK"]), default="GTC")
@click.option("--post-only", is_flag=True, help="Maker only — reject if crosses spread")
def order_place(token_id, side, size, price, order_type, post_only):
    """Place a limit order on the CLOB."""
    from modules.trading import place_order

    result = place_order(
        token_id=token_id,
        side=side.upper(),
        size=size,
        price=price,
        order_type=order_type,
        post_only=post_only,
    )
    if result and result["status"] == "placed":
        console.print(f"[green]Order placed![/green] {result.get('response', '')}")
    else:
        console.print(f"[red]Order failed[/red] {result}")


@order.command("list")
def order_list():
    """List open CLOB orders."""
    from modules.trading import get_open_orders

    orders = get_open_orders()
    if not orders:
        console.print("[dim]No open orders[/dim]")
        return

    table = Table(title="Open Orders", show_lines=True)
    table.add_column("Order ID", style="dim", max_width=16)
    table.add_column("Side")
    table.add_column("Size", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Status")

    for o in orders:
        table.add_row(
            str(o.get("id", ""))[:16],
            o.get("side", ""),
            str(o.get("original_size", o.get("size", ""))),
            str(o.get("price", "")),
            o.get("status", ""),
        )
    console.print(table)


@order.command("cancel")
@click.argument("order_id")
def order_cancel(order_id):
    """Cancel an open order."""
    from modules.trading import cancel_order

    result = cancel_order(order_id)
    if result["status"] == "cancelled":
        console.print(f"[green]Cancelled order {order_id}[/green]")
    else:
        console.print(f"[red]Cancel failed: {result.get('error', '')}[/red]")


@order.command("cancel-all")
def order_cancel_all():
    """Cancel all open orders."""
    from modules.trading import cancel_all_orders

    result = cancel_all_orders()
    if result["status"] == "cancelled_all":
        console.print("[green]All orders cancelled[/green]")
    else:
        console.print(f"[red]Cancel all failed: {result.get('error', '')}[/red]")


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


@cli.command("pnl")
@click.option("--json-output", "--json", is_flag=True)
def pnl_cmd(json_output):
    """Show P&L summary with realized/unrealized breakdown."""
    from modules.positions import get_pnl_summary

    summary = get_pnl_summary()

    if json_output:
        click.echo(json.dumps(summary, indent=2))
        return

    pnl_style = "green" if summary["realized_pnl"] >= 0 else "red"
    console.print(Panel(
        f"Total Trades: {summary['total_trades']} "
        f"(Open: {summary['open']}, Closed: {summary['closed']})\n"
        f"Win Rate: {summary['win_rate']:.1f}% "
        f"({summary['winning']}W / {summary['losing']}L)\n"
        f"Realized P&L: [{pnl_style}]${summary['realized_pnl']:+.4f}[/{pnl_style}]\n"
        f"Total Invested: ${summary['total_invested']:.2f}\n"
        f"Open Exposure: ${summary['open_exposure']:.2f}",
        title="P&L Summary",
    ))

    if summary["daily_pnl"]:
        table = Table(title="Daily P&L")
        table.add_column("Date")
        table.add_column("P&L", justify="right")
        for day, pnl in summary["daily_pnl"].items():
            style = "green" if pnl >= 0 else "red"
            table.add_row(day, f"[{style}]${pnl:+.4f}[/{style}]")
        console.print(table)


@cli.command("export")
@click.option("--output", default="trade_history.csv", help="Output CSV file path")
def export_cmd(output):
    """Export trade history to CSV."""
    from modules.positions import export_to_csv

    filepath = export_to_csv(output)
    console.print(f"[green]Exported to {filepath}[/green]")


@cli.command("sync")
def sync_cmd():
    """Sync local positions with on-chain CTF token balances."""
    from modules.positions import sync_positions_with_chain

    console.print("[yellow]Syncing positions with on-chain data...[/yellow]")
    result = run_async(sync_positions_with_chain())

    console.print(
        f"Checked: {result['positions_checked']} positions\n"
        f"Discrepancies: {result['discrepancies']}\n"
        f"Synced: {result['synced']}"
    )

    if result["details"]:
        table = Table(title="Discrepancies", show_lines=True)
        table.add_column("Position", max_width=20)
        table.add_column("Side")
        table.add_column("Local", justify="right")
        table.add_column("On-Chain", justify="right")
        table.add_column("Diff", justify="right")

        for d in result["details"]:
            table.add_row(
                d["position_id"][:20],
                d["side"],
                f"{d['local_size']:.2f}",
                f"{d['onchain_balance']:.2f}",
                f"{d['diff']:+.2f}",
            )
        console.print(table)


# ── Scanner ─────────────────────────────────────────────────────────

@cli.command("scan")
@click.option("--limit", default=50, help="Number of markets to scan")
@click.option("--query", default=None, help="Filter by search query")
@click.option("--json-output", "--json", is_flag=True)
@click.option("--auto", is_flag=True, help="Auto-execute found opportunities")
@click.option("--continuous", is_flag=True, help="Run continuously")
@click.option("--interval", default=10, help="Seconds between scans (with --continuous)")
@click.option("--dry-run", is_flag=True, help="Log trades but don't execute")
def scan_cmd(limit, query, json_output, auto, continuous, interval, dry_run):
    """Scan for pair-cost arbitrage opportunities."""
    from modules.scanner import scan_for_arbitrage, scan_with_query, continuous_scan
    from config import DRY_RUN as CONFIG_DRY_RUN

    effective_dry_run = dry_run or CONFIG_DRY_RUN

    if continuous:
        console.print(
            f"[yellow]Starting continuous scan "
            f"(interval={interval}s, auto={auto}, dry_run={effective_dry_run})[/yellow]"
        )
        try:
            run_async(continuous_scan(
                interval=interval,
                limit=limit,
                auto_execute=auto,
                dry_run=effective_dry_run,
                query=query,
            ))
        except KeyboardInterrupt:
            console.print("\n[yellow]Scanner stopped[/yellow]")
        return

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

    if auto and opps:
        from modules.scanner import execute_opportunity
        console.print(f"\n[yellow]Auto-executing top {min(3, len(opps))} opportunities...[/yellow]")
        for opp in opps[:3]:
            result = run_async(execute_opportunity(opp, dry_run=effective_dry_run))
            if result:
                status = "DRY RUN" if effective_dry_run else "EXECUTED"
                console.print(
                    f"  [{status}] {result['market'][:50]} — "
                    f"profit={result['profit_pct']:.2%}"
                )


# ── Risk ─────────────────────────────────────────────────────────────

@cli.command("risk")
def risk_cmd():
    """Show current risk metrics and limits."""
    from modules.risk import get_risk_summary

    summary = get_risk_summary()

    ks_status = "[red]ACTIVE[/red]" if summary["kill_switch"] else "[green]OFF[/green]"
    console.print(Panel(
        f"Kill Switch: {ks_status}\n"
        f"Open Positions: {summary['open_positions']}\n"
        f"Total Exposure: ${summary['total_exposure']:.2f} "
        f"/ ${summary['max_total_exposure']:.2f}\n"
        f"Daily Loss: ${summary['daily_loss']:.2f} "
        f"/ ${summary['max_daily_loss']:.2f}\n"
        f"Max Drawdown: {summary['max_drawdown_pct']:.1f}%",
        title="Risk Summary",
    ))

    if summary["top_markets"]:
        table = Table(title="Top Market Exposures")
        table.add_column("Condition ID", style="dim", max_width=16)
        table.add_column("Exposure", justify="right")
        for cid, exp in summary["top_markets"]:
            table.add_row(cid[:16] + "...", f"${exp:.2f}")
        console.print(table)


# ── Engine / Daemon ──────────────────────────────────────────────────

@cli.command("run")
@click.option("--strategies", default="arb", help="Comma-separated strategies: arb,endgame")
@click.option("--interval", default=10, help="Seconds between scan cycles")
@click.option("--dry-run", is_flag=True, help="Log trades but don't execute")
@click.option("--ws", is_flag=True, help="Enable WebSocket price feed")
@click.option("--limit", default=50, help="Markets per scan")
@click.option("--query", default=None, help="Filter markets by query")
def run_cmd(strategies, interval, dry_run, ws, limit, query):
    """Run the trading engine in daemon mode."""
    from modules.engine import TradingEngine
    from config import DRY_RUN as CONFIG_DRY_RUN

    effective_dry_run = dry_run or CONFIG_DRY_RUN
    strategy_list = [s.strip() for s in strategies.split(",")]

    console.print(
        f"[bold]Starting trading engine[/bold]\n"
        f"  Strategies: {strategy_list}\n"
        f"  Interval:   {interval}s\n"
        f"  Dry run:    {effective_dry_run}\n"
        f"  WebSocket:  {ws}\n"
        f"  Limit:      {limit}"
    )

    engine = TradingEngine(
        strategies=strategy_list,
        interval=interval,
        dry_run=effective_dry_run,
        use_ws=ws,
        limit=limit,
        query=query,
    )

    try:
        run_async(engine.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Engine stopped[/yellow]")


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
