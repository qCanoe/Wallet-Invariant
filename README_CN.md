# Wallet Invariant MVP

**一种基于执行不变量的钱包交易准入模型的研究原型**

## 概述

Wallet Invariant 是一个在钱包侧、交易执行前强制执行的**执行不变量（execution invariants）模型**。与现有智能合约不变量研究不同，Wallet Invariant 不试图验证合约正确性，而是约束交易的**可执行性（admissibility）**。

## 核心特性

- **机制优先**：不依赖用户理解或主观判断
- **钱包单边可实现**：无需修改链或合约
- **保守执行（fail-open）**：只拒绝明确违反不变量的交易
- **低语义依赖**：不试图理解复杂合约逻辑

## 不变量集合

### I1: 非资产行为不变量
非资产操作（如 login/claim）不得导致用户资产损失。

### I2: 权限比例不变量
一次性目标操作不得引入永久/无限授权。

### I3: 作用域局部性不变量
单目标操作不得影响多个无关资产。

### I4: 路径合理性不变量（标签化）
检测异常复杂的执行路径（高调用深度、多 delegatecall）。

## 安装

```bash
# 克隆仓库
git clone <repo-url>
cd wallet-invariant

# 安装依赖
pip install -e ".[dev]"
```

## 快速上手（3 分钟）

### 1. 配置 RPC

```bash
export RPC_URL="https://eth-mainnet.g.alchemy.com/v2/YOUR_API_KEY"
```

### 2. CLI：评估单笔链上交易

```bash
gate eval --tx-hash 0x5c504ed432cb51138bcf09aa5e8a410dd4a1e204ef84bfed1be16dfba1b22060
```

示例输出（Approval 滥用攻击被拒绝）：

```json
{
  "decision": "reject",
  "violations": [
    {
      "invariant_id": "I2",
      "message": "非授权操作引入 1 项永久/无限权限",
      "evidence": {
        "category": "non_asset_op",
        "suspicious_permissions": [
          {
            "token": "0xdac17f958d2ee523a2206206994597c13d831ec7",
            "type": "allowance",
            "spender": "0xattacker...",
            "reason": "unlimited_allowance"
          }
        ]
      }
    }
  ],
  "is_fail_open": false
}
```

### 3. Python API：在用户签名前拦截

```python
from src.gate import ExecutionGate
from src.types import TxInput, Decision

gate = ExecutionGate.from_env()          # 读取 RPC_URL 环境变量

tx = TxInput(
    chain_id=1,
    from_address="0xYourWallet",
    to_address="0xSomeContract",
    data="0xabcdef...",                  # calldata
    value=0,
)

decision = gate.evaluate_tx_input_sync(tx)

if decision.decision == Decision.REJECT:
    print("交易被拦截！")
    for v in decision.violations:
        print(f"  违规不变量 {v.invariant_id.value}: {v.message}")
else:
    print("交易通过，可以签名")
```

### 4. 批量评估数据集

```bash
# 生成示例数据集模板
gate init-dataset --output my_dataset.json

# 填入真实交易哈希后运行批量评估
gate batch --input my_dataset.json --output report.json --concurrency 5
```

---

## 配置

1. 复制示例配置：
```bash
cp config.example.json config.json
```

2. 编辑 `config.json`，填入你的 RPC URL。

3. 或使用环境变量：
```bash
export RPC_URL="https://eth-sepolia.g.alchemy.com/v2/YOUR_API_KEY"
```

## 使用

### 评估单笔交易

```bash
# 使用环境变量
export RPC_URL="https://..."
gate eval --tx-hash 0x1234...

# 或指定 RPC URL
gate eval --rpc-url https://... --tx-hash 0x1234...

# 输出 JSON 格式
gate eval --tx-hash 0x1234... --format json --output result.json
```

### 批量评估

```bash
# 初始化示例数据集
gate init-dataset --output my_dataset.json

# 编辑数据集，替换为真实交易哈希
# 然后运行批量评估
gate batch --input my_dataset.json --output report.json
```

### 编程接口

```python
import asyncio
from src.gate import ExecutionGate
from src.config import GateConfig

async def main():
    config = GateConfig()
    config.simulator.rpc_url = "https://..."
    
    gate = ExecutionGate(config)
    decision = await gate.evaluate_tx_hash("0x1234...")
    
    print(f"Decision: {decision.decision.value}")
    if decision.violations:
        for v in decision.violations:
            print(f"  - {v.invariant_id.value}: {v.message}")

asyncio.run(main())
```

## 项目结构

```
wallet-invariant/
├── src/
│   ├── __init__.py          # 包初始化
│   ├── types.py              # 核心类型定义
│   ├── constants.py          # 常量与选择器
│   ├── config.py             # 配置管理
│   ├── classifier.py         # 交易分类器
│   ├── simulator.py          # 预执行模拟器
│   ├── delta_extractor.py    # ΔS 抽取器
│   ├── invariants.py         # 不变量引擎
│   ├── gate.py               # 执行裁决门（核心入口）
│   ├── evaluation.py         # 回放评估管线
│   └── cli.py                # CLI 工具
├── tests/
│   ├── conftest.py               # 共享 fixtures
│   ├── fixtures/
│   │   └── rpc_responses.py      # Mock RPC 响应工厂
│   ├── test_types.py
│   ├── test_classifier.py
│   ├── test_invariants.py
│   └── test_integration.py       # 端到端集成测试（离线）
├── data/
│   └── sample_dataset.json   # 示例数据集
├── config.example.json       # 配置示例
├── requirements.txt          # 依赖列表
├── pyproject.toml            # 项目配置
├── .github/
│   └── workflows/ci.yml          # GitHub Actions CI
├── ROADMAP.md                    # 项目路线规划
└── README.md
```

## 执行流程

```
用户请求操作
  ↓
交易构造（候选）
  ↓
本地模拟执行 (Simulator)
  ↓
状态变化抽象 ΔS (DeltaExtractor)
  ↓
不变量验证 (InvariantEngine)
  ↓
允许签名 / 拒绝执行
```

## 测试

```bash
# 运行测试
pytest

# 带覆盖率
pytest --cov=src
```

## 评估指标

- **Attack blocked rate**: 攻击交易被拒绝的比例
- **False positive rate**: 正常交易被误杀的比例
- **Fail-open rate**: 因模拟失败而允许的比例
- **Reason breakdown**: 各不变量触发占比

## 设计原则

1. **Fail-open**: 模拟失败或证据不足时，允许交易（但记录原因）
2. **只拒绝有强证据的违规**: 不做过度推断
3. **透明**: 所有决策都有完整的证据记录

## License

MIT
