"""Immutable dashboard composition over authoritative upstream snapshots."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass,replace
from datetime import datetime,timedelta
from decimal import Decimal
from enum import Enum,auto
from threading import RLock
from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace
from amrte.analytics.performance import PhaseVIIIAnalyticsSnapshot,ResearchPerformanceSummary

VERSION="1.0";SCHEMA="1.0";ONE=Decimal("1");ZERO=Decimal("0")
class DashboardStatus(Enum):HEALTHY=auto();CAUTION=auto();RESTRICTED=auto();SUSPENDED=auto();RECOVERY_PENDING=auto();DEGRADED=auto();PARTIAL=auto();STALE=auto();UNKNOWN=auto()
class AlertSeverity(Enum):INFO=auto();NOTICE=auto();WARNING=auto();CRITICAL=auto()
class AlertAcknowledgement(Enum):UNACKNOWLEDGED=auto();ACKNOWLEDGED=auto()
class AlertResolution(Enum):ACTIVE=auto();RESOLVED_BY_SOURCE=auto()
class ControlAction(Enum):PAUSE_RESEARCH=auto();RESUME_RESEARCH=auto();REFRESH=auto();REQUEST_RECONCILIATION=auto();REQUEST_DIAGNOSTICS=auto();ACKNOWLEDGE_ALERT=auto();EXPORT_RESEARCH=auto();CHANGE_PREFERENCES=auto()
class ControlOutcome(Enum):ACCEPTED=auto();REJECTED=auto();NO_ACTION=auto();CONFLICT=auto();STALE_REQUEST=auto();FAILED_CLOSED=auto()
class DashboardPermission(Enum):VIEW_DASHBOARD=auto();VIEW_DIAGNOSTICS=auto();VIEW_AUDIT=auto();ACKNOWLEDGE_ALERT=auto();REQUEST_RECONCILIATION=auto();PAUSE_RESEARCH=auto();RESUME_RESEARCH=auto();EXPORT_RESEARCH_DATA=auto();CHANGE_DASHBOARD_PREFERENCES=auto()

@dataclass(frozen=True)
class DashboardConfiguration:
    stale_after:timedelta=timedelta(minutes=15);maximum_snapshots:int=1024;maximum_alerts:int=1024;maximum_controls:int=1024;maximum_preferences:int=64;configuration_snapshot_id:str="NEUTRAL_DASHBOARD_DEFAULT"
    def validate(self):
        errors=[]
        if self.stale_after<=timedelta(0):errors.append("DASHBOARD_STALE_THRESHOLD_INVALID")
        if min(self.maximum_snapshots,self.maximum_alerts,self.maximum_controls,self.maximum_preferences)<1:errors.append("DASHBOARD_BOUND_INVALID")
        return tuple(errors)
@dataclass(frozen=True)
class DashboardSourceSnapshot:
    source_module:str;snapshot_id:str;as_of_time_utc:datetime;dataset_fingerprint:str;configuration_snapshot_id:str;recovery_epoch:int;health_state:str;published_state:str;reason_codes:tuple[str,...]=();trace_id:str|None=None;payload:tuple[tuple[str,object],...]=()
    def get(self,key,default=None):return dict(self.payload).get(key,default)
@dataclass(frozen=True)
class AMRTESystemStatusView:
    state:DashboardStatus;research_mode:str;version:str;as_of_time_utc:datetime;stale:bool;operator_attention_required:bool;reason_codes:tuple[str,...]
@dataclass(frozen=True)
class ProtectionStatusCard:
    reliability_state:str;temporal_state:str;cooldown_state:str;systemic_state:str;effective_research_permission:Decimal;restriction_reasons:tuple[str,...];since_timestamp_utc:datetime|None
@dataclass(frozen=True)
class MarketRegimeCard:
    current_regime:str;confidence:object;regime_since_utc:datetime|None;previous_regime:str;transition_state:str;data_timestamp_utc:datetime
@dataclass(frozen=True)
class ResearchSessionCard:
    research_session:str;session_state:str;research_clock_utc:datetime;calendar_context:str
@dataclass(frozen=True)
class ActiveResearchProfileCard:
    profile_name:str;profile_version:str;configuration_snapshot_id:str;activation_time_utc:datetime|None;profile_status:str
@dataclass(frozen=True)
class StrategyHealthItem:
    strategy_id:str;strategy_version:str;variant:str;health_state:str;published_health_state:str;permission_multiplier:Decimal;observation_count:int;sample_adequacy:str;health_since_utc:datetime|None;last_evaluation_utc:datetime;reason_codes:tuple[str,...]
@dataclass(frozen=True)
class ResearchPerformancePanel:
    source_snapshot_id:str;summary:ResearchPerformanceSummary;analytics_trend_state:str;rolling_snapshot_ids:tuple[str,...];daily_snapshot_id:str|None;weekly_snapshot_id:str|None
@dataclass(frozen=True)
class ResearchLifecyclePanel:
    total:int;state_counts:tuple[tuple[str,int],...];hypothesis_references:tuple[str,...]
@dataclass(frozen=True)
class ResearchDataHealthPanel:
    health:str;freshness:str;integrity:str;missing_count:int;invalid_count:int;out_of_order_count:int;last_valid_observation_utc:datetime|None
@dataclass(frozen=True)
class SystemDiagnosticsPanel:
    engine_version:str;recovery_epoch:int;configuration_snapshot_id:str;dataset_fingerprint:str;latest_snapshot_utc:datetime;audit_health:str;persistence_health:str;module_health:tuple[tuple[str,str],...];replay_fingerprints:tuple[str,...]
@dataclass(frozen=True)
class DashboardAlert:
    alert_id:str;severity:AlertSeverity;category:str;source_module:str;source_event_id:str;title:str;summary:str;reason_codes:tuple[str,...];created_at_utc:datetime;known_at_utc:datetime;acknowledgement_state:AlertAcknowledgement;resolution_state:AlertResolution;related_trace_id:str|None;occurrence_count:int=1
@dataclass(frozen=True)
class DashboardAlertSummary:
    active_count:int;critical_count:int;unacknowledged_count:int;alert_ids:tuple[str,...]
@dataclass(frozen=True)
class AMRTEDashboardSnapshot:
    snapshot_id:str;as_of_time_utc:datetime;view_mode:str;system_status:AMRTESystemStatusView;data_health:ResearchDataHealthPanel;market_regime:MarketRegimeCard;session_context:ResearchSessionCard;event_context:tuple[tuple[str,object],...];active_research_profile:ActiveResearchProfileCard;strategy_health_summary:tuple[StrategyHealthItem,...];workflow_health:str;observation_quality:str;lifecycle_summary:ResearchLifecyclePanel;protection_status:ProtectionStatusCard;research_performance_summary:ResearchPerformancePanel;alert_summary:DashboardAlertSummary;diagnostic_summary:SystemDiagnosticsPanel;configuration_snapshot_id:str;dataset_fingerprint:str;source_snapshot_ids:tuple[str,...];source_fingerprint:str;engine_version:str;recovery_epoch:int;generated_at_utc:datetime
@dataclass(frozen=True)
class DashboardControlRequest:
    request_id:str;action_type:ControlAction;requested_at_utc:datetime;requested_by:str;target_scope:str;expected_state_version:int;configuration_snapshot_id:str;operator_reason:str;confirmed:bool
    @classmethod
    def create(cls,action_type,requested_at_utc,requested_by,target_scope,expected_state_version,configuration_snapshot_id,operator_reason="",confirmed=False,nonce=""):
        rid=deterministic_id("dashboard_control",action_type.name,requested_at_utc.isoformat(),requested_by,target_scope,expected_state_version,configuration_snapshot_id,operator_reason,confirmed,nonce);return cls(rid,action_type,requested_at_utc,requested_by,target_scope,expected_state_version,configuration_snapshot_id,operator_reason,confirmed)
@dataclass(frozen=True)
class DashboardControlResult:
    request_id:str;outcome:ControlOutcome;reason_codes:tuple[str,...];before_snapshot_id:str|None;after_snapshot_id:str|None;completed_at_utc:datetime;audit_event_id:str;trace_id:str
@dataclass(frozen=True)
class DashboardPreference:
    user_id:str;layout:str;visible_cards:tuple[str,...];theme:str;refresh_seconds:int;updated_at_utc:datetime
@dataclass(frozen=True)
class DashboardRecovery:
    schema_version:str;engine_version:str;configuration_snapshot_id:str;recovery_epoch:int;paused:bool;state_version:int;alerts:tuple[DashboardAlert,...];control_results:tuple[DashboardControlResult,...];preferences:tuple[DashboardPreference,...];snapshots:tuple[AMRTEDashboardSnapshot,...]

class DashboardSnapshotAggregator:
    REQUIRED=("DATA","REGIME","SESSION","PROFILE","LIFECYCLE","WORKFLOW","QUALITY","RELIABILITY","TEMPORAL","SYSTEM_SAFETY")
    def __init__(self,configuration=DashboardConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self._lock=RLock();self.snapshots=OrderedDict();self.alerts=OrderedDict();self.control_results=OrderedDict();self.preferences=OrderedDict();self.paused=False;self.state_version=0;self.recovery_restricted=False
    def aggregate(self,sources,analytics,as_of,generated_at,recovery_epoch=0):
        with self._lock:
            source_map={x.source_module:x for x in sources};reasons=[];required=[source_map.get(x) for x in self.REQUIRED]
            if any(x is None for x in required):reasons.append("DASHBOARD_SOURCE_MISSING")
            available=[x for x in required if x is not None];datasets={x.dataset_fingerprint for x in available};configs={x.configuration_snapshot_id for x in available};epochs={x.recovery_epoch for x in available}
            if len(datasets)>1 or (analytics and analytics.dataset_fingerprint not in datasets):reasons.append("DASHBOARD_DATASET_MISMATCH")
            if len(configs)>1 or (analytics and analytics.configuration_snapshot_id not in configs):reasons.append("DASHBOARD_CONFIGURATION_MISMATCH")
            if len(epochs)>1 or any(x.as_of_time_utc>as_of for x in available) or (analytics and analytics.as_of_time_utc>as_of):reasons.append("DASHBOARD_TEMPORAL_OR_EPOCH_MISMATCH")
            stale=generated_at-as_of>self.configuration.stale_after or any(generated_at-x.as_of_time_utc>self.configuration.stale_after for x in available)
            if stale:reasons.append("DASHBOARD_STALE")
            severe=self._most_restrictive(tuple(x.published_state for x in available));status=DashboardStatus.DEGRADED if any("MISMATCH" in x or "MISSING" in x for x in reasons) else DashboardStatus.STALE if stale else severe
            system=AMRTESystemStatusView(status,"RESEARCH-ONLY",VERSION,as_of,stale,status is not DashboardStatus.HEALTHY,tuple(reasons))
            protection=self._protection(source_map,as_of);data=self._data(source_map.get("DATA"));regime=self._regime(source_map.get("REGIME"),as_of);session=self._session(source_map.get("SESSION"),as_of);profile=self._profile(source_map.get("PROFILE"));strategies=self._strategies(source_map.get("STRATEGY_HEALTH"),as_of);lifecycle=self._lifecycle(source_map.get("LIFECYCLE"));performance=self._performance(analytics);diagnostics=self._diagnostics(available,analytics,as_of,recovery_epoch)
            self._derive_alerts(available,reasons,as_of)
            active=tuple(x for x in self.alerts.values() if x.resolution_state is AlertResolution.ACTIVE);alert_summary=DashboardAlertSummary(len(active),sum(x.severity is AlertSeverity.CRITICAL for x in active),sum(x.acknowledgement_state is AlertAcknowledgement.UNACKNOWLEDGED for x in active),tuple(x.alert_id for x in active))
            source_ids=tuple(sorted(x.snapshot_id for x in available))+((analytics.snapshot_id,) if analytics else ());fingerprint=deterministic_id("dashboard_source",*source_ids,*reasons,as_of.isoformat());snapshot_id=deterministic_id("amrte_dashboard",fingerprint,self.state_version,recovery_epoch)
            snapshot=AMRTEDashboardSnapshot(snapshot_id,as_of,"HISTORICAL_AS_OF" if generated_at>as_of else "CURRENT",system,data,regime,session,source_map.get("EVENTS").payload if source_map.get("EVENTS") else (),profile,strategies,source_map.get("WORKFLOW").published_state if source_map.get("WORKFLOW") else "UNKNOWN",source_map.get("QUALITY").published_state if source_map.get("QUALITY") else "UNKNOWN",lifecycle,protection,performance,alert_summary,diagnostics,next(iter(configs),self.configuration.configuration_snapshot_id),next(iter(datasets),"UNKNOWN"),source_ids,fingerprint,VERSION,recovery_epoch,generated_at)
            self.snapshots[snapshot_id]=snapshot
            while len(self.snapshots)>self.configuration.maximum_snapshots:self.snapshots.popitem(last=False)
            self._record("dashboard_snapshot_created",{"snapshot_id":snapshot_id,"status":status.name});return snapshot
    def acknowledge_alert(self,alert_id,actor,at):
        with self._lock:
            alert=self.alerts.get(alert_id)
            if not alert or not actor:return False
            self.alerts[alert_id]=replace(alert,acknowledgement_state=AlertAcknowledgement.ACKNOWLEDGED);self._record("dashboard_alert_acknowledged",{"alert_id":alert_id,"actor":actor,"at":at.isoformat()});return True
    def resolve_alert_from_source(self,alert_id,at):
        with self._lock:
            alert=self.alerts.get(alert_id)
            if not alert:return False
            self.alerts[alert_id]=replace(alert,resolution_state=AlertResolution.RESOLVED_BY_SOURCE);return True
    def process_control(self,request,permissions,current_snapshot,safety_permission=ONE):
        with self._lock:
            if request.request_id in self.control_results:return self.control_results[request.request_id]
            outcome=ControlOutcome.ACCEPTED;reasons=[]
            required={ControlAction.PAUSE_RESEARCH:DashboardPermission.PAUSE_RESEARCH,ControlAction.RESUME_RESEARCH:DashboardPermission.RESUME_RESEARCH,ControlAction.REQUEST_RECONCILIATION:DashboardPermission.REQUEST_RECONCILIATION,ControlAction.ACKNOWLEDGE_ALERT:DashboardPermission.ACKNOWLEDGE_ALERT,ControlAction.EXPORT_RESEARCH:DashboardPermission.EXPORT_RESEARCH_DATA,ControlAction.CHANGE_PREFERENCES:DashboardPermission.CHANGE_DASHBOARD_PREFERENCES}.get(request.action_type,DashboardPermission.VIEW_DASHBOARD)
            if required not in permissions:outcome=ControlOutcome.REJECTED;reasons.append("DASHBOARD_PERMISSION_DENIED")
            elif request.expected_state_version!=self.state_version:outcome=ControlOutcome.STALE_REQUEST;reasons.append("DASHBOARD_STATE_VERSION_STALE")
            elif request.configuration_snapshot_id!=current_snapshot.configuration_snapshot_id:outcome=ControlOutcome.CONFLICT;reasons.append("DASHBOARD_CONFIGURATION_CONFLICT")
            elif request.action_type in (ControlAction.PAUSE_RESEARCH,ControlAction.RESUME_RESEARCH,ControlAction.REQUEST_RECONCILIATION) and (not request.confirmed or not request.operator_reason):outcome=ControlOutcome.REJECTED;reasons.append("DASHBOARD_CONFIRMATION_REQUIRED")
            elif request.action_type is ControlAction.RESUME_RESEARCH and (Decimal(str(safety_permission))<ONE or current_snapshot.system_status.state is not DashboardStatus.HEALTHY):outcome=ControlOutcome.REJECTED;reasons.append("DASHBOARD_RESUME_BLOCKED_BY_AUTHORITY")
            elif request.action_type is ControlAction.PAUSE_RESEARCH:
                if self.paused:outcome=ControlOutcome.NO_ACTION;reasons.append("DASHBOARD_ALREADY_PAUSED")
                else:self.paused=True;self.state_version+=1;reasons.append("DASHBOARD_RESEARCH_PAUSED")
            elif request.action_type is ControlAction.RESUME_RESEARCH:
                if not self.paused:outcome=ControlOutcome.NO_ACTION;reasons.append("DASHBOARD_ALREADY_RESUMED")
                else:self.paused=False;self.state_version+=1;reasons.append("DASHBOARD_RESEARCH_RESUMED")
            else:reasons.append("DASHBOARD_REQUEST_ACCEPTED")
            completed=request.requested_at_utc;trace=self._trace(request,outcome,tuple(reasons));audit_id=deterministic_id("dashboard_control_audit",request.request_id,outcome.name,*reasons);result=DashboardControlResult(request.request_id,outcome,tuple(reasons),current_snapshot.snapshot_id,current_snapshot.snapshot_id,completed,audit_id,trace.decision_id);self.control_results[request.request_id]=result
            while len(self.control_results)>self.configuration.maximum_controls:self.control_results.popitem(last=False)
            self._record("dashboard_control_processed",{"request_id":request.request_id,"outcome":outcome.name,"actor":request.requested_by});return result
    def set_preference(self,preference):
        if preference.refresh_seconds<0 or not preference.user_id:raise ValueError("DASHBOARD_PREFERENCE_INVALID")
        self.preferences[preference.user_id]=preference
        while len(self.preferences)>self.configuration.maximum_preferences:self.preferences.popitem(last=False)
    def export_view(self,snapshot):
        return {"snapshot_id":snapshot.snapshot_id,"generated_at_utc":snapshot.generated_at_utc.isoformat(),"as_of_time_utc":snapshot.as_of_time_utc.isoformat(),"dataset_fingerprint":snapshot.dataset_fingerprint,"configuration_snapshot_id":snapshot.configuration_snapshot_id,"engine_version":snapshot.engine_version,"source_fingerprint":snapshot.source_fingerprint,"research_mode":"RESEARCH-ONLY"}
    def recovery_state(self,epoch):return DashboardRecovery(SCHEMA,VERSION,self.configuration.configuration_snapshot_id,epoch,self.paused,self.state_version,tuple(self.alerts.values()),tuple(self.control_results.values()),tuple(self.preferences.values()),tuple(self.snapshots.values()))
    def restore(self,state,epoch):
        with self._lock:
            if state.schema_version!=SCHEMA or state.engine_version!=VERSION or state.configuration_snapshot_id!=self.configuration.configuration_snapshot_id or state.recovery_epoch!=epoch:self.recovery_restricted=True;return False
            try:
                if len({x.alert_id for x in state.alerts})!=len(state.alerts) or len({x.request_id for x in state.control_results})!=len(state.control_results) or len({x.snapshot_id for x in state.snapshots})!=len(state.snapshots):raise ValueError
                self.paused=state.paused;self.state_version=state.state_version;self.alerts=OrderedDict((x.alert_id,x) for x in state.alerts);self.control_results=OrderedDict((x.request_id,x) for x in state.control_results);self.preferences=OrderedDict((x.user_id,x) for x in state.preferences);self.snapshots=OrderedDict((x.snapshot_id,x) for x in state.snapshots);self.recovery_restricted=False;return True
            except Exception:self.recovery_restricted=True;return False
    def replay_fingerprint(self):return deterministic_id("dashboard_replay",self.paused,self.state_version,*self.alerts,*self.control_results,*self.snapshots)
    def inspect_trace(self,trace):return trace
    def _protection(self,s,as_of):
        a=s.get("RELIABILITY");b=s.get("TEMPORAL");c=s.get("SYSTEM_SAFETY");permission=min((Decimal(str(x.get("permission_multiplier",ZERO))) for x in (a,b,c) if x),default=ZERO);reasons=tuple(sorted({r for x in (a,b,c) if x for r in x.reason_codes}));since=min((x.get("since",x.as_of_time_utc) for x in (a,b,c) if x),default=None);return ProtectionStatusCard(a.published_state if a else "UNKNOWN",b.published_state if b else "UNKNOWN",b.get("cooldown_state","UNKNOWN") if b else "UNKNOWN",c.published_state if c else "UNKNOWN",permission,reasons,since)
    @staticmethod
    def _data(x):return ResearchDataHealthPanel(x.published_state if x else "UNKNOWN",x.get("freshness","UNKNOWN") if x else "UNKNOWN",x.get("integrity","UNKNOWN") if x else "UNKNOWN",int(x.get("missing_count",0)) if x else 0,int(x.get("invalid_count",0)) if x else 0,int(x.get("out_of_order_count",0)) if x else 0,x.get("last_valid") if x else None)
    @staticmethod
    def _regime(x,as_of):return MarketRegimeCard(x.get("current_regime",x.published_state) if x else "UNKNOWN",x.get("confidence") if x else None,x.get("since") if x else None,x.get("previous_regime","UNKNOWN") if x else "UNKNOWN",x.get("transition","UNKNOWN") if x else "UNKNOWN",x.as_of_time_utc if x else as_of)
    @staticmethod
    def _session(x,as_of):return ResearchSessionCard(x.get("session",x.published_state) if x else "UNKNOWN",x.published_state if x else "UNKNOWN",x.get("research_clock",as_of) if x else as_of,x.get("calendar_context","UNKNOWN") if x else "UNKNOWN")
    @staticmethod
    def _profile(x):return ActiveResearchProfileCard(x.get("name","UNKNOWN") if x else "UNKNOWN",x.get("version","UNKNOWN") if x else "UNKNOWN",x.configuration_snapshot_id if x else "UNKNOWN",x.get("activated_at") if x else None,x.published_state if x else "UNKNOWN")
    @staticmethod
    def _strategies(x,as_of):
        return tuple(StrategyHealthItem(str(y.get("strategy_id","UNKNOWN")),str(y.get("version","UNKNOWN")),str(y.get("variant","UNKNOWN")),str(y.get("health","UNKNOWN")),str(y.get("published_health","UNKNOWN")),Decimal(str(y.get("permission_multiplier",ZERO))),int(y.get("observation_count",0)),str(y.get("sample_adequacy","UNKNOWN")),y.get("health_since"),y.get("last_evaluation",as_of),tuple(y.get("reason_codes",()))) for y in (x.get("items",()) if x else ()))
    @staticmethod
    def _lifecycle(x):
        counts=tuple(sorted(x.get("state_counts",()) if x else ()));return ResearchLifecyclePanel(sum(v for _,v in counts),counts,tuple(x.get("hypothesis_references",())) if x else ())
    @staticmethod
    def _performance(a):
        if not a:raise ValueError("DASHBOARD_ANALYTICS_REQUIRED")
        return ResearchPerformancePanel(a.snapshot_id,a.global_performance_summary,"AUTHORITATIVE",a.rolling_analytics_references,None,None)
    @staticmethod
    def _diagnostics(sources,a,as_of,epoch):return SystemDiagnosticsPanel(VERSION,epoch,sources[0].configuration_snapshot_id if sources else "UNKNOWN",sources[0].dataset_fingerprint if sources else "UNKNOWN",as_of,"UNKNOWN","UNKNOWN",tuple(sorted((x.source_module,x.health_state) for x in sources)),(a.source_fingerprint,) if a else ())
    def _derive_alerts(self,sources,reasons,as_of):
        candidates=[(x.source_module,x.snapshot_id,x.published_state,x.reason_codes,x.trace_id) for x in sources if self._status(x.published_state) is not DashboardStatus.HEALTHY]+[("DASHBOARD",deterministic_id("dashboard_consistency",*reasons),"DEGRADED",tuple(reasons),None)] if reasons else [(x.source_module,x.snapshot_id,x.published_state,x.reason_codes,x.trace_id) for x in sources if self._status(x.published_state) is not DashboardStatus.HEALTHY]
        for module,event,state,codes,trace in candidates:
            aid=deterministic_id("dashboard_alert",module,event,*codes);existing=self.alerts.get(aid);severity=AlertSeverity.CRITICAL if self._status(state) in (DashboardStatus.SUSPENDED,DashboardStatus.RESTRICTED) else AlertSeverity.WARNING
            self.alerts[aid]=replace(existing,occurrence_count=existing.occurrence_count+1,known_at_utc=as_of) if existing else DashboardAlert(aid,severity,module,module,event,f"{module} attention",state,tuple(codes),as_of,as_of,AlertAcknowledgement.UNACKNOWLEDGED,AlertResolution.ACTIVE,trace)
        while len(self.alerts)>self.configuration.maximum_alerts:self.alerts.popitem(last=False)
    @staticmethod
    def _status(value):
        v=str(value).upper();return DashboardStatus.SUSPENDED if any(x in v for x in ("EMERGENCY","SUSPENDED","CIRCUIT_OPEN","BLOCKED")) else DashboardStatus.RECOVERY_PENDING if "RECOVERY" in v else DashboardStatus.RESTRICTED if any(x in v for x in ("RESTRICTED","PROTECTED")) else DashboardStatus.CAUTION if any(x in v for x in ("CAUTION","WATCH","DEGRADED","LIMITED")) else DashboardStatus.HEALTHY if any(x in v for x in ("HEALTHY","NORMAL","VALID","AVAILABLE","ACTIVE")) else DashboardStatus.UNKNOWN
    @classmethod
    def _most_restrictive(cls,states):
        rank={DashboardStatus.HEALTHY:0,DashboardStatus.CAUTION:1,DashboardStatus.PARTIAL:2,DashboardStatus.RESTRICTED:3,DashboardStatus.RECOVERY_PENDING:4,DashboardStatus.SUSPENDED:5,DashboardStatus.STALE:6,DashboardStatus.DEGRADED:7,DashboardStatus.UNKNOWN:8};return max((cls._status(x) for x in states),key=lambda x:rank[x],default=DashboardStatus.UNKNOWN)
    @staticmethod
    def _trace(request,outcome,reasons):
        passed=outcome in (ControlOutcome.ACCEPTED,ControlOutcome.NO_ACTION);evaluation=DecisionEvaluation("DASHBOARD_CONTROL",DecisionStatus.PASSED if passed else DecisionStatus.FAILED,reasons[-1],"Governed neutral dashboard control evaluated",());trace_id=deterministic_id("dashboard_control_trace",request.request_id,outcome.name,*reasons);return DecisionTrace(trace_id,request.request_id,request.requested_at_utc,(evaluation,),DecisionOutcome.ACCEPTED if outcome is ControlOutcome.ACCEPTED else DecisionOutcome.NO_ACTION if outcome is ControlOutcome.NO_ACTION else DecisionOutcome.BLOCKED,reasons[-1],request.requested_at_utc,None if passed else "DASHBOARD")
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
