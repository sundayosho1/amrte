from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from types import MappingProxyType
from typing import Mapping


class ProviderCapability(Enum):
    BAR_DATA = auto(); BID_ASK_DATA = auto(); TICK_DATA = auto(); VOLUME_DATA = auto()
    REAL_VOLUME_DATA = auto(); SPREAD_DATA = auto(); INSTRUMENT_METADATA = auto()


class BarState(Enum):
    CLOSED_BAR = auto(); CURRENT_FORMING_BAR = auto(); UNKNOWN_BAR_STATE = auto()


class DataValidity(Enum):
    VALID = auto(); SUSPECT = auto(); INVALID = auto(); UNKNOWN = auto()


class VolumeKind(Enum):
    TICK_VOLUME = auto(); REAL_VOLUME = auto(); SYNTHETIC_VOLUME = auto(); UNAVAILABLE = auto()


class GapClassification(Enum):
    EXPECTED_CLOSURE = auto(); DATASET_BOUNDARY = auto(); MISSING_DATA = auto(); UNKNOWN_GAP = auto()


class DuplicateClassification(Enum):
    IDENTICAL_DUPLICATE = auto(); CONFLICTING_DUPLICATE = auto()


class AnomalyClassification(Enum):
    VALID_EXTREME_EVENT = auto(); SUSPECT = auto(); INVALID = auto(); UNKNOWN = auto()


class SpreadHealth(Enum):
    NORMAL = auto(); ELEVATED = auto(); EXTREME = auto(); UNAVAILABLE = auto(); UNKNOWN = auto()


class SpreadOrigin(Enum):
    OBSERVED = auto(); MODELED = auto(); UNAVAILABLE = auto()


class DataHealth(Enum):
    HEALTHY = auto(); DEGRADED = auto(); STALE = auto(); INCOMPLETE = auto()
    INVALID = auto(); UNAVAILABLE = auto(); UNKNOWN = auto()


class SynchronizationStatus(Enum):
    SYNCHRONIZED = auto(); PARTIALLY_SYNCHRONIZED = auto(); UNSYNCHRONIZED = auto()
    INSUFFICIENT_DATA = auto(); UNKNOWN = auto()


class WarmupStatus(Enum):
    NOT_STARTED = auto(); LOADING = auto(); INSUFFICIENT_HISTORY = auto()
    READY = auto(); DEGRADED = auto(); FAILED = auto()


class AdmissionStatus(Enum):
    ADMITTED = auto(); ADMITTED_WITH_WARNINGS = auto(); REJECTED = auto()


@dataclass(frozen=True)
class InstrumentMetadata:
    canonical_id: str
    provider_id: str
    asset_class: str = "FICTIONAL"
    precision: int | None = None
    tick_size: float | None = None
    supported_timeframes: tuple[str, ...] = ()
    capabilities: frozenset[ProviderCapability] = frozenset()


@dataclass(frozen=True)
class DataProvenance:
    provider_id: str
    dataset_id: str
    dataset_version: str
    dataset_fingerprint: str
    source_type: str
    import_timestamp: datetime
    original_timezone: str
    normalized_timezone: str
    instrument_id: str
    timeframe: str
    requested_start: datetime | None = None
    requested_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None


@dataclass(frozen=True)
class NormalizedBar:
    instrument_id: str
    timeframe: str
    open_time: datetime
    close_time: datetime | None
    open: float
    high: float
    low: float
    close: float
    tick_volume: float | None = None
    real_volume: float | None = None
    spread: float | None = None
    bar_state: BarState = BarState.CLOSED_BAR
    validity: DataValidity = DataValidity.UNKNOWN
    source_reference: str = ""
    bar_id: str = ""
    volume_kind: VolumeKind = VolumeKind.UNAVAILABLE


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    message: str
    instrument_id: str | None = None
    timeframe: str | None = None
    record_index: int | None = None


@dataclass(frozen=True)
class DatasetValidationReport:
    dataset_id: str
    dataset_fingerprint: str
    record_count: int
    date_range: tuple[datetime | None, datetime | None]
    instruments: tuple[str, ...]
    timeframes: tuple[str, ...]
    missing_records: int
    duplicate_records: int
    conflicting_duplicates: int
    invalid_ohlc: int
    timestamp_issues: int
    gap_count: int
    anomaly_count: int
    overall_health: DataHealth
    admission: AdmissionStatus
    warnings: tuple[ValidationFinding, ...] = ()
    errors: tuple[ValidationFinding, ...] = ()


@dataclass(frozen=True)
class SpreadState:
    current_spread: float | None
    spread_in_price_units: float | None
    normalized_spread: float | None
    rolling_typical_spread: float | None
    spread_deviation: float | None
    health: SpreadHealth
    origin: SpreadOrigin


@dataclass(frozen=True)
class MarketDataSnapshot:
    snapshot_id: str
    created_at: datetime
    as_of_timestamp: datetime
    experiment_id: str
    dataset_id: str
    dataset_fingerprint: str
    instrument_id: str
    bid_ask_state: SpreadState
    context_bars: tuple[NormalizedBar, ...]
    strategy_bars: tuple[NormalizedBar, ...]
    execution_bars: tuple[NormalizedBar, ...]
    synchronization_status: SynchronizationStatus
    data_health: DataHealth
    data_quality_score: float
    provenance: Mapping[str, DataProvenance]
    configuration_snapshot_id: str
    recovery_epoch: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True)
class DatasetAdmission:
    status: AdmissionStatus
    report: DatasetValidationReport
    normalized_bars: tuple[NormalizedBar, ...]


@dataclass(frozen=True)
class NewBarState:
    last_observed_bar_id: str | None
    last_closed_bar_id: str | None
    current_bar_id: str | None
    new_closed_bar_available: bool

