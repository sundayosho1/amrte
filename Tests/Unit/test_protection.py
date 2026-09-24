from dataclasses import FrozenInstanceError,replace
from datetime import timedelta
from decimal import Decimal
import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.risk.protection import *
from amrte.risk.exit_management import ResearchObservation
from Tests.Unit.test_exit_management import upstream,policy
from amrte.risk.exit_management import ResearchExitManagementEngine

def context(profile=None):
    snap,inv,rec,ref=upstream();exit_engine=ResearchExitManagementEngine();exit_result=exit_engine.create_plan(snap,inv,rec,ref,policy());engine=ProtectiveBoundaryEngine();profile=profile or ProtectionProfile("P","1","TREND");initial=engine.initialize(snap,inv,exit_result.plan,exit_result.state,profile,ref);return engine,profile,snap,inv,exit_result.plan,exit_result.state,ref,initial

def observation(plan,value,minutes=1,high=None,low=None,oid=None):
    t=plan.created_at_utc+timedelta(minutes=minutes);v=Decimal(str(value));return ResearchObservation(oid or f"O-{value}-{minutes}",t,t,Decimal(str(high if high is not None else value)),Decimal(str(low if low is not None else value)),v,minutes,"DATASET-A","FICTIONAL_ALPHA","H1","D1",False)

def evaluate(engine,profile,snap,inv,plan,state,ref,initial,value="103",**kwargs):
    o=observation(plan,value,kwargs.pop("minutes",1),kwargs.pop("high",None),kwargs.pop("low",None),kwargs.pop("oid",None));return engine.evaluate(snap,inv,plan,state,profile,ref,o,**kwargs)

def test_initial_boundary_preserves_prompt19_authority_and_is_immutable():
    *_,inv,plan,state,ref,initial=context();assert initial.state.current_boundary==inv.research_invalidation_boundary and initial.version.original_invalidation_decision_id==inv.decision_id
    with pytest.raises(FrozenInstanceError):initial.version.value=Decimal("0")

def test_zero_remaining_exposure_blocks_management():
    engine,p,snap,inv,plan,state,ref,_=context();zero=replace(state,remaining_exposure=Decimal("0"));result=engine.initialize(snap,inv,plan,zero,p,ref);assert result.decision.eligibility is ProtectionEligibility.BLOCKED

@pytest.mark.parametrize("direction",[ResearchDirection.BULLISH,ResearchDirection.BEARISH])
def test_break_even_r_activation_is_symmetric(direction):
    engine,p,snap,inv,plan,state,ref,initial=context()
    if direction is ResearchDirection.BEARISH:
        inv=replace(inv,direction=direction,research_invalidation_boundary=Decimal("102"),normalized_distance=replace(inv.normalized_distance,direction=direction));engine=ProtectiveBoundaryEngine();initial=engine.initialize(snap,inv,plan,state,p,ref)
    value="103" if direction is ResearchDirection.BULLISH else "97";result=evaluate(engine,p,snap,inv,plan,state,ref,initial,value);assert result.version and result.version.method is ManagementMode.BREAK_EVEN and result.state.current_boundary==Decimal("100")

def test_break_even_not_reached_and_duplicate_prevented():
    engine,p,snap,inv,plan,state,ref,initial=context();waiting=evaluate(engine,p,snap,inv,plan,state,ref,initial,"101");assert waiting.version is None
    activated=evaluate(engine,p,snap,inv,plan,state,ref,initial,"103");again=evaluate(engine,p,snap,inv,plan,state,ref,activated,"103",minutes=2);assert activated.version and again.version is None

def test_stage_and_structure_activation():
    p=ProtectionProfile("P","1","TREND",break_even_activation=ActivationMethod.TARGET_STAGE_COMPLETION,trailing_enabled=False);engine,p,snap,inv,plan,state,ref,initial=context(p);state=replace(state,completed_stage_ids=(plan.stages[0].stage_id,));assert evaluate(engine,p,snap,inv,plan,state,ref,initial,"101").version
    p=replace(p,profile_id="PS",break_even_activation=ActivationMethod.STRUCTURAL_PROGRESS);engine,p,snap,inv,plan,state,ref,initial=context(p);t=plan.created_at_utc+timedelta(minutes=1);a=ProtectionActivationEvidence("A",ActivationMethod.STRUCTURAL_PROGRESS,("S",),True,Decimal("0"),t,"DATASET-A",snap.instrument_id,"H1",ProtectionHealth.HEALTHY);assert evaluate(engine,p,snap,inv,plan,state,ref,initial,"101",activation=a).version

def test_fixed_and_atr_break_even_offsets():
    p=ProtectionProfile("P","1","TREND",offset_method=OffsetMethod.NORMALIZED_FIXED,offset_value=Decimal(".2"),trailing_enabled=False);engine,p,snap,inv,plan,state,ref,initial=context(p);assert evaluate(engine,p,snap,inv,plan,state,ref,initial,"103").state.current_boundary==Decimal("100.2")
    p=replace(p,profile_id="A",offset_method=OffsetMethod.ATR_NORMALIZED,offset_value=Decimal(".5"));engine,p,snap,inv,plan,state,ref,initial=context(p);t=plan.created_at_utc+timedelta(minutes=1);atr=ATRTrailEvidence("ATR",Decimal("2"),Decimal("103"),t,"DATASET-A",snap.instrument_id,"H1",ProtectionHealth.HEALTHY);assert evaluate(engine,p,snap,inv,plan,state,ref,initial,"103",atr=atr).state.current_boundary==Decimal("101.0")

def test_invalid_offset_and_config_rejected():
    assert ProtectionProfile("P","1","T",offset_value=Decimal("NaN")).validate()
    with pytest.raises(ValueError):ProtectiveBoundaryEngine(ProtectionConfiguration(tolerance=Decimal("NaN")))

def test_atr_trailing_and_expansion_cannot_loosen():
    p=ProtectionProfile("P","1","TREND",break_even_enabled=False,trailing_activation=ActivationMethod.NORMALIZED_R,trailing_threshold=Decimal("1"),trailing_methods=(TrailingMethod.ATR_TRAILING,),atr_multiplier=Decimal("1"));engine,p,snap,inv,plan,state,ref,initial=context(p);t=plan.created_at_utc+timedelta(minutes=1);atr=ATRTrailEvidence("ATR",Decimal("1"),Decimal("104"),t,"DATASET-A",snap.instrument_id,"H1",ProtectionHealth.HEALTHY);advanced=evaluate(engine,p,snap,inv,plan,state,ref,initial,"104",atr=atr);assert advanced.state.current_boundary==Decimal("103")
    wider=replace(atr,evidence_id="W",atr_value=Decimal("5"),reference_value=Decimal("104"),available_at_utc=t+timedelta(minutes=1));result=evaluate(engine,p,snap,inv,plan,state,ref,advanced,"104",minutes=2,atr=wider);assert result.version is None and result.state.current_boundary==Decimal("103")

def test_missing_future_and_invalid_atr_create_no_candidate():
    p=ProtectionProfile("P","1","T",break_even_enabled=False,trailing_activation=ActivationMethod.NORMALIZED_R,trailing_methods=(TrailingMethod.ATR_TRAILING,));engine,p,snap,inv,plan,state,ref,initial=context(p);assert not evaluate(engine,p,snap,inv,plan,state,ref,initial,"104").candidates
    t=plan.created_at_utc+timedelta(minutes=5);atr=ATRTrailEvidence("F",Decimal("1"),Decimal("104"),t,"DATASET-A",snap.instrument_id,"H1",ProtectionHealth.HEALTHY);assert not evaluate(engine,p,snap,inv,plan,state,ref,initial,"104",atr=atr).candidates

def test_structure_trailing_confirmation_time_and_monotonicity():
    p=ProtectionProfile("P","1","T",break_even_enabled=False,trailing_activation=ActivationMethod.NORMALIZED_R,trailing_methods=(TrailingMethod.STRUCTURE_TRAILING,));engine,p,snap,inv,plan,state,ref,initial=context(p);t=plan.created_at_utc+timedelta(minutes=1);s=StructureTrailEvidence("S",Decimal("101"),t,"DATASET-A",snap.instrument_id,"H1",ProtectionHealth.HEALTHY);assert evaluate(engine,p,snap,inv,plan,state,ref,initial,"104",structure=s).state.current_boundary==101
    future=replace(s,evidence_id="F",confirmed_at_utc=t+timedelta(hours=1));assert not evaluate(engine,p,snap,inv,plan,state,ref,initial,"104",structure=future).candidates

def test_r_steps_ordering_and_progression():
    p=ProtectionProfile("P","1","T",break_even_enabled=False,trailing_activation=ActivationMethod.NORMALIZED_R,trailing_methods=(TrailingMethod.R_BASED_TRAILING,),r_steps=(RStep(Decimal("1"),Decimal("0")),RStep(Decimal("2"),Decimal("1"))));engine,p,snap,inv,plan,state,ref,initial=context(p);a=evaluate(engine,p,snap,inv,plan,state,ref,initial,"103");assert a.state.current_boundary==100;b=evaluate(engine,p,snap,inv,plan,state,ref,a,"105",minutes=2);assert b.state.current_boundary==102
    assert ProtectionProfile("X","1","T",r_steps=(RStep(Decimal("2"),Decimal("1")),RStep(Decimal("1"),Decimal("2")))).validate()

def test_hybrid_selection_order_independent():
    p=ProtectionProfile("P","1","T",break_even_enabled=False,trailing_activation=ActivationMethod.NORMALIZED_R,trailing_methods=(TrailingMethod.ATR_TRAILING,TrailingMethod.STRUCTURE_TRAILING,TrailingMethod.R_BASED_TRAILING),atr_multiplier=Decimal("1"),r_steps=(RStep(Decimal("1"),Decimal(".5")),));engine,p,snap,inv,plan,state,ref,initial=context(p);t=plan.created_at_utc+timedelta(minutes=1);atr=ATRTrailEvidence("A",Decimal("1"),Decimal("104"),t,"DATASET-A",snap.instrument_id,"H1",ProtectionHealth.HEALTHY);s=StructureTrailEvidence("S",Decimal("101"),t,"DATASET-A",snap.instrument_id,"H1",ProtectionHealth.HEALTHY);a=evaluate(engine,p,snap,inv,plan,state,ref,initial,"104",atr=atr,structure=s)
    p2=replace(p,profile_id="P2",trailing_methods=tuple(reversed(p.trailing_methods)));engine2,p2,snap2,inv2,plan2,state2,ref2,initial2=context(p2);atr2=replace(atr,available_at_utc=plan2.created_at_utc+timedelta(minutes=1));s2=replace(s,confirmed_at_utc=plan2.created_at_utc+timedelta(minutes=1));b=evaluate(engine2,p2,snap2,inv2,plan2,state2,ref2,initial2,"104",atr=atr2,structure=s2);assert a.state.current_boundary==b.state.current_boundary==103

def test_minimum_improvement_and_cooldown():
    p=ProtectionProfile("P","1","T",minimum_improvement=Decimal("5"));engine,p,snap,inv,plan,state,ref,initial=context(p);assert evaluate(engine,p,snap,inv,plan,state,ref,initial,"103").version is None
    p=replace(p,profile_id="C",minimum_improvement=Decimal(".01"),cooldown_seconds=120);engine,p,snap,inv,plan,state,ref,initial=context(p);assert evaluate(engine,p,snap,inv,plan,state,ref,initial,"103").version is None

def test_partial_exit_and_runner_awareness_never_restore_exposure():
    engine,p,snap,inv,plan,state,ref,initial=context();reduced=replace(state,remaining_exposure=Decimal("10"),runner_active=True,runner_exposure=Decimal("10"));result=evaluate(engine,p,snap,inv,plan,reduced,ref,initial,"103");assert result.state.remaining_exposure==10 and result.state.runner_active
    restored=replace(reduced,remaining_exposure=Decimal("60"));assert evaluate(engine,p,snap,inv,plan,restored,ref,result,"104",minutes=2).decision.eligibility is ProtectionEligibility.BLOCKED

def test_same_bar_new_boundary_cannot_retroactively_hit():
    p=ProtectionProfile("P","1","T",break_even_enabled=False,trailing_activation=ActivationMethod.NORMALIZED_R,trailing_methods=(TrailingMethod.R_BASED_TRAILING,),r_steps=(RStep(Decimal("1"),Decimal(".5")),),trigger_policy=TriggerPolicy.TOUCH);engine,p,snap,inv,plan,state,ref,initial=context(p);result=evaluate(engine,p,snap,inv,plan,state,ref,initial,"103",low="99");assert result.version is None and "TRAIL_SAME_BAR_USE_PRIOR_BOUNDARY" in result.decision.reason_codes

def test_protective_event_touch_close_and_no_backdating():
    engine,p,snap,inv,plan,state,ref,initial=context();active=evaluate(engine,p,snap,inv,plan,state,ref,initial,"103");o=observation(plan,"99",minutes=2);event,terminal=engine.observe(plan,active.state,o,inv.direction);assert event.confirmed_at_utc==o.available_at_utc and terminal.remaining_exposure==0 and terminal.terminated
    duplicate,_=engine.observe(plan,terminal,o,inv.direction);assert duplicate is None

def test_recovery_replay_chain_and_weaker_restore_rejected():
    engine,p,snap,inv,plan,state,ref,initial=context();active=evaluate(engine,p,snap,inv,plan,state,ref,initial,"103");saved=engine.recovery_state();restored=ProtectiveBoundaryEngine();assert restored.restore(saved) and restored.ledger.states[plan.exit_plan_id].current_boundary==active.state.current_boundary
    corrupt=dict(saved);ledger=dict(corrupt["ledger"]);bad=dict(ledger["states"]);bad[plan.exit_plan_id]=replace(active.state,current_boundary=Decimal("1"));ledger["states"]=bad;corrupt["ledger"]=ledger;assert not ProtectiveBoundaryEngine().restore(corrupt)

def test_strategy_variant_instrument_and_lineage_isolation():
    engine,p,snap,inv,plan,state,ref,initial=context();wrong=replace(plan,strategy_variant="RETEST",exit_plan_id="OTHER");result=engine.initialize(snap,inv,wrong,state,p,ref);assert result.decision.eligibility is ProtectionEligibility.BLOCKED
    o=observation(plan,"103");o=replace(o,instrument_id="OTHER");assert engine.evaluate(snap,inv,plan,state,p,ref,o).decision.eligibility is ProtectionEligibility.BLOCKED

def test_observability_trace_and_bounds():
    audit=InMemoryAuditSink();cfg=ProtectionConfiguration(maximum_candidates=1,maximum_versions=2,maximum_events=1,maximum_ledger_entries=4,maximum_cache_entries=1);engine=ProtectiveBoundaryEngine(cfg,audit);snap,inv,rec,ref=upstream();er=ResearchExitManagementEngine().create_plan(snap,inv,rec,ref,policy());p=ProtectionProfile("P","1","T");initial=engine.initialize(snap,inv,er.plan,er.state,p,ref);result=evaluate(engine,p,snap,inv,er.plan,er.state,ref,initial,"103");assert result.decision_trace and len(engine._versions)<=2 and any(x[0]=="protective_boundary_advanced" for x in audit.events)

def test_safety_surface_has_no_execution_or_exposure_addition():
    forbidden={"connect_broker","broker_login","modify_stop","modify_order","close_position","place_order","set_leverage","calculate_margin","add_exposure","pyramid"};assert forbidden.isdisjoint(set(dir(ProtectiveBoundaryEngine)))
