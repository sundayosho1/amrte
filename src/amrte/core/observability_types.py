from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, Mapping

from .types import Severity


class EventClassification(Enum):
    LOG_EVENT = auto(); AUDIT_EVENT = auto(); ERROR_EVENT = auto()
    DECISION_EVENT = auto(); STATE_TRANSITION_EVENT = auto(); RECOVERY_EVENT = auto()
    HEALTH_EVENT = auto(); SECURITY_INTEGRITY_EVENT = auto(); METRIC_EVENT = auto()


class EventCategory(Enum):
    SYSTEM = auto(); CONFIGURATION = auto(); STATE = auto(); HEALTH = auto()
    PERSISTENCE = auto(); RECOVERY = auto(); DATASET = auto(); MARKET_DATA = auto()
    FEATURE = auto(); REGIME = auto(); SESSION = auto(); NEWS = auto(); SIGNAL = auto()
    STRATEGY = auto(); RISK = auto(); PORTFOLIO = auto(); SIMULATION = auto()
    EXECUTION_SIMULATION = auto(); PROTECTION = auto(); PERFORMANCE = auto()
    SECURITY_INTEGRITY = auto(); TEST = auto()


class Verbosity(Enum):
    MINIMAL = auto(); NORMAL = auto(); VERBOSE = auto(); DEBUG = auto()


class ObservabilityHealth(Enum):
    HEALTHY = auto(); DEGRADED = auto(); READ_ONLY = auto(); UNAVAILABLE = auto()
    CORRUPTED = auto(); UNKNOWN = auto()


class ErrorClassification(Enum):
    TRANSIENT = auto(); RECOVERABLE = auto(); DEGRADED = auto(); CRITICAL = auto(); FATAL = auto()


class DecisionStatus(Enum):
    PASSED = auto(); FAILED = auto(); SKIPPED = auto(); NOT_APPLICABLE = auto()


class DecisionOutcome(Enum):
    ACCEPTED = auto(); REJECTED = auto(); BLOCKED = auto(); EXPIRED = auto(); NO_ACTION = auto()


class ActorType(Enum):
    SYSTEM = auto(); CONFIGURATION_ENGINE = auto(); RECOVERY_ENGINE = auto()
    TEST_HARNESS = auto(); USER_REQUEST = auto()


@dataclass(frozen=True)
class AuditContext:
    actor_type: ActorType
    action: str
    target: str
    reason: str
    result: str
    previous_value_reference: str | None = None
    new_value_reference: str | None = None
    authorization_context: str | None = None


@dataclass(frozen=True)
class StructuredEvent:
    event_id: str
    event_sequence: int
    timestamp: datetime
    monotonic_order: int
    runtime_environment: str
    application_version: str
    instance_id: str
    recovery_epoch: int
    experiment_id: str | None
    dataset_id: str | None
    configuration_snapshot_id: str | None
    configuration_hash: str | None
    module: str
    operation: str
    severity: Severity
    classifications: tuple[EventClassification, ...]
    category: EventCategory
    event_type: str
    event_code: str
    message: str
    system_state: str | None
    correlation_id: str
    causation_id: str | None = None
    strategy_id: str | None = None
    instrument_id: str | None = None
    decision_id: str | None = None
    simulation_object_id: str | None = None
    checkpoint_id: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    previous_audit_hash: str | None = None
    event_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))


@dataclass(frozen=True)
class DecisionEvaluation:
    gate: str
    status: DecisionStatus
    reason_code: str
    explanation: str
    input_references: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecisionTrace:
    decision_id: str
    correlation_id: str
    started_at: datetime
    evaluations: tuple[DecisionEvaluation, ...]
    outcome: DecisionOutcome
    outcome_reason: str
    completed_at: datetime
    short_circuited_at: str | None = None


@dataclass(frozen=True)
class NotificationState:
    notification_key: str
    first_occurrence: datetime
    last_occurrence: datetime
    occurrence_count: int
    cooldown_seconds: int
    escalation_level: int
