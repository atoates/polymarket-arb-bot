"""
Wallet module — manage wallet status and contract approvals on Polygon.

Polymarket contracts:
  - CTF Exchange: 0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
  - CTF (Conditional Tokens): 0x4D97DCd97eC945f40cF65F87097ACe5EA0476045
  - USDC.e: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
"""
import os
from web3 import Web3
from utils.logger import get_logger

logger = get_logger("wallet")

# Contract addresses on Polygon mainnet
CTF_EXCHANGE = Web3.to_checksum_address("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E")
CTF_CONTRACT = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
USDC_E = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")

# Minimal ERC20 ABI for approve + balanceOf
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

MAX_UINT256 = 2**256 - 1


def _get_web3() -> Web3:
    """Create a Web3 instance connected to the Polygon RPC node."""
    rpc_url = os.getenv("CHAINSTACK_NODE", "")
    if not rpc_url:
        raise EnvironmentError("CHAINSTACK_NODE environment variable not set")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to RPC: {rpc_url}")
    return w3


def _get_account(w3: Web3):
    """Load the trading account from private key."""
    pk = os.getenv("POLYCLAW_PRIVATE_KEY", "")
    if not pk:
        raise EnvironmentError("POLYCLAW_PRIVATE_KEY not set")
    if not pk.startswith("0x"):
        pk = "0x" + pk
    return w3.eth.account.from_key(pk)


def get_wallet_status() -> dict:
    """Return wallet address, POL balance, and USDC.e balance."""
    w3 = _get_web3()
    account = _get_account(w3)
    address = account.address

    pol_balance = w3.eth.get_balance(address)
    pol_ether = w3.from_wei(pol_balance, "ether")

    usdc_contract = w3.eth.contract(address=USDC_E, abi=ERC20_ABI)
    usdc_raw = usdc_contract.functions.balanceOf(address).call()
    usdc_balance = usdc_raw / 1e6  # USDC.e has 6 decimals

    status = {
        "address": address,
        "pol_balance": float(pol_ether),
        "usdc_balance": usdc_balance,
    }
    logger.info(f"Wallet {address}: {pol_ether:.4f} POL, {usdc_balance:.2f} USDC.e")
    return status


def approve_contracts() -> list[dict]:
    """Set max approvals for Polymarket contracts. One-time setup."""
    w3 = _get_web3()
    account = _get_account(w3)
    address = account.address

    usdc_contract = w3.eth.contract(address=USDC_E, abi=ERC20_ABI)

    approvals = [
        ("USDC.e → CTF Exchange", USDC_E, CTF_EXCHANGE),
        ("USDC.e → CTF Contract", USDC_E, CTF_CONTRACT),
    ]

    results = []
    nonce = w3.eth.get_transaction_count(address)

    for label, token_addr, spender in approvals:
        contract = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        current = contract.functions.allowance(address, spender).call()

        if current >= MAX_UINT256 // 2:
            results.append({"label": label, "status": "already_approved", "tx": None})
            logger.info(f"{label}: already approved")
            continue

        try:
            tx = contract.functions.approve(spender, MAX_UINT256).build_transaction({
                "from": address,
                "nonce": nonce,
                "gas": 60_000,
                "gasPrice": w3.eth.gas_price,
                "chainId": 137,
            })

            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            nonce += 1  # Increment for next tx

            results.append({
                "label": label,
                "status": "approved" if receipt["status"] == 1 else "failed",
                "tx": tx_hash.hex(),
            })
            logger.info(f"{label}: tx {tx_hash.hex()} (status={receipt['status']})")
        except Exception as e:
            results.append({"label": label, "status": f"error: {e}", "tx": None})
            logger.error(f"{label}: failed: {e}")

    return results
