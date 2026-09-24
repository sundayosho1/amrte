from pathlib import Path

from amrte.app import build_engine
from amrte.infrastructure.local import ProhibitedExecutionProvider


def test_feature_configuration_and_execution_boundary():
    engine=build_engine(); values=engine.configuration.values
    assert values["features.macd_fast"]<values["features.macd_slow"]
    assert values["features.strict"] is True
    assert not ProhibitedExecutionProvider(engine.audit).submit({"feature":"EMA"}).success
    source=Path("src/amrte/market/features.py").read_text(encoding="utf-8")
    assert not any(token in source for token in ("import requests","import socket","order_send","market_regime","BUY","SELL"))

