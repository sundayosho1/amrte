from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from amrte.market.models import BarState, DataValidity, NormalizedBar, VolumeKind
from amrte.market.observation import (
    CSVBarSourceAdapter,
    CanonicalDatasetReplay,
    InstrumentIdentity,
    ObservationType,
    SourceIdentity,
    ValidationReason,
    ValidationStatus,
    build_canonical_dataset,
    create_canonical_bar,
    observation_from_normalized_bar,
    observation_to_normalized_bar,
    schema_identity,
    validate_canonical_observation,
    verify_dataset_manifest,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)


def source() -> SourceIdentity:
    return SourceIdentity("OFFLINE-P39", "CSV_BAR", "1.0", "PROMPT39_FIXTURE")


def instrument() -> InstrumentIdentity:
    return InstrumentIdentity("FICTIONAL_ALPHA", "SYN_ALPHA", price_precision=4)


def observation(index: int = 0, **changes):
    values = {
        "instrument": instrument(),
        "source": source(),
        "timeframe": "M15",
        "period_start": START + timedelta(minutes=15 * index),
        "period_end": START + timedelta(minutes=15 * (index + 1)),
        "available_at": START + timedelta(minutes=15 * (index + 1)),
        "received_at": START + timedelta(minutes=15 * (index + 1), seconds=5),
        "open": "100.0",
        "high": "102.0",
        "low": "99.0",
        "close": "101.0",
        "volume": "10",
        "volume_kind": "TICK_VOLUME",
        "sequence": index + 1,
    }
    values.update(changes)
    return create_canonical_bar(**values)


def test_schema_identities_are_deterministic_and_distinct():
    assert schema_identity("observation") == schema_identity("observation")
    assert schema_identity("dataset_manifest") == schema_identity("dataset_manifest")
    assert schema_identity("observation") != schema_identity("dataset_manifest")
    with pytest.raises(ValueError):
        schema_identity("unknown")


def test_canonical_bar_uses_bar_close_and_available_at_for_lookahead():
    item = observation()

    assert item.observation_type is ObservationType.BAR
    assert item.period_start == START
    assert item.event_time == START + timedelta(minutes=15)
    assert item.available_at == item.event_time
    assert validate_canonical_observation(item).valid is True

    before_close = START + timedelta(minutes=14, seconds=59)
    with pytest.raises(ValueError) as exc:
        observation(available_at=START + timedelta(minutes=15), logical_time=before_close)
    assert ValidationReason.FUTURE_TIMESTAMP.value in str(exc.value)
    validation = validate_canonical_observation(item, logical_time=before_close)
    assert validation.status is ValidationStatus.INVALID
    assert validation.issues[0].reason is ValidationReason.FUTURE_TIMESTAMP


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"period_end": START}, ValidationReason.INVALID_TIMESTAMP),
        ({"available_at": START + timedelta(minutes=14)}, ValidationReason.AVAILABILITY_VIOLATION),
        ({"received_at": START + timedelta(minutes=14)}, ValidationReason.AVAILABILITY_VIOLATION),
        ({"open": "nan"}, ValidationReason.INVALID_NUMERIC_VALUE),
        ({"high": "100.5"}, ValidationReason.INVALID_OHLC),
        ({"low": "101.5"}, ValidationReason.INVALID_OHLC),
        ({"volume": "-1"}, ValidationReason.INVALID_VOLUME),
        ({"timeframe": "M2"}, ValidationReason.UNSUPPORTED_TIMEFRAME),
    ],
)
def test_invalid_canonical_bars_fail_closed(changes, reason):
    with pytest.raises(ValueError) as exc:
        observation(**changes)
    assert reason.value in str(exc.value)


def test_dataset_manifest_deduplicates_exact_records_and_rejects_revisions():
    first = observation(0)
    duplicate = observation(0)
    revised = observation(0, close="101.5", high="102.5", received_at=START + timedelta(minutes=16))

    duplicate_dataset = build_canonical_dataset((first, duplicate))
    assert duplicate_dataset.diagnostics.status is ValidationStatus.VALID_WITH_WARNINGS
    assert duplicate_dataset.diagnostics.warnings[0].reason is ValidationReason.DUPLICATE
    assert duplicate_dataset.manifest.observation_count == 1
    assert verify_dataset_manifest(duplicate_dataset).valid is True

    revised_dataset = build_canonical_dataset((first, revised))
    assert revised_dataset.diagnostics.status is ValidationStatus.INVALID
    assert revised_dataset.observations == ()
    assert revised_dataset.diagnostics.errors[0].reason is ValidationReason.REVISED_OBSERVATION


def test_dataset_sequence_and_order_diagnostics_are_explicit():
    first = observation(0, sequence=1)
    gap = observation(1, sequence=3)
    out_of_order = build_canonical_dataset((gap, first), strict=False)

    reasons = {issue.reason for issue in (*out_of_order.diagnostics.errors, *out_of_order.diagnostics.warnings)}
    assert ValidationReason.OUT_OF_ORDER in reasons
    assert ValidationReason.SEQUENCE_REGRESSION in reasons

    gap_dataset = build_canonical_dataset((first, gap), strict=False)
    assert gap_dataset.diagnostics.warnings[0].reason is ValidationReason.SEQUENCE_GAP


def test_tampered_observation_identity_or_type_is_rejected():
    item = observation()
    invalid_type = replace(item, observation_type="TICK")
    invalid_id = replace(item, observation_id="not-canonical")

    assert validate_canonical_observation(invalid_type).issues[0].reason is ValidationReason.INVALID_OBSERVATION_TYPE
    assert validate_canonical_observation(invalid_id).status is ValidationStatus.INVALID
    rejected = build_canonical_dataset((invalid_id,))
    assert rejected.diagnostics.status is ValidationStatus.INVALID
    assert rejected.observations == ()


def test_replay_exposes_only_observations_available_as_of_logical_time():
    dataset = build_canonical_dataset((observation(0), observation(1)))
    replay = CanonicalDatasetReplay(dataset)

    assert replay.available_as_of(START + timedelta(minutes=14)) == ()
    assert len(replay.available_as_of(START + timedelta(minutes=15))) == 1
    assert len(replay.available_as_of(START + timedelta(minutes=30))) == 2


def test_csv_adapter_maps_rows_and_reports_record_errors(tmp_path):
    path = tmp_path / "bars.csv"
    path.write_text(
        "instrument,timeframe,period_start,period_end,available_at,received_at,open,high,low,close,volume,volume_kind,sequence\n"
        "SYN_ALPHA,M15,2026-01-01T00:00:00Z,2026-01-01T00:15:00Z,2026-01-01T00:15:00Z,2026-01-01T00:15:05Z,100,102,99,101,10,TICK_VOLUME,1\n"
        "UNKNOWN,M15,2026-01-01T00:15:00Z,2026-01-01T00:30:00Z,2026-01-01T00:30:00Z,2026-01-01T00:30:05Z,101,103,100,102,11,TICK_VOLUME,2\n",
        encoding="utf-8",
    )
    adapter = CSVBarSourceAdapter(source(), {"SYN_ALPHA": instrument()})
    result = adapter.read(path)

    assert len(result.observations) == 1
    assert result.diagnostics.total_records == 2
    assert result.diagnostics.rejected_records == 1
    assert result.diagnostics.errors[0].reason is ValidationReason.UNKNOWN_INSTRUMENT


def test_normalized_bar_compatibility_preserves_existing_market_data_contract():
    bar = NormalizedBar(
        "FICTIONAL_ALPHA",
        "M15",
        START,
        START + timedelta(minutes=15),
        100.0,
        102.0,
        99.0,
        101.0,
        10.0,
        None,
        None,
        BarState.CLOSED_BAR,
        DataValidity.UNKNOWN,
        "row-1",
        volume_kind=VolumeKind.TICK_VOLUME,
    )
    canonical = observation_from_normalized_bar(bar, source=source(), instrument=instrument())
    round_tripped = observation_to_normalized_bar(canonical)

    assert canonical.event_time == bar.close_time
    assert round_tripped.bar_state is BarState.CLOSED_BAR
    assert round_tripped.validity is DataValidity.VALID
    assert round_tripped.bar_id == canonical.observation_id

    forming = replace(bar, close_time=None, bar_state=BarState.CURRENT_FORMING_BAR)
    with pytest.raises(ValueError):
        observation_from_normalized_bar(forming, source=source())
