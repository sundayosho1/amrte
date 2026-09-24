from pathlib import Path
from amrte.core.constants import AMRTE_VERSION


def test_prompt10_version_phase2_modules_and_future_owner_boundary():
    assert tuple(map(int,AMRTE_VERSION.split(".")))>=(0,10,0)
    names={path.name for path in Path("src/amrte/market").glob("*.py")}
    assert {"events.py","intelligence.py"}.issubset(names) and "strategy.py" not in names


def test_prompt10_has_no_network_broker_execution_or_prediction_code():
    source="\n".join(Path(f"src/amrte/market/{name}").read_text(encoding="utf-8").lower() for name in ("events.py","intelligence.py"))
    forbidden=("import requests","import socket","metatrader","ccxt","order_send","position_size","predict_direction","broker authentication")
    assert not any(token in source for token in forbidden)
