"""
Wallet Invariant MVP - ΔS 抽取器

从模拟执行结果中抽取状态变化：
- ΔAsset: 资产变化（ETH + ERC20 + ERC721 + ERC1155）
- ΔPermission: 权限变化（allowance + approvalForAll）
- ΔScope: 作用域（影响的 token/账户数量）
- ΔPathShape: 路径形态（调用深度/delegatecall）
"""

import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from eth_abi import decode

from .types import (
    TxInput,
    SimMeta,
    DeltaS,
    AssetChange,
    PermissionChange,
    DeltaScope,
    DeltaPathShape,
    ETH_ADDRESS,
    is_unlimited_allowance,
)
from .constants import (
    TOPIC_ERC20_TRANSFER,
    TOPIC_ERC20_APPROVAL,
    TOPIC_APPROVAL_FOR_ALL,
    TOPIC_ERC1155_TRANSFER_SINGLE,
    TOPIC_ERC1155_TRANSFER_BATCH,
)
from .simulator import Simulator, SimulatorConfig

logger = logging.getLogger(__name__)


def _decode_address(hex_str: str) -> str:
    """从 32 字节 topic 解码地址"""
    if not hex_str:
        return ""
    # 去掉前缀和前导零
    hex_clean = hex_str.lower().replace("0x", "")
    # 取最后 40 个字符（20 字节）
    addr = hex_clean[-40:]
    return f"0x{addr}"


def _decode_uint256(hex_str: str) -> int:
    """解码 uint256"""
    if not hex_str:
        return 0
    return int(hex_str, 16)


def _parse_log_topics(log: Dict[str, Any]) -> Tuple[str, List[str]]:
    """解析日志的 topics"""
    topics = log.get("topics", [])
    if not topics:
        return "", []
    
    event_sig = topics[0].lower() if topics else ""
    indexed_topics = [t.lower() for t in topics[1:]] if len(topics) > 1 else []
    
    return event_sig, indexed_topics


class DeltaExtractor:
    """ΔS 抽取器"""
    
    def __init__(self, simulator: Optional[Simulator] = None):
        self.simulator = simulator
    
    def extract_from_logs(
        self,
        logs: List[Dict[str, Any]],
        user_address: str,
        tx: Optional[TxInput] = None
    ) -> DeltaS:
        """
        从日志中抽取 ΔS
        
        Args:
            logs: 交易日志列表
            user_address: 用户地址（用于判断流入/流出）
            tx: 交易输入（可选，用于补充信息）
        
        Returns:
            DeltaS 状态变化抽象
        """
        user_addr = user_address.lower()
        
        asset_changes: List[AssetChange] = []
        permission_changes: List[PermissionChange] = []
        affected_tokens: Set[str] = set()
        affected_accounts: Set[str] = set()
        
        for log in logs:
            event_sig, indexed = _parse_log_topics(log)
            
            # ERC20/ERC721 Transfer 事件
            if event_sig == TOPIC_ERC20_TRANSFER.lower():
                change = self._parse_transfer_event(log, user_addr)
                if change:
                    asset_changes.append(change)
                    affected_tokens.add(change.token_address)
                    # 记录受影响账户
                    if len(indexed) >= 2:
                        affected_accounts.add(_decode_address(indexed[0]))
                        affected_accounts.add(_decode_address(indexed[1]))
            
            # ERC20 Approval 事件
            elif event_sig == TOPIC_ERC20_APPROVAL.lower():
                permission_change = self._parse_approval_event(log, user_addr)
                if permission_change:
                    permission_changes.append(permission_change)
                    affected_tokens.add(permission_change.token_address)
            
            # ERC721/ERC1155 ApprovalForAll 事件
            elif event_sig == TOPIC_APPROVAL_FOR_ALL.lower():
                permission_change = self._parse_approval_for_all_event(log, user_addr)
                if permission_change:
                    permission_changes.append(permission_change)
                    affected_tokens.add(permission_change.token_address)
            
            # ERC1155 TransferSingle 事件
            elif event_sig == TOPIC_ERC1155_TRANSFER_SINGLE.lower():
                change = self._parse_erc1155_transfer_single(log, user_addr)
                if change:
                    asset_changes.append(change)
                    affected_tokens.add(change.token_address)
            
            # ERC1155 TransferBatch 事件
            elif event_sig == TOPIC_ERC1155_TRANSFER_BATCH.lower():
                changes = self._parse_erc1155_transfer_batch(log, user_addr)
                asset_changes.extend(changes)
                for c in changes:
                    affected_tokens.add(c.token_address)
        
        # 处理 ETH 转移（从 tx.value）
        if tx and tx.value > 0:
            eth_change = AssetChange(
                token_address=ETH_ADDRESS,
                token_type="ETH",
                balance_before=tx.value,  # 发送者减少
                balance_after=0,
            )
            asset_changes.append(eth_change)
            affected_tokens.add(ETH_ADDRESS)
        
        # 构建 ΔScope
        # 确定"意外"token：与交易目标无关的 token
        expected_tokens = set()
        if tx and tx.to_address:
            expected_tokens.add(tx.to_address.lower())
        unexpected = [t for t in affected_tokens if t not in expected_tokens and t != ETH_ADDRESS]
        
        scope = DeltaScope(
            affected_token_count=len(affected_tokens),
            affected_accounts=list(affected_accounts),
            unexpected_tokens=unexpected,
        )
        
        return DeltaS(
            user_address=user_address,
            asset_changes=asset_changes,
            permission_changes=permission_changes,
            scope=scope,
        )
    
    def _parse_transfer_event(
        self, 
        log: Dict[str, Any], 
        user_addr: str
    ) -> Optional[AssetChange]:
        """解析 Transfer 事件"""
        _, indexed = _parse_log_topics(log)
        contract_addr = log.get("address", "").lower()
        data = log.get("data", "0x")
        
        if len(indexed) < 2:
            return None
        
        from_addr = _decode_address(indexed[0])
        to_addr = _decode_address(indexed[1])
        
        # 检查用户是否参与
        if user_addr not in (from_addr, to_addr):
            return None
        
        # 解析金额/tokenId
        # ERC20: data 是 uint256 value
        # ERC721: indexed[2] 是 tokenId（如果有）或 data 是 tokenId
        
        value = 0
        token_id = None
        token_type = "ERC20"  # 默认假设 ERC20
        
        if len(indexed) >= 3:
            # ERC721: tokenId 在 indexed[2]
            token_id = _decode_uint256(indexed[2])
            token_type = "ERC721"
            value = 1  # NFT 数量为 1
        elif data and data != "0x":
            # ERC20: value 在 data
            value = _decode_uint256(data)
        
        # 计算 before/after（从用户视角）
        if user_addr == from_addr:
            # 用户发出
            balance_before = value
            balance_after = 0
        else:
            # 用户收到
            balance_before = 0
            balance_after = value
        
        return AssetChange(
            token_address=contract_addr,
            token_type=token_type,
            balance_before=balance_before,
            balance_after=balance_after,
            token_id=token_id,
        )
    
    def _parse_approval_event(
        self, 
        log: Dict[str, Any], 
        user_addr: str
    ) -> Optional[PermissionChange]:
        """解析 Approval 事件（ERC20）"""
        _, indexed = _parse_log_topics(log)
        contract_addr = log.get("address", "").lower()
        data = log.get("data", "0x")
        
        if len(indexed) < 2:
            return None
        
        owner = _decode_address(indexed[0])
        spender = _decode_address(indexed[1])
        
        # 只关心用户作为 owner 的授权
        if user_addr != owner:
            return None
        
        # 解析授权值
        value = _decode_uint256(data) if data and data != "0x" else 0
        
        return PermissionChange(
            token_address=contract_addr,
            permission_type="allowance",
            spender=spender,
            value_before=0,  # 从日志无法得知 before，默认为 0
            value_after=value,
            is_unlimited=is_unlimited_allowance(value),
        )
    
    def _parse_approval_for_all_event(
        self, 
        log: Dict[str, Any], 
        user_addr: str
    ) -> Optional[PermissionChange]:
        """解析 ApprovalForAll 事件"""
        _, indexed = _parse_log_topics(log)
        contract_addr = log.get("address", "").lower()
        data = log.get("data", "0x")
        
        if len(indexed) < 2:
            return None
        
        owner = _decode_address(indexed[0])
        operator = _decode_address(indexed[1])
        
        # 只关心用户作为 owner 的授权
        if user_addr != owner:
            return None
        
        # 解析 approved (bool)
        approved = False
        if data and data != "0x":
            # bool 在 data 中
            approved = _decode_uint256(data) != 0
        
        return PermissionChange(
            token_address=contract_addr,
            permission_type="approval_for_all",
            spender=operator,
            value_before=0,  # 假设之前未授权
            value_after=1 if approved else 0,
            is_unlimited=approved,  # approval_for_all 等同于无限授权
        )
    
    def _parse_erc1155_transfer_single(
        self, 
        log: Dict[str, Any], 
        user_addr: str
    ) -> Optional[AssetChange]:
        """解析 ERC1155 TransferSingle 事件"""
        _, indexed = _parse_log_topics(log)
        contract_addr = log.get("address", "").lower()
        data = log.get("data", "0x")
        
        if len(indexed) < 3:
            return None
        
        # operator = _decode_address(indexed[0])
        from_addr = _decode_address(indexed[1])
        to_addr = _decode_address(indexed[2])
        
        if user_addr not in (from_addr, to_addr):
            return None
        
        # data: (uint256 id, uint256 value)
        if data and data != "0x" and len(data) >= 130:  # 0x + 64 + 64
            try:
                decoded = decode(["uint256", "uint256"], bytes.fromhex(data[2:]))
                token_id, value = decoded
            except Exception:
                return None
        else:
            return None
        
        if user_addr == from_addr:
            balance_before = value
            balance_after = 0
        else:
            balance_before = 0
            balance_after = value
        
        return AssetChange(
            token_address=contract_addr,
            token_type="ERC1155",
            balance_before=balance_before,
            balance_after=balance_after,
            token_id=token_id,
        )
    
    def _parse_erc1155_transfer_batch(
        self, 
        log: Dict[str, Any], 
        user_addr: str
    ) -> List[AssetChange]:
        """解析 ERC1155 TransferBatch 事件"""
        _, indexed = _parse_log_topics(log)
        contract_addr = log.get("address", "").lower()
        data = log.get("data", "0x")
        
        changes: List[AssetChange] = []
        
        if len(indexed) < 3:
            return changes
        
        from_addr = _decode_address(indexed[1])
        to_addr = _decode_address(indexed[2])
        
        if user_addr not in (from_addr, to_addr):
            return changes
        
        # data: (uint256[] ids, uint256[] values)
        if data and data != "0x":
            try:
                decoded = decode(["uint256[]", "uint256[]"], bytes.fromhex(data[2:]))
                ids, values = decoded
                
                for token_id, value in zip(ids, values):
                    if user_addr == from_addr:
                        balance_before = value
                        balance_after = 0
                    else:
                        balance_before = 0
                        balance_after = value
                    
                    changes.append(AssetChange(
                        token_address=contract_addr,
                        token_type="ERC1155",
                        balance_before=balance_before,
                        balance_after=balance_after,
                        token_id=token_id,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse TransferBatch: {e}")
        
        return changes
    
    def extract_path_shape(self, trace: Optional[Dict[str, Any]]) -> Optional[DeltaPathShape]:
        """
        从 trace 中抽取路径形态
        
        Args:
            trace: debug_traceTransaction 返回的 callTracer 结果
        
        Returns:
            DeltaPathShape 或 None（如果无法解析）
        """
        if not trace:
            return None
        
        try:
            max_depth = 0
            delegate_count = 0
            internal_count = 0
            contracts: Set[str] = set()
            
            def traverse(node: Dict[str, Any], depth: int = 0):
                nonlocal max_depth, delegate_count, internal_count
                
                max_depth = max(max_depth, depth)
                
                call_type = node.get("type", "").upper()
                if call_type == "DELEGATECALL":
                    delegate_count += 1
                
                if "to" in node:
                    contracts.add(node["to"].lower())
                
                calls = node.get("calls", [])
                internal_count += len(calls)
                
                for call in calls:
                    traverse(call, depth + 1)
            
            traverse(trace)
            
            # 判断是否高复杂度
            is_high = (
                max_depth >= 10 or 
                delegate_count >= 5 or 
                len(contracts) >= 20
            )
            
            return DeltaPathShape(
                max_call_depth=max_depth,
                delegate_call_count=delegate_count,
                internal_call_count=internal_count,
                unique_contracts_called=len(contracts),
                is_high_complexity=is_high,
            )
        
        except Exception as e:
            logger.debug(f"Failed to extract path shape: {e}")
            return None
    
    def extract(
        self,
        tx: TxInput,
        sim_meta: SimMeta,
    ) -> DeltaS:
        """
        完整的 ΔS 抽取
        
        Args:
            tx: 交易输入
            sim_meta: 模拟执行元数据
        
        Returns:
            完整的 DeltaS
        """
        # 从日志抽取资产和权限变化
        delta = self.extract_from_logs(
            logs=sim_meta.logs,
            user_address=tx.from_address,
            tx=tx,
        )
        
        # 从 trace 抽取路径形态（如果有）
        if sim_meta.trace:
            delta.path_shape = self.extract_path_shape(sim_meta.trace)
        
        return delta


async def extract_delta_for_tx(
    tx_hash: str,
    rpc_url: str,
    enable_trace: bool = False
) -> Tuple[TxInput, SimMeta, DeltaS]:
    """
    便捷函数：为指定交易抽取 ΔS
    
    Args:
        tx_hash: 交易哈希
        rpc_url: RPC URL
        enable_trace: 是否获取 trace
    
    Returns:
        (TxInput, SimMeta, DeltaS)
    """
    from .simulator import Simulator
    
    config = SimulatorConfig(rpc_url=rpc_url, enable_trace=enable_trace)
    simulator = Simulator(config)
    extractor = DeltaExtractor(simulator)
    
    # 获取交易信息
    tx_input = await simulator.fetch_tx_input(tx_hash)
    if not tx_input:
        raise ValueError(f"Transaction not found: {tx_hash}")
    
    # 模拟执行
    sim_meta = await simulator.simulate(tx_input)
    
    # 抽取 ΔS
    delta = extractor.extract(tx_input, sim_meta)
    
    return tx_input, sim_meta, delta
