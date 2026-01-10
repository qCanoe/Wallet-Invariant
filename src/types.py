"""
Wallet Invariant MVP - Core Type Definitions

这个模块定义了 Wallet Invariant 系统的核心数据类型：
- TxInput: 交易输入规范化结构
- SimMeta: 模拟执行元数据
- DeltaS: 状态变化抽象结构（ΔAsset, ΔPermission, ΔScope, ΔPathShape）
- Decision: 准入裁决输出
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from decimal import Decimal


# ============================================================
# 交易分类枚举
# ============================================================

class TxCategory(Enum):
    """交易粗分类（基于启发式规则）"""
    ASSET_OP = "asset_op"           # 明显的资产操作（transfer/swap 等）
    PERMISSION_OP = "permission_op" # 明显的授权操作（approve/permit 等）
    NON_ASSET_OP = "non_asset_op"   # 其余（login/claim/mint 等）
    UNKNOWN = "unknown"             # 无法分类


class Decision(Enum):
    """准入裁决结果"""
    ALLOW = "allow"
    REJECT = "reject"


class FailOpenReason(Enum):
    """Fail-open 原因（模拟失败/不确定时允许的原因）"""
    SIMULATION_FAILED = "simulation_failed"         # 模拟执行失败
    RPC_ERROR = "rpc_error"                         # RPC 调用错误
    TRACE_UNAVAILABLE = "trace_unavailable"         # 无法获取 trace
    DELTA_EXTRACTION_FAILED = "delta_extraction_failed"  # ΔS 抽取失败
    INSUFFICIENT_EVIDENCE = "insufficient_evidence" # 证据不足
    TIMEOUT = "timeout"                             # 超时


class InvariantId(Enum):
    """不变量标识"""
    I1_NON_ASSET_NO_LOSS = "I1"   # 非资产行为不变量
    I2_NO_UNLIMITED_PERM = "I2"  # 权限比例不变量
    I3_SCOPE_LOCALITY = "I3"      # 作用域局部性不变量
    I4_PATH_COMPLEXITY = "I4"     # 路径合理性不变量（标签化）


# ============================================================
# TxInput: 交易输入与规范化
# ============================================================

@dataclass
class TxInput:
    """
    交易输入规范化结构
    
    支持两类输入：
    1. 真实交易回放：提供 tx_hash，系统拉取原始交易与 block_tag
    2. 候选交易：直接提供交易字段
    """
    # 链与区块信息
    chain_id: int
    block_tag: Optional[str] = None  # 区块号或 "latest"/"pending"
    
    # 交易基础字段
    from_address: str = ""           # 发起者地址（checksummed）
    to_address: Optional[str] = None # 目标地址（合约或 EOA）
    data: str = "0x"                 # calldata（十六进制）
    value: int = 0                   # ETH 数量（wei）
    
    # Gas 相关（可选）
    gas: Optional[int] = None
    max_fee_per_gas: Optional[int] = None
    max_priority_fee_per_gas: Optional[int] = None
    gas_price: Optional[int] = None
    
    # Nonce（可选）
    nonce: Optional[int] = None
    
    # 用于回放的 txHash（可选）
    tx_hash: Optional[str] = None
    
    # 元数据
    category: TxCategory = TxCategory.UNKNOWN
    
    def selector(self) -> Optional[str]:
        """提取函数选择器（前 4 字节）"""
        if self.data and len(self.data) >= 10:
            return self.data[:10].lower()
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "block_tag": self.block_tag,
            "from": self.from_address,
            "to": self.to_address,
            "data": self.data,
            "value": str(self.value),
            "gas": self.gas,
            "max_fee_per_gas": self.max_fee_per_gas,
            "max_priority_fee_per_gas": self.max_priority_fee_per_gas,
            "gas_price": self.gas_price,
            "nonce": self.nonce,
            "tx_hash": self.tx_hash,
            "category": self.category.value,
        }


# ============================================================
# SimMeta: 模拟执行元数据
# ============================================================

@dataclass
class SimMeta:
    """
    模拟执行元数据
    
    记录模拟执行的结果、日志、以及 fail-open 信息
    """
    # 执行结果
    success: bool                    # 是否执行成功（非 revert）
    return_data: str = "0x"          # 返回数据
    gas_used: Optional[int] = None   # 使用的 gas
    
    # 日志（用于 ΔS 抽取）
    logs: List[Dict[str, Any]] = field(default_factory=list)
    
    # Trace（可选，用于 ΔPathShape）
    trace: Optional[Dict[str, Any]] = None
    
    # Fail-open 信息
    fail_open: bool = False                           # 是否因失败而 fail-open
    fail_open_reason: Optional[FailOpenReason] = None # fail-open 原因
    fail_open_details: Optional[str] = None           # 详细错误信息
    
    # 元信息
    simulation_method: str = "eth_call"  # "eth_call" 或 "fork"
    block_number: Optional[int] = None   # 模拟所在区块号
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "return_data": self.return_data,
            "gas_used": self.gas_used,
            "logs_count": len(self.logs),
            "has_trace": self.trace is not None,
            "fail_open": self.fail_open,
            "fail_open_reason": self.fail_open_reason.value if self.fail_open_reason else None,
            "fail_open_details": self.fail_open_details,
            "simulation_method": self.simulation_method,
            "block_number": self.block_number,
        }


# ============================================================
# DeltaS: 状态变化抽象
# ============================================================

@dataclass
class AssetChange:
    """单个资产变化"""
    token_address: str              # 合约地址（ETH 为 "0x0000...0000"）
    token_type: str                 # "ETH" / "ERC20" / "ERC721" / "ERC1155"
    
    # 余额变化
    balance_before: int = 0
    balance_after: int = 0
    
    # NFT 特定字段
    token_id: Optional[int] = None  # ERC721/ERC1155 的 token ID
    
    @property
    def delta(self) -> int:
        """余额变化量（正为流入，负为流出）"""
        return self.balance_after - self.balance_before
    
    @property
    def is_outflow(self) -> bool:
        """是否为资产流出"""
        return self.delta < 0
    
    @property
    def is_inflow(self) -> bool:
        """是否为资产流入"""
        return self.delta > 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "token_type": self.token_type,
            "balance_before": str(self.balance_before),
            "balance_after": str(self.balance_after),
            "delta": str(self.delta),
            "token_id": self.token_id,
            "is_outflow": self.is_outflow,
            "is_inflow": self.is_inflow,
        }


@dataclass
class PermissionChange:
    """单个权限变化"""
    token_address: str              # 合约地址
    permission_type: str            # "allowance" / "approval_for_all"
    spender: str                    # 被授权地址
    
    # 权限值变化
    value_before: int = 0           # allowance 为数量，approval_for_all 为 0/1
    value_after: int = 0
    
    # 标记
    is_unlimited: bool = False      # 是否为无限授权（2^256-1 或接近）
    
    @property
    def delta(self) -> int:
        return self.value_after - self.value_before
    
    @property
    def is_new_permission(self) -> bool:
        """是否为新增权限（从 0 变为非 0）"""
        return self.value_before == 0 and self.value_after > 0
    
    @property
    def is_revocation(self) -> bool:
        """是否为撤销权限"""
        return self.value_before > 0 and self.value_after == 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "permission_type": self.permission_type,
            "spender": self.spender,
            "value_before": str(self.value_before),
            "value_after": str(self.value_after),
            "is_unlimited": self.is_unlimited,
            "is_new_permission": self.is_new_permission,
            "is_revocation": self.is_revocation,
        }


@dataclass
class DeltaScope:
    """作用域变化"""
    affected_token_count: int = 0           # 影响的 token 合约数量
    affected_accounts: List[str] = field(default_factory=list)  # 受影响账户
    unexpected_tokens: List[str] = field(default_factory=list)  # 与目标无关的 token
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "affected_token_count": self.affected_token_count,
            "affected_accounts_count": len(self.affected_accounts),
            "unexpected_tokens": self.unexpected_tokens,
        }


@dataclass
class DeltaPathShape:
    """路径形态特征（可选）"""
    max_call_depth: int = 0                 # 最大调用深度
    delegate_call_count: int = 0            # delegatecall 次数
    internal_call_count: int = 0            # 内部调用总数
    unique_contracts_called: int = 0        # 调用的唯一合约数
    
    # 风险标签
    is_high_complexity: bool = False        # 是否为高复杂度
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_call_depth": self.max_call_depth,
            "delegate_call_count": self.delegate_call_count,
            "internal_call_count": self.internal_call_count,
            "unique_contracts_called": self.unique_contracts_called,
            "is_high_complexity": self.is_high_complexity,
        }


@dataclass
class DeltaS:
    """
    状态变化抽象（ΔS）
    
    把"执行前后世界变化"压缩成钱包关心的低维表示
    """
    # 用户地址
    user_address: str
    
    # ΔAsset: 资产变化
    asset_changes: List[AssetChange] = field(default_factory=list)
    
    # ΔPermission: 权限变化
    permission_changes: List[PermissionChange] = field(default_factory=list)
    
    # ΔScope: 作用域
    scope: DeltaScope = field(default_factory=DeltaScope)
    
    # ΔPathShape: 路径形态（可选）
    path_shape: Optional[DeltaPathShape] = None
    
    # 聚合指标
    @property
    def total_outflow(self) -> int:
        """总资产流出量（所有 token 的 wei 值之和，不考虑价格）"""
        return sum(-c.delta for c in self.asset_changes if c.is_outflow)
    
    @property
    def has_outflow(self) -> bool:
        """是否有任何资产流出"""
        return any(c.is_outflow for c in self.asset_changes)
    
    @property
    def has_new_unlimited_permission(self) -> bool:
        """是否有新的无限授权"""
        return any(
            p.is_new_permission and p.is_unlimited 
            for p in self.permission_changes
        )
    
    @property
    def has_new_approval_for_all(self) -> bool:
        """是否有新的 approval for all"""
        return any(
            p.permission_type == "approval_for_all" and p.is_new_permission
            for p in self.permission_changes
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_address": self.user_address,
            "asset_changes": [c.to_dict() for c in self.asset_changes],
            "permission_changes": [p.to_dict() for p in self.permission_changes],
            "scope": self.scope.to_dict(),
            "path_shape": self.path_shape.to_dict() if self.path_shape else None,
            "summary": {
                "total_outflow": str(self.total_outflow),
                "has_outflow": self.has_outflow,
                "has_new_unlimited_permission": self.has_new_unlimited_permission,
                "has_new_approval_for_all": self.has_new_approval_for_all,
            }
        }


# ============================================================
# GateDecision: 准入裁决输出
# ============================================================

@dataclass
class InvariantViolation:
    """不变量违规记录"""
    invariant_id: InvariantId
    message: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "invariant_id": self.invariant_id.value,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass 
class RiskLabel:
    """风险标签（非拒绝级别的警告）"""
    label: str
    severity: str  # "low" / "medium" / "high"
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "severity": self.severity,
            "details": self.details,
        }


@dataclass
class GateDecision:
    """
    准入裁决输出
    
    完整的裁决结果，包含决策、违规记录、证据摘要
    """
    # 决策结果
    decision: Decision
    
    # 违规记录（如果 REJECT）
    violations: List[InvariantViolation] = field(default_factory=list)
    
    # 风险标签（非拒绝级别）
    risk_labels: List[RiskLabel] = field(default_factory=list)
    
    # Fail-open 信息
    is_fail_open: bool = False
    fail_open_reason: Optional[FailOpenReason] = None
    fail_open_details: Optional[str] = None
    
    # 输入与状态摘要
    tx_input: Optional[TxInput] = None
    delta_summary: Optional[Dict[str, Any]] = None
    sim_meta: Optional[SimMeta] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "violations": [v.to_dict() for v in self.violations],
            "risk_labels": [r.to_dict() for r in self.risk_labels],
            "is_fail_open": self.is_fail_open,
            "fail_open_reason": self.fail_open_reason.value if self.fail_open_reason else None,
            "fail_open_details": self.fail_open_details,
            "tx_input": self.tx_input.to_dict() if self.tx_input else None,
            "delta_summary": self.delta_summary,
            "sim_meta": self.sim_meta.to_dict() if self.sim_meta else None,
        }
    
    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ============================================================
# 常量与阈值
# ============================================================

# ETH 地址常量
ETH_ADDRESS = "0x0000000000000000000000000000000000000000"

# 无限授权阈值（2^256 - 1）
UNLIMITED_ALLOWANCE = 2**256 - 1

# 接近无限授权的阈值（大于 2^200 视为无限）
NEAR_UNLIMITED_THRESHOLD = 2**200

# 路径复杂度阈值
HIGH_CALL_DEPTH_THRESHOLD = 10
HIGH_DELEGATE_CALL_THRESHOLD = 5

# 作用域阈值
MAX_EXPECTED_TOKEN_COUNT = 2  # 单目标操作预期最多影响的 token 数


def is_unlimited_allowance(value: int) -> bool:
    """判断是否为无限授权"""
    return value >= NEAR_UNLIMITED_THRESHOLD
