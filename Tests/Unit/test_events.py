from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timedelta,timezone

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.events import *
from amrte.market.session import TimeHealth,TimeZoneService

UTC=timezone.utc
NOW=datetime(2026,6,10,12,tzinfo=UTC)


def windows():
    return {
        EventImportance.LOW:EventWindowPolicy(30,5,5,5,10),
        EventImportance.MEDIUM:EventWindowPolicy(60,10,10,10,20),
        EventImportance.HIGH:EventWindowPolicy(120,15,15,15,30),
        EventImportance.CRITICAL:EventWindowPolicy(180,30,30,30,60),
    }


def event(*,logical="EV1",version="EV1-V1",scheduled=None,known=None,updated=None,importance=EventImportance.HIGH,
          dimensions=("USD",),status=EconomicEventStatus.SCHEDULED,actual=None,actual_at=None,forecast="2.0",forecast_at=None,
          previous="1.8",previous_at=None,revision=0,supersedes=None):
    scheduled=scheduled or NOW+timedelta(minutes=60);known=known or NOW-timedelta(days=2);updated=updated or known
    return EconomicEvent(logical,version,logical,"Fictional Macro Release",EventCategory.INFLATION,"FICTIONLAND",dimensions,
        scheduled,known,updated,importance,forecast,previous,actual,forecast_at or known,previous_at or known,actual_at,
        status,revision=revision,supersedes_event_version_id=supersedes,metadata={"fixture":True})


def provider(events=(),health=EventProviderHealth.HEALTHY,coverage_start=None,coverage_end=None):
    return DeterministicEventProvider(events,coverage_start_utc=coverage_start or NOW-timedelta(days=10),
        coverage_end_utc=coverage_end or NOW+timedelta(days=10),imported_at_utc=NOW,health=health)


def config(**changes):
    values={"windows":windows(),"instrument_dimensions":{"FICTIONAL_ALPHA":("EUR","USD"),"FICTIONAL_BETA":("JPY",)},
        "strategy_policy":{"TREND_FAMILY":{NewsRiskState.CLEAR:EventEligibility.ELIGIBLE,NewsRiskState.UPCOMING_LOW:EventEligibility.CONDITIONAL}}}
    values.update(changes);return NewsRiskConfiguration(**values)


def engine(events=(),health=EventProviderHealth.HEALTHY,**changes):
    p=provider(events,health,changes.pop("coverage_start",None),changes.pop("coverage_end",None))
    return NewsRiskEngine(FixedClock(NOW),InMemoryAuditSink(),TimeZoneService(),p,config(**changes))


def test_provider_identity_fingerprint_and_abstraction():
    a=provider((event(),));b=provider((event(),))
    assert a.provenance.dataset_fingerprint==b.provenance.dataset_fingerprint
    assert a.provenance.provider_id=="OFFLINE_EVENTS" and a.health() is EventProviderHealth.HEALTHY
    c=provider((replace(event(),event_name="Changed"),))
    assert c.provenance.dataset_fingerprint!=a.provenance.dataset_fingerprint


def test_duplicate_version_and_malformed_time_rejected():
    with pytest.raises(ValueError):provider((event(),event(logical="EV2")))
    with pytest.raises(ValueError):provider((event(scheduled=datetime(2026,1,1)),))


def test_historical_as_of_revision_reschedule_and_cancellation_anti_leakage():
    original=event(scheduled=NOW+timedelta(hours=1))
    revised=event(version="EV1-V2",scheduled=NOW+timedelta(hours=3),updated=NOW+timedelta(minutes=10),
        known=original.first_known_at_utc,status=EconomicEventStatus.RESCHEDULED,revision=1,supersedes="EV1-V1")
    cancelled=event(version="EV1-V3",scheduled=revised.scheduled_time_utc,updated=NOW+timedelta(minutes=20),
        known=original.first_known_at_utc,status=EconomicEventStatus.CANCELLED,revision=2,supersedes="EV1-V2")
    p=provider((original,revised,cancelled))
    assert p.events_as_of(NOW,NOW-timedelta(days=1),NOW+timedelta(days=1))[0].event_version_id=="EV1-V1"
    assert p.events_as_of(NOW+timedelta(minutes=15),NOW-timedelta(days=1),NOW+timedelta(days=1))[0].event_version_id=="EV1-V2"
    assert p.events_as_of(NOW+timedelta(minutes=25),NOW-timedelta(days=1),NOW+timedelta(days=1))[0].event_status is EconomicEventStatus.CANCELLED


def test_first_known_and_value_availability_are_enforced():
    item=event(known=NOW+timedelta(minutes=1),actual="2.2",actual_at=NOW+timedelta(minutes=70),forecast_at=NOW-timedelta(minutes=30))
    p=provider((item,))
    assert p.events_as_of(NOW,NOW,NOW+timedelta(days=1))==()
    visible=p.events_as_of(NOW+timedelta(minutes=2),NOW,NOW+timedelta(days=1))[0]
    assert visible.actual is None and visible.forecast=="2.0"
    assert p.events_as_of(NOW+timedelta(minutes=71),NOW,NOW+timedelta(days=1))[0].actual=="2.2"


@pytest.mark.parametrize("importance,state",[
    (EventImportance.LOW,NewsRiskState.UPCOMING_LOW),(EventImportance.MEDIUM,NewsRiskState.UPCOMING_MEDIUM),
    (EventImportance.HIGH,NewsRiskState.UPCOMING_HIGH),(EventImportance.CRITICAL,NewsRiskState.UPCOMING_CRITICAL),
    (EventImportance.UNKNOWN,NewsRiskState.UPCOMING_HIGH),
])
def test_severity_and_unknown_conservative_policy(importance,state):
    minutes=20 if importance is EventImportance.LOW else 40
    result=engine((event(importance=importance,scheduled=NOW+timedelta(minutes=minutes)),)).analyze(NOW,"FICTIONAL_ALPHA","CFG")
    assert result.risk_state is state


def test_base_quote_and_generic_relevance():
    e=engine()
    assert e.relevance(event(dimensions=("EUR",)),"FICTIONAL_ALPHA").relevant
    assert e.relevance(event(dimensions=("USD",)),"FICTIONAL_ALPHA").relevant
    assert not e.relevance(event(dimensions=("GBP",)),"FICTIONAL_ALPHA").relevant
    assert e.relevance(event(dimensions=("JPY",)),"FICTIONAL_BETA").relevant


@pytest.mark.parametrize("offset,state",[
    (121,NewsRiskState.CLEAR),(120,NewsRiskState.UPCOMING_HIGH),(16,NewsRiskState.UPCOMING_HIGH),
    (15,NewsRiskState.BLACKOUT),(0,NewsRiskState.BLACKOUT),(-14,NewsRiskState.BLACKOUT),
    (-15,NewsRiskState.POST_EVENT_STABILIZATION),(-59,NewsRiskState.POST_EVENT_STABILIZATION),(-60,NewsRiskState.CLEAR),
])
def test_event_window_boundaries(offset,state):
    item=event(scheduled=NOW+timedelta(minutes=offset))
    assert engine((item,)).analyze(NOW,"FICTIONAL_ALPHA","CFG").risk_state is state


def test_valid_empty_unavailable_stale_and_incomplete_are_distinct():
    clear=engine().analyze(NOW,"FICTIONAL_ALPHA","CFG")
    unavailable=engine(health=EventProviderHealth.UNAVAILABLE).analyze(NOW,"FICTIONAL_ALPHA","CFG")
    stale=engine(health=EventProviderHealth.STALE).analyze(NOW,"FICTIONAL_ALPHA","CFG")
    incomplete=engine(coverage_end=NOW+timedelta(minutes=20)).analyze(NOW,"FICTIONAL_ALPHA","CFG")
    assert clear.risk_state is NewsRiskState.CLEAR and "VALID_NO_RELEVANT_EVENTS" in clear.supporting_reasons
    assert unavailable.risk_state is NewsRiskState.DATA_UNAVAILABLE
    assert stale.risk_state is NewsRiskState.DATA_STALE
    assert incomplete.risk_state is NewsRiskState.INCOMPLETE_COVERAGE


def test_overlapping_touching_simultaneous_clusters_and_critical_precedence():
    events=(event(logical="A",version="A1",scheduled=NOW+timedelta(minutes=30),importance=EventImportance.LOW),
        event(logical="B",version="B1",scheduled=NOW+timedelta(minutes=30),importance=EventImportance.CRITICAL),
        event(logical="C",version="C1",scheduled=NOW+timedelta(minutes=100),importance=EventImportance.MEDIUM))
    result=engine(events).analyze(NOW,"FICTIONAL_ALPHA","CFG")
    assert result.active_clusters and result.active_clusters[0].highest_severity is EventImportance.CRITICAL
    assert result.risk_state is NewsRiskState.BLACKOUT
    again=engine(tuple(reversed(events))).analyze(NOW,"FICTIONAL_ALPHA","CFG")
    assert tuple(c.cluster_id for c in result.active_clusters)==tuple(c.cluster_id for c in again.active_clusters)


def test_cancelled_and_postponed_do_not_restrict():
    events=(event(logical="A",version="A1",scheduled=NOW,status=EconomicEventStatus.CANCELLED),event(logical="B",version="B1",scheduled=NOW,status=EconomicEventStatus.POSTPONED))
    assert engine(events).analyze(NOW,"FICTIONAL_ALPHA","CFG").risk_state is NewsRiskState.CLEAR


def test_prompt9_time_normalization_and_ambiguity_reused():
    e=engine();valid=e.normalize_provider_local(datetime(2026,7,1,12),"Europe/London")
    ambiguous=e.normalize_provider_local(datetime(2026,10,25,1,30),"Europe/London")
    assert valid.health is TimeHealth.HEALTHY and valid.instant_utc.hour==11
    assert ambiguous.health is TimeHealth.AMBIGUOUS and ambiguous.instant_utc is None


def test_snapshot_immutability_advisory_policy_and_no_action():
    e=engine((event(scheduled=NOW),));result=e.analyze(NOW,"FICTIONAL_ALPHA","CFG")
    with pytest.raises(FrozenInstanceError):result.risk_state=NewsRiskState.CLEAR
    with pytest.raises(FrozenInstanceError):e.last_event_data_snapshot.provider_id="OTHER"
    assert result.policy_state is NewsPolicyState.BLOCK_NEW_RESEARCH_EXPOSURE
    assert result.decision_trace.outcome.name=="NO_ACTION"


def test_cache_isolation_bounds_recovery_and_provider_recovery_event():
    p=provider((),EventProviderHealth.STALE);audit=InMemoryAuditSink();e=NewsRiskEngine(FixedClock(NOW),audit,TimeZoneService(),p,config(maximum_cache_entries=2))
    for index in range(3):e.analyze(NOW+timedelta(minutes=index),"FICTIONAL_ALPHA","CFG",configuration_hash=str(index))
    assert e.cache_size==2 and len(e.history)==3
    p.set_health(EventProviderHealth.HEALTHY);latest=e.analyze(NOW+timedelta(minutes=4),"FICTIONAL_ALPHA","CFG")
    assert "event_provider_recovered" in {name for name,_ in audit.events}
    assert e.validate_recovery(e.recovery_state(),"CFG",0)
    assert not e.validate_recovery(e.recovery_state(),"OTHER",0)


def test_future_dataset_extension_does_not_change_earlier_risk_when_not_knowable():
    base=engine().analyze(NOW,"FICTIONAL_ALPHA","CFG")
    future=event(logical="F",version="F1",scheduled=NOW+timedelta(days=2),known=NOW+timedelta(days=1))
    extended=engine((future,)).analyze(NOW,"FICTIONAL_ALPHA","CFG")
    assert base.risk_state==extended.risk_state==NewsRiskState.CLEAR
