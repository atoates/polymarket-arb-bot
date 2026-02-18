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
from modules.wallet import _get_web3, _get_account, CTF_EXCHANGE, CTF_CONTRACT, USDC_E
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
    """
    Create authenticated CLOB client.

    Uses py-clob-client's actual constructor:
      ClobClient(host, chain_id, key, creds, signature_type, funder)

    If CLOB API credentials (api_key/secret/passphrase) are not set,
    automatically derives them from the private key.
    """
    from py_clob_client.clob_types import ApiCreds

    pk = os.getenv("POLYCLAW_PRIVATE_KEY", "")
    if not pk:
        raise EnvironmentError("POLYCLAW_PRIVATE_KEY not set")
    if not pk.startswith("0x"):
        pk = f"0x{pk}"

    chain_id = int(os.getenv("CHAIN_ID", "137"))
    sig_type = int(os.getenv("SIGNATURE_TYPE", "0"))
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")

    api_key = os.getenv("POLYMARKET_API_KEY", "")
    api_secret = os.getenv("POLYMARKET_API_SECRET", "")
    passphrase = os.getenv("POLYMARKET_PASSPHRASE", "")

    if all([api_key, api_secret, passphrase]):
        # Use provided credentials
        creds = ApiCreds(
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=passphrase,
        )
        client = ClobClient(
            host,
            chain_id=chain_id,
            key=pk,
            creds=creds,
            signature_type=sig_type,
        )
    else:
        # Auto-derive credentials from private key (L1 → L2)
        logger.info("No CLOB API credentials found — auto-deriving from private key")
        client = ClobClient(
            host,
            chain_id=chain_id,
            key=pk,
            signature_type=sig_type,
        )
        creds = client.create_or_derive_api_creds()
        if creds:
            client.set_api_creds(creds)
            logger.info(f"Derived CLOB API key: {creds.api_key[:12]}...")
        else:
            raise EnvironmentError(
                "Failed to derive CLOB credentials. Set POLYMARKET_API_KEY, "
                "POLYMARKET_API_SECRET, and POLYMARKET_PASSPHRASE manually."
            )

    return client


def split_position(condition_id: str, amount_usdc: float) -> dict:
    """Split USDC.e into YES + NO tokens via CTF contract."""
    w3 = _get_web3()
    account = _get_account(w3)
    amount_raw = int(amount_usdc * 1e6)  # 6 decimals

    # splitPosition is on the Conditional Tokens contract, NOT the Exchange
    ctf = w3.eth.contract(address=CTF_CONTRACT, abi=CTF_EXCHANGE_ABI)

    # Partition: [1, 2] = [YES, NO] for binary markets
    partition = [1, 2]
    parent_collection = b"\x00" * 32

    # Clean and validate condition_id as hex bytes32
    cid = condition_id.strip()
    if cid.startswith("0x"):
        cid = cid[2:]
    # Pad to 64 hex chars (32 bytes) if shorter
    cid = cid.zfill(64)
    try:
        condition_bytes = bytes.fromhex(cid)
    except ValueError:
        raise ValueError(
            f"condition_id is not valid hex: {condition_id!r}. "
            "Make sure you're passing the condition_id, not a CLOB token_id."
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
    yes_token_id: str | None = None,
    no_token_id: str | None = None,
    skip_sell: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Execute a buy order using split + CLOB strategy.

    1. Split USDC.e → YES + NO tokens
    2. Sell the unwanted side on CLOB (using clob_token_id, NOT condition_id)
    3. Record position

    Args:
        condition_id: Market condition ID (for CTF split)
        yes_token_id: CLOB token ID for YES outcome
        no_token_id: CLOB token ID for NO outcome
    """
    side = side.upper()
    if side not in ("YES", "NO"):
        raise ValueError(f"Side must be YES or NO, got: {side}")

    unwanted_side = "NO" if side == "YES" else "YES"
    unwanted_token_id = no_token_id if side == "YES" else yes_token_id

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

    # Step 2: Sell unwanted side on CLOB (requires the CLOB token ID)
    sell_result = None
    if not skip_sell and unwanted_token_id:
        unwanted_price = 1.0 - current_price
        token_count = amount_usdc  # After split, you get `amount` tokens of each side
        sell_result = sell_on_clob(unwanted_token_id, token_count, unwanted_price)
    elif not skip_sell and not unwanted_token_id:
        logger.warning("No CLOB token ID for unwanted side — skipping CLOB sell")

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
