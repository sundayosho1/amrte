from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from amrte.core.identity import deterministic_id
from .models import BarState, DataValidity, NormalizedBar, VolumeKind
from .service import TIMEFRAME_SECONDS


MARKET_OBSERVATION_SCHEMA_VERSION = "1.0"
DATASET_MANIFEST_SCHEMA_VERSION = "1.0"
MARKET_DATA_BOUNDARY_VERSION = "1.0"


class ObservationType(Enum):
    BAR = "BAR"


class BarTemporalSemantics(Enum):
    BAR_CLOSE = "BAR_CLOSE"


class ValidationStatus(Enum):
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    INVALID = "INVALID"


class ValidationReason(Enum):
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_OBSERVATION_TYPE = "INVALID_OBSERVATION_TYPE"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    NAIVE_TIMESTAMP = "NAIVE_TIMESTAMP"
    INVALID_NUMERIC_VALUE = "INVALID_NUMERIC_VALUE"
    INVALID_OHLC = "INVALID_OHLC"
    INVALID_VOLUME = "INVALID_VOLUME"
    DUPLICATE = "DUPLICATE"
    IDENTITY_COLLISION = "IDENTITY_COLLISION"
    REVISED_OBSERVATION = "REVISED_OBSERVATION"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    SEQUENCE_REGRESSION = "SEQUENCE_REGRESSION"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    AVAILABILITY_VIOLATION = "AVAILABILITY_VIOLATION"
    UNSUPPORTED_TIMEFRAME = "UNSUPPORTED_TIMEFRAME"
    UNKNOWN_INSTRUMENT = "UNKNOWN_INSTRUMENT"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    ADAPTER_ERROR = "ADAPTER_ERROR"
    RECORD_ERROR = "RECORD_ERROR"
    DATASET_ERROR = "DATASET_ERROR"


@dataclass(frozen=True)
class ValidationIssue:
    reason: ValidationReason
    message: str
    record_index: int | None = None
    observation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason.value,
            "message": self.message,
            "record_index": self.record_index,
            "observation_id": self.observation_id,
        }


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return self.status in (
            ValidationStatus.VALID,
            ValidationStatus.VALID_WITH_WARNINGS,
        )


@dataclass(frozen=True)
class InstrumentIdentity:
    canonical_id: str
    source_symbol: str
    asset_class: str = "FICTIONAL"
    price_precision: int | None = None
    volume_semantics: str = "TICK_OR_SOURCE_VOLUME"
    session_reference: str | None = None
    aliases: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.canonical_id or not self.source_symbol:
            raise ValueError("instrument identity requires canonical and source identifiers")
        object.__setattr__(self, "aliases", MappingProxyType(dict(self.aliases)))


@dataclass(frozen=True)
class SourceIdentity:
    source_id: str
    adapter_type: str
    adapter_version: str
    source_dataset: str
    source_version: str = "1"

    def __post_init__(self) -> None:
        if not all((self.source_id, self.adapter_type, self.adapter_version, self.source_dataset)):
            raise ValueError("source identity fields are required")


@dataclass(frozen=True)
class ObservationProvenance:
    source_record_locator: str
    source_path: str | None = None
    raw_record_fingerprint: str | None = None
    transformations: tuple[str, ...] = ()
    raw_retention_policy: str = "FINGERPRINT_ONLY"


@dataclass(frozen=True)
class CanonicalBarValues:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    volume_kind: str = "UNAVAILABLE"


@dataclass(frozen=True)
class CanonicalMarketObservation:
    schema_version: str
    observation_id: str
    instrument: InstrumentIdentity
    source: SourceIdentity
    observation_type: ObservationType
    timeframe: str
    temporal_semantics: BarTemporalSemantics
    period_start: datetime
    event_time: datetime
    available_at: datetime
    received_at: datetime
    sequence: int | None
    bar: CanonicalBarValues
    source_metadata: Mapping[str, Any]
    quality_metadata: Mapping[str, Any]
    provenance: ObservationProvenance
    observation_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_metadata", MappingProxyType(dict(self.source_metadata)))
        object.__setattr__(self, "quality_metadata", MappingProxyType(dict(self.quality_metadata)))


@dataclass(frozen=True)
class AdapterDiagnostics:
    total_records: int
    accepted_records: int
    rejected_records: int
    warnings: tuple[ValidationIssue, ...] = ()
    errors: tuple[ValidationIssue, ...] = ()
    status: ValidationStatus = ValidationStatus.VALID

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "accepted_records": self.accepted_records,
            "rejected_records": self.rejected_records,
            "warnings": [item.to_dict() for item in self.warnings],
            "errors": [item.to_dict() for item in self.errors],
            "status": self.status.value,
        }


@dataclass(frozen=True)
class AdapterResult:
    observations: tuple[CanonicalMarketObservation, ...]
    diagnostics: AdapterDiagnostics


@dataclass(frozen=True)
class DatasetManifest:
    manifest_schema_version: str
    dataset_id: str
    dataset_fingerprint: str
    observation_schema_version: str
    source_ids: tuple[str, ...]
    adapter_versions: tuple[str, ...]
    instruments: tuple[str, ...]
    timeframes: tuple[str, ...]
    temporal_start: datetime | None
    temporal_end: datetime | None
    observation_count: int
    validation_summary: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "validation_summary", MappingProxyType(dict(self.validation_summary)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_schema_version": self.manifest_schema_version,
            "dataset_id": self.dataset_id,
            "dataset_fingerprint": self.dataset_fingerprint,
            "observation_schema_version": self.observation_schema_version,
            "source_ids": list(self.source_ids),
            "adapter_versions": list(self.adapter_versions),
            "instruments": list(self.instruments),
            "timeframes": list(self.timeframes),
            "temporal_start": _datetime_text(self.temporal_start) if self.temporal_start else None,
            "temporal_end": _datetime_text(self.temporal_end) if self.temporal_end else None,
            "observation_count": self.observation_count,
            "validation_summary": dict(self.validation_summary),
        }


@dataclass(frozen=True)
class CanonicalMarketDataset:
    observations: tuple[CanonicalMarketObservation, ...]
    manifest: DatasetManifest
    diagnostics: AdapterDiagnostics

    def verify(self) -> ValidationResult:
        rebuilt = build_canonical_dataset(self.observations, strict=False)
        if rebuilt.manifest.dataset_fingerprint != self.manifest.dataset_fingerprint:
            return ValidationResult(
                ValidationStatus.INVALID,
                (ValidationIssue(ValidationReason.DATASET_ERROR, "dataset fingerprint mismatch"),),
            )
        if len(rebuilt.observations) != self.manifest.observation_count:
            return ValidationResult(
                ValidationStatus.INVALID,
                (ValidationIssue(ValidationReason.DATASET_ERROR, "dataset count mismatch"),),
            )
        return ValidationResult(ValidationStatus.VALID)


class CanonicalDatasetReplay:
    def __init__(self, dataset: CanonicalMarketDataset):
        self.dataset = dataset

    def available_as_of(self, logical_time: datetime) -> tuple[CanonicalMarketObservation, ...]:
        logical = _aware_utc(logical_time, "logical_time")
        return tuple(
            observation
            for observation in self.dataset.observations
            if observation.available_at <= logical
        )


def canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def schema_identity(kind: str) -> str:
    if kind == "observation":
        payload = {
            "schema": "canonical_market_observation",
            "version": MARKET_OBSERVATION_SCHEMA_VERSION,
            "observation_type": ObservationType.BAR.value,
            "temporal_semantics": BarTemporalSemantics.BAR_CLOSE.value,
            "fields": (
                "schema_version", "observation_id", "instrument", "source",
                "timeframe", "period_start", "event_time", "available_at",
                "received_at", "sequence", "bar", "provenance",
            ),
        }
    elif kind == "dataset_manifest":
        payload = {
            "schema": "canonical_market_dataset_manifest",
            "version": DATASET_MANIFEST_SCHEMA_VERSION,
            "fields": tuple(DatasetManifest.__dataclass_fields__),
        }
    else:
        raise ValueError("unknown schema identity kind")
    return _sha256_text(canonical_json(payload))


def create_canonical_bar(
    *,
    instrument: InstrumentIdentity,
    source: SourceIdentity,
    timeframe: str,
    period_start: datetime,
    period_end: datetime,
    available_at: datetime,
    received_at: datetime,
    open: Any,
    high: Any,
    low: Any,
    close: Any,
    volume: Any = None,
    volume_kind: str = "UNAVAILABLE",
    sequence: int | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    quality_metadata: Mapping[str, Any] | None = None,
    provenance: ObservationProvenance | None = None,
    logical_time: datetime | None = None,
) -> CanonicalMarketObservation:
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(ValidationReason.UNSUPPORTED_TIMEFRAME.value)
    start = _aware_utc(period_start, "period_start")
    end = _aware_utc(period_end, "period_end")
    available = _aware_utc(available_at, "available_at")
    received = _aware_utc(received_at, "received_at")
    if start >= end:
        raise ValueError(ValidationReason.INVALID_TIMESTAMP.value)
    if end > available or available > received:
        raise ValueError(ValidationReason.AVAILABILITY_VIOLATION.value)
    if logical_time is not None and available > _aware_utc(logical_time, "logical_time"):
        raise ValueError(ValidationReason.FUTURE_TIMESTAMP.value)
    values = CanonicalBarValues(
        _decimal(open, "open"),
        _decimal(high, "high"),
        _decimal(low, "low"),
        _decimal(close, "close"),
        _optional_decimal(volume, "volume"),
        volume_kind,
    )
    _validate_ohlc(values)
    identity = deterministic_id(
        "market_observation",
        source.source_id,
        instrument.canonical_id,
        ObservationType.BAR.value,
        timeframe,
        _datetime_text(end),
        "" if sequence is None else str(sequence),
    )
    provenance = provenance or ObservationProvenance(source_record_locator="")
    without_fingerprint = {
        "schema_version": MARKET_OBSERVATION_SCHEMA_VERSION,
        "observation_id": identity,
        "instrument": instrument,
        "source": source,
        "observation_type": ObservationType.BAR,
        "timeframe": timeframe,
        "temporal_semantics": BarTemporalSemantics.BAR_CLOSE,
        "period_start": start,
        "event_time": end,
        "available_at": available,
        "received_at": received,
        "sequence": sequence,
        "bar": values,
        "source_metadata": dict(source_metadata or {}),
        "quality_metadata": dict(quality_metadata or {}),
        "provenance": provenance,
    }
    fingerprint = _sha256_text(canonical_json(without_fingerprint))
    return CanonicalMarketObservation(
        MARKET_OBSERVATION_SCHEMA_VERSION,
        identity,
        instrument,
        source,
        ObservationType.BAR,
        timeframe,
        BarTemporalSemantics.BAR_CLOSE,
        start,
        end,
        available,
        received,
        sequence,
        values,
        source_metadata or {},
        quality_metadata or {},
        provenance,
        fingerprint,
    )


def validate_canonical_observation(
    observation: CanonicalMarketObservation,
    *,
    logical_time: datetime | None = None,
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    if observation.schema_version != MARKET_OBSERVATION_SCHEMA_VERSION:
        issues.append(ValidationIssue(ValidationReason.DATASET_ERROR, "unsupported observation schema version", observation_id=observation.observation_id))
    if observation.observation_type is not ObservationType.BAR:
        issues.append(ValidationIssue(ValidationReason.INVALID_OBSERVATION_TYPE, "only BAR observations are supported", observation_id=observation.observation_id))
    if observation.temporal_semantics is not BarTemporalSemantics.BAR_CLOSE:
        issues.append(ValidationIssue(ValidationReason.INVALID_TIMESTAMP, "only BAR_CLOSE temporal semantics are supported", observation_id=observation.observation_id))
    if observation.timeframe not in TIMEFRAME_SECONDS:
        issues.append(ValidationIssue(ValidationReason.UNSUPPORTED_TIMEFRAME, "unsupported timeframe", observation_id=observation.observation_id))
    try:
        start = _aware_utc(observation.period_start, "period_start")
        event = _aware_utc(observation.event_time, "event_time")
        available = _aware_utc(observation.available_at, "available_at")
        received = _aware_utc(observation.received_at, "received_at")
    except ValueError as exc:
        issues.append(ValidationIssue(_reason_from_exception(exc), str(exc), observation_id=observation.observation_id))
    else:
        if start >= event:
            issues.append(ValidationIssue(ValidationReason.INVALID_TIMESTAMP, "period_start must be before event_time", observation_id=observation.observation_id))
        if event > available or available > received:
            issues.append(ValidationIssue(ValidationReason.AVAILABILITY_VIOLATION, "event_time <= available_at <= received_at is required", observation_id=observation.observation_id))
        if logical_time is not None and available > _aware_utc(logical_time, "logical_time"):
            issues.append(ValidationIssue(ValidationReason.FUTURE_TIMESTAMP, "observation is not available at logical_time", observation_id=observation.observation_id))
    try:
        _validate_ohlc(observation.bar)
    except ValueError as exc:
        issues.append(ValidationIssue(_reason_from_exception(exc), str(exc), observation_id=observation.observation_id))
    expected_id = deterministic_id(
        "market_observation",
        observation.source.source_id,
        observation.instrument.canonical_id,
        ObservationType.BAR.value,
        observation.timeframe,
        _datetime_text(observation.event_time),
        "" if observation.sequence is None else str(observation.sequence),
    )
    if observation.observation_id != expected_id:
        issues.append(ValidationIssue(ValidationReason.IDENTITY_COLLISION, "observation_id does not match canonical identity", observation_id=observation.observation_id))
    expected_fingerprint = _sha256_text(canonical_json(_observation_payload_without_fingerprint(observation)))
    if observation.observation_fingerprint != expected_fingerprint:
        issues.append(ValidationIssue(ValidationReason.DATASET_ERROR, "observation fingerprint mismatch", observation_id=observation.observation_id))
    if issues:
        return ValidationResult(ValidationStatus.INVALID, tuple(issues))
    return ValidationResult(ValidationStatus.VALID)


class CSVBarSourceAdapter:
    adapter_type = "CSV_BAR"
    adapter_version = MARKET_DATA_BOUNDARY_VERSION

    required_columns = (
        "instrument",
        "timeframe",
        "period_start",
        "period_end",
        "available_at",
        "received_at",
        "open",
        "high",
        "low",
        "close",
    )

    def __init__(
        self,
        source: SourceIdentity,
        instruments: Mapping[str, InstrumentIdentity],
        *,
        encoding: str = "utf-8",
        max_errors: int = 100,
    ):
        self.source = source
        self.instruments = dict(instruments)
        self.encoding = encoding
        self.max_errors = max_errors

    def read(self, path: Path, *, strict: bool = True) -> AdapterResult:
        path = Path(path)
        if not path.is_file():
            issue = ValidationIssue(ValidationReason.SOURCE_UNAVAILABLE, "source file is missing")
            return AdapterResult((), AdapterDiagnostics(0, 0, 0, (), (issue,), ValidationStatus.INVALID))
        observations: list[CanonicalMarketObservation] = []
        warnings: list[ValidationIssue] = []
        errors: list[ValidationIssue] = []
        total = 0
        try:
            with path.open("r", encoding=self.encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                columns = tuple(reader.fieldnames or ())
                missing = tuple(column for column in self.required_columns if column not in columns)
                if missing:
                    issue = ValidationIssue(ValidationReason.MISSING_REQUIRED_FIELD, f"missing columns: {','.join(missing)}")
                    return AdapterResult((), AdapterDiagnostics(0, 0, 0, (), (issue,), ValidationStatus.INVALID))
                for index, row in enumerate(reader, start=1):
                    total += 1
                    try:
                        observations.append(self._row_to_observation(row, path, index))
                    except Exception as exc:
                        errors.append(ValidationIssue(_reason_from_exception(exc), str(exc), index))
                        if len(errors) >= self.max_errors:
                            break
        except UnicodeDecodeError as exc:
            errors.append(ValidationIssue(ValidationReason.ADAPTER_ERROR, f"encoding failure: {exc}"))
        status = _status(warnings, errors, strict)
        return AdapterResult(
            tuple(observations),
            AdapterDiagnostics(total, len(observations), total - len(observations), tuple(warnings), tuple(errors), status),
        )

    def _row_to_observation(self, row: Mapping[str, str], path: Path, index: int) -> CanonicalMarketObservation:
        alias = row["instrument"]
        instrument = self.instruments.get(alias)
        if instrument is None:
            raise ValueError(ValidationReason.UNKNOWN_INSTRUMENT.value)
        raw = canonical_json(dict(row))
        return create_canonical_bar(
            instrument=instrument,
            source=self.source,
            timeframe=row["timeframe"],
            period_start=_parse_time(row["period_start"]),
            period_end=_parse_time(row["period_end"]),
            available_at=_parse_time(row["available_at"]),
            received_at=_parse_time(row["received_at"]),
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row.get("volume") or None,
            volume_kind=row.get("volume_kind") or "UNAVAILABLE",
            sequence=int(row["sequence"]) if row.get("sequence") else None,
            source_metadata={"columns": tuple(sorted(row))},
            provenance=ObservationProvenance(
                source_record_locator=f"row:{index}",
                source_path=PurePosixPath(path.as_posix()).as_posix(),
                raw_record_fingerprint=_sha256_text(raw),
                transformations=("csv_field_mapping", "utc_timestamp_validation", "decimal_numeric_parsing"),
            ),
        )


def build_canonical_dataset(
    observations: Iterable[CanonicalMarketObservation],
    *,
    strict: bool = True,
) -> CanonicalMarketDataset:
    accepted: list[CanonicalMarketObservation] = []
    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []
    seen: dict[str, CanonicalMarketObservation] = {}
    source_order: list[CanonicalMarketObservation] = []
    for index, observation in enumerate(observations):
        source_order.append(observation)
        validation = validate_canonical_observation(observation)
        if not validation.valid:
            errors.extend(
                ValidationIssue(issue.reason, issue.message, index, issue.observation_id)
                for issue in validation.issues
            )
            continue
        existing = seen.get(observation.observation_id)
        if existing is not None:
            if existing.observation_fingerprint == observation.observation_fingerprint:
                warnings.append(ValidationIssue(ValidationReason.DUPLICATE, "exact duplicate observation", index, observation.observation_id))
                continue
            reason = ValidationReason.REVISED_OBSERVATION if observation.received_at > existing.received_at else ValidationReason.IDENTITY_COLLISION
            errors.append(ValidationIssue(reason, "same observation identity with different content", index, observation.observation_id))
            continue
        seen[observation.observation_id] = observation
        accepted.append(observation)
    for previous, current in zip(source_order, source_order[1:]):
        if _order_key(current) < _order_key(previous):
            errors.append(ValidationIssue(ValidationReason.OUT_OF_ORDER, "source observations are out of canonical order", observation_id=current.observation_id))
        if previous.sequence is not None and current.sequence is not None and previous.source.source_id == current.source.source_id:
            if current.sequence < previous.sequence:
                errors.append(ValidationIssue(ValidationReason.SEQUENCE_REGRESSION, "source sequence regressed", observation_id=current.observation_id))
            elif current.sequence > previous.sequence + 1:
                warnings.append(ValidationIssue(ValidationReason.SEQUENCE_GAP, "source sequence gap", observation_id=current.observation_id))
    ordered = tuple(sorted(accepted, key=_order_key))
    status = _status(warnings, errors, strict)
    fingerprint_payload = {
        "schema": DATASET_MANIFEST_SCHEMA_VERSION,
        "observation_schema": MARKET_OBSERVATION_SCHEMA_VERSION,
        "observations": [item.observation_fingerprint for item in ordered],
    }
    dataset_fingerprint = _sha256_text(canonical_json(fingerprint_payload))
    dataset_id = deterministic_id("canonical_dataset", dataset_fingerprint)
    temporal = tuple(item.event_time for item in ordered)
    manifest = DatasetManifest(
        DATASET_MANIFEST_SCHEMA_VERSION,
        dataset_id,
        dataset_fingerprint,
        MARKET_OBSERVATION_SCHEMA_VERSION,
        tuple(sorted({item.source.source_id for item in ordered})),
        tuple(sorted({f"{item.source.adapter_type}:{item.source.adapter_version}" for item in ordered})),
        tuple(sorted({item.instrument.canonical_id for item in ordered})),
        tuple(sorted({item.timeframe for item in ordered})),
        min(temporal) if temporal else None,
        max(temporal) if temporal else None,
        len(ordered),
        {"status": status.value, "warnings": len(warnings), "errors": len(errors)},
    )
    diagnostics = AdapterDiagnostics(len(source_order), len(ordered), len(source_order) - len(ordered), tuple(warnings), tuple(errors), status)
    return CanonicalMarketDataset(ordered if status is not ValidationStatus.INVALID or not strict else (), manifest, diagnostics)


def verify_dataset_manifest(dataset: CanonicalMarketDataset) -> ValidationResult:
    return dataset.verify()


def observation_from_normalized_bar(
    bar: NormalizedBar,
    *,
    source: SourceIdentity,
    instrument: InstrumentIdentity | None = None,
    available_at: datetime | None = None,
    received_at: datetime | None = None,
    sequence: int | None = None,
) -> CanonicalMarketObservation:
    if bar.close_time is None or bar.bar_state is not BarState.CLOSED_BAR:
        raise ValueError("Prompt 39 canonical observations require finalized closed bars")
    instrument = instrument or InstrumentIdentity(bar.instrument_id, bar.instrument_id)
    return create_canonical_bar(
        instrument=instrument,
        source=source,
        timeframe=bar.timeframe,
        period_start=bar.open_time,
        period_end=bar.close_time,
        available_at=available_at or bar.close_time,
        received_at=received_at or available_at or bar.close_time,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.tick_volume if bar.tick_volume is not None else bar.real_volume,
        volume_kind=bar.volume_kind.name,
        sequence=sequence,
        provenance=ObservationProvenance(
            source_record_locator=bar.source_reference or bar.bar_id,
            transformations=("normalized_bar_adapter",),
        ),
    )


def observation_to_normalized_bar(observation: CanonicalMarketObservation) -> NormalizedBar:
    if observation.observation_type is not ObservationType.BAR:
        raise ValueError("only BAR observations can be adapted to NormalizedBar")
    return NormalizedBar(
        observation.instrument.canonical_id,
        observation.timeframe,
        observation.period_start,
        observation.event_time,
        float(observation.bar.open),
        float(observation.bar.high),
        float(observation.bar.low),
        float(observation.bar.close),
        tick_volume=float(observation.bar.volume) if observation.bar.volume is not None else None,
        bar_state=BarState.CLOSED_BAR,
        validity=DataValidity.VALID,
        source_reference=observation.provenance.source_record_locator,
        bar_id=observation.observation_id,
        volume_kind=VolumeKind[observation.bar.volume_kind] if observation.bar.volume_kind in VolumeKind.__members__ else VolumeKind.UNAVAILABLE,
    )


def _observation_payload_without_fingerprint(observation: CanonicalMarketObservation) -> dict[str, Any]:
    return {
        "schema_version": observation.schema_version,
        "observation_id": observation.observation_id,
        "instrument": observation.instrument,
        "source": observation.source,
        "observation_type": observation.observation_type,
        "timeframe": observation.timeframe,
        "temporal_semantics": observation.temporal_semantics,
        "period_start": observation.period_start,
        "event_time": observation.event_time,
        "available_at": observation.available_at,
        "received_at": observation.received_at,
        "sequence": observation.sequence,
        "bar": observation.bar,
        "source_metadata": dict(observation.source_metadata),
        "quality_metadata": dict(observation.quality_metadata),
        "provenance": observation.provenance,
    }


def _validate_ohlc(values: CanonicalBarValues) -> None:
    if values.high < max(values.open, values.close) or values.low > min(values.open, values.close) or values.high < values.low:
        raise ValueError(ValidationReason.INVALID_OHLC.value)
    if values.volume is not None and values.volume < 0:
        raise ValueError(ValidationReason.INVALID_VOLUME.value)


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{ValidationReason.INVALID_NUMERIC_VALUE.value}:{field_name}") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{ValidationReason.INVALID_NUMERIC_VALUE.value}:{field_name}")
    return result.normalize()


def _optional_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{ValidationReason.INVALID_NUMERIC_VALUE.value}:{field_name}") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{ValidationReason.INVALID_VOLUME.value}:{field_name}")
    return result.normalize()


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(ValidationReason.INVALID_TIMESTAMP.value) from exc
    return _aware_utc(parsed, "timestamp")


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{ValidationReason.NAIVE_TIMESTAMP.value}:{field_name}")
    return value.astimezone(timezone.utc)


def _datetime_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return _datetime_text(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if hasattr(value, "__dataclass_fields__"):
        return {field: _jsonable(getattr(value, field)) for field in value.__dataclass_fields__}
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _order_key(observation: CanonicalMarketObservation) -> tuple[Any, ...]:
    return (
        observation.instrument.canonical_id,
        observation.timeframe,
        observation.event_time,
        -1 if observation.sequence is None else observation.sequence,
        observation.observation_id,
    )


def _status(warnings: list[ValidationIssue], errors: list[ValidationIssue], strict: bool) -> ValidationStatus:
    if errors and strict:
        return ValidationStatus.INVALID
    if errors or warnings:
        return ValidationStatus.VALID_WITH_WARNINGS
    return ValidationStatus.VALID


def _reason_from_exception(exc: Exception) -> ValidationReason:
    text = str(exc)
    for reason in ValidationReason:
        if reason.value in text:
            return reason
    return ValidationReason.RECORD_ERROR
