from dataclasses import FrozenInstanceError,replace
from datetime import timedelta

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.events import *
from amrte.market.intelligence import *
from amrte.market.regime import RegimeConfiguration,RegimeEngine
from amrte.market.session import SessionEngine,SessionConfiguration,TimeZoneService,WeekdayFallbackCalendar
from Tests.Unit.test_events import NOW,config,event,provider
from Tests.Unit.test_regime import upstream
from Tests.Unit.test_session import definitions


def chain(*,event_items=(),provider_health=EventProviderHealth.HEALTHY,identity="MD"):
    m,s,f=upstream(identity=identity);m=replace(m,created_at=NOW,as_of_timestamp=NOW);s=replace(s,created_at=NOW,as_of_timestamp=NOW);f=replace(f,created_at=NOW,as_of_timestamp=NOW)
    audit=InMemoryAuditSink();clock=FixedClock(NOW)
    r=RegimeEngine(clock,audit,RegimeConfiguration(confirmation_observations=1,minimum_classification_margin=0,cooldown_observations=0)).analyze(m,s,f)
    session=SessionEngine(clock,audit,SessionConfiguration(sessions=definitions()),WeekdayFallbackCalendar()).analyze(m)
    news=NewsRiskEngine(clock,audit,TimeZoneService(),provider(event_items,provider_health),config()).analyze(NOW,m.instrument_id,"CFG")
    return (m,s,f,r,session,news),audit


def test_full_phase2_chain_and_immutable_snapshot():
    values,audit=chain();result=MarketIntelligenceAssembler(FixedClock(NOW),audit).assemble(*values)
    assert result.overall_intelligence_health is IntelligenceHealth.HEALTHY
    assert result.intelligence_availability is IntelligenceAvailability.AVAILABLE
    assert result.decision_trace.outcome.name=="NO_ACTION"
    with pytest.raises(FrozenInstanceError):result.instrument_id="OTHER"


def test_high_event_restricts_but_does_not_authorize():
    values,audit=chain(event_items=(event(scheduled=NOW+timedelta(minutes=30)),))
    result=MarketIntelligenceAssembler(FixedClock(NOW),audit).assemble(*values)
    assert result.overall_intelligence_health is IntelligenceHealth.RESTRICTED
    assert result.intelligence_availability is IntelligenceAvailability.AVAILABLE_WITH_RESTRICTIONS
    assert result.decision_trace.outcome.name=="NO_ACTION"


def test_unavailable_news_cannot_become_clear_or_available():
    values,audit=chain(provider_health=EventProviderHealth.UNAVAILABLE)
    result=MarketIntelligenceAssembler(FixedClock(NOW),audit).assemble(*values)
    assert values[-1].risk_state is NewsRiskState.DATA_UNAVAILABLE
    assert result.intelligence_availability is IntelligenceAvailability.NOT_AVAILABLE


@pytest.mark.parametrize("index,field,value,reason",[
    (0,"instrument_id","FICTIONAL_OTHER","INSTRUMENT_MISMATCH"),
    (1,"dataset_id","OTHER","DATASET_ID_MISMATCH"),
    (2,"dataset_fingerprint","OTHER","DATASET_FINGERPRINT_MISMATCH"),
    (4,"configuration_snapshot_id","OTHER","CONFIGURATION_MISMATCH"),
    (5,"recovery_epoch",2,"RECOVERY_EPOCH_MISMATCH"),
])
def test_unified_lineage_rejections(index,field,value,reason):
    values,audit=chain();changed=list(values);changed[index]=replace(changed[index],**{field:value})
    assembler=MarketIntelligenceAssembler(FixedClock(NOW),audit)
    valid,reasons=assembler.validate_lineage(*changed)
    assert not valid and reason in reasons and assembler.assemble(*changed) is None


def test_future_component_rejected_by_temporal_coherence():
    values,audit=chain();changed=list(values);changed[3]=replace(changed[3],as_of_timestamp=NOW+timedelta(minutes=1))
    assert MarketIntelligenceAssembler(FixedClock(NOW),audit).assemble(*changed) is None


def test_multi_instrument_independent_news_intelligence():
    e=event(dimensions=("USD",));p=provider((e,));clock=FixedClock(NOW)
    engine=NewsRiskEngine(clock,InMemoryAuditSink(),TimeZoneService(),p,config())
    alpha=engine.analyze(NOW,"FICTIONAL_ALPHA","CFG");beta=engine.analyze(NOW,"FICTIONAL_BETA","CFG")
    assert alpha.risk_state is NewsRiskState.UPCOMING_HIGH and beta.risk_state is NewsRiskState.CLEAR
    assert alpha.news_risk_snapshot_id!=beta.news_risk_snapshot_id
