from pathlib import Path


def test_observability_adds_no_network_or_execution_dependencies():
    paths = [Path("src/amrte/core/observability.py"), Path("src/amrte/core/error_management.py")]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    forbidden = ("import requests", "import socket", "MetaTrader", "ccxt", "order_send")
    assert not any(token in source for token in forbidden)


def test_no_external_notification_implementation():
    source = Path("src/amrte/core/observability.py").read_text(encoding="utf-8")
    assert "smtplib" not in source and "http.client" not in source

