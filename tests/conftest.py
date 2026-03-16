"""
Shared pytest fixtures for all tests.
"""

import pytest
from src.config import GateConfig, SimulatorConfig, InvariantConfig


@pytest.fixture
def gate_config() -> GateConfig:
    """Default gate config with mock RPC URL for offline testing."""
    return GateConfig(
        simulator=SimulatorConfig(rpc_url="http://mock-rpc.test"),
        invariants=InvariantConfig(),
    )
