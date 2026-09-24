from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.operations.forward_ops import *

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


def config(**changes):
    values = dict(minimum_forward_observations=3, clock_jump_tolerance=timedelta(hours=1),
                  configuration_snapshot_id="CFG")
    values.update(changes); return OperationsConfiguration(**values)


def environment(epoch=1, fingerprint="CFG"):
    return RuntimeEnvironmentIdentity("ENV", "HOST", "0.26.0", fingerprint,
                                      "DEPLOY", epoch, "PROCESS", NOW)


def ready(audit=None):
    target = NeutralForwardOperationsEngine(config(), audit)
    assert target.startup(environment(), "TOKEN", NOW)[0]
    session = target.create_session("COMPONENT", "1.0", NOW, NOW + timedelta(seconds=1), "SOURCE", "POLICY")
    return target, session


def observation(sequence, value=1, **changes):
    at = NOW + timedelta(minutes=sequence)
    values = dict(source_id="SOURCE", observed_at_utc=at, available_at_utc=at,
                  received_at_utc=at, source_fingerprint="FP", quality_state="VALID",
                  sequence_number=sequence, neutral_value=Decimal(str(value)))
    values.update(changes); return ForwardObservation.create(**values)


def test_configuration_validation_and_startup_fail_closed():
    with pytest.raises(ValueError): NeutralForwardOperationsEngine(config(maximum_events=0))
    target = NeutralForwardOperationsEngine(config())
    assert not target.startup(environment(fingerprint="OTHER"), "TOKEN", NOW)[0]
    assert target.health is OperationalHealth.FAILED


def test_single_instance_unattended_start_and_shutdown():
    target, _ = ready(); assert not target.startup(environment(), "OTHER", NOW)[0]
    assert target.shutdown(NOW + timedelta(minutes=1)) and target.paused


def test_forward_only_and_lookahead_are_blocked():
    target, session = ready()
    old = observation(1, observed_at_utc=NOW)
    assert target.ingest(session.session_id, old, NOW + timedelta(minutes=1))[0] is None
    future = observation(2, available_at_utc=NOW + timedelta(hours=1), received_at_utc=NOW + timedelta(hours=1))
    assert "OPERATIONS_LOOKAHEAD_BLOCKED" in target.ingest(session.session_id, future, NOW + timedelta(minutes=2))[1]


def test_valid_observation_duplicate_and_sequence_protection():
    target, session = ready(); item = observation(1)
    decision, _ = target.ingest(session.session_id, item, item.available_at_utc)
    duplicate, reasons = target.ingest(session.session_id, item, item.available_at_utc)
    assert decision == duplicate and "OPERATIONS_DUPLICATE" in reasons and len(target.decisions) == 1
    assert target.ingest(session.session_id, observation(0), NOW + timedelta(minutes=2))[0] is None


def test_drift_detection_does_not_mutate_configuration():
    target, session = ready()
    for i, value in enumerate((1, 1, 3), 1): target.ingest(session.session_id, observation(i, value), NOW + timedelta(minutes=i))
    drift = target.detect_drift(session.session_id, 1, Decimal(".2"))
    assert drift.state is DriftState.DRIFTED and target.configuration.configuration_snapshot_id == "CFG"


def test_promotion_requires_predecessor_evidence_and_manual_approval():
    target, _ = ready()
    held = target.promote("C", "1", "L", ValidationStage.HISTORICAL_VALIDATED,
                          ValidationStage.OUT_OF_SAMPLE_VALIDATED, ("E",), NOW)
    approved = target.promote("C", "1", "L", ValidationStage.HISTORICAL_VALIDATED,
                              ValidationStage.OUT_OF_SAMPLE_VALIDATED, ("E",), NOW, True)
    skipped = target.promote("C", "1", "L", ValidationStage.HISTORICAL_VALIDATED,
                             ValidationStage.SOAK_VALIDATED, ("E",), NOW, True)
    assert held.decision is PromotionDecision.HOLD and approved.decision is PromotionDecision.PROMOTE
    assert skipped.decision is PromotionDecision.HOLD


def test_version_and_configuration_isolation_in_promotion_identity():
    target, _ = ready()
    a = target.promote("C", "1", "L", ValidationStage.HISTORICAL_VALIDATED, ValidationStage.OUT_OF_SAMPLE_VALIDATED, ("E",), NOW, True)
    b = target.promote("C", "2", "L", ValidationStage.HISTORICAL_VALIDATED, ValidationStage.OUT_OF_SAMPLE_VALIDATED, ("E",), NOW, True)
    assert a.record_id != b.record_id


def test_material_change_classifier():
    assert NeutralForwardOperationsEngine.classify_change(()) is ChangeClassification.NON_MATERIAL
    assert NeutralForwardOperationsEngine.classify_change(("threshold",)) is ChangeClassification.REVALIDATION_REQUIRED
    assert NeutralForwardOperationsEngine.classify_change(("component_logic",)) is ChangeClassification.FULL_REVALIDATION_REQUIRED


def test_pause_idempotent_and_resume_health_gated():
    target, _ = ready(); assert target.pause("TEST", NOW); assert target.pause("TEST", NOW)
    target.health = OperationalHealth.RESTRICTED
    assert not target.resume(NOW)[0]
    target.health = OperationalHealth.HEALTHY
    assert target.resume(NOW)[0]


def test_heartbeat_clock_anomaly_restricts_operation():
    target, _ = ready(); target.heartbeat(NOW + timedelta(minutes=1))
    target.heartbeat(NOW - timedelta(minutes=1))
    assert target.health is OperationalHealth.RESTRICTED and target.paused


def test_storage_protection_is_conservative():
    target, _ = ready(); assert target.storage_check(200_000_000)
    assert not target.storage_check(1) and target.health is OperationalHealth.RESTRICTED


def test_backup_checksum_and_restore_verification():
    target, _ = ready(); items = {"state": b"abc", "config": b"xyz"}
    manifest = target.backup(items, NOW)
    assert target.verify_backup(manifest, items)
    assert not target.verify_backup(manifest, {"state": b"changed", "config": b"xyz"})


def test_windows_paths_are_relative_and_os_neutral():
    profile = NeutralForwardOperationsEngine.deployment_profile("0.26.0", "3.11", "LOCK",
                                                                 {"state": "data/state", "logs": "data/logs"})
    assert profile.startup_mode == "UNATTENDED"
    with pytest.raises(ValueError): NeutralForwardOperationsEngine.deployment_profile("0.26.0", "3.11", "LOCK", {"state": "/var/state"})


def test_secret_redaction():
    assert NeutralForwardOperationsEngine.redact("token=SECRET", ("SECRET",)) == "token=[REDACTED]"


def test_soak_qualification_and_error_failure():
    passed = NeutralForwardOperationsEngine.soak("ENV", NOW, NOW + timedelta(hours=1), 100, 100, 1, 0, 0, 1000, 2000, True, True)
    failed = NeutralForwardOperationsEngine.soak("ENV", NOW, NOW + timedelta(hours=1), 100, 100, 1, 0, 1, 1000, 2000, True, True)
    assert passed.qualified and not failed.qualified


def test_readiness_never_automatically_promotes():
    target, _ = ready(); card = target.readiness({"state": OperationalHealth.HEALTHY, "backup": OperationalHealth.HEALTHY})
    assert card.overall_health is OperationalHealth.HEALTHY and card.decision is PromotionDecision.HOLD


def test_recovery_reconciliation_and_replay():
    target, session = ready(); item = observation(1); target.ingest(session.session_id, item, item.available_at_utc)
    fingerprint = target.replay_fingerprint(); state = target.recovery_state(3)
    restored = NeutralForwardOperationsEngine(config()); assert restored.restore(state, 3)
    assert restored.reconcile() == (True, ()) and restored.replay_fingerprint() == fingerprint and restored.paused
    incompatible = NeutralForwardOperationsEngine(config()); assert not incompatible.restore(replace(state, recovery_epoch=4), 3)


def test_reconciliation_detects_orphan_decision():
    target, session = ready(); item = observation(1); decision, _ = target.ingest(session.session_id, item, item.available_at_utc)
    target.observations.clear(); assert target.reconcile()[0] is False


def test_concurrent_duplicate_ingestion_is_idempotent():
    target, session = ready(); item = observation(1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: target.ingest(session.session_id, item, item.available_at_utc), range(4)))
    assert len(target.observations) == len(target.decisions) == 1


def test_bounded_heartbeats_logs_audit_and_trace():
    audit = InMemoryAuditSink(); target = NeutralForwardOperationsEngine(config(maximum_heartbeats=2, maximum_log_records=2), audit)
    assert target.startup(environment(), "TOKEN", NOW)[0]
    target.heartbeat(NOW + timedelta(minutes=1)); target.heartbeat(NOW + timedelta(minutes=2)); target.heartbeat(NOW + timedelta(minutes=3))
    trace = target.trace("REF", NOW)
    assert len(target.heartbeats) == 2 and trace.evaluations and audit.events


def test_no_financial_trading_gambling_or_credentials_capability():
    forbidden = {"place_order", "submit_trade", "open_position", "close_position", "broker_login",
                 "account_login", "set_leverage", "calculate_margin", "wager", "bet", "financial_execution"}
    assert forbidden.isdisjoint(dir(NeutralForwardOperationsEngine))
