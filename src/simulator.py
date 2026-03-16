"""
Wallet Invariant MVP - 预执行模拟器

支持两种模式：
1. eth_call：在指定 blockTag 上执行交易模拟
2. fork：使用本地 fork（anvil/hardhat）执行模拟

主要功能：
- 从 txHash 获取交易信息并重放
- 模拟交易执行并收集日志
- 获取 trace（如节点支持）
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple

from .types import TxInput, SimMeta, FailOpenReason
from .config import SimulatorConfig, DEFAULT_CONFIG
from .classifier import classify_transaction

logger = logging.getLogger(__name__)


class RPCClient:
    """简单的 JSON-RPC 客户端"""
    
    def __init__(self, rpc_url: str, timeout: int = 30):
        self.rpc_url = rpc_url
        self.timeout = timeout
        self._request_id = 0
    
    async def call(self, method: str, params: List[Any]) -> Any:
        """执行 JSON-RPC 调用"""
        import httpx
        
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._request_id,
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
        
        if "error" in result:
            raise RPCError(result["error"].get("message", "Unknown RPC error"))
        
        return result.get("result")
    
    async def batch_call(self, requests: List[Tuple[str, List[Any]]]) -> List[Any]:
        """批量 JSON-RPC 调用"""
        import httpx
        
        payloads = []
        for method, params in requests:
            self._request_id += 1
            payloads.append({
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": self._request_id,
            })
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.rpc_url,
                json=payloads,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            results = response.json()
        
        # 按 id 排序确保顺序
        results.sort(key=lambda x: x.get("id", 0))
        return [r.get("result") for r in results]


class RPCError(Exception):
    """RPC 调用错误"""
    pass


class Simulator:
    """交易模拟器"""
    
    def __init__(self, config: Optional[SimulatorConfig] = None):
        self.config = config or DEFAULT_CONFIG.simulator
        self._client: Optional[RPCClient] = None
    
    @property
    def client(self) -> RPCClient:
        if self._client is None:
            if not self.config.rpc_url:
                raise ValueError("RPC URL not configured")
            self._client = RPCClient(self.config.rpc_url, self.config.timeout)
        return self._client
    
    async def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """
        通过 txHash 获取交易信息
        
        Returns:
            交易数据，包含 from/to/data/value/gas 等字段
        """
        try:
            tx_data = await self.client.call("eth_getTransactionByHash", [tx_hash])
            if tx_data is None:
                return None
            if isinstance(tx_data, dict):
                return tx_data
            logger.warning(f"Unexpected transaction payload type for {tx_hash}: {type(tx_data)}")
            return None
        except Exception as e:
            logger.warning(f"Failed to get transaction {tx_hash}: {e}")
            return None
    
    async def get_transaction_receipt(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """获取交易收据（包含日志）"""
        try:
            receipt = await self.client.call("eth_getTransactionReceipt", [tx_hash])
            if receipt is None:
                return None
            if isinstance(receipt, dict):
                return receipt
            logger.warning(f"Unexpected receipt payload type for {tx_hash}: {type(receipt)}")
            return None
        except Exception as e:
            logger.warning(f"Failed to get receipt {tx_hash}: {e}")
            return None
    
    async def get_block_number(self) -> int:
        """获取当前区块号"""
        result = await self.client.call("eth_blockNumber", [])
        return int(result, 16)
    
    async def fetch_tx_input(self, tx_hash: str) -> Optional[TxInput]:
        """
        从 txHash 构造 TxInput
        
        包含交易所在区块作为 block_tag
        """
        tx_data = await self.get_transaction(tx_hash)
        if not tx_data:
            return None
        
        # 获取链 ID
        chain_id = 1  # 默认主网
        if "chainId" in tx_data and tx_data["chainId"]:
            chain_id = int(tx_data["chainId"], 16)
        
        # 构造 TxInput
        tx_input = TxInput(
            chain_id=chain_id,
            block_tag=tx_data.get("blockNumber"),
            from_address=tx_data.get("from", ""),
            to_address=tx_data.get("to"),
            data=tx_data.get("input", "0x"),
            value=int(tx_data.get("value", "0x0"), 16),
            gas=int(tx_data.get("gas", "0x0"), 16) if tx_data.get("gas") else None,
            gas_price=int(tx_data.get("gasPrice", "0x0"), 16) if tx_data.get("gasPrice") else None,
            nonce=int(tx_data.get("nonce", "0x0"), 16) if tx_data.get("nonce") else None,
            tx_hash=tx_hash,
        )
        
        # 分类
        tx_input.category = classify_transaction(tx_input)
        
        return tx_input
    
    async def simulate(self, tx: TxInput) -> SimMeta:
        """
        模拟交易执行
        
        使用 eth_call 在指定 block 上执行，并获取日志
        """
        # 确定 block tag
        block_tag = tx.block_tag or "latest"
        
        # 如果是历史交易，使用前一个区块进行模拟（执行前状态）
        block_number = None
        if block_tag != "latest" and block_tag != "pending":
            block_number = int(block_tag, 16) if block_tag.startswith("0x") else int(block_tag)
            # 使用前一个区块，模拟执行前状态
            sim_block_tag = hex(block_number - 1)
        else:
            sim_block_tag = block_tag
        
        # 构造 eth_call 参数
        call_params = {
            "from": tx.from_address,
            "to": tx.to_address,
            "data": tx.data,
            "value": hex(tx.value),
        }
        if tx.gas:
            call_params["gas"] = hex(tx.gas)
        
        try:
            # 执行 eth_call
            return_data = await self.client.call("eth_call", [call_params, sim_block_tag])
            
            # 尝试获取日志（对于历史交易，从 receipt 获取）
            logs = []
            if tx.tx_hash:
                receipt = await self.get_transaction_receipt(tx.tx_hash)
                if receipt and "logs" in receipt:
                    logs = receipt["logs"]
            
            # 尝试获取 trace（如果启用且节点支持）
            trace = None
            if self.config.enable_trace and tx.tx_hash:
                trace = await self._get_trace(tx.tx_hash)
            
            return SimMeta(
                success=True,
                return_data=return_data or "0x",
                logs=logs,
                trace=trace,
                simulation_method="eth_call",
                block_number=block_number,
            )
            
        except RPCError as e:
            error_msg = str(e)
            # 检查是否是 revert
            if "revert" in error_msg.lower() or "execution reverted" in error_msg.lower():
                return SimMeta(
                    success=False,
                    return_data="0x",
                    simulation_method="eth_call",
                    block_number=block_number,
                )
            
            # 其他 RPC 错误，fail-open
            logger.warning(f"Simulation RPC error: {e}")
            return SimMeta(
                success=True,  # fail-open: 允许
                fail_open=True,
                fail_open_reason=FailOpenReason.RPC_ERROR,
                fail_open_details=error_msg,
                simulation_method="eth_call",
                block_number=block_number,
            )
            
        except Exception as e:
            # 未预期错误，fail-open
            logger.error(f"Simulation failed: {e}")
            return SimMeta(
                success=True,  # fail-open: 允许
                fail_open=True,
                fail_open_reason=FailOpenReason.SIMULATION_FAILED,
                fail_open_details=str(e),
                simulation_method="eth_call",
                block_number=block_number,
            )
    
    async def _get_trace(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """获取交易 trace（需要节点支持 debug_traceTransaction）"""
        try:
            trace = await self.client.call(
                "debug_traceTransaction",
                [tx_hash, {"tracer": "callTracer"}]
            )
            if trace is None:
                return None
            if isinstance(trace, dict):
                return trace
            logger.debug(f"Unexpected trace payload type for {tx_hash}: {type(trace)}")
            return None
        except Exception as e:
            logger.debug(f"Failed to get trace for {tx_hash}: {e}")
            return None
    
    async def simulate_and_compare(
        self, 
        tx: TxInput,
        queries: List[Tuple[str, List[Any]]]
    ) -> Tuple[SimMeta, Dict[str, Tuple[Any, Any]]]:
        """
        模拟交易并比较状态变化
        
        Args:
            tx: 交易输入
            queries: 要比较的查询列表，格式为 [(method, params), ...]
                     通常是 eth_call 查询 balanceOf/allowance 等
        
        Returns:
            (SimMeta, {query_key: (before, after)})
        """
        block_tag = tx.block_tag or "latest"
        
        # 确定模拟区块
        if block_tag != "latest" and block_tag != "pending":
            block_number = int(block_tag, 16) if block_tag.startswith("0x") else int(block_tag)
            before_block = hex(block_number - 1)
            after_block = hex(block_number)
        else:
            # 对于 latest，before 和 after 都是 latest
            current_block = await self.get_block_number()
            before_block = hex(current_block)
            after_block = "latest"
            block_number = current_block
        
        # 执行 before 查询
        before_results = {}
        for method, params in queries:
            query_key = f"{method}:{params}"
            try:
                result = await self.client.call(method, params + [before_block])
                before_results[query_key] = result
            except Exception as e:
                logger.debug(f"Before query failed: {e}")
                before_results[query_key] = None
        
        # 执行模拟
        sim_meta = await self.simulate(tx)
        
        # 执行 after 查询
        after_results = {}
        for method, params in queries:
            query_key = f"{method}:{params}"
            try:
                result = await self.client.call(method, params + [after_block])
                after_results[query_key] = result
            except Exception as e:
                logger.debug(f"After query failed: {e}")
                after_results[query_key] = None
        
        # 组合结果
        comparisons = {}
        for key in before_results:
            comparisons[key] = (before_results.get(key), after_results.get(key))
        
        return sim_meta, comparisons


async def simulate_transaction(
    tx_hash: str,
    rpc_url: str,
    enable_trace: bool = False
) -> Tuple[TxInput, SimMeta]:
    """
    便捷函数：模拟指定交易
    
    Args:
        tx_hash: 交易哈希
        rpc_url: RPC URL
        enable_trace: 是否获取 trace
    
    Returns:
        (TxInput, SimMeta)
    """
    config = SimulatorConfig(rpc_url=rpc_url, enable_trace=enable_trace)
    simulator = Simulator(config)
    
    tx_input = await simulator.fetch_tx_input(tx_hash)
    if not tx_input:
        raise ValueError(f"Transaction not found: {tx_hash}")
    
    sim_meta = await simulator.simulate(tx_input)
    
    return tx_input, sim_meta


def simulate_transaction_sync(
    tx_hash: str,
    rpc_url: str,
    enable_trace: bool = False
) -> Tuple[TxInput, SimMeta]:
    """同步版本的交易模拟"""
    return asyncio.run(simulate_transaction(tx_hash, rpc_url, enable_trace))
