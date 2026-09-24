from datetime import datetime,time,timezone

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.models import GapClassification
from amrte.market.session import *
from Tests.Unit.test_market_data import bar,service as market_service
from Tests.Unit.test_session import definitions,market


def test_expected_closure_context_integrates_without_replacing_staleness_owner():
    instant=datetime(2026,3,21,12,tzinfo=timezone.utc)
    session=SessionEngine(FixedClock(instant),InMemoryAuditSink(),SessionConfiguration(sessions=definitions()),WeekdayFallbackCalendar()).analyze(market(instant))
    service=market_service()
    earlier=bar(0); later=bar(5)
    assert service.gap_classification(earlier,later,known_closure=session.expected_availability.expected_closure) is GapClassification.EXPECTED_CLOSURE
    assert service.data_health((earlier,),instant)[0].name=="INVALID"


def test_historical_clock_not_host_clock_drives_snapshot():
    historical=datetime(2024,7,1,12,tzinfo=timezone.utc)
    e=SessionEngine(FixedClock(historical),InMemoryAuditSink(),SessionConfiguration(sessions=definitions()),WeekdayFallbackCalendar())
    result=e.analyze(market(historical))
    assert result.as_of_timestamp_utc==historical and result.time_context.research_clock_time==historical
