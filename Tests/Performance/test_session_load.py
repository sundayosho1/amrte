from datetime import datetime,timedelta,timezone
from time import perf_counter

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.session import SessionConfiguration,SessionEngine,WeekdayFallbackCalendar
from Tests.Unit.test_session import definitions,market


def test_5000_timestamp_session_resolution_is_bounded():
    start=datetime(2026,3,16,12,tzinfo=timezone.utc)
    engine=SessionEngine(FixedClock(start),InMemoryAuditSink(),SessionConfiguration(sessions=definitions(),maximum_clock_jump_minutes=100000),WeekdayFallbackCalendar())
    began=perf_counter()
    for index in range(5000):
        instant=start+timedelta(minutes=index)
        engine.analyze(market(instant,f"MD{index}"))
    assert perf_counter()-began<10
