"""
Notification utilities — sends alerts via webhook (Discord/Slack).
"""
import requests
from config import WEBHOOK_URL
from utils.logger import get_logger

logger = get_logger("notifier")


def send_notification(title: str, message: str, color: int = 0x00FF00):
    """Send a notification via Discord webhook. Silently skips if no URL configured."""
    if not WEBHOOK_URL:
        return

    try:
        # Discord-style embed payload (also works with many Slack webhooks)
        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": color,
                }
            ]
        }
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        if resp.status_code not in (200, 204):
            logger.warning(f"Webhook returned status {resp.status_code}")
    except Exception as e:
        logger.warning(f"Failed to send notification: {e}")


def notify_opportunity(opportunity: dict):
    """Send alert about a detected arbitrage opportunity."""
    profit_pct = opportunity.get("net_profit_pct", 0) * 100
    strategy = opportunity.get("strategy", "unknown")
    market = opportunity.get("market_question", "Unknown market")
    send_notification(
        title=f"Arb Opportunity — {strategy}",
        message=(
            f"**Market:** {market}\n"
            f"**Net Profit:** {profit_pct:.2f}%\n"
            f"**Total Cost:** ${opportunity.get('total_cost', 0):.4f}\n"
            f"**Guaranteed Payout:** $1.00"
        ),
        color=0x00FF00,
    )


def notify_trade(trade: dict):
    """Send alert about an executed trade."""
    profit_pct = trade.get("net_profit_pct", 0) * 100
    send_notification(
        title="Trade Executed",
        message=(
            f"**Strategy:** {trade.get('strategy', 'unknown')}\n"
            f"**Net Profit:** {profit_pct:.2f}%\n"
            f"**Size:** ${trade.get('size_usdc', 0):.2f}"
        ),
        color=0x0099FF,
    )


def notify_error(error_msg: str):
    """Send alert about an error."""
    send_notification(
        title="Bot Error",
        message=error_msg,
        color=0xFF0000,
    )
