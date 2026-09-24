from pathlib import Path

from amrte.app import build_engine
from amrte.core.constants import AMRTE_VERSION


def test_prompt1_through_5_baseline_remains_ready():
    engine = build_engine()
    assert engine.state_machine.state.name == "READY"
    assert tuple(map(int, AMRTE_VERSION.split("."))) >= (0, 6, 0)
    assert engine.configuration.values["execution.available"] is False


def test_structure_has_no_network_execution_or_later_prompt_dependencies():
    source = Path("src/amrte/market/structure.py").read_text(encoding="utf-8")
    forbidden = ("import requests","import socket","MetaTrader","ccxt","order_send",
                 "ATR(","RSI(","MACD(","market_regime","strategy_signal")
    assert not any(token in source for token in forbidden)
