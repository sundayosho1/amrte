from __future__ import annotations

from .errors import AMRTEError, Result
from .interfaces import IAuditSink, IClock
from .types import Severity, SystemState


ALLOWED_TRANSITIONS: dict[SystemState, frozenset[SystemState]] = {
    SystemState.INITIALIZING: frozenset({SystemState.READY, SystemState.ERROR, SystemState.SUSPENDED}),
    SystemState.READY: frozenset({SystemState.RUNNING, SystemState.SUSPENDED, SystemState.ERROR, SystemState.STOPPED}),
    SystemState.RUNNING: frozenset({SystemState.DEFENSIVE, SystemState.PROTECT, SystemState.SUSPENDED, SystemState.ERROR, SystemState.STOPPED}),
    SystemState.DEFENSIVE: frozenset({SystemState.RUNNING, SystemState.PROTECT, SystemState.SUSPENDED, SystemState.ERROR, SystemState.STOPPED}),
    SystemState.PROTECT: frozenset({SystemState.DEFENSIVE, SystemState.SUSPENDED, SystemState.ERROR, SystemState.STOPPED}),
    SystemState.SUSPENDED: frozenset({SystemState.READY, SystemState.ERROR, SystemState.STOPPED}),
    SystemState.ERROR: frozenset({SystemState.SUSPENDED, SystemState.STOPPED}),
    SystemState.STOPPED: frozenset(),
}


class StateMachine:
    def __init__(self, clock: IClock, audit: IAuditSink):
        self._clock = clock
        self._audit = audit
        self._state = SystemState.INITIALIZING

    @property
    def state(self) -> SystemState:
        return self._state

    def transition(self, target: SystemState, reason: str) -> Result[SystemState]:
        if target not in ALLOWED_TRANSITIONS[self._state]:
            error = AMRTEError(self._clock.now(), "Core.State", "transition", Severity.ERROR,
                               "ILLEGAL_STATE_TRANSITION", f"{self._state.name} -> {target.name}",
                               context={"reason": reason}, recoverable=True)
            self._audit.record("state_transition_rejected", {"from": self._state.name, "to": target.name})
            return Result.fail(error)
        previous = self._state
        self._state = target
        self._audit.record("state_transition", {"from": previous.name, "to": target.name, "reason": reason})
        return Result.ok(target)

