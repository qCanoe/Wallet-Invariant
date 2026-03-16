"""
Wallet Invariant MVP - 配置管理
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import os
import json


@dataclass
class SimulatorConfig:
    """模拟器配置"""
    # RPC 端点
    rpc_url: str = ""
    
    # 模拟方法：eth_call / fork
    method: str = "eth_call"
    
    # 超时设置（秒）
    timeout: int = 30
    
    # 是否获取 trace（需要节点支持）
    enable_trace: bool = False
    
    # 重试次数
    max_retries: int = 3


@dataclass
class InvariantConfig:
    """不变量引擎配置"""
    # I2: 权限比例阈值
    # 大于此值视为无限授权
    unlimited_allowance_threshold: int = 2**200
    
    # I2: 相对阈值（用户余额的倍数）
    allowance_balance_multiplier: int = 5
    
    # I3: 作用域阈值
    max_expected_token_count: int = 2
    
    # I4: 路径复杂度阈值（触发 RiskLabel）
    high_call_depth_threshold: int = 10
    high_delegate_call_threshold: int = 5

    # I4: 极端阈值（无论 enable_path_rejection，直接 REJECT）
    critical_call_depth_threshold: int = 15
    critical_delegate_call_threshold: int = 10

    # I4: 是否启用路径合理性拒绝（默认只做标签化）
    enable_path_rejection: bool = False

    # I3: dust 转账过滤阈值（绝对值 < 此 wei 的转账不计入 scope）
    dust_threshold_wei: int = 1000

    # fail-open: 超时时是否允许交易（默认 True；设为 False 则超时 → REJECT）
    fail_open_on_timeout: bool = True


@dataclass
class GateConfig:
    """Gate 总配置"""
    simulator: SimulatorConfig = field(default_factory=SimulatorConfig)
    invariants: InvariantConfig = field(default_factory=InvariantConfig)
    
    # 调试模式
    debug: bool = False
    
    # 日志级别
    log_level: str = "INFO"
    
    @classmethod
    def from_env(cls) -> "GateConfig":
        """从环境变量加载配置"""
        config = cls()
        
        # RPC URL
        if rpc_url := os.environ.get("RPC_URL"):
            config.simulator.rpc_url = rpc_url
        elif eth_rpc := os.environ.get("ETH_RPC_URL"):
            config.simulator.rpc_url = eth_rpc
        
        # 调试模式
        config.debug = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
        
        # 日志级别
        if log_level := os.environ.get("LOG_LEVEL"):
            config.log_level = log_level.upper()
        
        return config
    
    @classmethod
    def from_file(cls, path: str) -> "GateConfig":
        """从 JSON 文件加载配置"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GateConfig":
        """从字典加载配置"""
        config = cls()
        
        if sim_data := data.get("simulator"):
            config.simulator.rpc_url = sim_data.get("rpc_url", config.simulator.rpc_url)
            config.simulator.method = sim_data.get("method", config.simulator.method)
            config.simulator.timeout = sim_data.get("timeout", config.simulator.timeout)
            config.simulator.enable_trace = sim_data.get("enable_trace", config.simulator.enable_trace)
            config.simulator.max_retries = sim_data.get("max_retries", config.simulator.max_retries)
        
        if inv_data := data.get("invariants"):
            config.invariants.unlimited_allowance_threshold = inv_data.get(
                "unlimited_allowance_threshold", 
                config.invariants.unlimited_allowance_threshold
            )
            config.invariants.allowance_balance_multiplier = inv_data.get(
                "allowance_balance_multiplier",
                config.invariants.allowance_balance_multiplier
            )
            config.invariants.max_expected_token_count = inv_data.get(
                "max_expected_token_count",
                config.invariants.max_expected_token_count
            )
            config.invariants.high_call_depth_threshold = inv_data.get(
                "high_call_depth_threshold",
                config.invariants.high_call_depth_threshold
            )
            config.invariants.high_delegate_call_threshold = inv_data.get(
                "high_delegate_call_threshold",
                config.invariants.high_delegate_call_threshold
            )
            config.invariants.enable_path_rejection = inv_data.get(
                "enable_path_rejection",
                config.invariants.enable_path_rejection
            )
            config.invariants.critical_call_depth_threshold = inv_data.get(
                "critical_call_depth_threshold",
                config.invariants.critical_call_depth_threshold,
            )
            config.invariants.critical_delegate_call_threshold = inv_data.get(
                "critical_delegate_call_threshold",
                config.invariants.critical_delegate_call_threshold,
            )
            config.invariants.dust_threshold_wei = inv_data.get(
                "dust_threshold_wei",
                config.invariants.dust_threshold_wei,
            )
            config.invariants.fail_open_on_timeout = inv_data.get(
                "fail_open_on_timeout",
                config.invariants.fail_open_on_timeout,
            )
        
        config.debug = data.get("debug", config.debug)
        config.log_level = data.get("log_level", config.log_level)
        
        return config
    
    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return {
            "simulator": {
                "rpc_url": self.simulator.rpc_url,
                "method": self.simulator.method,
                "timeout": self.simulator.timeout,
                "enable_trace": self.simulator.enable_trace,
                "max_retries": self.simulator.max_retries,
            },
            "invariants": {
                "unlimited_allowance_threshold": str(self.invariants.unlimited_allowance_threshold),
                "allowance_balance_multiplier": self.invariants.allowance_balance_multiplier,
                "max_expected_token_count": self.invariants.max_expected_token_count,
                "high_call_depth_threshold": self.invariants.high_call_depth_threshold,
                "high_delegate_call_threshold": self.invariants.high_delegate_call_threshold,
                "enable_path_rejection": self.invariants.enable_path_rejection,
            },
            "debug": self.debug,
            "log_level": self.log_level,
        }


# 默认配置实例
DEFAULT_CONFIG = GateConfig()
