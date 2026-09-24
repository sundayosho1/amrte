from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from amrte.core.clock import FixedClock
from amrte.core.observability import (
    ConsoleSink, DecisionTraceBuilder, EmergencyFallbackSink, InMemoryEventSink,
    JsonLinesSink, NotificationDeduplicator, ObservabilityService, event_to_dict, export_csv,
)
from amrte.core.observability_types import (
    DecisionOutcome, DecisionStatus, EventCategory, EventClassification,
    ObservabilityHealth, Verbosity,
)
from amrte.core.types import Severity


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def service(**kwargs):
    sink = InMemoryEventSink()
    obs = ObservabilityService(FixedClock(NOW), (sink,), **kwargs)
    return obs, sink


@pytest.mark.parametrize("severity", list(Severity))
def test_all_severities(severity):
    obs, sink = service(verbosity=Verbosity.DEBUG)
    event = obs.emit(f"TEST_{severity.name}", severity.name, severity=severity,
                     category=EventCategory.TEST,
                     classifications=(EventClassification.AUDIT_EVENT,))
    assert event.severity is severity and sink.events[-1] is event


@pytest.mark.parametrize("category", list(EventCategory))
def test_every_category_contract(category):
    obs, _ = service()
    event = obs.emit(f"TEST_CATEGORY_{category.name}", category.name,
                     category=category,
                     classifications=(EventClassification.AUDIT_EVENT,))
    assert event.category is category


def test_structured_identity_sequence_epoch_correlation_and_causation():
    obs, _ = service(recovery_epoch=3)
    first = obs.emit("TEST_FIRST", "first", classifications=(EventClassification.AUDIT_EVENT,),
                     correlation_id="CORR-1")
    second = obs.emit("TEST_SECOND", "second", classifications=(EventClassification.AUDIT_EVENT,),
                      correlation_id="CORR-1", causation_id=first.event_id,
                      configuration_snapshot_id="CFG-1", configuration_hash="HASH-1")
    assert first.event_id != second.event_id
    assert (first.event_sequence, second.event_sequence) == (1, 2)
    assert second.recovery_epoch == 3 and second.correlation_id == "CORR-1"
    assert second.causation_id == first.event_id
    assert second.configuration_snapshot_id == "CFG-1"


def test_schema_is_immutable_and_canonical():
    obs, _ = service()
    event = obs.emit("TEST_IMMUTABLE", "immutable",
                     classifications=(EventClassification.AUDIT_EVENT,), context={"b": 2, "a": 1})
    with pytest.raises(TypeError): event.context["a"] = 3
    assert json.dumps(event_to_dict(event), sort_keys=True)


def test_redacts_nested_fields_and_sensitive_text_before_sink():
    obs, sink = service()
    obs.emit("TEST_REDACTION", "safe", classifications=(EventClassification.AUDIT_EVENT,),
             context={"password": "value", "nested": {"api_key": "value"},
                      "message": "contains secret material", "ordinary": "visible"})
    stored = sink.events[-1].context
    assert stored["password"] == "[REDACTED]"
    assert stored["nested"]["api_key"] == "[REDACTED]"
    assert stored["message"] == "[REDACTED_TEXT]"
    assert stored["ordinary"] == "visible"


def test_large_context_is_bounded():
    obs, _ = service()
    event = obs.emit("TEST_LARGE", "large", classifications=(EventClassification.AUDIT_EVENT,),
                     context={"items": list(range(100)), "text": "x" * 2000})
    assert event.context["items"][-1] == "[TRUNCATED_ITEMS]"
    assert event.context["text"].endswith("[TRUNCATED_TEXT]")


def test_hash_chain_verifies_and_detects_modification():
    obs, _ = service()
    for index in range(3):
        obs.emit(f"TEST_CHAIN_{index}", "chain",
                 classifications=(EventClassification.AUDIT_EVENT,))
    assert obs.verify_chain()
    modified = list(obs.events)
    modified[1] = replace(modified[1], message="modified")
    assert not obs.verify_chain(modified)
    assert obs.health is ObservabilityHealth.CORRUPTED


def test_query_and_incident_timeline():
    obs, _ = service()
    for index in range(3):
        obs.emit(f"TEST_TIMELINE_{index}", "timeline", category=EventCategory.RECOVERY,
                 classifications=(EventClassification.AUDIT_EVENT,), correlation_id="INCIDENT-1",
                 configuration_hash="CONFIG-HASH")
    obs.emit("TEST_OTHER", "other", classifications=(EventClassification.AUDIT_EVENT,),
             correlation_id="OTHER")
    assert len(obs.query(category=EventCategory.RECOVERY, configuration_hash="CONFIG-HASH")) == 3
    timeline = obs.incident_timeline("INCIDENT-1")
    assert len(timeline) == 3
    assert [event.event_sequence for event in timeline] == sorted(event.event_sequence for event in timeline)


@pytest.mark.parametrize("verbosity,debug_visible,info_visible", [
    (Verbosity.MINIMAL, False, False), (Verbosity.NORMAL, False, True),
    (Verbosity.VERBOSE, True, True), (Verbosity.DEBUG, True, True),
])
def test_verbosity_profiles_and_critical_preservation(verbosity, debug_visible, info_visible):
    obs, _ = service(verbosity=verbosity)
    debug = obs.emit("TEST_DEBUG_VIS", "debug", severity=Severity.DEBUG)
    info = obs.emit("TEST_INFO_VIS", "info", severity=Severity.INFO)
    critical = obs.emit("TEST_CRITICAL_VIS", "critical", severity=Severity.CRITICAL)
    assert (debug is not None) is debug_visible
    assert (info is not None) is info_visible
    assert critical is not None


def test_audit_event_not_suppressed_by_minimal_or_deduplication():
    obs, _ = service(verbosity=Verbosity.MINIMAL)
    first = obs.emit("TEST_AUDIT", "audit", severity=Severity.INFO,
                     classifications=(EventClassification.AUDIT_EVENT,))
    second = obs.emit("TEST_AUDIT", "audit", severity=Severity.INFO,
                      classifications=(EventClassification.AUDIT_EVENT,))
    assert first is not None and second is not None


def test_diagnostic_deduplication():
    obs, _ = service()
    assert obs.emit("TEST_REPEAT", "same") is not None
    assert obs.emit("TEST_REPEAT", "same") is None


def test_bounded_backpressure_prefers_audit_records():
    obs, _ = service(verbosity=Verbosity.DEBUG, maximum_history=10)
    audit = obs.emit("TEST_AUDIT_KEEP", "keep", classifications=(EventClassification.AUDIT_EVENT,))
    for index in range(20):
        obs.emit(f"TEST_DIAG_{index}", "diagnostic", severity=Severity.DEBUG)
    assert audit in obs.events
    assert len(obs.events) <= 10
    assert obs.dropped_diagnostics > 0


def test_console_and_in_memory_sinks_and_flush():
    output = []
    console = ConsoleSink(output.append); memory = InMemoryEventSink()
    obs = ObservabilityService(FixedClock(NOW), (console, memory))
    obs.emit("TEST_CONSOLE", "visible", classifications=(EventClassification.AUDIT_EVENT,))
    obs.flush()
    assert "TEST_CONSOLE" in output[0] and memory.flushed


def test_jsonl_output_rotation_retention_and_storage_limit(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonLinesSink(path, maximum_file_bytes=1600, rotation_count=2, maximum_total_bytes=4500)
    obs = ObservabilityService(FixedClock(NOW), (sink,))
    for index in range(8):
        obs.emit(f"TEST_JSONL_{index}", "x" * 100,
                 classifications=(EventClassification.AUDIT_EVENT,))
    assert path.exists()
    assert list(tmp_path.glob("audit.jsonl.*"))
    for candidate in [path, *tmp_path.glob("audit.jsonl.*")]:
        for line in candidate.read_text().splitlines(): json.loads(line)
    assert sink.total_bytes() <= 4500


def test_authoritative_sink_failure_degrades_and_uses_fallback():
    fallback = EmergencyFallbackSink()
    failing = InMemoryEventSink(fail_writes=True)
    obs = ObservabilityService(FixedClock(NOW), (failing,), fallback=fallback)
    obs.emit("TEST_SINK_FAIL", "failure", severity=Severity.CRITICAL)
    assert obs.health is ObservabilityHealth.UNAVAILABLE
    assert fallback.records[-1][0] == "OBS_SINK_FAILED"


def test_fallback_failure_does_not_recurse():
    fallback = EmergencyFallbackSink(fail_writes=True)
    obs = ObservabilityService(FixedClock(NOW), (InMemoryEventSink(fail_writes=True),), fallback=fallback)
    obs.emit("TEST_DOUBLE_FAIL", "failure", severity=Severity.CRITICAL)
    assert obs.health is ObservabilityHealth.UNAVAILABLE


def test_exception_capture_redacts_safe_message_and_optional_stack():
    obs, _ = service()
    try:
        raise ValueError("ordinary failure appeared")
    except ValueError as exc:
        event = obs.capture_exception(exc, module="Test", operation="exception", include_stack=True)
    assert event.event_code == "OBS_EXCEPTION_CAPTURED"
    assert event.context["safe_message"] == "ordinary failure appeared"
    assert "ValueError" in event.context["stack"]


def test_decision_trace_pass_fail_skip_and_short_circuit():
    builder = DecisionTraceBuilder(FixedClock(NOW), "DECISION-1", "CORR-1")
    builder.evaluate("data", DecisionStatus.PASSED, "DATA_OK", "data valid")
    builder.evaluate("health", DecisionStatus.FAILED, "HEALTH_BLOCKED", "health not ready")
    with pytest.raises(RuntimeError):
        builder.evaluate("later", DecisionStatus.SKIPPED, "SKIP", "not reached")
    trace = builder.complete(DecisionOutcome.NO_ACTION, "health gate failed")
    assert trace.short_circuited_at == "health"
    assert trace.outcome is DecisionOutcome.NO_ACTION


def test_notification_deduplication_contract():
    dedupe = NotificationDeduplicator()
    notify1, first = dedupe.register("INCIDENT-A", NOW, 60)
    notify2, second = dedupe.register("INCIDENT-A", NOW, 60)
    assert notify1 and not notify2
    assert second.occurrence_count == 2 and second.escalation_level == 1


def test_selected_event_csv_export_excludes_context(tmp_path):
    obs, _ = service()
    event = obs.emit("TEST_CSV", "csv", classifications=(EventClassification.AUDIT_EVENT,),
                     context={"ordinary": "not-exported"})
    path = tmp_path / "selected.csv"
    export_csv((event,), path)
    content = path.read_text(encoding="utf-8")
    assert "TEST_CSV" in content and "not-exported" not in content
