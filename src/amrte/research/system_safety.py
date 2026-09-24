"""Highest-authority neutral research-system integrity gate."""
from __future__ import annotations
from collections import OrderedDict,defaultdict
from dataclasses import dataclass,replace
from datetime import datetime
from decimal import Decimal
from enum import Enum,auto
from threading import RLock
from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace
VERSION="1.0";SCHEMA="1.0";ZERO=Decimal("0");ONE=Decimal("1")
class SafetyDomain(Enum):DATA_INTEGRITY=auto();OBSERVATION_QUALITY=auto();WORKFLOW=auto();STATE_INTEGRITY=auto();CALCULATION=auto();TEMPORAL=auto();RECOVERY=auto();RECONCILIATION=auto();REPLAY=auto();PERSISTENCE=auto();CONFIGURATION=auto();RESOURCE=auto();UNKNOWN=auto()
class SignalSeverity(Enum):INFO=auto();LOW=auto();MEDIUM=auto();HIGH=auto();CRITICAL=auto();UNKNOWN=auto()
class SafetyState(Enum):NORMAL=auto();CAUTION=auto();RESTRICTED=auto();CIRCUIT_OPEN=auto();EMERGENCY_STOP=auto();RECOVERY_PENDING=auto();PROBATION=auto();UNKNOWN=auto()
class SafetyDecision(Enum):ACCEPTED=auto();NO_ACTION=auto();BLOCKED=auto();INVALID=auto()
class IncidentState(Enum):OPEN=auto();LATCHED=auto();RECOVERY_PENDING=auto();PROBATION=auto();RESOLVED=auto()
class TriggerScope(Enum):SCOPED=auto();GLOBAL=auto()
@dataclass(frozen=True)
class SafetyTriggerDefinition:
    trigger_type:str;domain:SafetyDomain;minimum_severity:SignalSeverity;scope:TriggerScope;critical:bool=False;emergency:bool=False
class SafetyTriggerRegistry:
    """Deterministic registry of neutral integrity triggers."""
    def __init__(self,definitions=()):
        self._items=OrderedDict()
        for item in definitions:self.register(item)
    def register(self,item):
        if not item.trigger_type or item.trigger_type in self._items or item.domain is SafetyDomain.UNKNOWN or item.minimum_severity is SignalSeverity.UNKNOWN:raise ValueError("SAFETY_TRIGGER_INVALID")
        self._items[item.trigger_type]=item
    def resolve(self,trigger_type):return self._items.get(trigger_type)
    def enumerate(self):return tuple(self._items[k] for k in sorted(self._items))
    @classmethod
    def default(cls):
        return cls(tuple(SafetyTriggerDefinition(f"{domain.name}_FAILURE",domain,SignalSeverity.HIGH,TriggerScope.SCOPED,domain in (SafetyDomain.DATA_INTEGRITY,SafetyDomain.STATE_INTEGRITY,SafetyDomain.REPLAY),domain in (SafetyDomain.PERSISTENCE,SafetyDomain.RECOVERY)) for domain in SafetyDomain if domain is not SafetyDomain.UNKNOWN))
class SafetyTriggerAggregator:
    @staticmethod
    def most_restrictive(states):return max(tuple(states) or (SafetyState.UNKNOWN,),key=lambda state:SystemSafetyEngine._rank(state))
class ResearchCircuitBreaker:
    @staticmethod
    def engaged(status):return bool(status and status.circuit_latched)
class EmergencyResearchStop:
    @staticmethod
    def engaged(status):return bool(status and status.emergency_latched and status.final_phase_multiplier==ZERO)
@dataclass(frozen=True)
class SystemSafetyConfiguration:
    medium_escalation_count:int=2;high_escalation_count:int=2;probation_confirmations:int=2;caution_multiplier:Decimal=Decimal(".75");restricted_multiplier:Decimal=Decimal(".25");maximum_scopes:int=256;maximum_events:int=4096;maximum_snapshots:int=2048;configuration_snapshot_id:str="NEUTRAL_SYSTEM_SAFETY_DEFAULT"
    def validate(self):
        e=[];a=Decimal(str(self.caution_multiplier));b=Decimal(str(self.restricted_multiplier))
        if not(a.is_finite() and b.is_finite() and ZERO<=b<=a<=ONE):e.append("SAFETY_MULTIPLIER_INVALID")
        if min(self.medium_escalation_count,self.high_escalation_count,self.probation_confirmations,self.maximum_scopes,self.maximum_events,self.maximum_snapshots)<1:e.append("SAFETY_CONFIGURATION_INVALID")
        return tuple(e)
@dataclass(frozen=True)
class SystemSafetySignal:
    signal_id:str;scope_id:str;domain:SafetyDomain;severity:SignalSeverity;trigger_code:str;observed_at_utc:datetime;available_at_utc:datetime;evidence_ids:tuple[str,...];dataset_fingerprint:str;configuration_snapshot_id:str;recovery_epoch:int
    @classmethod
    def create(cls,scope_id,domain,severity,trigger_code,observed_at_utc,available_at_utc,evidence_ids,dataset_fingerprint,configuration_snapshot_id="NEUTRAL_SYSTEM_SAFETY_DEFAULT",recovery_epoch=0):
        ids=tuple(sorted(set(evidence_ids)));sid=deterministic_id("system_safety_signal",scope_id,domain.name,severity.name,trigger_code,observed_at_utc.isoformat(),available_at_utc.isoformat(),*ids,dataset_fingerprint,configuration_snapshot_id,recovery_epoch);return cls(sid,scope_id,domain,severity,trigger_code,observed_at_utc,available_at_utc,ids,dataset_fingerprint,configuration_snapshot_id,recovery_epoch)
@dataclass(frozen=True)
class SystemSafetyStatus:
    status_id:str;scope_id:str;raw_state:SafetyState;published_state:SafetyState;permission_multiplier:Decimal;final_phase_multiplier:Decimal;upstream_multiplier:Decimal;circuit_latched:bool;emergency_latched:bool;incident_id:str|None;incident_state:IncidentState|None;probation_progress:int;signal_count:int;last_signal_id:str|None;updated_at_utc:datetime;dataset_fingerprint:str;configuration_snapshot_id:str;recovery_epoch:int
@dataclass(frozen=True)
class SafetyIncident:
    incident_id:str;scope_id:str;root_signal_id:str;trigger_codes:tuple[str,...];highest_severity:SignalSeverity;state:IncidentState;opened_at_utc:datetime;updated_at_utc:datetime
@dataclass(frozen=True)
class SystemSafetyEvent:
    event_id:str;scope_id:str;sequence:int;signal_id:str|None;previous_status_id:str;new_status_id:str;state:SafetyState;known_at_utc:datetime;reason_codes:tuple[str,...]
@dataclass(frozen=True)
class SystemSafetySnapshot:
    snapshot_id:str;scope_id:str;status_id:str;state:SafetyState;permission_multiplier:Decimal;circuit_latched:bool;emergency_latched:bool;incident_id:str|None;event_ids:tuple[str,...];as_of_timestamp_utc:datetime
@dataclass(frozen=True)
class PhaseVIISafetySnapshot:
    snapshot_id:str;scope_id:str;prompt28_multiplier:Decimal;prompt29_multiplier:Decimal;system_safety_multiplier:Decimal;final_phase_vii_multiplier:Decimal;state:SafetyState;hard_blocked:bool;as_of_timestamp_utc:datetime;configuration_snapshot_id:str;recovery_epoch:int
@dataclass(frozen=True)
class Prompt31SafetyHandoff:
    handoff_id:str;phase_vii_snapshot_id:str;scope_id:str;permission_multiplier:Decimal;state:SafetyState;restrictions:tuple[str,...];as_of_timestamp_utc:datetime
@dataclass(frozen=True)
class SystemSafetyResult:
    decision_id:str;status:SystemSafetyStatus|None;incident:SafetyIncident|None;event:SystemSafetyEvent|None;decision:SafetyDecision;reason_codes:tuple[str,...];decision_trace:DecisionTrace
@dataclass(frozen=True)
class SystemSafetyRecovery:
    schema_version:str;engine_version:str;configuration_snapshot_id:str;recovery_epoch:int;statuses:tuple[SystemSafetyStatus,...];versions:tuple[SystemSafetyStatus,...];signals:tuple[SystemSafetySignal,...];incidents:tuple[SafetyIncident,...];events:tuple[SystemSafetyEvent,...]
class SystemSafetyEngine:
    def __init__(self,configuration=SystemSafetyConfiguration(),audit=None,trigger_registry=None):
        e=configuration.validate()
        if e:raise ValueError(";".join(e))
        self.configuration=configuration;self.audit=audit;self.trigger_registry=trigger_registry or SafetyTriggerRegistry.default();self._lock=RLock();self.statuses=OrderedDict();self.versions=OrderedDict();self.signals=OrderedDict();self.incidents=OrderedDict();self.events=OrderedDict();self.by_scope=defaultdict(tuple);self.snapshots=OrderedDict();self.recovery_restricted=False
    def initialize(self,scope_id,dataset_fingerprint,as_of,recovery_epoch=0):
        with self._lock:
            if scope_id in self.statuses:return self.statuses[scope_id]
            if not scope_id or not dataset_fingerprint or len(self.statuses)>=self.configuration.maximum_scopes:raise ValueError("SAFETY_INITIALIZATION_INVALID")
            sid=deterministic_id("system_safety_status",scope_id,dataset_fingerprint,self.configuration.configuration_snapshot_id,recovery_epoch);s=SystemSafetyStatus(sid,scope_id,SafetyState.NORMAL,SafetyState.NORMAL,ONE,ONE,ONE,False,False,None,None,0,0,None,as_of,dataset_fingerprint,self.configuration.configuration_snapshot_id,recovery_epoch);self.statuses[scope_id]=s;self.versions[sid]=s;return s
    def process(self,signal,as_of,upstream_multiplier=ONE):
        with self._lock:
            current=self.statuses.get(signal.scope_id)
            if not current:return self._result(None,None,None,SafetyDecision.BLOCKED,("SAFETY_SCOPE_UNINITIALIZED",),as_of)
            if signal.signal_id in self.signals:return self._result(current,self.incidents.get(current.incident_id),None,SafetyDecision.NO_ACTION,("SAFETY_DUPLICATE_SIGNAL",),as_of)
            upstream=Decimal(str(upstream_multiplier));reasons=[]
            if signal.available_at_utc>as_of or signal.observed_at_utc>as_of or signal.available_at_utc<signal.observed_at_utc or signal.observed_at_utc<current.updated_at_utc:reasons.append("SAFETY_TEMPORAL_INVALID")
            if signal.dataset_fingerprint!=current.dataset_fingerprint or signal.configuration_snapshot_id!=current.configuration_snapshot_id or signal.recovery_epoch!=current.recovery_epoch:reasons.append("SAFETY_LINEAGE_INVALID")
            if signal.domain is SafetyDomain.UNKNOWN or signal.severity is SignalSeverity.UNKNOWN or not signal.trigger_code or not signal.evidence_ids:reasons.append("SAFETY_EVIDENCE_INVALID")
            if not upstream.is_finite() or not ZERO<=upstream<=ONE:reasons.append("SAFETY_UPSTREAM_MULTIPLIER_INVALID")
            if reasons:return self._result(current,self.incidents.get(current.incident_id),None,SafetyDecision.BLOCKED,tuple(reasons),as_of)
            same=[x for x in self.signals.values() if x.scope_id==signal.scope_id];medium=sum(x.severity is SignalSeverity.MEDIUM for x in same)+int(signal.severity is SignalSeverity.MEDIUM);high=sum(x.severity is SignalSeverity.HIGH for x in same)+int(signal.severity is SignalSeverity.HIGH)
            raw=self._raw(signal.severity,medium,high);published=max((current.published_state,raw),key=self._rank);circuit=current.circuit_latched or published in (SafetyState.CIRCUIT_OPEN,SafetyState.EMERGENCY_STOP);emergency=current.emergency_latched or published is SafetyState.EMERGENCY_STOP
            incident=self.incidents.get(current.incident_id)
            if raw in (SafetyState.CIRCUIT_OPEN,SafetyState.EMERGENCY_STOP):
                if not incident:
                    iid=deterministic_id("safety_incident",signal.scope_id,signal.signal_id,raw.name);incident=SafetyIncident(iid,signal.scope_id,signal.signal_id,(signal.trigger_code,),signal.severity,IncidentState.LATCHED,as_of,as_of)
                else:incident=replace(incident,trigger_codes=tuple(sorted(set(incident.trigger_codes+(signal.trigger_code,)))),highest_severity=max((incident.highest_severity,signal.severity),key=lambda x:x.value),updated_at_utc=as_of,state=IncidentState.LATCHED)
            multiplier=self._multiplier(published);final=min(upstream,multiplier);status_id=deterministic_id("system_safety_version",current.status_id,signal.signal_id,published.name,circuit,emergency,final,as_of.isoformat());updated=SystemSafetyStatus(status_id,current.scope_id,raw,published,multiplier,final,upstream,circuit,emergency,incident.incident_id if incident else current.incident_id,incident.state if incident else current.incident_state,0,current.signal_count+1,signal.signal_id,as_of,current.dataset_fingerprint,current.configuration_snapshot_id,current.recovery_epoch)
            seq=len(self.by_scope[current.scope_id])+1;eid=deterministic_id("system_safety_event",current.scope_id,seq,signal.signal_id,status_id);event=SystemSafetyEvent(eid,current.scope_id,seq,signal.signal_id,current.status_id,status_id,published,as_of,(f"SAFETY_{published.name}",))
            if len(self.events)>=self.configuration.maximum_events:return self._result(current,incident,None,SafetyDecision.BLOCKED,("SAFETY_EVENT_BOUND_REACHED",),as_of)
            self.signals[signal.signal_id]=signal;self.statuses[current.scope_id]=updated;self.versions[status_id]=updated;self.events[eid]=event;self.by_scope[current.scope_id]+=(eid,)
            if incident:self.incidents[incident.incident_id]=incident
            self._record("system_safety_signal_accepted",{"scope_id":current.scope_id,"state":published.name});return self._result(updated,incident,event,SafetyDecision.ACCEPTED,event.reason_codes,as_of)
    def request_recovery(self,scope_id,as_of,evidence_confirmed,actor,reason):
        with self._lock:
            current=self.statuses.get(scope_id)
            if not current:return self._result(None,None,None,SafetyDecision.INVALID,("SAFETY_SCOPE_UNINITIALIZED",),as_of)
            incident=self.incidents.get(current.incident_id)
            if not(current.circuit_latched or current.emergency_latched) or not evidence_confirmed or not actor or not reason:return self._result(current,incident,None,SafetyDecision.BLOCKED,("SAFETY_RECOVERY_PRECONDITION_FAILED",),as_of)
            state_id=deterministic_id("safety_recovery_pending",current.status_id,actor,reason,as_of.isoformat());updated=replace(current,status_id=state_id,published_state=SafetyState.RECOVERY_PENDING,permission_multiplier=ZERO,final_phase_multiplier=ZERO,probation_progress=0,updated_at_utc=as_of,incident_state=IncidentState.RECOVERY_PENDING);self.statuses[scope_id]=updated;self.versions[state_id]=updated
            if incident:self.incidents[incident.incident_id]=replace(incident,state=IncidentState.RECOVERY_PENDING,updated_at_utc=as_of)
            self._record("system_safety_recovery_requested",{"scope_id":scope_id,"actor":actor,"reason":reason});return self._result(updated,self.incidents.get(current.incident_id),None,SafetyDecision.ACCEPTED,("SAFETY_RECOVERY_PENDING",),as_of)
    def confirm_probation(self,scope_id,as_of,healthy_evidence):
        with self._lock:
            current=self.statuses.get(scope_id);incident=self.incidents.get(current.incident_id) if current else None
            if not current or current.published_state not in (SafetyState.RECOVERY_PENDING,SafetyState.PROBATION):return self._result(current,incident,None,SafetyDecision.NO_ACTION,("SAFETY_PROBATION_NOT_APPLICABLE",),as_of)
            if not healthy_evidence:
                updated=replace(current,status_id=deterministic_id("safety_probation_failed",current.status_id,as_of.isoformat()),published_state=SafetyState.EMERGENCY_STOP,permission_multiplier=ZERO,final_phase_multiplier=ZERO,emergency_latched=True,probation_progress=0,updated_at_utc=as_of);self.statuses[scope_id]=updated;self.versions[updated.status_id]=updated;return self._result(updated,incident,None,SafetyDecision.BLOCKED,("SAFETY_PROBATION_FAILED",),as_of)
            progress=current.probation_progress+1
            if progress<self.configuration.probation_confirmations:
                updated=replace(current,status_id=deterministic_id("safety_probation",current.status_id,progress,as_of.isoformat()),published_state=SafetyState.PROBATION,permission_multiplier=self.configuration.restricted_multiplier,final_phase_multiplier=min(current.upstream_multiplier,self.configuration.restricted_multiplier),probation_progress=progress,updated_at_utc=as_of);self.statuses[scope_id]=updated;self.versions[updated.status_id]=updated;return self._result(updated,incident,None,SafetyDecision.ACCEPTED,("SAFETY_PROBATION_CONTINUES",),as_of)
            updated=replace(current,status_id=deterministic_id("safety_recovered",current.status_id,as_of.isoformat()),raw_state=SafetyState.NORMAL,published_state=SafetyState.NORMAL,permission_multiplier=ONE,final_phase_multiplier=min(current.upstream_multiplier,ONE),circuit_latched=False,emergency_latched=False,probation_progress=0,updated_at_utc=as_of,incident_state=IncidentState.RESOLVED);self.statuses[scope_id]=updated;self.versions[updated.status_id]=updated
            if incident:self.incidents[incident.incident_id]=replace(incident,state=IncidentState.RESOLVED,updated_at_utc=as_of)
            return self._result(updated,self.incidents.get(current.incident_id),None,SafetyDecision.ACCEPTED,("SAFETY_RECOVERED_CONFIRMED",),as_of)
    def snapshot(self,scope_id,as_of):
        candidates=[x for x in self.versions.values() if x.scope_id==scope_id and x.updated_at_utc<=as_of]
        if not candidates:return None
        current=max(candidates,key=lambda x:(x.updated_at_utc,x.signal_count,x.status_id));ev=tuple(x.event_id for x in self.events.values() if x.scope_id==scope_id and x.known_at_utc<=as_of);sid=deterministic_id("system_safety_snapshot",scope_id,current.status_id,*ev,as_of.isoformat());s=SystemSafetySnapshot(sid,scope_id,current.status_id,current.published_state,current.final_phase_multiplier,current.circuit_latched,current.emergency_latched,current.incident_id,ev,as_of);self.snapshots[sid]=s
        while len(self.snapshots)>self.configuration.maximum_snapshots:self.snapshots.popitem(last=False)
        return s
    def phase_vii_snapshot(self,scope_id,as_of,prompt28_multiplier=ONE,prompt29_multiplier=ONE):
        current=self.snapshot(scope_id,as_of)
        if not current:return None
        p28=Decimal(str(prompt28_multiplier));p29=Decimal(str(prompt29_multiplier))
        if not p28.is_finite() or not p29.is_finite() or not ZERO<=p28<=ONE or not ZERO<=p29<=ONE:raise ValueError("SAFETY_PHASE_VII_INPUT_INVALID")
        final=min(p28,p29,current.permission_multiplier);sid=deterministic_id("phase_vii_safety_snapshot",current.snapshot_id,p28,p29,final)
        status=self.versions[current.status_id]
        return PhaseVIISafetySnapshot(sid,scope_id,p28,p29,current.permission_multiplier,final,current.state,final==ZERO,as_of,status.configuration_snapshot_id,status.recovery_epoch)
    @staticmethod
    def prompt31_handoff(snapshot):
        restrictions=() if snapshot.final_phase_vii_multiplier==ONE else ("PHASE_VII_RESTRICTION_ACTIVE",)
        hid=deterministic_id("prompt31_safety_handoff",snapshot.snapshot_id,*restrictions)
        return Prompt31SafetyHandoff(hid,snapshot.snapshot_id,snapshot.scope_id,snapshot.final_phase_vii_multiplier,snapshot.state,restrictions,snapshot.as_of_timestamp_utc)
    def reconcile(self,scope_id):
        current=self.statuses.get(scope_id);ev=[self.events[x] for x in self.by_scope.get(scope_id,()) if x in self.events];issues=[]
        if not current:issues.append("SAFETY_SCOPE_MISSING")
        elif [x.sequence for x in ev]!=list(range(1,len(ev)+1)) or len(ev)!=current.signal_count:issues.append("SAFETY_SEQUENCE_MISMATCH")
        if current and (current.final_phase_multiplier>current.upstream_multiplier or current.final_phase_multiplier>current.permission_multiplier or not ZERO<=current.final_phase_multiplier<=ONE):issues.append("SAFETY_NON_AMPLIFICATION_INVALID")
        zero_states=(SafetyState.CIRCUIT_OPEN,SafetyState.EMERGENCY_STOP,SafetyState.RECOVERY_PENDING)
        if current and current.published_state in zero_states and current.final_phase_multiplier!=ZERO:issues.append("SAFETY_LATCH_PERMISSION_INVALID")
        return tuple(issues)
    def recovery_state(self,epoch):return SystemSafetyRecovery(SCHEMA,VERSION,self.configuration.configuration_snapshot_id,epoch,tuple(self.statuses.values()),tuple(self.versions.values()),tuple(self.signals.values()),tuple(self.incidents.values()),tuple(self.events.values()))
    def restore(self,state,epoch):
        with self._lock:
            if state.schema_version!=SCHEMA or state.engine_version!=VERSION or state.configuration_snapshot_id!=self.configuration.configuration_snapshot_id or state.recovery_epoch!=epoch:self.recovery_restricted=True;return False
            try:
                if len({x.scope_id for x in state.statuses})!=len(state.statuses) or len({x.signal_id for x in state.signals})!=len(state.signals) or len({x.event_id for x in state.events})!=len(state.events):raise ValueError
                statuses=OrderedDict((x.scope_id,x) for x in state.statuses);signals=OrderedDict((x.signal_id,x) for x in state.signals);groups=defaultdict(list)
                for e in state.events:
                    if e.scope_id not in statuses or (e.signal_id and e.signal_id not in signals):raise ValueError
                    groups[e.scope_id].append(e)
                for scope,s in statuses.items():
                    ev=sorted(groups[scope],key=lambda x:x.sequence)
                    zero_states=(SafetyState.CIRCUIT_OPEN,SafetyState.EMERGENCY_STOP,SafetyState.RECOVERY_PENDING)
                    if [x.sequence for x in ev]!=list(range(1,len(ev)+1)) or len(ev)!=s.signal_count or not ZERO<=s.final_phase_multiplier<=min(ONE,s.upstream_multiplier,s.permission_multiplier) or (s.published_state in zero_states and s.final_phase_multiplier!=ZERO):raise ValueError
                self.statuses=statuses;self.versions=OrderedDict((x.status_id,x) for x in state.versions);self.signals=signals;self.incidents=OrderedDict((x.incident_id,x) for x in state.incidents);self.events=OrderedDict((x.event_id,x) for x in state.events);self.by_scope=defaultdict(tuple,{k:tuple(x.event_id for x in sorted(v,key=lambda x:x.sequence)) for k,v in groups.items()});self.recovery_restricted=False;return True
            except Exception:self.recovery_restricted=True;return False
    def replay_fingerprint(self,scope):return deterministic_id("system_safety_replay",scope,self.statuses[scope].status_id if scope in self.statuses else "MISSING",*self.by_scope.get(scope,()))
    def _raw(self,severity,medium,high):
        if severity is SignalSeverity.CRITICAL:return SafetyState.EMERGENCY_STOP
        if severity is SignalSeverity.HIGH and high>=self.configuration.high_escalation_count:return SafetyState.CIRCUIT_OPEN
        if severity is SignalSeverity.HIGH:return SafetyState.RESTRICTED
        if severity is SignalSeverity.MEDIUM and medium>=self.configuration.medium_escalation_count:return SafetyState.RESTRICTED
        if severity in (SignalSeverity.MEDIUM,SignalSeverity.LOW):return SafetyState.CAUTION
        return SafetyState.NORMAL
    @staticmethod
    def _rank(state):return {SafetyState.NORMAL:0,SafetyState.CAUTION:1,SafetyState.RESTRICTED:2,SafetyState.RECOVERY_PENDING:3,SafetyState.PROBATION:3,SafetyState.CIRCUIT_OPEN:4,SafetyState.EMERGENCY_STOP:5,SafetyState.UNKNOWN:6}[state]
    def _multiplier(self,state):return {SafetyState.NORMAL:ONE,SafetyState.CAUTION:self.configuration.caution_multiplier,SafetyState.RESTRICTED:self.configuration.restricted_multiplier,SafetyState.RECOVERY_PENDING:ZERO,SafetyState.PROBATION:self.configuration.restricted_multiplier,SafetyState.CIRCUIT_OPEN:ZERO,SafetyState.EMERGENCY_STOP:ZERO,SafetyState.UNKNOWN:ZERO}[state]
    def _result(self,status,incident,event,decision,reasons,as_of):
        c=status.scope_id if status else deterministic_id("safety_missing",*reasons,as_of.isoformat());d=deterministic_id("system_safety_decision",c,decision.name,*reasons,event.event_id if event else "NONE",as_of.isoformat());passed=decision in (SafetyDecision.ACCEPTED,SafetyDecision.NO_ACTION);x=DecisionEvaluation("SYSTEM_SAFETY",DecisionStatus.PASSED if passed else DecisionStatus.FAILED,reasons[-1],"Neutral systemic research safety evaluated",(event.event_id,) if event else ());t=DecisionTrace(d,c,as_of,(x,),DecisionOutcome.ACCEPTED if decision is SafetyDecision.ACCEPTED else DecisionOutcome.NO_ACTION if decision is SafetyDecision.NO_ACTION else DecisionOutcome.BLOCKED,reasons[-1],as_of,None if passed else "SYSTEM_SAFETY");return SystemSafetyResult(d,status,incident,event,decision,tuple(reasons),t)
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)

SystemSafetyDecision=SafetyDecision
SystemSafetyState=SafetyState
