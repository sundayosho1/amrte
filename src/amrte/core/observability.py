from __future__ import annotations

import csv
import json
import os
import traceback
from collections import deque
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from .constants import AMRTE_VERSION
from .event_codes import validate_event_code
from .identity import deterministic_id
from .interfaces import IAuditSink, IClock
from .observability_types import (
    ActorType, DecisionEvaluation, DecisionOutcome, DecisionStatus, DecisionTrace,
    EventCategory, EventClassification, NotificationState, ObservabilityHealth,
    StructuredEvent, Verbosity,
)
from .persistence import canonical_json, sha256_json
from .types import Severity


SENSITIVE_FRAGMENTS = (
    "password", "secret", "token", "credential", "api_key", "private_key",
    "broker", "authentication",
)
SEVERITY_RANK = {Severity.DEBUG: 0, Severity.INFO: 1, Severity.WARNING: 2,
                 Severity.ERROR: 3, Severity.CRITICAL: 4}


class IEventSink(Protocol):
    authoritative: bool
    health: ObservabilityHealth
    def write(self, event: StructuredEvent) -> None: ...
    def flush(self) -> None: ...


class INotificationProvider(Protocol):
    def notify(self, notification_key: str, event: StructuredEvent) -> None: ...


def _safe_value(value: Any, *, depth: int = 0, max_depth: int = 5,
                max_items: int = 50, max_text: int = 1000) -> Any:
    if depth > max_depth:
        return "[TRUNCATED_DEPTH]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, nested) in enumerate(value.items()):
            if index >= max_items:
                result["_truncated"] = True
                break
            key_text = str(key)
            if any(fragment in key_text.lower() for fragment in SENSITIVE_FRAGMENTS):
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = _safe_value(nested, depth=depth + 1,
                                               max_depth=max_depth, max_items=max_items,
                                               max_text=max_text)
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        safe = [_safe_value(item, depth=depth + 1, max_depth=max_depth,
                            max_items=max_items, max_text=max_text)
                for item in items[:max_items]]
        if len(items) > max_items:
            safe.append("[TRUNCATED_ITEMS]")
        return safe
    if isinstance(value, str):
        lowered = value.lower()
        if any(fragment in lowered for fragment in SENSITIVE_FRAGMENTS):
            return "[REDACTED_TEXT]"
        if len(value) > max_text:
            return value[:max_text] + "[TRUNCATED_TEXT]"
        return value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:max_text]


def event_to_dict(event: StructuredEvent, *, include_hash: bool = True) -> dict[str, Any]:
    result = {
        "event_id": event.event_id, "event_sequence": event.event_sequence,
        "timestamp": event.timestamp.isoformat(), "monotonic_order": event.monotonic_order,
        "runtime_environment": event.runtime_environment,
        "application_version": event.application_version, "instance_id": event.instance_id,
        "recovery_epoch": event.recovery_epoch, "experiment_id": event.experiment_id,
        "dataset_id": event.dataset_id, "configuration_snapshot_id": event.configuration_snapshot_id,
        "configuration_hash": event.configuration_hash, "module": event.module,
        "operation": event.operation, "severity": event.severity.name,
        "classifications": [item.name for item in event.classifications],
        "category": event.category.name, "event_type": event.event_type,
        "event_code": event.event_code, "message": event.message,
        "system_state": event.system_state, "correlation_id": event.correlation_id,
        "causation_id": event.causation_id, "strategy_id": event.strategy_id,
        "instrument_id": event.instrument_id, "decision_id": event.decision_id,
        "simulation_object_id": event.simulation_object_id, "checkpoint_id": event.checkpoint_id,
        "context": dict(event.context), "tags": list(event.tags),
        "previous_audit_hash": event.previous_audit_hash,
    }
    if include_hash:
        result["event_hash"] = event.event_hash
    return result


class InMemoryEventSink:
    authoritative = True

    def __init__(self, fail_writes: bool = False):
        self.events: list[StructuredEvent] = []
        self.health = ObservabilityHealth.HEALTHY
        self.fail_writes = fail_writes
        self.flushed = False

    def write(self, event: StructuredEvent) -> None:
        if self.fail_writes:
            self.health = ObservabilityHealth.UNAVAILABLE
            raise OSError("injected event sink failure")
        self.events.append(event)

    def flush(self) -> None:
        self.flushed = True


class JsonLinesSink:
    authoritative = True

    def __init__(self, path: Path, *, maximum_file_bytes: int = 1_000_000,
                 rotation_count: int = 3, maximum_total_bytes: int = 5_000_000,
                 fail_writes: bool = False):
        self.path = Path(path)
        self.maximum_file_bytes = maximum_file_bytes
        self.rotation_count = max(1, rotation_count)
        self.maximum_total_bytes = maximum_total_bytes
        self.fail_writes = fail_writes
        self.health = ObservabilityHealth.UNKNOWN
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.health = ObservabilityHealth.HEALTHY

    def write(self, event: StructuredEvent) -> None:
        if self.fail_writes:
            self.health = ObservabilityHealth.UNAVAILABLE
            raise OSError("injected JSONL write failure")
        encoded = (canonical_json(event_to_dict(event)) + "\n").encode("utf-8")
        if len(encoded) > self.maximum_file_bytes:
            self.health = ObservabilityHealth.DEGRADED
            raise ValueError("single event exceeds maximum file size")
        if self.path.exists() and self.path.stat().st_size + len(encoded) > self.maximum_file_bytes:
            self.rotate()
        if self.total_bytes() + len(encoded) > self.maximum_total_bytes:
            self.apply_retention()
        if self.total_bytes() + len(encoded) > self.maximum_total_bytes:
            self.health = ObservabilityHealth.DEGRADED
            raise OSError("total log storage limit reached")
        with self.path.open("ab") as handle:
            handle.write(encoded); handle.flush(); os.fsync(handle.fileno())

    def rotate(self) -> None:
        oldest = self.path.with_suffix(self.path.suffix + f".{self.rotation_count}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self.rotation_count - 1, 0, -1):
            source = self.path.with_suffix(self.path.suffix + f".{index}")
            target = self.path.with_suffix(self.path.suffix + f".{index + 1}")
            if source.exists():
                os.replace(source, target)
        if self.path.exists():
            os.replace(self.path, self.path.with_suffix(self.path.suffix + ".1"))

    def apply_retention(self) -> None:
        rotated = sorted(self.path.parent.glob(self.path.name + ".*"),
                         key=lambda item: item.stat().st_mtime)
        while rotated and self.total_bytes() >= self.maximum_total_bytes:
            rotated.pop(0).unlink()

    def total_bytes(self) -> int:
        return sum(path.stat().st_size for path in [self.path, *self.path.parent.glob(self.path.name + ".*")]
                   if path.exists())

    def flush(self) -> None:
        return None


class ConsoleSink:
    authoritative = False

    def __init__(self, writer=None):
        self.writer = writer or print
        self.health = ObservabilityHealth.HEALTHY

    def write(self, event: StructuredEvent) -> None:
        self.writer(f"{event.timestamp.isoformat()} {event.severity.name} {event.event_code} {event.message}")

    def flush(self) -> None:
        return None


class EmergencyFallbackSink:
    authoritative = False

    def __init__(self, capacity: int = 50, fail_writes: bool = False):
        self.records = deque(maxlen=capacity)
        self.health = ObservabilityHealth.HEALTHY
        self.fail_writes = fail_writes

    def write_minimal(self, code: str, message: str) -> None:
        if self.fail_writes:
            self.health = ObservabilityHealth.UNAVAILABLE
            return
        self.records.append((code, message[:500]))

    def write(self, event: StructuredEvent) -> None:
        self.write_minimal(event.event_code, event.message)

    def flush(self) -> None:
        return None


class ObservabilityService(IAuditSink):
    def __init__(self, clock: IClock, sinks: Iterable[IEventSink], *,
                 instance_id: str = "AMRTE-RESEARCH-001", runtime_environment: str = "RESEARCH",
                 recovery_epoch: int = 0, verbosity: Verbosity = Verbosity.NORMAL,
                 minimum_severity: Severity = Severity.DEBUG, maximum_history: int = 1000,
                 fallback: EmergencyFallbackSink | None = None):
        self.clock = clock; self.sinks = tuple(sinks); self.instance_id = instance_id
        self.runtime_environment = runtime_environment; self.recovery_epoch = recovery_epoch
        self.verbosity = verbosity; self.minimum_severity = minimum_severity
        self.maximum_history = max(10, maximum_history); self.fallback = fallback or EmergencyFallbackSink()
        self.health = ObservabilityHealth.HEALTHY; self._sequence = 0; self._previous_hash = None
        self._history: list[StructuredEvent] = []; self._failure_guard = False
        self._dedupe: dict[str, tuple[datetime, int]] = {}
        self.dropped_diagnostics = 0

    @property
    def events(self) -> tuple[StructuredEvent, ...]:
        return tuple(self._history)

    def record(self, event: str, context: Mapping[str, Any]) -> None:
        code, category, classifications, severity = self._legacy_mapping(event)
        self.emit(code, event.replace("_", " "), severity=severity, category=category,
                  classifications=classifications, module="LegacyHook", operation=event,
                  context=context)

    def emit(self, event_code: str, message: str, *, severity: Severity = Severity.INFO,
             category: EventCategory = EventCategory.SYSTEM,
             classifications: tuple[EventClassification, ...] = (EventClassification.LOG_EVENT,),
             module: str = "Core", operation: str = "emit", context: Mapping[str, Any] | None = None,
             correlation_id: str | None = None, causation_id: str | None = None,
             experiment_id: str | None = None, dataset_id: str | None = None,
             configuration_snapshot_id: str | None = None, configuration_hash: str | None = None,
             system_state: str | None = None, decision_id: str | None = None,
             checkpoint_id: str | None = None, tags: tuple[str, ...] = ()) -> StructuredEvent | None:
        if not validate_event_code(event_code):
            raise ValueError(f"unregistered event-code namespace: {event_code}")
        if not self._should_emit(severity, classifications):
            return None
        if self._should_dedupe(event_code, classifications):
            return None
        self._sequence += 1
        now = self.clock.now(); correlation = correlation_id or deterministic_id("correlation", self.instance_id, self.recovery_epoch, self._sequence)
        event_id = deterministic_id("event", self.instance_id, self.recovery_epoch, self._sequence, event_code)
        safe_context = _safe_value(dict(context or {}))
        event = StructuredEvent(
            event_id, self._sequence, now, self._sequence, self.runtime_environment,
            AMRTE_VERSION, self.instance_id, self.recovery_epoch, experiment_id,
            dataset_id, configuration_snapshot_id, configuration_hash, module, operation,
            severity, classifications, category, event_code, event_code, message,
            system_state, correlation, causation_id, decision_id=decision_id,
            checkpoint_id=checkpoint_id, context=safe_context, tags=tags,
            previous_audit_hash=self._previous_hash,
        )
        event_hash = sha256_json(event_to_dict(event, include_hash=False))
        event = replace(event, event_hash=event_hash)
        self._previous_hash = event_hash
        self._retain(event)
        self._route(event)
        return event

    def capture_exception(self, exc: BaseException, *, module: str, operation: str,
                          correlation_id: str | None = None, include_stack: bool = False) -> StructuredEvent | None:
        context = {"exception_type": type(exc).__name__, "safe_message": str(exc)[:500]}
        if include_stack:
            context["stack"] = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:]
        return self.emit("OBS_EXCEPTION_CAPTURED", "unexpected exception captured",
                         severity=Severity.ERROR, category=EventCategory.SYSTEM,
                         classifications=(EventClassification.ERROR_EVENT, EventClassification.AUDIT_EVENT),
                         module=module, operation=operation, context=context,
                         correlation_id=correlation_id)

    def query(self, *, severity: Severity | None = None, category: EventCategory | None = None,
              event_code: str | None = None, correlation_id: str | None = None,
              configuration_hash: str | None = None, recovery_epoch: int | None = None,
              start: datetime | None = None, end: datetime | None = None) -> tuple[StructuredEvent, ...]:
        result = self._history
        return tuple(event for event in result if
                     (severity is None or event.severity is severity) and
                     (category is None or event.category is category) and
                     (event_code is None or event.event_code == event_code) and
                     (correlation_id is None or event.correlation_id == correlation_id) and
                     (configuration_hash is None or event.configuration_hash == configuration_hash) and
                     (recovery_epoch is None or event.recovery_epoch == recovery_epoch) and
                     (start is None or event.timestamp >= start) and (end is None or event.timestamp <= end))

    def incident_timeline(self, correlation_id: str) -> tuple[StructuredEvent, ...]:
        return tuple(sorted(self.query(correlation_id=correlation_id), key=lambda event: event.event_sequence))

    def verify_chain(self, events: Iterable[StructuredEvent] | None = None) -> bool:
        selected = tuple(events or self._history)
        previous = selected[0].previous_audit_hash if selected else None
        for event in selected:
            if event.previous_audit_hash != previous:
                self.health = ObservabilityHealth.CORRUPTED
                return False
            if sha256_json(event_to_dict(event, include_hash=False)) != event.event_hash:
                self.health = ObservabilityHealth.CORRUPTED
                return False
            previous = event.event_hash
        return True

    def flush(self) -> None:
        for sink in self.sinks:
            try: sink.flush()
            except Exception as exc: self._sink_failure(sink, exc)

    def _route(self, event: StructuredEvent) -> None:
        for sink in self.sinks:
            try: sink.write(event)
            except Exception as exc: self._sink_failure(sink, exc)

    def _sink_failure(self, sink: IEventSink, exc: Exception) -> None:
        if self._failure_guard:
            self.health = ObservabilityHealth.UNAVAILABLE
            return
        self._failure_guard = True
        try:
            self.health = ObservabilityHealth.UNAVAILABLE if getattr(sink, "authoritative", False) else ObservabilityHealth.DEGRADED
            self.fallback.write_minimal("OBS_SINK_FAILED", f"{type(sink).__name__}:{type(exc).__name__}")
        finally:
            self._failure_guard = False

    def _retain(self, event: StructuredEvent) -> None:
        if len(self._history) >= self.maximum_history:
            removable = next((index for index, old in enumerate(self._history)
                              if EventClassification.AUDIT_EVENT not in old.classifications and
                              old.severity in (Severity.DEBUG, Severity.INFO)), None)
            if removable is None:
                self.health = ObservabilityHealth.DEGRADED; self.dropped_diagnostics += 1
                self.fallback.write_minimal("OBS_BACKPRESSURE", "history capacity reached")
                return
            self._history.pop(removable); self.dropped_diagnostics += 1
        self._history.append(event)

    def _should_emit(self, severity: Severity, classes: tuple[EventClassification, ...]) -> bool:
        if severity in (Severity.ERROR, Severity.CRITICAL) or EventClassification.AUDIT_EVENT in classes:
            return True
        if SEVERITY_RANK[severity] < SEVERITY_RANK[self.minimum_severity]:
            return False
        allowed = {Verbosity.MINIMAL: Severity.WARNING, Verbosity.NORMAL: Severity.INFO,
                   Verbosity.VERBOSE: Severity.DEBUG, Verbosity.DEBUG: Severity.DEBUG}[self.verbosity]
        return SEVERITY_RANK[severity] >= SEVERITY_RANK[allowed]

    def _should_dedupe(self, code: str, classes: tuple[EventClassification, ...]) -> bool:
        if EventClassification.AUDIT_EVENT in classes:
            return False
        now = self.clock.now(); previous = self._dedupe.get(code)
        if previous and now - previous[0] <= timedelta(seconds=1):
            self._dedupe[code] = (previous[0], previous[1] + 1); return True
        self._dedupe[code] = (now, 1); return False

    def _legacy_mapping(self, event: str):
        mappings = {
            "state_transition": ("STATE_TRANSITION", EventCategory.STATE, (EventClassification.AUDIT_EVENT, EventClassification.STATE_TRANSITION_EVENT), Severity.INFO),
            "state_transition_rejected": ("STATE_TRANSITION_REJECTED", EventCategory.STATE, (EventClassification.AUDIT_EVENT, EventClassification.STATE_TRANSITION_EVENT), Severity.WARNING),
            "checkpoint_saved": ("PERSIST_CHECKPOINT_SAVED", EventCategory.PERSISTENCE, (EventClassification.AUDIT_EVENT,), Severity.INFO),
            "checkpoint_write_failed": ("PERSIST_WRITE_FAILED", EventCategory.PERSISTENCE, (EventClassification.AUDIT_EVENT, EventClassification.ERROR_EVENT), Severity.ERROR),
            "checkpoint_quarantined": ("PERSIST_QUARANTINED", EventCategory.SECURITY_INTEGRITY, (EventClassification.AUDIT_EVENT, EventClassification.SECURITY_INTEGRITY_EVENT), Severity.ERROR),
            "recovery_started": ("REC_STARTED", EventCategory.RECOVERY, (EventClassification.AUDIT_EVENT, EventClassification.RECOVERY_EVENT), Severity.INFO),
            "recovery_result": ("REC_COMPLETED", EventCategory.RECOVERY, (EventClassification.AUDIT_EVENT, EventClassification.RECOVERY_EVENT), Severity.INFO),
            "configuration_rejected": ("CFG_VALIDATION_FAILED", EventCategory.CONFIGURATION, (EventClassification.AUDIT_EVENT, EventClassification.ERROR_EVENT), Severity.ERROR),
            "configuration_activated": ("CFG_ACTIVATED", EventCategory.CONFIGURATION, (EventClassification.AUDIT_EVENT,), Severity.INFO),
            "configuration_rollback": ("CFG_ROLLBACK", EventCategory.CONFIGURATION, (EventClassification.AUDIT_EVENT,), Severity.WARNING),
        }
        return mappings.get(event, (f"OBS_{event.upper()}", EventCategory.SYSTEM,
                                    (EventClassification.LOG_EVENT,), Severity.INFO))


class DecisionTraceBuilder:
    def __init__(self, clock: IClock, decision_id: str, correlation_id: str):
        self.clock = clock; self.decision_id = decision_id; self.correlation_id = correlation_id
        self.started_at = clock.now(); self.evaluations: list[DecisionEvaluation] = []
        self.short_circuited_at = None

    def evaluate(self, gate: str, status: DecisionStatus, reason_code: str,
                 explanation: str, input_references: tuple[str, ...] = ()) -> None:
        if self.short_circuited_at is not None:
            raise RuntimeError("decision trace already short-circuited")
        self.evaluations.append(DecisionEvaluation(gate, status, reason_code, explanation, input_references))
        if status is DecisionStatus.FAILED:
            self.short_circuited_at = gate

    def complete(self, outcome: DecisionOutcome, reason: str) -> DecisionTrace:
        return DecisionTrace(self.decision_id, self.correlation_id, self.started_at,
                             tuple(self.evaluations), outcome, reason, self.clock.now(),
                             self.short_circuited_at)


class NotificationDeduplicator:
    def __init__(self): self._states: dict[str, NotificationState] = {}

    def register(self, key: str, now: datetime, cooldown_seconds: int) -> tuple[bool, NotificationState]:
        previous = self._states.get(key)
        if previous is None:
            state = NotificationState(key, now, now, 1, cooldown_seconds, 1)
            self._states[key] = state; return True, state
        elapsed = (now - previous.last_occurrence).total_seconds()
        state = NotificationState(key, previous.first_occurrence, now,
                                  previous.occurrence_count + 1, cooldown_seconds,
                                  previous.escalation_level + (1 if elapsed >= cooldown_seconds else 0))
        self._states[key] = state
        return elapsed >= cooldown_seconds, state


def export_csv(events: Iterable[StructuredEvent], path: Path) -> None:
    """Export selected event summaries without context payloads or secrets."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "event_id", "event_sequence", "timestamp", "severity", "category",
            "event_code", "correlation_id", "recovery_epoch",
        ))
        writer.writeheader()
        for event in events:
            writer.writerow({
                "event_id": event.event_id, "event_sequence": event.event_sequence,
                "timestamp": event.timestamp.isoformat(), "severity": event.severity.name,
                "category": event.category.name, "event_code": event.event_code,
                "correlation_id": event.correlation_id, "recovery_epoch": event.recovery_epoch,
            })
