from pathlib import Path

from amrte.core.config_schema import HARD_SAFETY_VALUES
from amrte.core.profiles import PROFILE_DELTAS
from amrte.core.types import ResearchProfile


def test_profiles_are_data_not_code():
    assert set(PROFILE_DELTAS) == set(ResearchProfile)
    assert all(isinstance(delta, type(PROFILE_DELTAS[ResearchProfile.BALANCED])) for delta in PROFILE_DELTAS.values())


def test_no_market_execution_dependencies_added():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in Path("src").rglob("*.py"))
    forbidden = ("import requests", "import socket", "MetaTrader", "ccxt", "order_send", "broker_login")
    assert not any(token in combined for token in forbidden)


def test_hard_safety_values_remain_explicit():
    assert HARD_SAFETY_VALUES["execution.available"] is False
    assert HARD_SAFETY_VALUES["broker.live_execution"] is False
    assert HARD_SAFETY_VALUES["broker.demo_execution"] is False
    assert HARD_SAFETY_VALUES["safety.martingale"] is False
    assert HARD_SAFETY_VALUES["safety.unlimited_exposure"] is False

