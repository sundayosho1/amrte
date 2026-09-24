from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, Hashable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class CacheKey:
    dataset_fingerprint: str
    instrument_id: str
    timeframe: str
    cursor: str
    bar_state: str
    normalization_version: str = "1"


class BoundedMarketDataCache(Generic[T]):
    def __init__(self, maximum_entries: int = 128):
        if maximum_entries < 1: raise ValueError("maximum_entries must be positive")
        self.maximum_entries = maximum_entries
        self._items: OrderedDict[Hashable, T] = OrderedDict()

    def get(self, key: Hashable) -> T | None:
        value = self._items.get(key)
        if value is not None: self._items.move_to_end(key)
        return value

    def put(self, key: Hashable, value: T) -> None:
        self._items[key] = value; self._items.move_to_end(key)
        while len(self._items) > self.maximum_entries: self._items.popitem(last=False)

    def invalidate_fingerprint(self, fingerprint: str) -> int:
        keys = [key for key in self._items if getattr(key, "dataset_fingerprint", None) == fingerprint]
        for key in keys: del self._items[key]
        return len(keys)

    def clear(self) -> None: self._items.clear()
    def __len__(self) -> int: return len(self._items)

