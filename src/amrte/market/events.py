from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol

from amrte.core.identity import deterministic_id
from amrte.core.interfaces import IAuditSink, IClock
from amrte.core.observability import DecisionTraceBuilder
from amrte.core.observability_types import DecisionOutcome, DecisionStatus, DecisionTrace
from .session import TimeHealth, TimeZoneService

NEWS_RISK_ENGINE_VERSION="1.0"
EVENT_SCHEMA_VERSION="1.0"


class EventProviderHealth(Enum): HEALTHY=auto(); DEGRADED=auto(); STALE=auto(); INCOMPLETE=auto(); UNAVAILABLE=auto(); INVALID=auto(); UNKNOWN=auto()
class EventCategory(Enum): CENTRAL_BANK_RATE_DECISION=auto(); MONETARY_POLICY_STATEMENT=auto(); INFLATION=auto(); EMPLOYMENT=auto(); GDP=auto(); RETAIL_ACTIVITY=auto(); BUSINESS_ACTIVITY=auto(); TRADE=auto(); HOUSING=auto(); MAJOR_SPEECH=auto(); OTHER_SCHEDULED_MACRO=auto(); UNKNOWN=auto()
class EventImportance(Enum): LOW=1; MEDIUM=2; HIGH=3; CRITICAL=4; UNKNOWN=5
class EconomicEventStatus(Enum): SCHEDULED=auto(); CONFIRMED=auto(); RESCHEDULED=auto(); POSTPONED=auto(); CANCELLED=auto(); RELEASED=auto(); REVISED=auto(); UNKNOWN=auto()
class NewsRiskState(Enum): CLEAR=auto(); UPCOMING_LOW=auto(); UPCOMING_MEDIUM=auto(); UPCOMING_HIGH=auto(); UPCOMING_CRITICAL=auto(); BLACKOUT=auto(); POST_EVENT_STABILIZATION=auto(); DATA_UNAVAILABLE=auto(); DATA_STALE=auto(); INCOMPLETE_COVERAGE=auto(); UNKNOWN=auto()
class NewsRiskHealth(Enum): HEALTHY=auto(); DEGRADED=auto(); RESTRICTED=auto(); STALE=auto(); INCOMPLETE=auto(); UNAVAILABLE=auto(); INVALID=auto(); UNKNOWN=auto()
class NewsPolicyState(Enum): ALLOW_CONTEXT=auto(); RESTRICT_CONTEXT=auto(); BLOCK_NEW_RESEARCH_EXPOSURE=auto(); MANAGEMENT_ONLY_REFERENCE=auto(); UNKNOWN=auto()
class EventEligibility(Enum): ELIGIBLE=auto(); CONDITIONAL=auto(); RESTRICTED=auto(); BLOCKED=auto(); UNKNOWN=auto()


@dataclass(frozen=True)
class EventDatasetProvenance:
    event_dataset_id:str; provider_id:str; provider_version:str; dataset_fingerprint:str
    coverage_start_utc:datetime; coverage_end_utc:datetime; imported_at_utc:datetime
    source_description:str; schema_version:str=EVENT_SCHEMA_VERSION; configuration_snapshot_id:str=""


@dataclass(frozen=True)
class EconomicEvent:
    logical_event_id:str; event_version_id:str; provider_event_id:str; event_name:str
    event_category:EventCategory; country:str; affected_dimensions:tuple[str,...]
    scheduled_time_utc:datetime; first_known_at_utc:datetime; last_updated_at_utc:datetime
    importance:EventImportance; forecast:str|float|None=None; previous:str|float|None=None
    actual:str|float|None=None; forecast_available_at_utc:datetime|None=None
    previous_available_at_utc:datetime|None=None; actual_available_at_utc:datetime|None=None
    event_status:EconomicEventStatus=EconomicEventStatus.SCHEDULED; provider_id:str=""
    dataset_id:str=""; dataset_fingerprint:str=""; revision:int=0
    supersedes_event_version_id:str|None=None; metadata:Mapping[str,object]|None=None

    def __post_init__(self):
        object.__setattr__(self,"metadata",MappingProxyType(dict(self.metadata or {})))

    def visible_at(self,as_of:datetime)->"EconomicEvent|None":
        if self.first_known_at_utc>as_of or self.last_updated_at_utc>as_of:return None
        return EconomicEvent(self.logical_event_id,self.event_version_id,self.provider_event_id,self.event_name,
            self.event_category,self.country,self.affected_dimensions,self.scheduled_time_utc,self.first_known_at_utc,
            self.last_updated_at_utc,self.importance,
            self.forecast if self.forecast_available_at_utc and self.forecast_available_at_utc<=as_of else None,
            self.previous if self.previous_available_at_utc and self.previous_available_at_utc<=as_of else None,
            self.actual if self.actual_available_at_utc and self.actual_available_at_utc<=as_of else None,
            self.forecast_available_at_utc,self.previous_available_at_utc,self.actual_available_at_utc,self.event_status,
            self.provider_id,self.dataset_id,self.dataset_fingerprint,self.revision,self.supersedes_event_version_id,self.metadata)


def event_dataset_fingerprint(events:Iterable[EconomicEvent],provider_id:str,provider_version:str)->str:
    payload=[]
    for event in sorted(events,key=lambda item:item.event_version_id):
        payload.append({"logical":event.logical_event_id,"version":event.event_version_id,"provider_event":event.provider_event_id,
            "name":event.event_name,"category":event.event_category.name,"country":event.country,"dimensions":list(event.affected_dimensions),
            "scheduled":event.scheduled_time_utc.astimezone(timezone.utc).isoformat(),"first_known":event.first_known_at_utc.astimezone(timezone.utc).isoformat(),
            "updated":event.last_updated_at_utc.astimezone(timezone.utc).isoformat(),"importance":event.importance.name,
            "forecast":event.forecast,"previous":event.previous,"actual":event.actual,
            "forecast_at":event.forecast_available_at_utc.isoformat() if event.forecast_available_at_utc else None,
            "previous_at":event.previous_available_at_utc.isoformat() if event.previous_available_at_utc else None,
            "actual_at":event.actual_available_at_utc.isoformat() if event.actual_available_at_utc else None,
            "status":event.event_status.name,"revision":event.revision,"supersedes":event.supersedes_event_version_id})
    encoded=json.dumps({"provider_id":provider_id,"provider_version":provider_version,"events":payload},sort_keys=True,separators=(",",":"),ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class IHistoricalEventProvider(Protocol):
    @property
    def provenance(self)->EventDatasetProvenance:...
    def health(self)->EventProviderHealth:...
    def events_as_of(self,as_of_utc:datetime,start_utc:datetime,end_utc:datetime)->tuple[EconomicEvent,...]:...


class DeterministicEventProvider:
    """Versioned, in-memory, offline provider with historical as-of projection."""
    def __init__(self,events:Iterable[EconomicEvent],*,provider_id:str="OFFLINE_EVENTS",provider_version:str="1",
                 dataset_id:str="EVENTS",coverage_start_utc:datetime,coverage_end_utc:datetime,
                 imported_at_utc:datetime,source_description:str="deterministic fixture",health:EventProviderHealth=EventProviderHealth.HEALTHY,
                 configuration_snapshot_id:str=""):
        raw=tuple(events);self._health=health
        ids=[item.event_version_id for item in raw]
        if len(ids)!=len(set(ids)):raise ValueError("DUPLICATE_EVENT_VERSION_ID")
        if any(value.tzinfo is None for item in raw for value in (item.scheduled_time_utc,item.first_known_at_utc,item.last_updated_at_utc)):
            raise ValueError("EVENT_TIME_MUST_BE_AWARE")
        fingerprint=event_dataset_fingerprint(raw,provider_id,provider_version)
        normalized=tuple(EconomicEvent(item.logical_event_id,item.event_version_id,item.provider_event_id,item.event_name,item.event_category,
            item.country,tuple(item.affected_dimensions),item.scheduled_time_utc.astimezone(timezone.utc),item.first_known_at_utc.astimezone(timezone.utc),
            item.last_updated_at_utc.astimezone(timezone.utc),item.importance,item.forecast,item.previous,item.actual,item.forecast_available_at_utc,
            item.previous_available_at_utc,item.actual_available_at_utc,item.event_status,provider_id,dataset_id,fingerprint,item.revision,
            item.supersedes_event_version_id,item.metadata) for item in raw)
        self._events = tuple(
    sorted(
        normalized,
        key=lambda value: (
            value.last_updated_at_utc,
            value.revision,
            value.event_version_id,
        ),
    )
)
        grouped = {}

        for item in self._events:
            grouped.setdefault(item.logical_event_id, []).append(item)

        self._events_by_logical_id = {
            logical_event_id: tuple(items)
            for logical_event_id, items in grouped.items()
        }
        self._provenance=EventDatasetProvenance(dataset_id,provider_id,provider_version,fingerprint,coverage_start_utc.astimezone(timezone.utc),
            coverage_end_utc.astimezone(timezone.utc),imported_at_utc.astimezone(timezone.utc),source_description,EVENT_SCHEMA_VERSION,configuration_snapshot_id)
    @property
    def provenance(self):return self._provenance
    def health(self):return self._health
    def set_health(self,value:EventProviderHealth):self._health=value
    def events_as_of(
        self,
        as_of_utc: datetime,
        start_utc: datetime,
        end_utc: datetime,
    ) -> tuple[EconomicEvent, ...]:
        as_of = as_of_utc.astimezone(timezone.utc)
        latest = {}

        for logical_event_id, versions in self._events_by_logical_id.items():
            if not any(
                start_utc <= item.scheduled_time_utc <= end_utc
                for item in versions
            ):
                continue

            for item in versions:
                visible = item.visible_at(as_of)

                if visible is not None:
                    latest[logical_event_id] = visible

        return tuple(
            sorted(
                (
                    item
                    for item in latest.values()
                    if start_utc <= item.scheduled_time_utc <= end_utc
                ),
                key=lambda item: (
                    item.scheduled_time_utc,
                    item.logical_event_id,
                    item.event_version_id,
                ),
            )
        )


@dataclass(frozen=True)
class EventWindowPolicy:
    pre_minutes:int; blackout_before_minutes:int; blackout_after_minutes:int
    post_minutes:int; stabilization_minutes:int


@dataclass(frozen=True)
class NewsRiskConfiguration:
    windows:Mapping[EventImportance,EventWindowPolicy]
    instrument_dimensions:Mapping[str,tuple[str,...]]
    strategy_policy:Mapping[str,Mapping[NewsRiskState,EventEligibility]]|None=None
    unknown_importance_as:EventImportance=EventImportance.HIGH
    maximum_cache_entries:int=256
    maximum_history:int=100
    strict:bool=True

    def __post_init__(self):
        object.__setattr__(self,"windows",MappingProxyType(dict(self.windows)))
        object.__setattr__(self,"instrument_dimensions",MappingProxyType({k:tuple(v) for k,v in self.instrument_dimensions.items()}))
        object.__setattr__(self,"strategy_policy",MappingProxyType({k:MappingProxyType(dict(v)) for k,v in (self.strategy_policy or {}).items()}))
        if self.maximum_cache_entries<1 or self.maximum_history<1:raise ValueError("BOUNDS_MUST_BE_POSITIVE")
        if any(min(w.pre_minutes,w.blackout_before_minutes,w.blackout_after_minutes,w.post_minutes,w.stabilization_minutes)<0 for w in self.windows.values()):raise ValueError("NEGATIVE_EVENT_WINDOW")


@dataclass(frozen=True)
class EventRelevance:
    instrument_id:str; logical_event_id:str; relevant:bool; affected_dimensions:tuple[str,...]
    relevance_score:float; reason_codes:tuple[str,...]


@dataclass(frozen=True)
class EventCluster:
    cluster_id:str; relevant_event_ids:tuple[str,...]; start_utc:datetime; end_utc:datetime
    highest_severity:EventImportance; affected_dimensions:tuple[str,...]
    event_categories:tuple[EventCategory,...]; cluster_risk_state:NewsRiskState


@dataclass(frozen=True)
class EventDataSnapshot:
    event_data_snapshot_id:str; as_of_timestamp_utc:datetime; provider_id:str; provider_version:str
    dataset_id:str; dataset_fingerprint:str; coverage_start_utc:datetime; coverage_end_utc:datetime
    event_versions:tuple[EconomicEvent,...]; provider_health:EventProviderHealth; data_freshness:str
    configuration_snapshot_id:str; recovery_epoch:int


@dataclass(frozen=True)
class NewsRiskSnapshot:
    news_risk_snapshot_id:str; as_of_timestamp_utc:datetime; instrument_id:str; event_data_snapshot_id:str
    event_dataset_id:str; event_dataset_fingerprint:str; relevant_events:tuple[EconomicEvent,...]
    active_clusters:tuple[EventCluster,...]; highest_severity:EventImportance|None
    previous_relevant_event:EconomicEvent|None; next_relevant_event:EconomicEvent|None
    minutes_since_previous_event:int|None; minutes_until_next_event:int|None
    risk_state:NewsRiskState; news_risk_health:NewsRiskHealth; policy_state:NewsPolicyState
    strategy_family_eligibility:Mapping[str,EventEligibility]; provider_health:EventProviderHealth
    data_freshness:str; coverage_health:str; supporting_reasons:tuple[str,...]
    restrictions:tuple[str,...]; warnings:tuple[str,...]; decision_trace:DecisionTrace
    configuration_snapshot_id:str; recovery_epoch:int; news_risk_engine_version:str=NEWS_RISK_ENGINE_VERSION
    def __post_init__(self):object.__setattr__(self,"strategy_family_eligibility",MappingProxyType(dict(self.strategy_family_eligibility)))


class NewsRiskEngine:
    def __init__(self,clock:IClock,audit:IAuditSink,timezones:TimeZoneService,provider:IHistoricalEventProvider,configuration:NewsRiskConfiguration):
        self.clock=clock;self.audit=audit;self.timezones=timezones;self.provider=provider;self.configuration=configuration
        self._cache:OrderedDict[tuple,NewsRiskSnapshot]=OrderedDict();self._history:list[NewsRiskSnapshot]=[];self._last_health=provider.health()
        self._last_event_data_snapshot:EventDataSnapshot|None=None
        self.audit.record("event_dataset_admitted",{"dataset_id":provider.provenance.event_dataset_id,"fingerprint":provider.provenance.dataset_fingerprint})

    def normalize_provider_local(self,value:datetime,timezone_name:str,*,fold:int|None=None):
        return self.timezones.resolve_local(value,timezone_name,fold=fold)

    def relevance(self,event:EconomicEvent,instrument_id:str)->EventRelevance:
        dimensions=set(self.configuration.instrument_dimensions.get(instrument_id,()))
        affected=tuple(sorted(dimensions.intersection(event.affected_dimensions)))
        return EventRelevance(instrument_id,event.logical_event_id,bool(affected),affected,
            100*len(affected)/max(1,len(dimensions)),("DIMENSION_MATCH",) if affected else ("IRRELEVANT_DIMENSION",))

    def _importance(self,event:EconomicEvent)->EventImportance:
        return self.configuration.unknown_importance_as if event.importance is EventImportance.UNKNOWN else event.importance

    def _window(self,event:EconomicEvent)->tuple[datetime,datetime,datetime,datetime]:
        policy=self.configuration.windows[self._importance(event)];e=event.scheduled_time_utc
        return e-timedelta(minutes=policy.pre_minutes),e-timedelta(minutes=policy.blackout_before_minutes),e+timedelta(minutes=policy.blackout_after_minutes),e+timedelta(minutes=policy.blackout_after_minutes+policy.post_minutes+policy.stabilization_minutes)

    def _clusters(self,events:tuple[EconomicEvent,...],as_of:datetime)->tuple[EventCluster,...]:
        intervals=[]
        for event in events:
            start,_,_,end=self._window(event);intervals.append((start,end,event))
        intervals.sort(key=lambda item:(item[0],item[1],item[2].logical_event_id));groups=[]
        for start,end,event in intervals:
            if groups and start<=groups[-1][1]:groups[-1][1]=max(groups[-1][1],end);groups[-1][2].append(event)
            else:groups.append([start,end,[event]])
        results=[]
        for start,end,items in groups:
            highest=max((self._importance(item) for item in items),key=lambda value:value.value)
            state=self._state_for(tuple(items),as_of)
            ids=tuple(sorted(item.logical_event_id for item in items));results.append(EventCluster(
                deterministic_id("event_cluster",self.provider.provenance.dataset_fingerprint,start.isoformat(),end.isoformat(),"|".join(ids)),
                ids,start,end,highest,tuple(sorted({value for item in items for value in item.affected_dimensions})),
                tuple(sorted({item.event_category for item in items},key=lambda value:value.name)),state))
        return tuple(results)

    def _state_for(self,events:tuple[EconomicEvent,...],as_of:datetime)->NewsRiskState:
        candidates=[]
        for event in events:
            if event.event_status in (EconomicEventStatus.CANCELLED,EconomicEventStatus.POSTPONED):continue
            pre,blackout_start,blackout_end,restriction_end=self._window(event)
            if blackout_start<=as_of<blackout_end:candidates.append((4,NewsRiskState.BLACKOUT))
            elif blackout_end<=as_of<restriction_end:candidates.append((3,NewsRiskState.POST_EVENT_STABILIZATION))
            elif pre<=as_of<blackout_start:
                importance=self._importance(event);candidates.append((2+importance.value/10,{
                    EventImportance.LOW:NewsRiskState.UPCOMING_LOW,EventImportance.MEDIUM:NewsRiskState.UPCOMING_MEDIUM,
                    EventImportance.HIGH:NewsRiskState.UPCOMING_HIGH,EventImportance.CRITICAL:NewsRiskState.UPCOMING_CRITICAL}[importance]))
        return max(candidates,key=lambda item:item[0])[1] if candidates else NewsRiskState.CLEAR

    def analyze(self,as_of_utc:datetime,instrument_id:str,configuration_snapshot_id:str,recovery_epoch:int=0,*,configuration_hash:str="")->NewsRiskSnapshot:
        if as_of_utc.tzinfo is None:raise ValueError("TIME_INVALID_INPUT")
        as_of=as_of_utc.astimezone(timezone.utc);provenance=self.provider.provenance;health=self.provider.health()
        max_pre=max(item.pre_minutes for item in self.configuration.windows.values());max_post=max(item.blackout_after_minutes+item.post_minutes+item.stabilization_minutes for item in self.configuration.windows.values())
        start=as_of-timedelta(minutes=max_post);end=as_of+timedelta(minutes=max_pre)
        cache_key=(provenance.dataset_fingerprint,as_of.isoformat(),instrument_id,configuration_hash,provenance.provider_version,NEWS_RISK_ENGINE_VERSION,health.name)
        if cache_key in self._cache:self._cache.move_to_end(cache_key);return self._cache[cache_key]
        events=self.provider.events_as_of(as_of,start,end) if health not in (EventProviderHealth.UNAVAILABLE,EventProviderHealth.INVALID) else ()
        data_snapshot=EventDataSnapshot(deterministic_id("event_data",provenance.dataset_fingerprint,as_of.isoformat(),"|".join(item.event_version_id for item in events)),
            as_of,provenance.provider_id,provenance.provider_version,provenance.event_dataset_id,provenance.dataset_fingerprint,
            provenance.coverage_start_utc,provenance.coverage_end_utc,events,health,"CURRENT" if health is EventProviderHealth.HEALTHY else health.name,configuration_snapshot_id,recovery_epoch)
        self._last_event_data_snapshot=data_snapshot
        relevant=tuple(item for item in events if self.relevance(item,instrument_id).relevant and item.event_status not in (EconomicEventStatus.CANCELLED,EconomicEventStatus.POSTPONED))
        coverage_ok=provenance.coverage_start_utc<=start and provenance.coverage_end_utc>=end
        reasons=[];warnings=[]
        if health in (EventProviderHealth.UNAVAILABLE,EventProviderHealth.INVALID):state=NewsRiskState.DATA_UNAVAILABLE;news_health=NewsRiskHealth.UNAVAILABLE;reasons.append("EVENT_DATA_UNAVAILABLE")
        elif health is EventProviderHealth.STALE:state=NewsRiskState.DATA_STALE;news_health=NewsRiskHealth.STALE;reasons.append("EVENT_DATA_STALE")
        elif not coverage_ok:state=NewsRiskState.INCOMPLETE_COVERAGE;news_health=NewsRiskHealth.INCOMPLETE;reasons.append("EVENT_COVERAGE_INCOMPLETE")
        else:
            state=self._state_for(relevant,as_of);news_health=NewsRiskHealth.HEALTHY if health is EventProviderHealth.HEALTHY else NewsRiskHealth.DEGRADED
            reasons.append("VALID_NO_RELEVANT_EVENTS" if not relevant else state.name)
        clusters=self._clusters(relevant,as_of)
        previous=max((item for item in relevant if item.scheduled_time_utc<=as_of),key=lambda item:item.scheduled_time_utc,default=None)
        next_event=min((item for item in relevant if item.scheduled_time_utc>as_of),key=lambda item:item.scheduled_time_utc,default=None)
        restrictive=state not in (NewsRiskState.CLEAR,NewsRiskState.UPCOMING_LOW)
        policy=NewsPolicyState.BLOCK_NEW_RESEARCH_EXPOSURE if state in (NewsRiskState.BLACKOUT,NewsRiskState.DATA_UNAVAILABLE,NewsRiskState.INCOMPLETE_COVERAGE,NewsRiskState.UNKNOWN) else NewsPolicyState.RESTRICT_CONTEXT if restrictive else NewsPolicyState.ALLOW_CONTEXT
        eligibility={family:policy_map.get(state,EventEligibility.UNKNOWN) for family,policy_map in self.configuration.strategy_policy.items()}
        if policy is NewsPolicyState.BLOCK_NEW_RESEARCH_EXPOSURE:eligibility={key:EventEligibility.BLOCKED for key in eligibility}
        elif policy is NewsPolicyState.RESTRICT_CONTEXT:eligibility={key:EventEligibility.RESTRICTED if value is EventEligibility.ELIGIBLE else value for key,value in eligibility.items()}
        trace=DecisionTraceBuilder(self.clock,deterministic_id("news_decision",data_snapshot.event_data_snapshot_id,instrument_id),deterministic_id("correlation",data_snapshot.event_data_snapshot_id,instrument_id))
        trace.evaluate("coverage",DecisionStatus.PASSED if coverage_ok else DecisionStatus.FAILED,"COVERAGE_COMPLETE" if coverage_ok else "INCOMPLETE_COVERAGE","required event horizon")
        if coverage_ok:
            provider_ok=news_health in (NewsRiskHealth.HEALTHY,NewsRiskHealth.DEGRADED)
            trace.evaluate("provider",DecisionStatus.PASSED if provider_ok else DecisionStatus.FAILED,health.name,"offline provider health")
            if provider_ok:
                trace.evaluate("risk",DecisionStatus.PASSED if policy is NewsPolicyState.ALLOW_CONTEXT else DecisionStatus.FAILED,state.name,"scheduled-event restriction metadata")
        decision_trace=trace.complete(DecisionOutcome.NO_ACTION,"news policy cannot execute")
        identity=deterministic_id("news_risk",data_snapshot.event_data_snapshot_id,instrument_id,configuration_hash,state.name,NEWS_RISK_ENGINE_VERSION)
        snapshot=NewsRiskSnapshot(identity,as_of,instrument_id,data_snapshot.event_data_snapshot_id,provenance.event_dataset_id,
            provenance.dataset_fingerprint,relevant,clusters,max((self._importance(item) for item in relevant),key=lambda value:value.value,default=None),
            previous,next_event,int((as_of-previous.scheduled_time_utc).total_seconds()/60) if previous else None,
            int((next_event.scheduled_time_utc-as_of).total_seconds()/60) if next_event else None,state,news_health,policy,eligibility,health,
            data_snapshot.data_freshness,"COMPLETE" if coverage_ok else "INCOMPLETE",tuple(reasons),tuple(reasons if restrictive else ()),tuple(warnings),decision_trace,
            configuration_snapshot_id,recovery_epoch)
        self._cache[cache_key]=snapshot;self._cache.move_to_end(cache_key)
        while len(self._cache)>self.configuration.maximum_cache_entries:self._cache.popitem(last=False)
        self._history.append(snapshot);self._history=self._history[-self.configuration.maximum_history:]
        if self._last_health is not EventProviderHealth.HEALTHY and health is EventProviderHealth.HEALTHY:self.audit.record("event_provider_recovered",{"dataset_id":provenance.event_dataset_id})
        self._last_health=health;self.audit.record("news_snapshot_created",{"news_risk_snapshot_id":identity,"risk_state":state.name,"policy":policy.name})
        return snapshot

    @property
    def history(self):return tuple(self._history)
    @property
    def last_event_data_snapshot(self):return self._last_event_data_snapshot
    @property
    def cache_size(self):return len(self._cache)
    def recovery_state(self):
        latest=self._history[-1] if self._history else None
        return {"news_risk_engine_version":NEWS_RISK_ENGINE_VERSION,"dataset_fingerprint":self.provider.provenance.dataset_fingerprint,
            "provider_version":self.provider.provenance.provider_version,"latest_event_data_snapshot_id":self._last_event_data_snapshot.event_data_snapshot_id if self._last_event_data_snapshot else None,
            "latest_news_risk_snapshot_id":latest.news_risk_snapshot_id if latest else None,
            "configuration_snapshot_id":latest.configuration_snapshot_id if latest else None,"recovery_epoch":latest.recovery_epoch if latest else None}
    def validate_recovery(self,state:Mapping[str,object],configuration_snapshot_id:str,recovery_epoch:int)->bool:
        return state.get("news_risk_engine_version")==NEWS_RISK_ENGINE_VERSION and state.get("dataset_fingerprint")==self.provider.provenance.dataset_fingerprint and state.get("configuration_snapshot_id")==configuration_snapshot_id and state.get("recovery_epoch")==recovery_epoch
