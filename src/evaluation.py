"""
Wallet Invariant MVP - 回放评估管线

功能：
- 批量回放交易
- 统计 blocked rate / false positive / fail-open / reason breakdown
- 生成评估报告
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import defaultdict

from .types import Decision, GateDecision
from .config import GateConfig
from .gate import ExecutionGate

logger = logging.getLogger(__name__)


@dataclass
class TxSample:
    """交易样本"""
    tx_hash: str
    label: str  # "attack" / "benign" / "unknown"
    description: Optional[str] = None
    expected_decision: Optional[str] = None  # "reject" / "allow"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TxSample":
        return cls(
            tx_hash=data["tx_hash"],
            label=data.get("label", "unknown"),
            description=data.get("description"),
            expected_decision=data.get("expected_decision"),
        )


@dataclass
class EvalResult:
    """单笔交易评估结果"""
    sample: TxSample
    decision: GateDecision
    duration_ms: float
    error: Optional[str] = None
    
    @property
    def is_blocked(self) -> bool:
        return self.decision.decision == Decision.REJECT
    
    @property
    def is_fail_open(self) -> bool:
        return self.decision.is_fail_open
    
    @property
    def violated_invariants(self) -> List[str]:
        return [v.invariant_id.value for v in self.decision.violations]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_hash": self.sample.tx_hash,
            "label": self.sample.label,
            "description": self.sample.description,
            "decision": self.decision.decision.value,
            "is_blocked": self.is_blocked,
            "is_fail_open": self.is_fail_open,
            "violated_invariants": self.violated_invariants,
            "risk_labels": [r.to_dict() for r in self.decision.risk_labels],
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class EvalMetrics:
    """评估指标"""
    total: int = 0
    blocked: int = 0
    allowed: int = 0
    fail_open: int = 0
    errors: int = 0
    
    # 按标签分组
    attack_total: int = 0
    attack_blocked: int = 0
    benign_total: int = 0
    benign_blocked: int = 0
    
    # 不变量触发统计
    invariant_triggers: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # 时间统计
    total_duration_ms: float = 0.0
    
    @property
    def blocked_rate(self) -> float:
        """总拒绝率"""
        return self.blocked / self.total if self.total > 0 else 0.0
    
    @property
    def attack_blocked_rate(self) -> float:
        """攻击交易拦截率"""
        return self.attack_blocked / self.attack_total if self.attack_total > 0 else 0.0
    
    @property
    def false_positive_rate(self) -> float:
        """误杀率（正常交易被拒绝的比例）"""
        return self.benign_blocked / self.benign_total if self.benign_total > 0 else 0.0
    
    @property
    def fail_open_rate(self) -> float:
        """Fail-open 率"""
        return self.fail_open / self.total if self.total > 0 else 0.0
    
    @property
    def avg_duration_ms(self) -> float:
        """平均评估耗时"""
        return self.total_duration_ms / self.total if self.total > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "blocked": self.blocked,
            "allowed": self.allowed,
            "fail_open": self.fail_open,
            "errors": self.errors,
            "blocked_rate": f"{self.blocked_rate:.2%}",
            "attack": {
                "total": self.attack_total,
                "blocked": self.attack_blocked,
                "blocked_rate": f"{self.attack_blocked_rate:.2%}",
            },
            "benign": {
                "total": self.benign_total,
                "blocked": self.benign_blocked,
                "false_positive_rate": f"{self.false_positive_rate:.2%}",
            },
            "fail_open_rate": f"{self.fail_open_rate:.2%}",
            "invariant_triggers": dict(self.invariant_triggers),
            "avg_duration_ms": f"{self.avg_duration_ms:.1f}",
        }


@dataclass
class EvalReport:
    """评估报告"""
    metrics: EvalMetrics
    results: List[EvalResult]
    config: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "metrics": self.metrics.to_dict(),
            "config": self.config,
            "results": [r.to_dict() for r in self.results],
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    def save(self, path: str):
        """保存报告到文件"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
    
    def summary(self) -> str:
        """生成摘要文本"""
        m = self.metrics
        lines = [
            "=" * 60,
            "Wallet Invariant 评估报告",
            "=" * 60,
            f"时间: {self.timestamp}",
            "",
            "总体指标:",
            f"  - 总交易数: {m.total}",
            f"  - 拒绝数: {m.blocked} ({m.blocked_rate:.2%})",
            f"  - 允许数: {m.allowed}",
            f"  - Fail-open: {m.fail_open} ({m.fail_open_rate:.2%})",
            f"  - 错误: {m.errors}",
            "",
            "攻击交易拦截:",
            f"  - 攻击样本数: {m.attack_total}",
            f"  - 拦截数: {m.attack_blocked}",
            f"  - 拦截率: {m.attack_blocked_rate:.2%}",
            "",
            "误杀率（正常交易被拒绝）:",
            f"  - 正常样本数: {m.benign_total}",
            f"  - 误杀数: {m.benign_blocked}",
            f"  - 误杀率: {m.false_positive_rate:.2%}",
            "",
            "不变量触发统计:",
        ]
        
        for inv_id, count in sorted(m.invariant_triggers.items()):
            lines.append(f"  - {inv_id}: {count} 次")
        
        lines.extend([
            "",
            f"平均评估耗时: {m.avg_duration_ms:.1f} ms",
            "=" * 60,
        ])
        
        return "\n".join(lines)


class Evaluator:
    """评估器"""
    
    def __init__(self, config: Optional[GateConfig] = None):
        self.config = config or GateConfig()
        self.gate = ExecutionGate(self.config)
    
    async def evaluate_sample(self, sample: TxSample) -> EvalResult:
        """评估单个样本"""
        start = time.time()
        error = None
        decision = None
        
        try:
            decision = await self.gate.evaluate_tx_hash(sample.tx_hash)
        except Exception as e:
            error = str(e)
            logger.warning(f"Failed to evaluate {sample.tx_hash}: {e}")
            # 创建 fail-open 决策
            from .types import FailOpenReason
            decision = GateDecision(
                decision=Decision.ALLOW,
                is_fail_open=True,
                fail_open_reason=FailOpenReason.SIMULATION_FAILED,
                fail_open_details=error,
            )
        
        duration_ms = (time.time() - start) * 1000
        
        return EvalResult(
            sample=sample,
            decision=decision,
            duration_ms=duration_ms,
            error=error,
        )
    
    async def evaluate_batch(
        self, 
        samples: List[TxSample],
        concurrency: int = 5,
        progress_callback=None,
    ) -> List[EvalResult]:
        """批量评估"""
        results = []
        semaphore = asyncio.Semaphore(concurrency)
        
        async def eval_with_semaphore(sample: TxSample, idx: int):
            async with semaphore:
                result = await self.evaluate_sample(sample)
                if progress_callback:
                    progress_callback(idx + 1, len(samples), result)
                return result
        
        tasks = [
            eval_with_semaphore(sample, idx) 
            for idx, sample in enumerate(samples)
        ]
        results = await asyncio.gather(*tasks)
        
        return results
    
    def compute_metrics(self, results: List[EvalResult]) -> EvalMetrics:
        """计算评估指标"""
        metrics = EvalMetrics()
        
        for r in results:
            metrics.total += 1
            metrics.total_duration_ms += r.duration_ms
            
            if r.error:
                metrics.errors += 1
            
            if r.is_blocked:
                metrics.blocked += 1
            else:
                metrics.allowed += 1
            
            if r.is_fail_open:
                metrics.fail_open += 1
            
            # 按标签统计
            if r.sample.label == "attack":
                metrics.attack_total += 1
                if r.is_blocked:
                    metrics.attack_blocked += 1
            elif r.sample.label == "benign":
                metrics.benign_total += 1
                if r.is_blocked:
                    metrics.benign_blocked += 1
            
            # 不变量触发统计
            for inv_id in r.violated_invariants:
                metrics.invariant_triggers[inv_id] += 1
        
        return metrics
    
    async def run_evaluation(
        self, 
        samples: List[TxSample],
        concurrency: int = 5,
        progress_callback=None,
    ) -> EvalReport:
        """运行完整评估"""
        # 批量评估
        results = await self.evaluate_batch(
            samples, 
            concurrency=concurrency,
            progress_callback=progress_callback,
        )
        
        # 计算指标
        metrics = self.compute_metrics(results)
        
        # 生成报告
        report = EvalReport(
            metrics=metrics,
            results=results,
            config=self.config.to_dict(),
        )
        
        return report
    
    def run_evaluation_sync(
        self, 
        samples: List[TxSample],
        concurrency: int = 5,
    ) -> EvalReport:
        """同步版本"""
        return asyncio.run(self.run_evaluation(samples, concurrency))


def load_dataset(path: str) -> List[TxSample]:
    """从 JSON 文件加载数据集"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if isinstance(data, list):
        return [TxSample.from_dict(item) for item in data]
    elif isinstance(data, dict) and "samples" in data:
        return [TxSample.from_dict(item) for item in data["samples"]]
    else:
        raise ValueError("Invalid dataset format")


def save_dataset(samples: List[TxSample], path: str):
    """保存数据集到 JSON 文件"""
    data = {
        "samples": [
            {
                "tx_hash": s.tx_hash,
                "label": s.label,
                "description": s.description,
                "expected_decision": s.expected_decision,
            }
            for s in samples
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
