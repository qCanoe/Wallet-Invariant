"""
Wallet Invariant MVP - 常量与函数选择器定义
"""

# ============================================================
# 常用函数选择器（4 bytes）
# ============================================================

# ERC20 标准
SELECTOR_TRANSFER = "0xa9059cbb"           # transfer(address,uint256)
SELECTOR_TRANSFER_FROM = "0x23b872dd"      # transferFrom(address,address,uint256)
SELECTOR_APPROVE = "0x095ea7b3"            # approve(address,uint256)
SELECTOR_BALANCE_OF = "0x70a08231"         # balanceOf(address)
SELECTOR_ALLOWANCE = "0xdd62ed3e"          # allowance(address,address)

# ERC721 标准
SELECTOR_SAFE_TRANSFER_FROM_721 = "0x42842e0e"  # safeTransferFrom(address,address,uint256)
SELECTOR_SAFE_TRANSFER_FROM_721_DATA = "0xb88d4fde"  # safeTransferFrom(address,address,uint256,bytes)
SELECTOR_SET_APPROVAL_FOR_ALL = "0xa22cb465"    # setApprovalForAll(address,bool)
SELECTOR_IS_APPROVED_FOR_ALL = "0xe985e9c5"     # isApprovedForAll(address,address)
SELECTOR_OWNER_OF = "0x6352211e"                # ownerOf(uint256)

# ERC1155 标准
SELECTOR_SAFE_TRANSFER_FROM_1155 = "0xf242432a"  # safeTransferFrom(address,address,uint256,uint256,bytes)
SELECTOR_SAFE_BATCH_TRANSFER_FROM = "0x2eb2c2d6"  # safeBatchTransferFrom(...)
SELECTOR_BALANCE_OF_1155 = "0x00fdd58e"          # balanceOf(address,uint256)

# Permit / Permit2
SELECTOR_PERMIT = "0xd505accf"             # permit(address,address,uint256,uint256,uint8,bytes32,bytes32)
SELECTOR_PERMIT2_PERMIT = "0x2a2d80d1"     # permit(...)
SELECTOR_PERMIT2_TRANSFER_FROM = "0x36c78516"  # transferFrom(...)
SELECTOR_PERMIT2_PERMIT_BATCH = "0x4bdb7453"   # permitBatch(address,(address,uint160,uint48,uint48)[],uint256,bytes)
SELECTOR_PERMIT2_PERMIT_SINGLE = "0x44d46566"  # permitSingle(address,(address,uint160,uint48,uint48),uint256,bytes)
SELECTOR_PERMIT2_PERMIT_AND_TRANSFER = "0x0d58b1db"  # permitAndTransferFrom(address,(address,uint160,uint48,uint48),address,uint256,uint256,bytes)

# DEX / Swap 相关
SELECTOR_SWAP_EXACT_TOKENS = "0x38ed1739"  # swapExactTokensForTokens
SELECTOR_SWAP_TOKENS_EXACT = "0x8803dbee"  # swapTokensForExactTokens
SELECTOR_SWAP_EXACT_ETH = "0x7ff36ab5"     # swapExactETHForTokens
SELECTOR_SWAP_ETH_EXACT = "0xfb3bdb41"     # swapETHForExactTokens
SELECTOR_MULTICALL = "0xac9650d8"          # multicall(bytes[])
SELECTOR_EXECUTE = "0x3593564c"            # execute(bytes,bytes[],uint256) - Universal Router


# ============================================================
# 事件 Topic（keccak256 哈希）
# ============================================================

# ERC20 Transfer(address indexed from, address indexed to, uint256 value)
TOPIC_ERC20_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# ERC20 Approval(address indexed owner, address indexed spender, uint256 value)
TOPIC_ERC20_APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"

# ERC721/ERC1155 ApprovalForAll(address indexed owner, address indexed operator, bool approved)
TOPIC_APPROVAL_FOR_ALL = "0x17307eab39ab6107e8899845ad3d59bd9653f200f220920489ca2b5937696c31"

# ERC1155 TransferSingle(address indexed operator, address indexed from, address indexed to, uint256 id, uint256 value)
TOPIC_ERC1155_TRANSFER_SINGLE = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"

# ERC1155 TransferBatch(address indexed operator, address indexed from, address indexed to, uint256[] ids, uint256[] values)
TOPIC_ERC1155_TRANSFER_BATCH = "0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb"


# ============================================================
# 分类选择器集合
# ============================================================

# 明确的资产转移操作
ASSET_OP_SELECTORS = {
    SELECTOR_TRANSFER,
    SELECTOR_TRANSFER_FROM,
    SELECTOR_SAFE_TRANSFER_FROM_721,
    SELECTOR_SAFE_TRANSFER_FROM_721_DATA,
    SELECTOR_SAFE_TRANSFER_FROM_1155,
    SELECTOR_SAFE_BATCH_TRANSFER_FROM,
    SELECTOR_SWAP_EXACT_TOKENS,
    SELECTOR_SWAP_TOKENS_EXACT,
    SELECTOR_SWAP_EXACT_ETH,
    SELECTOR_SWAP_ETH_EXACT,
    SELECTOR_PERMIT2_TRANSFER_FROM,
}

# 明确的授权操作
PERMISSION_OP_SELECTORS = {
    SELECTOR_APPROVE,
    SELECTOR_SET_APPROVAL_FOR_ALL,
    SELECTOR_PERMIT,
    SELECTOR_PERMIT2_PERMIT,
    SELECTOR_PERMIT2_PERMIT_BATCH,
    SELECTOR_PERMIT2_PERMIT_SINGLE,
    SELECTOR_PERMIT2_PERMIT_AND_TRANSFER,
}

# 可能包含多种操作的复合调用（需要更谨慎处理）
COMPOSITE_OP_SELECTORS = {
    SELECTOR_MULTICALL,
    SELECTOR_EXECUTE,
}
