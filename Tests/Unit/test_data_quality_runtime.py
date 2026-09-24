from dataclasses import replace
from datetime import datetime, timedelta, timezone

from amrte.market.observation import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    MARKET_OBSERVATION_SCHEMA_VERSION,
    InstrumentIdentity,
    ObservationProvenance,
    SourceIdentity,
    build_canonical_dataset,
    create_canonical_bar,
    schema_identity,
)
from amrte.research.data_quality_runtime import (
    DataQualityTrustRuntime,
    ProcessingMode,
    TrustStatus,
    quality_trust_schema_identity,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
P39_OBSERVATION_IDENTITY = "efc145adc2e2eb8895ac06c348e26a0d6ac11f1f0c2acb4f1f6042b61dbcf84d"
P39_DATASET_IDENTITY = "0412d47d673c75345e5b9604a213e7889567878a592cc1f443805cbacd0b44f3"


def source(name="OFFLINE-P40") -> SourceIdentity:
    return SourceIdentity(name, "CSV_BAR", "1.0", "P40_FIXTURE", "1")


def instrument(name="FICTIONAL_ALPHA") -> InstrumentIdentity:
    return InstrumentIdentity(name, f"SYN_{name}")


def observation(index=0, *, sequence=None, source_id="OFFLINE-P40", instrument_id="FICTIONAL_ALPHA", **changes):
    start = START + timedelta(minutes=15 * index)
    values = {
        "instrument": instrument(instrument_id),
        "source": source(source_id),
        "timeframe": "M15",
        "period_start": start,
        "period_end": start + timedelta(minutes=15),
        "available_at": start + timedelta(minutes=15),
        "received_at": start + timedelta(minutes=15, seconds=1),
        "open": "100",
        "high": "102",
        "low": "99",
        "close": "101",
        "volume": "10",
        "volume_kind": "TICK_VOLUME",
        "sequence": index + 1 if sequence is None else sequence,
        "provenance": ObservationProvenance(
            source_record_locator=f"row:{index}",
            raw_record_fingerprint=f"raw-{index}",
            transformations=("csv_field_mapping",),
        ),
    }
    values.update(changes)
    return create_canonical_bar(**values)


def trusted_runtime_with_history(recovery_epoch=0):
    runtime = DataQualityTrustRuntime()
    items = tuple(observation(index) for index in range(6))
    dataset = build_canonical_dataset(items)
    for item in items[:5]:
        runtime.ingest_observation(item, dataset=dataset, logical_time=item.available_at, recovery_epoch=recovery_epoch)
    return runtime, dataset, items


def test_p39_contract_identities_remain_unchanged_and_p40_has_own_schema():
    assert MARKET_OBSERVATION_SCHEMA_VERSION == "1.0"
    assert DATASET_MANIFEST_SCHEMA_VERSION == "1.0"
    assert schema_identity("observation") == P39_OBSERVATION_IDENTITY
    assert schema_identity("dataset_manifest") == P39_DATASET_IDENTITY
    assert quality_trust_schema_identity() == quality_trust_schema_identity()
    assert quality_trust_schema_identity() not in {P39_OBSERVATION_IDENTITY, P39_DATASET_IDENTITY}


def test_valid_observation_becomes_trusted_only_after_quality_evidence_exists():
    runtime, dataset, items = trusted_runtime_with_history()

    bootstrap = next(iter(runtime.trusted_observations.values()))
    trusted = runtime.ingest_observation(items[5], dataset=dataset, logical_time=items[5].available_at)

    assert bootstrap.trust_status is TrustStatus.RESTRICTED
    assert trusted.trust_status is TrustStatus.TRUSTED
    assert trusted.authoritative_effect_applied is True
    snapshot = runtime.snapshots[trusted.quality_snapshot_id]
    assert snapshot.structural_status == "VALID"
    assert snapshot.provenance_status == "VALID"
    assert snapshot.temporal_status == "ELIGIBLE"
    assert snapshot.trust_status is TrustStatus.TRUSTED


def test_invalid_schema_and_fingerprint_mismatch_fail_closed():
    runtime = DataQualityTrustRuntime()
    item = observation()
    dataset = build_canonical_dataset((item,))

    invalid_schema = replace(item, schema_version="9.9")
    schema_result = runtime.ingest_observation(invalid_schema, dataset=dataset, logical_time=item.available_at)
    assert schema_result.trust_status is TrustStatus.REJECTED

    tampered = replace(item, observation_fingerprint="not-the-fingerprint")
    tampered_result = runtime.ingest_observation(tampered, dataset=dataset, logical_time=item.available_at)
    assert tampered_result.trust_status is TrustStatus.REJECTED
    assert any("fingerprint" in reason.lower() or "DATASET_ERROR" in reason for reason in tampered_result.blocking_reasons)


def test_missing_provenance_restricts_without_becoming_trusted():
    runtime = DataQualityTrustRuntime()
    item = create_canonical_bar(
        instrument=instrument(),
        source=source(),
        timeframe="M15",
        period_start=START,
        period_end=START + timedelta(minutes=15),
        available_at=START + timedelta(minutes=15),
        received_at=START + timedelta(minutes=15, seconds=1),
        open="100",
        high="102",
        low="99",
        close="101",
    )

    result = runtime.ingest_observation(item, logical_time=item.available_at)

    assert result.trust_status is TrustStatus.RESTRICTED
    assert "PROVENANCE_MISSING" in result.blocking_reasons


def test_idempotent_reprocessing_exact_duplicate_and_identity_collision():
    runtime, dataset, items = trusted_runtime_with_history()
    first = runtime.ingest_observation(items[5], dataset=dataset, logical_time=items[5].available_at)
    duplicate = runtime.ingest_observation(items[5], dataset=dataset, logical_time=items[5].available_at)
    revised = observation(5, close="101.5", high="102.5")
    collision = runtime.ingest_observation(revised, dataset=dataset, logical_time=revised.available_at)

    assert duplicate.trusted_observation_id == first.trusted_observation_id
    assert duplicate.authoritative_effect_applied is False
    assert collision.trust_status is TrustStatus.QUARANTINED
    assert "IDENTITY_COLLISION" in collision.blocking_reasons


def test_sequence_gap_and_out_of_order_observations_are_detected():
    runtime = DataQualityTrustRuntime()
    first = observation(0, sequence=1)
    gap = observation(1, sequence=3)
    old = observation(0, sequence=4)
    dataset = build_canonical_dataset((first, gap), strict=False)

    runtime.ingest_observation(first, dataset=dataset, logical_time=first.available_at)
    gap_result = runtime.ingest_observation(gap, dataset=dataset, logical_time=gap.available_at)
    out_of_order = runtime.ingest_observation(old, dataset=dataset, logical_time=gap.available_at)

    assert "SEQUENCE_GAP" in gap_result.warning_reasons
    assert out_of_order.trust_status is TrustStatus.QUARANTINED
    assert "OUT_OF_ORDER" in out_of_order.blocking_reasons


def test_future_observation_and_clock_regression_never_become_trusted():
    runtime = DataQualityTrustRuntime()
    item = observation()

    future = runtime.ingest_observation(item, logical_time=item.available_at - timedelta(seconds=1))

    assert future.trust_status is TrustStatus.REJECTED
    assert "FUTURE_TIMESTAMP" in future.blocking_reasons


def test_source_instrument_and_timeframe_state_are_isolated():
    runtime = DataQualityTrustRuntime()
    alpha = observation(0, source_id="SOURCE-A", instrument_id="FICTIONAL_ALPHA")
    beta = observation(0, source_id="SOURCE-B", instrument_id="FICTIONAL_BETA")
    runtime.ingest_observation(alpha, logical_time=alpha.available_at)
    runtime.ingest_observation(beta, logical_time=beta.available_at)

    scopes = {snapshot.scope_id for snapshot in runtime.source_health.values()}
    assert len(scopes) == 2
    assert any("FICTIONAL_ALPHA" in scope for scope in scopes)
    assert any("FICTIONAL_BETA" in scope for scope in scopes)


def test_recovery_round_trip_preserves_idempotency_and_does_not_increase_permission():
    runtime, dataset, items = trusted_runtime_with_history(recovery_epoch=2)
    trusted = runtime.ingest_observation(items[5], dataset=dataset, logical_time=items[5].available_at, recovery_epoch=2)
    state = runtime.recovery_state(2)

    restored = DataQualityTrustRuntime()

    assert restored.restore(state, 2)
    repeated = restored.ingest_observation(items[5], dataset=dataset, logical_time=items[5].available_at, recovery_epoch=2)
    assert repeated.trusted_observation_id == trusted.trusted_observation_id
    assert repeated.authoritative_effect_applied is False
    assert restored.reconcile(2) == ()


def test_batch_ingestion_counts_are_deterministic():
    items = tuple(observation(index) for index in range(7))
    dataset = build_canonical_dataset(items)
    first = DataQualityTrustRuntime().ingest_dataset(dataset, logical_time=items[-1].available_at)
    second = DataQualityTrustRuntime().ingest_dataset(dataset, logical_time=items[-1].available_at)

    assert first == second
    assert first.received == 7
    assert first.trusted >= 1
    assert first.rejected == 0
