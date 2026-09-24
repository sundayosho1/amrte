from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, Mapping


class SystemState(Enum):
    INITIALIZING = auto()
    READY = auto()
    RUNNING = auto()
    DEFENSIVE = auto()
    PROTECT = auto()
    SUSPENDED = auto()
    ERROR = auto()
    STOPPED = auto()


class RuntimeEnvironment(Enum):
    DEVELOPMENT = auto()
    TEST = auto()
    BACKTEST = auto()
    SIMULATION = auto()
    OPTIMIZATION = auto()
    RESEARCH = auto()
    UNKNOWN = auto()


class ResearchProfile(Enum):
    CONSERVATIVE = auto()
    BALANCED = auto()
    AGGRESSIVE = auto()
    CUSTOM = auto()


class StrategyId(Enum):
    SYSTEM = auto()
    TREND_PULLBACK = auto()
    BREAKOUT = auto()
    MEAN_REVERSION = auto()


class Severity(Enum):
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


class Direction(Enum):
    NONE = auto()
    LONG = auto()
    SHORT = auto()


class HealthStatus(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    RESTRICTED = auto()
    UNHEALTHY = auto()
    UNKNOWN = auto()


class ValidationStatus(Enum):
    VALID = auto()
    VALID_WITH_WARNINGS = auto()
    INVALID = auto()


class ConfigurationSource(Enum):
    HARD_CONSTRAINT = auto()
    GLOBAL_DEFAULT = auto()
    PROFILE = auto()
    STRATEGY_OVERRIDE = auto()
    INSTRUMENT_OVERRIDE = auto()
    RUNTIME_RESTRICTION = auto()


class SchemaCompatibility(Enum):
    CURRENT = auto()
    COMPATIBLE = auto()
    MIGRATION_REQUIRED = auto()
    INCOMPATIBLE = auto()
    CORRUPTED = auto()


class OverridePolicy(Enum):
    DENY = auto()
    ALLOW = auto()
    RESTRICT_ONLY = auto()


class Capability(Enum):
    MARKET_DATA_AVAILABLE = auto()
    SIMULATION_AVAILABLE = auto()
    BACKTEST_AVAILABLE = auto()
    OPTIMIZATION_AVAILABLE = auto()
    PERSISTENCE_AVAILABLE = auto()
    NEWS_DATA_AVAILABLE = auto()
    LIVE_BROKER_EXECUTION_AVAILABLE = auto()
    DEMO_BROKER_EXECUTION_AVAILABLE = auto()


class ConfigCategory(Enum):
    GENERAL = auto(); RUNTIME = auto(); INSTRUMENTS = auto(); TIMEFRAMES = auto()
    STRATEGIES = auto(); RISK = auto(); PORTFOLIO = auto(); CORRELATION = auto()
    DRAWDOWN = auto(); DAILY_LOSS = auto(); WEEKLY_LOSS = auto()
    EXECUTION_SIMULATION = auto(); SPREAD = auto(); SLIPPAGE = auto()
    SESSIONS = auto(); NEWS = auto(); TREND = auto(); BREAKOUT = auto()
    MEAN_REVERSION = auto(); STOP_LOSS = auto(); TAKE_PROFIT = auto()
    BREAK_EVEN = auto(); TRAILING = auto(); STRATEGY_HEALTH = auto()
    PROTECTION = auto(); LOGGING = auto(); NOTIFICATIONS = auto(); BACKTEST = auto()
    OPTIMIZATION = auto(); SIMULATION = auto()


@dataclass(frozen=True)
class InstrumentIdentity:
    canonical: str
    provider_symbol: str
    asset_class: str = "FICTIONAL"
    base_unit: str | None = None
    quote_unit: str | None = None
    metadata_status: HealthStatus = HealthStatus.UNKNOWN


@dataclass(frozen=True)
class TimeframeRoles:
    context: str
    strategy: str
    execution: str


@dataclass(frozen=True)
class EffectiveConfigurationSnapshot:
    values: Mapping[str, Any]
    provenance: Mapping[str, str]
    schema_version: str
    snapshot_id: str = ""
    application_version: str = ""
    selected_profile: ResearchProfile = ResearchProfile.BALANCED
    created_at: datetime | None = None
    configuration_hash: str = ""
    validation_status: ValidationStatus = ValidationStatus.VALID
    warnings: tuple[str, ...] = ()
    runtime_environment: RuntimeEnvironment = RuntimeEnvironment.RESEARCH
    overridden_sources: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))
        object.__setattr__(self, "overridden_sources", MappingProxyType(dict(self.overridden_sources)))


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: Severity
    path: str
    message: str
    current_value: Any = None
    constraint: str | None = None
    suggested_correction: str | None = None


@dataclass(frozen=True)
class ConfigurationValidation:
    status: ValidationStatus
    issues: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True)
class ConfigurationDiff:
    added: Mapping[str, Any]
    removed: Mapping[str, Any]
    changed: Mapping[str, tuple[Any, Any]]
    provenance_changed: Mapping[str, tuple[str | None, str | None]]
    safety_relevant: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "added", MappingProxyType(dict(self.added)))
        object.__setattr__(self, "removed", MappingProxyType(dict(self.removed)))
        object.__setattr__(self, "changed", MappingProxyType(dict(self.changed)))
        object.__setattr__(self, "provenance_changed", MappingProxyType(dict(self.provenance_changed)))


@dataclass(frozen=True)
class ResearchWorkspace:
    """Non-financial placeholder for later aggregate research state."""
    starting_units: float
    current_units: float
    base_unit: str
    profile: ResearchProfile
    state: SystemState


@dataclass(frozen=True)
class HealthReport:
    components: Mapping[str, HealthStatus]
    ready: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
