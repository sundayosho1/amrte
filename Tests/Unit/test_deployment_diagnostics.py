from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from amrte.operations.deployment import *

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


def engine(**changes):
    values = dict(configuration_snapshot_id="CFG")
    values.update(changes)
    return DeploymentDiagnosticsEngine(DeploymentConfiguration(**values))


def test_configuration_validation():
    with pytest.raises(ValueError): DeploymentDiagnosticsEngine(DeploymentConfiguration(maximum_alerts=0))


def test_health_tree_localizes_root_and_affected_components():
    target = engine()
    target.publish_health("STORE", HealthState.FAILED, "STORE_DOWN", (), NOW, "restore")
    target.publish_health("SERVICE", HealthState.DEGRADED, "DEPENDENCY_DOWN", ("STORE",), NOW, "wait")
    summary = target.summary(NOW)
    assert summary.overall_state is HealthState.FAILED and summary.root_component_ids == ("STORE",)
    assert summary.affected_component_ids == ("SERVICE", "STORE")


def test_no_false_healthy_when_required_component_is_restricted():
    target = engine(); target.publish_health("CORE", HealthState.RESTRICTED, "CORE_BLOCK", (), NOW, "inspect")
    assert target.summary(NOW).overall_state is HealthState.RESTRICTED


def test_invalid_self_dependency_and_bounds():
    target = engine(maximum_components=1)
    with pytest.raises(ValueError): target.publish_health("A", HealthState.HEALTHY, "OK", ("A",), NOW, "none")
    target.publish_health("A", HealthState.HEALTHY, "OK", (), NOW, "none")
    with pytest.raises(ValueError): target.publish_health("B", HealthState.HEALTHY, "OK", (), NOW, "none")


def test_alert_deduplication_escalation_and_resolution():
    target = engine(); a = target.alert("CORE", AlertSeverity.ERROR, "BROKEN", NOW, "inspect")
    b = target.alert("CORE", AlertSeverity.ERROR, "BROKEN", NOW + timedelta(minutes=1), "inspect")
    assert a.alert_id == b.alert_id and b.occurrence_count == 2
    assert target.resolve_alert(a.alert_id, NOW + timedelta(minutes=2))


def test_diagnostics_pass_fail_and_exception():
    target = engine()
    checks = (("A", lambda: (True, ("ok",)), "none"),
              ("B", lambda: (False, ("bad",)), "repair"),
              ("C", lambda: (_ for _ in ()).throw(RuntimeError()), "inspect"))
    report = target.diagnose(checks, NOW)
    assert report.overall_state is CheckState.FAIL and len(report.results) == 3


def test_support_bundle_redacts_secrets_and_is_deterministic():
    a = DeploymentDiagnosticsEngine.support_bundle("RC", "ENV", {"log": "token=SECRET"}, NOW, ("SECRET",))
    b = DeploymentDiagnosticsEngine.support_bundle("RC", "ENV", {"log": "token=SECRET"}, NOW, ("SECRET",))
    assert a == b and a.redacted


def manifest(data=b"package"):
    checksum = sha256(data).hexdigest()
    uid = deterministic_id("update", "0.26.0", "1.0.0-rc1", checksum)
    return UpdateManifest(uid, "0.26.0", "1.0.0-rc1", checksum, "1", "1", "BACKUP", NOW), data


def test_update_requires_checksum_backup_and_compatible_state():
    target = engine(); target.permission_state = HealthState.HEALTHY; item, data = manifest()
    blocked = target.prepare_update(item, "0.26.0", b"wrong", False, True, True, NOW)
    ready = target.prepare_update(item, "0.26.0", data, True, True, True, NOW)
    assert blocked.state is UpdateState.BLOCKED and ready.state is UpdateState.READY


def test_successful_update_does_not_change_permission():
    target = engine(); target.permission_state = HealthState.DEGRADED; item, data = manifest()
    record = target.prepare_update(item, "0.26.0", data, True, True, True, NOW)
    done = target.complete_update(record.record_id, True, NOW + timedelta(minutes=1))
    assert done.state is UpdateState.APPLIED and done.resulting_permission_state is HealthState.DEGRADED


def test_failed_update_rolls_back_and_cannot_improve_permission():
    target = engine(); target.permission_state = HealthState.HEALTHY; item, data = manifest()
    record = target.prepare_update(item, "0.26.0", data, True, True, True, NOW)
    done = target.complete_update(record.record_id, False, NOW + timedelta(minutes=1))
    assert done.state is UpdateState.ROLLED_BACK and done.resulting_permission_state is HealthState.RESTRICTED


def test_blocked_update_cannot_be_completed():
    target = engine(); item, data = manifest()
    record = target.prepare_update(item, "wrong", data, True, True, True, NOW)
    assert target.complete_update(record.record_id, True, NOW) == record


def test_paths_are_configurable_relative_and_windows_portable():
    ok, invalid, normalized = DeploymentDiagnosticsEngine.validate_paths({"state": "data/state", "logs": "data/logs"})
    assert ok and not invalid and normalized
    assert not DeploymentDiagnosticsEngine.validate_paths({"state": "C:\\fixed", "logs": "/var/log"})[0]


def test_release_manifest_declares_only_safe_capabilities():
    release = DeploymentDiagnosticsEngine.release_manifest("1.0.0-rc1", NOW, "SRC", "DEP", "1", "1", "HASH")
    assert "NON_FINANCIAL" in release.safety_capabilities and "NON_EXECUTING" in release.safety_capabilities


def test_global_state_audit_detects_missing_dependency():
    target = engine(); target.publish_health("A", HealthState.DEGRADED, "WAIT", ("MISSING",), NOW, "inspect")
    assert target.audit_global_state()[0] is False


def test_recovery_reconciliation_and_replay():
    target = engine(); target.publish_health("A", HealthState.HEALTHY, "OK", (), NOW, "none")
    fingerprint = target.replay_fingerprint(); state = target.recovery_state(3)
    restored = engine(); assert restored.restore(state, 3) and restored.replay_fingerprint() == fingerprint
    incompatible = engine(); assert not incompatible.restore(replace(state, recovery_epoch=4), 3)
    assert incompatible.permission_state is HealthState.RECOVERY_PENDING


def test_corrupt_recovery_fails_closed():
    target = engine(); record = target.publish_health("A", HealthState.HEALTHY, "OK", (), NOW, "none")
    state = target.recovery_state(1); corrupt = replace(state, health_records=(record, record))
    restored = engine(); assert not restored.restore(corrupt, 1) and restored.recovery_restricted


def test_repeated_inputs_have_deterministic_identities():
    a = engine(); b = engine()
    assert a.publish_health("A", HealthState.HEALTHY, "OK", (), NOW, "none") == b.publish_health("A", HealthState.HEALTHY, "OK", (), NOW, "none")


def test_absence_of_financial_gambling_and_broker_operations():
    forbidden = {"place_order", "submit_trade", "open_position", "close_position", "broker_login",
                 "account_login", "set_leverage", "calculate_margin", "wager", "bet", "financial_execution"}
    assert forbidden.isdisjoint(dir(DeploymentDiagnosticsEngine))
