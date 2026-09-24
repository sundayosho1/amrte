from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

from amrte.core.errors import AMRTEError, Result
from amrte.core.interfaces import IAuditSink, IExecutionProvider, IRandomSource, IStateRepository
from amrte.core.types import Severity
from amrte.core.clock import SystemClock


class InMemoryAuditSink(IAuditSink):
    def __init__(self, observer=None) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.flushed = False
        self.observer = observer

    def record(self, event: str, context: Mapping[str, Any]) -> None:
        self.events.append((event, dict(context)))
        if self.observer is not None:
            self.observer.record(event, context)

    def flush(self) -> None:
        self.flushed = True
        if self.observer is not None:
            self.observer.flush()


class InMemoryStateRepository(IStateRepository):
    def __init__(self, initial: Mapping[str, Any] | None = None, available: bool = True):
        self._state = dict(initial or {})
        self.available = available

    def load(self) -> Result[Mapping[str, Any]]:
        return Result.ok(dict(self._state)) if self.available else self._failure("load")

    def save(self, state: Mapping[str, Any]) -> Result[None]:
        if not self.available:
            return self._failure("save")
        self._state = dict(state)
        return Result.ok()

    def _failure(self, function: str):
        return Result.fail(AMRTEError(SystemClock().now(), "Infrastructure.State", function,
                                      Severity.CRITICAL, "PERSISTENCE_UNAVAILABLE",
                                      "local state repository unavailable"))


class SeededRandomSource(IRandomSource):
    def __init__(self, seed: int):
        self._seed = seed
        self._random = random.Random(seed)
        self._position = 0

    @property
    def seed(self) -> int:
        return self._seed

    def random(self) -> float:
        self._position += 1
        return self._random.random()

    @property
    def position(self) -> int:
        return self._position

    def restore(self, seed: int, position: int) -> None:
        if position < 0:
            raise ValueError("random sequence position must be non-negative")
        self._seed = seed
        self._random = random.Random(seed)
        self._position = 0
        for _ in range(position):
            self.random()


class ProhibitedExecutionProvider(IExecutionProvider):
    """Permanent safety implementation: every execution request is rejected."""
    def __init__(self, audit: IAuditSink):
        self._audit = audit

    def submit(self, request: Mapping[str, Any]) -> Result[None]:
        self._audit.record("prohibited_capability_requested", {"capability": "EXECUTION"})
        return Result.fail(AMRTEError(SystemClock().now(), "Infrastructure.Execution", "submit",
                                      Severity.CRITICAL, "CAPABILITY_NOT_AVAILABLE",
                                      "order execution is not available in this research build",
                                      recoverable=False))
