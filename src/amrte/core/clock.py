from datetime import datetime, timezone

from .interfaces import IClock


class SystemClock(IClock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock(IClock):
    def __init__(self, instant: datetime):
        if instant.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware instant")
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


class AdvancingClock(IClock):
    def __init__(self, instant: datetime):
        if instant.tzinfo is None:
            raise ValueError("AdvancingClock requires a timezone-aware instant")
        self._instant = instant

    def now(self) -> datetime:
        return self._instant

    def set(self, instant: datetime) -> None:
        if instant.tzinfo is None or instant < self._instant:
            raise ValueError("simulation time must be aware and monotonic")
        self._instant = instant

