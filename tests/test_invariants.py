"""
测试不变量引擎
"""

import pytest
from src.types import (
    TxInput,
    TxCategory,
    DeltaS,
    DeltaScope,
    AssetChange,
    PermissionChange,
    DeltaPathShape,
    Decision,
)
from src.invariants import (
    I1NonAssetNoLoss,
    I2NoUnlimitedPermission,
    I3ScopeLocality,
    I4PathComplexity,
    InvariantEngine,
)
from src.config import InvariantConfig


@pytest.fixture
def config():
    return InvariantConfig()


class TestI1NonAssetNoLoss:
    def test_non_asset_op_with_outflow_should_reject(self, config):
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.NON_ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken", "ERC20", 1000, 0),  # 流出 1000
            ]
        )
        
        inv = I1NonAssetNoLoss()
        passed, violation, _ = inv.check(tx, delta, config)
        
        assert not passed
        assert violation is not None
        assert "非资产操作" in violation.message
    
    def test_non_asset_op_with_inflow_should_allow(self, config):
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.NON_ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken", "ERC20", 0, 1000),  # 流入 1000
            ]
        )
        
        inv = I1NonAssetNoLoss()
        passed, violation, _ = inv.check(tx, delta, config)
        
        assert passed
        assert violation is None
    
    def test_asset_op_with_outflow_should_allow(self, config):
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken", "ERC20", 1000, 0),  # 流出
            ]
        )
        
        inv = I1NonAssetNoLoss()
        passed, _, _ = inv.check(tx, delta, config)
        
        assert passed  # AssetOp 允许资产流出


class TestI2NoUnlimitedPermission:
    def test_non_permission_op_with_unlimited_should_reject(self, config):
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.NON_ASSET_OP)
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
        
        inv = I2NoUnlimitedPermission()
        passed, violation, _ = inv.check(tx, delta, config)
        
        assert not passed
        assert violation is not None
    
    def test_permission_op_with_unlimited_should_allow(self, config):
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.PERMISSION_OP)
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
        
        inv = I2NoUnlimitedPermission()
        passed, _, _ = inv.check(tx, delta, config)
        
        assert passed  # PermissionOp 允许无限授权
    
    def test_approval_for_all_should_reject(self, config):
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            permission_changes=[
                PermissionChange(
                    token_address="0xnft",
                    permission_type="approval_for_all",
                    spender="0xoperator",
                    value_before=0,
                    value_after=1,
                    is_unlimited=True,
                )
            ]
        )
        
        inv = I2NoUnlimitedPermission()
        passed, violation, _ = inv.check(tx, delta, config)
        
        assert not passed


class TestI3ScopeLocality:
    def test_single_target_multiple_tokens_should_reject(self, config):
        tx = TxInput(
            chain_id=1, 
            from_address="0xuser", 
            to_address="0xtarget",
            data="0xa9059cbb",  # transfer
            category=TxCategory.ASSET_OP,
        )
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken1", "ERC20", 1000, 0),
                AssetChange("0xtoken2", "ERC20", 500, 0),
                AssetChange("0xtoken3", "ERC20", 200, 0),
            ],
            scope=DeltaScope(
                affected_token_count=3,
                unexpected_tokens=["0xtoken2", "0xtoken3"],
            )
        )
        
        inv = I3ScopeLocality()
        passed, violation, _ = inv.check(tx, delta, config)
        
        assert not passed
        assert "单目标操作" in violation.message
    
    def test_swap_multiple_tokens_should_allow(self, config):
        tx = TxInput(
            chain_id=1, 
            from_address="0xuser", 
            to_address="0xrouter",
            data="0x38ed1739",  # swapExactTokensForTokens
            category=TxCategory.ASSET_OP,
        )
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken1", "ERC20", 1000, 0),  # 流出
                AssetChange("0xtoken2", "ERC20", 0, 800),   # 流入
            ],
            scope=DeltaScope(affected_token_count=2)
        )
        
        inv = I3ScopeLocality()
        passed, _, _ = inv.check(tx, delta, config)
        
        assert passed  # swap 允许多 token


class TestI4PathComplexity:
    def test_high_complexity_should_label(self, config):
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            path_shape=DeltaPathShape(
                max_call_depth=15,
                delegate_call_count=3,
            )
        )
        
        inv = I4PathComplexity()
        passed, violation, label = inv.check(tx, delta, config)
        
        assert passed  # 默认不拒绝
        assert violation is None
        assert label is not None
        assert label.label == "high_path_complexity"
    
    def test_high_complexity_with_rejection_enabled(self):
        config = InvariantConfig(enable_path_rejection=True)
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            path_shape=DeltaPathShape(
                max_call_depth=15,
                delegate_call_count=6,
            )
        )
        
        inv = I4PathComplexity()
        passed, violation, label = inv.check(tx, delta, config)
        
        assert not passed
        assert violation is not None


class TestInvariantEngine:
    def test_engine_reject(self, config):
        engine = InvariantEngine(config)
        
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.NON_ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[AssetChange("0xtoken", "ERC20", 1000, 0)]
        )
        
        decision = engine.evaluate(tx, delta)
        
        assert decision.decision == Decision.REJECT
        assert len(decision.violations) > 0
    
    def test_engine_allow(self, config):
        engine = InvariantEngine(config)
        
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[AssetChange("0xtoken", "ERC20", 1000, 0)]
        )
        
        decision = engine.evaluate(tx, delta)
        
        assert decision.decision == Decision.ALLOW
