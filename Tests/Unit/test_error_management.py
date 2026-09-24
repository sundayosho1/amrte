from datetime import datetime, timezone

from amrte.core.clock import FixedClock
from amrte.core.error_management import ErrorManager, RetryPolicy
from amrte.core.errors import AMRTEError, Result
from amrte.core.observability import InMemoryEventSink, ObservabilityService
from amrte.core.observability_types import ErrorClassification
from amrte.core.recovery import IdempotencyLedger
from amrte.core.types import Severity


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def setup(threshold=3):
    clock = FixedClock(NOW); sink = InMemoryEventSink()
    obs = ObservabilityService(clock, (sink,))
    return clock, sink, obs, ErrorManager(clock, obs, storm_threshold=threshold)


def error(code="TEST_FAILURE", severity=Severity.ERROR, recoverable=True):
    return AMRTEError(NOW, "Test", "operation", severity, code, "failed",
                      recoverable=recoverable, suggested_action="inspect test")


def test_error_classification_and_counters():
    _, _, _, manager = setup()
    managed = manager.capture(error())
    assert managed.classification is ErrorClassification.RECOVERABLE
    assert managed.occurrence_count == 1
    assert manager.count_in_window("TEST_FAILURE") == 1


def test_critical_fatal_escalates_immediately():
    _, _, _, manager = setup()
    managed = manager.capture(error(severity=Severity.CRITICAL, recoverable=False))
    assert managed.classification is ErrorClassification.FATAL and managed.escalated


def test_error_storm_aggregates_and_escalates():
    _, sink, _, manager = setup(threshold=3)
    states = [manager.capture(error()) for _ in range(3)]
    assert states[-1].escalated
    assert any(event.event_code == "ERR_STORM" for event in sink.events)


def test_bounded_retry_and_idempotent_commit():
    _, _, _, manager = setup()
    attempts = {"count": 0}
    def operation():
        attempts["count"] += 1
        return Result.ok("done") if attempts["count"] == 3 else Result.fail(error("TRANSIENT"))
    ledger = IdempotencyLedger()
    result = manager.execute_with_retry(operation, RetryPolicy(3, ("TRANSIENT",)),
                                        idempotency_key="OP-1", ledger=ledger)
    assert result.success and attempts["count"] == 3 and ledger.is_committed("OP-1")
    repeated = manager.execute_with_retry(operation, RetryPolicy(3, ("TRANSIENT",)),
                                          idempotency_key="OP-1", ledger=ledger)
    assert not repeated.success and repeated.error.code == "RETRY_ALREADY_COMMITTED"


def test_non_retryable_failure_stops_immediately():
    _, _, _, manager = setup()
    attempts = {"count": 0}
    def operation():
        attempts["count"] += 1
        return Result.fail(error("PERMANENT"))
    result = manager.execute_with_retry(operation, RetryPolicy(3, ("TRANSIENT",)),
                                        idempotency_key="OP-2", ledger=IdempotencyLedger())
    assert not result.success and attempts["count"] == 1

