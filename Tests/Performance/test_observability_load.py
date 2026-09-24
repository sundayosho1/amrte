from datetime import datetime, timezone
from time import perf_counter

from amrte.core.clock import FixedClock
from amrte.core.observability import ObservabilityService
from amrte.core.observability_types import ObservabilityHealth, Verbosity
from amrte.core.types import Severity


class CountingSink:
    authoritative = False
    health = ObservabilityHealth.HEALTHY

    def __init__(self): self.count = 0
    def write(self, event): self.count += 1
    def flush(self): return None


def test_bounded_synthetic_event_load():
    sink = CountingSink()
    service = ObservabilityService(
        FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)), (sink,),
        verbosity=Verbosity.DEBUG, maximum_history=200,
    )
    total = 5000
    started = perf_counter()
    for index in range(total):
        service.emit(f"TEST_LOAD_{index}", "bounded synthetic diagnostic",
                     severity=Severity.DEBUG)
    elapsed = perf_counter() - started
    assert sink.count == total
    assert len(service.events) <= 200
    assert service.dropped_diagnostics >= total - 200
    assert elapsed < 5.0
