from dataclasses import replace
from decimal import Decimal
from Tests.Unit.test_exit_management import upstream,policy,obs
from amrte.risk.exit_management import ResearchExitManagementEngine,ExitStagePolicy,TargetMethod,RunnerPolicy
from amrte.risk.protection import *

def test_phase4_partial_runner_break_even_trailing_and_terminal_pipeline():
    snap,inv,rec,ref=upstream();exit_engine=ResearchExitManagementEngine();stages=(ExitStagePolicy(1,TargetMethod.FIXED_R,Decimal(".5"),r_multiple=Decimal("1")),);p20=policy(stages,RunnerPolicy.FUTURE_PROMPT21_MANAGED,".5");plan=exit_engine.create_plan(snap,inv,rec,ref,p20);partial=exit_engine.observe(plan.plan,obs(plan,"102"));assert partial.state.runner_active and partial.state.remaining_exposure<plan.state.remaining_exposure
    p21=ProtectionProfile("S1-PROTECTION","1","TREND",trailing_activation=ActivationMethod.BREAK_EVEN_ACTIVATED,trailing_methods=(TrailingMethod.R_BASED_TRAILING,));engine=ProtectiveBoundaryEngine();initial=engine.initialize(snap,inv,plan.plan,partial.state,p21,ref);be=engine.evaluate(snap,inv,plan.plan,partial.state,p21,ref,obs(plan,"103",minutes=2));assert be.state.current_boundary>=initial.state.current_boundary and be.state.remaining_exposure==partial.state.remaining_exposure
    trail=engine.evaluate(snap,inv,plan.plan,partial.state,p21,ref,obs(plan,"105",minutes=3));assert trail.state.current_boundary>=be.state.current_boundary
    hit=replace(obs(plan,"101",minutes=4),high=Decimal("101"),low=Decimal("101"),close=Decimal("101"));event,done=engine.observe(plan.plan,trail.state,hit,inv.direction);assert event and done.remaining_exposure==0

def test_phase4_same_bar_and_restart_remain_conservative_and_deterministic():
    snap,inv,rec,ref=upstream();exit_result=ResearchExitManagementEngine().create_plan(snap,inv,rec,ref,policy());profile=ProtectionProfile("P","1","TREND",break_even_enabled=False,trailing_activation=ActivationMethod.NORMALIZED_R,trailing_methods=(TrailingMethod.R_BASED_TRAILING,),r_steps=(RStep(Decimal("1"),Decimal(".5")),),trigger_policy=TriggerPolicy.TOUCH);engine=ProtectiveBoundaryEngine();initial=engine.initialize(snap,inv,exit_result.plan,exit_result.state,profile,ref);bar=replace(obs(exit_result,"103"),low=Decimal("99"));result=engine.evaluate(snap,inv,exit_result.plan,exit_result.state,profile,ref,bar);assert result.version is None
    restored=ProtectiveBoundaryEngine();assert restored.restore(engine.recovery_state());replay=restored.evaluate(snap,inv,exit_result.plan,exit_result.state,profile,ref,bar);assert replay.decision.new_protective_boundary==result.decision.new_protective_boundary
