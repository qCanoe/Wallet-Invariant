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
    SimMeta,
    FailOpenReason,
)
from src.invariants import (
    I1NonAssetNoLoss,
    I2NoUnlimitedPermission,
    I3ScopeLocality,
    I4PathComplexity,
    InvariantEngine,
)
from src.config import InvariantConfig
from src.classifier import classify_transaction
from src.constants import SELECTOR_INCREASE_ALLOWANCE, SELECTOR_MULTICALL, SELECTOR_1INCH_SWAP


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
                AssetChange("0xtoken1", "ERC20", 10**6, 0),
                AssetChange("0xtoken2", "ERC20", 5 * 10**5, 0),
                AssetChange("0xtoken3", "ERC20", 2 * 10**5, 0),
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
        # depth=12 超过 high_call_depth_threshold(10)，但低于 critical(15)
        # 默认应只产生 RiskLabel，不拒绝
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            path_shape=DeltaPathShape(
                max_call_depth=12,
                delegate_call_count=3,
            )
        )

        inv = I4PathComplexity()
        passed, violation, label = inv.check(tx, delta, config)

        assert passed  # 未达到 critical 阈值，默认不拒绝
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

    def test_engine_fail_open_timeout_with_rejection_enabled(self):
        """fail_open_on_timeout=False 时，超时 → REJECT"""
        config = InvariantConfig(fail_open_on_timeout=False)
        engine = InvariantEngine(config)

        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(user_address="0xuser")
        sim_meta = SimMeta(
            success=False,
            fail_open=True,
            fail_open_reason=FailOpenReason.TIMEOUT,
            fail_open_details="simulation timed out after 30s",
        )

        decision = engine.evaluate(tx, delta, sim_meta=sim_meta)

        assert decision.decision == Decision.REJECT
        assert decision.is_fail_open is True
        assert decision.fail_open_reason == FailOpenReason.TIMEOUT

    def test_engine_fail_open_rpc_error_always_allows(self):
        """fail_open_on_timeout=False 只影响 TIMEOUT，其他 fail-open 原因仍 ALLOW"""
        config = InvariantConfig(fail_open_on_timeout=False)
        engine = InvariantEngine(config)

        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(user_address="0xuser")
        sim_meta = SimMeta(
            success=False,
            fail_open=True,
            fail_open_reason=FailOpenReason.RPC_ERROR,
        )

        decision = engine.evaluate(tx, delta, sim_meta=sim_meta)

        assert decision.decision == Decision.ALLOW


class TestClassifier:
    def test_increase_allowance_classified_as_permission_op(self):
        """increaseAllowance 应被分类为 PERMISSION_OP，而非 NON_ASSET_OP"""
        tx = TxInput(
            chain_id=1,
            from_address="0xuser",
            to_address="0xtoken",
            data=SELECTOR_INCREASE_ALLOWANCE + "0" * 128,
        )
        assert classify_transaction(tx) == TxCategory.PERMISSION_OP

    def test_1inch_swap_is_likely_swap(self):
        """1inch swap 选择器应被 is_likely_swap() 识别"""
        from src.classifier import is_likely_swap
        tx = TxInput(
            chain_id=1,
            from_address="0xuser",
            to_address="0x1inchrouter",
            data=SELECTOR_1INCH_SWAP + "0" * 192,
        )
        assert is_likely_swap(tx) is True


class TestI2DisproportionateAllowance:
    def test_allowance_exceeds_balance_multiplier_should_reject(self):
        """授权量 > 余额 × allowance_balance_multiplier(5) 应拒绝"""
        config = InvariantConfig(allowance_balance_multiplier=5)
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.NON_ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken", "ERC20", 1000, 1000),  # 余额 1000
            ],
            permission_changes=[
                PermissionChange(
                    token_address="0xtoken",
                    permission_type="allowance",
                    spender="0xspender",
                    value_before=0,
                    value_after=6000,  # 6× 余额，超过 5× 阈值
                    is_unlimited=False,
                )
            ],
        )

        inv = I2NoUnlimitedPermission()
        passed, violation, _ = inv.check(tx, delta, config)

        assert not passed
        assert violation is not None
        evidence = violation.evidence["suspicious_permissions"]
        assert any(e["reason"] == "disproportionate_allowance" for e in evidence)

    def test_allowance_within_balance_multiplier_should_allow(self):
        """授权量 ≤ 余额 × allowance_balance_multiplier 不触发拒绝"""
        config = InvariantConfig(allowance_balance_multiplier=5)
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.NON_ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken", "ERC20", 1000, 1000),
            ],
            permission_changes=[
                PermissionChange(
                    token_address="0xtoken",
                    permission_type="allowance",
                    spender="0xspender",
                    value_before=0,
                    value_after=4000,  # 4× 余额，低于 5× 阈值
                    is_unlimited=False,
                )
            ],
        )

        inv = I2NoUnlimitedPermission()
        passed, violation, _ = inv.check(tx, delta, config)

        assert passed
        assert violation is None


class TestI3DustFilter:
    def test_dust_outflow_from_unexpected_token_should_not_reject(self):
        """意外 token 的 dust 流出（< dust_threshold_wei=1000）不应触发 I3"""
        config = InvariantConfig(dust_threshold_wei=1000)
        tx = TxInput(
            chain_id=1,
            from_address="0xuser",
            to_address="0xtarget",
            data="0xa9059cbb" + "0" * 128,  # transfer
            category=TxCategory.ASSET_OP,
        )
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken1", "ERC20", 10**6, 0),   # 正常流出
                AssetChange("0xtoken2", "ERC20", 500, 0),      # dust 流出 (500 < 1000)
            ],
            scope=DeltaScope(
                affected_token_count=2,
                unexpected_tokens=["0xtoken2"],
            ),
        )

        inv = I3ScopeLocality()
        passed, violation, _ = inv.check(tx, delta, config)

        assert passed
        assert violation is None

    def test_significant_outflow_from_unexpected_token_should_reject(self):
        """意外 token 的显著流出（>= dust_threshold_wei=1000）应触发 I3"""
        config = InvariantConfig(dust_threshold_wei=1000)
        tx = TxInput(
            chain_id=1,
            from_address="0xuser",
            to_address="0xtarget",
            data="0xa9059cbb" + "0" * 128,
            category=TxCategory.ASSET_OP,
        )
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken1", "ERC20", 10**6, 0),
                AssetChange("0xtoken2", "ERC20", 5000, 0),    # 5000 >= 1000 → 显著
                AssetChange("0xtoken3", "ERC20", 2000, 0),    # 第三个 token 使 count 超限
            ],
            scope=DeltaScope(
                affected_token_count=3,  # 超过 effective_limit(2)
                unexpected_tokens=["0xtoken2", "0xtoken3"],
            ),
        )

        inv = I3ScopeLocality()
        passed, violation, _ = inv.check(tx, delta, config)

        assert not passed
        assert violation is not None


class TestI3CompositeOpRelaxedLimit:
    def test_multicall_with_three_tokens_not_rejected(self):
        """multicall（复合操作）应享有双倍 token 限额（2×2=4），3 个 token 应通过"""
        config = InvariantConfig(max_expected_token_count=2)
        tx = TxInput(
            chain_id=1,
            from_address="0xuser",
            to_address="0xrouter",
            data=SELECTOR_MULTICALL + "0" * 128,
            category=TxCategory.ASSET_OP,
        )
        delta = DeltaS(
            user_address="0xuser",
            asset_changes=[
                AssetChange("0xtoken1", "ERC20", 10**6, 0),
                AssetChange("0xtoken2", "ERC20", 5 * 10**5, 0),
                AssetChange("0xtoken3", "ERC20", 2 * 10**5, 0),
            ],
            scope=DeltaScope(
                affected_token_count=3,
                unexpected_tokens=["0xtoken2", "0xtoken3"],
            ),
        )

        inv = I3ScopeLocality()
        passed, violation, _ = inv.check(tx, delta, config)

        # affected_token_count(3) <= effective_limit(4)，不触发拒绝
        assert passed
        assert violation is None


class TestI4CriticalThreshold:
    def test_critical_call_depth_should_reject_without_flag(self):
        """max_call_depth >= critical_call_depth_threshold(15) 应无条件拒绝"""
        config = InvariantConfig(enable_path_rejection=False)  # 确认非 rejection 模式
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            path_shape=DeltaPathShape(
                max_call_depth=15,  # == critical_call_depth_threshold
                delegate_call_count=2,
            ),
        )

        inv = I4PathComplexity()
        passed, violation, label = inv.check(tx, delta, config)

        assert not passed
        assert violation is not None
        assert label is not None  # RiskLabel 也会产生

    def test_critical_delegatecall_count_should_reject_without_flag(self):
        """delegate_call_count >= critical_delegate_call_threshold(10) 应无条件拒绝"""
        config = InvariantConfig(enable_path_rejection=False)
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            path_shape=DeltaPathShape(
                max_call_depth=8,
                delegate_call_count=10,  # == critical_delegate_call_threshold
            ),
        )

        inv = I4PathComplexity()
        passed, violation, label = inv.check(tx, delta, config)

        assert not passed
        assert violation is not None

    def test_below_critical_with_rejection_disabled_should_label_only(self):
        """低于 critical 阈值且 enable_path_rejection=False，应只产生标签"""
        config = InvariantConfig(enable_path_rejection=False)
        tx = TxInput(chain_id=1, from_address="0xuser", category=TxCategory.ASSET_OP)
        delta = DeltaS(
            user_address="0xuser",
            path_shape=DeltaPathShape(
                max_call_depth=12,  # 高于 high(10)，低于 critical(15)
                delegate_call_count=3,
            ),
        )

        inv = I4PathComplexity()
        passed, violation, label = inv.check(tx, delta, config)

        assert passed
        assert violation is None
        assert label is not None
        assert label.label == "high_path_complexity"
