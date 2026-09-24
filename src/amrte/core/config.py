from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .constants import (
    CONFIG_SCHEMA_VERSION, DEFAULT_CONTEXT_TIMEFRAME,
    DEFAULT_EXECUTION_TIMEFRAME, DEFAULT_STRATEGY_TIMEFRAME,
)
from .errors import AMRTEError, Result
from .interfaces import IConfigurationProvider, IClock
from .types import EffectiveConfigurationSnapshot, Severity


LAYERS = ("global", "profile", "strategy", "instrument", "runtime")
HARD_SAFETY = {
    "broker.live_execution": False,
    "broker.demo_execution": False,
    "broker.authentication": False,
    "safety.unlimited_exposure": False,
    "safety.martingale": False,
}


class LayeredConfigurationProvider(IConfigurationProvider):
    def __init__(self, clock: IClock, layers: Mapping[str, Mapping[str, Any]] | None = None):
        self._clock = clock
        self._layers = dict(layers or {})

    def load(self) -> Result[EffectiveConfigurationSnapshot]:
        values: dict[str, Any] = {
            "timeframes.context": DEFAULT_CONTEXT_TIMEFRAME,
            "timeframes.strategy": DEFAULT_STRATEGY_TIMEFRAME,
            "timeframes.execution": DEFAULT_EXECUTION_TIMEFRAME,
        }
        provenance = {key: "global-default" for key in values}
        for layer in LAYERS:
            source = self._layers.get(layer, {})
            if not isinstance(source, Mapping):
                return Result.fail(self._error("CONFIG_LAYER_INVALID", f"{layer} must be a mapping"))
            for key, value in source.items():
                if key in HARD_SAFETY and value != HARD_SAFETY[key]:
                    return Result.fail(self._error("HARD_SAFETY_OVERRIDE", f"cannot override {key}"))
                values[key] = value
                provenance[key] = layer
        values.update(HARD_SAFETY)
        provenance.update({key: "hard-safety" for key in HARD_SAFETY})
        return Result.ok(EffectiveConfigurationSnapshot(values, provenance, CONFIG_SCHEMA_VERSION))

    def _error(self, code: str, message: str) -> AMRTEError:
        return AMRTEError(self._clock.now(), "Core.Config", "load", Severity.CRITICAL,
                          code, message, suggested_action="Correct configuration and restart")

