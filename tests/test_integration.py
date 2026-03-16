"""
Integration tests for the ExecutionGate pipeline.

Each test mocks httpx HTTP calls (via pytest-httpx) to avoid real RPC
dependencies, making the suite fully offline and CI-safe.

10 scenarios cover the four invariants plus fail-open and classifier
behaviour:

  I1 (NonAssetNoLoss):
    1. NON_ASSET_OP + outflow            → REJECT
    2. NON_ASSET_OP + inflow only        → ALLOW
    3. ASSET_OP (transfer) + outflow     → ALLOW  (I1 not triggered)

  I2 (NoUnlimitedPermission):
    4. NON_ASSET_OP + unlimited approval → REJECT
    5. NON_ASSET_OP + ApprovalForAll     → REJECT
    6. PERMISSION_OP + unlimited         → ALLOW  (I2 not triggered)

  I3 (ScopeLocality):
    7. Single transfer → 3 tokens out   → REJECT
    8. Swap → 2 tokens                  → ALLOW   (swap bypass)

  Misc:
    9.  RPC error                        → ALLOW (fail-open)
    10. Permit2 permitBatch (PERMISSION_OP) + unlimited → ALLOW
"""

import httpx
import pytest
from pytest_httpx import HTTPXMock

from src.gate import ExecutionGate
from src.types import Decision, InvariantId, TxInput
from src.config import GateConfig
from src.constants import (
    SELECTOR_TRANSFER,
    SELECTOR_APPROVE,
    SELECTOR_SWAP_EXACT_TOKENS,
    SELECTOR_PERMIT2_PERMIT_BATCH,
)
from tests.fixtures.rpc_responses import (
    USER, ATTACKER, SPENDER, NFT_CONTRACT, DEX_ROUTER,
    TOKEN_A, TOKEN_B, TOKEN_C,
    ONE_ETHER,
    eth_call_ok, receipt_ok, receipt_empty,
    transfer_log, approval_log, approval_for_all_log,
)

UNLIMITED = 2**256 - 1
FAKE_TX_HASH = "0x" + "ab" * 32


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tx(selector: str, to: str = TOKEN_A, value: int = 0, with_hash: bool = True) -> TxInput:
    """Build a minimal TxInput for a given selector."""
    return TxInput(
        chain_id=1,
        from_address=USER,
        to_address=to,
        data=selector + "0" * 192,  # pad calldata
        value=value,
        tx_hash=FAKE_TX_HASH if with_hash else None,
    )


def _gate(gate_config: GateConfig) -> ExecutionGate:
    return ExecutionGate(gate_config)


# ── I1 tests ──────────────────────────────────────────────────────────────────

async def test_i1_non_asset_with_outflow_is_rejected(
    httpx_mock: HTTPXMock, gate_config: GateConfig
):
    """NON_ASSET_OP that drains a token should be rejected by I1."""
    logs = [transfer_log(TOKEN_A, USER, ATTACKER, ONE_ETHER)]
    httpx_mock.add_response(json=eth_call_ok())
    httpx_mock.add_response(json=receipt_ok(FAKE_TX_HASH, logs))

    # unknown selector → NON_ASSET_OP
    tx = _tx("0xdeadbeef")
    result = await _gate(gate_config).evaluate_tx_input(tx)

    assert result.decision == Decision.REJECT
    violated_ids = {v.invariant_id for v in result.violations}
    assert InvariantId.I1_NON_ASSET_NO_LOSS in violated_ids


async def test_i1_non_asset_inflow_only_is_allowed(
    httpx_mock: HTTPXMock, gate_config: GateConfig
):
    """NON_ASSET_OP with only an inflow (airdrop) should pass I1."""
    logs = [transfer_log(TOKEN_A, ATTACKER, USER, ONE_ETHER)]
    httpx_mock.add_response(json=eth_call_ok())
    httpx_mock.add_response(json=receipt_ok(FAKE_TX_HASH, logs))

    tx = _tx("0xdeadbeef")
    result = await _gate(gate_config).evaluate_tx_input(tx)

    assert result.decision == Decision.ALLOW


async def test_i1_asset_op_outflow_is_allowed(
    httpx_mock: HTTPXMock, gate_config: GateConfig
):
    """ASSET_OP (transfer) with outflow should NOT trigger I1."""
    logs = [transfer_log(TOKEN_A, USER, ATTACKER, ONE_ETHER)]
    httpx_mock.add_response(json=eth_call_ok())
    httpx_mock.add_response(json=receipt_ok(FAKE_TX_HASH, logs))

    tx = _tx(SELECTOR_TRANSFER)
    result = await _gate(gate_config).evaluate_tx_input(tx)

    assert result.decision == Decision.ALLOW
    assert not any(v.invariant_id == InvariantId.I1_NON_ASSET_NO_LOSS for v in result.violations)


# ── I2 tests ──────────────────────────────────────────────────────────────────

async def test_i2_non_asset_with_unlimited_approval_is_rejected(
    httpx_mock: HTTPXMock, gate_config: GateConfig
):
    """NON_ASSET_OP that produces an unlimited ERC20 approval triggers I2."""
    logs = [approval_log(TOKEN_A, USER, SPENDER, UNLIMITED)]
    httpx_mock.add_response(json=eth_call_ok())
    httpx_mock.add_response(json=receipt_ok(FAKE_TX_HASH, logs))

    tx = _tx("0xdeadbeef")
    result = await _gate(gate_config).evaluate_tx_input(tx)

    assert result.decision == Decision.REJECT
    violated_ids = {v.invariant_id for v in result.violations}
    assert InvariantId.I2_NO_UNLIMITED_PERM in violated_ids


async def test_i2_non_asset_with_approval_for_all_is_rejected(
    httpx_mock: HTTPXMock, gate_config: GateConfig
):
    """NON_ASSET_OP that grants ApprovalForAll on an NFT triggers I2."""
    logs = [approval_for_all_log(NFT_CONTRACT, USER, ATTACKER, approved=True)]
    httpx_mock.add_response(json=eth_call_ok())
    httpx_mock.add_response(json=receipt_ok(FAKE_TX_HASH, logs))

    tx = _tx("0xdeadbeef")
    result = await _gate(gate_config).evaluate_tx_input(tx)

    assert result.decision == Decision.REJECT
    violated_ids = {v.invariant_id for v in result.violations}
    assert InvariantId.I2_NO_UNLIMITED_PERM in violated_ids


async def test_i2_permission_op_with_unlimited_is_allowed(
    httpx_mock: HTTPXMock, gate_config: GateConfig
):
    """Explicit approve() with unlimited allowance is PERMISSION_OP → I2 skips."""
    logs = [approval_log(TOKEN_A, USER, SPENDER, UNLIMITED)]
    httpx_mock.add_response(json=eth_call_ok())
    httpx_mock.add_response(json=receipt_ok(FAKE_TX_HASH, logs))

    # SELECTOR_APPROVE → classify as PERMISSION_OP
    tx = _tx(SELECTOR_APPROVE)
    result = await _gate(gate_config).evaluate_tx_input(tx)

    assert result.decision == Decision.ALLOW


# ── I3 tests ──────────────────────────────────────────────────────────────────

async def test_i3_single_transfer_affecting_three_tokens_is_rejected(
    httpx_mock: HTTPXMock, gate_config: GateConfig
):
    """transfer() touching 3 unrelated tokens with outflows exceeds scope and triggers I3."""
    logs = [
        transfer_log(TOKEN_A, USER, ATTACKER, ONE_ETHER, log_index=0),
        transfer_log(TOKEN_B, USER, ATTACKER, ONE_ETHER, log_index=1),
        transfer_log(TOKEN_C, USER, ATTACKER, ONE_ETHER, log_index=2),
    ]
    httpx_mock.add_response(json=eth_call_ok())
    httpx_mock.add_response(json=receipt_ok(FAKE_TX_HASH, logs))

    # to=TOKEN_A means TOKEN_A is "expected"; TOKEN_B and TOKEN_C are unexpected
    tx = _tx(SELECTOR_TRANSFER, to=TOKEN_A)
    result = await _gate(gate_config).evaluate_tx_input(tx)

    assert result.decision == Decision.REJECT
    violated_ids = {v.invariant_id for v in result.violations}
    assert InvariantId.I3_SCOPE_LOCALITY in violated_ids


async def test_i3_swap_with_two_tokens_is_allowed(
    httpx_mock: HTTPXMock, gate_config: GateConfig
):
    """Swap (ASSET_OP + is_likely_swap) touching 2 tokens should not trigger I3."""
    logs = [
        transfer_log(TOKEN_A, USER, DEX_ROUTER, ONE_ETHER, log_index=0),
        transfer_log(TOKEN_B, DEX_ROUTER, USER, ONE_ETHER * 2, log_index=1),
    ]
    httpx_mock.add_response(json=eth_call_ok())
    httpx_mock.add_response(json=receipt_ok(FAKE_TX_HASH, logs))

    tx = _tx(SELECTOR_SWAP_EXACT_TOKENS, to=DEX_ROUTER)
    result = await _gate(gate_config).evaluate_tx_input(tx)

    assert result.decision == Decision.ALLOW
    assert not any(v.invariant_id == InvariantId.I3_SCOPE_LOCALITY for v in result.violations)


# ── Fail-open test ────────────────────────────────────────────────────────────

async def test_rpc_error_triggers_fail_open(
    httpx_mock: HTTPXMock, gate_config: GateConfig
):
    """Network failure during simulation must result in ALLOW with is_fail_open=True."""
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"))

    tx = _tx("0xdeadbeef", with_hash=False)
    result = await _gate(gate_config).evaluate_tx_input(tx)

    assert result.decision == Decision.ALLOW
    assert result.is_fail_open is True


# ── Classifier / selector test ────────────────────────────────────────────────

async def test_permit2_permit_batch_classified_as_permission_op(
    httpx_mock: HTTPXMock, gate_config: GateConfig
):
    """Permit2 permitBatch must be classified as PERMISSION_OP so I2 is skipped."""
    logs = [approval_log(TOKEN_A, USER, SPENDER, UNLIMITED)]
    httpx_mock.add_response(json=eth_call_ok())
    httpx_mock.add_response(json=receipt_ok(FAKE_TX_HASH, logs))

    # SELECTOR_PERMIT2_PERMIT_BATCH was added to PERMISSION_OP_SELECTORS in Task 1
    tx = _tx(SELECTOR_PERMIT2_PERMIT_BATCH)
    result = await _gate(gate_config).evaluate_tx_input(tx)

    assert result.decision == Decision.ALLOW
    assert not any(v.invariant_id == InvariantId.I2_NO_UNLIMITED_PERM for v in result.violations)
