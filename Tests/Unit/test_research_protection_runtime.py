from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal

import pytest

from amrte.core.clock import FixedClock
from amrte.core.identity import deterministic_id
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.portfolio.research_portfolio_runtime import (
    CandidateResearchRiskAssessment,
    PortfolioResearchStateValue,
    ResearchPortfolioRuntime,
    _sha256_json as p44_sha256_json,
)
from amrte.research.protection_runtime import (
    CooldownEvidence,
    DependencyProtectionEvidence,
    ProtectionRestrictionCategory,
    ResearchProtectionEvidence,
    ResearchProtectionPermission,
    ResearchProtectionRuntime,
    ResearchProtectionRuntimeConfiguration,
    protection_evidence_schema_identity,
    research_protection_snapshot_schema_identity,
)
from Tests.Unit.test_events import NOW
from Tests.Unit.test_research_portfolio_runtime import contexts_for, p43_assessment_for
from Tests.Unit.test_strategy_framework import TestStrategy


def p44_snapshot():
    p42, _, evaluation_set, assessment = p43_assessment_for(TestStrategy("S1"))
    runtime = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    return runtime.assess(assessment, contexts_for(p42, evaluation_set, assessment)).snapshot


def unrestricted_p44(snapshot):
    risks = tuple(
        replace(
            risk,
            risk_state="ACCEPTABLE",
            restrictions=(),
            reason_codes=("P44_CANDIDATE_RISK_ASSESSED",),
        )
        for risk in snapshot.candidate_risk_assessments
    )
    fingerprint = p44_sha256_json(
        {
            "p43_assessment_id": snapshot.p43_assessment_id,
            "p43_fingerprint": snapshot.p43_assessment_fingerprint,
            "portfolio_state": snapshot.portfolio_state_id,
            "correlation": snapshot.correlation_snapshot_id,
            "risk": tuple(item.fingerprint for item in risks),
            "conflicts": (),
            "restrictions": (),
            "configuration_identity": snapshot.configuration_identity,
            "recovery_epoch": snapshot.recovery_epoch,
        }
    )
    return replace(
        snapshot,
        portfolio_snapshot_id=deterministic_id("p44_portfolio_research_snapshot", fingerprint),
        candidate_risk_assessments=risks,
        portfolio_conflicts=(),
        aggregate_restrictions=(),
        warnings=(),
        portfolio_research_state=PortfolioResearchStateValue.ACCEPTABLE.value,
        reason_codes=("ACCEPTABLE",),
        snapshot_fingerprint=fingerprint,
    )


def deps(snapshot, *, required=True, status="ACTIVE", health="HEALTHY", stale=False):
    return (
        DependencyProtectionEvidence(
            "portfolio_research_snapshot",
            required,
            status,
            health,
            f"DEP-{status}-{health}-{stale}",
            snapshot.as_of_timestamp_utc,
            stale,
        ),
    )


def healthy_evidence(snapshot, **overrides):
    values = {
        "dataset_id": "DS-P45",
        "dataset_fingerprint": "FP-P45",
        "as_of_timestamp_utc": snapshot.as_of_timestamp_utc,
        "knowledge_cutoff_utc": snapshot.knowledge_cutoff_utc,
        "configuration_identity": snapshot.configuration_identity,
        "recovery_epoch": snapshot.recovery_epoch,
        "dependency_states": deps(snapshot),
    }
    values.update(overrides)
    return ResearchProtectionEvidence.create(**values)


def assess(snapshot, evidence=None, configuration=None):
    runtime = ResearchProtectionRuntime(configuration or ResearchProtectionRuntimeConfiguration(), clock=FixedClock(NOW), audit=InMemoryAuditSink())
    return runtime, runtime.assess(snapshot, evidence)


def test_schema_identities_are_deterministic_and_distinct():
    assert research_protection_snapshot_schema_identity() == research_protection_snapshot_schema_identity()
    assert protection_evidence_schema_identity() == protection_evidence_schema_identity()
    assert research_protection_snapshot_schema_identity() != protection_evidence_schema_identity()


def test_healthy_evidence_allows_only_research_processing_not_authorization():
    snapshot = unrestricted_p44(p44_snapshot())
    runtime, result = assess(snapshot, healthy_evidence(snapshot))

    assert result.acceptance == "ACCEPTED"
    assert result.snapshot.effective_permission == ResearchProtectionPermission.ALLOWED.value
    assert "P45_ALLOWED_IS_NOT_AUTHORIZATION" in result.snapshot.reason_codes
    assert runtime.diagnostics()["financial_execution"] == "NONE"


def test_invalid_p44_identity_is_blocked_before_publication():
    snapshot = replace(p44_snapshot(), portfolio_snapshot_id="bad")
    runtime, result = assess(snapshot, healthy_evidence(snapshot))

    assert result.acceptance == "BLOCKED"
    assert "P45_P44_IDENTITY_MISMATCH" in result.reason_codes
    assert runtime.snapshots == {}


def test_missing_required_safety_evidence_fails_closed():
    runtime, result = assess(unrestricted_p44(p44_snapshot()), None)

    assert result.acceptance == "BLOCKED"
    assert "P45_REQUIRED_EVIDENCE_UNAVAILABLE" in result.reason_codes
    assert runtime.metrics["protection_assessments"] == 0


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("ALLOWED", "ALLOWED", "ALLOWED"),
        ("ALLOWED", "RESTRICTED", "RESTRICTED"),
        ("RESTRICTED", "ALLOWED", "RESTRICTED"),
        ("RESTRICTED", "RESTRICTED", "RESTRICTED"),
        ("ALLOWED", "BLOCKED", "BLOCKED"),
        ("RESTRICTED", "BLOCKED", "BLOCKED"),
        ("BLOCKED", "ALLOWED", "BLOCKED"),
        ("BLOCKED", "RESTRICTED", "BLOCKED"),
        ("BLOCKED", "BLOCKED", "BLOCKED"),
    ],
)
def test_permission_composition_is_monotonic(left, right, expected):
    assert ResearchProtectionRuntime.compose_permissions((left, right)) == expected


def test_restriction_order_independence_and_duplicate_handling():
    snapshot = unrestricted_p44(p44_snapshot())
    first = healthy_evidence(
        snapshot,
        reliability_stage="WATCH",
        strategy_health="FAILED",
    )
    second = healthy_evidence(
        snapshot,
        strategy_health="FAILED",
        reliability_stage="WATCH",
    )

    left = assess(snapshot, first)[1].snapshot
    right = assess(snapshot, second)[1].snapshot

    assert left.effective_permission == right.effective_permission == "BLOCKED"
    assert [item.reason_code for item in left.aggregate_restrictions] == [item.reason_code for item in right.aggregate_restrictions]
    assert len({item.restriction_id for item in left.aggregate_restrictions}) == len(left.aggregate_restrictions)


def test_upstream_p44_restriction_cannot_be_weakened_to_allowed():
    snapshot = p44_snapshot()
    result = assess(snapshot, healthy_evidence(snapshot))[1].snapshot

    assert result.effective_permission in {"RESTRICTED", "BLOCKED"}
    assert any(item.category == ProtectionRestrictionCategory.UPSTREAM.value for item in result.aggregate_restrictions)


@pytest.mark.parametrize(
    "trust,expected,reason",
    [
        ("TRUSTED", "ALLOWED", None),
        ("RESTRICTED", "RESTRICTED", "P45_OBSERVATION_PROTECTION_RESTRICTED"),
        ("QUARANTINED", "BLOCKED", "P45_OBSERVATION_PROTECTION_RESTRICTED"),
        ("REJECTED", "BLOCKED", "P45_OBSERVATION_PROTECTION_RESTRICTED"),
    ],
)
def test_observation_protection_mapping(trust, expected, reason):
    snapshot = unrestricted_p44(p44_snapshot())
    result = assess(snapshot, healthy_evidence(snapshot, observation_trust_status=trust))[1].snapshot

    assert result.effective_permission == expected
    if reason:
        assert reason in result.reason_codes


@pytest.mark.parametrize(
    "stage,expected",
    [
        ("NORMAL", "ALLOWED"),
        ("WATCH", "RESTRICTED"),
        ("RESTRICTED", "RESTRICTED"),
        ("PROTECTED", "RESTRICTED"),
        ("SUSPENDED", "BLOCKED"),
        ("UNKNOWN", "BLOCKED"),
    ],
)
def test_reliability_mapping(stage, expected):
    snapshot = unrestricted_p44(p44_snapshot())
    result = assess(snapshot, healthy_evidence(snapshot, reliability_stage=stage))[1].snapshot
    assert result.effective_permission == expected


@pytest.mark.parametrize(
    "health,expected",
    [
        ("HEALTHY", "ALLOWED"),
        ("DEGRADED", "RESTRICTED"),
        ("STALE", "RESTRICTED"),
        ("UNAVAILABLE", "BLOCKED"),
        ("FAILED", "BLOCKED"),
    ],
)
def test_strategy_health_mapping(health, expected):
    snapshot = unrestricted_p44(p44_snapshot())
    result = assess(snapshot, healthy_evidence(snapshot, strategy_health=health))[1].snapshot
    assert result.effective_permission == expected


@pytest.mark.parametrize(
    "stage,expected",
    [
        ("NORMAL", "ALLOWED"),
        ("WATCH", "RESTRICTED"),
        ("RESTRICTED", "RESTRICTED"),
        ("COOLDOWN", "BLOCKED"),
        ("SUSPENDED", "BLOCKED"),
    ],
)
def test_temporal_mapping(stage, expected):
    snapshot = unrestricted_p44(p44_snapshot())
    result = assess(snapshot, healthy_evidence(snapshot, temporal_stage=stage))[1].snapshot
    assert result.effective_permission == expected


def test_cooldown_expiry_requires_reassessment_and_does_not_force_allowed():
    snapshot = unrestricted_p44(p44_snapshot())
    active = CooldownEvidence("CD-A", "TEMPORAL", NOW, NOW + timedelta(minutes=5), "ACTIVE", "EV-A")
    expired = CooldownEvidence("CD-B", "TEMPORAL", NOW, NOW - timedelta(minutes=1), "EXPIRED_PENDING_CONFIRMATION", "EV-B")

    blocked = assess(snapshot, healthy_evidence(snapshot, cooldowns=(active,)))[1].snapshot
    restricted = assess(snapshot, healthy_evidence(snapshot, cooldowns=(expired,)))[1].snapshot

    assert blocked.effective_permission == "BLOCKED"
    assert restricted.effective_permission == "RESTRICTED"
    assert "P45_COOLDOWN_ACTIVE" in restricted.reason_codes


def test_temporal_cutoff_mismatch_future_and_stale_dependency_restrict_or_block():
    snapshot = unrestricted_p44(p44_snapshot())
    future = healthy_evidence(snapshot, as_of_timestamp_utc=snapshot.knowledge_cutoff_utc + timedelta(seconds=1))
    cutoff = healthy_evidence(snapshot, knowledge_cutoff_utc=snapshot.knowledge_cutoff_utc - timedelta(seconds=1))
    stale_dependency = healthy_evidence(snapshot, dependency_states=deps(snapshot, stale=True))

    assert "P45_TEMPORAL_RESTRICTED" in assess(snapshot, future)[1].reason_codes
    assert "P45_KNOWLEDGE_CUTOFF_MISMATCH" in assess(snapshot, cutoff)[1].reason_codes
    stale_result = assess(snapshot, stale_dependency)[1]
    assert "P45_DEPENDENCY_UNAVAILABLE" in stale_result.snapshot.reason_codes


@pytest.mark.parametrize(
    "state,health,expected",
    [
        ("ACTIVE", "HEALTHY", "ALLOWED"),
        ("PROPOSED", "HEALTHY", "RESTRICTED"),
        ("RECOVERING", "HEALTHY", "RESTRICTED"),
        ("FAILED", "INVALID", "BLOCKED"),
    ],
)
def test_lifecycle_mapping(state, health, expected):
    snapshot = unrestricted_p44(p44_snapshot())
    result = assess(snapshot, healthy_evidence(snapshot, lifecycle_state=state, lifecycle_health=health))[1].snapshot
    assert result.effective_permission == expected


def test_dependency_required_optional_degradation_and_failure():
    snapshot = unrestricted_p44(p44_snapshot())
    required_failed = deps(snapshot, status="FAILED", health="UNHEALTHY")
    required_degraded = deps(snapshot, status="DEGRADED", health="DEGRADED")
    optional_failed = deps(snapshot, required=False, status="FAILED", health="UNHEALTHY")

    assert assess(snapshot, healthy_evidence(snapshot, dependency_states=required_failed))[1].snapshot.effective_permission == "BLOCKED"
    assert assess(snapshot, healthy_evidence(snapshot, dependency_states=required_degraded))[1].snapshot.effective_permission == "RESTRICTED"
    assert assess(snapshot, healthy_evidence(snapshot, dependency_states=optional_failed))[1].snapshot.effective_permission == "ALLOWED"


@pytest.mark.parametrize(
    "state,expected",
    [
        ("NORMAL", "ALLOWED"),
        ("CAUTION", "RESTRICTED"),
        ("RESTRICTED", "RESTRICTED"),
        ("CIRCUIT_OPEN", "BLOCKED"),
        ("EMERGENCY_STOP", "BLOCKED"),
        ("RECOVERY_PENDING", "BLOCKED"),
        ("UNKNOWN", "BLOCKED"),
    ],
)
def test_system_safety_mapping(state, expected):
    snapshot = unrestricted_p44(p44_snapshot())
    result = assess(snapshot, healthy_evidence(snapshot, system_safety_state=state))[1].snapshot
    assert result.effective_permission == expected


def test_recovery_restriction_blocks_and_recovery_restore_duplicate_equivalence():
    snapshot = unrestricted_p44(p44_snapshot())
    evidence = healthy_evidence(snapshot, recovery_restricted=True)
    runtime = ResearchProtectionRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    first = runtime.assess(snapshot, evidence).snapshot
    state = runtime.recovery_state(0)

    assert first.effective_permission == "BLOCKED"
    restored = ResearchProtectionRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    assert restored.restore(state, 0)
    assert restored.reconcile(0) == ()
    duplicate = restored.assess(snapshot, evidence)
    assert duplicate.acceptance == "DUPLICATE"
    assert duplicate.snapshot.protection_snapshot_id == first.protection_snapshot_id

    diverged = ResearchProtectionRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    bad = replace(state, configuration_identity="other")
    assert not diverged.restore(bad, 0)
    assert diverged.reconcile(0) == ("P45_RECOVERY_RESTRICTED",)


def test_snapshot_is_immutable_and_deterministic_for_identical_inputs():
    snapshot = unrestricted_p44(p44_snapshot())
    evidence = healthy_evidence(snapshot)
    first = assess(snapshot, evidence)[1].snapshot
    second = assess(snapshot, evidence)[1].snapshot

    assert first.protection_snapshot_id == second.protection_snapshot_id
    assert first.snapshot_fingerprint == second.snapshot_fingerprint
    with pytest.raises(FrozenInstanceError):
        first.effective_permission = "BLOCKED"


def test_runtime_has_no_recompute_override_or_financial_capability_methods():
    forbidden = {
        "evaluate_raw_observation",
        "evaluate_trusted_observation",
        "rescore_candidate",
        "rerun_arbitration",
        "recompute_portfolio_risk",
        "force_allow",
        "ignore_safety",
        "bypass_protection",
        "disable_fail_closed",
        "submit_order",
        "place_order",
        "open_position",
        "broker_login",
        "size_position",
        "allocate_capital",
    }
    assert forbidden.isdisjoint(set(dir(ResearchProtectionRuntime)))
