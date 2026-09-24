from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.lifecycle import *


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def create(engine=None, tag="A", epoch=0):
    engine = engine or ResearchLifecycleEngine()
    result = engine.create(f"H-{tag}", f"D-{tag}", "FAMILY", "VARIANT", f"SUBJECT-{tag}", f"FP-{tag}", NOW, epoch)
    return engine, result.lifecycle


def conditions(lifecycle, at, **changes):
    values = dict(hypothesis_id=lifecycle.hypothesis_id, as_of_timestamp_utc=at, dataset_fingerprint=lifecycle.dataset_fingerprint, evidence_ids=("WORKFLOW", "QUALITY"))
    values.update(changes)
    return LifecyclePreconditionSnapshot.create(**values)


def move(engine, lifecycle, state, at, trigger=None, **changes):
    result = engine.transition(lifecycle.lifecycle_id, state, lifecycle.state_version, conditions(lifecycle, at, **changes), at, trigger or state.name)
    return result, result.lifecycle


def test_configuration_is_strict_and_fail_closed():
    with pytest.raises(ValueError):
        ResearchLifecycleEngine(LifecycleConfiguration(strict_state_machine=False))
    with pytest.raises(ValueError):
        ResearchLifecycleEngine(LifecycleConfiguration(require_lineage=False))
    with pytest.raises(ValueError):
        ResearchLifecycleEngine(LifecycleConfiguration(maximum_lifecycles=0))


def test_creation_identity_immutability_and_one_lifecycle_per_hypothesis():
    engine, lifecycle = create()
    duplicate = engine.create("H-A", "D-A", "FAMILY", "VARIANT", "SUBJECT-A", "FP-A", NOW)
    assert duplicate.decision is TransitionDecision.NO_ACTION
    assert duplicate.lifecycle.lifecycle_id == lifecycle.lifecycle_id and len(engine.lifecycles) == 1
    with pytest.raises(FrozenInstanceError):
        lifecycle.current_state = LifecycleState.ACTIVE


def test_creation_rejects_missing_lineage_and_respects_bound():
    engine = ResearchLifecycleEngine(LifecycleConfiguration(maximum_lifecycles=1))
    invalid = engine.create("", "D", "F", "V", "S", "FP", NOW)
    assert invalid.decision is TransitionDecision.INVALID
    create(engine, "A")
    blocked = engine.create("H-B", "D-B", "F", "V", "S", "FP-B", NOW)
    assert blocked.decision is TransitionDecision.BLOCK


def test_canonical_flow_versions_sequences_and_atomic_records():
    engine, lifecycle = create()
    states = [LifecycleState.VALIDATED, LifecycleState.AUTHORIZED, LifecycleState.QUEUED, LifecycleState.ACTIVATED, LifecycleState.ACTIVE, LifecycleState.SAFEGUARDED, LifecycleState.MONITORED, LifecycleState.RESOLVED, LifecycleState.ARCHIVED]
    for index, state in enumerate(states, 1):
        result, lifecycle = move(engine, lifecycle, state, NOW + timedelta(seconds=index))
        assert result.decision is TransitionDecision.ALLOW
        assert lifecycle.state_version == index and result.transition.sequence_number == index and result.event.sequence_number == index
        assert result.event.transition_id == result.transition.transition_id
    assert lifecycle.current_state is LifecycleState.ARCHIVED and len(engine.transitions) == len(engine.events) == 9


@pytest.mark.parametrize("target", [LifecycleState.ACTIVE, LifecycleState.MONITORED, LifecycleState.ARCHIVED])
def test_illegal_transitions_fail_without_version_change(target):
    engine, lifecycle = create()
    result, after = move(engine, lifecycle, target, NOW + timedelta(seconds=1))
    assert result.decision is TransitionDecision.BLOCK and after.state_version == 0 and not engine.transitions


@pytest.mark.parametrize("terminal", [LifecycleState.REJECTED, LifecycleState.CANCELLED, LifecycleState.EXPIRED])
def test_pre_active_terminal_states_are_immutable(terminal):
    engine, lifecycle = create()
    result, terminal_lifecycle = move(engine, lifecycle, terminal, NOW + timedelta(seconds=1))
    later, unchanged = move(engine, terminal_lifecycle, LifecycleState.VALIDATED, NOW + timedelta(seconds=2))
    assert result.decision is TransitionDecision.ALLOW and later.decision is TransitionDecision.BLOCK
    assert unchanged.state_version == terminal_lifecycle.state_version


def test_authorization_requires_upstream_and_quality_evidence():
    engine, lifecycle = create()
    _, lifecycle = move(engine, lifecycle, LifecycleState.VALIDATED, NOW + timedelta(seconds=1))
    blocked, same = move(engine, lifecycle, LifecycleState.AUTHORIZED, NOW + timedelta(seconds=2), upstream_authorized=False)
    assert blocked.decision is TransitionDecision.BLOCK and same.state_version == 1
    blocked2, same2 = move(engine, lifecycle, LifecycleState.AUTHORIZED, NOW + timedelta(seconds=2), quality_allowed=False)
    assert blocked2.decision is TransitionDecision.BLOCK and same2.state_version == 1


def test_activation_requires_neutral_workflow_health():
    engine, lifecycle = create()
    for index, state in enumerate((LifecycleState.VALIDATED, LifecycleState.AUTHORIZED, LifecycleState.QUEUED), 1):
        _, lifecycle = move(engine, lifecycle, state, NOW + timedelta(seconds=index))
    blocked, same = move(engine, lifecycle, LifecycleState.ACTIVATED, NOW + timedelta(seconds=4), workflow_healthy=False)
    assert blocked.decision is TransitionDecision.BLOCK and same.current_state is LifecycleState.QUEUED


def test_terminal_restriction_cannot_be_bypassed_by_permissive_transition():
    engine, lifecycle = create()
    blocked, _ = move(engine, lifecycle, LifecycleState.VALIDATED, NOW + timedelta(seconds=1), terminal_restriction=True)
    allowed, terminal = move(engine, lifecycle, LifecycleState.REJECTED, NOW + timedelta(seconds=1), terminal_restriction=True)
    assert blocked.decision is TransitionDecision.BLOCK and allowed.decision is TransitionDecision.ALLOW and terminal.current_state is LifecycleState.REJECTED


def test_temporal_future_dataset_configuration_and_hypothesis_mismatch_fail_closed():
    engine, lifecycle = create()
    at = NOW + timedelta(seconds=1)
    future = conditions(lifecycle, at, evidence_available_at_utc=at + timedelta(seconds=1))
    assert engine.transition(lifecycle.lifecycle_id, LifecycleState.VALIDATED, 0, future, at, "FUTURE").decision is TransitionDecision.BLOCK
    assert move(engine, lifecycle, LifecycleState.VALIDATED, at, dataset_fingerprint="OTHER")[0].decision is TransitionDecision.BLOCK
    assert move(engine, lifecycle, LifecycleState.VALIDATED, at, hypothesis_id="OTHER")[0].decision is TransitionDecision.BLOCK


def test_optimistic_concurrency_allows_exactly_one_competing_transition():
    engine, lifecycle = create()
    at = NOW + timedelta(seconds=1)
    preconditions = conditions(lifecycle, at)
    def attempt(target):
        return engine.transition(lifecycle.lifecycle_id, target, 0, preconditions, at, target.name)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (LifecycleState.VALIDATED, LifecycleState.REJECTED)))
    assert sum(item.decision is TransitionDecision.ALLOW for item in results) == 1
    assert engine.lifecycles[lifecycle.lifecycle_id].state_version == 1


def test_duplicate_request_and_already_state_are_no_action():
    engine, lifecycle = create()
    at = NOW + timedelta(seconds=1)
    first, lifecycle = move(engine, lifecycle, LifecycleState.VALIDATED, at, trigger="SAME")
    duplicate = engine.transition(lifecycle.lifecycle_id, LifecycleState.VALIDATED, lifecycle.state_version, conditions(lifecycle, at), at, "SAME")
    assert first.decision is TransitionDecision.ALLOW and duplicate.decision is TransitionDecision.NO_ACTION and lifecycle.state_version == 1


def test_point_in_time_snapshot_does_not_leak_future_state():
    engine, lifecycle = create()
    first_at = NOW + timedelta(seconds=1)
    _, lifecycle = move(engine, lifecycle, LifecycleState.VALIDATED, first_at)
    _, lifecycle = move(engine, lifecycle, LifecycleState.AUTHORIZED, NOW + timedelta(seconds=2))
    historical = engine.snapshot(lifecycle.lifecycle_id, first_at)
    current = engine.snapshot(lifecycle.lifecycle_id, NOW + timedelta(seconds=2))
    assert historical.state is LifecycleState.VALIDATED and historical.state_version == 1
    assert current.state is LifecycleState.AUTHORIZED and current.state_version == 2


def test_configured_queue_expiration_is_point_in_time_safe():
    engine = ResearchLifecycleEngine(LifecycleConfiguration(queue_expiration_seconds=10))
    _, lifecycle = create(engine)
    for index, state in enumerate((LifecycleState.VALIDATED, LifecycleState.AUTHORIZED, LifecycleState.QUEUED), 1):
        _, lifecycle = move(engine, lifecycle, state, NOW + timedelta(seconds=index))
    early = engine.expire_if_due(lifecycle.lifecycle_id, NOW + timedelta(seconds=12))
    expired = engine.expire_if_due(lifecycle.lifecycle_id, NOW + timedelta(seconds=13))
    assert early.decision is TransitionDecision.NO_ACTION
    assert expired.decision is TransitionDecision.ALLOW and expired.lifecycle.current_state is LifecycleState.EXPIRED


def test_reconciliation_consistent_and_detects_state_version_event_mismatch_without_repair():
    engine, lifecycle = create()
    _, lifecycle = move(engine, lifecycle, LifecycleState.VALIDATED, NOW + timedelta(seconds=1))
    good = engine.reconcile(lifecycle.lifecycle_id, NOW + timedelta(seconds=2))
    assert good.outcome is ReconciliationOutcome.CONSISTENT and not good.repaired
    engine.lifecycles[lifecycle.lifecycle_id] = replace(lifecycle, state_version=9)
    bad = engine.reconcile(lifecycle.lifecycle_id, NOW + timedelta(seconds=3))
    assert bad.outcome is ReconciliationOutcome.FAILED_CLOSED and "LIFECYCLE_VERSION_MISMATCH" in bad.issues and not bad.repaired


def test_missing_lifecycle_reconciliation_does_not_fabricate_state():
    engine = ResearchLifecycleEngine()
    result = engine.reconcile("MISSING", NOW)
    assert result.outcome is ReconciliationOutcome.FAILED_CLOSED and result.observed_state is None and not engine.lifecycles


def test_recovery_round_trip_preserves_state_and_cannot_advance_it():
    engine, lifecycle = create(epoch=3)
    _, lifecycle = move(engine, lifecycle, LifecycleState.VALIDATED, NOW + timedelta(seconds=1))
    state = engine.recovery_state(3)
    restored = ResearchLifecycleEngine()
    assert restored.restore(state, 3)
    recovered = restored.lifecycles[lifecycle.lifecycle_id]
    assert recovered.current_state is LifecycleState.VALIDATED and recovered.state_version == 1
    assert restored.reconcile(lifecycle.lifecycle_id, NOW + timedelta(seconds=2)).outcome is ReconciliationOutcome.CONSISTENT


def test_incompatible_and_corrupt_recovery_fail_closed():
    engine, lifecycle = create(epoch=2)
    state = engine.recovery_state(2)
    target = ResearchLifecycleEngine()
    assert not target.restore(replace(state, recovery_epoch=3), 2) and target.recovery_restricted
    corrupt_lifecycle = replace(lifecycle, state_version=1)
    target2 = ResearchLifecycleEngine()
    assert not target2.restore(replace(state, lifecycles=(corrupt_lifecycle,)), 2) and target2.recovery_restricted


def test_recovery_rejects_orphan_event_and_illegal_transition():
    engine, lifecycle = create(epoch=1)
    _, lifecycle = move(engine, lifecycle, LifecycleState.VALIDATED, NOW + timedelta(seconds=1))
    state = engine.recovery_state(1)
    orphan = replace(state.events[0], lifecycle_id="OTHER")
    assert not ResearchLifecycleEngine().restore(replace(state, events=(orphan,)), 1)
    illegal = replace(state.transitions[0], from_state=LifecycleState.PROPOSED, to_state=LifecycleState.ACTIVE)
    assert not ResearchLifecycleEngine().restore(replace(state, transitions=(illegal,)), 1)


def test_history_bound_blocks_without_silent_audit_loss():
    engine = ResearchLifecycleEngine(LifecycleConfiguration(maximum_transitions_per_lifecycle=1))
    _, lifecycle = create(engine)
    _, lifecycle = move(engine, lifecycle, LifecycleState.VALIDATED, NOW + timedelta(seconds=1))
    blocked, same = move(engine, lifecycle, LifecycleState.AUTHORIZED, NOW + timedelta(seconds=2))
    assert blocked.decision is TransitionDecision.BLOCK and same.state_version == 1 and len(engine.transitions) == 1


def test_subject_variant_dataset_and_lifecycle_isolation():
    engine, a = create(tag="A")
    _, b = create(engine, tag="B")
    _, a = move(engine, a, LifecycleState.VALIDATED, NOW + timedelta(seconds=1))
    assert engine.lifecycles[b.lifecycle_id].current_state is LifecycleState.PROPOSED
    assert a.lifecycle_id != b.lifecycle_id and a.dataset_fingerprint != b.dataset_fingerprint


def test_audit_and_decision_trace_reconstruct_transition():
    audit = InMemoryAuditSink()
    engine = ResearchLifecycleEngine(audit=audit)
    _, lifecycle = create(engine)
    result, _ = move(engine, lifecycle, LifecycleState.VALIDATED, NOW + timedelta(seconds=1))
    assert result.decision_trace.evaluations[0].input_references == (result.transition.transition_id, result.event.event_id)
    assert any(item[0] == "lifecycle_transition_committed" for item in audit.events)


def test_deterministic_replay_produces_same_ids_and_hash_inputs():
    first, a = create()
    result_a, a = move(first, a, LifecycleState.VALIDATED, NOW + timedelta(seconds=1), trigger="T")
    second, b = create()
    result_b, b = move(second, b, LifecycleState.VALIDATED, NOW + timedelta(seconds=1), trigger="T")
    assert a.lifecycle_id == b.lifecycle_id
    assert result_a.transition.transition_id == result_b.transition.transition_id
    assert result_a.event.event_id == result_b.event.event_id
    assert first.replay_fingerprint(a.lifecycle_id) == second.replay_fingerprint(b.lifecycle_id)


def test_safety_surface_contains_no_financial_execution_methods():
    forbidden = {"place_order", "submit_trade", "broker_login", "fill_order", "open_position", "close_position", "set_leverage", "calculate_margin"}
    assert forbidden.isdisjoint(set(dir(ResearchLifecycleEngine())))
