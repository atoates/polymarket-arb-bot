"""
Swap module — USDC ↔ USDC.e via Uniswap V3 on Polygon.

Polymarket uses USDC.e (bridged), but wallets often hold native USDC.
This module handles the conversion via Uniswap V3 exactInputSingle.
"""
import os
from web3 import Web3
from modules.wallet import _get_web3, _get_account, USDC_E, ERC20_ABI
from utils.logger import get_logger

logger = get_logger("swap")

# Native USDC on Polygon (PoS)
USDC_NATIVE = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")

# Uniswap V3 SwapRouter on Polygon
UNISWAP_ROUTER = Web3.to_checksum_address("0xE592427A0AEce92De3Edee1F18E0157C05861564")

# Minimal ABI for Uniswap V3 SwapRouter.exactInputSingle
SWAP_ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    }
]

# Fee tier: 0.01% (100) — stablecoin-to-stablecoin
POOL_FEE = 100


def get_balances() -> dict:
    """Get USDC (native), USDC.e (bridged), and POL balances."""
    w3 = _get_web3()
    account = _get_account(w3)
    address = account.address

    pol_balance = float(w3.from_wei(w3.eth.get_balance(address), "ether"))

    usdc_contract = w3.eth.contract(address=USDC_NATIVE, abi=ERC20_ABI)
    usdc_raw = usdc_contract.functions.balanceOf(address).call()
    usdc_balance = usdc_raw / 1e6

    usdc_e_contract = w3.eth.contract(address=USDC_E, abi=ERC20_ABI)
    usdc_e_raw = usdc_e_contract.functions.balanceOf(address).call()
    usdc_e_balance = usdc_e_raw / 1e6

    return {
        "address": address,
        "pol_balance": pol_balance,
        "usdc_balance": usdc_balance,
        "usdc_e_balance": usdc_e_balance,
    }


def swap_usdc_to_usdc_e(
    amount: float,
    slippage_bps: int = 10,
    dry_run: bool = False,
) -> dict:
    """
    Swap native USDC → USDC.e via Uniswap V3.

    Args:
        amount: Amount of USDC to swap (human units, e.g. 9.98)
        slippage_bps: Slippage tolerance in basis points (default 10 = 0.1%)
        dry_run: If True, build the tx but don't send it
    """
    import time

    w3 = _get_web3()
    account = _get_account(w3)
    address = account.address

    amount_raw = int(amount * 1e6)
    min_out = int(amount_raw * (10000 - slippage_bps) / 10000)

    # Check balance
    usdc_contract = w3.eth.contract(address=USDC_NATIVE, abi=ERC20_ABI)
    balance = usdc_contract.functions.balanceOf(address).call()
    if balance < amount_raw:
        raise ValueError(
            f"Insufficient USDC: have {balance / 1e6:.2f}, need {amount:.2f}"
        )

    # Approve Uniswap Router to spend USDC
    allowance = usdc_contract.functions.allowance(address, UNISWAP_ROUTER).call()
    approve_tx_hash = None
    if allowance < amount_raw:
        logger.info("Approving Uniswap Router for USDC spend...")
        max_uint = 2**256 - 1
        approve_tx = usdc_contract.functions.approve(
            UNISWAP_ROUTER, max_uint
        ).build_transaction({
            "from": address,
            "nonce": w3.eth.get_transaction_count(address),
            "gas": 60_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 137,
        })
        signed = account.sign_transaction(approve_tx)
        approve_tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        w3.eth.wait_for_transaction_receipt(approve_tx_hash, timeout=60)
        logger.info(f"Approved: {approve_tx_hash.hex()}")

    # Build swap tx
    router = w3.eth.contract(address=UNISWAP_ROUTER, abi=SWAP_ROUTER_ABI)
    deadline = int(time.time()) + 300  # 5 minutes

    swap_params = (
        USDC_NATIVE,    # tokenIn
        USDC_E,         # tokenOut
        POOL_FEE,       # fee (0.01%)
        address,        # recipient
        deadline,
        amount_raw,     # amountIn
        min_out,        # amountOutMinimum
        0,              # sqrtPriceLimitX96 (0 = no limit)
    )

    nonce = w3.eth.get_transaction_count(address)
    if approve_tx_hash:
        nonce += 1  # Account for pending approve tx

    swap_tx = router.functions.exactInputSingle(swap_params).build_transaction({
        "from": address,
        "nonce": nonce,
        "gas": 200_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 137,
        "value": 0,
    })

    if dry_run:
        logger.info(
            f"[DRY RUN] Would swap {amount:.2f} USDC → USDC.e "
            f"(min out: {min_out / 1e6:.2f}, slippage: {slippage_bps}bps)"
        )
        return {
            "status": "dry_run",
            "amount_in": amount,
            "min_out": min_out / 1e6,
            "slippage_bps": slippage_bps,
        }

    signed_swap = account.sign_transaction(swap_tx)
    tx_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    result = {
        "status": "success" if receipt["status"] == 1 else "failed",
        "tx_hash": tx_hash.hex(),
        "amount_in": amount,
        "min_out": min_out / 1e6,
    }
    logger.info(f"Swap {amount:.2f} USDC → USDC.e: {result['status']} (tx: {tx_hash.hex()})")
    return result


def swap_usdc_e_to_usdc(
    amount: float,
    slippage_bps: int = 10,
    dry_run: bool = False,
) -> dict:
    """
    Swap USDC.e (bridged) → native USDC via Uniswap V3.

    Args:
        amount: Amount of USDC.e to swap (human units)
        slippage_bps: Slippage tolerance in basis points (default 10 = 0.1%)
        dry_run: If True, build the tx but don't send it
    """
    import time

    w3 = _get_web3()
    account = _get_account(w3)
    address = account.address

    amount_raw = int(amount * 1e6)
    min_out = int(amount_raw * (10000 - slippage_bps) / 10000)

    usdc_e_contract = w3.eth.contract(address=USDC_E, abi=ERC20_ABI)
    balance = usdc_e_contract.functions.balanceOf(address).call()
    if balance < amount_raw:
        raise ValueError(
            f"Insufficient USDC.e: have {balance / 1e6:.2f}, need {amount:.2f}"
        )

    allowance = usdc_e_contract.functions.allowance(address, UNISWAP_ROUTER).call()
    approve_tx_hash = None
    if allowance < amount_raw:
        logger.info("Approving Uniswap Router for USDC.e spend...")
        max_uint = 2**256 - 1
        approve_tx = usdc_e_contract.functions.approve(
            UNISWAP_ROUTER, max_uint
        ).build_transaction({
            "from": address,
            "nonce": w3.eth.get_transaction_count(address),
            "gas": 60_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 137,
        })
        signed = account.sign_transaction(approve_tx)
        approve_tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        w3.eth.wait_for_transaction_receipt(approve_tx_hash, timeout=60)
        logger.info(f"Approved: {approve_tx_hash.hex()}")

    router = w3.eth.contract(address=UNISWAP_ROUTER, abi=SWAP_ROUTER_ABI)
    deadline = int(time.time()) + 300

    swap_params = (
        USDC_E,         # tokenIn
        USDC_NATIVE,    # tokenOut
        POOL_FEE,
        address,
        deadline,
        amount_raw,
        min_out,
        0,
    )

    nonce = w3.eth.get_transaction_count(address)
    if approve_tx_hash:
        nonce += 1

    swap_tx = router.functions.exactInputSingle(swap_params).build_transaction({
        "from": address,
        "nonce": nonce,
        "gas": 200_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 137,
        "value": 0,
    })

    if dry_run:
        logger.info(
            f"[DRY RUN] Would swap {amount:.2f} USDC.e → USDC "
            f"(min out: {min_out / 1e6:.2f}, slippage: {slippage_bps}bps)"
        )
        return {
            "status": "dry_run",
            "amount_in": amount,
            "min_out": min_out / 1e6,
            "slippage_bps": slippage_bps,
        }

    signed_swap = account.sign_transaction(swap_tx)
    tx_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    result = {
        "status": "success" if receipt["status"] == 1 else "failed",
        "tx_hash": tx_hash.hex(),
        "amount_in": amount,
        "min_out": min_out / 1e6,
    }
    logger.info(f"Swap {amount:.2f} USDC.e → USDC: {result['status']} (tx: {tx_hash.hex()})")
    return result
