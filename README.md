# Wallet Invariant MVP

**A research prototype for wallet transaction admission model based on execution invariants**

## Overview

Wallet Invariant is an **execution invariants model** enforced on the wallet side before transaction execution. Unlike existing smart contract invariant research, Wallet Invariant does not attempt to verify contract correctness, but rather constrains the **admissibility** of transactions.

## Core Features

- **Mechanism-first**: Does not rely on user understanding or subjective judgment
- **Wallet-side implementable**: No need to modify the chain or contracts
- **Conservative execution (fail-open)**: Only rejects transactions that clearly violate invariants
- **Low semantic dependency**: Does not attempt to understand complex contract logic

## Invariant Set

### I1: Non-Asset Behavior Invariant
Non-asset operations (such as login/claim) must not result in user asset loss.

### I2: Permission Proportionality Invariant
One-time target operations must not introduce permanent/unlimited authorization.

Enforced checks:
- Absolute threshold: allowance ≥ `unlimited_allowance_threshold` (≈ 2^200) → REJECT
- Relative threshold: allowance > user balance × `allowance_balance_multiplier` (default 5×) → REJECT
- `setApprovalForAll` from non-permission operations → REJECT
- `increaseAllowance` / `decreaseAllowance` are correctly classified as `PERMISSION_OP` and exempt

### I3: Scope Locality Invariant
Single-target operations must not affect multiple unrelated assets.

Enforced checks:
- Token count exceeds `max_expected_token_count` (default 2) with unexpected outflows → REJECT
- Dust filter: outflows < `dust_threshold_wei` (default 1000 wei) are excluded from scope counting
- Composite ops (`multicall` / `execute`): limit doubled to reduce false positives
- Known swap selectors (Uniswap V2, 1inch, Curve, Balancer, Paraswap, 0x) are exempt

### I4: Path Complexity Invariant (Dual-Threshold)
Detects abnormally complex execution paths (high call depth, multiple delegatecalls).

| Level | Condition | Action |
|-------|-----------|--------|
| High | depth ≥ 10 or delegatecall ≥ 5 | `RiskLabel` (warn only) |
| Critical | depth ≥ 15 or delegatecall ≥ 10 | **REJECT** (unconditional) |
| Rejection mode | `enable_path_rejection=true` | REJECT at high threshold too |

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd wallet-invariant

# Install dependencies
pip install -e ".[dev]"
```

## Quick Start (3 minutes)

### 1. Configure RPC

```bash
export RPC_URL="https://eth-mainnet.g.alchemy.com/v2/YOUR_API_KEY"
```

### 2. CLI: Evaluate an on-chain transaction

```bash
gate eval --tx-hash 0x5c504ed432cb51138bcf09aa5e8a410dd4a1e204ef84bfed1be16dfba1b22060
```

Example output (approval-abuse attack rejected):

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

### 3. Python API: Intercept before user signature

```python
from src.gate import ExecutionGate
from src.types import TxInput, Decision

gate = ExecutionGate.from_env()  # reads RPC_URL env var

tx = TxInput(
    chain_id=1,
    from_address="0xYourWallet",
    to_address="0xSomeContract",
    data="0xabcdef...",
    value=0,
)

decision = gate.evaluate_tx_input_sync(tx)

if decision.decision == Decision.REJECT:
    print("Transaction blocked!")
    for v in decision.violations:
        print(f"  {v.invariant_id.value}: {v.message}")
else:
    print("Transaction passed, safe to sign")
```

### 4. Batch Evaluation

```bash
gate init-dataset --output my_dataset.json
gate batch --input my_dataset.json --output report.json --concurrency 5
```

## Configuration

Copy the example config and fill in your RPC URL:

```bash
cp config.example.json config.json
```

Key `invariants` parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `unlimited_allowance_threshold` | 2^200 | Absolute unlimited allowance threshold |
| `allowance_balance_multiplier` | 5 | Max allowance as multiple of token balance (I2) |
| `max_expected_token_count` | 2 | Max tokens for single-target ops (I3) |
| `dust_threshold_wei` | 1000 | Outflows below this value ignored in scope (I3) |
| `high_call_depth_threshold` | 10 | Call depth triggering RiskLabel (I4) |
| `high_delegate_call_threshold` | 5 | Delegatecall count triggering RiskLabel (I4) |
| `critical_call_depth_threshold` | 15 | Call depth triggering unconditional REJECT (I4) |
| `critical_delegate_call_threshold` | 10 | Delegatecall count triggering unconditional REJECT (I4) |
| `enable_path_rejection` | false | Reject at high (non-critical) I4 threshold |
| `fail_open_on_timeout` | true | Allow on timeout (set false for stricter mode) |

## Project Structure

```
wallet-invariant/
├── src/
│   ├── types.py              # Core type definitions
│   ├── constants.py          # Constants and function selectors
│   ├── config.py             # Configuration management
│   ├── classifier.py         # Transaction classifier (heuristic)
│   ├── simulator.py          # Pre-execution simulator
│   ├── delta_extractor.py    # ΔS extractor (from logs/trace)
│   ├── invariants.py         # Invariant engine (I1–I4)
│   ├── gate.py               # Execution gate (core entry point)
│   ├── evaluation.py         # Replay evaluation pipeline
│   └── cli.py                # CLI tool
├── tests/
│   ├── conftest.py               # Shared fixtures
│   ├── fixtures/
│   │   └── rpc_responses.py      # Mock RPC response builders
│   ├── test_types.py
│   ├── test_invariants.py        # Unit tests (I1–I4, classifier)
│   └── test_integration.py       # End-to-end tests (offline, mocked RPC)
├── data/
│   └── sample_dataset.json
├── config.example.json
├── requirements.txt
├── pyproject.toml
├── .github/workflows/ci.yml  # GitHub Actions CI (test + lint)
├── ROADMAP.md                # Project roadmap (v0.1 → v1.0)
└── README.md
```

## Execution Flow

```
User requests operation
  ↓
Transaction construction (candidate tx)
  ↓
Local simulation (Simulator)
  ↓
State change abstraction ΔS (DeltaExtractor)
  ↓
Invariant verification (InvariantEngine: I1 → I2 → I3 → I4)
  ↓
Allow signature / Reject execution
```

## Testing

```bash
# Run all tests (57 cases, offline)
pytest -v

# With coverage report
pytest --cov=src --cov-report=term-missing

# Lint
ruff check src/ tests/
```

## Evaluation Metrics

- **Attack blocked rate**: Proportion of attack transactions rejected
- **False positive rate**: Proportion of legitimate transactions incorrectly blocked
- **Fail-open rate**: Proportion allowed due to simulation failure
- **Reason breakdown**: Proportion of each invariant triggered

## Design Principles

1. **Fail-open**: Allow transactions when simulation fails or evidence is insufficient (but record the reason)
2. **Only reject violations with strong evidence**: Do not make excessive inferences
3. **Transparency**: All decisions have complete evidence records
4. **Dual-threshold for I4**: Distinguish warning-level from must-reject-level path complexity

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full development roadmap (v0.1.0 → v1.0.0).

## License

MIT
