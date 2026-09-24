from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal

import pytest

from amrte.core.clock import FixedClock
from amrte.core.identity import deterministic_id
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.observation import InstrumentIdentity, SourceIdentity, create_canonical_bar
from amrte.research.data_quality_runtime import IngestionEnvelope, TrustedResearchObservation, TrustStatus
from amrte.research.outcome_performance import (
    AnalysisIntent,
    CohortDefinition,
    FutureOutcomeObservation,
    OutcomeWindowState,
    ResearchOutcomePerformanceRuntime,
    ResearchOutcomePolicy,
    research_outcome_attribution_schema_identity,
    research_outcome_policy_identity,
    research_outcome_window_schema_identity,
    research_performance_snapshot_schema_identity,
)
from Tests.Unit.test_events import NOW
from Tests.Unit.test_research_evidence_ledger import ledger, p46_result
from Tests.Unit.test_research_decision_runtime import DATASET_FINGERPRINT, DATASET_ID, protected_snapshot


INSTRUMENT = "AMRTE.TEST"
TIMEFRAME = "M15"


def runtime(tmp_path, *, max_items=64):
    target = ledger(tmp_path)
    return ResearchOutcomePerformanceRuntime(
        clock=FixedClock(NOW + timedelta(hours=1)),
        audit=InMemoryAuditSink(),
        evidence_ledger=target,
        storage_root=tmp_path / "p48",
        maximum_windows=max_items,
        maximum_attributions=max_items,
        maximum_snapshots=max_items,
    ), target


def evidence_record(target, index=0, *, classification_reason=(), snapshot=None):
    result = p46_result(index, snapshot=snapshot)
    reasons = tuple(result.decision.reason_codes) + (
        f"INSTRUMENT:{INSTRUMENT}",
        f"TIMEFRAME:{TIMEFRAME}",
        "DIRECTION:LONG",
        "STRATEGY:S1@1",
        "IMPLEMENTATION:S1-IMPL-1",
        "CANDIDATE:CAND-1",
        "REGIME:TREND",
        "REALIZED_REGIME:RANGE",
        "SESSION:GLOBAL_WEEKDAY",
        "SCORE:0.70",
        *classification_reason,
    )
    decision = replace(result.decision, reason_codes=reasons)
    return target.commit_decision_evidence(result.context, decision, result.trace).record


def future_observation(record, index, close, *, high=None, low=None, available_offset=2, event_offset=None, trust=TrustStatus.TRUSTED):
    event = record.knowledge_cutoff_utc + timedelta(minutes=15 * (event_offset or index))
    start = event - timedelta(minutes=15)
    available = event + timedelta(seconds=available_offset)
    received = available + timedelta(seconds=1)
    source = SourceIdentity("SRC-P48", "fixture", "1", DATASET_ID)
    observation = create_canonical_bar(
        instrument=InstrumentIdentity(INSTRUMENT, INSTRUMENT),
        source=source,
        timeframe=TIMEFRAME,
        period_start=start,
        period_end=event,
        available_at=available,
        received_at=received,
        open=Decimal(str(close)),
        high=Decimal(str(high if high is not None else close)),
        low=Decimal(str(low if low is not None else close)),
        close=Decimal(str(close)),
        sequence=index,
        logical_time=received,
    )
    envelope = IngestionEnvelope(
        deterministic_id("p48_future_ingestion", observation.observation_id),
        observation.observation_id,
        observation.observation_fingerprint,
        record.dataset_id,
        record.dataset_fingerprint,
        source.source_id,
        observation.schema_version,
        "P40_DATA_QUALITY_TRUST_DEFAULT",
        record.recovery_epoch,
        received,
        "REPLAY",
    )
    trusted = TrustedResearchObservation(
        deterministic_id("p48_trusted_future", observation.observation_id),
        envelope,
        "QUALITY-P48",
        "RELIABILITY-P48",
        "TEMPORAL-P48",
        "SOURCE-HEALTH-P48",
        trust,
        received,
        (),
        (),
        False,
    )
    return FutureOutcomeObservation.from_canonical(observation, trusted, logical_time=received)


def future_path(record, values=(101, 103, 104)):
    return tuple(future_observation(record, i + 1, value, high=value + 1, low=value - 1) for i, value in enumerate(values))


def mature_attribution(target, record, values=(101, 103, 104), reference=Decimal("100")):
    observations = future_path(record, values)
    window = target.update_window(record, observations, evaluation_time=observations[-1].received_at)
    attribution = target.attribute(record, window, observations, historical_reference_value=reference)
    return window, attribution


def test_p48_schema_policy_identities_are_deterministic():
    assert research_outcome_window_schema_identity() == research_outcome_window_schema_identity()
    assert research_outcome_attribution_schema_identity() == research_outcome_attribution_schema_identity()
    assert research_performance_snapshot_schema_identity() == research_performance_snapshot_schema_identity()
    assert research_outcome_policy_identity() == ResearchOutcomePolicy.current().policy_identity
    assert len({research_outcome_window_schema_identity(), research_outcome_attribution_schema_identity(), research_performance_snapshot_schema_identity()}) == 3


def test_outcome_window_is_deterministic_immutable_and_maturity_explicit(tmp_path):
    target, p47 = runtime(tmp_path)
    record = evidence_record(p47)
    pending = target.open_window(record)
    partial = target.update_window(record, future_path(record, (101, 102))[:2])
    mature = target.update_window(record, future_path(record))

    assert pending.coverage_state == OutcomeWindowState.PENDING.value
    assert partial.coverage_state == OutcomeWindowState.PARTIALLY_OBSERVED.value
    assert mature.coverage_state == OutcomeWindowState.MATURE.value
    assert mature.window_id == target.update_window(record, future_path(record)).window_id
    with pytest.raises(FrozenInstanceError):
        mature.coverage_state = "MUTATED"


def test_temporal_firewall_rejects_future_to_past_and_not_yet_available_data(tmp_path):
    target, p47 = runtime(tmp_path)
    record = evidence_record(p47)
    before_cutoff = future_observation(record, 1, 101, event_offset=-1)
    invalid = target.update_window(record, (before_cutoff,), evaluation_time=NOW + timedelta(hours=1))
    assert invalid.coverage_state == OutcomeWindowState.INVALID.value
    assert "P48_FUTURE_TO_PAST_CONTAMINATION" in invalid.invalid_reasons

    not_available = future_observation(record, 2, 102, available_offset=600)
    invalid_available = target.update_window(record, (not_available,), evaluation_time=not_available.event_time)
    assert "P48_OBSERVATION_NOT_AVAILABLE_AT_EVALUATION_TIME" in invalid_available.invalid_reasons


def test_invalid_trust_and_cross_dataset_future_data_fail_closed(tmp_path):
    target, p47 = runtime(tmp_path)
    record = evidence_record(p47)
    with pytest.raises(ValueError):
        future_observation(record, 1, 101, trust=TrustStatus.REJECTED)

    other = replace(future_observation(record, 1, 101), dataset_fingerprint="OTHER")
    window = target.update_window(record, (other,))
    assert window.coverage_state == OutcomeWindowState.INVALID.value
    assert "P48_DATASET_ISOLATION_MISMATCH" in window.invalid_reasons


def test_attribution_identity_lineage_excursion_and_hypothesis_are_deterministic(tmp_path):
    target, p47 = runtime(tmp_path)
    record = evidence_record(p47)
    window, attribution = mature_attribution(target, record)
    duplicate = target.attribute(record, window, future_path(record), historical_reference_value=Decimal("100"))

    assert duplicate.attribution_id == attribution.attribution_id
    assert attribution.evidence_record_id == record.evidence_record_id
    assert attribution.decision_id == record.decision_id
    assert attribution.trace_id == record.trace_id
    assert attribution.normalized_research_change == Decimal("0.04000000")
    assert attribution.favorable_adverse_excursion.maximum_favorable == Decimal("0.05000000")
    assert attribution.hypothesis_outcome == "SUPPORTED"
    assert attribution.causal_claim is False
    assert attribution.financial_execution == "NONE"


def test_directionless_decision_does_not_invent_excursion_or_return(tmp_path):
    target, p47 = runtime(tmp_path)
    record = evidence_record(p47)
    record = replace(record, reason_codes=tuple(reason for reason in record.reason_codes if reason != "DIRECTION:LONG"))
    observations = future_path(record)
    window = target.update_window(record, observations, evaluation_time=observations[-1].received_at)
    attribution = target.attribute(record, window, observations, historical_reference_value=Decimal("100"))
    assert attribution.research_direction == "DIRECTIONLESS"
    assert attribution.normalized_research_change is None
    assert attribution.favorable_adverse_excursion.applicability == "NOT_APPLICABLE"


def test_no_action_restricted_rejected_failed_and_protection_analysis_are_first_class(tmp_path):
    target, p47 = runtime(tmp_path, max_items=16)
    records = [
        evidence_record(p47, 1, classification_reason=("NO_ACTION_CONFLICT",)),
        evidence_record(p47, 2, snapshot=protected_snapshot(reliability_stage="WATCH")),
        evidence_record(p47, 3, snapshot=protected_snapshot(system_safety_state="EMERGENCY_STOP")),
    ]
    for record in records:
        mature_attribution(target, record)
    snapshot = target.publish_snapshot()

    assert snapshot.classification_distribution["ELIGIBLE_RESEARCH"] >= 1
    assert snapshot.restriction_statistics["causal_claim"] is False
    assert snapshot.protection_statistics
    assert "RestrictionOutcome != ProvenCausalProtection" not in snapshot.warnings


def test_cohort_sufficiency_missingness_and_denominator_integrity(tmp_path):
    target, p47 = runtime(tmp_path)
    record = evidence_record(p47)
    target.open_window(record)
    mature_attribution(target, record)
    cohort = CohortDefinition.create(("decision_classification",), target.policy, analysis_intent=AnalysisIntent.PREDEFINED)
    snapshot = target.publish_snapshot(cohort_definitions=(cohort,))

    assert snapshot.decision_count == 1
    assert snapshot.mature_outcome_count == 1
    assert snapshot.missing_count == 1
    assert snapshot.outcome_statistics[0].sample_count == 1
    assert snapshot.outcome_statistics[0].sufficiency_state == "INSUFFICIENT_EVIDENCE"
    assert "P48_INSUFFICIENT_SAMPLE" in snapshot.warnings


def test_recovery_restart_replay_and_incremental_full_rebuild_equivalence(tmp_path):
    target, p47 = runtime(tmp_path)
    record = evidence_record(p47)
    mature_attribution(target, record)
    target.publish_snapshot()
    fingerprint = target.replay_fingerprint()
    state = target.recovery_state(7)

    restored, _ = runtime(tmp_path / "restored")
    assert restored.restore(state, 7)
    assert restored.replay_fingerprint() == fingerprint
    assert restored.incremental_equals_full_rebuild()
    assert not restored.restore(replace(state, policy_identity="DIFFERENT"), 7)
    assert restored.recovery_restricted


def test_outcome_revision_supersession_preserves_original_provenance(tmp_path):
    target, p47 = runtime(tmp_path)
    record = evidence_record(p47)
    window, original = mature_attribution(target, record, values=(101, 102, 103))
    revised = target.attribute(
        record,
        window,
        future_path(record, (101, 102, 103)),
        historical_reference_value=Decimal("100"),
        supersedes_attribution_id=original.attribution_id,
        revised_dataset_fingerprint="FP-P46-REV2",
    )
    assert revised.supersedes_attribution_id == original.attribution_id
    assert revised.original_dataset_fingerprint == DATASET_FINGERPRINT
    assert revised.revised_dataset_fingerprint == "FP-P46-REV2"
    assert original.revised_dataset_fingerprint is None


def test_runtime_diagnostics_and_forbidden_permission_surface(tmp_path):
    target, p47 = runtime(tmp_path)
    record = evidence_record(p47)
    mature_attribution(target, record)
    diagnostics = target.diagnostics()
    assert diagnostics["p47_ledger_verification"] == "VERIFIED"
    assert diagnostics["financial_execution"] == "NONE"
    forbidden = {"place_order", "submit_trade", "promote_strategy", "tune_parameters", "authorize_execution", "mutate_configuration"}
    assert forbidden.isdisjoint(set(dir(target)))
