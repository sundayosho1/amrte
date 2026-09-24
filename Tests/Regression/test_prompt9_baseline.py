from pathlib import Path
from amrte.core.constants import AMRTE_VERSION


def test_prompt9_version_and_no_future_or_execution_owners():
    assert tuple(map(int,AMRTE_VERSION.split(".")))>=(0,9,0)
    names={path.name for path in Path("src/amrte/market").glob("*.py")}
    assert "session.py" in names and not names.intersection({"news.py","strategy.py"})


def test_session_module_has_no_connectivity_or_order_capability():
    source=Path("src/amrte/market/session.py").read_text(encoding="utf-8").lower()
    assert not any(token in source for token in ("import requests","import socket","order_send","metatrader","ccxt","broker authentication"))
