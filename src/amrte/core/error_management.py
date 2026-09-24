from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, TypeVar

from .errors import AMRTEError, Result
from .interfaces import IClock
from .observability import ObservabilityService
from .observability_types import ErrorClassification, EventCategory, EventClassification
from .recovery import IdempotencyLedger
from .types import Severity

T = TypeVar("T")


@dataclass(frozen=True)
class ManagedError:
    error: AMRTEError
    classification: ErrorClassification
    occurrence_count: int
    escalated: bool


@dataclass(frozen=True)
class RetryPolicy:
    maximum_attempts: int = 3
    retryable_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.maximum_attempts < 1 or self.maximum_attempts > 10:
            raise ValueError("maximum attempts must be between 1 and 10")


class ErrorManager:
    def __init__(self, clock: IClock, observability: ObservabilityService, *,
                 storm_threshold: int = 5, window_seconds: int = 60):
        self.clock = clock; self.observability = observability
        self.storm_threshold = storm_threshold; self.window_seconds = window_seconds
        self.counters: Counter[str] = Counter(); self._windows: dict[str, deque[datetime]] = {}

    def capture(self, error: AMRTEError,
                classification: ErrorClassification | None = None) -> ManagedError:
        kind = classification or self._classify(error)
        self.counters[error.code] += 1
        window = self._windows.setdefault(error.code, deque())
        now = self.clock.now(); window.append(now)
        cutoff = now - timedelta(seconds=self.window_seconds)
        while window and window[0] < cutoff: window.popleft()
        escalated = len(window) >= self.storm_threshold or kind in (
            ErrorClassification.CRITICAL, ErrorClassification.FATAL
        )
        severity = Severity.CRITICAL if escalated else error.severity
        self.observability.emit(
            "ERR_ESCALATED" if escalated else "ERR_CAPTURED", error.message,
            severity=severity, category=EventCategory.SYSTEM,
            classifications=(EventClassification.ERROR_EVENT, EventClassification.AUDIT_EVENT),
            module=error.module, operation=error.function,
            correlation_id=error.correlation_id,
            context={"error_code": error.code, "classification": kind.name,
                     "recoverable": error.recoverable, "occurrences_in_window": len(window),
                     "suggested_action": error.suggested_action},
        )
        if len(window) == self.storm_threshold:
            self.observability.emit(
                "ERR_STORM", "error storm threshold reached", severity=Severity.CRITICAL,
                category=EventCategory.HEALTH,
                classifications=(EventClassification.ERROR_EVENT, EventClassification.HEALTH_EVENT,
                                 EventClassification.AUDIT_EVENT),
                module="ErrorManager", operation="capture",
                context={"error_code": error.code, "count": len(window),
                         "window_seconds": self.window_seconds},
            )
        return ManagedError(error, kind, self.counters[error.code], escalated)

    def execute_with_retry(self, operation: Callable[[], Result[T]], policy: RetryPolicy,
                           *, idempotency_key: str, ledger: IdempotencyLedger) -> Result[T]:
        if ledger.is_committed(idempotency_key):
            return Result.fail(self._error("RETRY_ALREADY_COMMITTED", "operation was already committed"))
        last: Result[T] | None = None
        for _ in range(policy.maximum_attempts):
            last = operation()
            if last.success:
                ledger.commit(idempotency_key)
                return last
            if not last.error or last.error.code not in policy.retryable_codes:
                return last
        return last or Result.fail(self._error("RETRY_NO_ATTEMPT", "retry operation did not execute"))

    def count_in_window(self, code: str) -> int:
        now = self.clock.now(); cutoff = now - timedelta(seconds=self.window_seconds)
        window = self._windows.get(code, deque())
        return sum(1 for timestamp in window if timestamp >= cutoff)

    def _classify(self, error: AMRTEError) -> ErrorClassification:
        if error.severity is Severity.CRITICAL and not error.recoverable:
            return ErrorClassification.FATAL
        if error.severity is Severity.CRITICAL:
            return ErrorClassification.CRITICAL
        if error.severity is Severity.ERROR and error.recoverable:
            return ErrorClassification.RECOVERABLE
        if error.severity is Severity.ERROR:
            return ErrorClassification.DEGRADED
        return ErrorClassification.TRANSIENT

    def _error(self, code: str, message: str) -> AMRTEError:
        return AMRTEError(self.clock.now(), "Core.ErrorManager", "execute_with_retry",
                          Severity.ERROR, code, message, recoverable=False)

