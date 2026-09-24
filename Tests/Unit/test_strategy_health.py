from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import pytest

from amrte.portfolio.strategy_health import *
from amrte.portfolio.correlation import CorrelationDecisionOutcome
from Tests.Unit.test_correlation_dependency import NOW,engine as correlation_engine,pregistry,req

def profile(**kw):
    values=dict(profile_id="PROFILE-S1",profile_version="1",strategy_id="S1",strategy_version="1",strategy_family="TREND",strategy_variant=None,applicable_regimes=("TREND",),expected_mean_r_min=Decimal("0"),expected_mean_r_max=Decimal("2"),expected_win_rate_min=Decimal(".3"),expected_win_rate_max=Decimal(".8"),maximum_expected_drawdown=Decimal("4"),caution_expectancy=Decimal("-.1"),defensive_expectancy=Decimal("-.5"),suspend_expectancy=Decimal("-1"),caution_drawdown=Decimal("2"),defensive_drawdown=Decimal("4"),suspend_drawdown=Decimal("6"),minimum_observations=3,minimum_regime_observations=2,provenance="APPROVED_SYNTHETIC_BASELINE",valid_from_utc=NOW-timedelta(days=100),known_at_utc=NOW-timedelta(days=100),configuration_snapshot_id="PROFILE-CFG");values.update(kw);return StrategyExpectedBehaviorProfile(**values)

def outcome(index,value,strategy="S1",version="1",variant=None,regime="TREND",known=None):
    known=known or NOW-timedelta(days=10-index);opened=known-timedelta(hours=2);value=Decimal(str(value));oid=deterministic_id("test_outcome",strategy,version,variant or "NONE",index,str(value),known.isoformat())
    return StrategyOutcomeObservation(oid,"COMP-"+str(index),strategy,version,"TREND",variant,"HYP-"+str(index),"SIG-"+str(index),"DEC-"+str(index),"FICTIONAL_AB",regime,regime,ONE,value,"R_TARGET","POLICY",opened,known,known,"FP","PROFILE-CFG",0,OutcomeHealth.HEALTHY)

def health_engine(**kw):
    cfg=StrategyHealthConfiguration(windows=(HealthWindow("SHORT",5,3),),recovery_cooldown_seconds=0,configuration_snapshot_id="H24",**kw);return StrategyHealthEngine(cfg)

def p23_decision(amount=".4"):
    r=pregistry();q=req("P24",amount=amount);p22=r.assess(q);e=correlation_engine();snap=e.snapshot(r.snapshot(NOW),(),{},NOW);return e.assess(q,p22,snap,(),{})

def test_config_validation_multiplier_bounds_windows_and_transitions():
    with pytest.raises(ValueError):StrategyHealthEngine(StrategyHealthConfiguration(healthy_multiplier=Decimal("1.1")))
    with pytest.raises(ValueError):StrategyHealthEngine(StrategyHealthConfiguration(windows=()))
    with pytest.raises(ValueError):StrategyHealthEngine(StrategyHealthConfiguration(recovery_confirmation_count=0))

def test_outcome_ingestion_deduplication_and_point_in_time():
    e=health_engine();items=(outcome(1,1),outcome(2,-1),outcome(3,1),outcome(4,-5,known=NOW+timedelta(days=1)));e.ingest(items+items);s=e.evaluate(profile(),NOW)
    assert len(e.ledger.outcomes)==4 and len(s.outcome_observation_ids)==3 and items[-1].observation_id not in s.outcome_observation_ids

def test_metrics_reference_vector():
    e=health_engine();items=tuple(outcome(i,v) for i,v in enumerate([1,-1,2,-2,0],1));m=e._metrics(items)
    assert m.observation_count==5 and m.cumulative_r==0 and m.mean_r==0 and m.median_r==0 and m.win_rate==Decimal(".4") and m.loss_rate==Decimal(".4") and m.neutral_rate==Decimal(".2") and m.maximum_drawdown>=0

def test_insufficient_history_is_probation_not_healthy():
    e=health_engine();e.ingest((outcome(1,1),));s=e.evaluate(profile(),NOW);assert s.raw_health_state is StrategyHealthState.INSUFFICIENT_HISTORY and s.current_allocation_multiplier==e.configuration.probation_multiplier

@pytest.mark.parametrize("values,expected",[([1,1,1],StrategyHealthState.HEALTHY),([-.2,-.2,-.2],StrategyHealthState.CAUTION),([-.6,-.6,-.6],StrategyHealthState.DEFENSIVE),([-2,-2,-2],StrategyHealthState.SUSPENDED)])
def test_health_states(values,expected):
    e=health_engine();e.ingest(tuple(outcome(i,v) for i,v in enumerate(values,1)));s=e.evaluate(profile(),NOW);assert s.raw_health_state is expected and s.published_health_state is expected

def test_recent_profit_never_boosts_and_upstream_reduction_not_restored():
    e=health_engine();e.ingest(tuple(outcome(i,5) for i in range(1,6)));s=e.evaluate(profile(),NOW);d=e.allocate(p23_decision(".4"),s);assert s.current_allocation_multiplier<=1 and d.final_approved_exposure<=d.prompt23_approved_exposure

def test_caution_defensive_and_suspension_restrict():
    for values,maximum in (([-.2]*3,Decimal(".75")),([-.6]*3,Decimal(".35")),([-2]*3,ZERO)):
        e=health_engine();e.ingest(tuple(outcome(i,v) for i,v in enumerate(values,1)));s=e.evaluate(profile(),NOW);d=e.allocate(p23_decision(),s);assert d.final_approved_exposure<=d.prompt23_approved_exposure*maximum

def test_no_action_is_explicit_and_non_mutating():
    e=health_engine();e.ingest(tuple(outcome(i,1) for i in range(1,4)));s=e.evaluate(profile(),NOW);up=replace(p23_decision(),outcome=CorrelationDecisionOutcome.NO_ACTION,approved_exposure=ZERO);before=len(e.ledger.outcomes);d=e.allocate(up,s);assert d.outcome is AllocationOutcome.NO_ACTION and d.final_approved_exposure==0 and len(e.ledger.outcomes)==before

def test_strategy_version_and_variant_isolation():
    e=health_engine();e.ingest((outcome(1,1),outcome(2,1,version="2"),outcome(3,-2,variant="RETEST")));s=e.evaluate(replace(profile(),minimum_observations=1),NOW);assert s.outcome_observation_ids==(outcome(1,1).observation_id,)

def test_regime_conditioned_metrics_require_minimum_sample():
    e=health_engine();e.ingest((outcome(1,1,regime="TREND"),outcome(2,-1,regime="TREND"),outcome(3,1,regime="RANGE")));s=e.evaluate(profile(),NOW);assert tuple(x[0] for x in s.regime_results)==("TREND",)

def test_recovery_requires_new_evidence_and_confirmation():
    e=health_engine(recovery_confirmation_count=2);e.ingest(tuple(outcome(i,-2) for i in range(1,4)));bad=e.evaluate(profile(),NOW);assert bad.published_health_state is StrategyHealthState.SUSPENDED
    e.ingest((outcome(4,2,known=NOW+timedelta(minutes=1)),));one=e.evaluate(profile(),NOW+timedelta(minutes=1));assert one.published_health_state is StrategyHealthState.SUSPENDED
    e.ingest((outcome(5,2,known=NOW+timedelta(minutes=2)),));two=e.evaluate(profile(),NOW+timedelta(minutes=2));assert two.published_health_state in (StrategyHealthState.SUSPENDED,StrategyHealthState.DEFENSIVE,StrategyHealthState.CAUTION)

def test_stale_invalid_and_future_profile_fail_closed():
    e=health_engine(stale_after_seconds=1);e.ingest(tuple(outcome(i,1) for i in range(1,4)));s=e.evaluate(profile(),NOW);assert s.raw_health_state is StrategyHealthState.STALE and e.allocate(p23_decision(),s).outcome is AllocationOutcome.BLOCK
    with pytest.raises(ValueError):e.evaluate(replace(profile(),known_at_utc=NOW+timedelta(days=1)),NOW)
    with pytest.raises(ValueError):e.ingest((replace(outcome(1,1),realized_normalized_r=Decimal("NaN")),))

def test_family_health_composition_is_most_restrictive():
    e=health_engine();e.ingest(tuple(outcome(i,1) for i in range(1,4)));healthy=e.evaluate(profile(),NOW)
    family=replace(healthy,snapshot_id="FAMILY",current_allocation_multiplier=Decimal(".35"),published_health_state=StrategyHealthState.DEFENSIVE);d=e.allocate(p23_decision(),healthy,family);assert d.allocation_multiplier==Decimal(".35")

def test_recovery_and_fail_closed_restart():
    e=health_engine();e.ingest(tuple(outcome(i,-.2) for i in range(1,4)));e.evaluate(profile(),NOW);state=e.recovery_state();r=health_engine();assert r.restore(state) and len(r.ledger.outcomes)==3
    assert not r.restore({**state,"schema_version":"OLD"}) and r.recovery_restricted

def test_phase_v_snapshot_identity_immutability_and_monotonicity():
    e=health_engine();e.ingest(tuple(outcome(i,1) for i in range(1,4)));s=e.evaluate(profile(),NOW);d=e.allocate(p23_decision(),s);final=e.phase_v_snapshot("P22","P23",(s,),(d,),NOW,"FP");assert final.final_research_admission[0][1]<=d.final_approved_exposure
    with pytest.raises(FrozenInstanceError):final.portfolio_health="X"

def test_bounded_history_observability_trace_and_safety_surface():
    cfg=StrategyHealthConfiguration(windows=(HealthWindow("W",3,1),),maximum_outcomes=2,maximum_snapshots=1,maximum_transitions=2,maximum_decisions=1,configuration_snapshot_id="H24");e=StrategyHealthEngine(cfg);e.ingest(tuple(outcome(i,1) for i in range(1,4)));assert len(e.ledger.outcomes)==2;s=e.evaluate(replace(profile(),minimum_observations=1),NOW);d=e.allocate(p23_decision(),s);assert d.decision_trace
    forbidden={"connect_broker","broker_login","read_account","place_order","modify_order","close_position","set_leverage","calculate_margin"};assert forbidden.isdisjoint(set(dir(e)))
