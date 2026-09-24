from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Mapping

from .errors import AMRTEError, Result
from .types import EffectiveConfigurationSnapshot, HealthStatus


class IClock(ABC):
    @abstractmethod
    def now(self) -> datetime: ...


class IConfigurationProvider(ABC):
    @abstractmethod
    def load(self) -> Result[EffectiveConfigurationSnapshot]: ...


class IStateRepository(ABC):
    @abstractmethod
    def load(self) -> Result[Mapping[str, Any]]: ...
    @abstractmethod
    def save(self, state: Mapping[str, Any]) -> Result[None]: ...


class ILogger(ABC):
    @abstractmethod
    def record(self, event: str, context: Mapping[str, Any]) -> None: ...
    @abstractmethod
    def flush(self) -> None: ...


class IAuditSink(ILogger):
    pass


class IMarketDataProvider(ABC):
    """Contract restricted to historical/synthetic/fictional research data."""
    @abstractmethod
    def health(self) -> HealthStatus: ...
    @abstractmethod
    def capabilities(self): ...
    @abstractmethod
    def get_instrument_metadata(self, instrument_id: str): ...
    @abstractmethod
    def get_bars(self, instrument_id: str, timeframe: str, *, as_of: datetime | None = None): ...
    @abstractmethod
    def latest_available_record(self, instrument_id: str, timeframe: str,
                                as_of: datetime | None = None): ...
    @abstractmethod
    def data_range(self, instrument_id: str, timeframe: str): ...
    @abstractmethod
    def dataset_identity(self) -> Mapping[str, str]: ...
    @abstractmethod
    def dataset_fingerprint(self) -> str: ...


class IExecutionProvider(ABC):
    """Capability contract; this build supplies only a prohibited-operation stub."""
    @abstractmethod
    def submit(self, request: Mapping[str, Any]) -> Result[None]: ...


class IPositionRepository(ABC):
    @abstractmethod
    def list_all(self) -> tuple[Mapping[str, Any], ...]: ...


class IEventProvider(ABC):
    @abstractmethod
    def health(self) -> HealthStatus: ...


class IRandomSource(ABC):
    @property
    @abstractmethod
    def seed(self) -> int: ...
    @abstractmethod
    def random(self) -> float: ...
