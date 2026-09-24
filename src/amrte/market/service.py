from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Iterable, Mapping

from amrte.core.identity import deterministic_id
from amrte.core.interfaces import IAuditSink, IClock
from .cache import BoundedMarketDataCache, CacheKey
from .models import (
    AdmissionStatus, AnomalyClassification, BarState, DataHealth, DataProvenance,
    DataValidity, DatasetAdmission, DatasetValidationReport, DuplicateClassification,
    GapClassification, MarketDataSnapshot, NewBarState, NormalizedBar, SpreadHealth,
    SpreadOrigin, SpreadState, SynchronizationStatus, ValidationFinding, VolumeKind,
    WarmupStatus,
)
from .provider import DeterministicMarketDataProvider, dataset_fingerprint

TIMEFRAME_SECONDS = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}


def deterministic_bar_id(dataset_id: str, bar: NormalizedBar) -> str:
    return deterministic_id("bar", dataset_id, bar.instrument_id, bar.timeframe,
                            bar.open_time.isoformat())


class MarketDataService:
    def __init__(self, provider: DeterministicMarketDataProvider, clock: IClock,
                 audit: IAuditSink, *, strict: bool = True, minimum_history: int = 1,
                 stale_multiplier: float = 2.0, anomaly_ratio: float = 0.25,
                 maximum_cache_entries: int = 128):
        self.provider = provider; self.clock = clock; self.audit = audit; self.strict = strict
        self.minimum_history = minimum_history; self.stale_multiplier = stale_multiplier
        self.anomaly_ratio = anomaly_ratio
        self.cache = BoundedMarketDataCache[tuple[NormalizedBar, ...]](maximum_cache_entries)
        self._admission: DatasetAdmission | None = None
        self._new_bar: dict[tuple[str, str], NewBarState] = {}

    @property
    def admission(self) -> DatasetAdmission | None: return self._admission

    def normalize(self, bars: Iterable[NormalizedBar]) -> tuple[NormalizedBar, ...]:
        result = []
        for bar in bars:
            if bar.open_time.tzinfo is None or (bar.close_time and bar.close_time.tzinfo is None):
                result.append(replace(bar, validity=DataValidity.INVALID)); continue
            normalized = replace(bar, open_time=bar.open_time.astimezone(timezone.utc),
                                 close_time=bar.close_time.astimezone(timezone.utc) if bar.close_time else None,
                                 bar_id=deterministic_bar_id(self.provider.dataset_id, bar))
            result.append(normalized)
        return tuple(result)

    def validate_and_admit(self, bars: Iterable[NormalizedBar] | None = None) -> DatasetAdmission:
        raw = tuple(bars if bars is not None else self.provider._bars)
        normalized = self.normalize(raw)
        fingerprint = dataset_fingerprint(normalized)
        errors: list[ValidationFinding] = []; warnings: list[ValidationFinding] = []
        accepted: list[NormalizedBar] = []; seen: dict[tuple[str, str, datetime], NormalizedBar] = {}
        duplicates = conflicts = invalid_ohlc = timestamps = gaps = anomalies = 0
        by_series: dict[tuple[str, str], list[NormalizedBar]] = {}
        for index, bar in enumerate(normalized):
            key = (bar.instrument_id, bar.timeframe, bar.open_time)
            if bar.open_time.tzinfo is None or (bar.close_time and bar.close_time <= bar.open_time):
                timestamps += 1; errors.append(ValidationFinding("TIMESTAMP_INVALID", "timestamp is missing timezone or has invalid bounds", bar.instrument_id, bar.timeframe, index)); continue
            values = (bar.open, bar.high, bar.low, bar.close)
            if not all(math.isfinite(item) and item > 0 for item in values) or not (bar.high >= max(bar.open, bar.close) and bar.low <= min(bar.open, bar.close) and bar.high >= bar.low):
                invalid_ohlc += 1; errors.append(ValidationFinding("INVALID_OHLC", "bar values violate finite positive OHLC invariants", bar.instrument_id, bar.timeframe, index)); continue
            if bar.tick_volume is not None and (not math.isfinite(bar.tick_volume) or bar.tick_volume < 0):
                errors.append(ValidationFinding("IMPOSSIBLE_VOLUME", "volume is non-finite or negative", bar.instrument_id, bar.timeframe, index)); continue
            if key in seen:
                if seen[key] == bar:
                    duplicates += 1; warnings.append(ValidationFinding("IDENTICAL_DUPLICATE", "identical record deduplicated", bar.instrument_id, bar.timeframe, index)); continue
                conflicts += 1; errors.append(ValidationFinding("CONFLICTING_DUPLICATE", "conflicting record at the same timestamp", bar.instrument_id, bar.timeframe, index)); continue
            seen[key] = bar
            valid = replace(bar, validity=DataValidity.VALID)
            accepted.append(valid); by_series.setdefault((bar.instrument_id, bar.timeframe), []).append(valid)
        for (instrument, timeframe), series in by_series.items():
            original = [bar.open_time for bar in normalized if bar.instrument_id == instrument and bar.timeframe == timeframe]
            if original != sorted(original):
                errors.append(ValidationFinding("CHRONOLOGY_INVALID", "source records are out of order", instrument, timeframe)); timestamps += 1
            ordered = sorted(series, key=lambda item: item.open_time)
            cadence = TIMEFRAME_SECONDS.get(timeframe)
            for previous, current in zip(ordered, ordered[1:]):
                if cadence and (current.open_time - previous.open_time).total_seconds() > cadence:
                    gaps += 1; warnings.append(ValidationFinding("UNKNOWN_GAP", "gap requires later session classification", instrument, timeframe))
                movement = abs(current.close - previous.close) / previous.close
                if movement > self.anomaly_ratio:
                    anomalies += 1; warnings.append(ValidationFinding("ANOMALY_DETECTED", "large discontinuity preserved for inspection", instrument, timeframe))
        fatal = bool(errors) and self.strict
        health = DataHealth.INVALID if fatal else (DataHealth.DEGRADED if errors or warnings else DataHealth.HEALTHY)
        admission_status = AdmissionStatus.REJECTED if fatal else (AdmissionStatus.ADMITTED_WITH_WARNINGS if errors or warnings else AdmissionStatus.ADMITTED)
        dates = tuple(bar.open_time for bar in accepted)
        report = DatasetValidationReport(self.provider.dataset_id, fingerprint, len(raw),
            (min(dates) if dates else None, max(dates) if dates else None),
            tuple(sorted({bar.instrument_id for bar in accepted})),
            tuple(sorted({bar.timeframe for bar in accepted})), 0, duplicates, conflicts,
            invalid_ohlc, timestamps, gaps, anomalies, health, admission_status,
            tuple(warnings), tuple(errors))
        self._admission = DatasetAdmission(admission_status, report, tuple(sorted(accepted, key=lambda item: (item.instrument_id, item.timeframe, item.open_time))))
        self.audit.record("dataset_validated" if admission_status is not AdmissionStatus.REJECTED else "dataset_rejected",
                          {"dataset_id": self.provider.dataset_id, "fingerprint": fingerprint,
                           "admission": admission_status.name, "errors": len(errors), "warnings": len(warnings)})
        return self._admission

    def bars(self, instrument_id: str, timeframe: str, as_of: datetime, *,
             closed_only: bool = True, required_bars: int | None = None) -> tuple[NormalizedBar, ...]:
        if as_of.tzinfo is None: raise ValueError("as_of timestamp must be timezone-aware")
        if self._admission is None: self.validate_and_admit()
        if self._admission.status is AdmissionStatus.REJECTED: return ()
        if self.provider.get_instrument_metadata(instrument_id) is None: return ()
        metadata = self.provider.get_instrument_metadata(instrument_id)
        if timeframe not in metadata.supported_timeframes: return ()
        key = CacheKey(self._admission.report.dataset_fingerprint, instrument_id, timeframe,
                       as_of.astimezone(timezone.utc).isoformat(), "CLOSED" if closed_only else "ANY")
        cached = self.cache.get(key)
        if cached is not None: return cached
        selected = tuple(bar for bar in self._admission.normalized_bars
                         if bar.instrument_id == instrument_id and bar.timeframe == timeframe
                         and bar.open_time <= as_of
                         and (not closed_only or (bar.bar_state is BarState.CLOSED_BAR and
                              bar.close_time is not None and bar.close_time <= as_of)))
        required = required_bars if required_bars is not None else self.minimum_history
        if len(selected) < required:
            self.audit.record("insufficient_history", {"instrument_id": instrument_id, "timeframe": timeframe, "required": required, "available": len(selected)})
            return ()
        self.cache.put(key, selected)
        return selected

    def warmup_status(self, available: int, required: int) -> WarmupStatus:
        return WarmupStatus.READY if available >= required else WarmupStatus.INSUFFICIENT_HISTORY

    def gap_classification(self, previous: NormalizedBar, current: NormalizedBar,
                           known_closure: bool = False) -> GapClassification:
        cadence = TIMEFRAME_SECONDS.get(previous.timeframe)
        if not cadence: return GapClassification.UNKNOWN_GAP
        delta = (current.open_time - previous.open_time).total_seconds()
        if delta <= cadence: return GapClassification.DATASET_BOUNDARY
        return GapClassification.EXPECTED_CLOSURE if known_closure else GapClassification.UNKNOWN_GAP

    def anomaly(self, previous: NormalizedBar, current: NormalizedBar,
                confirmed_extreme: bool = False) -> AnomalyClassification:
        if current.validity is DataValidity.INVALID: return AnomalyClassification.INVALID
        movement = abs(current.close - previous.close) / previous.close
        if movement <= self.anomaly_ratio: return AnomalyClassification.UNKNOWN
        return AnomalyClassification.VALID_EXTREME_EVENT if confirmed_extreme else AnomalyClassification.SUSPECT

    def spread_state(self, bars: tuple[NormalizedBar, ...]) -> SpreadState:
        observed = [bar.spread for bar in bars if bar.spread is not None]
        if not observed: return SpreadState(None, None, None, None, None, SpreadHealth.UNAVAILABLE, SpreadOrigin.UNAVAILABLE)
        current = observed[-1]; typical = median(observed); deviation = current - typical
        ratio = current / typical if typical > 0 else math.inf
        health = SpreadHealth.NORMAL if ratio <= 1.5 else (SpreadHealth.ELEVATED if ratio <= 3 else SpreadHealth.EXTREME)
        return SpreadState(current, current, ratio, typical, deviation, health, SpreadOrigin.OBSERVED)

    def data_health(self, series: Iterable[tuple[NormalizedBar, ...]], as_of: datetime) -> tuple[DataHealth, float]:
        items = tuple(series)
        if self._admission is None or self._admission.status is AdmissionStatus.REJECTED: return DataHealth.INVALID, 0.0
        if not items or any(not item for item in items): return DataHealth.INCOMPLETE, 0.0
        latest = max((bar.close_time or bar.open_time) for item in items for bar in item)
        if latest > as_of: return DataHealth.INVALID, 0.0
        maximum_cadence = max(TIMEFRAME_SECONDS.get(item[-1].timeframe, 0) for item in items)
        if maximum_cadence and (as_of - latest).total_seconds() > maximum_cadence * self.stale_multiplier:
            return DataHealth.STALE, 50.0
        return DataHealth.HEALTHY, 100.0

    def synchronization_status(self, series: Iterable[tuple[NormalizedBar, ...]],
                               as_of: datetime) -> SynchronizationStatus:
        items = tuple(series)
        if not items or any(not item for item in items):
            return SynchronizationStatus.INSUFFICIENT_DATA
        available = []
        for item in items:
            latest = item[-1].close_time or item[-1].open_time
            if latest > as_of:
                return SynchronizationStatus.UNSYNCHRONIZED
            cadence = TIMEFRAME_SECONDS.get(item[-1].timeframe)
            available.append(cadence is not None and
                             (as_of - latest).total_seconds() <= cadence * self.stale_multiplier)
        if all(available): return SynchronizationStatus.SYNCHRONIZED
        if any(available): return SynchronizationStatus.PARTIALLY_SYNCHRONIZED
        return SynchronizationStatus.UNSYNCHRONIZED

    def create_snapshot(self, instrument_id: str, roles: Mapping[str, str], as_of: datetime,
                        *, experiment_id: str, configuration_snapshot_id: str,
                        recovery_epoch: int = 0, required_bars: int | None = None) -> MarketDataSnapshot | None:
        if self._admission is None: self.validate_and_admit()
        if self._admission.status is AdmissionStatus.REJECTED: return None
        context = self.bars(instrument_id, roles["context"], as_of, required_bars=required_bars)
        strategy = self.bars(instrument_id, roles["strategy"], as_of, required_bars=required_bars)
        execution = self.bars(instrument_id, roles["execution"], as_of, required_bars=required_bars)
        health, quality = self.data_health((context, strategy, execution), as_of)
        synchronization = self.synchronization_status((context, strategy, execution), as_of)
        if health is not DataHealth.HEALTHY or synchronization is not SynchronizationStatus.SYNCHRONIZED:
            self.audit.record("snapshot_rejected", {"instrument_id": instrument_id,
                              "health": health.name, "synchronization": synchronization.name}); return None
        fingerprint = self._admission.report.dataset_fingerprint
        provenance = {}
        for role, selected in (("context", context), ("strategy", strategy), ("execution", execution)):
            provenance[role] = DataProvenance(self.provider.provider_id, self.provider.dataset_id,
                self.provider.dataset_version, fingerprint, "OFFLINE_DETERMINISTIC", self.clock.now(),
                "UTC", "UTC", instrument_id, roles[role], None, as_of,
                selected[0].open_time, selected[-1].close_time or selected[-1].open_time)
        identity = deterministic_id("snapshot", experiment_id, fingerprint, instrument_id,
                                    as_of.isoformat(), configuration_snapshot_id, recovery_epoch)
        snapshot = MarketDataSnapshot(identity, self.clock.now(), as_of, experiment_id,
            self.provider.dataset_id, fingerprint, instrument_id, self.spread_state(execution),
            context, strategy, execution, synchronization, health,
            quality, provenance, configuration_snapshot_id, recovery_epoch)
        self.audit.record("snapshot_created", {"snapshot_id": identity, "dataset_id": self.provider.dataset_id})
        return snapshot

    def detect_new_bar(self, bar: NormalizedBar) -> NewBarState:
        key = (bar.instrument_id, bar.timeframe); previous = self._new_bar.get(key)
        is_closed = bar.bar_state is BarState.CLOSED_BAR
        is_new = is_closed and (previous is None or previous.last_closed_bar_id != bar.bar_id)
        state = NewBarState(bar.bar_id, bar.bar_id if is_closed else (previous.last_closed_bar_id if previous else None),
                            bar.bar_id if not is_closed else None, is_new)
        self._new_bar[key] = state; return state

    def recovery_state(self) -> Mapping[str, object]:
        return {"dataset_id": self.provider.dataset_id,
                "dataset_fingerprint": self._admission.report.dataset_fingerprint if self._admission else self.provider.dataset_fingerprint(),
                "last_committed_bar_ids": {f"{k[0]}|{k[1]}": v.last_closed_bar_id for k, v in self._new_bar.items()}}

    def readiness(self) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if self.provider.health().name != "HEALTHY": reasons.append("provider:UNHEALTHY")
        if self._admission is None: reasons.append("dataset:NOT_VALIDATED")
        elif self._admission.status is AdmissionStatus.REJECTED: reasons.append("dataset:REJECTED")
        return not reasons, tuple(reasons)
