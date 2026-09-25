"""
api/deposit_check.py

Low-level deposit / blockchain transaction API helpers.

This module is independent from:
    services/deposit_checker.py

It:
    - Provides EVM transaction lookup helpers
    - Provides token transfer verification
    - Provides HTTP API handlers for testing

It does NOT:
    - Modify Deposit records
    - Credit user balances
    - Start background loops
    - Create Telegram bots
    - Start polling
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import requests
from aiohttp import web

logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_TIMEOUT = 15

POLYGON_RPC_URL = "https://polygon-rpc.com/"
BSC_RPC_URL = "https://bsc-dataseed.binance.org/"

# ============================================================
# OFFICIAL TOKEN CONTRACTS
# ============================================================

TOKEN_CONTRACTS = {
    "POLYGON": {
        "USDT": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",
        "USDC": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
    },
    "BEP20": {
        "USDT": "0x55d398326f99059ff775485246999027b3197955",
        "BUSD": "0xe9e7cea3dedca5984780bafc599bd69add087d56",
        "USDC": "0x8ac76a51cc95059ff775485246999027b3197955",
    },
}

# Correct ERC20 Transfer event topic:
#
# keccak256("Transfer(address,address,uint256)")
#
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55"
    "4df523b3ef"
)

# ============================================================
# TOKEN DECIMALS
# ============================================================

TOKEN_DECIMALS = {
    "USDT": {
        "POLYGON": 6,
        "BEP20": 18,
    },
    "USDC": {
        "POLYGON": 6,
        "BEP20": 18,
    },
    "BUSD": {
        "BEP20": 18,
    },
}


# ============================================================
# DATA CLASS
# ============================================================

@dataclass
class TransactionResult:
    found: bool
    confirmed: bool = False

    tx_hash: str = ""
    from_address: str = ""
    to_address: str = ""

    contract_address: str = ""
    token: str = ""
    network: str = ""

    amount: Decimal = Decimal("0")

    block_number: int = 0
    confirmations: int = 0

    status: Optional[int] = None

    reason: str = ""

    raw: Optional[dict[str, Any]] = None


# ============================================================
# VALIDATION
# ============================================================

def valid_tx_hash(tx_hash: str) -> bool:
    """
    Validate an EVM transaction hash.
    """

    if not isinstance(tx_hash, str):
        return False

    tx_hash = tx_hash.strip()

    return (
        len(tx_hash) == 66
        and tx_hash.startswith("0x")
        and all(
            c in "0123456789abcdefABCDEF"
            for c in tx_hash[2:]
        )
    )


def valid_address(address: str) -> bool:
    """
    Validate a basic EVM address.
    """

    if not isinstance(address, str):
        return False

    address = address.strip()

    return (
        len(address) == 42
        and address.startswith("0x")
        and all(
            c in "0123456789abcdefABCDEF"
            for c in address[2:]
        )
    )


# ============================================================
# RPC REQUEST
# ============================================================

def rpc_call(
    rpc_url: str,
    method: str,
    params: list[Any],
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[Any]:
    """
    Execute a JSON-RPC request.

    Returns:
        JSON-RPC result on success.
        None on failure.
    """

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    try:
        response = requests.post(
            rpc_url,
            json=payload,
            timeout=timeout,
        )

        response.raise_for_status()

        data = response.json()

        if "error" in data:
            logger.warning(
                "RPC error | method=%s | error=%s",
                method,
                data["error"],
            )
            return None

        return data.get("result")

    except requests.RequestException as exc:
        logger.warning(
            "RPC request failed | method=%s | error=%s",
            method,
            exc,
        )
        return None

    except ValueError:
        logger.warning(
            "RPC returned invalid JSON | method=%s",
            method,
        )
        return None

    except Exception:
        logger.exception(
            "Unexpected RPC error | method=%s",
            method,
        )
        return None


# ============================================================
# BLOCK INFORMATION
# ============================================================

def get_latest_block(
    rpc_url: str,
) -> Optional[int]:
    """
    Return the latest block number.
    """

    result = rpc_call(
        rpc_url,
        "eth_blockNumber",
        [],
    )

    if result is None:
        return None

    try:
        return int(result, 16)

    except (TypeError, ValueError):
        return None


def get_transaction_receipt(
    rpc_url: str,
    tx_hash: str,
) -> Optional[dict[str, Any]]:
    """
    Retrieve a transaction receipt.

    Returns None when:
        - transaction is not mined
        - RPC request fails
    """

    if not valid_tx_hash(tx_hash):
        return None

    result = rpc_call(
        rpc_url,
        "eth_getTransactionReceipt",
        [tx_hash],
    )

    if not isinstance(result, dict):
        return None

    return result


def get_transaction(
    rpc_url: str,
    tx_hash: str,
) -> Optional[dict[str, Any]]:
    """
    Retrieve the raw transaction.
    """

    if not valid_tx_hash(tx_hash):
        return None

    result = rpc_call(
        rpc_url,
        "eth_getTransactionByHash",
        [tx_hash],
    )

    if not isinstance(result, dict):
        return None

    return result


# ============================================================
# CONFIRMATIONS
# ============================================================

def get_confirmations(
    rpc_url: str,
    block_number: int,
) -> int:
    """
    Calculate transaction confirmations.

    A transaction in the latest block has 1 confirmation.
    """

    latest = get_latest_block(rpc_url)

    if latest is None:
        return 0

    if block_number <= 0:
        return 0

    if latest < block_number:
        return 0

    return latest - block_number + 1


# ============================================================
# ERC20 TRANSFER DECODING
# ============================================================

def _topic_address(topic: str) -> str:
    """
    Convert an indexed ERC20 address topic to an address.
    """

    if not isinstance(topic, str):
        return ""

    topic = topic.removeprefix("0x")

    if len(topic) < 40:
        return ""

    return "0x" + topic[-40:]


def _decode_uint256(data: str) -> int:
    """
    Decode a uint256 ABI value.
    """

    if not isinstance(data, str):
        return 0

    data = data.removeprefix("0x")

    try:
        return int(data, 16)

    except ValueError:
        return 0


# ============================================================
# TOKEN DECIMALS
# ============================================================

def token_decimals(
    token: str,
    network: str,
) -> int:
    """
    Return known token decimals.
    """

    token = token.upper()
    network = network.upper()

    return TOKEN_DECIMALS.get(
        token,
        {},
    ).get(
        network,
        18,
    )


# ============================================================
# DECODE TRANSFER LOG
# ============================================================

def decode_transfer_log(
    log: dict[str, Any],
    *,
    network: str,
    token: str,
) -> Optional[dict[str, Any]]:
    """
    Decode a standard ERC20 Transfer event log.
    """

    topics = log.get("topics") or []

    if len(topics) < 3:
        return None

    topic0 = str(topics[0]).lower()

    if topic0 != TRANSFER_TOPIC:
        return None

    sender = _topic_address(
        str(topics[1])
    )

    receiver = _topic_address(
        str(topics[2])
    )

    raw_amount = _decode_uint256(
        str(log.get("data", "0x0"))
    )

    decimals = token_decimals(
        token,
        network,
    )

    amount = Decimal(raw_amount) / (
        Decimal(10) ** decimals
    )

    return {
        "sender": sender,
        "receiver": receiver,
        "contract": str(
            log.get("address", "")
        ).lower(),
        "amount": amount,
        "token": token.upper(),
        "network": network.upper(),
    }


# ============================================================
# GET TOKEN TRANSFERS FROM RECEIPT
# ============================================================

def get_token_transfers(
    receipt: dict[str, Any],
    *,
    network: str,
    token: str,
) -> list[dict[str, Any]]:
    """
    Decode all ERC20 transfers contained
    in a transaction receipt.
    """

    transfers: list[dict[str, Any]] = []

    logs = receipt.get("logs") or []

    official_contract = TOKEN_CONTRACTS.get(
        network.upper(),
        {},
    ).get(
        token.upper(),
        "",
    ).lower()

    for log in logs:

        if not isinstance(log, dict):
            continue

        contract = str(
            log.get("address", "")
        ).lower()

        if (
            official_contract
            and contract != official_contract
        ):
            continue

        transfer = decode_transfer_log(
            log,
            network=network,
            token=token,
        )

        if transfer:
            transfers.append(transfer)

    return transfers


# ============================================================
# VERIFY TOKEN DEPOSIT
# ============================================================

def check_token_deposit(
    *,
    rpc_url: str,
    tx_hash: str,
    network: str,
    token: str,
    receiving_address: str,
    minimum_amount: Decimal | float | str = Decimal("0"),
    required_confirmations: int = 1,
) -> TransactionResult:
    """
    Verify an ERC20 token deposit using an EVM RPC endpoint.

    This function only checks blockchain state.

    It does NOT modify the database.
    """

    network = network.upper()
    token = token.upper()
    receiving_address = receiving_address.lower()

    if not valid_tx_hash(tx_hash):
        return TransactionResult(
            found=False,
            network=network,
            token=token,
            reason="invalid transaction hash",
        )

    if not valid_address(receiving_address):
        return TransactionResult(
            found=False,
            network=network,
            token=token,
            reason="invalid receiving address",
        )

    official_contract = TOKEN_CONTRACTS.get(
        network,
        {},
    ).get(
        token,
        "",
    )

    if not official_contract:
        return TransactionResult(
            found=False,
            network=network,
            token=token,
            reason="unsupported token/network",
        )

    receipt = get_transaction_receipt(
        rpc_url,
        tx_hash,
    )

    if receipt is None:
        return TransactionResult(
            found=False,
            tx_hash=tx_hash,
            network=network,
            token=token,
            reason="transaction not mined or unavailable",
        )

    try:
        status = int(
            receipt.get("status", "0x0"),
            16,
        )

    except (TypeError, ValueError):
        status = 0

    if status != 1:
        return TransactionResult(
            found=True,
            confirmed=False,
            tx_hash=tx_hash,
            network=network,
            token=token,
            status=status,
            reason="transaction failed",
            raw=receipt,
        )

    block_hex = receipt.get("blockNumber")

    try:
        block_number = (
            int(block_hex, 16)
            if block_hex
            else 0
        )

    except (TypeError, ValueError):
        block_number = 0

    confirmations = get_confirmations(
        rpc_url,
        block_number,
    )

    transfers = get_token_transfers(
        receipt,
        network=network,
        token=token,
    )

    try:
        minimum = Decimal(
            str(minimum_amount)
        )

    except (InvalidOperation, ValueError):
        minimum = Decimal("0")

    target = None

    for transfer in transfers:

        if (
            transfer["receiver"].lower()
            != receiving_address
        ):
            continue

        if (
            transfer["contract"].lower()
            != official_contract.lower()
        ):
            continue

        try:
            amount = Decimal(
                str(transfer["amount"])
            )

        except (InvalidOperation, ValueError):
            continue

        if amount < minimum:
            continue

        target = transfer
        break

    if target is None:
        return TransactionResult(
            found=False,
            confirmed=False,
            tx_hash=tx_hash,
            network=network,
            token=token,
            block_number=block_number,
            confirmations=confirmations,
            status=status,
            reason="matching token transfer not found",
            raw=receipt,
        )

    confirmed = (
        confirmations >= required_confirmations
    )

    return TransactionResult(
        found=True,
        confirmed=confirmed,
        tx_hash=tx_hash,
        from_address=target["sender"],
        to_address=target["receiver"],
        contract_address=target["contract"],
        token=target["token"],
        network=target["network"],
        amount=target["amount"],
        block_number=block_number,
        confirmations=confirmations,
        status=status,
        reason=(
            "confirmed"
            if confirmed
            else "waiting for confirmations"
        ),
        raw=receipt,
    )


# ============================================================
# NETWORK HELPERS
# ============================================================

def polygon_rpc() -> str:
    return POLYGON_RPC_URL


def bsc_rpc() -> str:
    return BSC_RPC_URL


def get_rpc_for_network(
    network: str,
) -> Optional[str]:
    """
    Return the default public RPC for a supported network.
    """

    network = network.upper()

    if network == "POLYGON":
        return POLYGON_RPC_URL

    if network in {"BEP20", "BSC"}:
        return BSC_RPC_URL

    return None


# ============================================================
# SIMPLE HIGH-LEVEL CHECK
# ============================================================

def check_deposit(
    *,
    tx_hash: str,
    network: str,
    token: str,
    receiving_address: str,
    minimum_amount: Decimal | float | str = Decimal("0"),
    required_confirmations: int = 1,
) -> TransactionResult:
    """
    Convenience wrapper using the default RPC.
    """

    rpc_url = get_rpc_for_network(
        network
    )

    if not rpc_url:
        return TransactionResult(
            found=False,
            network=network.upper(),
            token=token.upper(),
            reason="unsupported network",
        )

    return check_token_deposit(
        rpc_url=rpc_url,
        tx_hash=tx_hash,
        network=network,
        token=token,
        receiving_address=receiving_address,
        minimum_amount=minimum_amount,
        required_confirmations=required_confirmations,
    )


# ============================================================
# API SERIALIZATION
# ============================================================

def transaction_result_to_dict(
    result: TransactionResult,
) -> dict[str, Any]:
    """
    Convert TransactionResult into JSON-safe data.
    """

    return {
        "success": True,
        "found": result.found,
        "confirmed": result.confirmed,
        "tx_hash": result.tx_hash,
        "from_address": result.from_address,
        "to_address": result.to_address,
        "contract_address": result.contract_address,
        "token": result.token,
        "network": result.network,
        "amount": str(result.amount),
        "block_number": result.block_number,
        "confirmations": result.confirmations,
        "status": result.status,
        "reason": result.reason,
    }


# ============================================================
# API HEALTH HANDLER
# ============================================================

async def deposit_check_health(
    request: web.Request,
) -> web.Response:
    """
    Health endpoint.

    GET /api/deposit_check/health
    """

    return web.json_response(
        {
            "success": True,
            "service": "deposit_check",
            "status": "ok",
            "message": "Deposit check API is running.",
        }
    )


# ============================================================
# API DEPOSIT CHECK HANDLER
# ============================================================

async def deposit_check_handler(
    request: web.Request,
) -> web.Response:
    """
    HTTP API endpoint.

    POST /api/deposit_check

    JSON:

    {
        "tx_hash": "0x...",
        "network": "POLYGON",
        "token": "USDT",
        "receiving_address": "0x...",
        "minimum_amount": "1",
        "required_confirmations": 1
    }
    """

    try:
        data = await request.json()

    except Exception:
        return web.json_response(
            {
                "success": False,
                "error": "Request body must be valid JSON.",
            },
            status=400,
        )

    if not isinstance(data, dict):
        return web.json_response(
            {
                "success": False,
                "error": "JSON body must be an object.",
            },
            status=400,
        )

    tx_hash = str(
        data.get("tx_hash", "")
    ).strip()

    network = str(
        data.get("network", "")
    ).strip().upper()

    token = str(
        data.get("token", "")
    ).strip().upper()

    receiving_address = str(
        data.get("receiving_address", "")
    ).strip()

    minimum_amount = data.get(
        "minimum_amount",
        "0",
    )

    required_confirmations = data.get(
        "required_confirmations",
        1,
    )

    if not tx_hash:
        return web.json_response(
            {
                "success": False,
                "error": "tx_hash is required.",
            },
            status=400,
        )

    if not network:
        return web.json_response(
            {
                "success": False,
                "error": "network is required.",
            },
            status=400,
        )

    if not token:
        return web.json_response(
            {
                "success": False,
                "error": "token is required.",
            },
            status=400,
        )

    if not receiving_address:
        return web.json_response(
            {
                "success": False,
                "error": "receiving_address is required.",
            },
            status=400,
        )

    try:
        required_confirmations = int(
            required_confirmations
        )

    except (TypeError, ValueError):
        return web.json_response(
            {
                "success": False,
                "error": "required_confirmations must be an integer.",
            },
            status=400,
        )

    if required_confirmations < 1:
        required_confirmations = 1

    try:
        result = check_deposit(
            tx_hash=tx_hash,
            network=network,
            token=token,
            receiving_address=receiving_address,
            minimum_amount=minimum_amount,
            required_confirmations=required_confirmations,
        )

    except Exception as exc:
        logger.exception(
            "Deposit API check failed"
        )

        return web.json_response(
            {
                "success": False,
                "error": "Internal deposit check error.",
                "details": str(exc),
            },
            status=500,
        )

    return web.json_response(
        transaction_result_to_dict(result)
    )


# ============================================================
# GET API INFORMATION
# ============================================================

async def deposit_check_info(
    request: web.Request,
) -> web.Response:
    """
    GET /api/deposit_check

    Useful for browser testing.
    """

    return web.json_response(
        {
            "success": True,
            "service": "deposit_check",
            "status": "online",
            "endpoints": {
                "health": "GET /api/deposit_check/health",
                "check": "POST /api/deposit_check",
            },
            "supported_networks": [
                "POLYGON",
                "BEP20",
            ],
            "supported_tokens": {
                "POLYGON": [
                    "USDT",
                    "USDC",
                ],
                "BEP20": [
                    "USDT",
                    "BUSD",
                    "USDC",
                ],
            },
        }
    )