"""Deterministic neutral workflow simulation.

The abstractions in this module model generic authorized work units.  They do
not represent financial orders, market activity, accounts, positions, prices,
or execution.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass,replace
from datetime import datetime,timedelta
from decimal import Decimal,ROUND_FLOOR,localcontext
from enum import Enum,auto
from functools import wraps
from threading import RLock

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace

WORKFLOW_ENGINE_VERSION="1.0";RECOVERY_SCHEMA_VERSION="1.0";ZERO=Decimal("0")

class WorkflowState(Enum):CREATED=auto();VALIDATED=auto();SUBMITTED=auto();ACKNOWLEDGED=auto();PARTIALLY_COMPLETED=auto();COMPLETED=auto();REJECTED=auto();TIMED_OUT=auto();CANCELLED=auto();EXPIRED=auto();RECOVERY_RESTRICTED=auto();INVALID=auto();UNKNOWN=auto()
class WorkflowHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();STALE=auto();INVALID=auto();UNKNOWN=auto()
class WorkflowOutcome(Enum):ACCEPTED=auto();PARTIAL=auto();COMPLETED=auto();REJECTED=auto();CANCELLED=auto();EXPIRED=auto();TIMED_OUT=auto();NO_ACTION=auto();INVALID=auto()
class CompletionPolicy(Enum):ALL_OR_NOTHING=auto();PARTIAL_ALLOWED=auto()
class RetryClass(Enum):RETRYABLE=auto();NON_RETRYABLE=auto();UNKNOWN=auto()
class ReconciliationStatus(Enum):CONSISTENT=auto();GHOST_STATE=auto();MISSING_STATE=auto();COMPLETION_MISMATCH=auto();SEQUENCE_MISMATCH=auto();INVALID=auto()

TERMINAL={WorkflowState.COMPLETED,WorkflowState.REJECTED,WorkflowState.CANCELLED,WorkflowState.EXPIRED,WorkflowState.INVALID}

def synchronized(method):
    """Serialize mutations while permitting nested engine calls via an RLock."""
    @wraps(method)
    def guarded(self,*args,**kwargs):
        with self._lock:return method(self,*args,**kwargs)
    return guarded

@dataclass(frozen=True)
class WorkflowConfiguration:
    work_step:Decimal=Decimal("0.01");minimum_work:Decimal=Decimal("0.01");maximum_work:Decimal=Decimal("1000")
    maximum_retries:int=3;retry_backoff_seconds:int=5;timeout_seconds:int=300;request_ttl_seconds:int=3600
    maximum_requests:int=512;maximum_submissions:int=512;maximum_events:int=2048;maximum_snapshots:int=512;maximum_cache_entries:int=512
    completion_policy:CompletionPolicy=CompletionPolicy.PARTIAL_ALLOWED;configuration_snapshot_id:str="NEUTRAL_WORKFLOW_DEFAULT"
    def validate(self):
        errors=[]
        try:
            values=tuple(Decimal(str(x)) for x in (self.work_step,self.minimum_work,self.maximum_work))
            if any(not x.is_finite() for x in values) or values[0]<=0 or values[1]<0 or values[2]<values[1]:errors.append("WORKFLOW_NUMERICAL_INVALID")
        except Exception:errors.append("WORKFLOW_NUMERICAL_INVALID")
        if self.maximum_retries<0 or self.retry_backoff_seconds<0 or self.timeout_seconds<1 or self.request_ttl_seconds<1:errors.append("WORKFLOW_TIME_POLICY_INVALID")
        if min(self.maximum_requests,self.maximum_submissions,self.maximum_events,self.maximum_snapshots,self.maximum_cache_entries)<1:errors.append("WORKFLOW_BOUND_INVALID")
        return tuple(dict.fromkeys(errors))

@dataclass(frozen=True)
class WorkflowRequest:
    request_id:str;authorization_id:str;workflow_type:str;subject_id:str;authorized_work:Decimal;requested_work:Decimal
    created_at_utc:datetime;available_at_utc:datetime;expires_at_utc:datetime;idempotency_key:str;payload_fingerprint:str
    configuration_snapshot_id:str;recovery_epoch:int
    @classmethod
    def create(cls,authorization_id,workflow_type,subject_id,authorized_work,requested_work,created_at_utc,payload_fingerprint,configuration_snapshot_id="NEUTRAL_WORKFLOW_DEFAULT",recovery_epoch=0,ttl_seconds=3600):
        authorized=Decimal(str(authorized_work));requested=Decimal(str(requested_work));key=deterministic_id("workflow_idempotency",authorization_id,workflow_type,subject_id,payload_fingerprint,configuration_snapshot_id);rid=deterministic_id("workflow_request",key,str(authorized),str(requested),created_at_utc.isoformat(),recovery_epoch)
        return cls(rid,authorization_id,workflow_type,subject_id,authorized,requested,created_at_utc,created_at_utc,created_at_utc+timedelta(seconds=ttl_seconds),key,payload_fingerprint,configuration_snapshot_id,recovery_epoch)

@dataclass(frozen=True)
class WorkflowValidationResult:
    validation_id:str;request_id:str;valid:bool;authorized_work:Decimal;accepted_work:Decimal;health:WorkflowHealth;reason_codes:tuple[str,...];validated_at_utc:datetime

@dataclass(frozen=True)
class WorkflowIntent:
    intent_id:str;request_id:str;workflow_type:str;subject_id:str;authorized_work:Decimal;planned_work:Decimal;completion_policy:CompletionPolicy;created_at_utc:datetime;configuration_snapshot_id:str

@dataclass(frozen=True)
class WorkflowSubmission:
    submission_id:str;submission_version_id:str;request_id:str;intent_id:str;state:WorkflowState;authorized_work:Decimal;completed_work:Decimal;remaining_work:Decimal
    retry_count:int;last_event_sequence:int;created_at_utc:datetime;updated_at_utc:datetime;timeout_at_utc:datetime;expires_at_utc:datetime
    last_event_id:str|None;health:WorkflowHealth;reason_codes:tuple[str,...];configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class WorkflowCompletionEvent:
    event_id:str;submission_id:str;event_sequence:int;event_type:str;previous_state:WorkflowState;current_state:WorkflowState
    requested_completed_work:Decimal;accepted_completed_work:Decimal;cumulative_completed_work:Decimal;remaining_work:Decimal
    occurred_at_utc:datetime;available_at_utc:datetime;causation_id:str;reason_codes:tuple[str,...];configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class WorkflowSnapshot:
    snapshot_id:str;submission_id:str;submission_version_id:str;state:WorkflowState;authorized_work:Decimal;completed_work:Decimal;remaining_work:Decimal
    event_ids:tuple[str,...];health:WorkflowHealth;as_of_timestamp_utc:datetime;configuration_snapshot_id:str;engine_version:str;recovery_epoch:int

@dataclass(frozen=True)
class WorkflowReconciliationResult:
    reconciliation_id:str;submission_id:str|None;status:ReconciliationStatus;ledger_completed_work:Decimal;state_completed_work:Decimal
    repaired:bool;reason_codes:tuple[str,...];as_of_timestamp_utc:datetime

@dataclass(frozen=True)
class WorkflowProcessingResult:
    submission:WorkflowSubmission|None;events:tuple[WorkflowCompletionEvent,...];outcome:WorkflowOutcome;reason_codes:tuple[str,...];decision_trace:DecisionTrace

class WorkflowEventLedger:
    def __init__(self,maximum_events=2048):self.maximum_events=maximum_events;self.events=OrderedDict();self.by_submission={}
    def append(self,event):
        if event.event_id in self.events:return False
        previous=self.by_submission.get(event.submission_id,())
        if previous and event.event_sequence!=self.events[previous[-1]].event_sequence+1:return False
        if not previous and event.event_sequence!=1:return False
        self.events[event.event_id]=event;self.by_submission[event.submission_id]=previous+(event.event_id,);self._bound();return True
    def _bound(self):
        while len(self.events)>self.maximum_events:
            event_id,event=self.events.popitem(last=False);self.by_submission[event.submission_id]=tuple(x for x in self.by_submission.get(event.submission_id,()) if x!=event_id)

class DeterministicWorkflowEngine:
    def __init__(self,configuration=WorkflowConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self._lock=RLock();self.requests=OrderedDict();self.validations=OrderedDict();self.intents=OrderedDict();self.submissions=OrderedDict();self.submission_versions=OrderedDict();self.snapshots=OrderedDict();self.ledger=WorkflowEventLedger(configuration.maximum_events);self._idempotency={};self._cache=OrderedDict();self.recovery_restricted=False
    @synchronized
    def process(self,request:WorkflowRequest,as_of):
        existing_id=self._idempotency.get(request.idempotency_key)
        if existing_id:
            existing=self.submissions.get(existing_id);return self._result(existing,(),WorkflowOutcome.ACCEPTED,("WORKFLOW_DUPLICATE_REQUEST_IDEMPOTENT",),as_of)
        validation=self.validate(request,as_of)
        if not validation.valid:return self._result(None,(),WorkflowOutcome.NO_ACTION if request.requested_work<=0 else WorkflowOutcome.REJECTED,validation.reason_codes,as_of)
        intent=WorkflowIntent(deterministic_id("workflow_intent",request.request_id,str(validation.accepted_work),self.configuration.completion_policy.name),request.request_id,request.workflow_type,request.subject_id,validation.authorized_work,validation.accepted_work,self.configuration.completion_policy,as_of,self.configuration.configuration_snapshot_id);sid=deterministic_id("workflow_submission",request.idempotency_key,intent.intent_id,self.configuration.configuration_snapshot_id,request.recovery_epoch);version=deterministic_id("workflow_submission_version",sid,WorkflowState.SUBMITTED.name,0,as_of.isoformat())
        submission=WorkflowSubmission(sid,version,request.request_id,intent.intent_id,WorkflowState.SUBMITTED,validation.accepted_work,ZERO,validation.accepted_work,0,0,as_of,as_of,as_of+timedelta(seconds=self.configuration.timeout_seconds),request.expires_at_utc,None,WorkflowHealth.HEALTHY,("WORKFLOW_SUBMITTED",),self.configuration.configuration_snapshot_id,request.recovery_epoch)
        self.requests[request.request_id]=request;self.validations[validation.validation_id]=validation;self.intents[intent.intent_id]=intent;self.submissions[sid]=submission;self.submission_versions[version]=submission;self._idempotency[request.idempotency_key]=sid;self._bound();self._record("workflow_submitted",{"submission_id":sid});return self._result(submission,(),WorkflowOutcome.ACCEPTED,("WORKFLOW_SUBMITTED",),as_of)
    def validate(self,request,as_of):
        reasons=[]
        try:authorized=Decimal(str(request.authorized_work));requested=Decimal(str(request.requested_work))
        except Exception:authorized=requested=ZERO;reasons.append("WORKFLOW_NUMERICAL_INVALID")
        if request.configuration_snapshot_id!=self.configuration.configuration_snapshot_id or request.available_at_utc>as_of:reasons.append("WORKFLOW_LINEAGE_OR_FUTURE_REQUEST")
        if as_of>=request.expires_at_utc:reasons.append("WORKFLOW_REQUEST_EXPIRED")
        if not authorized.is_finite() or not requested.is_finite() or authorized<0 or requested<0:reasons.append("WORKFLOW_NUMERICAL_INVALID")
        if requested>authorized:reasons.append("WORKFLOW_REQUEST_EXCEEDS_AUTHORIZATION")
        if requested>self.configuration.maximum_work:reasons.append("WORKFLOW_MAXIMUM_EXCEEDED")
        if ZERO<requested<self.configuration.minimum_work:reasons.append("WORKFLOW_BELOW_MINIMUM")
        accepted=self._floor(min(max(ZERO,requested),max(ZERO,authorized))) if not reasons else ZERO;valid=not reasons and accepted>0
        if requested==0:reasons.append("WORKFLOW_NO_ACTION")
        vid=deterministic_id("workflow_validation",request.request_id,valid,str(accepted),*reasons,as_of.isoformat());result=WorkflowValidationResult(vid,request.request_id,valid,authorized,accepted,WorkflowHealth.HEALTHY if valid else WorkflowHealth.RESTRICTED,tuple(dict.fromkeys(reasons or ("WORKFLOW_VALID",))),as_of);self.validations[vid]=result;return result
    def acknowledge(self,submission_id,as_of,causation_id="ACK"):
        return self._transition(submission_id,WorkflowState.ACKNOWLEDGED,"ACKNOWLEDGED",ZERO,as_of,causation_id)
    @synchronized
    def complete(self,submission_id,work,as_of,causation_id):
        item=self.submissions.get(submission_id)
        if not item:return self._result(None,(),WorkflowOutcome.INVALID,("WORKFLOW_MISSING_SUBMISSION",),as_of)
        requested=Decimal(str(work))
        if not requested.is_finite() or requested<=0:return self._result(item,(),WorkflowOutcome.INVALID,("WORKFLOW_COMPLETION_INVALID",),as_of)
        accepted=self._floor(min(requested,item.remaining_work));target=WorkflowState.COMPLETED if accepted==item.remaining_work else WorkflowState.PARTIALLY_COMPLETED
        if self.configuration.completion_policy is CompletionPolicy.ALL_OR_NOTHING and accepted!=item.remaining_work:return self._result(item,(),WorkflowOutcome.REJECTED,("WORKFLOW_PARTIAL_NOT_ALLOWED",),as_of)
        return self._transition(submission_id,target,"COMPLETION",accepted,as_of,causation_id,requested)
    def reject(self,submission_id,as_of,reason="WORKFLOW_REJECTED"):return self._transition(submission_id,WorkflowState.REJECTED,"REJECTED",ZERO,as_of,reason)
    def cancel(self,submission_id,as_of,reason="WORKFLOW_CANCELLED"):return self._transition(submission_id,WorkflowState.CANCELLED,"CANCELLED",ZERO,as_of,reason)
    def expire(self,submission_id,as_of):
        item=self.submissions.get(submission_id)
        if not item or as_of<item.expires_at_utc:return self._result(item,(),WorkflowOutcome.NO_ACTION,("WORKFLOW_NOT_EXPIRED",),as_of)
        return self._transition(submission_id,WorkflowState.EXPIRED,"EXPIRED",ZERO,as_of,"EXPIRY")
    def timeout(self,submission_id,as_of):
        item=self.submissions.get(submission_id)
        if not item or as_of<item.timeout_at_utc:return self._result(item,(),WorkflowOutcome.NO_ACTION,("WORKFLOW_NOT_TIMED_OUT",),as_of)
        return self._transition(submission_id,WorkflowState.TIMED_OUT,"TIMED_OUT",ZERO,as_of,"TIMEOUT")
    @synchronized
    def retry(self,submission_id,as_of,retry_class=RetryClass.RETRYABLE):
        item=self.submissions.get(submission_id)
        if not item:return self._result(None,(),WorkflowOutcome.INVALID,("WORKFLOW_MISSING_SUBMISSION",),as_of)
        if retry_class is not RetryClass.RETRYABLE or item.retry_count>=self.configuration.maximum_retries:return self._result(item,(),WorkflowOutcome.REJECTED,("WORKFLOW_RETRY_NOT_ALLOWED",),as_of)
        if item.state not in (WorkflowState.TIMED_OUT,WorkflowState.SUBMITTED,WorkflowState.ACKNOWLEDGED,WorkflowState.PARTIALLY_COMPLETED):return self._result(item,(),WorkflowOutcome.REJECTED,("WORKFLOW_TERMINAL_NO_RETRY",),as_of)
        new=self._version(item,WorkflowState.SUBMITTED,as_of,item.completed_work,item.remaining_work,item.last_event_sequence,item.last_event_id,("WORKFLOW_RETRY",),retry_count=item.retry_count+1);self._save(new);return self._result(new,(),WorkflowOutcome.ACCEPTED,("WORKFLOW_RETRY",),as_of)
    @synchronized
    def snapshot(self,submission_id,as_of):
        versions=[x for x in self.submission_versions.values() if x.submission_id==submission_id and x.updated_at_utc<=as_of];item=max(versions,key=lambda x:(x.updated_at_utc,x.submission_version_id)) if versions else None
        if not item:return None
        events=tuple(x for x in self.ledger.by_submission.get(submission_id,()) if self.ledger.events[x].available_at_utc<=as_of);sid=deterministic_id("workflow_snapshot",item.submission_version_id,*events,as_of.isoformat(),self.configuration.configuration_snapshot_id,item.recovery_epoch);result=WorkflowSnapshot(sid,submission_id,item.submission_version_id,item.state,item.authorized_work,item.completed_work,item.remaining_work,events,item.health,as_of,self.configuration.configuration_snapshot_id,WORKFLOW_ENGINE_VERSION,item.recovery_epoch);self.snapshots[sid]=result;self._bound();return result
    @synchronized
    def reconcile(self,submission_id,as_of,repair=False):
        item=self.submissions.get(submission_id);events=[self.ledger.events[x] for x in self.ledger.by_submission.get(submission_id,())]
        if not item:status=ReconciliationStatus.GHOST_STATE if events else ReconciliationStatus.MISSING_STATE;ledger_work=sum((x.accepted_completed_work for x in events),ZERO);state_work=ZERO
        else:
            ledger_work=sum((x.accepted_completed_work for x in events),ZERO);state_work=item.completed_work
            status=ReconciliationStatus.CONSISTENT if ledger_work==state_work and len(events)==item.last_event_sequence else ReconciliationStatus.COMPLETION_MISMATCH if ledger_work!=state_work else ReconciliationStatus.SEQUENCE_MISMATCH
        rid=deterministic_id("workflow_reconciliation",submission_id,status.name,str(ledger_work),str(state_work),as_of.isoformat());return WorkflowReconciliationResult(rid,submission_id,status,ledger_work,state_work,False,(f"WORKFLOW_RECONCILIATION_{status.name}",),as_of)
    @synchronized
    def _transition(self,submission_id,target,event_type,completed,as_of,causation_id,requested=ZERO):
        item=self.submissions.get(submission_id)
        if not item:return self._result(None,(),WorkflowOutcome.INVALID,("WORKFLOW_MISSING_SUBMISSION",),as_of)
        if item.state in TERMINAL:return self._result(item,(),WorkflowOutcome.NO_ACTION,("WORKFLOW_TERMINAL",),as_of)
        allowed={WorkflowState.SUBMITTED:{WorkflowState.ACKNOWLEDGED,WorkflowState.REJECTED,WorkflowState.CANCELLED,WorkflowState.EXPIRED,WorkflowState.TIMED_OUT},WorkflowState.ACKNOWLEDGED:{WorkflowState.PARTIALLY_COMPLETED,WorkflowState.COMPLETED,WorkflowState.REJECTED,WorkflowState.CANCELLED,WorkflowState.EXPIRED,WorkflowState.TIMED_OUT},WorkflowState.PARTIALLY_COMPLETED:{WorkflowState.PARTIALLY_COMPLETED,WorkflowState.COMPLETED,WorkflowState.CANCELLED,WorkflowState.EXPIRED,WorkflowState.TIMED_OUT},WorkflowState.TIMED_OUT:{WorkflowState.CANCELLED,WorkflowState.EXPIRED}}
        if target not in allowed.get(item.state,set()):return self._result(item,(),WorkflowOutcome.REJECTED,("WORKFLOW_TRANSITION_INVALID",),as_of)
        if as_of<item.updated_at_utc:return self._result(item,(),WorkflowOutcome.INVALID,("WORKFLOW_EVENT_OUT_OF_ORDER",),as_of)
        completed=min(item.remaining_work,self._floor(completed));cumulative=item.completed_work+completed;remaining=item.authorized_work-cumulative;sequence=item.last_event_sequence+1;event_id=deterministic_id("workflow_event",submission_id,sequence,event_type,causation_id,str(completed),as_of.isoformat())
        if event_id in self.ledger.events:return self._result(item,(),WorkflowOutcome.NO_ACTION,("WORKFLOW_DUPLICATE_EVENT",),as_of)
        event=WorkflowCompletionEvent(event_id,submission_id,sequence,event_type,item.state,target,Decimal(str(requested)),completed,cumulative,remaining,as_of,as_of,causation_id,(f"WORKFLOW_{event_type}",),self.configuration.configuration_snapshot_id,item.recovery_epoch)
        if not self.ledger.append(event):return self._result(item,(),WorkflowOutcome.INVALID,("WORKFLOW_EVENT_SEQUENCE_INVALID",),as_of)
        new=self._version(item,target,as_of,cumulative,remaining,sequence,event_id,event.reason_codes);self._save(new);outcome=WorkflowOutcome.COMPLETED if target is WorkflowState.COMPLETED else WorkflowOutcome.PARTIAL if target is WorkflowState.PARTIALLY_COMPLETED else WorkflowOutcome.CANCELLED if target is WorkflowState.CANCELLED else WorkflowOutcome.EXPIRED if target is WorkflowState.EXPIRED else WorkflowOutcome.TIMED_OUT if target is WorkflowState.TIMED_OUT else WorkflowOutcome.REJECTED if target is WorkflowState.REJECTED else WorkflowOutcome.ACCEPTED;self._record("workflow_transition",{"submission_id":submission_id,"state":target.name,"event_id":event_id});return self._result(new,(event,),outcome,event.reason_codes,as_of)
    def _version(self,item,state,as_of,completed,remaining,sequence,event_id,reasons,retry_count=None):
        version=deterministic_id("workflow_submission_version",item.submission_id,item.submission_version_id,state.name,str(completed),sequence,event_id or "NONE",as_of.isoformat());return replace(item,submission_version_id=version,state=state,completed_work=completed,remaining_work=remaining,retry_count=item.retry_count if retry_count is None else retry_count,last_event_sequence=sequence,updated_at_utc=as_of,last_event_id=event_id,reason_codes=tuple(reasons))
    def _save(self,item):self.submissions[item.submission_id]=item;self.submission_versions[item.submission_version_id]=item;self._bound()
    def _result(self,submission,events,outcome,reasons,as_of):
        correlation=submission.submission_id if submission else deterministic_id("workflow_no_submission",*reasons,as_of.isoformat());did=deterministic_id("workflow_decision",correlation,outcome.name,*reasons,as_of.isoformat());status=DecisionStatus.PASSED if outcome in (WorkflowOutcome.ACCEPTED,WorkflowOutcome.PARTIAL,WorkflowOutcome.COMPLETED,WorkflowOutcome.NO_ACTION) else DecisionStatus.FAILED;trace=DecisionTrace(did,correlation,as_of,(DecisionEvaluation("WORKFLOW_STATE",status,reasons[-1],"Neutral deterministic workflow transition evaluated",tuple(x.event_id for x in events)),),DecisionOutcome.ACCEPTED if status is DecisionStatus.PASSED and outcome is not WorkflowOutcome.NO_ACTION else DecisionOutcome.NO_ACTION,reasons[-1],as_of,"WORKFLOW_STATE" if status is DecisionStatus.FAILED else None);return WorkflowProcessingResult(submission,tuple(events),outcome,tuple(reasons),trace)
    @synchronized
    def recovery_state(self):return {"schema_version":RECOVERY_SCHEMA_VERSION,"engine_version":WORKFLOW_ENGINE_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"requests":tuple(self.requests.values()),"validations":tuple(self.validations.values()),"intents":tuple(self.intents.values()),"submissions":tuple(self.submissions.values()),"submission_versions":tuple(self.submission_versions.values()),"events":tuple(self.ledger.events.values()),"idempotency":tuple(self._idempotency.items())}
    @synchronized
    def restore(self,state):
        if state.get("schema_version")!=RECOVERY_SCHEMA_VERSION or state.get("engine_version")!=WORKFLOW_ENGINE_VERSION or state.get("configuration_snapshot_id")!=self.configuration.configuration_snapshot_id:self.recovery_restricted=True;return False
        try:
            requests=tuple(state.get("requests",()));submissions=tuple(state.get("submissions",()));versions=tuple(state.get("submission_versions",()));events=tuple(state.get("events",()))
            if len({x.request_id for x in requests})!=len(requests) or len({x.submission_id for x in submissions})!=len(submissions) or len({x.submission_version_id for x in versions})!=len(versions):raise ValueError
            ledger=WorkflowEventLedger(self.configuration.maximum_events)
            for event in sorted(events,key=lambda x:(x.submission_id,x.event_sequence)):
                if not ledger.append(event):raise ValueError
            for item in submissions:
                item_events=[ledger.events[x] for x in ledger.by_submission.get(item.submission_id,())]
                recovered=sum((x.accepted_completed_work for x in item_events),ZERO)
                if recovered!=item.completed_work or len(item_events)!=item.last_event_sequence or item.completed_work<0 or item.completed_work>item.authorized_work or item.remaining_work!=item.authorized_work-item.completed_work:raise ValueError
            known={x.submission_id for x in submissions}
            if any(event.submission_id not in known for event in events):raise ValueError
            self.requests=OrderedDict((x.request_id,x) for x in requests);self.validations=OrderedDict((x.validation_id,x) for x in state.get("validations",()));self.intents=OrderedDict((x.intent_id,x) for x in state.get("intents",()));self.submissions=OrderedDict((x.submission_id,x) for x in submissions);self.submission_versions=OrderedDict((x.submission_version_id,x) for x in versions);self.ledger=ledger;self._idempotency=dict(state.get("idempotency",()));self.recovery_restricted=False;return True
        except Exception:self.recovery_restricted=True;return False
    def _floor(self,value):
        step=self.configuration.work_step
        with localcontext() as ctx:ctx.prec=28;return (Decimal(str(value))/step).to_integral_value(rounding=ROUND_FLOOR)*step
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def _bound(self):
        for store,limit in ((self.requests,self.configuration.maximum_requests),(self.validations,self.configuration.maximum_requests),(self.intents,self.configuration.maximum_requests),(self.submissions,self.configuration.maximum_submissions),(self.submission_versions,self.configuration.maximum_submissions*8),(self.snapshots,self.configuration.maximum_snapshots),(self._cache,self.configuration.maximum_cache_entries)):
            while len(store)>limit:store.popitem(last=False)
