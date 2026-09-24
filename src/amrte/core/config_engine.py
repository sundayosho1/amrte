from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config_schema import HARD_SAFETY_VALUES, SCHEMA, SettingDefinition, contains_secret_key
from .constants import AMRTE_VERSION, CONFIG_SCHEMA_VERSION, MAX_CONCURRENT_SCENARIOS, MAX_RESEARCH_RESOURCE_LOAD
from .errors import AMRTEError, Result
from .identity import deterministic_id
from .interfaces import IAuditSink, IClock, IConfigurationProvider
from .profiles import PROFILE_DELTAS
from .types import (
    ConfigurationDiff, ConfigurationSource, ConfigurationValidation,
    EffectiveConfigurationSnapshot, OverridePolicy, ResearchProfile,
    RuntimeEnvironment, SchemaCompatibility, Severity, ValidationIssue,
    ValidationStatus,
)


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Mapping):
        return {str(k): _json_value(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    return value


def canonical_serialize(values: Mapping[str, Any], profile: ResearchProfile,
                        schema_version: str = CONFIG_SCHEMA_VERSION) -> str:
    payload = {"profile": profile.name, "schema_version": schema_version, "values": _json_value(values)}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def configuration_hash(values: Mapping[str, Any], profile: ResearchProfile,
                       schema_version: str = CONFIG_SCHEMA_VERSION) -> str:
    return hashlib.sha256(canonical_serialize(values, profile, schema_version).encode("utf-8")).hexdigest()


def classify_schema(version: Any) -> SchemaCompatibility:
    if not isinstance(version, str) or not version:
        return SchemaCompatibility.CORRUPTED
    if version == CONFIG_SCHEMA_VERSION:
        return SchemaCompatibility.CURRENT
    try:
        current_major = int(CONFIG_SCHEMA_VERSION.split(".")[0])
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        return SchemaCompatibility.CORRUPTED
    if major == current_major:
        return SchemaCompatibility.COMPATIBLE
    if major < current_major:
        return SchemaCompatibility.MIGRATION_REQUIRED
    return SchemaCompatibility.INCOMPATIBLE


class IConfigurationMigrator:
    def can_migrate(self, source_version: str, target_version: str) -> bool:
        raise NotImplementedError

    def migrate(self, values: Mapping[str, Any], source_version: str,
                target_version: str) -> Mapping[str, Any]:
        raise NotImplementedError


class ConfigurationValidator:
    def validate(self, values: Mapping[str, Any], *, strict: bool = True) -> ConfigurationValidation:
        issues: list[ValidationIssue] = []
        for key in sorted(set(values) - set(SCHEMA)):
            severity = Severity.ERROR if strict or contains_secret_key(key) else Severity.WARNING
            issues.append(ValidationIssue("UNKNOWN_FIELD", severity, key, "unknown configuration field",
                                          values[key], "field must be declared in schema",
                                          "remove the field or add an approved schema definition"))
        for key, definition in SCHEMA.items():
            if key not in values:
                if definition.required and definition.deprecated_replacement is None:
                    issues.append(ValidationIssue("MISSING_REQUIRED", Severity.ERROR, key,
                                                  "required value is missing"))
                continue
            self._validate_field(definition, values[key], issues)
            if definition.deprecated_replacement:
                issues.append(ValidationIssue("DEPRECATED_FIELD", Severity.WARNING, key,
                                              "deprecated configuration field", values[key],
                                              f"use {definition.deprecated_replacement}"))
        self._cross_validate(values, issues)
        errors = [issue for issue in issues if issue.severity in (Severity.ERROR, Severity.CRITICAL)]
        status = ValidationStatus.INVALID if errors else (
            ValidationStatus.VALID_WITH_WARNINGS if issues else ValidationStatus.VALID
        )
        return ConfigurationValidation(status, tuple(issues))

    def _validate_field(self, definition: SettingDefinition, value: Any,
                        issues: list[ValidationIssue]) -> None:
        expected = definition.value_type
        valid_type = isinstance(value, expected)
        if expected is float:
            valid_type = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not valid_type:
            issues.append(ValidationIssue("INVALID_TYPE", Severity.ERROR, definition.key,
                                          f"expected {expected.__name__}", value))
            return
        if isinstance(value, float) and not math.isfinite(value):
            issues.append(ValidationIssue("NON_FINITE", Severity.ERROR, definition.key,
                                          "value must be finite", value))
            return
        if definition.minimum is not None and value < definition.minimum:
            issues.append(ValidationIssue("BELOW_MINIMUM", Severity.ERROR, definition.key,
                                          "value is below minimum", value, f">={definition.minimum}"))
        if definition.maximum is not None and value > definition.maximum:
            issues.append(ValidationIssue("ABOVE_MAXIMUM", Severity.ERROR, definition.key,
                                          "value exceeds maximum", value, f"<={definition.maximum}"))
        if definition.choices and value not in definition.choices:
            issues.append(ValidationIssue("INVALID_ENUM", Severity.ERROR, definition.key,
                                          "value is not an allowed choice", value,
                                          ",".join(map(str, definition.choices))))
        if isinstance(value, str) and definition.required and not value.strip():
            issues.append(ValidationIssue("EMPTY_REQUIRED", Severity.ERROR, definition.key,
                                          "required text must not be empty", value))

    def _cross_validate(self, values: Mapping[str, Any], issues: list[ValidationIssue]) -> None:
        if values.get("research.minimum_units", 0) > values.get("research.starting_units", 0):
            issues.append(ValidationIssue("INVALID_RESEARCH_UNIT_FLOOR", Severity.ERROR,
                                          "research.minimum_units", "minimum exceeds starting units"))
        instruments = values.get("instruments.enabled", ())
        if not instruments or any(not isinstance(item, str) or not item.startswith("FICTIONAL_") for item in instruments):
            issues.append(ValidationIssue("INVALID_FICTIONAL_INSTRUMENT", Severity.ERROR,
                                          "instruments.enabled", "only non-empty FICTIONAL_* identifiers are permitted"))
        ranks = {"M15": 1, "H1": 2, "H4": 3, "D1": 4}
        context, strategy, execution = (values.get(f"timeframes.{name}") for name in ("context", "strategy", "execution"))
        if all(item in ranks for item in (context, strategy, execution)) and not (ranks[context] >= ranks[strategy] >= ranks[execution]):
            issues.append(ValidationIssue("INVALID_TIMEFRAME_ORDER", Severity.ERROR, "timeframes",
                                          "expected context >= strategy >= execution"))
        if values.get("research.max_resource_load", 0) > MAX_RESEARCH_RESOURCE_LOAD:
            issues.append(ValidationIssue("RESOURCE_CEILING_EXCEEDED", Severity.CRITICAL,
                                          "research.max_resource_load", "hard ceiling exceeded"))
        if values.get("research.max_concurrent_scenarios", 0) > MAX_CONCURRENT_SCENARIOS:
            issues.append(ValidationIssue("SCENARIO_CEILING_EXCEEDED", Severity.CRITICAL,
                                          "research.max_concurrent_scenarios", "hard ceiling exceeded"))
        entry = values.get("structure.consolidation_entry_threshold", 0)
        exit_threshold = values.get("structure.consolidation_exit_threshold", 0)
        if isinstance(entry, (int, float)) and isinstance(exit_threshold, (int, float)) and exit_threshold < entry:
            issues.append(ValidationIssue("INVALID_STRUCTURE_HYSTERESIS", Severity.ERROR,
                                          "structure.consolidation_exit_threshold",
                                          "exit threshold must be >= entry threshold"))
        weights = values.get("structure.alignment_weights", ())
        if not isinstance(weights, tuple) or len(weights) != 3 or any(not isinstance(item, (int, float)) or item < 0 for item in weights) or not sum(weights):
            issues.append(ValidationIssue("INVALID_ALIGNMENT_WEIGHTS", Severity.ERROR,
                                          "structure.alignment_weights",
                                          "three non-negative weights with positive total are required"))
        fast, slow = values.get("features.macd_fast", 0), values.get("features.macd_slow", 0)
        if isinstance(fast, int) and isinstance(slow, int) and fast >= slow:
            issues.append(ValidationIssue("INVALID_MACD_PERIODS", Severity.ERROR,
                                          "features.macd_fast", "MACD fast period must be below slow period"))
        periods = values.get("features.ema_periods", ())
        if not isinstance(periods, tuple) or not periods or any(not isinstance(item, int) or item <= 0 for item in periods):
            issues.append(ValidationIssue("INVALID_EMA_PERIODS", Severity.ERROR,
                                          "features.ema_periods", "EMA periods must be positive integers"))
        regime_entry = values.get("regime.entry_threshold", 0)
        regime_exit = values.get("regime.exit_threshold", 0)
        if isinstance(regime_entry, (int, float)) and isinstance(regime_exit, (int, float)) and regime_exit > regime_entry:
            issues.append(ValidationIssue("INVALID_REGIME_HYSTERESIS", Severity.ERROR,
                                          "regime.exit_threshold", "exit threshold must not exceed entry threshold"))
        regime_weights = values.get("regime.timeframe_weights", ())
        if not isinstance(regime_weights, tuple) or len(regime_weights) != 3 or any(not isinstance(item, (int, float)) or item < 0 for item in regime_weights) or not sum(regime_weights):
            issues.append(ValidationIssue("INVALID_REGIME_TIMEFRAME_WEIGHTS", Severity.ERROR,
                                          "regime.timeframe_weights", "three non-negative weights with positive total are required"))
        for key in ("time.reference_timezone","time.data_source_timezone","time.trading_day_timezone","time.trading_week_timezone"):
            try:
                ZoneInfo(values.get(key,""))
            except (ZoneInfoNotFoundError,ValueError,TypeError):
                issues.append(ValidationIssue("INVALID_TIMEZONE",Severity.ERROR,key,"valid IANA timezone required"))
        for key in ("time.trading_day_boundary","time.trading_week_start","time.friday_cutoff"):
            try:
                datetime.strptime(values.get(key,""),"%H:%M")
            except (ValueError,TypeError):
                issues.append(ValidationIssue("INVALID_LOCAL_TIME",Severity.ERROR,key,"HH:MM required"))
        for key in ("events.low_windows","events.medium_windows","events.high_windows","events.critical_windows"):
            window=values.get(key,())
            if not isinstance(window,tuple) or len(window)!=5 or any(not isinstance(item,int) or item<0 for item in window):
                issues.append(ValidationIssue("INVALID_EVENT_WINDOW",Severity.ERROR,key,"five non-negative integer durations required"))
        strategy_instruments=values.get("strategies.allowed_instruments",())
        if not isinstance(strategy_instruments,tuple) or not strategy_instruments or any(not isinstance(item,str) or not item.startswith("FICTIONAL_") for item in strategy_instruments):
            issues.append(ValidationIssue("INVALID_STRATEGY_INSTRUMENTS",Severity.ERROR,"strategies.allowed_instruments","non-empty FICTIONAL_* identifiers required"))
        for key, expected in HARD_SAFETY_VALUES.items():
            if values.get(key) != expected:
                issues.append(ValidationIssue("HARD_SAFETY_VIOLATION", Severity.CRITICAL, key,
                                              "hard safety value changed", values.get(key), str(expected)))


def diff_snapshots(a: EffectiveConfigurationSnapshot,
                   b: EffectiveConfigurationSnapshot) -> ConfigurationDiff:
    a_keys, b_keys = set(a.values), set(b.values)
    added = {key: b.values[key] for key in sorted(b_keys - a_keys)}
    removed = {key: a.values[key] for key in sorted(a_keys - b_keys)}
    changed = {key: (a.values[key], b.values[key]) for key in sorted(a_keys & b_keys)
               if a.values[key] != b.values[key]}
    provenance_changed = {key: (a.provenance.get(key), b.provenance.get(key))
                          for key in sorted(a_keys | b_keys)
                          if a.provenance.get(key) != b.provenance.get(key)}
    safety_relevant = tuple(sorted(key for key in set(changed) | set(added) | set(removed)
                                   if key in SCHEMA and SCHEMA[key].safety_critical))
    return ConfigurationDiff(added, removed, changed, provenance_changed, safety_relevant)


class MasterConfigurationEngine:
    def __init__(self, clock: IClock, audit: IAuditSink):
        self._clock = clock
        self._audit = audit
        self._validator = ConfigurationValidator()
        self._active: EffectiveConfigurationSnapshot | None = None
        self._last_valid: EffectiveConfigurationSnapshot | None = None

    @property
    def active_snapshot(self) -> EffectiveConfigurationSnapshot | None:
        return self._active

    @property
    def last_valid_snapshot(self) -> EffectiveConfigurationSnapshot | None:
        return self._last_valid

    def build_candidate(self, profile: ResearchProfile = ResearchProfile.BALANCED, *,
                        custom: Mapping[str, Any] | None = None,
                        strategy: Mapping[str, Any] | None = None,
                        instrument: Mapping[str, Any] | None = None,
                        runtime: Mapping[str, Any] | None = None,
                        environment: RuntimeEnvironment = RuntimeEnvironment.RESEARCH,
                        schema_version: str = CONFIG_SCHEMA_VERSION) -> Result[EffectiveConfigurationSnapshot]:
        compatibility = classify_schema(schema_version)
        if compatibility not in (SchemaCompatibility.CURRENT, SchemaCompatibility.COMPATIBLE):
            return self._failure("SCHEMA_MISMATCH", f"schema is {compatibility.name}")
        values = {key: definition.default for key, definition in SCHEMA.items()
                  if definition.deprecated_replacement is None}
        provenance = {key: ConfigurationSource.GLOBAL_DEFAULT.name for key in values}
        history: dict[str, list[str]] = {key: [] for key in values}
        layers = [
            (ConfigurationSource.PROFILE, PROFILE_DELTAS[profile]),
            (ConfigurationSource.PROFILE, custom or {}),
            (ConfigurationSource.STRATEGY_OVERRIDE, strategy or {}),
            (ConfigurationSource.INSTRUMENT_OVERRIDE, instrument or {}),
            (ConfigurationSource.RUNTIME_RESTRICTION, runtime or {}),
        ]
        for source, layer in layers:
            merge = self._merge(values, provenance, history, layer, source)
            if not merge.success:
                self._audit.record("configuration_rejected", {"code": merge.error.code})
                return merge
        for key, value in HARD_SAFETY_VALUES.items():
            if values.get(key) != value:
                return self._failure("HARD_SAFETY_OVERRIDE", f"cannot override {key}")
            provenance[key] = ConfigurationSource.HARD_CONSTRAINT.name
        strict = bool(values.get("general.strict_validation", True))
        validation = self._validator.validate(values, strict=strict)
        if validation.status is ValidationStatus.INVALID:
            self._audit.record("configuration_rejected", {"issues": [issue.code for issue in validation.issues]})
            return self._failure("CONFIGURATION_INVALID", "; ".join(f"{i.path}:{i.code}" for i in validation.issues))
        fingerprint = configuration_hash(values, profile, schema_version)
        snapshot = EffectiveConfigurationSnapshot(
            values=values, provenance=provenance, schema_version=schema_version,
            snapshot_id=deterministic_id("config", fingerprint), application_version=AMRTE_VERSION,
            selected_profile=profile, created_at=self._clock.now(), configuration_hash=fingerprint,
            validation_status=validation.status,
            warnings=tuple(issue.message for issue in validation.issues if issue.severity is Severity.WARNING),
            runtime_environment=environment,
            overridden_sources={key: tuple(items) for key, items in history.items() if items},
        )
        self._audit.record("configuration_candidate_built", {
            "profile": profile.name, "snapshot_id": snapshot.snapshot_id,
            "configuration_hash": fingerprint, "status": validation.status.name,
        })
        return Result.ok(snapshot, snapshot.warnings)

    def activate(self, candidate: EffectiveConfigurationSnapshot, *, safe_boundary: bool) -> Result[EffectiveConfigurationSnapshot]:
        if not safe_boundary:
            return self._failure("UNSAFE_ACTIVATION_BOUNDARY", "activation requires a deterministic safe boundary")
        if candidate.validation_status is ValidationStatus.INVALID:
            return self._failure("INVALID_CANDIDATE", "invalid candidate cannot become active")
        previous = self._active
        self._active = candidate
        self._last_valid = candidate
        change = diff_snapshots(previous, candidate) if previous else None
        self._audit.record("configuration_activated", {
            "snapshot_id": candidate.snapshot_id,
            "changed": sorted(change.changed) if change else [],
        })
        return Result.ok(candidate)

    def switch_profile(self, profile: ResearchProfile, *, safe_boundary: bool,
                       custom: Mapping[str, Any] | None = None) -> Result[EffectiveConfigurationSnapshot]:
        candidate = self.build_candidate(profile, custom=custom)
        if not candidate.success:
            self._audit.record("configuration_rollback", {
                "retained": self._active.snapshot_id if self._active else None,
            })
            return candidate
        return self.activate(candidate.value, safe_boundary=safe_boundary)

    def _merge(self, values: dict[str, Any], provenance: dict[str, str],
               history: dict[str, list[str]], layer: Mapping[str, Any],
               source: ConfigurationSource) -> Result[None]:
        for key in sorted(layer):
            value = layer[key]
            definition = SCHEMA.get(key)
            if definition is None:
                values[key] = value
                provenance[key] = source.name
                continue
            if definition.override_policy is OverridePolicy.DENY and value != definition.default:
                return self._failure("HARD_SAFETY_OVERRIDE", f"cannot override {key}")
            if definition.override_policy is OverridePolicy.RESTRICT_ONLY:
                if isinstance(definition.default, bool) and definition.default and value is False:
                    return self._failure("RESTRICTION_WEAKENED", f"cannot weaken {key}")
            previous = provenance.get(key)
            if previous:
                history.setdefault(key, []).append(previous)
            if isinstance(values.get(key), Mapping) and isinstance(value, Mapping):
                values[key] = {**values[key], **value}
            else:
                values[key] = tuple(value) if definition.value_type is tuple and isinstance(value, list) else value
            provenance[key] = source.name
        return Result.ok()

    def _failure(self, code: str, message: str):
        return Result.fail(AMRTEError(self._clock.now(), "Core.Configuration", "resolve",
                                      Severity.ERROR, code, message, recoverable=True))


class MasterConfigurationProvider(IConfigurationProvider):
    """Lifecycle adapter that activates one validated snapshot atomically."""

    def __init__(self, engine: MasterConfigurationEngine,
                 profile: ResearchProfile = ResearchProfile.BALANCED,
                 custom: Mapping[str, Any] | None = None):
        self.engine = engine
        self.profile = profile
        self.custom = custom

    def load(self) -> Result[EffectiveConfigurationSnapshot]:
        candidate = self.engine.build_candidate(self.profile, custom=self.custom)
        if not candidate.success:
            return candidate
        return self.engine.activate(candidate.value, safe_boundary=True)
