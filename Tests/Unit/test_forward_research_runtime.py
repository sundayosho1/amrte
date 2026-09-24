from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.observation import (
    InstrumentIdentity,
    ObservationProvenance,
    SourceIdentity,
    build_canonical_dataset,
    create_canonical_bar,
)
from amrte.research.controlled_experimentation import (
    ConfigurationStatus,
    VERSIONED_RESEARCH_CONFIGURATION_SCHEMA_VERSION,
    VersionedResearchConfiguration,
    versioned_research_configuration_schema_identity,
)
from amrte.research.forward_runtime import (
    ForwardDriftState,
    ForwardObservationEffect,
    ForwardResearchRuntime,
    ShadowComparisonState,
    SourceLifecycleState,
    forward_drift_snapshot_schema_identity,
    forward_observation_envelope_schema_identity,
    forward_research_decision_record_schema_identity,
    forward_research_policy_identity,
    forward_research_session_schema_identity,
    shadow_research_comparison_schema_identity,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
P50_VERSIONED_CONFIGURATION_IDENTITY = "311db48f0dba3ef1835c9bbbe7d74451c947dd211946f6ac078594686acbb5ca"


def runtime() -> ForwardResearchRuntime:
    return ForwardResearchRuntime(clock=FixedClock(START), audit=InMemoryAuditSink())


def approved_configuration(**changes) -> VersionedResearchConfiguration:
    values = {
        "research_configuration_id": "P50-CONFIG-APPROVED",
        "schema_version": VERSIONED_RESEARCH_CONFIGURATION_SCHEMA_VERSION,
        "schema_identity": versioned_research_configuration_schema_identity(),
        "configuration_version": "CONFIG-A@research-v1",
        "parent_configuration_id": "CONFIG-A",
        "experiment_id": "EXP-P51",
        "promotion_decision_id": "PROMOTION-P51",
        "source_improvement_candidate_id": "CAND-P51",
        "resolved_configuration": {"strategies.s1_trend_pullback.minimum_adx": 21.0},
        "configuration_delta": {"strategies.s1_trend_pullback.minimum_adx": 1.0},
        "configuration_fingerprint": "P50-CONFIG-FP",
        "created_at_logical": START,
        "approval_evidence_refs": ("EXP-P51", "RESULT-P51", "PROMOTION-P51"),
        "status": ConfigurationStatus.APPROVED_RESEARCH.value,
        "configuration_lineage": ("CONFIG-A", "P50-CONFIG-APPROVED"),
        "configuration_fingerprint_authority": "P50-CONFIG-AUTHORITY",
    }
    values.update(changes)
    return VersionedResearchConfiguration(**values)


def source() -> SourceIdentity:
    return SourceIdentity("SRC-P51", "CSV_BAR", "1.0", "P51_FIXTURE", "1")


def instrument() -> InstrumentIdentity:
    return InstrumentIdentity("FICTIONAL_P51", "SYN_P51")


def observation(index: int = 0, *, sequence: int | None = None, close: str | int = "101", **changes):
    start = START + timedelta(minutes=15 * index)
    values = {
        "instrument": instrument(),
        "source": source(),
        "timeframe": "M15",
        "period_start": start,
        "period_end": start + timedelta(minutes=15),
        "available_at": start + timedelta(minutes=15),
        "received_at": start + timedelta(minutes=15, seconds=1),
        "open": "100",
        "high": str(max(Decimal(str(close)), Decimal("100")) + Decimal("1")),
        "low": "99",
        "close": str(close),
        "volume": "10",
        "volume_kind": "TICK_VOLUME",
        "sequence": index + 1 if sequence is None else sequence,
        "provenance": ObservationProvenance(
            source_record_locator=f"row:{index}:{sequence if sequence is not None else index + 1}",
            raw_record_fingerprint=f"raw-{index}-{sequence if sequence is not None else index + 1}",
            transformations=("csv_field_mapping",),
        ),
    }
    values.update(changes)
    return create_canonical_bar(**values)


def dataset(count: int = 8):
    return build_canonical_dataset(tuple(observation(index) for index in range(count)))


def started(target: ForwardResearchRuntime, data=None):
    data = data or dataset()
    return target.start_session(
        approved_configuration(),
        data,
        historical_cutoff_utc=START - timedelta(seconds=1),
        as_of=START,
    ), data


def feed_history(target: ForwardResearchRuntime, session_id: str, data, count: int = 7):
    records = []
    for item in data.observations[:count]:
        records.append(
            target.ingest_observation(
                session_id,
                item,
                dataset=data,
                logical_time=item.available_at,
                baseline_shadow_value=item.bar.close,
            )
        )
    return records


def test_schema_policy_and_upstream_identities_are_stable():
    assert versioned_research_configuration_schema_identity() == P50_VERSIONED_CONFIGURATION_IDENTITY
    assert forward_research_policy_identity() == forward_research_policy_identity()
    assert forward_research_session_schema_identity() == forward_research_session_schema_identity()
    assert forward_observation_envelope_schema_identity() == forward_observation_envelope_schema_identity()
    assert forward_research_decision_record_schema_identity() == forward_research_decision_record_schema_identity()
    assert shadow_research_comparison_schema_identity() == shadow_research_comparison_schema_identity()
    assert forward_drift_snapshot_schema_identity() == forward_drift_snapshot_schema_identity()


def test_session_freezes_approved_p50_configuration_without_mutation():
    target = runtime()
    data = dataset()
    config = approved_configuration()
    session = target.start_session(config, data, historical_cutoff_utc=START - timedelta(seconds=1), as_of=START)

    assert session.research_configuration_id == config.research_configuration_id
    assert session.configuration_fingerprint == config.configuration_fingerprint
    assert session.configuration_status == ConfigurationStatus.APPROVED_RESEARCH.value
    assert session.financial_execution == "NONE"
    assert dict(config.resolved_configuration)["strategies.s1_trend_pullback.minimum_adx"] == 21.0
    with pytest.raises(FrozenInstanceError):
        session.configuration_fingerprint = "mutated"
    with pytest.raises(ValueError, match="P51_CONFIGURATION_NOT_APPROVED_RESEARCH"):
        target.start_session(replace(config, status=ConfigurationStatus.CANDIDATE.value), data, historical_cutoff_utc=START)
    with pytest.raises(ValueError, match="P51_FINANCIAL_EXECUTION_FORBIDDEN"):
        target.start_session(replace(config, financial_execution="SIMULATED"), data, historical_cutoff_utc=START)


def test_forward_ingestion_uses_p40_for_dedupe_gap_backfill_and_decisions():
    target = runtime()
    session, data = started(target)
    feed_history(target, session.session_id, data, 7)

    accepted = [item for item in target.envelopes.values() if item.effect == ForwardObservationEffect.ACCEPTED.value]
    assert accepted
    assert target.sessions[session.session_id].accepted_decision_count == len(target.decisions)
    assert all(item.financial_execution == "NONE" for item in target.decisions.values())

    duplicate_envelope, duplicate_decision = target.ingest_observation(
        session.session_id,
        data.observations[6],
        dataset=data,
        logical_time=data.observations[6].available_at,
    )
    assert duplicate_envelope.effect == ForwardObservationEffect.DUPLICATE.value
    assert duplicate_envelope.duplicate is True
    assert duplicate_decision is None

    gap = observation(7, sequence=10, close="104")
    gap_envelope, gap_decision = target.ingest_observation(session.session_id, gap, dataset=data, logical_time=gap.available_at)
    assert gap_envelope.gap_detected is True
    assert "P51_SEQUENCE_GAP" in gap_envelope.warning_codes
    assert gap_decision is not None

    backfill = observation(3, sequence=11, close="103.5")
    backfill_envelope, backfill_decision = target.ingest_observation(session.session_id, backfill, dataset=data, logical_time=gap.available_at)
    assert backfill_envelope.backfill is True
    assert backfill_envelope.effect == ForwardObservationEffect.REJECTED.value
    assert any("OUT_OF_ORDER" in reason for reason in backfill_envelope.reason_codes)
    assert backfill_decision is None

    current = target.sessions[session.session_id]
    assert current.duplicate_observation_count == 1
    assert current.gap_count == 1
    assert current.backfill_count == 1
    assert current.source_lifecycle_state == SourceLifecycleState.RESTRICTED.value


def test_shadow_comparison_and_drift_are_forward_only_research_evidence():
    target = runtime()
    session, data = started(target, dataset(12))
    feed_history(target, session.session_id, data, 12)
    decision = next(reversed(target.decisions.values()))

    match = target.compare_shadow_decision(decision.decision_id, decision.forward_signal_value)
    diverged = target.compare_shadow_decision(decision.decision_id, decision.forward_signal_value + Decimal("1"))
    stable = target.detect_drift(session.session_id, baseline_mean=Decimal("101.0"), threshold=Decimal("1.0"))
    drifted = target.detect_drift(session.session_id, baseline_mean=Decimal("90.0"), threshold=Decimal("1.0"))

    assert match.state == ShadowComparisonState.MATCH.value
    assert diverged.state == ShadowComparisonState.DIVERGED.value
    assert stable.state == ForwardDriftState.STABLE.value
    assert drifted.state == ForwardDriftState.DRIFTED.value
    assert {match.financial_execution, diverged.financial_execution, stable.financial_execution, drifted.financial_execution} == {"NONE"}


def test_recovery_round_trip_preserves_replay_and_epoch_identity():
    target = runtime()
    session, data = started(target)
    feed_history(target, session.session_id, data, 7)
    target.detect_drift(session.session_id, baseline_mean=Decimal("101.0"))
    state = target.recovery_state(4)
    before = target.replay_fingerprint()

    restored = runtime()
    assert restored.restore(state, 4)
    assert restored.replay_fingerprint() == before
    assert restored.recovery_restricted is False

    rejected = runtime()
    assert rejected.restore(state, 5) is False
    assert rejected.recovery_restricted is True


def test_historical_or_mismatched_observations_fail_closed_without_decisions():
    target = runtime()
    session, data = started(target)
    old = observation(0, sequence=1)
    historical_session = target.start_session(
        approved_configuration(research_configuration_id="P50-CONFIG-APPROVED-2"),
        data,
        historical_cutoff_utc=old.event_time,
        as_of=START,
    )
    envelope, decision = target.ingest_observation(
        historical_session.session_id,
        old,
        dataset=data,
        logical_time=old.available_at,
    )

    assert envelope.effect == ForwardObservationEffect.REJECTED.value
    assert "P51_NOT_FORWARD_OBSERVATION" in envelope.reason_codes
    assert decision is None
