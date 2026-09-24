from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath

from amrte.app import build_engine
from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink, ProhibitedExecutionProvider
from amrte.market.models import BarState, DataValidity, InstrumentMetadata, NormalizedBar, VolumeKind
from amrte.market.provider import DeterministicMarketDataProvider
from amrte.market.service import MarketDataService


def _bars():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    decision = start + timedelta(hours=4)
    result = []
    for frame, minutes in (("M15", 15), ("H1", 60), ("H4", 240)):
        result.append(NormalizedBar("FICTIONAL_ALPHA", frame, decision - timedelta(minutes=minutes), decision,
            100, 102, 99, 101, 10, None, None, BarState.CLOSED_BAR,
            DataValidity.UNKNOWN, frame, volume_kind=VolumeKind.TICK_VOLUME))
    return tuple(result)


def test_end_to_end_snapshot_observability_and_recovery_metadata():
    engine = build_engine(); audit = engine.audit; start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    metadata = InstrumentMetadata("FICTIONAL_ALPHA", "SYN", supported_timeframes=("M15", "H1", "H4"))
    provider = DeterministicMarketDataProvider("OFFLINE", "DS", "1", _bars(), (metadata,))
    service = MarketDataService(provider, FixedClock(start + timedelta(hours=5)), audit)
    admission = service.validate_and_admit()
    snapshot = service.create_snapshot("FICTIONAL_ALPHA", {"context":"H4","strategy":"H1","execution":"M15"},
        start + timedelta(hours=4), experiment_id="EXP", configuration_snapshot_id=engine.configuration.snapshot_id)
    assert admission.status.name == "ADMITTED" and snapshot is not None
    assert service.recovery_state()["dataset_fingerprint"] == snapshot.dataset_fingerprint
    names = [name for name, _ in audit.events]
    assert "dataset_validated" in names and "snapshot_created" in names


def test_execution_remains_prohibited_after_market_data_activation():
    audit = InMemoryAuditSink(); execution = ProhibitedExecutionProvider(audit)
    assert not execution.submit({"fictional": True}).success


def test_windows_safe_configured_paths_are_relative_and_portable():
    engine = build_engine(); values = engine.configuration.values
    for key in ("market_data.dataset_reference", "market_data.cache_directory", "market_data.temporary_directory"):
        value = values[key]
        assert not Path(value).is_absolute()
        assert not PureWindowsPath(value).is_absolute()
        assert ":" not in value and not value.startswith("/")
