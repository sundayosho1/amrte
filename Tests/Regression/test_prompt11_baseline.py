from pathlib import Path
from amrte.core.constants import AMRTE_VERSION


def test_prompt11_version_and_framework_only_boundary():
    assert tuple(map(int,AMRTE_VERSION.split(".")))>=(0,11,0)
    names={path.name for path in Path("src/amrte/strategies").glob("*.py")}
    assert "framework.py" in names and not names.intersection({"trend.py","breakout.py","mean_reversion.py","arbitration.py"})


def test_strategy_source_has_no_broker_execution_financial_sizing_or_duplicate_intelligence():
    source=Path("src/amrte/strategies/framework.py").read_text(encoding="utf-8").lower()
    forbidden=("import requests","import socket","metatrader","ccxt","order_send","lot_size","stop_loss","take_profit","broker authentication","ema_series","atr_series")
    assert not any(token in source for token in forbidden)
