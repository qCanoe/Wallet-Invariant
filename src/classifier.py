"""
Wallet Invariant MVP - 交易粗分类器

基于启发式规则对交易进行分类：
- AssetOp: 明显的资产操作（transfer/swap 等）
- PermissionOp: 明显的授权操作（approve/permit 等）
- NonAssetOp: 其余（login/claim/mint 等）
"""

from typing import Optional
from .types import TxInput, TxCategory
from .constants import (
    ASSET_OP_SELECTORS,
    PERMISSION_OP_SELECTORS,
    COMPOSITE_OP_SELECTORS,
)


def classify_transaction(tx: TxInput) -> TxCategory:
    """
    对交易进行粗分类
    
    分类逻辑（按优先级）：
    1. 如果 selector 在 PERMISSION_OP_SELECTORS → PermissionOp
    2. 如果 selector 在 ASSET_OP_SELECTORS → AssetOp
    3. 如果 value > 0（发送 ETH）→ AssetOp
    4. 如果 to 为空（合约创建）→ NonAssetOp
    5. 如果 selector 在 COMPOSITE_OP_SELECTORS → AssetOp（保守处理）
    6. 其余 → NonAssetOp
    
    Args:
        tx: 交易输入
        
    Returns:
        交易分类
    """
    selector = tx.selector()
    
    # 规则 1: 明确的授权操作
    if selector and selector.lower() in PERMISSION_OP_SELECTORS:
        return TxCategory.PERMISSION_OP
    
    # 规则 2: 明确的资产转移操作
    if selector and selector.lower() in ASSET_OP_SELECTORS:
        return TxCategory.ASSET_OP
    
    # 规则 3: 发送 ETH 视为资产操作
    if tx.value > 0:
        return TxCategory.ASSET_OP
    
    # 规则 4: 合约创建
    if tx.to_address is None or tx.to_address == "":
        return TxCategory.NON_ASSET_OP
    
    # 规则 5: 复合调用保守处理为资产操作
    if selector and selector.lower() in COMPOSITE_OP_SELECTORS:
        return TxCategory.ASSET_OP
    
    # 规则 6: 默认为非资产操作
    return TxCategory.NON_ASSET_OP


def is_likely_swap(tx: TxInput) -> bool:
    """
    判断交易是否可能是 swap 操作
    
    用于 I3 不变量：swap 允许涉及多个 token
    """
    selector = tx.selector()
    if not selector:
        return False
    
    swap_selectors = {
        "0x38ed1739",  # swapExactTokensForTokens
        "0x8803dbee",  # swapTokensForExactTokens
        "0x7ff36ab5",  # swapExactETHForTokens
        "0xfb3bdb41",  # swapETHForExactTokens
        "0x5c11d795",  # swapExactTokensForTokensSupportingFeeOnTransferTokens
        "0xb6f9de95",  # swapExactETHForTokensSupportingFeeOnTransferTokens
        "0x3593564c",  # execute (Universal Router)
        "0xac9650d8",  # multicall
    }
    
    return selector.lower() in swap_selectors


def get_category_description(category: TxCategory) -> str:
    """获取分类的人类可读描述"""
    descriptions = {
        TxCategory.ASSET_OP: "资产操作（转账/交换）",
        TxCategory.PERMISSION_OP: "授权操作（approve/permit）",
        TxCategory.NON_ASSET_OP: "非资产操作（登录/claim 等）",
        TxCategory.UNKNOWN: "未知分类",
    }
    return descriptions.get(category, "未知")
