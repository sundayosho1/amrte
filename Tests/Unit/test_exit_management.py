from dataclasses import FrozenInstanceError,replace
from datetime import timedelta
from decimal import Decimal
import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.risk.exit_management import *
from amrte.risk.invalidation import InvalidationEvent,InvalidationCondition,InvalidationLifecycle
from Tests.Unit.test_thesis_invalidation import inputs as invalidation_inputs
from amrte.risk.invalidation import ThesisInvalidationEngine
from amrte.risk.sizing import ResearchCapitalContext,RiskSizingEngine
from amrte.risk.adaptive import AdaptiveRiskEngine,ResearchEquityObservation,VolatilityEvidence,VolatilityState,HealthEvidence

def upstream():
    snap,profile,ref,structure,atr=invalidation_inputs();inv_engine=ThesisInvalidationEngine();inv=inv_engine.evaluate(snap,profile,ref,structure,atr);t=snap.as_of_timestamp_utc;capital=ResearchCapitalContext.create("10000",t);equity=(ResearchEquityObservation.create("10000",t),);vol=VolatilityEvidence("VOL",VolatilityState.NORMAL,t,"FEATURES","TREND");sh=HealthEvidence("SH","HEALTHY",t,"SIGNAL","STRATEGY");dh=HealthEvidence("DH","HEALTHY",t,"INTEL","DATA");rec=inv_engine.reconcile(inv,snap,capital,equity,vol,sh,dh,RiskSizingEngine(),AdaptiveRiskEngine());return snap,inv.decision,rec,ref.value

def policy(stages=None,runner=RunnerPolicy.NO_RUNNER,runner_fraction="0",**kwargs):
    stages=stages or (ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal("1"),TriggerPolicy.CLOSE_AT_OR_BEYOND,Decimal("1")),)
    return ExitPolicy("POLICY","1.0","TREND",None,stages,runner_policy=runner,runner_fraction=Decimal(runner_fraction),**kwargs)

def plan(policy_value=None,structural=()):
    snap,inv,rec,reference=upstream();engine=ResearchExitManagementEngine();result=engine.create_plan(snap,inv,rec,reference,policy_value or policy(),structural);return engine,result,snap,inv

def obs(plan_result,value,minutes=1,bar_index=1,high=None,low=None,session_ended=False,trading_day_id="D1"):
    t=plan_result.plan.created_at_utc+timedelta(minutes=minutes);v=Decimal(str(value));return ResearchObservation(f"OBS-{value}-{minutes}",t,t,Decimal(str(high if high is not None else value)),Decimal(str(low if low is not None else value)),v,bar_index,"DATASET-A","FICTIONAL_ALPHA","H1",trading_day_id,session_ended)

def test_fixed_r_bullish_plan_and_immutability():
    engine,result,_,_=plan();stage=result.plan.stages[0];assert result.plan.eligibility in (ExitEligibility.ELIGIBLE,ExitEligibility.ELIGIBLE_WITH_RESTRICTIONS) and stage.normalized_r==1 and stage.target_value==102
    with pytest.raises(FrozenInstanceError):result.plan.initial_simulated_exposure=999

def test_fixed_r_bearish_symmetry_and_multi_r():
    snap,profile,ref,structure,atr=invalidation_inputs(direction=ResearchDirection.BEARISH);inv_engine=ThesisInvalidationEngine();inv=inv_engine.evaluate(snap,profile,ref,structure,atr);t=snap.as_of_timestamp_utc;cap=ResearchCapitalContext.create("10000",t);eq=(ResearchEquityObservation.create("10000",t),);vol=VolatilityEvidence("V",VolatilityState.NORMAL,t,"F","TREND");h=HealthEvidence("H","HEALTHY",t,"S","STRATEGY");d=HealthEvidence("D","HEALTHY",t,"I","DATA");rec=inv_engine.reconcile(inv,snap,cap,eq,vol,h,d,RiskSizingEngine(),AdaptiveRiskEngine());p=policy((ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal("1"),r_multiple=Decimal("2")),));result=ResearchExitManagementEngine().create_plan(snap,inv.decision,rec,ref.value,p);assert result.plan.stages[0].target_value==96 and result.plan.stages[0].normalized_r==2

@pytest.mark.parametrize("value",["0","-1","NaN","Infinity"])
def test_invalid_r_rejected(value):
    assert policy((ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal("1"),r_multiple=Decimal(value)),)).validate()

def test_structural_target_temporal_direction_and_lineage_validation():
    snap,inv,rec,reference=upstream();t=snap.as_of_timestamp_utc;e=StructuralTargetEvidence("E",snap.snapshot_id,inv.research_signal_id,inv.direction,"STRUCT","SWING","CONFIRMED_SWING",Decimal("105"),t,ExitHealth.HEALTHY,True,t,"EXIT_DEFAULT_RESEARCH","DATASET-A",snap.instrument_id,"H1");p=policy((ExitStagePolicy(1,TargetMethod.STRUCTURAL,Decimal("1")),));result=ResearchExitManagementEngine().create_plan(snap,inv,rec,reference,p,(e,));assert result.plan.stages[0].target_value==105
    future=replace(e,evidence_id="F",confirmed_at_utc=t+timedelta(minutes=1));assert ResearchExitManagementEngine().create_plan(snap,inv,rec,reference,p,(future,)).plan.eligibility is ExitEligibility.BLOCKED
    wrong=replace(e,evidence_id="W",target_value=Decimal("95"));assert ResearchExitManagementEngine().create_plan(snap,inv,rec,reference,p,(wrong,)).plan.eligibility is ExitEligibility.BLOCKED

def test_multistage_partial_accounting_order_runner_and_completion():
    stages=(ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal(".5"),r_multiple=Decimal("1")),ExitStagePolicy(2,TargetMethod.FIXED_R,Decimal(".3"),r_multiple=Decimal("2")))
    engine,result,_,_=plan(policy(stages,RunnerPolicy.FUTURE_PROMPT21_MANAGED,".2"));initial=result.plan.initial_simulated_exposure
    first=engine.observe(result.plan,obs(result,"102"));assert first.state.remaining_exposure==initial-Decimal("25.00") and first.events[0].exposure_after<=first.events[0].exposure_before
    second=engine.observe(result.plan,obs(result,"104",minutes=2));assert second.state.runner_active and second.state.runner_exposure==Decimal("10.00") and second.state.remaining_exposure==Decimal("10.00")

def test_fraction_validation_cumulative_and_runner_consistency():
    with pytest.raises(ValueError,match="EXIT_FRACTION_INVALID"):ResearchExitManagementEngine().create_plan(*upstream()[:3],upstream()[3],policy((ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal("1.1"),r_multiple=Decimal("1")),)))
    assert "EXIT_FRACTION_INVALID" in policy((ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal(".7"),r_multiple=Decimal("1")),ExitStagePolicy(2,TargetMethod.FIXED_R,Decimal(".4"),r_multiple=Decimal("2")))).validate()
    assert "EXIT_UNOWNED_EXPOSURE" in policy(runner=RunnerPolicy.FIXED_REMAINDER,runner_fraction=".2").validate()

def test_zero_exposure_and_invalid_invalidation_produce_no_plan():
    snap,inv,rec,ref=upstream();zero=replace(rec,final_simulated_exposure=Decimal("0"));assert ResearchExitManagementEngine().create_plan(snap,inv,zero,ref,policy()).plan.eligibility is ExitEligibility.BLOCKED
    invalid=replace(inv,eligibility=InvalidationEligibility.BLOCKED);assert ResearchExitManagementEngine().create_plan(snap,invalid,rec,ref,policy()).plan.eligibility is ExitEligibility.BLOCKED

def test_target_touch_vs_close_and_no_backdating():
    engine,result,_,_=plan(policy((ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal("1"),TriggerPolicy.CLOSE_AT_OR_BEYOND,Decimal("1")),)));o=obs(result,"101",high="103",low="100");assert not engine.observe(result.plan,o).events
    engine,result,_,_=plan(policy((ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal("1"),TriggerPolicy.TOUCH,Decimal("1")),)));event=engine.observe(result.plan,o).events[0];assert event.confirmed_at_utc==o.available_at_utc and event.exposure_after==0

def test_same_bar_ambiguity_default_never_assumes_favorable_order():
    engine,result,_,inv=plan();o=obs(result,"103",high="103",low="97");ie=InvalidationEvent("INV-E",inv.decision_id,inv.selected_candidate_id,InvalidationCondition.TOUCH,o.observed_at_utc,o.available_at_utc,(o.observation_id,),InvalidationLifecycle.INVALIDATED,("INV_THESIS_INVALIDATED",));out=engine.observe(result.plan,o,ie);assert out.events[0].resolution is EventResolution.AMBIGUOUS and out.state.remaining_exposure==result.plan.initial_simulated_exposure

def test_invalidation_precedence_and_no_later_target_override():
    cfg=ExitManagementConfiguration(same_bar_policy=SameBarPolicy.INVALIDATION_FIRST);snap,inv,rec,ref=upstream();engine=ResearchExitManagementEngine(cfg);result=engine.create_plan(snap,inv,rec,ref,policy());o=obs(result,"103",high="103",low="97");ie=InvalidationEvent("IE",inv.decision_id,inv.selected_candidate_id,InvalidationCondition.TOUCH,o.observed_at_utc,o.available_at_utc,(o.observation_id,),InvalidationLifecycle.INVALIDATED,("INV_THESIS_INVALIDATED",));out=engine.observe(result.plan,o,ie);assert out.completion.terminal_reason is ExitReason.THESIS_INVALIDATED and out.state.remaining_exposure==0
    assert engine.observe(result.plan,obs(result,"110",minutes=2)).reason_codes==("EXIT_EXPOSURE_COMPLETE",)

def test_higher_resolution_can_resolve_same_bar_order_when_authoritative():
    engine,result,_,inv=plan();o=obs(result,"103",high="103",low="97");ie=InvalidationEvent("IEX",inv.decision_id,inv.selected_candidate_id,InvalidationCondition.TOUCH,o.observed_at_utc,o.available_at_utc,(o.observation_id,),InvalidationLifecycle.INVALIDATED,("INV_THESIS_INVALIDATED",));out=engine.observe(result.plan,o,ie,higher_resolution_order="TARGET_FIRST");assert out.events and out.events[0].exit_reason is ExitReason.R_TARGET

@pytest.mark.parametrize("method,kwargs",[(TimeExitMethod.MAX_BARS,{"maximum_bars":2}),(TimeExitMethod.MAX_ELAPSED_RESEARCH_TIME,{"maximum_elapsed_seconds":60}),(TimeExitMethod.SESSION_END,{}),(TimeExitMethod.TRADING_DAY_END,{})])
def test_time_exits_use_authoritative_observation_time(method,kwargs):
    if method is TimeExitMethod.TRADING_DAY_END:kwargs={**kwargs,"starting_trading_day_id":"D1"}
    p=policy(time_exit_method=method,**kwargs);engine,result,_,_=plan(p);o=obs(result,"100",minutes=2,bar_index=2,session_ended=True,trading_day_id="D2");out=engine.observe(result.plan,o);assert out.completion and out.completion.terminal_reason is ExitReason.TIME

@pytest.mark.parametrize("regime",["INCOMPATIBLE","ABNORMAL","UNKNOWN"])
def test_regime_state_exit_is_restrictive(regime):
    engine,result,_,_=plan();out=engine.observe(result.plan,obs(result,"100"),regime_state=regime);assert out.state.remaining_exposure==0 and out.completion.terminal_reason is ExitReason.REGIME_CHANGE

def test_multiple_targets_crossed_process_in_order_and_never_overreduce():
    stages=(ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal(".5"),r_multiple=Decimal("1")),ExitStagePolicy(2,TargetMethod.FIXED_R,Decimal(".5"),r_multiple=Decimal("2")));engine,result,_,_=plan(policy(stages));out=engine.observe(result.plan,obs(result,"105"));assert len(out.events)==2 and out.state.remaining_exposure==0 and sum(x.exposure_reduced for x in out.events)==result.plan.initial_simulated_exposure

def test_duplicate_targets_do_not_create_duplicate_exit_stages():
    stages=(ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal(".5"),r_multiple=Decimal("1")),ExitStagePolicy(2,TargetMethod.FIXED_R,Decimal(".5"),r_multiple=Decimal("1")));_,result,_,_=plan(policy(stages));assert result.plan.eligibility is ExitEligibility.BLOCKED

def test_strategy_variant_isolation_and_s3_destination_contract():
    engine,a,_,inv=plan();_,b,_,_=plan(replace(policy(),policy_id="S2-RETEST",strategy_family="BREAKOUT",strategy_variant="RETEST"));assert a.plan.exit_plan_id!=b.plan.exit_plan_id
    snap,_,_,_=upstream();t=snap.as_of_timestamp_utc;e=StructuralTargetEvidence("S3-MEAN",snap.snapshot_id,inv.research_signal_id,inv.direction,"S3","MEAN","MEAN_REVERSION_DESTINATION",Decimal("103"),t,ExitHealth.HEALTHY,True,t,"EXIT_DEFAULT_RESEARCH","DATASET-A",snap.instrument_id,"H1");p=policy((ExitStagePolicy(1,TargetMethod.STRUCTURAL,Decimal("1")),));assert plan(p,(e,))[1].plan.stages[0].target_value==103

def test_recovery_idempotency_bounded_state_trace_and_observability():
    audit=InMemoryAuditSink();cfg=ExitManagementConfiguration(maximum_plans=1,maximum_targets=1,maximum_events=1,maximum_ledger_entries=4,maximum_cache_entries=1);snap,inv,rec,ref=upstream();engine=ResearchExitManagementEngine(cfg,audit);result=engine.create_plan(snap,inv,rec,ref,policy());event1=engine.observe(result.plan,obs(result,"103"));event2=engine.observe(result.plan,obs(result,"103"));assert len(event1.events)==1 and event2.reason_codes==("EXIT_EXPOSURE_COMPLETE",)
    state=engine.recovery_state();restored=ResearchExitManagementEngine(cfg);assert restored.restore(state) and restored.ledger.states[result.plan.exit_plan_id].remaining_exposure==0 and not restored.restore({"engine_version":"OLD"})
    assert len(engine._plans)<=1 and len(engine._targets)<=1 and len(engine._events)<=1 and result.decision_trace.outcome is DecisionOutcome.ACCEPTED and {x for x,_ in audit.events}>={"exit_evaluation_started","exit_plan_created"}

def test_safety_surface_has_no_broker_or_protective_boundary_movement():
    forbidden={"connect_broker","broker_login","place_take_profit","place_stop_order","modify_order","partial_close","close_position","read_live_pnl","set_break_even","trail_stop","set_leverage","calculate_margin"};assert forbidden.isdisjoint(set(dir(ResearchExitManagementEngine)))
