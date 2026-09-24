from pathlib import Path
from amrte.app import build_engine
from amrte.infrastructure.local import ProhibitedExecutionProvider


def test_regime_configuration_and_execution_remain_separate():
    engine=build_engine(); values=engine.configuration.values
    assert values["regime.exit_threshold"]<=values["regime.entry_threshold"]
    assert values["regime.strict"] is True
    assert not ProhibitedExecutionProvider(engine.audit).submit({"regime_metadata":"UNKNOWN"}).success
    source=Path("src/amrte/market/regime.py").read_text(encoding="utf-8")
    forbidden=("import requests","import socket","MetaTrader","order_send","position_size","session_classification","news_risk")
    assert not any(token in source for token in forbidden)

