"""Neutral deployment, health, diagnostics, and update hardening.

The module manages only application operations.  It exposes no financial,
market-participation, wagering, account, order, or execution capability.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum, auto
from hashlib import sha256
from pathlib import PurePath
from threading import RLock

from amrte.core.identity import deterministic_id

VERSION = "1.0"
SCHEMA = "1.0"


class HealthState(Enum):
    HEALTHY = auto(); DEGRADED = auto(); RESTRICTED = auto(); SUSPENDED = auto(); RECOVERY_PENDING = auto(); FAILED = auto(); UNKNOWN = auto()


class AlertSeverity(Enum): INFO = auto(); WARNING = auto(); ERROR = auto(); CRITICAL = auto()
class CheckState(Enum): PASS = auto(); WARN = auto(); FAIL = auto(); UNKNOWN = auto()
class UpdateState(Enum): PLANNED = auto(); READY = auto(); BLOCKED = auto(); APPLIED = auto(); ROLLED_BACK = auto(); FAILED = auto()


@dataclass(frozen=True)
class DeploymentConfiguration:
    maximum_components: int = 256
    maximum_alerts: int = 2048
    maximum_diagnostics: int = 2048
    maximum_update_history: int = 256
    alert_repeat_window: timedelta = timedelta(minutes=15)
    minimum_free_bytes: int = 100_000_000
    configuration_snapshot_id: str = "NEUTRAL_DEPLOYMENT_DEFAULT"

    def validate(self):
        values = (self.maximum_components, self.maximum_alerts, self.maximum_diagnostics,
                  self.maximum_update_history, self.minimum_free_bytes)
        return ("DEPLOYMENT_CONFIGURATION_INVALID",) if min(values) < 1 or self.alert_repeat_window < timedelta(0) else ()


@dataclass(frozen=True)
class ComponentHealthRecord:
    record_id: str
    component_id: str
    state: HealthState
    reason_code: str
    dependency_ids: tuple[str, ...]
    observed_at_utc: datetime
    recovery_action: str


@dataclass(frozen=True)
class SystemHealthSummary:
    summary_id: str
    overall_state: HealthState
    root_component_ids: tuple[str, ...]
    affected_component_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    as_of_utc: datetime


@dataclass(frozen=True)
class OperationalAlert:
    alert_id: str
    component_id: str
    severity: AlertSeverity
    reason_code: str
    first_seen_utc: datetime
    last_seen_utc: datetime
    occurrence_count: int
    resolved_at_utc: datetime | None
    operator_action: str


@dataclass(frozen=True)
class DiagnosticResult:
    diagnostic_id: str
    check_id: str
    state: CheckState
    reason_code: str
    evidence: tuple[str, ...]
    operator_action: str
    checked_at_utc: datetime


@dataclass(frozen=True)
class DiagnosticSummary:
    summary_id: str
    results: tuple[DiagnosticResult, ...]
    overall_state: CheckState
    generated_at_utc: datetime
    fingerprint: str


@dataclass(frozen=True)
class SupportBundleManifest:
    bundle_id: str
    application_version: str
    environment_id: str
    created_at_utc: datetime
    included_items: tuple[tuple[str, str], ...]
    redacted: bool
    checksum: str


@dataclass(frozen=True)
class UpdateManifest:
    update_id: str
    from_version: str
    to_version: str
    package_checksum: str
    configuration_schema: str
    state_schema: str
    required_backup_id: str
    created_at_utc: datetime


@dataclass(frozen=True)
class UpdateRecord:
    record_id: str
    manifest_id: str
    state: UpdateState
    requested_at_utc: datetime
    completed_at_utc: datetime | None
    reason_codes: tuple[str, ...]
    previous_permission_state: HealthState
    resulting_permission_state: HealthState


@dataclass(frozen=True)
class ReleaseManifest:
    release_id: str
    version: str
    build_timestamp_utc: datetime
    source_fingerprint: str
    dependency_fingerprint: str
    configuration_schema: str
    state_schema: str
    package_checksum: str
    safety_capabilities: tuple[str, ...]


@dataclass(frozen=True)
class DeploymentRecovery:
    schema_version: str
    engine_version: str
    configuration_snapshot_id: str
    recovery_epoch: int
    health_records: tuple[ComponentHealthRecord, ...]
    alerts: tuple[OperationalAlert, ...]
    diagnostics: tuple[DiagnosticResult, ...]
    updates: tuple[UpdateRecord, ...]
    permission_state: HealthState


class DeploymentDiagnosticsEngine:
    _RANK = {HealthState.HEALTHY: 0, HealthState.DEGRADED: 1, HealthState.UNKNOWN: 2,
             HealthState.RESTRICTED: 3, HealthState.RECOVERY_PENDING: 4,
             HealthState.SUSPENDED: 5, HealthState.FAILED: 6}

    def __init__(self, configuration=DeploymentConfiguration(), audit=None):
        errors = configuration.validate()
        if errors: raise ValueError(";".join(errors))
        self.configuration = configuration; self.audit = audit; self._lock = RLock()
        self.health_records = OrderedDict(); self.alerts = OrderedDict(); self.diagnostics = OrderedDict()
        self.updates = OrderedDict(); self.permission_state = HealthState.RECOVERY_PENDING
        self.recovery_restricted = False

    def publish_health(self, component_id, state, reason_code, dependency_ids, at, recovery_action):
        with self._lock:
            if not component_id or component_id in dependency_ids or len(self.health_records) >= self.configuration.maximum_components and component_id not in self.health_records:
                raise ValueError("DEPLOYMENT_HEALTH_INVALID")
            rid = deterministic_id("component_health", component_id, state.name, reason_code,
                                   *sorted(dependency_ids), at.isoformat())
            record = ComponentHealthRecord(rid, component_id, state, reason_code,
                                           tuple(sorted(dependency_ids)), at, recovery_action)
            self.health_records[component_id] = record
            if self._RANK[state] > self._RANK[self.permission_state]: self.permission_state = state
            elif self.permission_state is HealthState.RECOVERY_PENDING and state is HealthState.HEALTHY: self.permission_state = HealthState.HEALTHY
            return record

    def summary(self, at):
        records = tuple(self.health_records.values())
        if not records:
            state, roots, affected, reasons = HealthState.UNKNOWN, (), (), ("DEPLOYMENT_HEALTH_EMPTY",)
        else:
            state = max((x.state for x in records), key=lambda x: self._RANK[x])
            failed = {x.component_id for x in records if self._RANK[x.state] >= self._RANK[HealthState.RESTRICTED]}
            roots = tuple(sorted(x for x in failed if not set(self.health_records[x].dependency_ids) & failed))
            affected_set = set(failed)
            changed = True
            while changed:
                before = len(affected_set)
                affected_set.update(x.component_id for x in records if set(x.dependency_ids) & affected_set)
                changed = len(affected_set) != before
            affected = tuple(sorted(affected_set)); reasons = tuple(sorted({x.reason_code for x in records if x.component_id in affected_set}))
        sid = deterministic_id("health_summary", state.name, *roots, *affected, *reasons, at.isoformat())
        return SystemHealthSummary(sid, state, roots, affected, reasons, at)

    def alert(self, component_id, severity, reason_code, at, operator_action):
        with self._lock:
            logical = deterministic_id("alert_logical", component_id, severity.name, reason_code)
            existing = self.alerts.get(logical)
            if existing and existing.resolved_at_utc is None and at - existing.last_seen_utc <= self.configuration.alert_repeat_window:
                updated = replace(existing, last_seen_utc=at, occurrence_count=existing.occurrence_count + 1)
                self.alerts[logical] = updated; return updated
            record = OperationalAlert(logical, component_id, severity, reason_code, at, at, 1, None, operator_action)
            self.alerts[logical] = record
            while len(self.alerts) > self.configuration.maximum_alerts: self.alerts.popitem(last=False)
            return record

    def resolve_alert(self, alert_id, at):
        if alert_id not in self.alerts: return False
        self.alerts[alert_id] = replace(self.alerts[alert_id], resolved_at_utc=at); return True

    def diagnose(self, checks, at):
        with self._lock:
            results = []
            for check_id, fn, action in checks:
                try:
                    passed, evidence = fn()
                    state = CheckState.PASS if passed else CheckState.FAIL
                    reason = f"DIAGNOSTIC_{check_id}_{state.name}"
                except Exception:
                    state, evidence, reason = CheckState.UNKNOWN, (), f"DIAGNOSTIC_{check_id}_ERROR"
                did = deterministic_id("diagnostic", check_id, state.name, *evidence, at.isoformat())
                result = DiagnosticResult(did, check_id, state, reason, tuple(evidence), action, at)
                self.diagnostics[did] = result; results.append(result)
            overall = CheckState.FAIL if any(x.state is CheckState.FAIL for x in results) else CheckState.UNKNOWN if any(x.state is CheckState.UNKNOWN for x in results) else CheckState.PASS
            fingerprint = deterministic_id("diagnostic_fingerprint", *(x.diagnostic_id for x in results))
            sid = deterministic_id("diagnostic_summary", fingerprint, overall.name)
            return DiagnosticSummary(sid, tuple(results), overall, at, fingerprint)

    @staticmethod
    def support_bundle(application_version, environment_id, items, created_at, secrets=()):
        normalized = []
        for name, data in sorted(items.items()):
            text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
            for secret in secrets:
                if secret: text = text.replace(secret, "[REDACTED]")
            normalized.append((name, sha256(text.encode("utf-8")).hexdigest()))
        included = tuple(normalized); checksum = sha256(repr(included).encode("utf-8")).hexdigest()
        bid = deterministic_id("support_bundle", application_version, environment_id, created_at.isoformat(), checksum)
        return SupportBundleManifest(bid, application_version, environment_id, created_at, included, True, checksum)

    def prepare_update(self, manifest, current_version, package_bytes, backup_verified, configuration_compatible, state_compatible, at):
        with self._lock:
            reasons = []
            if current_version != manifest.from_version: reasons.append("UPDATE_VERSION_MISMATCH")
            if sha256(package_bytes).hexdigest() != manifest.package_checksum: reasons.append("UPDATE_CHECKSUM_MISMATCH")
            if not backup_verified: reasons.append("UPDATE_BACKUP_REQUIRED")
            if not configuration_compatible: reasons.append("UPDATE_CONFIGURATION_INCOMPATIBLE")
            if not state_compatible: reasons.append("UPDATE_STATE_INCOMPATIBLE")
            state = UpdateState.READY if not reasons else UpdateState.BLOCKED
            rid = deterministic_id("update_record", manifest.update_id, state.name, *reasons)
            record = UpdateRecord(rid, manifest.update_id, state, at, None, tuple(reasons),
                                  self.permission_state, self.permission_state)
            self.updates[rid] = record; return record

    def complete_update(self, record_id, success, at):
        with self._lock:
            record = self.updates[record_id]
            if record.state is not UpdateState.READY: return record
            state = UpdateState.APPLIED if success else UpdateState.ROLLED_BACK
            resulting = record.previous_permission_state if success else max(record.previous_permission_state, HealthState.RESTRICTED, key=lambda x: self._RANK[x])
            updated = replace(record, state=state, completed_at_utc=at,
                              reason_codes=("UPDATE_APPLIED",) if success else ("UPDATE_ROLLED_BACK",),
                              resulting_permission_state=resulting)
            self.updates[record_id] = updated; self.permission_state = resulting
            while len(self.updates) > self.configuration.maximum_update_history: self.updates.popitem(last=False)
            return updated

    @staticmethod
    def validate_paths(paths):
        normalized = tuple(sorted((name, str(PurePath(path))) for name, path in paths.items()))
        invalid = tuple(name for name, path in normalized if not path or path.startswith(("/", "~")) or ":" in path)
        return not invalid, invalid, normalized

    @staticmethod
    def release_manifest(version, build_timestamp, source_fingerprint, dependency_fingerprint,
                         configuration_schema, state_schema, package_checksum):
        capabilities = ("OFFLINE", "NON_FINANCIAL", "NON_EXECUTING", "NO_BROKER", "NO_ACCOUNT")
        rid = deterministic_id("release_manifest", version, build_timestamp.isoformat(), source_fingerprint,
                               dependency_fingerprint, configuration_schema, state_schema,
                               package_checksum, *capabilities)
        return ReleaseManifest(rid, version, build_timestamp, source_fingerprint,
                               dependency_fingerprint, configuration_schema, state_schema,
                               package_checksum, capabilities)

    def audit_global_state(self):
        problems = []
        for component_id, record in self.health_records.items():
            missing = set(record.dependency_ids) - set(self.health_records)
            if missing: problems.append((component_id, "MISSING_DEPENDENCY", tuple(sorted(missing))))
        if any(x.resulting_permission_state is HealthState.HEALTHY and self._RANK[x.previous_permission_state] > self._RANK[HealthState.HEALTHY] for x in self.updates.values()):
            problems.append(("UPDATE", "PERMISSION_IMPROVED_ON_RESTART", ()))
        return not problems, tuple(problems)

    def recovery_state(self, epoch):
        return DeploymentRecovery(SCHEMA, VERSION, self.configuration.configuration_snapshot_id,
                                  epoch, tuple(self.health_records.values()), tuple(self.alerts.values()),
                                  tuple(self.diagnostics.values()), tuple(self.updates.values()), self.permission_state)

    def restore(self, state, epoch):
        with self._lock:
            if (state.schema_version, state.engine_version, state.configuration_snapshot_id, state.recovery_epoch) != (SCHEMA, VERSION, self.configuration.configuration_snapshot_id, epoch):
                self.permission_state = HealthState.RECOVERY_PENDING; self.recovery_restricted = True; return False
            try:
                self.health_records = OrderedDict((x.component_id, x) for x in state.health_records)
                if len(self.health_records) != len(state.health_records): raise ValueError
                self.alerts = OrderedDict((x.alert_id, x) for x in state.alerts)
                self.diagnostics = OrderedDict((x.diagnostic_id, x) for x in state.diagnostics)
                self.updates = OrderedDict((x.record_id, x) for x in state.updates)
                self.permission_state = state.permission_state
                if not self.audit_global_state()[0]: raise ValueError
                self.recovery_restricted = False; return True
            except Exception:
                self.permission_state = HealthState.RECOVERY_PENDING; self.recovery_restricted = True; return False

    def replay_fingerprint(self):
        return deterministic_id("deployment_replay", *(x.record_id for x in self.health_records.values()),
                               *(x.alert_id for x in self.alerts.values()),
                               *(x.diagnostic_id for x in self.diagnostics.values()),
                               *(x.record_id for x in self.updates.values()), self.permission_state.name)

