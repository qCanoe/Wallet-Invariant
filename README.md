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

### I3: Scope Locality Invariant
Single-target operations must not affect multiple unrelated assets.

### I4: Path Reasonableness Invariant (Tagged)
Detects abnormally complex execution paths (high call depth, multiple delegatecalls).

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd wallet-invariant

# Install dependencies
pip install -e ".[dev]"
```

## Configuration

1. Copy the example configuration:
```bash
cp config.example.json config.json
```

2. Edit `config.json` and fill in your RPC URL.

3. Or use environment variables:
```bash
export RPC_URL="https://eth-sepolia.g.alchemy.com/v2/YOUR_API_KEY"
```

## Usage

### Evaluate a Single Transaction

```bash
# Using environment variables
export RPC_URL="https://..."
gate eval --tx-hash 0x1234...

# Or specify RPC URL
gate eval --rpc-url https://... --tx-hash 0x1234...

# Output JSON format
gate eval --tx-hash 0x1234... --format json --output result.json
```

### Batch Evaluation

```bash
# Initialize example dataset
gate init-dataset --output my_dataset.json

# Edit the dataset, replace with real transaction hashes
# Then run batch evaluation
gate batch --input my_dataset.json --output report.json
```

### Programming Interface

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

## Project Structure

```
wallet-invariant/
├── src/
│   ├── __init__.py          # Package initialization
│   ├── types.py              # Core type definitions
│   ├── constants.py          # Constants and selectors
│   ├── config.py             # Configuration management
│   ├── classifier.py         # Transaction classifier
│   ├── simulator.py          # Pre-execution simulator
│   ├── delta_extractor.py    # ΔS extractor
│   ├── invariants.py         # Invariant engine
│   ├── gate.py               # Execution gate (core entry point)
│   ├── evaluation.py         # Replay evaluation pipeline
│   └── cli.py                # CLI tool
├── tests/
│   ├── test_types.py
│   ├── test_classifier.py
│   └── test_invariants.py
├── data/
│   └── sample_dataset.json   # Example dataset
├── config.example.json       # Configuration example
├── requirements.txt          # Dependencies list
├── pyproject.toml            # Project configuration
└── README.md
```

## Execution Flow

```
User requests operation
  ↓
Transaction construction (candidate)
  ↓
Local simulation execution (Simulator)
  ↓
State change abstraction ΔS (DeltaExtractor)
  ↓
Invariant verification (InvariantEngine)
  ↓
Allow signature / Reject execution
```

## Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=src
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

## License

MIT
