from pathlib import Path

from amrte.app import build_engine
from amrte.core.constants import AMRTE_VERSION


def test_phase_i_baseline_and_version_remain_available():
    engine = build_engine()
    assert engine.state_machine.state.name == "READY"
    assert tuple(map(int, AMRTE_VERSION.split("."))) >= (0, 5, 0)
    assert engine.configuration.values["execution.available"] is False


def test_market_layer_contains_no_network_or_platform_adapter():
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/amrte/market").glob("*.py"))
    forbidden = ("import requests", "import socket", "MetaTrader", "ccxt", "order_send",
                 "smtplib", "http.client")
    assert not any(item in source for item in forbidden)


def test_market_layer_does_not_implement_unreached_phase_owners():
    names = {path.name for path in Path("src/amrte/market").glob("*.py")}
    assert not names.intersection({"sessions.py", "news.py", "strategy.py"})
