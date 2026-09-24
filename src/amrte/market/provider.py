from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Iterable, Mapping

from amrte.core.interfaces import IMarketDataProvider
from amrte.core.types import HealthStatus
from .models import InstrumentMetadata, NormalizedBar, ProviderCapability


def _canonical_bar(bar: NormalizedBar) -> dict[str, object]:
    def number(value: float | None) -> float | str | None:
        if value is None or math.isfinite(value): return value
        if math.isnan(value): return "NON_FINITE_NAN"
        return "NON_FINITE_POSITIVE_INFINITY" if value > 0 else "NON_FINITE_NEGATIVE_INFINITY"
    return {
        "instrument_id": bar.instrument_id, "timeframe": bar.timeframe,
        "open_time": bar.open_time.isoformat(),
        "close_time": bar.close_time.isoformat() if bar.close_time else None,
        "open": number(bar.open), "high": number(bar.high), "low": number(bar.low),
        "close": number(bar.close), "tick_volume": number(bar.tick_volume),
        "real_volume": number(bar.real_volume), "spread": number(bar.spread),
        "bar_state": bar.bar_state.name,
        "volume_kind": bar.volume_kind.name,
    }


def dataset_fingerprint(bars: Iterable[NormalizedBar]) -> str:
    ordered = sorted((_canonical_bar(bar) for bar in bars),
                     key=lambda item: (str(item["instrument_id"]), str(item["timeframe"]),
                                       str(item["open_time"]), str(item["close_time"])))
    payload = json.dumps(ordered, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DeterministicMarketDataProvider(IMarketDataProvider):
    """In-memory offline provider for historical, synthetic, or fictional fixtures."""

    def __init__(self, provider_id: str, dataset_id: str, dataset_version: str,
                 bars: Iterable[NormalizedBar], metadata: Iterable[InstrumentMetadata],
                 *, available: bool = True):
        self.provider_id = provider_id
        self.dataset_id = dataset_id
        self.dataset_version = dataset_version
        self._bars = tuple(bars)
        self._metadata = {item.canonical_id: item for item in metadata}
        self.available = available

    def health(self) -> HealthStatus:
        return HealthStatus.HEALTHY if self.available else HealthStatus.UNHEALTHY

    def capabilities(self) -> frozenset[ProviderCapability]:
        result = {ProviderCapability.BAR_DATA, ProviderCapability.INSTRUMENT_METADATA}
        for item in self._metadata.values(): result.update(item.capabilities)
        return frozenset(result)

    def get_instrument_metadata(self, instrument_id: str) -> InstrumentMetadata | None:
        return self._metadata.get(instrument_id) if self.available else None

    def get_bars(self, instrument_id: str, timeframe: str, *,
                 as_of: datetime | None = None) -> tuple[NormalizedBar, ...]:
        if not self.available:
            raise OSError("offline research provider unavailable")
        selected = (bar for bar in self._bars
                    if bar.instrument_id == instrument_id and bar.timeframe == timeframe)
        if as_of is not None:
            # A bar is available only when its information was available. Closed bars
            # require close_time; a forming bar may be observed at/after open_time.
            selected = (bar for bar in selected if
                        (bar.close_time <= as_of if bar.close_time is not None and
                         bar.bar_state.name == "CLOSED_BAR" else bar.open_time <= as_of))
        return tuple(sorted(selected, key=lambda bar: bar.open_time))

    def latest_available_record(self, instrument_id: str, timeframe: str,
                                as_of: datetime | None = None) -> NormalizedBar | None:
        bars = self.get_bars(instrument_id, timeframe, as_of=as_of)
        return bars[-1] if bars else None

    def data_range(self, instrument_id: str, timeframe: str) -> tuple[datetime, datetime] | None:
        bars = self.get_bars(instrument_id, timeframe)
        return (bars[0].open_time, bars[-1].close_time or bars[-1].open_time) if bars else None

    def dataset_identity(self) -> Mapping[str, str]:
        return {"provider_id": self.provider_id, "dataset_id": self.dataset_id,
                "dataset_version": self.dataset_version}

    def dataset_fingerprint(self) -> str:
        return dataset_fingerprint(self._bars)
