from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

from .types import Severity, StrategyId

T = TypeVar("T")


@dataclass(frozen=True)
class AMRTEError:
    timestamp: datetime
    module: str
    function: str
    severity: Severity
    code: str
    message: str
    instrument: str | None = None
    strategy: StrategyId = StrategyId.SYSTEM
    correlation_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = False
    suggested_action: str | None = None
    underlying_error: str | None = None


@dataclass(frozen=True)
class Result(Generic[T]):
    success: bool
    value: T | None = None
    error: AMRTEError | None = None
    warnings: tuple[str, ...] = ()

    @classmethod
    def ok(cls, value: T | None = None, warnings: tuple[str, ...] = ()) -> "Result[T]":
        return cls(True, value=value, warnings=warnings)

    @classmethod
    def fail(cls, error: AMRTEError) -> "Result[T]":
        return cls(False, error=error)

