"""
Wallet Invariant MVP - 不变量引擎

实现四条不变量：
- I1: 非资产行为不变量（NonAssetOp → 不得发生资产损失）
- I2: 权限比例不变量（一次性目标不得引入永久权限）
- I3: 作用域局部性不变量（单目标操作不得影响多资产）
- I4: 路径合理性不变量（可选，标签化）

设计原则：
- fail-open: 证据不足时允许
- 只拒绝有强证据的违规
"""

import logging
from typing import List, Optional, Tuple
from abc import ABC, abstractmethod

from .types import (
    TxInput,
    TxCategory,
    DeltaS,
    SimMeta,
    Decision,
    GateDecision,
    InvariantId,
    InvariantViolation,
    RiskLabel,
    FailOpenReason,
    is_unlimited_allowance,
)
from .config import InvariantConfig, DEFAULT_CONFIG
from .classifier import is_likely_swap

logger = logging.getLogger(__name__)


class Invariant(ABC):
    """不变量基类"""
    
    @property
    @abstractmethod
    def invariant_id(self) -> InvariantId:
        """不变量标识"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """不变量描述"""
        pass
    
    @abstractmethod
    def check(
        self,
        tx: TxInput,
        delta: DeltaS,
        config: InvariantConfig
    ) -> Tuple[bool, Optional[InvariantViolation], Optional[RiskLabel]]:
        """
        检查不变量
        
        Args:
            tx: 交易输入
            delta: 状态变化
            config: 配置
        
        Returns:
            (passed, violation, risk_label)
            - passed: 是否通过（True = 不拒绝）
            - violation: 如果拒绝，返回违规记录
            - risk_label: 风险标签（非拒绝级别）
        """
        pass


class I1NonAssetNoLoss(Invariant):
    """
    I1: 非资产行为不变量
    
    规则：NonAssetOp 类型的交易不得导致用户资产净流出
    
    触发条件：tx.category == NonAssetOp
    拒绝条件：delta 显示用户资产净流出（ETH 或任意 token）
    """
    
    @property
    def invariant_id(self) -> InvariantId:
        return InvariantId.I1_NON_ASSET_NO_LOSS
    
    @property
    def description(self) -> str:
        return "非资产操作不得导致资产损失"
    
    def check(
        self,
        tx: TxInput,
        delta: DeltaS,
        config: InvariantConfig
    ) -> Tuple[bool, Optional[InvariantViolation], Optional[RiskLabel]]:
        # 只对 NonAssetOp 检查
        if tx.category != TxCategory.NON_ASSET_OP:
            return True, None, None
        
        # 检查是否有资产流出
        outflows = [c for c in delta.asset_changes if c.is_outflow]
        
        if not outflows:
            return True, None, None
        
        # 构建证据
        outflow_details = []
        total_outflow = 0
        for c in outflows:
            total_outflow += abs(c.delta)
            outflow_details.append({
                "token": c.token_address,
                "type": c.token_type,
                "amount": str(abs(c.delta)),
                "token_id": c.token_id,
            })
        
        violation = InvariantViolation(
            invariant_id=self.invariant_id,
            message=f"非资产操作导致 {len(outflows)} 项资产流出",
            evidence={
                "category": tx.category.value,
                "outflows": outflow_details,
                "total_outflow_raw": str(total_outflow),
            }
        )
        
        return False, violation, None


class I2NoUnlimitedPermission(Invariant):
    """
    I2: 权限比例不变量
    
    规则：非授权操作不得引入永久/无限权限
    
    触发条件：交易包含权限变化但分类不为 PermissionOp
    拒绝条件：
      - ERC20 allowance 从 0/小额 → 极大值（≥阈值）
      - isApprovedForAll 从 false → true
    """
    
    @property
    def invariant_id(self) -> InvariantId:
        return InvariantId.I2_NO_UNLIMITED_PERM
    
    @property
    def description(self) -> str:
        return "一次性操作不得引入永久权限"
    
    def check(
        self,
        tx: TxInput,
        delta: DeltaS,
        config: InvariantConfig
    ) -> Tuple[bool, Optional[InvariantViolation], Optional[RiskLabel]]:
        # 如果是明确的授权操作，不触发此检查
        if tx.category == TxCategory.PERMISSION_OP:
            return True, None, None
        
        # 没有权限变化，通过
        if not delta.permission_changes:
            return True, None, None
        
        # 检查可疑的权限变化
        suspicious = []
        
        for perm in delta.permission_changes:
            # 检查 1: 无限授权
            if perm.is_new_permission and perm.is_unlimited:
                suspicious.append({
                    "token": perm.token_address,
                    "type": perm.permission_type,
                    "spender": perm.spender,
                    "reason": "unlimited_allowance" if perm.permission_type == "allowance" else "approval_for_all",
                    "value": str(perm.value_after),
                })
            
            # 检查 2: 超大授权（超过阈值）
            elif (perm.permission_type == "allowance" and 
                  perm.is_new_permission and
                  perm.value_after >= config.unlimited_allowance_threshold):
                suspicious.append({
                    "token": perm.token_address,
                    "type": perm.permission_type,
                    "spender": perm.spender,
                    "reason": "near_unlimited_allowance",
                    "value": str(perm.value_after),
                })
        
        if not suspicious:
            return True, None, None
        
        violation = InvariantViolation(
            invariant_id=self.invariant_id,
            message=f"非授权操作引入 {len(suspicious)} 项永久/无限权限",
            evidence={
                "category": tx.category.value,
                "suspicious_permissions": suspicious,
            }
        )
        
        return False, violation, None


class I3ScopeLocality(Invariant):
    """
    I3: 作用域局部性不变量
    
    规则：单目标操作不得影响多个资产
    
    触发条件：分类为 AssetOp 且不是 swap
    拒绝条件：
      - 涉及的 token 合约数 > 预期上限
      - 出现与 to 无关的 token 流出
    """
    
    @property
    def invariant_id(self) -> InvariantId:
        return InvariantId.I3_SCOPE_LOCALITY
    
    @property
    def description(self) -> str:
        return "单目标操作不得影响多资产"
    
    def check(
        self,
        tx: TxInput,
        delta: DeltaS,
        config: InvariantConfig
    ) -> Tuple[bool, Optional[InvariantViolation], Optional[RiskLabel]]:
        # 只对 AssetOp 检查
        if tx.category != TxCategory.ASSET_OP:
            return True, None, None
        
        # swap 允许涉及多个 token，放宽检查
        if is_likely_swap(tx):
            # 对 swap，只在出现"额外第三方 token 流出"时警告
            if delta.scope.unexpected_tokens:
                outflow_unexpected = [
                    c for c in delta.asset_changes 
                    if c.is_outflow and c.token_address in delta.scope.unexpected_tokens
                ]
                if outflow_unexpected:
                    # 只做警告，不拒绝
                    label = RiskLabel(
                        label="unexpected_token_outflow_in_swap",
                        severity="medium",
                        details={
                            "unexpected_tokens": delta.scope.unexpected_tokens,
                            "outflows": [c.to_dict() for c in outflow_unexpected],
                        }
                    )
                    return True, None, label
            return True, None, None
        
        # 非 swap 的资产操作
        # 检查涉及的 token 数量
        if delta.scope.affected_token_count > config.max_expected_token_count:
            # 检查是否有意外的 token 流出
            outflow_unexpected = [
                c for c in delta.asset_changes 
                if c.is_outflow and c.token_address in delta.scope.unexpected_tokens
            ]
            
            if outflow_unexpected:
                violation = InvariantViolation(
                    invariant_id=self.invariant_id,
                    message=f"单目标操作影响了 {delta.scope.affected_token_count} 个资产，"
                            f"其中 {len(outflow_unexpected)} 项意外流出",
                    evidence={
                        "target_contract": tx.to_address,
                        "affected_token_count": delta.scope.affected_token_count,
                        "unexpected_tokens": delta.scope.unexpected_tokens,
                        "unexpected_outflows": [c.to_dict() for c in outflow_unexpected],
                    }
                )
                return False, violation, None
        
        return True, None, None


class I4PathComplexity(Invariant):
    """
    I4: 路径合理性不变量（标签化，不拒绝）
    
    规则：简单目标不应触发异常复杂路径
    
    策略：作为风险标签输出，不做拒绝（除非 enable_path_rejection=True）
    """
    
    @property
    def invariant_id(self) -> InvariantId:
        return InvariantId.I4_PATH_COMPLEXITY
    
    @property
    def description(self) -> str:
        return "路径复杂度检查"
    
    def check(
        self,
        tx: TxInput,
        delta: DeltaS,
        config: InvariantConfig
    ) -> Tuple[bool, Optional[InvariantViolation], Optional[RiskLabel]]:
        # 没有路径信息，通过
        if not delta.path_shape:
            return True, None, None
        
        ps = delta.path_shape
        
        # 检查复杂度指标
        is_complex = (
            ps.max_call_depth >= config.high_call_depth_threshold or
            ps.delegate_call_count >= config.high_delegate_call_threshold
        )
        
        if not is_complex:
            return True, None, None
        
        # 构建风险标签
        details = {
            "max_call_depth": ps.max_call_depth,
            "delegate_call_count": ps.delegate_call_count,
            "internal_call_count": ps.internal_call_count,
            "unique_contracts_called": ps.unique_contracts_called,
        }
        
        severity = "high" if ps.delegate_call_count >= config.high_delegate_call_threshold else "medium"
        
        label = RiskLabel(
            label="high_path_complexity",
            severity=severity,
            details=details,
        )
        
        # 如果启用路径拒绝
        if config.enable_path_rejection:
            violation = InvariantViolation(
                invariant_id=self.invariant_id,
                message=f"执行路径复杂度异常（深度={ps.max_call_depth}, delegatecall={ps.delegate_call_count}）",
                evidence=details,
            )
            return False, violation, label
        
        # 默认只做标签
        return True, None, label


class InvariantEngine:
    """不变量裁决引擎"""
    
    def __init__(self, config: Optional[InvariantConfig] = None):
        self.config = config or DEFAULT_CONFIG.invariants
        
        # 注册所有不变量
        self.invariants: List[Invariant] = [
            I1NonAssetNoLoss(),
            I2NoUnlimitedPermission(),
            I3ScopeLocality(),
            I4PathComplexity(),
        ]
    
    def evaluate(
        self,
        tx: TxInput,
        delta: DeltaS,
        sim_meta: Optional[SimMeta] = None,
    ) -> GateDecision:
        """
        执行不变量裁决
        
        Args:
            tx: 交易输入
            delta: 状态变化
            sim_meta: 模拟元数据（可选）
        
        Returns:
            GateDecision 裁决结果
        """
        violations: List[InvariantViolation] = []
        risk_labels: List[RiskLabel] = []
        
        # 检查 fail-open 条件
        if sim_meta and sim_meta.fail_open:
            return GateDecision(
                decision=Decision.ALLOW,
                is_fail_open=True,
                fail_open_reason=sim_meta.fail_open_reason,
                fail_open_details=sim_meta.fail_open_details,
                tx_input=tx,
                delta_summary=delta.to_dict(),
                sim_meta=sim_meta,
            )
        
        # 逐一检查不变量
        for inv in self.invariants:
            try:
                passed, violation, label = inv.check(tx, delta, self.config)
                
                if not passed and violation:
                    violations.append(violation)
                    logger.info(f"Invariant {inv.invariant_id.value} violated: {violation.message}")
                
                if label:
                    risk_labels.append(label)
                    
            except Exception as e:
                # 不变量检查出错，记录但不拒绝（fail-open）
                logger.warning(f"Invariant {inv.invariant_id.value} check failed: {e}")
                risk_labels.append(RiskLabel(
                    label=f"invariant_check_error_{inv.invariant_id.value}",
                    severity="low",
                    details={"error": str(e)},
                ))
        
        # 确定最终决策
        decision = Decision.REJECT if violations else Decision.ALLOW
        
        return GateDecision(
            decision=decision,
            violations=violations,
            risk_labels=risk_labels,
            tx_input=tx,
            delta_summary=delta.to_dict(),
            sim_meta=sim_meta,
        )
    
    def evaluate_quick(
        self,
        tx: TxInput,
        delta: DeltaS,
    ) -> Tuple[Decision, List[str]]:
        """
        快速评估（简化输出）
        
        Returns:
            (Decision, [violated_invariant_ids])
        """
        result = self.evaluate(tx, delta)
        violated_ids = [v.invariant_id.value for v in result.violations]
        return result.decision, violated_ids


def evaluate_transaction(
    tx: TxInput,
    delta: DeltaS,
    sim_meta: Optional[SimMeta] = None,
    config: Optional[InvariantConfig] = None,
) -> GateDecision:
    """
    便捷函数：评估单笔交易
    """
    engine = InvariantEngine(config)
    return engine.evaluate(tx, delta, sim_meta)
