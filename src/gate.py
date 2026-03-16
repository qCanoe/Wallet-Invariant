"""
Wallet Invariant MVP - Execution Gate

核心入口：将模拟、ΔS 抽取、不变量裁决串联起来
"""

import asyncio
import logging
from typing import Optional

from .types import TxInput, GateDecision
from .config import GateConfig, DEFAULT_CONFIG
from .simulator import Simulator
from .delta_extractor import DeltaExtractor
from .invariants import InvariantEngine
from .classifier import classify_transaction

logger = logging.getLogger(__name__)


class ExecutionGate:
    """
    执行裁决门
    
    完整的 Wallet Invariant 管线：
    TxInput → Simulate → DeltaExtract → InvariantCheck → GateDecision
    """
    
    def __init__(self, config: Optional[GateConfig] = None):
        self.config = config or DEFAULT_CONFIG
        self.simulator = Simulator(self.config.simulator)
        self.extractor = DeltaExtractor(self.simulator)
        self.engine = InvariantEngine(self.config.invariants)
    
    async def evaluate_tx_hash(self, tx_hash: str) -> GateDecision:
        """
        评估指定交易哈希
        
        完整流程：获取交易 → 模拟 → 抽取 ΔS → 不变量裁决
        """
        # 1. 获取交易信息
        tx_input = await self.simulator.fetch_tx_input(tx_hash)
        if not tx_input:
            raise ValueError(f"Transaction not found: {tx_hash}")
        
        # 2. 分类
        tx_input.category = classify_transaction(tx_input)
        
        # 3. 模拟执行
        sim_meta = await self.simulator.simulate(tx_input)
        
        # 4. 抽取 ΔS
        delta = self.extractor.extract(tx_input, sim_meta)
        
        # 5. 不变量裁决
        decision = self.engine.evaluate(tx_input, delta, sim_meta)
        
        return decision
    
    async def evaluate_tx_input(self, tx_input: TxInput) -> GateDecision:
        """
        评估候选交易（不是链上已有的交易）
        
        用于在用户签名前评估
        """
        # 1. 分类
        if tx_input.category is None or tx_input.category == tx_input.category.UNKNOWN:
            tx_input.category = classify_transaction(tx_input)
        
        # 2. 模拟执行
        sim_meta = await self.simulator.simulate(tx_input)
        
        # 3. 抽取 ΔS
        delta = self.extractor.extract(tx_input, sim_meta)
        
        # 4. 不变量裁决
        decision = self.engine.evaluate(tx_input, delta, sim_meta)
        
        return decision
    
    def evaluate_tx_hash_sync(self, tx_hash: str) -> GateDecision:
        """同步版本"""
        return asyncio.run(self.evaluate_tx_hash(tx_hash))
    
    def evaluate_tx_input_sync(self, tx_input: TxInput) -> GateDecision:
        """同步版本"""
        return asyncio.run(self.evaluate_tx_input(tx_input))


async def evaluate(
    tx_hash: str,
    rpc_url: str,
    enable_trace: bool = False,
) -> GateDecision:
    """
    便捷函数：评估单笔交易
    
    Args:
        tx_hash: 交易哈希
        rpc_url: RPC URL
        enable_trace: 是否获取 trace
    
    Returns:
        GateDecision
    """
    config = GateConfig()
    config.simulator.rpc_url = rpc_url
    config.simulator.enable_trace = enable_trace
    
    gate = ExecutionGate(config)
    return await gate.evaluate_tx_hash(tx_hash)


def evaluate_sync(
    tx_hash: str,
    rpc_url: str,
    enable_trace: bool = False,
) -> GateDecision:
    """同步版本"""
    return asyncio.run(evaluate(tx_hash, rpc_url, enable_trace))
