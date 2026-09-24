from pathlib import Path


def test_persistence_source_has_no_network_or_market_execution_dependencies():
    paths = [Path("src/amrte/core/persistence.py"), Path("src/amrte/core/recovery.py")]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    forbidden = ("requests", "socket", "MetaTrader", "ccxt", "order_send", "broker_login")
    assert not any(token in combined for token in forbidden)


def test_checkpoint_model_contains_no_broker_fields():
    source = Path("src/amrte/core/persistence_types.py").read_text(encoding="utf-8").lower()
    forbidden = ("broker_account", "broker_order", "leverage", "margin", "magic_number")
    assert not any(token in source for token in forbidden)

