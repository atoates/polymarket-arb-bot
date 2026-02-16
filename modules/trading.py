"""
Trading module — execute buy orders via split + CLOB strategy.

Strategy:
  1. Split USDC.e into YES + NO tokens via CTF contract
  2. Sell the unwanted side on the CLOB order book
  3. Record the position with entry price
"""
import os
import json
import time
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from modules.wallet import _get_web3, _get_account, CTF_EXCHANGE, USDC_E
from modules.positions import record_position
from utils.logger import get_logger
from utils.notifier import notify_trade

logger = get_logger("trading")

# CTF Exchange partial ABI for splitPosition
CTF_EXCHANGE_ABI = [
    {
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "partition", "type": "uint256[]"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "splitPosition",
        "outputs": [],
        "type": "function",
    }
]


def _get_clob_client() -> ClobClient:
    """Create authenticated CLOB client."""
    api_key = os.getenv("POLYMARKET_API_KEY", "")
    api_secret = os.getenv("POLYMARKET_API_SECRET", "")
    passphrase = os.getenv("POLYMARKET_PASSPHRASE", "")
    pk = os.getenv("POLYCLAW_PRIVATE_KEY", "")

    if not all([api_key, api_secret, passphrase, pk]):
        raise EnvironmentError("Missing CLOB credentials. Check .env file.")

    chain_id = int(os.getenv("CHAIN_ID", "137"))

    client = ClobClient(
        host="https://clob.polymarket.com",
        key=api_key,
        chain_id=chain_id,
        private_key=pk if pk.startswith("0x") else f"0x{pk}",
        signature_type=int(os.getenv("SIGNATURE_TYPE", "1")),
        api_creds={
            "api_key": api_key,
            "api_secret": api_secret,
            "api_passphrase": passphrase,
        },
    )
    return client


def split_position(condition_id: str, amount_usdc: float) -> dict:
    """Split USDC.e into YES + NO tokens via CTF contract."""
    w3 = _get_web3()
    account = _get_account(w3)
    amount_raw = int(amount_usdc * 1e6)  # 6 decimals

    ctf = w3.eth.contract(address=CTF_EXCHANGE, abi=CTF_EXCHANGE_ABI)

    # Partition: [1, 2] = [YES, NO] for binary markets
    partition = [1, 2]
    parent_collection = b"\x00" * 32
    condition_bytes = bytes.fromhex(
        condition_id if not condition_id.startswith("0x") else condition_id[2:]
    )

    tx = ctf.functions.splitPosition(
        USDC_E,
        parent_collection,
        condition_bytes,
        partition,
        amount_raw,
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 300_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 137,
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    result = {
        "tx_hash": tx_hash.hex(),
        "status": "success" if receipt["status"] == 1 else "failed",
        "amount_usdc": amount_usdc,
        "condition_id": condition_id,
    }
    logger.info(f"Split {amount_usdc} USDC.e: {result['status']} (tx: {tx_hash.hex()})")
    return result


def sell_on_clob(token_id: str, amount: float, price: float) -> dict | None:
    """Sell tokens on the CLOB order book."""
    max_retries = int(os.getenv("CLOB_MAX_RETRIES", "5"))

    for attempt in range(max_retries):
        try:
            client = _get_clob_client()
            order_args = OrderArgs(
                price=price,
                size=amount,
                side="SELL",
                token_id=token_id,
            )
            resp = client.create_and_post_order(order_args)
            logger.info(f"CLOB sell order placed: {resp}")
            return {"status": "placed", "response": resp, "attempt": attempt + 1}

        except Exception as e:
            logger.warning(f"CLOB sell attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    logger.error("All CLOB sell attempts failed. Tokens remain in wallet.")
    return None


def buy(
    condition_id: str,
    side: str,
    amount_usdc: float,
    current_price: float,
    skip_sell: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Execute a buy order using split + CLOB strategy.

    1. Split USDC.e → YES + NO tokens
    2. Sell the unwanted side on CLOB
    3. Record position
    """
    side = side.upper()
    if side not in ("YES", "NO"):
        raise ValueError(f"Side must be YES or NO, got: {side}")

    unwanted_side = "NO" if side == "YES" else "YES"

    if dry_run:
        logger.info(f"[DRY RUN] Would buy {side} on {condition_id} for ${amount_usdc}")
        return {
            "status": "dry_run",
            "side": side,
            "amount_usdc": amount_usdc,
            "condition_id": condition_id,
        }

    # Step 1: Split
    split_result = split_position(condition_id, amount_usdc)
    if split_result["status"] != "success":
        return {"status": "split_failed", **split_result}

    # Step 2: Sell unwanted side on CLOB
    sell_result = None
    if not skip_sell:
        unwanted_price = 1.0 - current_price
        token_count = amount_usdc  # After split, you get `amount` tokens of each side
        sell_result = sell_on_clob(condition_id, token_count, unwanted_price)

    # Step 3: Compute entry price and record position
    recovered = 0.0
    if sell_result and sell_result.get("status") == "placed":
        recovered = (1.0 - current_price) * amount_usdc

    net_cost = amount_usdc - recovered
    entry_price = net_cost / amount_usdc if amount_usdc > 0 else current_price

    position = record_position(
        condition_id=condition_id,
        side=side,
        size=amount_usdc,
        entry_price=entry_price,
    )

    trade_result = {
        "status": "executed",
        "side": side,
        "amount_usdc": amount_usdc,
        "entry_price": entry_price,
        "net_cost": net_cost,
        "recovered": recovered,
        "split_tx": split_result.get("tx_hash"),
        "sell_status": sell_result.get("status") if sell_result else "skipped",
        "condition_id": condition_id,
    }

    notify_trade({
        "strategy": "split_clob",
        "net_profit_pct": 0,
        "size_usdc": amount_usdc,
    })

    logger.info(f"Buy {side} complete: entry={entry_price:.4f}, cost=${net_cost:.2f}")
    return trade_result
