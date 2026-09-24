"""Neutral temporal quality budgets, adverse sequences, and cooldown governance."""
from __future__ import annotations
from collections import OrderedDict,defaultdict
from dataclasses import dataclass,replace
from datetime import datetime,timedelta
from decimal import Decimal
from enum import Enum,auto
from threading import RLock
from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace

TEMPORAL_ENGINE_VERSION="1.0";TEMPORAL_RECOVERY_SCHEMA_VERSION="1.0";ZERO=Decimal("0");ONE=Decimal("1")
class OutcomeClass(Enum):ADVERSE=auto();NEUTRAL=auto();FAVORABLE=auto();UNKNOWN=auto()
class TemporalStage(Enum):NORMAL=auto();WATCH=auto();RESTRICTED=auto();COOLDOWN=auto();SUSPENDED=auto();UNKNOWN=auto()
class TemporalDecision(Enum):ACCEPTED=auto();NO_ACTION=auto();BLOCKED=auto();INVALID=auto()
class CooldownState(Enum):INACTIVE=auto();ACTIVE=auto();EXPIRED_PENDING_CONFIRMATION=auto();RELEASED=auto()
class TemporalReconciliationOutcome(Enum):CONSISTENT=auto();FAILED_CLOSED=auto()

@dataclass(frozen=True)
class TemporalQualityConfiguration:
    daily_watch:Decimal=Decimal("5");daily_block:Decimal=Decimal("10");weekly_watch:Decimal=Decimal("10");weekly_block:Decimal=Decimal("20")
    streak_watch:int=3;streak_cooldown:int=5;cooldown_seconds:int=3600;watch_multiplier:Decimal=Decimal("0.75");restricted_multiplier:Decimal=Decimal("0.40")
    recovery_confirmations:int=2;maximum_scopes:int=256;maximum_events_per_scope:int=1024;maximum_snapshots:int=2048;configuration_snapshot_id:str="NEUTRAL_TEMPORAL_QUALITY_DEFAULT"
    def validate(self):
        errors=[]; nums=tuple(Decimal(str(x)) for x in (self.daily_watch,self.daily_block,self.weekly_watch,self.weekly_block,self.watch_multiplier,self.restricted_multiplier))
        if any(not x.is_finite() for x in nums) or not(ZERO<nums[0]<nums[1] and ZERO<nums[2]<nums[3]):errors.append("TEMPORAL_THRESHOLDS_INVALID")
        if not(ZERO<=nums[5]<=nums[4]<=ONE):errors.append("TEMPORAL_MULTIPLIERS_INVALID")
        if self.streak_watch<1 or self.streak_cooldown<self.streak_watch or self.cooldown_seconds<1 or self.recovery_confirmations<1 or min(self.maximum_scopes,self.maximum_events_per_scope,self.maximum_snapshots)<1:errors.append("TEMPORAL_POLICY_INVALID")
        return tuple(errors)

@dataclass(frozen=True)
class TemporalQualityOutcome:
    outcome_id:str;scope_id:str;category_id:str;variant_id:str;subject_id:str;classification:OutcomeClass;adverse_units:Decimal;research_day_id:str;research_week_id:str
    observed_at_utc:datetime;available_at_utc:datetime;source_lifecycle_id:str;dataset_fingerprint:str;configuration_snapshot_id:str;recovery_epoch:int
    @classmethod
    def create(cls,scope_id,category_id,variant_id,subject_id,classification,adverse_units,research_day_id,research_week_id,observed_at_utc,available_at_utc,source_lifecycle_id,dataset_fingerprint,configuration_snapshot_id="NEUTRAL_TEMPORAL_QUALITY_DEFAULT",recovery_epoch=0):
        units=Decimal(str(adverse_units));oid=deterministic_id("temporal_quality_outcome",scope_id,category_id,variant_id,subject_id,classification.name,units,research_day_id,research_week_id,observed_at_utc.isoformat(),available_at_utc.isoformat(),source_lifecycle_id,dataset_fingerprint,configuration_snapshot_id,recovery_epoch)
        return cls(oid,scope_id,category_id,variant_id,subject_id,classification,units,research_day_id,research_week_id,observed_at_utc,available_at_utc,source_lifecycle_id,dataset_fingerprint,configuration_snapshot_id,recovery_epoch)

@dataclass(frozen=True)
class TemporalProtectionState:
    state_id:str;scope_id:str;current_day_id:str;current_week_id:str;daily_adverse:Decimal;weekly_adverse:Decimal;global_streak:int;category_streaks:tuple[tuple[str,int],...]
    raw_stage:TemporalStage;published_stage:TemporalStage;temporal_multiplier:Decimal;final_permission_multiplier:Decimal;upstream_multiplier:Decimal
    cooldown_state:CooldownState;cooldown_started_at_utc:datetime|None;cooldown_until_utc:datetime|None;breach_count:int;recovery_progress:int;accepted_count:int
    last_outcome_id:str|None;last_observed_at_utc:datetime;dataset_fingerprint:str;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class TemporalProtectionEvent:
    event_id:str;scope_id:str;sequence_number:int;outcome_id:str;previous_state_id:str;new_state_id:str;stage:TemporalStage;observed_at_utc:datetime;known_at_utc:datetime;reason_codes:tuple[str,...]

@dataclass(frozen=True)
class TemporalProtectionSnapshot:
    snapshot_id:str;scope_id:str;state_id:str;day_id:str;week_id:str;daily_adverse:Decimal;weekly_adverse:Decimal;streak:int;stage:TemporalStage;permission_multiplier:Decimal;cooldown_state:CooldownState;event_ids:tuple[str,...];as_of_timestamp_utc:datetime

@dataclass(frozen=True)
class TemporalProcessingResult:
    decision_id:str;state:TemporalProtectionState|None;event:TemporalProtectionEvent|None;decision:TemporalDecision;reason_codes:tuple[str,...];decision_trace:DecisionTrace

@dataclass(frozen=True)
class TemporalReconciliationResult:
    reconciliation_id:str;scope_id:str;issues:tuple[str,...];outcome:TemporalReconciliationOutcome;repaired:bool;as_of_timestamp_utc:datetime

@dataclass(frozen=True)
class TemporalRecoveryState:
    schema_version:str;engine_version:str;configuration_snapshot_id:str;recovery_epoch:int;states:tuple[TemporalProtectionState,...];versions:tuple[TemporalProtectionState,...];outcomes:tuple[TemporalQualityOutcome,...];events:tuple[TemporalProtectionEvent,...]

class TemporalQualityProtectionEngine:
    def __init__(self,configuration=TemporalQualityConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self._lock=RLock();self.states=OrderedDict();self.versions=OrderedDict();self.outcomes=OrderedDict();self.events=OrderedDict();self.events_by_scope=defaultdict(tuple);self.snapshots=OrderedDict();self.recovery_restricted=False
    def initialize(self,scope_id,dataset_fingerprint,day_id,week_id,as_of,recovery_epoch=0):
        with self._lock:
            if scope_id in self.states:return self.states[scope_id]
            if not all((scope_id,dataset_fingerprint,day_id,week_id)) or len(self.states)>=self.configuration.maximum_scopes:raise ValueError("TEMPORAL_INITIALIZATION_INVALID")
            sid=deterministic_id("temporal_protection_state",scope_id,dataset_fingerprint,day_id,week_id,self.configuration.configuration_snapshot_id,recovery_epoch)
            state=TemporalProtectionState(sid,scope_id,day_id,week_id,ZERO,ZERO,0,(),TemporalStage.NORMAL,TemporalStage.NORMAL,ONE,ONE,ONE,CooldownState.INACTIVE,None,None,0,0,0,None,as_of,dataset_fingerprint,self.configuration.configuration_snapshot_id,recovery_epoch)
            self.states[scope_id]=state;self.versions[sid]=state;return state
    def process(self,outcome,as_of,upstream_multiplier=ONE):
        with self._lock:
            current=self.states.get(outcome.scope_id)
            if not current:return self._result(None,None,TemporalDecision.BLOCKED,("TEMPORAL_SCOPE_UNINITIALIZED",),as_of)
            if outcome.outcome_id in self.outcomes:return self._result(current,None,TemporalDecision.NO_ACTION,("TEMPORAL_DUPLICATE_OUTCOME",),as_of)
            reasons=[];upstream=Decimal(str(upstream_multiplier))
            if not outcome.adverse_units.is_finite() or outcome.adverse_units<ZERO or not upstream.is_finite() or not ZERO<=upstream<=ONE:reasons.append("TEMPORAL_NUMERICAL_INVALID")
            if outcome.available_at_utc>as_of or outcome.observed_at_utc>as_of or outcome.available_at_utc<outcome.observed_at_utc or outcome.observed_at_utc<current.last_observed_at_utc:reasons.append("TEMPORAL_ORDER_INVALID")
            if outcome.dataset_fingerprint!=current.dataset_fingerprint or outcome.configuration_snapshot_id!=current.configuration_snapshot_id or outcome.recovery_epoch!=current.recovery_epoch or not outcome.source_lifecycle_id:reasons.append("TEMPORAL_LINEAGE_INVALID")
            if outcome.classification is OutcomeClass.UNKNOWN:reasons.append("TEMPORAL_OUTCOME_UNKNOWN")
            if outcome.classification is not OutcomeClass.ADVERSE and outcome.adverse_units!=ZERO:reasons.append("TEMPORAL_CLASSIFICATION_INVALID")
            if reasons:return self._result(current,None,TemporalDecision.BLOCKED,tuple(reasons),as_of)
            daily=ZERO if outcome.research_day_id!=current.current_day_id else current.daily_adverse;weekly=ZERO if outcome.research_week_id!=current.current_week_id else current.weekly_adverse
            streak=current.global_streak;categories=dict(current.category_streaks)
            if outcome.classification is OutcomeClass.ADVERSE:
                daily+=outcome.adverse_units;weekly+=outcome.adverse_units;streak+=1;categories[outcome.category_id]=categories.get(outcome.category_id,0)+1
            elif outcome.classification is OutcomeClass.FAVORABLE:
                streak=0;categories[outcome.category_id]=0
            raw=self._stage(daily,weekly,streak);cooldown_state=current.cooldown_state;started=current.cooldown_started_at_utc;until=current.cooldown_until_utc;breaches=current.breach_count
            if raw in (TemporalStage.COOLDOWN,TemporalStage.SUSPENDED):
                if cooldown_state is not CooldownState.ACTIVE:started=outcome.observed_at_utc
                cooldown_state=CooldownState.ACTIVE;until=max(until or outcome.observed_at_utc,outcome.observed_at_utc+timedelta(seconds=self.configuration.cooldown_seconds));breaches+=1
            published,recovery=self._publish(raw,current)
            if cooldown_state is CooldownState.ACTIVE:published=max((published,TemporalStage.COOLDOWN),key=self._rank)
            temporal=self._multiplier(published);final=min(upstream,temporal)
            state_id=deterministic_id("temporal_state_version",current.state_id,outcome.outcome_id,daily,weekly,streak,published.name,cooldown_state.name,final,as_of.isoformat())
            updated=TemporalProtectionState(state_id,current.scope_id,outcome.research_day_id,outcome.research_week_id,daily,weekly,streak,tuple(sorted(categories.items())),raw,published,temporal,final,upstream,cooldown_state,started,until,breaches,recovery,current.accepted_count+1,outcome.outcome_id,outcome.observed_at_utc,current.dataset_fingerprint,current.configuration_snapshot_id,current.recovery_epoch)
            if len(self.events_by_scope[current.scope_id])>=self.configuration.maximum_events_per_scope:return self._result(current,None,TemporalDecision.BLOCKED,("TEMPORAL_HISTORY_BOUND_REACHED",),as_of)
            seq=len(self.events_by_scope[current.scope_id])+1;eid=deterministic_id("temporal_event",current.scope_id,seq,outcome.outcome_id,state_id);event=TemporalProtectionEvent(eid,current.scope_id,seq,outcome.outcome_id,current.state_id,state_id,published,outcome.observed_at_utc,as_of,(f"TEMPORAL_STAGE_{published.name}",))
            self.outcomes[outcome.outcome_id]=outcome;self.states[current.scope_id]=updated;self.versions[state_id]=updated;self.events[eid]=event;self.events_by_scope[current.scope_id]+=(eid,);self._record("temporal_quality_accepted",{"scope_id":current.scope_id,"stage":published.name});return self._result(updated,event,TemporalDecision.ACCEPTED,event.reason_codes,as_of)
    def confirm_cooldown_release(self,scope_id,as_of,evidence_confirmed):
        with self._lock:
            current=self.states.get(scope_id)
            if not current:return self._result(None,None,TemporalDecision.INVALID,("TEMPORAL_SCOPE_UNINITIALIZED",),as_of)
            if current.cooldown_state is not CooldownState.ACTIVE or not current.cooldown_until_utc or as_of<current.cooldown_until_utc:return self._result(current,None,TemporalDecision.NO_ACTION,("TEMPORAL_COOLDOWN_NOT_RELEASABLE",),as_of)
            if not evidence_confirmed:return self._result(current,None,TemporalDecision.BLOCKED,("TEMPORAL_RELEASE_CONFIRMATION_REQUIRED",),as_of)
            updated=replace(current,state_id=deterministic_id("temporal_release",current.state_id,as_of.isoformat()),cooldown_state=CooldownState.RELEASED,published_stage=TemporalStage.RESTRICTED,temporal_multiplier=self.configuration.restricted_multiplier,final_permission_multiplier=min(current.upstream_multiplier,self.configuration.restricted_multiplier),recovery_progress=0)
            self.states[scope_id]=updated;self.versions[updated.state_id]=updated;return self._result(updated,None,TemporalDecision.ACCEPTED,("TEMPORAL_COOLDOWN_RELEASED_RESTRICTED",),as_of)
    def snapshot(self,scope_id,as_of):
        with self._lock:
            candidates=[x for x in self.versions.values() if x.scope_id==scope_id and x.last_observed_at_utc<=as_of]
            if not candidates:return None
            current=max(candidates,key=lambda x:(x.accepted_count,x.last_observed_at_utc,x.state_id));events=tuple(x.event_id for x in self.events.values() if x.scope_id==scope_id and x.known_at_utc<=as_of and x.sequence_number<=current.accepted_count);sid=deterministic_id("temporal_snapshot",scope_id,current.state_id,*events,as_of.isoformat());snap=TemporalProtectionSnapshot(sid,scope_id,current.state_id,current.current_day_id,current.current_week_id,current.daily_adverse,current.weekly_adverse,current.global_streak,current.published_stage,current.final_permission_multiplier,current.cooldown_state,events,as_of);self.snapshots[sid]=snap
            while len(self.snapshots)>self.configuration.maximum_snapshots:self.snapshots.popitem(last=False)
            return snap
    def reconcile(self,scope_id,as_of):
        current=self.states.get(scope_id);issues=[];events=[self.events[x] for x in self.events_by_scope.get(scope_id,()) if x in self.events]
        if not current:issues.append("TEMPORAL_SCOPE_MISSING")
        elif [x.sequence_number for x in events]!=list(range(1,len(events)+1)) or len(events)!=current.accepted_count:issues.append("TEMPORAL_SEQUENCE_MISMATCH")
        if current and (not ZERO<=current.final_permission_multiplier<=ONE or current.final_permission_multiplier>current.upstream_multiplier or current.final_permission_multiplier>current.temporal_multiplier):issues.append("TEMPORAL_NON_AMPLIFICATION_INVALID")
        rid=deterministic_id("temporal_reconciliation",scope_id,*issues,as_of.isoformat());return TemporalReconciliationResult(rid,scope_id,tuple(issues),TemporalReconciliationOutcome.CONSISTENT if not issues else TemporalReconciliationOutcome.FAILED_CLOSED,False,as_of)
    def recovery_state(self,epoch):return TemporalRecoveryState(TEMPORAL_RECOVERY_SCHEMA_VERSION,TEMPORAL_ENGINE_VERSION,self.configuration.configuration_snapshot_id,epoch,tuple(self.states.values()),tuple(self.versions.values()),tuple(self.outcomes.values()),tuple(self.events.values()))
    def restore(self,state,expected_epoch):
        with self._lock:
            if state.schema_version!=TEMPORAL_RECOVERY_SCHEMA_VERSION or state.engine_version!=TEMPORAL_ENGINE_VERSION or state.configuration_snapshot_id!=self.configuration.configuration_snapshot_id or state.recovery_epoch!=expected_epoch:self.recovery_restricted=True;return False
            try:
                if len({x.scope_id for x in state.states})!=len(state.states) or len({x.outcome_id for x in state.outcomes})!=len(state.outcomes) or len({x.event_id for x in state.events})!=len(state.events):raise ValueError
                states=OrderedDict((x.scope_id,x) for x in state.states);outcomes=OrderedDict((x.outcome_id,x) for x in state.outcomes);groups=defaultdict(list)
                for e in state.events:
                    if e.scope_id not in states or e.outcome_id not in outcomes:raise ValueError
                    groups[e.scope_id].append(e)
                for scope,current in states.items():
                    ev=sorted(groups[scope],key=lambda x:x.sequence_number)
                    if [x.sequence_number for x in ev]!=list(range(1,len(ev)+1)) or len(ev)!=current.accepted_count or not ZERO<=current.final_permission_multiplier<=min(ONE,current.upstream_multiplier,current.temporal_multiplier):raise ValueError
                self.states=states;self.versions=OrderedDict((x.state_id,x) for x in state.versions);self.outcomes=outcomes;self.events=OrderedDict((x.event_id,x) for x in state.events);self.events_by_scope=defaultdict(tuple,{k:tuple(x.event_id for x in sorted(v,key=lambda x:x.sequence_number)) for k,v in groups.items()});self.recovery_restricted=False;return True
            except Exception:self.recovery_restricted=True;return False
    def replay_fingerprint(self,scope_id):return deterministic_id("temporal_replay",scope_id,self.states[scope_id].state_id if scope_id in self.states else "MISSING",*self.events_by_scope.get(scope_id,()))
    def _stage(self,daily,weekly,streak):
        if daily>=self.configuration.daily_block or weekly>=self.configuration.weekly_block:return TemporalStage.SUSPENDED
        if streak>=self.configuration.streak_cooldown:return TemporalStage.COOLDOWN
        if daily>=self.configuration.daily_watch or weekly>=self.configuration.weekly_watch:return TemporalStage.RESTRICTED
        if streak>=self.configuration.streak_watch:return TemporalStage.WATCH
        return TemporalStage.NORMAL
    def _publish(self,raw,current):
        if self._rank(raw)>=self._rank(current.published_stage):return raw,0
        p=current.recovery_progress+1
        return (current.published_stage,p) if p<self.configuration.recovery_confirmations else (raw,0)
    @staticmethod
    def _rank(stage):return {TemporalStage.NORMAL:0,TemporalStage.WATCH:1,TemporalStage.RESTRICTED:2,TemporalStage.COOLDOWN:3,TemporalStage.SUSPENDED:4,TemporalStage.UNKNOWN:5}[stage]
    def _multiplier(self,stage):return {TemporalStage.NORMAL:ONE,TemporalStage.WATCH:self.configuration.watch_multiplier,TemporalStage.RESTRICTED:self.configuration.restricted_multiplier,TemporalStage.COOLDOWN:ZERO,TemporalStage.SUSPENDED:ZERO,TemporalStage.UNKNOWN:ZERO}[stage]
    def _result(self,state,event,decision,reasons,as_of):
        corr=state.scope_id if state else deterministic_id("temporal_missing",*reasons,as_of.isoformat());did=deterministic_id("temporal_decision",corr,decision.name,*reasons,event.event_id if event else "NONE",as_of.isoformat());passed=decision in (TemporalDecision.ACCEPTED,TemporalDecision.NO_ACTION);ev=DecisionEvaluation("TEMPORAL_QUALITY",DecisionStatus.PASSED if passed else DecisionStatus.FAILED,reasons[-1],"Neutral temporal quality protection evaluated",(event.event_id,) if event else ());trace=DecisionTrace(did,corr,as_of,(ev,),DecisionOutcome.ACCEPTED if decision is TemporalDecision.ACCEPTED else DecisionOutcome.NO_ACTION if decision is TemporalDecision.NO_ACTION else DecisionOutcome.BLOCKED,reasons[-1],as_of,None if passed else "TEMPORAL_QUALITY");return TemporalProcessingResult(did,state,event,decision,tuple(reasons),trace)
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
