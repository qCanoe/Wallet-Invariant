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

执行的检查项：
- 绝对阈值：授权量 ≥ `unlimited_allowance_threshold`（≈ 2^200）→ 拒绝
- 相对阈值：授权量 > 用户余额 × `allowance_balance_multiplier`（默认 5×）→ 拒绝
- 非授权操作中出现 `setApprovalForAll` → 拒绝
- `increaseAllowance` / `decreaseAllowance` 被正确分类为 `PERMISSION_OP`，豁免检查

### I3: 作用域局部性不变量
单目标操作不得影响多个无关资产。

执行的检查项：
- token 数量超过 `max_expected_token_count`（默认 2）且有意外流出 → 拒绝
- Dust 过滤：流出量 < `dust_threshold_wei`（默认 1000 wei）的转账不计入 scope
- 复合操作（`multicall` / `execute`）享有双倍限额，降低误报
- 已知 swap 选择器（Uniswap V2、1inch、Curve、Balancer、Paraswap、0x）豁免

### I4: 路径复杂度不变量（双阈值策略）
检测异常复杂的执行路径（高调用深度、多 delegatecall）。

| 级别 | 触发条件 | 动作 |
|------|---------|------|
| 高风险 | 深度 ≥ 10 或 delegatecall ≥ 5 | 产生 `RiskLabel`（仅警告） |
| 极端危险 | 深度 ≥ 15 或 delegatecall ≥ 10 | **无条件拒绝** |
| 拒绝模式 | `enable_path_rejection=true` | 高风险阈值也触发拒绝 |

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

复制示例配置并填入 RPC URL：

```bash
cp config.example.json config.json
```

`invariants` 关键参数说明：

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `unlimited_allowance_threshold` | 2^200 | 绝对无限授权阈值（I2） |
| `allowance_balance_multiplier` | 5 | 授权量与余额的最大倍数（I2） |
| `max_expected_token_count` | 2 | 单目标操作预期 token 上限（I3） |
| `dust_threshold_wei` | 1000 | 低于此值的转账不计入 scope（I3） |
| `high_call_depth_threshold` | 10 | 触发 RiskLabel 的调用深度（I4） |
| `high_delegate_call_threshold` | 5 | 触发 RiskLabel 的 delegatecall 次数（I4） |
| `critical_call_depth_threshold` | 15 | 触发无条件拒绝的调用深度（I4） |
| `critical_delegate_call_threshold` | 10 | 触发无条件拒绝的 delegatecall 次数（I4） |
| `enable_path_rejection` | false | 在高风险（非极端）阈值也触发拒绝 |
| `fail_open_on_timeout` | true | 超时时允许交易（设为 false 则超时→拒绝） |

或使用环境变量：

```bash
export RPC_URL="https://eth-sepolia.g.alchemy.com/v2/YOUR_API_KEY"
export DEBUG=true
export LOG_LEVEL=DEBUG
```

---

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
gate init-dataset --output my_dataset.json
gate batch --input my_dataset.json --output report.json
```

### 编程接口（异步）

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

---

## 项目结构

```
wallet-invariant/
├── src/
│   ├── __init__.py          # 包初始化
│   ├── types.py              # 核心类型定义
│   ├── constants.py          # 常量与函数选择器
│   ├── config.py             # 配置管理
│   ├── classifier.py         # 交易分类器（启发式）
│   ├── simulator.py          # 预执行模拟器
│   ├── delta_extractor.py    # ΔS 抽取器（日志/trace 解析）
│   ├── invariants.py         # 不变量引擎（I1–I4）
│   ├── gate.py               # 执行裁决门（核心入口）
│   ├── evaluation.py         # 回放评估管线
│   └── cli.py                # CLI 工具
├── tests/
│   ├── conftest.py               # 共享 fixtures
│   ├── fixtures/
│   │   └── rpc_responses.py      # Mock RPC 响应工厂函数
│   ├── test_types.py
│   ├── test_invariants.py        # 不变量单元测试（57 cases）
│   └── test_integration.py       # 端到端集成测试（离线，Mock RPC）
├── data/
│   └── sample_dataset.json       # 示例数据集
├── config.example.json           # 配置示例（含所有参数说明）
├── requirements.txt              # 依赖列表
├── pyproject.toml                # 项目配置
├── .github/
│   └── workflows/ci.yml          # GitHub Actions CI（test + lint）
├── ROADMAP.md                    # 项目路线规划（v0.1.0 → v1.0.0）
└── README_CN.md
```

---

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
不变量验证 (InvariantEngine: I1 → I2 → I3 → I4)
  ↓
允许签名 / 拒绝执行
```

---

## 测试

```bash
# 运行全部测试（57 cases，全离线）
pytest -v

# 带覆盖率报告
pytest --cov=src --cov-report=term-missing

# 代码风格检查
ruff check src/ tests/
```

测试覆盖场景：

| 模块 | 测试数 | 覆盖场景 |
|------|--------|---------|
| `test_types.py` | 11 | 类型定义、属性计算 |
| `test_invariants.py` | 34 | I1–I4 单元测试、分类器、双阈值、dust filter |
| `test_integration.py` | 12 | 端到端（mock RPC）、fail-open、swap bypass |

---

## 评估指标

- **Attack blocked rate**：攻击交易被拒绝的比例
- **False positive rate**：正常交易被误杀的比例
- **Fail-open rate**：因模拟失败而允许的比例
- **Reason breakdown**：各不变量触发占比

---

## 设计原则

1. **Fail-open**：模拟失败或证据不足时，允许交易（但记录原因）
2. **只拒绝有强证据的违规**：不做过度推断
3. **透明**：所有决策都有完整的证据记录
4. **双阈值 I4**：区分"高风险警告"与"必须拒绝"的路径复杂度场景

---

## 路线规划

查看 [ROADMAP.md](ROADMAP.md) 了解完整开发路线（v0.1.0 → v1.0.0）。

## License

MIT
