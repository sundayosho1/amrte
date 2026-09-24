from pathlib import Path

from amrte.app import build_engine
from amrte.core.types import Capability, SystemState


def test_prompt1_safety_baseline():
    engine = build_engine()
    assert engine.state_machine.state is SystemState.READY
    assert engine.configuration.values["broker.live_execution"] is False
    assert engine.configuration.values["broker.demo_execution"] is False
    assert engine.configuration.values["safety.martingale"] is False
    assert engine.configuration.values["safety.unlimited_exposure"] is False
    assert not engine.capabilities.has(Capability.LIVE_BROKER_EXECUTION_AVAILABLE)
    assert not engine.capabilities.has(Capability.DEMO_BROKER_EXECUTION_AVAILABLE)


def test_source_contains_no_network_or_broker_adapter_modules():
    source_files = list(Path("src").rglob("*.py"))
    forbidden_imports = ("import requests", "import socket", "import MetaTrader", "import ccxt")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in source_files)
    assert not any(token in combined for token in forbidden_imports)

