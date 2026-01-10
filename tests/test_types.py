"""
测试类型定义
"""

import pytest
from src.types import (
    TxInput,
    TxCategory,
    AssetChange,
    PermissionChange,
    DeltaS,
    DeltaScope,
    GateDecision,
    Decision,
    InvariantViolation,
    InvariantId,
    ETH_ADDRESS,
    is_unlimited_allowance,
    UNLIMITED_ALLOWANCE,
)


class TestTxInput:
    def test_selector_extraction(self):
        tx = TxInput(
            chain_id=1,
            from_address="0x1234",
            to_address="0x5678",
            data="0xa9059cbb0000000000000000000000001234",  # transfer
        )
        assert tx.selector() == "0xa9059cbb"
    
    def test_selector_empty_data(self):
        tx = TxInput(chain_id=1, from_address="0x1234", data="0x")
        assert tx.selector() is None
    
    def test_to_dict(self):
        tx = TxInput(
            chain_id=1,
            from_address="0x1234",
            to_address="0x5678",
            value=1000,
            category=TxCategory.ASSET_OP,
        )
        d = tx.to_dict()
        assert d["chain_id"] == 1
        assert d["from"] == "0x1234"
        assert d["value"] == "1000"
        assert d["category"] == "asset_op"


class TestAssetChange:
    def test_delta_calculation(self):
        change = AssetChange(
            token_address="0xtoken",
            token_type="ERC20",
            balance_before=1000,
            balance_after=500,
        )
        assert change.delta == -500
        assert change.is_outflow
        assert not change.is_inflow
    
    def test_inflow(self):
        change = AssetChange(
            token_address="0xtoken",
            token_type="ERC20",
            balance_before=0,
            balance_after=1000,
        )
        assert change.delta == 1000
        assert change.is_inflow
        assert not change.is_outflow


class TestPermissionChange:
    def test_new_permission(self):
        perm = PermissionChange(
            token_address="0xtoken",
            permission_type="allowance",
            spender="0xspender",
            value_before=0,
            value_after=1000,
        )
        assert perm.is_new_permission
        assert not perm.is_revocation
    
    def test_revocation(self):
        perm = PermissionChange(
            token_address="0xtoken",
            permission_type="allowance",
            spender="0xspender",
            value_before=1000,
            value_after=0,
        )
        assert perm.is_revocation
        assert not perm.is_new_permission


class TestDeltaS:
    def test_has_outflow(self):
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken", "ERC20", 1000, 500),
            ]
        )
        assert delta.has_outflow
        assert delta.total_outflow == 500
    
    def test_no_outflow(self):
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken", "ERC20", 0, 1000),
            ]
        )
        assert not delta.has_outflow
        assert delta.total_outflow == 0
    
    def test_unlimited_permission_detection(self):
        delta = DeltaS(
            user_address="0xuser",
            permission_changes=[
                PermissionChange(
                    token_address="0xtoken",
                    permission_type="allowance",
                    spender="0xspender",
                    value_before=0,
                    value_after=2**256 - 1,
                    is_unlimited=True,
                )
            ]
        )
        assert delta.has_new_unlimited_permission


class TestIsUnlimitedAllowance:
    def test_unlimited(self):
        assert is_unlimited_allowance(UNLIMITED_ALLOWANCE)
        assert is_unlimited_allowance(2**255)
    
    def test_not_unlimited(self):
        assert not is_unlimited_allowance(1000)
        assert not is_unlimited_allowance(2**100)


class TestGateDecision:
    def test_allow_decision(self):
        decision = GateDecision(decision=Decision.ALLOW)
        d = decision.to_dict()
        assert d["decision"] == "allow"
        assert d["violations"] == []
    
    def test_reject_decision(self):
        decision = GateDecision(
            decision=Decision.REJECT,
            violations=[
                InvariantViolation(
                    invariant_id=InvariantId.I1_NON_ASSET_NO_LOSS,
                    message="Test violation",
                )
            ]
        )
        d = decision.to_dict()
        assert d["decision"] == "reject"
        assert len(d["violations"]) == 1
        assert d["violations"][0]["invariant_id"] == "I1"
