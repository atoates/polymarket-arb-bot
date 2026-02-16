"""
Structured logging for the arbitrage bot.
"""
import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Outputs log records as single-line JSON objects."""

    def format(self, record):
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def get_logger(name: str) -> logging.Logger:
    """Create a logger with JSON output to stdout."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def log_opportunity(logger: logging.Logger, opportunity: dict):
    """Log an arbitrage opportunity with structured data."""
    record = logger.makeRecord(
        logger.name, logging.INFO, "", 0,
        f"Opportunity: {opportunity.get('strategy', 'unknown')} — "
        f"profit={opportunity.get('net_profit_pct', 0):.4%}",
        (), None,
    )
    record.extra_data = opportunity
    logger.handle(record)


def log_trade(logger: logging.Logger, trade: dict):
    """Log an executed trade with structured data."""
    record = logger.makeRecord(
        logger.name, logging.INFO, "", 0,
        f"Trade executed: {trade.get('strategy', 'unknown')} — "
        f"profit={trade.get('net_profit_pct', 0):.4%}",
        (), None,
    )
    record.extra_data = trade
    logger.handle(record)
