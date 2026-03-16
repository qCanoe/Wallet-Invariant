"""
Mock JSON-RPC response builders for integration tests.

All responses conform to the JSON-RPC 2.0 spec and match the field
expectations of src/simulator.py and src/delta_extractor.py.
"""

# ── Event topics ──────────────────────────────────────────────────────────────
TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TOPIC_APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
TOPIC_APPROVAL_FOR_ALL = "0x17307eab39ab6107e8899845ad3d59bd9653f200f220920489ca2b5937696c31"

# ── Canonical test addresses (all lowercase) ──────────────────────────────────
USER = "0xab5801a7d398351b8be11c439e05c5b3259aec9b"
ATTACKER = "0x1111111111111111111111111111111111111111"
SPENDER = "0x2222222222222222222222222222222222222222"
NFT_CONTRACT = "0x3333333333333333333333333333333333333333"
DEX_ROUTER = "0x4444444444444444444444444444444444444444"
TOKEN_A = "0xdac17f958d2ee523a2206206994597c13d831ec7"  # USDT
TOKEN_B = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"  # USDC
TOKEN_C = "0x6b175474e89094c44da98b954eedeac495271d0f"  # DAI

ONE_ETHER = 10**18


# ── Encoding helpers ──────────────────────────────────────────────────────────

def pad_address(addr: str) -> str:
    """Left-pad an address to 32 bytes for use as an indexed topic."""
    clean = addr.lower().replace("0x", "").rjust(64, "0")
    return "0x" + clean


def encode_uint256(value: int) -> str:
    """Encode a uint256 as a 32-byte hex string."""
    return "0x" + format(value, "064x")


# ── RPC response builders ─────────────────────────────────────────────────────

def eth_call_ok(request_id: int = 1) -> dict:
    """Successful eth_call response (returns 0x)."""
    return {"jsonrpc": "2.0", "id": request_id, "result": "0x"}


def eth_call_revert(message: str = "execution reverted", request_id: int = 1) -> dict:
    """Reverted eth_call response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": 3, "message": message},
    }


def receipt_ok(tx_hash: str, logs: list, request_id: int = 2) -> dict:
    """Successful eth_getTransactionReceipt response with custom logs."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "transactionHash": tx_hash,
            "blockNumber": "0x1000000",
            "status": "0x1",
            "logs": logs,
        },
    }


def receipt_empty(tx_hash: str, request_id: int = 2) -> dict:
    """Successful receipt with no logs."""
    return receipt_ok(tx_hash, [], request_id)


# ── Log builders ──────────────────────────────────────────────────────────────

def transfer_log(token: str, from_addr: str, to_addr: str, amount: int, log_index: int = 0) -> dict:
    """Build an ERC20 Transfer(from, to, value) log."""
    return {
        "address": token,
        "topics": [
            TOPIC_TRANSFER,
            pad_address(from_addr),
            pad_address(to_addr),
        ],
        "data": encode_uint256(amount),
        "blockNumber": "0x1000000",
        "logIndex": hex(log_index),
    }


def approval_log(token: str, owner: str, spender: str, amount: int, log_index: int = 0) -> dict:
    """Build an ERC20 Approval(owner, spender, value) log."""
    return {
        "address": token,
        "topics": [
            TOPIC_APPROVAL,
            pad_address(owner),
            pad_address(spender),
        ],
        "data": encode_uint256(amount),
        "blockNumber": "0x1000000",
        "logIndex": hex(log_index),
    }


def approval_for_all_log(
    token: str,
    owner: str,
    operator: str,
    approved: bool = True,
    log_index: int = 0,
) -> dict:
    """Build an ERC721/ERC1155 ApprovalForAll(owner, operator, approved) log."""
    return {
        "address": token,
        "topics": [
            TOPIC_APPROVAL_FOR_ALL,
            pad_address(owner),
            pad_address(operator),
        ],
        "data": encode_uint256(1 if approved else 0),
        "blockNumber": "0x1000000",
        "logIndex": hex(log_index),
    }
