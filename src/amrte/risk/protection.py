"""Point-in-time-safe protective-boundary research; never broker instructions."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass,replace
from datetime import datetime,timedelta
from decimal import Decimal
from enum import Enum,auto

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace
from amrte.risk.sizing import _decimal
from amrte.risk.invalidation import ResearchDirection,ThesisInvalidationDecision,ThesisState
from amrte.risk.exit_management import ExitManagementState,ResearchExitPlan,ResearchObservation
from amrte.strategies.strategy_arbitration import StrategyDecisionSnapshot

PROTECTION_ENGINE_VERSION="1.0";ZERO=Decimal("0")

class ActivationMethod(Enum):NORMALIZED_R=auto();TARGET_STAGE_COMPLETION=auto();STRUCTURAL_PROGRESS=auto();BREAK_EVEN_ACTIVATED=auto();RUNNER_ACTIVATED=auto();STRATEGY_DEFINED=auto()
class OffsetMethod(Enum):NONE=auto();NORMALIZED_FIXED=auto();ATR_NORMALIZED=auto();RESEARCH_FRICTION_AWARE=auto();STRATEGY_DEFINED=auto()
class TrailingMethod(Enum):ATR_TRAILING=auto();STRUCTURE_TRAILING=auto();R_BASED_TRAILING=auto();HYBRID_TRAILING=auto();CUSTOM_REGISTERED=auto()
class RTrailingPolicy(Enum):STEP_R=auto();LOCK_R=auto();DISTANCE_BEHIND_FAVORABLE_R=auto();STAGE_BASED_R=auto()
class HybridPolicy(Enum):MOST_PROTECTIVE_VALID=auto();LEAST_AGGRESSIVE_VALID=auto();STRUCTURE_PRIORITY=auto();ATR_PRIORITY=auto();R_PRIORITY=auto();CONSENSUS_REQUIRED=auto();STRATEGY_DEFINED=auto()
class ManagementMode(Enum):ORIGINAL_INVALIDATION=auto();BREAK_EVEN=auto();ATR_TRAILING=auto();STRUCTURE_TRAILING=auto();R_TRAILING=auto();HYBRID_TRAILING=auto();TERMINATED=auto();UNKNOWN=auto()
class ProtectionHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();INCOMPLETE=auto();BLOCKED=auto();INVALID=auto();UNKNOWN=auto()
class ProtectionEligibility(Enum):ELIGIBLE=auto();ELIGIBLE_WITH_RESTRICTIONS=auto();NOT_ELIGIBLE=auto();BLOCKED=auto();INCOMPLETE=auto();UNKNOWN=auto()
class BreakEvenState(Enum):NOT_ELIGIBLE=auto();WAITING=auto();ACTIVATION_PENDING=auto();ELIGIBLE=auto();ACTIVATED=auto();SUPERSEDED_BY_TRAILING=auto();TERMINATED=auto();BLOCKED=auto();UNKNOWN=auto()
class TrailingState(Enum):INACTIVE=auto();WAITING_FOR_ACTIVATION=auto();ACTIVE=auto();UPDATE_PENDING=auto();UPDATED=auto();FROZEN=auto();TERMINATED=auto();BLOCKED=auto();UNKNOWN=auto()
class TriggerPolicy(Enum):TOUCH=auto();CLOSE_AT_OR_BEYOND=auto();MULTI_CLOSE=auto();STRUCTURAL_CONFIRMATION=auto();STRATEGY_DEFINED=auto()
class SameBarTrailPolicy(Enum):AMBIGUOUS_NO_RESULT=auto();USE_PRIOR_ACTIVE_BOUNDARY=auto();USE_HIGHER_RESOLUTION_IF_AUTHORITATIVE=auto();CONSERVATIVE_TERMINATION=auto()
class ProtectiveExitReason(Enum):BREAK_EVEN_BOUNDARY=auto();ATR_TRAILING_BOUNDARY=auto();STRUCTURE_TRAILING_BOUNDARY=auto();R_TRAILING_BOUNDARY=auto();HYBRID_TRAILING_BOUNDARY=auto();PROMPT19_INVALIDATION=auto();PROMPT20_EXIT=auto();DATA_PROTECTION=auto();UNKNOWN=auto()

@dataclass(frozen=True)
class RStep:
    activation_r:Decimal;locked_r:Decimal

@dataclass(frozen=True)
class ProtectionProfile:
    profile_id:str;profile_version:str;strategy_family:str;strategy_variant:str|None=None
    break_even_enabled:bool=True;break_even_activation:ActivationMethod=ActivationMethod.NORMALIZED_R;break_even_threshold:Decimal=Decimal("1")
    break_even_stage_id:str|None=None;offset_method:OffsetMethod=OffsetMethod.NONE;offset_value:Decimal=ZERO;break_even_one_time:bool=True
    trailing_enabled:bool=True;trailing_activation:ActivationMethod=ActivationMethod.BREAK_EVEN_ACTIVATED;trailing_threshold:Decimal=Decimal("1")
    trailing_methods:tuple[TrailingMethod,...]=(TrailingMethod.R_BASED_TRAILING,);atr_multiplier:Decimal=Decimal("2");r_steps:tuple[RStep,...]=(RStep(Decimal("2"),Decimal("1")),)
    hybrid_policy:HybridPolicy=HybridPolicy.MOST_PROTECTIVE_VALID;trigger_policy:TriggerPolicy=TriggerPolicy.CLOSE_AT_OR_BEYOND
    minimum_improvement:Decimal=Decimal("0.01");minimum_noise_distance:Decimal=ZERO;cooldown_seconds:int=0;configuration_snapshot_id:str="PROTECTION_DEFAULT_RESEARCH"
    def validate(self):
        errors=[]
        try:
            values=(self.break_even_threshold,self.offset_value,self.trailing_threshold,self.atr_multiplier,self.minimum_improvement,self.minimum_noise_distance)
            if any(not _decimal(x).is_finite() or _decimal(x)<0 for x in values):errors.append("PROTECTION_NUMERICAL_INVALID")
            if self.break_even_enabled and self.break_even_activation is ActivationMethod.NORMALIZED_R and _decimal(self.break_even_threshold)<=0:errors.append("BE_THRESHOLD_INVALID")
            if TrailingMethod.ATR_TRAILING in self.trailing_methods and _decimal(self.atr_multiplier)<=0:errors.append("TRAIL_ATR_MULTIPLIER_INVALID")
            previous_a=previous_l=None
            for step in sorted(self.r_steps,key=lambda x:x.activation_r):
                a=_decimal(step.activation_r);l=_decimal(step.locked_r)
                if not a.is_finite() or not l.is_finite() or a<=0 or (previous_a is not None and (a<=previous_a or l<previous_l)):errors.append("TRAIL_R_SCHEDULE_INVALID")
                previous_a,previous_l=a,l
        except (ValueError,ArithmeticError):errors.append("PROTECTION_NUMERICAL_INVALID")
        if not self.profile_id or not self.profile_version:errors.append("PROTECTION_PROFILE_IDENTITY_INVALID")
        return tuple(dict.fromkeys(errors))

@dataclass(frozen=True)
class ProtectionConfiguration:
    enabled:bool=True;never_loosen:bool=True;closed_observation_only:bool=True;same_bar_policy:SameBarTrailPolicy=SameBarTrailPolicy.USE_PRIOR_ACTIVE_BOUNDARY
    tolerance:Decimal=Decimal("0.00000001");maximum_candidates:int=512;maximum_versions:int=512;maximum_events:int=512;maximum_ledger_entries:int=1024;maximum_cache_entries:int=256
    configuration_snapshot_id:str="PROTECTION_DEFAULT_RESEARCH"
    def validate(self):
        errors=[]
        try:
            if not _decimal(self.tolerance).is_finite() or _decimal(self.tolerance)<0:errors.append("PROTECTION_TOLERANCE_INVALID")
        except ValueError:errors.append("PROTECTION_TOLERANCE_INVALID")
        if min(self.maximum_candidates,self.maximum_versions,self.maximum_events,self.maximum_ledger_entries,self.maximum_cache_entries)<1:errors.append("PROTECTION_BOUND_INVALID")
        return tuple(errors)

@dataclass(frozen=True)
class ProtectionActivationEvidence:
    evidence_id:str;method:ActivationMethod;source_ids:tuple[str,...];qualified:bool;favorable_r:Decimal;available_at_utc:datetime;dataset_id:str;instrument_id:str;timeframe:str;health:ProtectionHealth

@dataclass(frozen=True)
class ATRTrailEvidence:
    evidence_id:str;atr_value:Decimal;reference_value:Decimal;available_at_utc:datetime;dataset_id:str;instrument_id:str;timeframe:str;health:ProtectionHealth

@dataclass(frozen=True)
class StructureTrailEvidence:
    evidence_id:str;boundary_value:Decimal;confirmed_at_utc:datetime;dataset_id:str;instrument_id:str;timeframe:str;health:ProtectionHealth;confirmed:bool=True

@dataclass(frozen=True)
class BreakEvenCandidate:
    candidate_id:str;strategy_decision_snapshot_id:str;exit_plan_id:str;direction:ResearchDirection;activation_method:ActivationMethod;activation_evidence_ids:tuple[str,...];reference_point_id:str;offset_method:OffsetMethod;offset_evidence_ids:tuple[str,...];candidate_boundary:Decimal;health:ProtectionHealth;eligibility:ProtectionEligibility;as_of_timestamp_utc:datetime;configuration_snapshot_id:str

@dataclass(frozen=True)
class TrailingBoundaryCandidate:
    candidate_id:str;method:TrailingMethod;strategy_decision_snapshot_id:str;exit_plan_id:str;direction:ResearchDirection;reference_id:str;evidence_ids:tuple[str,...];candidate_boundary:Decimal;normalized_protection_distance:Decimal;normalized_locked_r:Decimal;health:ProtectionHealth;eligibility:ProtectionEligibility;as_of_timestamp_utc:datetime;configuration_snapshot_id:str

@dataclass(frozen=True)
class ProtectiveBoundaryVersion:
    logical_boundary_id:str;boundary_version_id:str;parent_version_id:str|None;original_invalidation_decision_id:str;original_boundary:Decimal;method:ManagementMode;value:Decimal;activation_evidence_ids:tuple[str,...];update_evidence_ids:tuple[str,...];created_at_utc:datetime;effective_at_utc:datetime;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class ProtectiveBoundaryDecision:
    decision_id:str;strategy_decision_snapshot_id:str;research_signal_id:str;invalidation_decision_id:str;exit_plan_id:str;direction:ResearchDirection;previous_boundary_id:str|None;original_invalidation_boundary_id:str;management_mode:ManagementMode;break_even_candidate_id:str|None;trailing_candidate_ids:tuple[str,...];selected_candidate_id:str|None;new_protective_boundary:Decimal;protection_improvement:Decimal;normalized_locked_r:Decimal;remaining_exposure:Decimal;health:ProtectionHealth;eligibility:ProtectionEligibility;restrictions:tuple[str,...];reason_codes:tuple[str,...];as_of_timestamp_utc:datetime;configuration_snapshot_id:str;engine_version:str;recovery_epoch:int

@dataclass(frozen=True)
class ProtectiveBoundaryEvent:
    event_id:str;boundary_version_id:str;exit_plan_id:str;reason:ProtectiveExitReason;observed_at_utc:datetime;confirmed_at_utc:datetime;boundary_value:Decimal;remaining_exposure_before:Decimal;remaining_exposure_after:Decimal;observation_ids:tuple[str,...];health:ProtectionHealth;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class ProtectiveManagementState:
    exit_plan_id:str;current_boundary_version_id:str;current_boundary:Decimal;original_boundary:Decimal;remaining_exposure:Decimal;break_even_state:BreakEvenState;trailing_state:TrailingState;last_update_at_utc:datetime;last_event_id:str|None;terminated:bool;runner_active:bool;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class ProtectionEvaluationResult:
    decision:ProtectiveBoundaryDecision;state:ProtectiveManagementState;version:ProtectiveBoundaryVersion|None;candidates:tuple[BreakEvenCandidate|TrailingBoundaryCandidate,...];rejected_candidate_ids:tuple[str,...];decision_trace:DecisionTrace

class ProtectiveBoundaryLedger:
    def __init__(self,maximum_entries=1024):self.maximum_entries=maximum_entries;self.versions=OrderedDict();self.events=OrderedDict();self.states={}
    def add_version(self,version,state):self.versions[version.boundary_version_id]=version;self.states[state.exit_plan_id]=state;self._bound()
    def add_event(self,event,state):self.events.setdefault(event.event_id,event);self.states[state.exit_plan_id]=state;self._bound()
    def _bound(self):
        while len(self.versions)+len(self.events)>self.maximum_entries:(self.events if self.events else self.versions).popitem(last=False)
    def snapshot(self):return {"maximum_entries":self.maximum_entries,"versions":tuple(self.versions.values()),"events":tuple(self.events.values()),"states":dict(self.states)}
    def restore(self,data):
        if data.get("maximum_entries")!=self.maximum_entries:return False
        versions=tuple(data.get("versions",()));states=dict(data.get("states",{}))
        for plan_id,state in states.items():
            chain=[x for x in versions if x.boundary_version_id==state.current_boundary_version_id]
            if not chain or chain[0].value!=state.current_boundary:return False
        self.versions=OrderedDict((x.boundary_version_id,x) for x in versions);self.events=OrderedDict((x.event_id,x) for x in data.get("events",()));self.states=states;return True

class ProtectiveBoundaryEngine:
    def __init__(self,configuration=ProtectionConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self.ledger=ProtectiveBoundaryLedger(configuration.maximum_ledger_entries);self._candidates=OrderedDict();self._decisions=OrderedDict();self._versions=OrderedDict();self._events=OrderedDict();self._cache=OrderedDict()
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def initialize(self,snapshot:StrategyDecisionSnapshot,invalidation:ThesisInvalidationDecision,plan:ResearchExitPlan,state:ExitManagementState,profile:ProtectionProfile,reference_value,dataset_id="DATASET-A",timeframe="H1"):
        errors=profile.validate()
        if errors:raise ValueError(";".join(errors))
        as_of=max(snapshot.as_of_timestamp_utc,state.as_of_timestamp_utc);original=invalidation.research_invalidation_boundary;hard=[]
        if not self.configuration.enabled:hard.append("PROTECTION_DISABLED")
        if original is None or invalidation.strategy_decision_snapshot_id!=snapshot.snapshot_id or plan.strategy_decision_snapshot_id!=snapshot.snapshot_id or plan.invalidation_decision_id!=invalidation.decision_id or state.exit_plan_id!=plan.exit_plan_id:hard.append("TRAIL_LINEAGE_MISMATCH")
        if state.remaining_exposure<=0:hard.append("TRAIL_NO_REMAINING_EXPOSURE")
        logical=deterministic_id("protective_boundary",snapshot.snapshot_id,invalidation.decision_id,plan.exit_plan_id,profile.profile_id)
        version_id=deterministic_id("protective_boundary_version",logical,"ORIGINAL",str(original),profile.configuration_snapshot_id)
        version=None if original is None else ProtectiveBoundaryVersion(logical,version_id,None,invalidation.decision_id,original,ManagementMode.ORIGINAL_INVALIDATION,original,(invalidation.decision_id,),(),as_of,as_of,profile.configuration_snapshot_id,snapshot.recovery_epoch)
        current=original if original is not None else ZERO;elig=ProtectionEligibility.BLOCKED if hard else ProtectionEligibility.ELIGIBLE;health=ProtectionHealth.BLOCKED if hard else ProtectionHealth.HEALTHY
        pstate=ProtectiveManagementState(plan.exit_plan_id,version_id,current,current,state.remaining_exposure,BreakEvenState.BLOCKED if hard else BreakEvenState.WAITING,TrailingState.BLOCKED if hard else TrailingState.WAITING_FOR_ACTIVATION,as_of,None,bool(hard),state.runner_active,profile.configuration_snapshot_id,snapshot.recovery_epoch)
        if version:self.ledger.add_version(version,pstate);self._versions[version_id]=version
        decision=self._decision(snapshot,invalidation,plan,pstate,ManagementMode.ORIGINAL_INVALIDATION,None,(),None,current,ZERO,ZERO,health,elig,tuple(hard) or ("PROTECTION_INITIALIZED",),as_of)
        trace=self._trace(decision,snapshot,tuple(hard),version_id)
        return ProtectionEvaluationResult(decision,pstate,version,(),(),trace)
    def evaluate(self,snapshot,invalidation,plan,exit_state,profile,reference_value,observation:ResearchObservation,activation:ProtectionActivationEvidence|None=None,atr:ATRTrailEvidence|None=None,structure:StructureTrailEvidence|None=None):
        errors=profile.validate()
        if errors:raise ValueError(";".join(errors))
        current=self.ledger.states.get(plan.exit_plan_id)
        if current is None:return self.initialize(snapshot,invalidation,plan,exit_state,profile,reference_value,observation.dataset_id,observation.timeframe)
        as_of=observation.available_at_utc;hard=[];rejected=[];candidates=[];reasons=[]
        if current.terminated or exit_state.remaining_exposure<=0:hard.append("TRAIL_NO_REMAINING_EXPOSURE")
        if exit_state.exit_plan_id!=plan.exit_plan_id or plan.invalidation_decision_id!=invalidation.decision_id or observation.instrument_id!=snapshot.instrument_id or exit_state.remaining_exposure>current.remaining_exposure:hard.append("TRAIL_LINEAGE_MISMATCH")
        if observation.available_at_utc<observation.observed_at_utc:hard.append("TRAIL_TEMPORAL_INVALID")
        distance=invalidation.normalized_distance.normalized_distance if invalidation.normalized_distance else ZERO;reference=_decimal(reference_value)
        favorable_r=((observation.close-reference) if invalidation.direction is ResearchDirection.BULLISH else (reference-observation.close))/distance if distance>0 else ZERO
        qualified=self._activation(profile.break_even_activation,profile.break_even_threshold,profile.break_even_stage_id,activation,exit_state,current,favorable_r)
        be=None
        if not hard and profile.break_even_enabled and qualified and current.break_even_state is not BreakEvenState.ACTIVATED:
            offset=self._offset(profile,atr,as_of)
            if offset is not None:
                boundary=reference+offset if invalidation.direction is ResearchDirection.BULLISH else reference-offset
                be=BreakEvenCandidate(deterministic_id("break_even_candidate",snapshot.snapshot_id,plan.exit_plan_id,str(boundary),as_of.isoformat()),snapshot.snapshot_id,plan.exit_plan_id,invalidation.direction,profile.break_even_activation,(activation.evidence_id,) if activation else (observation.observation_id,),invalidation.reference_point_id,profile.offset_method,(atr.evidence_id,) if atr and profile.offset_method is OffsetMethod.ATR_NORMALIZED else (),boundary,ProtectionHealth.HEALTHY,ProtectionEligibility.ELIGIBLE,as_of,profile.configuration_snapshot_id);candidates.append(be)
            else:reasons.append("BE_OFFSET_INVALID")
        trail_active=profile.trailing_enabled and self._activation(profile.trailing_activation,profile.trailing_threshold,None,activation,exit_state,current,favorable_r)
        if not hard and trail_active:
            for method in profile.trailing_methods:
                item=self._trail_candidate(method,snapshot,invalidation,plan,profile,current,reference,observation,favorable_r,atr,structure)
                if item:candidates.append(item)
        valid=[]
        for item in candidates:
            value=item.candidate_boundary
            improvement=value-current.current_boundary if invalidation.direction is ResearchDirection.BULLISH else current.current_boundary-value
            if improvement<profile.minimum_improvement or not self._protective(value,current.current_boundary,invalidation.direction):rejected.append(item.candidate_id);reasons.append("TRAIL_LOOSENING_REJECTED" if improvement<0 else "TRAIL_UPDATE_TOO_SMALL")
            elif self._hit_value(observation,value,invalidation.direction,profile.trigger_policy) and as_of==item.as_of_timestamp_utc:rejected.append(item.candidate_id);reasons.append("TRAIL_SAME_BAR_USE_PRIOR_BOUNDARY")
            else:valid.append(item)
        if profile.cooldown_seconds and as_of<current.last_update_at_utc+timedelta(seconds=profile.cooldown_seconds):rejected.extend(x.candidate_id for x in valid);valid=[];reasons.append("TRAIL_COOLDOWN_ACTIVE")
        selected=self._select(valid,profile.hybrid_policy,invalidation.direction)
        if hard or selected is None:
            decision=self._decision(snapshot,invalidation,plan,current,ManagementMode.ORIGINAL_INVALIDATION,None,tuple(x.candidate_id for x in candidates if isinstance(x,TrailingBoundaryCandidate)),None,current.current_boundary,ZERO,self._locked(reference,current.current_boundary,distance,invalidation.direction),ProtectionHealth.BLOCKED if hard else ProtectionHealth.HEALTHY,ProtectionEligibility.BLOCKED if hard else ProtectionEligibility.ELIGIBLE,tuple(hard+reasons) or ("TRAIL_NO_ACTION",),as_of)
            new_state=replace(current,remaining_exposure=exit_state.remaining_exposure,runner_active=exit_state.runner_active)
            trace=self._trace(decision,snapshot,tuple(hard+reasons),current.current_boundary_version_id);self._record("protective_no_action",{"decision_id":decision.decision_id});return ProtectionEvaluationResult(decision,new_state,None,tuple(candidates),tuple(rejected),trace)
        value=selected.candidate_boundary;mode=ManagementMode.BREAK_EVEN if isinstance(selected,BreakEvenCandidate) else {TrailingMethod.ATR_TRAILING:ManagementMode.ATR_TRAILING,TrailingMethod.STRUCTURE_TRAILING:ManagementMode.STRUCTURE_TRAILING,TrailingMethod.R_BASED_TRAILING:ManagementMode.R_TRAILING,TrailingMethod.HYBRID_TRAILING:ManagementMode.HYBRID_TRAILING}.get(selected.method,ManagementMode.UNKNOWN)
        improvement=value-current.current_boundary if invalidation.direction is ResearchDirection.BULLISH else current.current_boundary-value;locked=self._locked(reference,value,distance,invalidation.direction)
        parent=current.current_boundary_version_id;logical=self._versions[parent].logical_boundary_id;vid=deterministic_id("protective_boundary_version",logical,parent,selected.candidate_id,str(value),as_of.isoformat(),profile.configuration_snapshot_id)
        version=ProtectiveBoundaryVersion(logical,vid,parent,invalidation.decision_id,current.original_boundary,mode,value,selected.activation_evidence_ids if isinstance(selected,BreakEvenCandidate) else (),selected.evidence_ids if isinstance(selected,TrailingBoundaryCandidate) else (),as_of,as_of,profile.configuration_snapshot_id,snapshot.recovery_epoch)
        new_state=ProtectiveManagementState(plan.exit_plan_id,vid,value,current.original_boundary,exit_state.remaining_exposure,BreakEvenState.ACTIVATED if mode is ManagementMode.BREAK_EVEN else current.break_even_state,TrailingState.UPDATED if mode not in (ManagementMode.BREAK_EVEN,ManagementMode.ORIGINAL_INVALIDATION) else current.trailing_state,as_of,current.last_event_id,False,exit_state.runner_active,profile.configuration_snapshot_id,snapshot.recovery_epoch)
        decision=self._decision(snapshot,invalidation,plan,new_state,mode,be.candidate_id if be else None,tuple(x.candidate_id for x in candidates if isinstance(x,TrailingBoundaryCandidate)),selected.candidate_id,value,improvement,locked,ProtectionHealth.HEALTHY,ProtectionEligibility.ELIGIBLE,("BE_ACTIVATED",) if mode is ManagementMode.BREAK_EVEN else ("TRAIL_BOUNDARY_ADVANCED",),as_of)
        self._versions[vid]=version;self.ledger.add_version(version,new_state);self._decisions[decision.decision_id]=decision;self._bound();self._record("protective_boundary_advanced",{"boundary_version_id":vid});return ProtectionEvaluationResult(decision,new_state,version,tuple(candidates),tuple(rejected),self._trace(decision,snapshot,(),vid))
    def observe(self,plan,state,observation,direction,trigger_policy=TriggerPolicy.CLOSE_AT_OR_BEYOND):
        if state.terminated or state.remaining_exposure<=0:return None,state
        hit=self._hit_value(observation,state.current_boundary,direction,trigger_policy)
        if not hit:return None,state
        version=self._versions.get(state.current_boundary_version_id);mode=version.method if version else ManagementMode.UNKNOWN
        reason={ManagementMode.BREAK_EVEN:ProtectiveExitReason.BREAK_EVEN_BOUNDARY,ManagementMode.ATR_TRAILING:ProtectiveExitReason.ATR_TRAILING_BOUNDARY,ManagementMode.STRUCTURE_TRAILING:ProtectiveExitReason.STRUCTURE_TRAILING_BOUNDARY,ManagementMode.R_TRAILING:ProtectiveExitReason.R_TRAILING_BOUNDARY,ManagementMode.HYBRID_TRAILING:ProtectiveExitReason.HYBRID_TRAILING_BOUNDARY}.get(mode,ProtectiveExitReason.PROMPT19_INVALIDATION)
        eid=deterministic_id("protective_boundary_event",state.current_boundary_version_id,observation.observation_id,reason.name,str(state.remaining_exposure))
        event=ProtectiveBoundaryEvent(eid,state.current_boundary_version_id,plan.exit_plan_id,reason,observation.observed_at_utc,observation.available_at_utc,state.current_boundary,state.remaining_exposure,ZERO,(observation.observation_id,),ProtectionHealth.HEALTHY,state.configuration_snapshot_id,state.recovery_epoch)
        new=replace(state,remaining_exposure=ZERO,last_event_id=eid,terminated=True,break_even_state=BreakEvenState.TERMINATED,trailing_state=TrailingState.TERMINATED,last_update_at_utc=observation.available_at_utc);self._events[eid]=event;self.ledger.add_event(event,new);self._bound();self._record("protective_boundary_triggered",{"event_id":eid});return event,new
    def _activation(self,method,threshold,stage_id,evidence,exit_state,current,favorable_r):
        if method is ActivationMethod.NORMALIZED_R:return favorable_r>=_decimal(threshold)
        if method is ActivationMethod.TARGET_STAGE_COMPLETION:return bool(exit_state.completed_stage_ids) if stage_id is None else stage_id in exit_state.completed_stage_ids
        if method is ActivationMethod.RUNNER_ACTIVATED:return exit_state.runner_active
        if method is ActivationMethod.BREAK_EVEN_ACTIVATED:return current.break_even_state is BreakEvenState.ACTIVATED
        return bool(evidence and evidence.qualified and evidence.health in (ProtectionHealth.HEALTHY,ProtectionHealth.DEGRADED))
    def _offset(self,profile,atr,as_of):
        if profile.offset_method is OffsetMethod.NONE:return ZERO
        if profile.offset_method is OffsetMethod.NORMALIZED_FIXED:return _decimal(profile.offset_value)
        if profile.offset_method is OffsetMethod.ATR_NORMALIZED and atr and atr.available_at_utc<=as_of and atr.health is ProtectionHealth.HEALTHY and atr.atr_value>0:return atr.atr_value*_decimal(profile.offset_value)
        return None
    def _trail_candidate(self,method,snapshot,invalidation,plan,profile,current,reference,observation,favorable_r,atr,structure):
        direction=invalidation.direction;distance=invalidation.normalized_distance.normalized_distance
        evidence=();locked=ZERO;ref=observation.observation_id
        if method is TrailingMethod.ATR_TRAILING:
            if not atr or atr.available_at_utc>observation.available_at_utc or atr.health is not ProtectionHealth.HEALTHY or atr.atr_value<=0:return None
            boundary=atr.reference_value-atr.atr_value*profile.atr_multiplier if direction is ResearchDirection.BULLISH else atr.reference_value+atr.atr_value*profile.atr_multiplier;evidence=(atr.evidence_id,);ref=atr.evidence_id
        elif method is TrailingMethod.STRUCTURE_TRAILING:
            if not structure or not structure.confirmed or structure.confirmed_at_utc>observation.available_at_utc or structure.health is not ProtectionHealth.HEALTHY:return None
            boundary=structure.boundary_value;evidence=(structure.evidence_id,);ref=structure.evidence_id
        elif method is TrailingMethod.R_BASED_TRAILING:
            eligible=[x for x in profile.r_steps if favorable_r>=x.activation_r]
            if not eligible:return None
            step=max(eligible,key=lambda x:x.activation_r);locked=step.locked_r;boundary=reference+locked*distance if direction is ResearchDirection.BULLISH else reference-locked*distance;evidence=(observation.observation_id,)
        else:return None
        nd=boundary-current.current_boundary if direction is ResearchDirection.BULLISH else current.current_boundary-boundary;locked=self._locked(reference,boundary,distance,direction)
        cid=deterministic_id("trailing_candidate",method.name,snapshot.snapshot_id,plan.exit_plan_id,ref,str(boundary),observation.available_at_utc.isoformat(),profile.configuration_snapshot_id)
        return TrailingBoundaryCandidate(cid,method,snapshot.snapshot_id,plan.exit_plan_id,direction,ref,evidence,boundary,nd,locked,ProtectionHealth.HEALTHY,ProtectionEligibility.ELIGIBLE,observation.available_at_utc,profile.configuration_snapshot_id)
    def _select(self,candidates,policy,direction):
        if not candidates:return None
        ordered=sorted(candidates,key=lambda x:(x.candidate_boundary,x.candidate_id),reverse=direction is ResearchDirection.BULLISH)
        if policy is HybridPolicy.LEAST_AGGRESSIVE_VALID:return ordered[-1]
        priorities={HybridPolicy.STRUCTURE_PRIORITY:TrailingMethod.STRUCTURE_TRAILING,HybridPolicy.ATR_PRIORITY:TrailingMethod.ATR_TRAILING,HybridPolicy.R_PRIORITY:TrailingMethod.R_BASED_TRAILING}
        preferred=priorities.get(policy)
        if preferred:
            return next((x for x in ordered if isinstance(x,TrailingBoundaryCandidate) and x.method is preferred),ordered[0])
        if policy is HybridPolicy.CONSENSUS_REQUIRED and len(candidates)<2:return None
        return ordered[0]
    def _protective(self,new,current,direction):return new>=current-self.configuration.tolerance if direction is ResearchDirection.BULLISH else new<=current+self.configuration.tolerance
    def _hit_value(self,obs,boundary,direction,policy):
        value=(obs.low if direction is ResearchDirection.BULLISH else obs.high) if policy is TriggerPolicy.TOUCH else obs.close
        return value<=boundary if direction is ResearchDirection.BULLISH else value>=boundary
    def _locked(self,reference,boundary,distance,direction):return ((boundary-reference) if direction is ResearchDirection.BULLISH else (reference-boundary))/distance if distance>0 else ZERO
    def _decision(self,snapshot,inv,plan,state,mode,be,trails,selected,value,improvement,locked,health,eligibility,reasons,as_of):
        did=deterministic_id("protective_boundary_decision",snapshot.snapshot_id,inv.decision_id,plan.exit_plan_id,state.current_boundary_version_id,selected or "NONE",str(value),as_of.isoformat(),state.configuration_snapshot_id)
        return ProtectiveBoundaryDecision(did,snapshot.snapshot_id,inv.research_signal_id,inv.decision_id,plan.exit_plan_id,inv.direction,state.current_boundary_version_id,inv.selected_candidate_id or inv.decision_id,mode,be,tuple(sorted(trails)),selected,value,improvement,locked,state.remaining_exposure,health,eligibility,(),tuple(reasons),as_of,state.configuration_snapshot_id,PROTECTION_ENGINE_VERSION,state.recovery_epoch)
    def _trace(self,decision,snapshot,errors,evidence):
        status=DecisionStatus.FAILED if errors else DecisionStatus.PASSED;reason=decision.reason_codes[-1];checks=(DecisionEvaluation("PROTECTION_AUTHORITY",status,reason,"Prompt 19 and Prompt 20 lineage and remaining exposure validated",(snapshot.snapshot_id,decision.invalidation_decision_id,decision.exit_plan_id)),DecisionEvaluation("PROTECTION_MONOTONICITY",status,reason,"Point-in-time candidate, monotonicity, cooldown and same-bar gates evaluated",(evidence,)))
        return DecisionTrace(decision.decision_id,snapshot.snapshot_id,decision.as_of_timestamp_utc,checks,DecisionOutcome.NO_ACTION if errors or decision.selected_candidate_id is None else DecisionOutcome.ACCEPTED,reason,decision.as_of_timestamp_utc,"PROTECTION_AUTHORITY" if errors else None)
    def _bound(self):
        for store,limit in ((self._candidates,self.configuration.maximum_candidates),(self._decisions,self.configuration.maximum_versions),(self._versions,self.configuration.maximum_versions),(self._events,self.configuration.maximum_events),(self._cache,self.configuration.maximum_cache_entries)):
            while len(store)>limit:store.popitem(last=False)
    def recovery_state(self):return {"engine_version":PROTECTION_ENGINE_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"ledger":self.ledger.snapshot()}
    def validate_recovery(self,state):return state.get("engine_version")==PROTECTION_ENGINE_VERSION and state.get("configuration_snapshot_id")==self.configuration.configuration_snapshot_id
    def restore(self,state):
        if not self.validate_recovery(state):return False
        ok=self.ledger.restore(state.get("ledger",{}))
        if ok:self._versions=OrderedDict(self.ledger.versions)
        return ok
