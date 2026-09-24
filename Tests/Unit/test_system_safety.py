from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.system_safety import *


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def initialized(config=None, scope="SCOPE-A", epoch=0, audit=None):
    engine = SystemSafetyEngine(config or SystemSafetyConfiguration(), audit)
    status = engine.initialize(scope, f"FP-{scope}", NOW, epoch)
    return engine, status


def signal(tag, severity, at, scope="SCOPE-A", epoch=0, fingerprint=None, available=None, domain=SafetyDomain.STATE_INTEGRITY):
    return SystemSafetySignal.create(scope, domain, severity, f"TRIGGER-{tag}", at, available or at, (f"EVIDENCE-{tag}",), fingerprint or f"FP-{scope}", recovery_epoch=epoch)


def test_configuration_validation():
    with pytest.raises(ValueError):
        SystemSafetyEngine(SystemSafetyConfiguration(caution_multiplier=Decimal("1.1")))
    with pytest.raises(ValueError):
        SystemSafetyEngine(SystemSafetyConfiguration(restricted_multiplier=Decimal(".8"), caution_multiplier=Decimal(".7")))
    with pytest.raises(ValueError):
        SystemSafetyEngine(SystemSafetyConfiguration(maximum_events=0))


def test_initialization_is_deterministic_immutable_and_idempotent():
    engine, first = initialized()
    second = engine.initialize("SCOPE-A", "FP-SCOPE-A", NOW)
    assert first.status_id == second.status_id and len(engine.statuses) == 1
    with pytest.raises(FrozenInstanceError):
        first.published_state = SafetyState.CAUTION


@pytest.mark.parametrize("severity,expected,multiplier", [
    (SignalSeverity.INFO, SafetyState.NORMAL, "1"),
    (SignalSeverity.LOW, SafetyState.CAUTION, ".75"),
    (SignalSeverity.MEDIUM, SafetyState.CAUTION, ".75"),
    (SignalSeverity.HIGH, SafetyState.RESTRICTED, ".25"),
    (SignalSeverity.CRITICAL, SafetyState.EMERGENCY_STOP, "0"),
])
def test_single_signal_severity_mapping(severity, expected, multiplier):
    engine, _ = initialized()
    result = engine.process(signal("ONE", severity, NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1))
    assert result.decision is SafetyDecision.ACCEPTED
    assert result.status.published_state is expected
    assert result.status.final_phase_multiplier == Decimal(multiplier)


def test_repeated_signals_escalate_and_incident_aggregates():
    engine, _ = initialized()
    engine.process(signal("M1", SignalSeverity.MEDIUM, NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1))
    medium = engine.process(signal("M2", SignalSeverity.MEDIUM, NOW + timedelta(seconds=2)), NOW + timedelta(seconds=2))
    assert medium.status.published_state is SafetyState.RESTRICTED
    engine.process(signal("H1", SignalSeverity.HIGH, NOW + timedelta(seconds=3)), NOW + timedelta(seconds=3))
    opened = engine.process(signal("H2", SignalSeverity.HIGH, NOW + timedelta(seconds=4)), NOW + timedelta(seconds=4))
    critical = engine.process(signal("C", SignalSeverity.CRITICAL, NOW + timedelta(seconds=5)), NOW + timedelta(seconds=5))
    assert opened.status.published_state is SafetyState.CIRCUIT_OPEN and opened.incident is not None
    assert critical.incident.incident_id == opened.incident.incident_id
    assert critical.incident.highest_severity is SignalSeverity.CRITICAL


def test_unknown_missing_evidence_and_invalid_lineage_fail_closed():
    engine, current = initialized()
    at = NOW + timedelta(seconds=1)
    unknown = signal("U", SignalSeverity.UNKNOWN, at)
    assert engine.process(unknown, at).decision is SafetyDecision.BLOCKED
    missing = replace(signal("M", SignalSeverity.LOW, at), evidence_ids=())
    assert engine.process(missing, at).decision is SafetyDecision.BLOCKED
    wrong = signal("W", SignalSeverity.LOW, at, fingerprint="OTHER")
    assert engine.process(wrong, at).decision is SafetyDecision.BLOCKED
    assert engine.statuses["SCOPE-A"] == current


def test_temporal_validation_duplicate_and_upstream_non_amplification():
    engine, _ = initialized()
    at = NOW + timedelta(seconds=1)
    first = signal("ONE", SignalSeverity.LOW, at)
    assert engine.process(first, at, Decimal(".4")).status.final_phase_multiplier == Decimal(".4")
    assert engine.process(first, at + timedelta(seconds=1)).decision is SafetyDecision.NO_ACTION
    future = signal("FUTURE", SignalSeverity.LOW, at + timedelta(seconds=4))
    assert engine.process(future, at + timedelta(seconds=3)).decision is SafetyDecision.BLOCKED
    old = signal("OLD", SignalSeverity.LOW, NOW)
    assert engine.process(old, at + timedelta(seconds=2)).decision is SafetyDecision.BLOCKED
    assert engine.process(signal("BAD-M", SignalSeverity.LOW, at + timedelta(seconds=3)), at + timedelta(seconds=3), Decimal("2")).decision is SafetyDecision.BLOCKED


def test_circuit_latch_recovery_probation_and_resolution():
    engine, _ = initialized(SystemSafetyConfiguration(probation_confirmations=2))
    engine.process(signal("C", SignalSeverity.CRITICAL, NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1))
    assert engine.request_recovery("SCOPE-A", NOW + timedelta(seconds=2), False, "operator", "verified").decision is SafetyDecision.BLOCKED
    pending = engine.request_recovery("SCOPE-A", NOW + timedelta(seconds=2), True, "operator", "verified")
    first = engine.confirm_probation("SCOPE-A", NOW + timedelta(seconds=3), True)
    recovered = engine.confirm_probation("SCOPE-A", NOW + timedelta(seconds=4), True)
    assert pending.status.published_state is SafetyState.RECOVERY_PENDING
    assert first.status.published_state is SafetyState.PROBATION and first.status.final_phase_multiplier == Decimal(".25")
    assert recovered.status.published_state is SafetyState.NORMAL and not recovered.status.circuit_latched
    assert recovered.incident.state is IncidentState.RESOLVED


def test_failed_probation_returns_to_emergency():
    engine, _ = initialized()
    engine.process(signal("C", SignalSeverity.CRITICAL, NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1))
    engine.request_recovery("SCOPE-A", NOW + timedelta(seconds=2), True, "operator", "verified")
    failed = engine.confirm_probation("SCOPE-A", NOW + timedelta(seconds=3), False)
    assert failed.decision is SafetyDecision.BLOCKED and failed.status.published_state is SafetyState.EMERGENCY_STOP


def test_point_in_time_snapshot_excludes_future_signals():
    engine, _ = initialized()
    first_at = NOW + timedelta(seconds=1)
    engine.process(signal("ONE", SignalSeverity.LOW, first_at), first_at)
    engine.process(signal("TWO", SignalSeverity.CRITICAL, NOW + timedelta(seconds=2)), NOW + timedelta(seconds=2))
    historical = engine.snapshot("SCOPE-A", first_at)
    current = engine.snapshot("SCOPE-A", NOW + timedelta(seconds=2))
    assert historical.state is SafetyState.CAUTION and len(historical.event_ids) == 1
    assert current.state is SafetyState.EMERGENCY_STOP and len(current.event_ids) == 2


def test_reconciliation_detects_corruption_without_repair():
    engine, _ = initialized()
    at = NOW + timedelta(seconds=1)
    current = engine.process(signal("ONE", SignalSeverity.CRITICAL, at), at).status
    assert engine.reconcile("SCOPE-A") == ()
    engine.statuses["SCOPE-A"] = replace(current, final_phase_multiplier=Decimal(".5"))
    assert "SAFETY_LATCH_PERMISSION_INVALID" in engine.reconcile("SCOPE-A")


def test_recovery_round_trip_probation_and_deterministic_replay():
    engine, _ = initialized(SystemSafetyConfiguration(probation_confirmations=2), epoch=3)
    at = NOW + timedelta(seconds=1)
    engine.process(signal("C", SignalSeverity.CRITICAL, at, epoch=3), at)
    engine.request_recovery("SCOPE-A", at + timedelta(seconds=1), True, "operator", "verified")
    engine.confirm_probation("SCOPE-A", at + timedelta(seconds=2), True)
    fingerprint = engine.replay_fingerprint("SCOPE-A")
    state = engine.recovery_state(3)
    restored = SystemSafetyEngine(SystemSafetyConfiguration(probation_confirmations=2))
    assert restored.restore(state, 3)
    assert restored.replay_fingerprint("SCOPE-A") == fingerprint
    assert restored.statuses["SCOPE-A"].published_state is SafetyState.PROBATION


def test_corrupt_and_incompatible_recovery_fail_closed():
    engine, _ = initialized(epoch=2)
    state = engine.recovery_state(2)
    incompatible = SystemSafetyEngine()
    assert not incompatible.restore(replace(state, recovery_epoch=3), 2) and incompatible.recovery_restricted
    corrupt_status = replace(state.statuses[0], signal_count=1)
    corrupt = SystemSafetyEngine()
    assert not corrupt.restore(replace(state, statuses=(corrupt_status,)), 2) and corrupt.recovery_restricted


def test_scope_isolation_event_bound_audit_trace_and_concurrency():
    audit = InMemoryAuditSink()
    engine = SystemSafetyEngine(SystemSafetyConfiguration(maximum_scopes=2, maximum_events=2), audit)
    engine.initialize("A", "FP-A", NOW)
    b = engine.initialize("B", "FP-B", NOW)
    event = signal("A1", SignalSeverity.LOW, NOW + timedelta(seconds=1), scope="A")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: engine.process(event, NOW + timedelta(seconds=1)), range(4)))
    assert sum(x.decision is SafetyDecision.ACCEPTED for x in results) == 1
    assert engine.statuses["B"] == b
    accepted = next(x for x in results if x.decision is SafetyDecision.ACCEPTED)
    assert accepted.decision_trace.evaluations
    assert any(item[0] == "system_safety_signal_accepted" for item in audit.events)


def test_safety_surface_has_no_financial_execution_capabilities():
    forbidden = {"place_order", "submit_trade", "broker_login", "fill_order", "open_position", "close_position", "set_leverage", "calculate_margin", "account_balance"}
    assert forbidden.isdisjoint(set(dir(SystemSafetyEngine())))


def test_trigger_registry_aggregator_and_explicit_control_contracts():
    registry = SafetyTriggerRegistry.default()
    assert {item.domain for item in registry.enumerate()} == {item for item in SafetyDomain if item is not SafetyDomain.UNKNOWN}
    assert any(item.critical for item in registry.enumerate()) and any(item.emergency for item in registry.enumerate())
    assert SafetyTriggerAggregator.most_restrictive((SafetyState.NORMAL, SafetyState.CIRCUIT_OPEN, SafetyState.CAUTION)) is SafetyState.CIRCUIT_OPEN
    with pytest.raises(ValueError):
        registry.register(registry.enumerate()[0])
    engine, status = initialized()
    assert not ResearchCircuitBreaker.engaged(status) and not EmergencyResearchStop.engaged(status)


def test_phase_vii_composition_and_prompt31_handoff_never_amplify():
    engine, _ = initialized()
    at = NOW + timedelta(seconds=1)
    engine.process(signal("LOW", SignalSeverity.LOW, at), at)
    snapshot = engine.phase_vii_snapshot("SCOPE-A", at, Decimal(".50"), Decimal(".60"))
    assert snapshot.final_phase_vii_multiplier == Decimal(".50")
    assert snapshot.final_phase_vii_multiplier <= snapshot.prompt28_multiplier
    assert snapshot.final_phase_vii_multiplier <= snapshot.prompt29_multiplier
    handoff = engine.prompt31_handoff(snapshot)
    assert handoff.permission_multiplier == snapshot.final_phase_vii_multiplier
    assert handoff.restrictions == ("PHASE_VII_RESTRICTION_ACTIVE",)
