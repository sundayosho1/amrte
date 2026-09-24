from dataclasses import FrozenInstanceError,replace
from datetime import date,datetime,time,timezone,timedelta

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.models import *
from amrte.market.session import *

UTC=timezone.utc
NOW=datetime(2026,3,18,14,0,tzinfo=UTC)


def market(instant=NOW,identity="MD",health=DataHealth.HEALTHY,sync=SynchronizationStatus.SYNCHRONIZED,spread=SpreadHealth.NORMAL):
    spread_state=SpreadState(1,1,1,1,0,spread,SpreadOrigin.MODELED)
    return MarketDataSnapshot(identity,NOW,instant,"EXP","DS","FP","FICTIONAL_ALPHA",spread_state,(),(),(),sync,health,100,{},"CFG",0)


def definitions():
    weekdays=frozenset({0,1,2,3,4})
    return (
        SessionDefinition("ASIA",SessionType.ASIAN,"Asian","Asia/Tokyo",time(9),time(17),weekdays,1),
        SessionDefinition("LONDON",SessionType.LONDON,"London","Europe/London",time(8),time(17),weekdays,2),
        SessionDefinition("NEW_YORK",SessionType.NEW_YORK,"New York","America/New_York",time(8),time(17),weekdays,3),
    )


def engine(instant=NOW,**changes):
    configured_sessions=changes.pop("sessions",definitions())
    config=SessionConfiguration(sessions=configured_sessions,calendar_required=False,**changes)
    return SessionEngine(FixedClock(instant),InMemoryAuditSink(),config,WeekdayFallbackCalendar(CalendarProvenance("WEEKDAY","1","TEST")))


def test_utc_source_reference_and_named_timezone_separation():
    e=engine(reference_timezone="Europe/London",data_source_timezone="America/New_York")
    context=e.time_context(NOW,"CFG")
    assert context.utc_instant==NOW and context.data_source_time.hour==10 and context.reference_time.hour==14
    assert context.data_source_timezone!=context.reference_timezone


def test_fixed_offset_is_distinct_from_named_timezone():
    service=TimeZoneService(); instant=datetime(2026,7,1,12,tzinfo=UTC)
    assert service.from_utc(instant,"Europe/London").utcoffset()==timedelta(hours=1)
    assert instant.astimezone(timezone(timedelta(0))).utcoffset()==timedelta(0)


def test_dst_standard_daylight_and_differing_transition_weeks():
    service=TimeZoneService()
    assert service.from_utc(datetime(2026,1,1,12,tzinfo=UTC),"Europe/London").hour==12
    assert service.from_utc(datetime(2026,7,1,12,tzinfo=UTC),"Europe/London").hour==13
    instant=datetime(2026,3,20,12,tzinfo=UTC)
    assert service.from_utc(instant,"America/New_York").hour==8
    assert service.from_utc(instant,"Europe/London").hour==12


def test_nonexistent_and_ambiguous_local_times_fail_closed():
    service=TimeZoneService()
    nonexistent=service.resolve_local(datetime(2026,3,29,1,30),"Europe/London")
    ambiguous=service.resolve_local(datetime(2026,10,25,1,30),"Europe/London")
    assert nonexistent.health is TimeHealth.NONEXISTENT_LOCAL_TIME and nonexistent.instant_utc is None
    assert ambiguous.health is TimeHealth.AMBIGUOUS and ambiguous.instant_utc is None and len(ambiguous.candidates_utc)==2
    assert service.resolve_local(datetime(2026,10,25,1,30),"Europe/London",fold=1).health is TimeHealth.HEALTHY


def test_invalid_timezone_and_invalid_configuration():
    assert TimeZoneService().resolve_local(datetime(2026,1,1),"Invalid/Zone").health is TimeHealth.UNAVAILABLE
    with pytest.raises(ValueError):SessionEngine(FixedClock(NOW),InMemoryAuditSink(),SessionConfiguration(sessions=(
        SessionDefinition("X",SessionType.CUSTOM,"X","Invalid/Zone",time(1),time(2),frozenset({1})),)))


def test_timezone_cache_is_bounded():
    service=TimeZoneService(2);service.zone("Europe/London");service.zone("America/New_York")
    assert len(service._zones)<=2 and "UTC" in service._zones


def test_active_sessions_overlap_priority_and_no_action():
    result=engine().analyze(market())
    assert set(result.active_sessions)=={"LONDON","NEW_YORK"}
    assert result.is_overlap and result.primary_session is SessionType.LONDON_NEW_YORK_OVERLAP
    assert result.decision_trace.outcome.name=="NO_ACTION"


@pytest.mark.parametrize("instant,active",[
    (datetime(2026,3,18,7,59,tzinfo=UTC),False),
    (datetime(2026,3,18,8,0,tzinfo=UTC),True),
    (datetime(2026,3,18,16,59,tzinfo=UTC),True),
    (datetime(2026,3,18,17,0,tzinfo=UTC),False),
])
def test_open_inclusive_close_exclusive_boundaries(instant,active):
    definition=SessionDefinition("UTC_DAY",SessionType.CUSTOM,"UTC Day","UTC",time(8),time(17),frozenset({2}),9)
    result=engine(instant,sessions=(definition,)).analyze(market(instant))
    assert ("UTC_DAY" in result.active_sessions) is active


def test_cross_midnight_and_weekday_anchor():
    definition=SessionDefinition("NIGHT",SessionType.CUSTOM,"Night","UTC",time(22),time(6),frozenset({1}),1)
    instant=datetime(2026,3,18,2,tzinfo=UTC)
    result=engine(instant,sessions=(definition,)).analyze(market(instant))
    assert result.active_sessions==("NIGHT",)


def test_out_of_session_and_custom_session():
    instant=datetime(2026,3,18,23,tzinfo=UTC)
    result=engine(instant).analyze(market(instant))
    assert result.primary_session is SessionType.OUT_OF_SESSION and result.minutes_to_next_session_open is not None


def test_trading_day_week_custom_boundaries_are_deterministic():
    e=engine()
    before=datetime(2026,3,18,20,59,tzinfo=UTC); after=datetime(2026,3,18,21,0,tzinfo=UTC)
    assert e.trading_day_id(before)!=e.trading_day_id(after)
    assert e.trading_day_id(after)==engine().trading_day_id(after)
    assert e.trading_week_id(after).startswith("TW-")


def test_weekend_expected_closure_and_prompt5_contract():
    instant=datetime(2026,3,21,12,tzinfo=UTC); result=engine(instant).analyze(market(instant))
    assert result.is_weekend and result.expected_availability.expected_closure
    assert result.expected_availability.state is ExpectedAvailability.EXPECTED_CLOSED
    assert result.temporal_restriction is not TemporalRestriction.ALLOW_CONTEXT


def test_calendar_special_closure_and_unknown_strict():
    provenance=CalendarProvenance("HIST","2","FIXTURE")
    calendar=ConfiguredMarketCalendar({NOW.date():CalendarDecision(CalendarDayState.CLOSED,reason="HOLIDAY",provenance=provenance)},provenance)
    e=SessionEngine(FixedClock(NOW),InMemoryAuditSink(),SessionConfiguration(sessions=definitions(),calendar_required=True),calendar)
    result=e.analyze(market());assert result.expected_availability.expected_closure and result.calendar_provenance==provenance
    unknown=SessionEngine(FixedClock(NOW),InMemoryAuditSink(),SessionConfiguration(sessions=definitions(),calendar_required=True)).analyze(market())
    assert unknown.session_health is SessionHealth.CALENDAR_UNAVAILABLE and all(v is not SessionEligibility.ELIGIBLE for v in unknown.strategy_family_eligibility.values())


def test_friday_cutoff_boundary():
    before=datetime(2026,3,20,19,59,tzinfo=UTC); at=datetime(2026,3,20,20,0,tzinfo=UTC)
    assert engine(before).analyze(market(before)).friday_restriction is FridayRestrictionState.NORMAL
    assert engine(at).analyze(market(at)).friday_restriction is FridayRestrictionState.NEW_ACTIVITY_RESTRICTED


def test_monday_reopening_state_machine():
    early=datetime(2026,3,16,12,5,tzinfo=UTC)
    e=engine(early,monday_reopen_delay_minutes=30,minimum_reopen_observations=2)
    assert e.analyze(market(early)).monday_reopening is MondayReopeningState.INITIAL_REOPEN_WINDOW
    later=datetime(2026,3,16,13,tzinfo=UTC)
    assert engine(later,minimum_reopen_observations=2).analyze(market(later),closed_observations_after_reopen=1).monday_reopening is MondayReopeningState.NORMALIZATION_PENDING
    assert engine(later,minimum_reopen_observations=2).analyze(market(later),closed_observations_after_reopen=2).monday_reopening is MondayReopeningState.READY
    degraded=engine(later).analyze(market(later,health=DataHealth.STALE))
    assert degraded.monday_reopening is MondayReopeningState.DATA_REVALIDATION


def test_monday_waiting_for_open():
    instant=datetime(2026,3,16,22,tzinfo=UTC)
    assert engine(instant).analyze(market(instant)).monday_reopening is MondayReopeningState.WAITING_FOR_OPEN


@pytest.mark.parametrize("instant,state",[
    (datetime(2026,3,18,20,45,tzinfo=UTC),RolloverState.APPROACHING),
    (datetime(2026,3,18,21,0,tzinfo=UTC),RolloverState.ACTIVE),
    (datetime(2026,3,18,21,15,tzinfo=UTC),RolloverState.RECOVERY),
])
def test_rollover_states(instant,state):assert engine(instant).analyze(market(instant)).rollover is state


def test_instrument_override_and_advisory_eligibility():
    custom=SessionDefinition("SPECIAL",SessionType.CUSTOM,"Special","UTC",time(0),time(23,59),frozenset(range(7)),99)
    policy={"TREND_FAMILY":{"SPECIAL":SessionEligibility.ELIGIBLE}}
    result=engine(instrument_session_overrides={"FICTIONAL_ALPHA":(custom,)},strategy_eligibility=policy).analyze(market())
    assert result.active_sessions==("SPECIAL",) and result.strategy_family_eligibility["TREND_FAMILY"] is SessionEligibility.ELIGIBLE
    assert result.decision_trace.outcome.name=="NO_ACTION"


def test_snapshot_immutable_lineage_identity_and_recovery():
    e=engine(); first=e.analyze(market()); second=engine().analyze(market())
    assert first.session_snapshot_id==second.session_snapshot_id and first.dataset_fingerprint=="FP"
    with pytest.raises(FrozenInstanceError):first.primary_session=SessionType.ASIAN
    assert e.validate_recovery(e.recovery_state(),"FP","CFG") and not e.validate_recovery(e.recovery_state(),"OTHER","CFG")


def test_clock_discontinuity_restricts_and_readiness_fails():
    e=engine(maximum_clock_jump_minutes=60); assert e.readiness(e.analyze(market()))[0]
    later=NOW+timedelta(hours=2); result=e.analyze(market(later,"MD2"))
    assert "CLOCK_DISCONTINUITY" in result.reason_codes and not e.readiness(result)[0]


def test_observability_events():
    audit=InMemoryAuditSink(); e=SessionEngine(FixedClock(NOW),audit,SessionConfiguration(sessions=definitions()),WeekdayFallbackCalendar())
    e.analyze(market());assert {name for name,_ in audit.events}>={"time_engine_initialized","session_snapshot_created"}
