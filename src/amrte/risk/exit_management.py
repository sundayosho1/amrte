"""Offline fictional research exit planning and exposure-reduction accounting."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass,replace
from datetime import datetime,timedelta
from decimal import Decimal,ROUND_FLOOR,localcontext
from enum import Enum,auto

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace
from amrte.risk.sizing import _decimal
from amrte.risk.invalidation import (InvalidationEligibility,InvalidationEvent,InvalidationLifecycle,
    ResearchDirection,RiskReconciliationResult,ThesisInvalidationDecision,ThesisState)
from amrte.strategies.strategy_arbitration import ArbitrationOutcome,ResearchAvailability,StrategyDecisionSnapshot

EXIT_ENGINE_VERSION="1.0";ZERO=Decimal("0");ONE=Decimal("1")

class TargetMethod(Enum):FIXED_R=auto();STRUCTURAL=auto();CUSTOM_REGISTERED=auto()
class TargetSelectionPolicy(Enum):STRUCTURE_FIRST=auto();R_MULTIPLE_FIRST=auto();NEAREST_VALID=auto();FARTHEST_VALID=auto();STRATEGY_DEFINED=auto();COMPOSITE=auto()
class DuplicateTargetPolicy(Enum):MERGE=auto();KEEP_HIGHEST_PRIORITY=auto();REJECT_AMBIGUOUS=auto()
class TriggerPolicy(Enum):TOUCH=auto();CLOSE_AT_OR_BEYOND=auto();MULTI_CLOSE=auto();STRUCTURAL_CONFIRMATION=auto();TIME_CONDITION=auto();STRATEGY_DEFINED=auto()
class TargetState(Enum):PROPOSED=auto();VALIDATED=auto();ACTIVE=auto();APPROACHED=auto();TRIGGERED=auto();COMPLETED=auto();EXPIRED=auto();CANCELLED_BY_INVALIDATION=auto();SUPERSEDED=auto();INVALID=auto();UNKNOWN=auto()
class RunnerPolicy(Enum):NO_RUNNER=auto();FIXED_REMAINDER=auto();UNTIL_STRUCTURAL_TARGET=auto();UNTIL_TIME_EXIT=auto();UNTIL_THESIS_INVALIDATION=auto();FUTURE_PROMPT21_MANAGED=auto()
class TimeExitMethod(Enum):NONE=auto();MAX_BARS=auto();MAX_ELAPSED_RESEARCH_TIME=auto();SESSION_END=auto();TRADING_DAY_END=auto();STRATEGY_DEFINED=auto()
class RegimeExitAction(Enum):IGNORE=auto();REDUCE=auto();FULL_EXIT=auto()
class SameBarPolicy(Enum):INVALIDATION_FIRST=auto();AMBIGUOUS_NO_RESULT=auto();USE_HIGHER_RESOLUTION_IF_AUTHORITATIVE=auto()
class MultiTargetPolicy(Enum):PROCESS_IN_ORDER=auto();COMBINE=auto();AMBIGUOUS=auto()
class ResidualPolicy(Enum):CLOSE_REMAINDER=auto();RETAIN_IF_VALID=auto()
class ExitReason(Enum):TARGET=auto();STRUCTURAL_TARGET=auto();R_TARGET=auto();TIME=auto();REGIME_CHANGE=auto();THESIS_INVALIDATED=auto();DATA_PROTECTION=auto();EXPIRED=auto();UNKNOWN=auto()
class ExitHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();INCOMPLETE=auto();BLOCKED=auto();INVALID=auto();UNKNOWN=auto()
class ExitEligibility(Enum):ELIGIBLE=auto();ELIGIBLE_WITH_RESTRICTIONS=auto();NOT_ELIGIBLE=auto();BLOCKED=auto();INCOMPLETE=auto();UNKNOWN=auto()
class EventResolution(Enum):RESOLVED=auto();AMBIGUOUS=auto();NO_EVENT=auto();REJECTED=auto()

@dataclass(frozen=True)
class ExitStagePolicy:
    stage_index:int;method:TargetMethod;exit_fraction:Decimal;trigger_policy:TriggerPolicy=TriggerPolicy.CLOSE_AT_OR_BEYOND;r_multiple:Decimal|None=None

@dataclass(frozen=True)
class ExitPolicy:
    policy_id:str;policy_version:str;strategy_family:str;strategy_variant:str|None;stages:tuple[ExitStagePolicy,...]
    selection_policy:TargetSelectionPolicy=TargetSelectionPolicy.R_MULTIPLE_FIRST;duplicate_policy:DuplicateTargetPolicy=DuplicateTargetPolicy.MERGE
    runner_policy:RunnerPolicy=RunnerPolicy.NO_RUNNER;runner_fraction:Decimal=ZERO;time_exit_method:TimeExitMethod=TimeExitMethod.NONE
    maximum_bars:int|None=None;maximum_elapsed_seconds:int|None=None;regime_exit_action:RegimeExitAction=RegimeExitAction.FULL_EXIT
    starting_trading_day_id:str|None=None
    fallback_methods:tuple[TargetMethod,...]=();configuration_snapshot_id:str="EXIT_DEFAULT_RESEARCH"
    def validate(self,maximum_stages=16):
        errors=[];indexes=[x.stage_index for x in self.stages]
        if not self.policy_id or not self.policy_version:errors.append("EXIT_POLICY_IDENTITY_INVALID")
        if len(self.stages)>maximum_stages or len(indexes)!=len(set(indexes)) or indexes!=sorted(indexes) or any(i<1 for i in indexes):errors.append("EXIT_STAGE_CONFIGURATION_INVALID")
        try:
            fractions=tuple(_decimal(x.exit_fraction) for x in self.stages);runner=_decimal(self.runner_fraction)
            if any(x<ZERO or x>ONE for x in fractions) or runner<ZERO or runner>ONE or sum(fractions,runner)>ONE:errors.append("EXIT_FRACTION_INVALID")
            for stage in self.stages:
                if stage.method is TargetMethod.FIXED_R and (stage.r_multiple is None or _decimal(stage.r_multiple)<=0):errors.append("EXIT_R_MULTIPLE_INVALID")
        except ValueError:errors.append("EXIT_NUMERICAL_INVALID")
        if self.runner_policy is RunnerPolicy.NO_RUNNER and runner!=ZERO:errors.append("EXIT_RUNNER_INCONSISTENT")
        if self.runner_policy is not RunnerPolicy.NO_RUNNER and sum(fractions,runner)!=ONE:errors.append("EXIT_UNOWNED_EXPOSURE")
        if self.time_exit_method is TimeExitMethod.MAX_BARS and (self.maximum_bars is None or self.maximum_bars<1):errors.append("EXIT_TIME_POLICY_INVALID")
        if self.time_exit_method is TimeExitMethod.MAX_ELAPSED_RESEARCH_TIME and (self.maximum_elapsed_seconds is None or self.maximum_elapsed_seconds<1):errors.append("EXIT_TIME_POLICY_INVALID")
        return tuple(dict.fromkeys(errors))

@dataclass(frozen=True)
class ExitManagementConfiguration:
    enabled:bool=True;require_positive_exposure:bool=True;invalidation_precedence:bool=True
    maximum_stages:int=16;duplicate_tolerance:Decimal=Decimal("0.00000001");same_bar_policy:SameBarPolicy=SameBarPolicy.AMBIGUOUS_NO_RESULT
    multi_target_policy:MultiTargetPolicy=MultiTargetPolicy.PROCESS_IN_ORDER;residual_policy:ResidualPolicy=ResidualPolicy.CLOSE_REMAINDER
    exposure_step:Decimal=Decimal("0.01");minimum_residual:Decimal=Decimal("0.01");precision:int=28;tolerance:Decimal=Decimal("0.00000001")
    maximum_plans:int=256;maximum_targets:int=512;maximum_events:int=512;maximum_ledger_entries:int=1024;maximum_cache_entries:int=256
    configuration_snapshot_id:str="EXIT_DEFAULT_RESEARCH"
    def validate(self):
        errors=[]
        try:
            if _decimal(self.duplicate_tolerance)<0 or _decimal(self.exposure_step)<=0 or _decimal(self.minimum_residual)<0 or _decimal(self.tolerance)<0:errors.append("EXIT_NUMERICAL_POLICY_INVALID")
        except ValueError:errors.append("EXIT_NUMERICAL_INVALID")
        if self.maximum_stages<1 or min(self.maximum_plans,self.maximum_targets,self.maximum_events,self.maximum_ledger_entries,self.maximum_cache_entries)<1:errors.append("EXIT_HISTORY_BOUND_INVALID")
        return tuple(errors)

@dataclass(frozen=True)
class StructuralTargetEvidence:
    evidence_id:str;strategy_decision_snapshot_id:str;research_signal_id:str;direction:ResearchDirection;structure_snapshot_id:str;structural_reference_id:str;structural_reference_type:str;target_value:Decimal;confirmed_at_utc:datetime;health:ExitHealth;available:bool;as_of_timestamp_utc:datetime;configuration_snapshot_id:str;dataset_id:str;instrument_id:str;timeframe:str

@dataclass(frozen=True)
class ResearchTargetCandidate:
    target_candidate_id:str;method:TargetMethod;stage_index:int;direction:ResearchDirection;reference_point_id:str;target_reference_id:str;target_value:Decimal;normalized_target_distance:Decimal;normalized_r_multiple:Decimal;evidence_ids:tuple[str,...];health:ExitHealth;available:bool;as_of_timestamp_utc:datetime;configuration_snapshot_id:str

@dataclass(frozen=True)
class ExitStage:
    stage_id:str;stage_index:int;target_candidate_id:str;target_method:TargetMethod;target_value:Decimal;normalized_distance:Decimal;normalized_r:Decimal;exit_fraction:Decimal;remaining_fraction_after_stage:Decimal;trigger_policy:TriggerPolicy;state:TargetState;health:ExitHealth;configuration_snapshot_id:str

@dataclass(frozen=True)
class ResearchExitPlan:
    exit_plan_id:str;logical_plan_id:str;strategy_decision_snapshot_id:str;research_signal_id:str;invalidation_decision_id:str;strategy_id:str;strategy_variant:str|None;direction:ResearchDirection;reference_point_id:str;exit_policy_id:str;stages:tuple[ExitStage,...];runner_policy:RunnerPolicy;runner_fraction:Decimal;time_exit_method:TimeExitMethod;maximum_bars:int|None;maximum_elapsed_seconds:int|None;starting_trading_day_id:str|None;regime_exit_action:RegimeExitAction;initial_simulated_exposure:Decimal;health:ExitHealth;eligibility:ExitEligibility;restrictions:tuple[str,...];reason_codes:tuple[str,...];created_at_utc:datetime;as_of_timestamp_utc:datetime;configuration_snapshot_id:str;exit_engine_version:str;recovery_epoch:int

@dataclass(frozen=True)
class ResearchObservation:
    observation_id:str;observed_at_utc:datetime;available_at_utc:datetime;high:Decimal;low:Decimal;close:Decimal;bar_index:int;dataset_id:str;instrument_id:str;timeframe:str;trading_day_id:str|None=None;session_ended:bool=False

@dataclass(frozen=True)
class ResearchExitEvent:
    exit_event_id:str;exit_plan_id:str;stage_id:str|None;event_type:str;exit_reason:ExitReason;resolution:EventResolution;observed_at_utc:datetime;confirmed_at_utc:datetime;exposure_before:Decimal;exit_fraction:Decimal;exposure_reduced:Decimal;exposure_after:Decimal;observed_research_exit_value:Decimal|None;trigger_evidence:tuple[str,...];health:ExitHealth;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class ResearchExitCompletion:
    completion_id:str;exit_plan_id:str;initial_exposure:Decimal;event_ids:tuple[str,...];terminal_reason:ExitReason;normalized_research_outcome:Decimal|None;completed_at_utc:datetime;health:ExitHealth

@dataclass(frozen=True)
class ExitManagementState:
    exit_plan_id:str;initial_exposure:Decimal;remaining_exposure:Decimal;completed_stage_ids:tuple[str,...];active_stage_ids:tuple[str,...];runner_active:bool;runner_exposure:Decimal;thesis_state:ThesisState;current_normalized_research_outcome:Decimal|None;last_exit_event_id:str|None;as_of_timestamp_utc:datetime;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class ExitPlanResult:
    plan:ResearchExitPlan;state:ExitManagementState;decision_trace:DecisionTrace

@dataclass(frozen=True)
class ExitEvaluationResult:
    state:ExitManagementState;events:tuple[ResearchExitEvent,...];completion:ResearchExitCompletion|None;reason_codes:tuple[str,...]

class ResearchExitLedger:
    def __init__(self,maximum_entries=1024):self.maximum_entries=maximum_entries;self.plans=OrderedDict();self.events=OrderedDict();self.states={};self.completions=OrderedDict()
    def add_plan(self,plan,state):self.plans[plan.exit_plan_id]=plan;self.states[plan.exit_plan_id]=state;self._bound()
    def add_event(self,event,state):
        if event.exit_event_id not in self.events:self.events[event.exit_event_id]=event
        self.states[state.exit_plan_id]=state;self._bound()
    def add_completion(self,item):self.completions[item.completion_id]=item;self._bound()
    def _bound(self):
        while len(self.plans)+len(self.events)+len(self.completions)>self.maximum_entries:
            store=self.events if self.events else self.completions if self.completions else self.plans;store.popitem(last=False)
    def snapshot(self):return {"maximum_entries":self.maximum_entries,"plans":tuple(self.plans.values()),"events":tuple(self.events.values()),"states":dict(self.states),"completions":tuple(self.completions.values())}
    def restore(self,data):
        if data.get("maximum_entries")!=self.maximum_entries:return False
        self.plans=OrderedDict((x.exit_plan_id,x) for x in data.get("plans",()));self.events=OrderedDict((x.exit_event_id,x) for x in data.get("events",()));self.states=dict(data.get("states",{}));self.completions=OrderedDict((x.completion_id,x) for x in data.get("completions",()));return True

class ResearchExitManagementEngine:
    def __init__(self,configuration=ExitManagementConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self.ledger=ResearchExitLedger(configuration.maximum_ledger_entries);self._targets=OrderedDict();self._plans=OrderedDict();self._events=OrderedDict();self._cache=OrderedDict()
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def create_plan(self,snapshot:StrategyDecisionSnapshot,invalidation:ThesisInvalidationDecision,reconciliation:RiskReconciliationResult,reference_value,policy:ExitPolicy,structural_targets:tuple[StructuralTargetEvidence,...]=()):
        cfg=self.configuration;as_of=snapshot.as_of_timestamp_utc;self._record("exit_evaluation_started",{"snapshot_id":snapshot.snapshot_id});errors=list(policy.validate(cfg.maximum_stages));hard=[];reasons=[]
        if errors:raise ValueError(";".join(errors))
        exposure=_decimal(reconciliation.final_simulated_exposure);reference=_decimal(reference_value)
        if not cfg.enabled:hard.append("EXIT_DISABLED")
        if snapshot.outcome not in (ArbitrationOutcome.SINGLE_PREFERRED,ArbitrationOutcome.MULTIPLE_COMPATIBLE) or snapshot.research_availability not in (ResearchAvailability.AVAILABLE,ResearchAvailability.AVAILABLE_WITH_RESTRICTIONS):hard.append("EXIT_UPSTREAM_BLOCKED")
        if invalidation.strategy_decision_snapshot_id!=snapshot.snapshot_id or invalidation.research_signal_id not in ((snapshot.preferred_research_signal_id,)+snapshot.permitted_research_signal_ids):hard.append("EXIT_LINEAGE_MISMATCH")
        if invalidation.eligibility not in (InvalidationEligibility.ELIGIBLE,InvalidationEligibility.ELIGIBLE_WITH_RESTRICTIONS) or invalidation.normalized_distance is None:hard.append("EXIT_INVALIDATION_UNAVAILABLE")
        if cfg.require_positive_exposure and exposure<=0:hard.append("EXIT_NO_POSITIVE_EXPOSURE")
        candidates=[]
        if not hard:
            for stage_policy in policy.stages:
                candidate=self._candidate(stage_policy,invalidation,reference,structural_targets,as_of,snapshot)
                if candidate:candidates.append(candidate)
                else:hard.append(f"EXIT_STAGE_{stage_policy.stage_index}_TARGET_UNAVAILABLE")
        candidates=self._deduplicate(candidates,policy)
        if len(candidates)!=len(policy.stages) and not hard:hard.append("EXIT_STAGE_TARGET_COUNT_INVALID")
        stages=[];remaining=ONE
        for candidate,stage_policy in zip(sorted(candidates,key=lambda x:x.stage_index),policy.stages):
            remaining-=_decimal(stage_policy.exit_fraction);sid=deterministic_id("exit_stage",policy.policy_id,stage_policy.stage_index,candidate.target_candidate_id,str(stage_policy.exit_fraction),cfg.configuration_snapshot_id)
            stages.append(ExitStage(sid,stage_policy.stage_index,candidate.target_candidate_id,candidate.method,candidate.target_value,candidate.normalized_target_distance,candidate.normalized_r_multiple,_decimal(stage_policy.exit_fraction),remaining,stage_policy.trigger_policy,TargetState.ACTIVE,candidate.health,cfg.configuration_snapshot_id))
        blocked=bool(hard);eligibility=ExitEligibility.BLOCKED if blocked else ExitEligibility.ELIGIBLE_WITH_RESTRICTIONS if snapshot.restrictions else ExitEligibility.ELIGIBLE;health=ExitHealth.BLOCKED if blocked else ExitHealth.HEALTHY
        logical=deterministic_id("logical_exit_plan",snapshot.snapshot_id,invalidation.decision_id,policy.policy_id);pid=deterministic_id("research_exit_plan",logical,policy.policy_version,*(x.stage_id for x in stages),str(exposure),cfg.configuration_snapshot_id,EXIT_ENGINE_VERSION)
        reason_codes=tuple(dict.fromkeys(tuple(hard)+(("EXIT_NO_ACTION",) if blocked else ("EXIT_POLICY_SELECTED","EXIT_PLAN_CREATED"))))
        plan=ResearchExitPlan(pid,logical,snapshot.snapshot_id,invalidation.research_signal_id,invalidation.decision_id,invalidation.strategy_id,invalidation.strategy_variant,invalidation.direction,invalidation.reference_point_id,policy.policy_id,tuple(stages),policy.runner_policy,_decimal(policy.runner_fraction),policy.time_exit_method,policy.maximum_bars,policy.maximum_elapsed_seconds,policy.starting_trading_day_id,policy.regime_exit_action,exposure,health,eligibility,tuple(dict.fromkeys(snapshot.restrictions+tuple(hard))),reason_codes,as_of,as_of,cfg.configuration_snapshot_id,EXIT_ENGINE_VERSION,snapshot.recovery_epoch)
        state=ExitManagementState(pid,exposure,exposure,(),tuple(x.stage_id for x in stages),False,ZERO,invalidation.thesis_state,None,None,as_of,cfg.configuration_snapshot_id,snapshot.recovery_epoch)
        status=DecisionStatus.FAILED if blocked else DecisionStatus.PASSED;checks=(DecisionEvaluation("EXIT_PRECONDITIONS",status,reason_codes[0],"Strategy, invalidation and fictional exposure authority validated",(snapshot.snapshot_id,invalidation.decision_id)),DecisionEvaluation("EXIT_TARGETS",status,reason_codes[-1],"Targets, stages, fractions and runner ownership validated",tuple(x.target_candidate_id for x in candidates)))
        trace=DecisionTrace(pid,snapshot.snapshot_id,as_of,checks,DecisionOutcome.NO_ACTION if blocked else DecisionOutcome.ACCEPTED,reason_codes[-1],as_of,"EXIT_PRECONDITIONS" if blocked else None);result=ExitPlanResult(plan,state,trace)
        for x in candidates:self._targets[x.target_candidate_id]=x
        self._plans[pid]=plan;self.ledger.add_plan(plan,state);self._cache[(snapshot.snapshot_id,invalidation.decision_id,policy.policy_id,policy.policy_version,cfg.configuration_snapshot_id)]=result;self._bound();self._record("exit_no_action" if blocked else "exit_plan_created",{"plan_id":pid});return result
    def _candidate(self,stage,invalidation,reference,structural,as_of,snapshot):
        direction=invalidation.direction;distance=invalidation.normalized_distance.normalized_distance
        if stage.method is TargetMethod.FIXED_R:
            multiple=_decimal(stage.r_multiple);target_distance=distance*multiple;target=reference+target_distance if direction is ResearchDirection.BULLISH else reference-target_distance;source=f"R-{multiple}";evidence=(invalidation.normalized_distance.distance_id,)
        else:
            valid=[x for x in structural if x.confirmed_at_utc<=as_of and x.available and x.health in (ExitHealth.HEALTHY,ExitHealth.DEGRADED) and x.strategy_decision_snapshot_id==snapshot.snapshot_id and x.research_signal_id==invalidation.research_signal_id]
            valid=[x for x in valid if (x.target_value>reference if direction is ResearchDirection.BULLISH else x.target_value<reference)]
            if not valid:return None
            item=min(valid,key=lambda x:(abs(x.target_value-reference),x.evidence_id));target=item.target_value;target_distance=abs(target-reference);multiple=target_distance/distance;source=item.structural_reference_id;evidence=(item.evidence_id,)
        if target_distance<=0:return None
        identity=deterministic_id("research_target",stage.stage_index,stage.method.name,direction.name,str(target),str(target_distance),str(multiple),*evidence,self.configuration.configuration_snapshot_id)
        return ResearchTargetCandidate(identity,stage.method,stage.stage_index,direction,invalidation.reference_point_id,source,target,target_distance,multiple,evidence,ExitHealth.HEALTHY,True,as_of,self.configuration.configuration_snapshot_id)
    def _deduplicate(self,candidates,policy):
        result=[]
        for candidate in sorted(candidates,key=lambda x:(x.normalized_target_distance,x.stage_index,x.target_candidate_id)):
            duplicate=next((x for x in result if abs(x.normalized_target_distance-candidate.normalized_target_distance)<=self.configuration.duplicate_tolerance),None)
            if not duplicate:result.append(candidate)
            elif policy.duplicate_policy is DuplicateTargetPolicy.REJECT_AMBIGUOUS:return []
            elif policy.duplicate_policy is DuplicateTargetPolicy.KEEP_HIGHEST_PRIORITY and candidate.stage_index<duplicate.stage_index:result[result.index(duplicate)]=candidate
        return tuple(sorted(result,key=lambda x:x.stage_index))
    def observe(self,plan:ResearchExitPlan,observation:ResearchObservation,invalidation_event:InvalidationEvent|None=None,regime_state="COMPATIBLE",higher_resolution_order:str|None=None):
        state=self.ledger.states.get(plan.exit_plan_id)
        if state is None or state.remaining_exposure<=0:return ExitEvaluationResult(state or self._empty_state(plan,observation.available_at_utc),(),None,("EXIT_EXPOSURE_COMPLETE",))
        if observation.available_at_utc>observation.observed_at_utc:as_of=observation.available_at_utc
        else:as_of=observation.observed_at_utc
        if as_of<plan.as_of_timestamp_utc:return ExitEvaluationResult(state,(),None,("EXIT_FUTURE_OR_PREPLAN_OBSERVATION",))
        active=[x for x in plan.stages if x.stage_id in state.active_stage_ids and x.stage_id not in state.completed_stage_ids];target_hits=[x for x in active if self._hit(x,plan.direction,observation)]
        invalidation_hit=invalidation_event is not None and invalidation_event.confirmed_at_utc<=as_of
        ambiguous=bool(target_hits and invalidation_hit and invalidation_event.observed_at_utc==observation.observed_at_utc)
        if ambiguous and self.configuration.same_bar_policy is SameBarPolicy.AMBIGUOUS_NO_RESULT and not higher_resolution_order:
            event=self._event(plan,None,ExitReason.UNKNOWN,EventResolution.AMBIGUOUS,state.remaining_exposure,ZERO,ZERO,state.remaining_exposure,observation,None,(observation.observation_id,invalidation_event.event_id));self._store_event(event,state);return ExitEvaluationResult(state,(event,),None,("EXIT_SAME_BAR_AMBIGUOUS",))
        if invalidation_hit and (not ambiguous or self.configuration.same_bar_policy is SameBarPolicy.INVALIDATION_FIRST or higher_resolution_order!="TARGET_FIRST"):
            return self._terminal(plan,state,observation,ExitReason.THESIS_INVALIDATED,(invalidation_event.event_id,))
        if regime_state in ("ABNORMAL","UNKNOWN","INCOMPATIBLE") and plan.regime_exit_action is RegimeExitAction.FULL_EXIT:return self._terminal(plan,state,observation,ExitReason.REGIME_CHANGE,(regime_state,))
        if self._time_due(plan,observation):return self._terminal(plan,state,observation,ExitReason.TIME,(observation.observation_id,))
        if not target_hits:return ExitEvaluationResult(replace(state,as_of_timestamp_utc=as_of),(),None,("EXIT_CONTINUE",))
        if self.configuration.multi_target_policy is MultiTargetPolicy.AMBIGUOUS and len(target_hits)>1:return ExitEvaluationResult(state,(),None,("EXIT_MULTI_TARGET_AMBIGUOUS",))
        events=[];current=state
        for stage in sorted(target_hits,key=lambda x:x.stage_index):
            if any(s.stage_index<stage.stage_index and s.stage_id not in current.completed_stage_ids for s in plan.stages):break
            before=current.remaining_exposure;requested=plan.initial_simulated_exposure*stage.exit_fraction;reduced=min(before,self._floor(requested));after=max(ZERO,before-reduced)
            if ZERO<after<self.configuration.minimum_residual and self.configuration.residual_policy is ResidualPolicy.CLOSE_REMAINDER:reduced=before;after=ZERO
            event=self._event(plan,stage,ExitReason.R_TARGET if stage.target_method is TargetMethod.FIXED_R else ExitReason.STRUCTURAL_TARGET,EventResolution.RESOLVED,before,stage.exit_fraction,reduced,after,observation,stage.target_value,(observation.observation_id,stage.target_candidate_id));events.append(event)
            completed=current.completed_stage_ids+(stage.stage_id,);active_ids=tuple(x for x in current.active_stage_ids if x!=stage.stage_id);runner=after>0 and (not active_ids) and plan.runner_policy is not RunnerPolicy.NO_RUNNER;current=ExitManagementState(plan.exit_plan_id,plan.initial_simulated_exposure,after,completed,active_ids,runner,after if runner else ZERO,current.thesis_state,stage.normalized_r,event.exit_event_id,as_of,plan.configuration_snapshot_id,plan.recovery_epoch);self._store_event(event,current)
            if after==0:break
        completion=self._completion(plan,current,events[-1].exit_reason,as_of) if events and current.remaining_exposure==0 else None
        return ExitEvaluationResult(current,tuple(events),completion,("EXIT_EXPOSURE_COMPLETE",) if completion else ("EXIT_PARTIAL_RECORDED",))
    def _hit(self,stage,direction,observation):
        if stage.trigger_policy is TriggerPolicy.TOUCH:return observation.high>=stage.target_value if direction is ResearchDirection.BULLISH else observation.low<=stage.target_value
        return observation.close>=stage.target_value if direction is ResearchDirection.BULLISH else observation.close<=stage.target_value
    def _time_due(self,plan,obs):
        if plan.time_exit_method is TimeExitMethod.NONE:return False
        if plan.time_exit_method is TimeExitMethod.MAX_BARS:return plan.maximum_bars is not None and obs.bar_index>=plan.maximum_bars
        if plan.time_exit_method is TimeExitMethod.MAX_ELAPSED_RESEARCH_TIME:return plan.maximum_elapsed_seconds is not None and (obs.observed_at_utc-plan.created_at_utc).total_seconds()>=plan.maximum_elapsed_seconds
        if plan.time_exit_method is TimeExitMethod.SESSION_END:return obs.session_ended
        if plan.time_exit_method is TimeExitMethod.TRADING_DAY_END:return plan.starting_trading_day_id is not None and obs.trading_day_id is not None and obs.trading_day_id!=plan.starting_trading_day_id
        return False
    def _terminal(self,plan,state,observation,reason,evidence):
        event=self._event(plan,None,reason,EventResolution.RESOLVED,state.remaining_exposure,ONE,state.remaining_exposure,ZERO,observation,observation.close,tuple(evidence));new=ExitManagementState(plan.exit_plan_id,plan.initial_simulated_exposure,ZERO,state.completed_stage_ids,(),False,ZERO,ThesisState.THESIS_INVALIDATED if reason is ExitReason.THESIS_INVALIDATED else state.thesis_state,state.current_normalized_research_outcome,event.exit_event_id,observation.available_at_utc,plan.configuration_snapshot_id,plan.recovery_epoch);self._store_event(event,new);completion=self._completion(plan,new,reason,observation.available_at_utc);return ExitEvaluationResult(new,(event,),completion,(f"EXIT_{reason.name}","EXIT_EXPOSURE_COMPLETE"))
    def _event(self,plan,stage,reason,resolution,before,fraction,reduced,after,observation,value,evidence):
        identity=deterministic_id("research_exit_event",plan.exit_plan_id,stage.stage_id if stage else "TERMINAL",reason.name,resolution.name,observation.observation_id,str(before),str(reduced),str(after))
        return ResearchExitEvent(identity,plan.exit_plan_id,stage.stage_id if stage else None,"TARGET" if stage else "TERMINAL",reason,resolution,observation.observed_at_utc,observation.available_at_utc,before,_decimal(fraction),reduced,after,value,tuple(evidence),ExitHealth.RESTRICTED if resolution is EventResolution.AMBIGUOUS else ExitHealth.HEALTHY,plan.configuration_snapshot_id,plan.recovery_epoch)
    def _store_event(self,event,state):self._events[event.exit_event_id]=event;self.ledger.add_event(event,state);self._bound();self._record("same_bar_ambiguity_detected" if event.resolution is EventResolution.AMBIGUOUS else "partial_exit_recorded",{"event_id":event.exit_event_id})
    def _completion(self,plan,state,reason,at):
        event_ids=tuple(x.exit_event_id for x in self.ledger.events.values() if x.exit_plan_id==plan.exit_plan_id);identity=deterministic_id("research_exit_completion",plan.exit_plan_id,*event_ids,reason.name);item=ResearchExitCompletion(identity,plan.exit_plan_id,plan.initial_simulated_exposure,event_ids,reason,state.current_normalized_research_outcome,at,ExitHealth.HEALTHY);self.ledger.add_completion(item);return item
    def _floor(self,value):
        step=_decimal(self.configuration.exposure_step)
        with localcontext() as ctx:ctx.prec=self.configuration.precision;return (_decimal(value)/step).to_integral_value(rounding=ROUND_FLOOR)*step
    def _empty_state(self,plan,at):return ExitManagementState(plan.exit_plan_id,plan.initial_simulated_exposure,ZERO,(),(),False,ZERO,ThesisState.THESIS_WEAKENING,None,None,at,plan.configuration_snapshot_id,plan.recovery_epoch)
    def _bound(self):
        for store,limit in ((self._targets,self.configuration.maximum_targets),(self._plans,self.configuration.maximum_plans),(self._events,self.configuration.maximum_events),(self._cache,self.configuration.maximum_cache_entries)):
            while len(store)>limit:store.popitem(last=False)
    def recovery_state(self):return {"engine_version":EXIT_ENGINE_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"ledger":self.ledger.snapshot(),"last_plan_id":next(reversed(self._plans),None)}
    def restore(self,state):return self.validate_recovery(state) and self.ledger.restore(state.get("ledger",{}))
    def validate_recovery(self,state):return state.get("engine_version")==EXIT_ENGINE_VERSION and state.get("configuration_snapshot_id")==self.configuration.configuration_snapshot_id
