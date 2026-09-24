from dataclasses import FrozenInstanceError,replace
from datetime import timedelta
from decimal import Decimal
import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.risk.adaptive import *
from amrte.risk.sizing import ResearchCapitalContext,InvalidationDistanceContext,RiskSizingConfiguration,RiskSizingEngine
from Tests.Unit.test_risk_sizing import strategy_snapshot

def context():
    snap=strategy_snapshot();cap=ResearchCapitalContext.create("10000",snap.as_of_timestamp_utc);dist=InvalidationDistanceContext.create("2",snap.as_of_timestamp_utc);base=RiskSizingEngine().size(snap,cap,dist);t=snap.as_of_timestamp_utc
    vol=VolatilityEvidence("VOL",VolatilityState.NORMAL,t,"FEATURES","TREND")
    strategy=HealthEvidence("STRATEGY","HEALTHY",t,"SIGNAL","STRATEGY")
    data=HealthEvidence("DATA","HEALTHY",t,"INTELLIGENCE","DATA")
    equity=(ResearchEquityObservation.create("10000",t),)
    return base,equity,vol,strategy,data

def evaluate(config=AdaptiveRiskConfiguration(),equities=("10000",),volatility=VolatilityState.NORMAL,strategy="HEALTHY",data="HEALTHY",engine=None):
    base,_,vol,sh,dh=context();t=base.exposure_decision.as_of_timestamp_utc
    history=tuple(ResearchEquityObservation.create(x,t-timedelta(minutes=len(equities)-i-1)) for i,x in enumerate(equities))
    vol=replace(vol,state=volatility,evidence_id="VOL-"+volatility.name);sh=replace(sh,state=strategy,evidence_id="SH-"+strategy);dh=replace(dh,state=data,evidence_id="DH-"+data)
    return (engine or AdaptiveRiskEngine(config)).evaluate(base,history,vol,sh,dh)

def test_prompt17_authority_base_preserved_and_immutable():
    result=evaluate();d=result.decision
    assert d.prompt17_risk_budget_id and d.base_risk_amount==Decimal("100.00") and d.adaptive_risk_amount==d.base_risk_amount
    assert d.adaptive_risk_state is AdaptiveRiskState.NORMAL and d.adapted_exposure.quantized_simulated_exposure==Decimal("50.00")
    with pytest.raises(FrozenInstanceError):d.adaptive_risk_amount=999

def test_modifier_domain_and_configuration_rejects_amplification_nonfinite_negative():
    t=context()[0].exposure_decision.as_of_timestamp_utc
    with pytest.raises(ValueError,match="AR_MODIFIER_OUT_OF_RANGE"):RiskModifierResult("X",ModifierType.CUSTOM,"1",(),"X",Decimal("1.1"),ModifierHealth.HEALTHY,ModifierAvailability.AVAILABLE,(),(),t,"C","X")
    with pytest.raises(ValueError,match="AR_MODIFIER_OUT_OF_RANGE"):AdaptiveRiskEngine(AdaptiveRiskConfiguration(maximum_modifier=Decimal("-1")))
    with pytest.raises(ValueError,match="AR_RISK_AMPLIFICATION_FORBIDDEN"):AdaptiveRiskEngine(AdaptiveRiskConfiguration(allow_risk_amplification=True))
    with pytest.raises(ValueError,match="AR_NUMERICAL_INVALID"):AdaptiveRiskEngine(AdaptiveRiskConfiguration(maximum_modifier=Decimal("NaN")))

@pytest.mark.parametrize("equities,state,maximum",[(('10000','9700'),AdaptiveRiskState.CAUTION,Decimal('100')),(('10000','9200'),AdaptiveRiskState.REDUCED,Decimal('80')),(('10000','8500'),AdaptiveRiskState.DEFENSIVE,Decimal('50')),(('10000','7000'),AdaptiveRiskState.BLOCKED,Decimal('0'))])
def test_drawdown_bands_are_restrictive(equities,state,maximum):
    d=evaluate(equities=equities).decision;assert d.adaptive_risk_state is state and d.adaptive_risk_amount<=maximum and d.adaptive_risk_amount<=d.base_risk_amount

def test_drawdown_monotonic_metamorphic_and_peak_temporal_safety():
    risks=[evaluate(equities=('10000',x)).decision.adaptive_risk_amount for x in ('10000','9700','9200','8500','7000')]
    assert risks==sorted(risks,reverse=True)
    base,history,vol,sh,dh=context();future=ResearchEquityObservation.create('20000',base.exposure_decision.as_of_timestamp_utc+timedelta(minutes=1))
    d=AdaptiveRiskEngine().evaluate(base,history+(future,),vol,sh,dh).decision;assert d.adaptive_risk_amount==0 and 'AR_FUTURE_DRAWDOWN_EVIDENCE' in d.reason_codes

@pytest.mark.parametrize("state,expected",[(VolatilityState.NORMAL,Decimal('100')),(VolatilityState.ELEVATED,Decimal('75')),(VolatilityState.HIGH,Decimal('50')),(VolatilityState.EXTREME,Decimal('0')),(VolatilityState.UNKNOWN,Decimal('0'))])
def test_volatility_authoritative_states_only_restrict(state,expected):
    d=evaluate(volatility=state).decision;assert d.adaptive_risk_amount==expected

@pytest.mark.parametrize("health,maximum",[("HEALTHY",Decimal('100')),("DEGRADED",Decimal('75')),("RESTRICTED",Decimal('40')),("INVALID",Decimal('0')),("UNKNOWN",Decimal('0'))])
def test_strategy_health_deterioration_nonincreasing(health,maximum):
    assert evaluate(strategy=health).decision.adaptive_risk_amount<=maximum

@pytest.mark.parametrize("health,maximum",[("HEALTHY",Decimal('100')),("DEGRADED",Decimal('70')),("INCOMPLETE",Decimal('40')),("INVALID",Decimal('0')),("UNKNOWN",Decimal('0'))])
def test_data_health_deterioration_nonincreasing(health,maximum):
    assert evaluate(data=health).decision.adaptive_risk_amount<=maximum

def test_future_owned_portfolio_and_protection_are_honest_and_missing_policies_work():
    normal=evaluate().decision;future=[m for m in normal.modifier_results if m.modifier_type in (ModifierType.PORTFOLIO,ModifierType.PROTECTION)]
    assert all(m.availability is ModifierAvailability.FUTURE_OWNED and m.health is ModifierHealth.DEGRADED for m in future)
    restricted=evaluate(AdaptiveRiskConfiguration(portfolio_missing_policy=MissingModifierPolicy.RESTRICT)).decision;assert restricted.adaptive_risk_amount==Decimal('50.000')
    blocked=evaluate(AdaptiveRiskConfiguration(protection_missing_policy=MissingModifierPolicy.BLOCK)).decision;assert blocked.adaptive_risk_amount==0

def test_hard_maximum_most_restrictive_and_no_high_confidence_or_agreement_boost():
    cfg=AdaptiveRiskConfiguration(system_maximum_fraction=Decimal('.02'),profile_maximum_fraction=Decimal('.008'),strategy_maximum_fraction=Decimal('.015'))
    d=evaluate(cfg).decision;assert d.effective_hard_maximum==Decimal('80.000') and d.adaptive_risk_amount==Decimal('80.000') and d.adaptive_risk_amount<=d.base_risk_amount

def test_overlap_most_restrictive_avoids_double_penalty():
    base,equity,vol,sh,dh=context();t=base.exposure_decision.as_of_timestamp_utc
    sh=replace(sh,state="DEGRADED",dependency_group="SHARED");dh=replace(dh,state="DEGRADED",dependency_group="SHARED")
    d=AdaptiveRiskEngine().evaluate(base,equity,vol,sh,dh).decision;assert d.adaptive_risk_amount==Decimal('70.000')

def test_adaptive_exposure_requantized_down_and_below_minimum_zero():
    d=evaluate(volatility=VolatilityState.HIGH).decision;assert d.adapted_exposure.quantized_simulated_exposure==Decimal('25.00') and d.adapted_exposure.recalculated_risk<=d.adaptive_risk_amount
    cfg=AdaptiveRiskConfiguration(volatility_modifiers=((VolatilityState.NORMAL,Decimal('.0001')),))
    d=evaluate(cfg).decision;assert d.adapted_exposure.quantized_simulated_exposure==0 and 'AR_EXPOSURE_BELOW_MINIMUM' in d.adapted_exposure.reason_codes

def test_blocked_prompt17_and_corrupt_lineage_fail_closed():
    base,equity,vol,sh,dh=context();bad=replace(base.exposure_decision,eligibility=SizingEligibility.BLOCKED)
    d=AdaptiveRiskEngine().evaluate(replace(base,exposure_decision=bad),equity,vol,sh,dh).decision;assert d.adaptive_risk_amount==0
    corrupt=replace(base.risk_budget,risk_budget_id="CORRUPT");d=AdaptiveRiskEngine().evaluate(replace(base,risk_budget=corrupt),equity,vol,sh,dh).decision;assert d.adaptive_risk_amount==0

def test_risk_down_fast_recovery_slow_cooldown_and_restart_persistence():
    cfg=AdaptiveRiskConfiguration(cooldown_seconds=600,recovery_confirmation_observations=2);engine=AdaptiveRiskEngine(cfg)
    severe=evaluate(cfg,equities=('10000','8500'),engine=engine).decision;assert severe.adaptive_risk_state is AdaptiveRiskState.DEFENSIVE
    recover1=evaluate(cfg,equities=('10000','9900'),engine=engine).decision;assert recover1.adaptive_risk_state is AdaptiveRiskState.DEFENSIVE and 'AR_COOLDOWN_ACTIVE' in recover1.reason_codes
    state=engine.recovery_state();restored=AdaptiveRiskEngine(cfg);assert restored.restore(state) and restored._peak_by_dataset==engine._peak_by_dataset and restored._cooldowns==engine._cooldowns
    assert not restored.restore({"adaptive_risk_engine_version":"OLD"})

def test_deterministic_identity_cache_trace_observability_bounds_and_isolation():
    audit=InMemoryAuditSink();cfg=AdaptiveRiskConfiguration(maximum_cache_entries=1,maximum_decisions=1,maximum_modifier_results=6);engine=AdaptiveRiskEngine(cfg,audit=audit)
    base,equity,vol,sh,dh=context();a=engine.evaluate(base,equity,vol,sh,dh);b=engine.evaluate(base,equity,vol,sh,dh)
    assert a is b and a.decision.decision_id==b.decision.decision_id and a.decision_trace.outcome is DecisionOutcome.ACCEPTED
    assert len(engine._cache)<=1 and len(engine._decisions)<=1 and len(engine._modifiers)<=6
    assert {x for x,_ in audit.events}>={"adaptive_risk_started","adaptive_risk_completed"}

def test_safety_surface_has_no_broker_account_or_execution_capabilities():
    forbidden={"connect_broker","broker_login","read_account_equity","size_lots","calculate_margin","set_leverage","place_order","modify_position","submit_order"}
    assert forbidden.isdisjoint(set(dir(AdaptiveRiskEngine)))
