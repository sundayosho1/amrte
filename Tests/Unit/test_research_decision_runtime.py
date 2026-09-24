from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.portfolio.research_portfolio_runtime import ResearchPortfolioRuntime
from amrte.research.decision_runtime import (
    FinalResearchClassification,
    MasterResearchDecisionOrchestrator,
    ResearchDecisionAcceptance,
    ResearchProcessingContext,
    final_research_decision_schema_identity,
    research_decision_trace_schema_identity,
    research_processing_context_schema_identity,
    stage_records_for_protection_snapshot,
)
from amrte.research.protection_runtime import ResearchProtectionRuntime
from amrte.strategies.framework import DetectionState
from Tests.Unit.test_events import NOW
from Tests.Unit.test_research_portfolio_runtime import contexts_for, p43_assessment_for
from Tests.Unit.test_research_protection_runtime import healthy_evidence, p44_snapshot, unrestricted_p44
from Tests.Unit.test_strategy_framework import TestStrategy


DATASET_ID = "DS-P46"
DATASET_FINGERPRINT = "FP-P46"


def protected_snapshot(*, p44=None, **evidence_overrides):
    p44 = p44 or unrestricted_p44(p44_snapshot())
    runtime = ResearchProtectionRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    return runtime.assess(p44, healthy_evidence(p44, dataset_id=DATASET_ID, dataset_fingerprint=DATASET_FINGERPRINT, **evidence_overrides)).snapshot


def context_for(snapshot, records=None):
    records = records or stage_records_for_protection_snapshot(
        snapshot,
        dataset_id=DATASET_ID,
        dataset_fingerprint=DATASET_FINGERPRINT,
    )
    return ResearchProcessingContext.create(
        created_at_utc=NOW,
        dataset_id=DATASET_ID,
        dataset_fingerprint=DATASET_FINGERPRINT,
        knowledge_cutoff_utc=snapshot.knowledge_cutoff_utc,
        configuration_identity=snapshot.configuration_identity,
        recovery_epoch=snapshot.recovery_epoch,
        p45_protection_snapshot_id=snapshot.protection_snapshot_id,
        stage_records=records,
    )


def decide(snapshot, context=None):
    runtime = MasterResearchDecisionOrchestrator(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    return runtime, runtime.decide(context or context_for(snapshot), snapshot)


def test_schema_identities_are_deterministic_and_distinct():
    assert research_processing_context_schema_identity() == research_processing_context_schema_identity()
    assert final_research_decision_schema_identity() == final_research_decision_schema_identity()
    assert research_decision_trace_schema_identity() == research_decision_trace_schema_identity()
    assert len(
        {
            research_processing_context_schema_identity(),
            final_research_decision_schema_identity(),
            research_decision_trace_schema_identity(),
        }
    ) == 3


def test_allowed_p45_snapshot_becomes_research_eligible_not_authorized():
    snapshot = protected_snapshot()
    runtime, result = decide(snapshot)

    assert result.acceptance is ResearchDecisionAcceptance.ACCEPTED
    assert result.decision.final_classification == FinalResearchClassification.ELIGIBLE_RESEARCH.value
    assert result.decision.effective_permission == "ALLOWED"
    assert result.decision.trade_authorization == "NONE"
    assert result.decision.financial_authorization == "NONE"
    assert result.decision.financial_execution == "NONE"
    assert runtime.diagnostics()["financial_execution"] == "NONE"
    with pytest.raises(FrozenInstanceError):
        result.decision.final_classification = "TRADE"


def test_p45_blocked_cannot_become_positive():
    snapshot = protected_snapshot(system_safety_state="EMERGENCY_STOP")
    _, result = decide(snapshot)

    assert snapshot.effective_permission == "BLOCKED"
    assert result.decision.final_classification == FinalResearchClassification.REJECTED.value
    assert "ELIGIBLE_RESEARCH" not in result.decision.reason_codes


def test_p45_restricted_cannot_become_unrestricted():
    snapshot = protected_snapshot(reliability_stage="WATCH")
    _, result = decide(snapshot)

    assert snapshot.effective_permission == "RESTRICTED"
    assert result.decision.final_classification == FinalResearchClassification.RESTRICTED.value


def test_upstream_no_action_remains_non_positive_final_decision():
    p42, _, evaluation_set, assessment = p43_assessment_for(
        TestStrategy("NO_ACTION", detect=DetectionState.NOT_DETECTED)
    )
    p44 = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink()).assess(
        assessment,
        contexts_for(p42, evaluation_set, assessment),
    ).snapshot
    snapshot = protected_snapshot(p44=p44)
    _, result = decide(snapshot)

    assert p44.portfolio_research_state == "NO_ACTION"
    assert result.decision.final_classification == FinalResearchClassification.NO_ACTION.value
    assert result.decision.trade_authorization == "NONE"


def test_missing_stage_evidence_fails_closed():
    snapshot = protected_snapshot()
    records = tuple(item for item in stage_records_for_protection_snapshot(snapshot, dataset_id=DATASET_ID, dataset_fingerprint=DATASET_FINGERPRINT) if item.stage != "P40_QUALITY_TRUST")
    _, result = decide(snapshot, context_for(snapshot, records))

    assert result.decision.final_classification == FinalResearchClassification.FAILED.value
    assert "P46_STAGE_EVIDENCE_INCOMPLETE" in result.decision.reason_codes
    assert result.trace.core_trace.short_circuited_at is not None


def test_stage_order_violation_fails_closed():
    snapshot = protected_snapshot()
    records = list(stage_records_for_protection_snapshot(snapshot, dataset_id=DATASET_ID, dataset_fingerprint=DATASET_FINGERPRINT))
    records[0], records[1] = records[1], records[0]
    _, result = decide(snapshot, context_for(snapshot, tuple(records)))

    assert result.decision.final_classification == FinalResearchClassification.FAILED.value
    assert "P46_STAGE_ORDER_VIOLATION" in result.decision.reason_codes


def test_stage_schema_and_temporal_mismatch_fail_closed():
    snapshot = protected_snapshot()
    records = list(stage_records_for_protection_snapshot(snapshot, dataset_id=DATASET_ID, dataset_fingerprint=DATASET_FINGERPRINT))
    records[3] = replace(records[3], schema_identity="bad-schema")
    records[4] = replace(records[4], as_of_timestamp_utc=snapshot.knowledge_cutoff_utc + timedelta(seconds=1))
    _, result = decide(snapshot, context_for(snapshot, tuple(records)))

    assert result.decision.final_classification == FinalResearchClassification.FAILED.value
    assert "P46_P41_MARKET_INTELLIGENCE_SCHEMA_MISMATCH" in result.decision.reason_codes
    assert "P46_TEMPORAL_ORDER_VIOLATION" in result.decision.reason_codes


def test_idempotency_ledger_and_recovery_preserve_duplicate_decision():
    snapshot = protected_snapshot()
    context = context_for(snapshot)
    runtime = MasterResearchDecisionOrchestrator(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    first = runtime.decide(context, snapshot)
    duplicate = runtime.decide(context, snapshot)
    state = runtime.recovery_state(0)

    assert duplicate.acceptance is ResearchDecisionAcceptance.DUPLICATE
    assert duplicate.decision.decision_id == first.decision.decision_id

    restored = MasterResearchDecisionOrchestrator(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    assert restored.restore(state, 0)
    restored_duplicate = restored.decide(context, snapshot)
    assert restored_duplicate.acceptance is ResearchDecisionAcceptance.DUPLICATE
    assert restored_duplicate.decision.decision_id == first.decision.decision_id

    diverged = MasterResearchDecisionOrchestrator(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    assert not diverged.restore(replace(state, configuration_identity="other"), 0)
    assert diverged.reconcile(0) == ("P46_RECOVERY_RESTRICTED",)


def test_runtime_has_no_recompute_override_or_financial_capability_methods():
    forbidden = {
        "evaluate_raw_observation",
        "evaluate_trusted_observation",
        "rebuild_market_intelligence",
        "rerun_strategy_evaluation",
        "rescore_candidate",
        "rerun_arbitration",
        "recompute_portfolio_risk",
        "bypass_protection",
        "force_allow",
        "submit_order",
        "place_order",
        "open_position",
        "broker_login",
        "allocate_capital",
    }
    assert forbidden.isdisjoint(set(dir(MasterResearchDecisionOrchestrator)))
