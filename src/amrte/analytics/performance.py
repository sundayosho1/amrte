"""Deterministic statistics for neutral, dimensionless research outcomes.

This module describes immutable historical evidence.  It has no authority to
change upstream state, create permission, or interact with financial systems.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import Enum, auto
from math import sqrt
from statistics import median
from threading import RLock

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation, DecisionOutcome, DecisionStatus, DecisionTrace

VERSION = "1.0"
SCHEMA = "1.0"
METRIC_VERSION = "1.0"
ZERO = Decimal("0")
ONE = Decimal("1")


class OutcomeClassification(Enum): POSITIVE=auto(); NEGATIVE=auto(); FLAT=auto(); UNKNOWN=auto(); INVALID=auto()
class AnalyticsScope(Enum): GLOBAL=auto(); STRATEGY=auto(); STRATEGY_VERSION=auto(); STRATEGY_VARIANT=auto(); STRATEGY_FAMILY=auto(); SUBJECT=auto(); CATEGORY=auto(); REGIME=auto(); SESSION=auto(); TIMEFRAME=auto(); DATASET=auto(); RESEARCH_PERIOD=auto(); COMPOSITE=auto()
class MetricAvailability(Enum): AVAILABLE=auto(); UNDEFINED=auto(); INSUFFICIENT_DATA=auto(); NOT_APPLICABLE=auto(); INVALID=auto()
class SampleAdequacyState(Enum): INSUFFICIENT=auto(); LIMITED=auto(); ADEQUATE=auto(); STRONG=auto()
class AnalyticsQualityState(Enum): VALID=auto(); LIMITED=auto(); DEGRADED=auto(); INSUFFICIENT_DATA=auto(); INVALID=auto(); UNKNOWN=auto()
class AnalyticsTrendState(Enum): IMPROVING=auto(); STABLE=auto(); DETERIORATING=auto(); MIXED=auto(); INSUFFICIENT_DATA=auto()
class ReconciliationOutcome(Enum): CONSISTENT=auto(); REBUILT=auto(); QUARANTINED=auto(); REVIEW_REQUIRED=auto(); FAILED_CLOSED=auto()


@dataclass(frozen=True)
class AnalyticsConfiguration:
    zero_tolerance: Decimal = Decimal("0.00000001")
    precision: Decimal = Decimal("0.00000001")
    limited_sample: int = 10
    adequate_sample: int = 30
    strong_sample: int = 100
    stability_minimum: int = 2
    segmented_minimum: int = 5
    rolling_minimum: int = 5
    worst_best_n: int = 3
    trend_tolerance: Decimal = Decimal("0.05")
    maximum_observations: int = 10000
    maximum_snapshots: int = 2048
    maximum_cache_entries: int = 512
    configuration_snapshot_id: str = "NEUTRAL_ANALYTICS_DEFAULT"
    def validate(self):
        errors=[]
        numeric=(self.zero_tolerance,self.precision,self.trend_tolerance)
        if any(not Decimal(str(x)).is_finite() or Decimal(str(x))<ZERO for x in numeric):errors.append("ANALYTICS_NUMERICAL_POLICY_INVALID")
        if not 1<=self.limited_sample<=self.adequate_sample<=self.strong_sample:errors.append("ANALYTICS_SAMPLE_THRESHOLDS_INVALID")
        if min(self.stability_minimum,self.segmented_minimum,self.rolling_minimum,self.worst_best_n,self.maximum_observations,self.maximum_snapshots,self.maximum_cache_entries)<1:errors.append("ANALYTICS_BOUND_INVALID")
        return tuple(errors)


@dataclass(frozen=True)
class ResearchOutcomeObservation:
    observation_id:str; hypothesis_id:str; strategy_id:str; strategy_version:str; variant_id:str; family_id:str; subject_id:str; category_id:str; regime_id:str; session_id:str; timeframe_id:str; normalized_outcome_r:Decimal; outcome_classification:OutcomeClassification; opened_at_utc:datetime; closed_at_utc:datetime; known_at_utc:datetime; duration:timedelta; dataset_fingerprint:str; configuration_snapshot_id:str; lifecycle_snapshot_id:str; phase_vii_safety_snapshot_id:str; phase_vii_safety_state:str; engine_version:str; recovery_epoch:int
    @classmethod
    def create(cls,hypothesis_id,strategy_id,strategy_version,variant_id,family_id,subject_id,category_id,regime_id,session_id,timeframe_id,normalized_outcome_r,opened_at_utc,closed_at_utc,known_at_utc,dataset_fingerprint,configuration_snapshot_id="NEUTRAL_ANALYTICS_DEFAULT",lifecycle_snapshot_id="LIFECYCLE",phase_vii_safety_snapshot_id="PHASE-VII",phase_vii_safety_state="NORMAL",engine_version="UPSTREAM",recovery_epoch=0,zero_tolerance=Decimal("0.00000001")):
        value=Decimal(str(normalized_outcome_r));tol=Decimal(str(zero_tolerance));classification=OutcomeClassification.INVALID if not value.is_finite() else OutcomeClassification.FLAT if abs(value)<=tol else OutcomeClassification.POSITIVE if value>ZERO else OutcomeClassification.NEGATIVE
        oid=deterministic_id("research_outcome",hypothesis_id,strategy_id,strategy_version,variant_id,subject_id,value,opened_at_utc.isoformat(),closed_at_utc.isoformat(),known_at_utc.isoformat(),dataset_fingerprint,configuration_snapshot_id,lifecycle_snapshot_id,phase_vii_safety_snapshot_id,recovery_epoch)
        return cls(oid,hypothesis_id,strategy_id,strategy_version,variant_id,family_id,subject_id,category_id,regime_id,session_id,timeframe_id,value,classification,opened_at_utc,closed_at_utc,known_at_utc,closed_at_utc-opened_at_utc,dataset_fingerprint,configuration_snapshot_id,lifecycle_snapshot_id,phase_vii_safety_snapshot_id,phase_vii_safety_state,engine_version,recovery_epoch)


@dataclass(frozen=True)
class ResearchAnalyticsQuery:
    query_id:str; scope:AnalyticsScope; filters:tuple[tuple[str,str],...]; start_time_utc:datetime; end_time_utc:datetime; as_of_time_utc:datetime; rolling_window:int|None; minimum_sample_size:int|None; dataset_fingerprint:str; configuration_snapshot_id:str; requested_metrics:tuple[str,...]
    @classmethod
    def create(cls,scope,start_time_utc,end_time_utc,as_of_time_utc,dataset_fingerprint,filters=(),rolling_window=None,minimum_sample_size=None,configuration_snapshot_id="NEUTRAL_ANALYTICS_DEFAULT",requested_metrics=()):
        canonical=tuple(sorted((str(k),str(v)) for k,v in dict(filters).items())) if isinstance(filters,dict) else tuple(sorted((str(k),str(v)) for k,v in filters));metrics=tuple(sorted(set(requested_metrics)))
        qid=deterministic_id("analytics_query",scope.name,*sum(canonical,()),start_time_utc.isoformat(),end_time_utc.isoformat(),as_of_time_utc.isoformat(),rolling_window,minimum_sample_size,dataset_fingerprint,configuration_snapshot_id,*metrics)
        return cls(qid,scope,canonical,start_time_utc,end_time_utc,as_of_time_utc,rolling_window,minimum_sample_size,dataset_fingerprint,configuration_snapshot_id,metrics)


@dataclass(frozen=True)
class MetricDefinitionVersion:
    metric_id:str; metric_name:str; definition_version:str; input_requirements:tuple[str,...]; minimum_sample_size:int; denominator_policy:str; numerical_policy:str; aggregation_policy:str; output_type:str
class AnalyticsMetricRegistry:
    def __init__(self,definitions=()):
        self._items=OrderedDict()
        for definition in definitions:self.register(definition)
    def register(self,definition):
        if not definition.metric_id or definition.metric_id in self._items or definition.minimum_sample_size<1:raise ValueError("ANALYTICS_METRIC_DEFINITION_INVALID")
        self._items[definition.metric_id]=definition
    def resolve(self,metric_id):return self._items.get(metric_id)
    def enumerate(self):return tuple(self._items[k] for k in sorted(self._items))
    @classmethod
    def default(cls):
        names=("CUMULATIVE_R","AVERAGE_R","MEDIAN_R","POSITIVE_RATE","NEGATIVE_RATE","FLAT_RATE","MAGNITUDE_RATIO","EXPECTANCY_R","STANDARD_DEVIATION_R","MAXIMUM_R_DECLINE","R_STABILITY","DOWNSIDE_R_STABILITY","RECOVERY_RATIO")
        return cls(MetricDefinitionVersion(x,x.replace("_"," ").title(),METRIC_VERSION,("NORMALIZED_OUTCOME_R",),1,"EXPLICIT_UNDEFINED","DECIMAL_DETERMINISTIC","ELIGIBLE_OBSERVATIONS","DECIMAL") for x in names)


@dataclass(frozen=True)
class MetricValue:
    value:Decimal|None; availability:MetricAvailability; reason_code:str; definition_version:str=METRIC_VERSION
@dataclass(frozen=True)
class DistributionStatistics:
    minimum_r:Decimal;maximum_r:Decimal;mean_r:Decimal;median_r:Decimal;standard_deviation_r:Decimal;variance_r:Decimal;lower_quartile_r:Decimal;upper_quartile_r:Decimal;interquartile_range_r:Decimal;quantile_05:Decimal;quantile_25:Decimal;quantile_50:Decimal;quantile_75:Decimal;quantile_95:Decimal;worst_n_mean_r:Decimal;best_n_mean_r:Decimal;outlier_observation_ids:tuple[str,...]
@dataclass(frozen=True)
class SequenceStatistics:
    current_negative_sequence:int;maximum_negative_sequence:int;average_negative_sequence:Decimal;negative_sequence_count:int;maximum_adverse_sequence_r:Decimal;average_adverse_sequence_r:Decimal;current_positive_sequence:int;maximum_positive_sequence:int;average_positive_sequence:Decimal;positive_sequence_count:int;maximum_positive_sequence_r:Decimal;average_positive_sequence_r:Decimal
@dataclass(frozen=True)
class DeclineStatistics:
    cumulative_path:tuple[tuple[datetime,Decimal],...];peak_cumulative_r:Decimal;current_r_decline:Decimal;maximum_r_decline:Decimal;decline_start:datetime|None;decline_trough:datetime|None;decline_recovery:datetime|None;decline_duration:timedelta|None;recovery_duration:timedelta|None
@dataclass(frozen=True)
class ConfidenceMetadata:
    observation_count:int;effective_observation_count:int;sample_adequacy:SampleAdequacyState;standard_error:MetricValue;confidence_interval_low:Decimal|None;confidence_interval_high:Decimal|None;method:str
@dataclass(frozen=True)
class ResearchPerformanceSummary:
    scope:AnalyticsScope;observation_count:int;cumulative_normalized_outcome:MetricValue;average_r:MetricValue;median_r:MetricValue;expectancy_r:MetricValue;positive_outcome_rate:MetricValue;negative_outcome_rate:MetricValue;flat_outcome_rate:MetricValue;positive_negative_magnitude_ratio:MetricValue;maximum_r_decline:MetricValue;recovery_ratio:MetricValue;maximum_positive_sequence:int;maximum_negative_sequence:int;r_based_stability_ratio:MetricValue;downside_r_based_stability_ratio:MetricValue;sample_adequacy:SampleAdequacyState;analytics_quality_state:AnalyticsQualityState;start_time_utc:datetime;end_time_utc:datetime;as_of_time_utc:datetime
@dataclass(frozen=True)
class ResearchAnalyticsSnapshot:
    snapshot_id:str;query_id:str;scope:AnalyticsScope;observation_count:int;valid_observation_count:int;excluded_observation_count:int;sample_adequacy_state:SampleAdequacyState;summary:ResearchPerformanceSummary;distribution_statistics:DistributionStatistics|None;sequence_statistics:SequenceStatistics|None;decline_statistics:DeclineStatistics|None;duration_statistics:tuple[tuple[str,object],...];segmentation_statistics:tuple[tuple[str,str],...];analytics_trend_state:AnalyticsTrendState;data_quality_state:AnalyticsQualityState;confidence_metadata:ConfidenceMetadata;included_observation_ids:tuple[str,...];excluded_reason_codes:tuple[str,...];start_time_utc:datetime;end_time_utc:datetime;as_of_time_utc:datetime;dataset_fingerprint:str;configuration_snapshot_id:str;source_fingerprint:str;metric_definition_versions:tuple[str,...];engine_version:str;recovery_epoch:int;decision_trace:DecisionTrace
@dataclass(frozen=True)
class SegmentAnalyticsSnapshot:
    snapshot_id:str;dimension:str;dimension_value:str;analytics_snapshot_id:str;summary:ResearchPerformanceSummary
StrategyAnalyticsSnapshot=SegmentAnalyticsSnapshot
SubjectAnalyticsSnapshot=SegmentAnalyticsSnapshot
SessionAnalyticsSnapshot=SegmentAnalyticsSnapshot
RegimeAnalyticsSnapshot=SegmentAnalyticsSnapshot
TimeframeAnalyticsSnapshot=SegmentAnalyticsSnapshot
@dataclass(frozen=True)
class RollingAnalyticsSnapshot:
    snapshot_id:str;window_size:int;analytics_snapshot_id:str;summary:ResearchPerformanceSummary;as_of_time_utc:datetime
@dataclass(frozen=True)
class AnalyticsComparison:
    comparison_id:str;left_snapshot_id:str;right_snapshot_id:str;average_r_delta:MetricValue;expectancy_delta:MetricValue;positive_rate_delta:MetricValue;stability_delta:MetricValue;maximum_r_decline_delta:MetricValue;validity:str;reason_codes:tuple[str,...]
@dataclass(frozen=True)
class ContributionAnalytics:
    contribution_id:str;snapshot_id:str;top_n:int;top_positive_observation_ids:tuple[str,...];top_negative_observation_ids:tuple[str,...];top_positive_r:Decimal;top_negative_r:Decimal;positive_share:MetricValue;negative_share:MetricValue
@dataclass(frozen=True)
class PhaseVIIIAnalyticsSnapshot:
    snapshot_id:str;as_of_time_utc:datetime;global_performance_summary:ResearchPerformanceSummary;strategy_analytics_references:tuple[str,...];subject_analytics_references:tuple[str,...];session_analytics_references:tuple[str,...];regime_analytics_references:tuple[str,...];rolling_analytics_references:tuple[str,...];distribution_summary:DistributionStatistics|None;sequence_summary:SequenceStatistics|None;data_quality_summary:AnalyticsQualityState;phase_vii_safety_snapshot_id:str;dataset_fingerprint:str;configuration_snapshot_id:str;metric_definition_version_set:tuple[str,...];source_fingerprint:str;engine_version:str;recovery_epoch:int
@dataclass(frozen=True)
class Prompt32AnalyticsHandoff:
    handoff_id:str;phase_viii_snapshot_id:str;as_of_time_utc:datetime;summary:ResearchPerformanceSummary;breakdown_references:tuple[str,...];warnings:tuple[str,...]
@dataclass(frozen=True)
class AnalyticsRecovery:
    schema_version:str;engine_version:str;configuration_snapshot_id:str;recovery_epoch:int;observations:tuple[ResearchOutcomeObservation,...];quarantined:tuple[ResearchOutcomeObservation,...];snapshots:tuple[ResearchAnalyticsSnapshot,...]


class ResearchPerformanceAnalyticsEngine:
    def __init__(self,configuration=AnalyticsConfiguration(),metric_registry=None,audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.metric_registry=metric_registry or AnalyticsMetricRegistry.default();self.audit=audit;self._lock=RLock();self.observations=OrderedDict();self.quarantined=OrderedDict();self.duplicates=0;self.snapshots=OrderedDict();self.cache=OrderedDict();self.recovery_restricted=False

    def ingest(self,observation,as_of):
        with self._lock:
            if observation.observation_id in self.observations or observation.observation_id in self.quarantined:self.duplicates+=1;return False,"OUTCOME_DUPLICATE"
            reason=self._validate(observation,as_of)
            if reason:
                self.quarantined[observation.observation_id]=observation;return False,reason
            if len(self.observations)>=self.configuration.maximum_observations:return False,"ANALYTICS_OBSERVATION_BOUND_REACHED"
            self.observations[observation.observation_id]=observation;self.cache.clear();self._record("analytics_outcome_ingested",{"observation_id":observation.observation_id});return True,"OUTCOME_INCLUDED"

    def calculate(self,query,recovery_epoch=0,full_recompute=False):
        with self._lock:
            invalid=self._validate_query(query)
            if invalid:raise ValueError(invalid)
            eligible=[];excluded=[]
            for observation in self.observations.values():
                reason=self._exclusion(observation,query)
                if reason:excluded.append(reason)
                else:eligible.append(observation)
            eligible.sort(key=lambda x:(x.known_at_utc,x.closed_at_utc,x.observation_id))
            if query.rolling_window is not None:eligible=eligible[-query.rolling_window:]
            source=deterministic_id("analytics_source",query.query_id,*[x.observation_id for x in eligible],*excluded)
            key=deterministic_id("analytics_cache",query.query_id,source,METRIC_VERSION,recovery_epoch)
            if not full_recompute and key in self.cache:
                self.cache.move_to_end(key);return self.cache[key]
            snapshot=self._build(query,eligible,excluded,source,recovery_epoch)
            self.snapshots[snapshot.snapshot_id]=snapshot;self.cache[key]=snapshot
            while len(self.cache)>self.configuration.maximum_cache_entries:self.cache.popitem(last=False)
            while len(self.snapshots)>self.configuration.maximum_snapshots:self.snapshots.popitem(last=False)
            self._record("analytics_snapshot_published",{"snapshot_id":snapshot.snapshot_id,"observations":len(eligible)});return snapshot

    def segment(self,base_query,dimension):
        field=self._field(dimension);values=sorted({str(getattr(x,field)) for x in self.observations.values()})
        result=[]
        for value in values:
            query=ResearchAnalyticsQuery.create(AnalyticsScope.COMPOSITE,base_query.start_time_utc,base_query.end_time_utc,base_query.as_of_time_utc,base_query.dataset_fingerprint,dict(base_query.filters)|{dimension:value},base_query.rolling_window,base_query.minimum_sample_size,base_query.configuration_snapshot_id,base_query.requested_metrics)
            snap=self.calculate(query);sid=deterministic_id("segment_analytics",dimension,value,snap.snapshot_id);result.append(SegmentAnalyticsSnapshot(sid,dimension,value,snap.snapshot_id,snap.summary))
        return tuple(result)

    def rolling(self,base_query,window_sizes):
        result=[]
        for size in sorted(set(window_sizes)):
            if size<self.configuration.rolling_minimum:continue
            query=replace(base_query,query_id=deterministic_id("rolling_query",base_query.query_id,size),rolling_window=size)
            snapshot=self.calculate(query);result.append(RollingAnalyticsSnapshot(deterministic_id("rolling_snapshot",snapshot.snapshot_id,size),size,snapshot.snapshot_id,snapshot.summary,base_query.as_of_time_utc))
        return tuple(result)

    def compare(self,left,right):
        same=left.dataset_fingerprint==right.dataset_fingerprint and left.metric_definition_versions==right.metric_definition_versions
        enough=left.sample_adequacy_state not in (SampleAdequacyState.INSUFFICIENT,) and right.sample_adequacy_state not in (SampleAdequacyState.INSUFFICIENT,)
        validity="VALID" if same and enough else "COMPARISON_LIMITED" if same else "COMPARISON_INVALID";reasons=() if validity=="VALID" else (validity,)
        def delta(a,b):
            if a.value is None or b.value is None:return MetricValue(None,MetricAvailability.UNDEFINED,"INVALID_DENOMINATOR")
            return self._metric(a.value-b.value)
        a=left.summary;b=right.summary;cid=deterministic_id("analytics_comparison",left.snapshot_id,right.snapshot_id,validity)
        return AnalyticsComparison(cid,left.snapshot_id,right.snapshot_id,delta(a.average_r,b.average_r),delta(a.expectancy_r,b.expectancy_r),delta(a.positive_outcome_rate,b.positive_outcome_rate),delta(a.r_based_stability_ratio,b.r_based_stability_ratio),delta(a.maximum_r_decline,b.maximum_r_decline),validity,reasons)

    def contribution(self,snapshot,top_n):
        if top_n<1:raise ValueError("ANALYTICS_TOP_N_INVALID")
        items=[self.observations[x] for x in snapshot.included_observation_ids];positive=sorted((x for x in items if x.normalized_outcome_r>ZERO),key=lambda x:(-x.normalized_outcome_r,x.observation_id))[:top_n];negative=sorted((x for x in items if x.normalized_outcome_r<ZERO),key=lambda x:(x.normalized_outcome_r,x.observation_id))[:top_n]
        positive_r=self._q(sum((x.normalized_outcome_r for x in positive),ZERO));negative_r=self._q(sum((x.normalized_outcome_r for x in negative),ZERO));all_positive=sum((x.normalized_outcome_r for x in items if x.normalized_outcome_r>ZERO),ZERO);all_negative=abs(sum((x.normalized_outcome_r for x in items if x.normalized_outcome_r<ZERO),ZERO))
        positive_share=self._undefined("INVALID_DENOMINATOR") if all_positive==ZERO else self._metric(positive_r/all_positive);negative_share=self._undefined("INVALID_DENOMINATOR") if all_negative==ZERO else self._metric(abs(negative_r)/all_negative);cid=deterministic_id("analytics_contribution",snapshot.snapshot_id,top_n,*[x.observation_id for x in positive],*[x.observation_id for x in negative])
        return ContributionAnalytics(cid,snapshot.snapshot_id,top_n,tuple(x.observation_id for x in positive),tuple(x.observation_id for x in negative),positive_r,negative_r,positive_share,negative_share)

    def phase_viii_snapshot(self,global_snapshot,segments=(),rolling=(),phase_vii_safety_snapshot_id=""):
        refs=lambda d:tuple(x.snapshot_id for x in segments if x.dimension==d)
        sid=deterministic_id("phase_viii_analytics",global_snapshot.snapshot_id,*[x.snapshot_id for x in segments],*[x.snapshot_id for x in rolling],phase_vii_safety_snapshot_id)
        return PhaseVIIIAnalyticsSnapshot(sid,global_snapshot.as_of_time_utc,global_snapshot.summary,refs("strategy_id"),refs("subject_id"),refs("session_id"),refs("regime_id"),tuple(x.snapshot_id for x in rolling),global_snapshot.distribution_statistics,global_snapshot.sequence_statistics,global_snapshot.data_quality_state,phase_vii_safety_snapshot_id,global_snapshot.dataset_fingerprint,global_snapshot.configuration_snapshot_id,global_snapshot.metric_definition_versions,global_snapshot.source_fingerprint,VERSION,global_snapshot.recovery_epoch)

    @staticmethod
    def prompt32_handoff(snapshot):
        refs=snapshot.strategy_analytics_references+snapshot.subject_analytics_references+snapshot.session_analytics_references+snapshot.regime_analytics_references+snapshot.rolling_analytics_references
        warnings=() if snapshot.global_performance_summary.sample_adequacy not in (SampleAdequacyState.INSUFFICIENT,SampleAdequacyState.LIMITED) else ("ANALYTICS_SAMPLE_LIMITED",)
        return Prompt32AnalyticsHandoff(deterministic_id("prompt32_analytics_handoff",snapshot.snapshot_id,*refs,*warnings),snapshot.snapshot_id,snapshot.as_of_time_utc,snapshot.global_performance_summary,refs,warnings)

    def reconcile(self,snapshot):
        try:
            query_ids={x.query_id for x in self.snapshots.values()}
            if snapshot.query_id not in query_ids:return ReconciliationOutcome.REVIEW_REQUIRED,("ANALYTICS_SNAPSHOT_NOT_REGISTERED",)
            if snapshot.valid_observation_count!=len(snapshot.included_observation_ids):return ReconciliationOutcome.FAILED_CLOSED,("ANALYTICS_COUNT_MISMATCH",)
            total=snapshot.summary.cumulative_normalized_outcome.value
            expected=sum((self.observations[x].normalized_outcome_r for x in snapshot.included_observation_ids),ZERO)
            if total!=self._q(expected):return ReconciliationOutcome.FAILED_CLOSED,("ANALYTICS_CUMULATIVE_MISMATCH",)
            return ReconciliationOutcome.CONSISTENT,()
        except Exception:return ReconciliationOutcome.FAILED_CLOSED,("ANALYTICS_RECONCILIATION_FAILURE",)

    def recovery_state(self,epoch):return AnalyticsRecovery(SCHEMA,VERSION,self.configuration.configuration_snapshot_id,epoch,tuple(self.observations.values()),tuple(self.quarantined.values()),tuple(self.snapshots.values()))
    def restore(self,state,epoch):
        with self._lock:
            if state.schema_version!=SCHEMA or state.engine_version!=VERSION or state.configuration_snapshot_id!=self.configuration.configuration_snapshot_id or state.recovery_epoch!=epoch:self.recovery_restricted=True;return False
            try:
                if len({x.observation_id for x in state.observations})!=len(state.observations) or len({x.snapshot_id for x in state.snapshots})!=len(state.snapshots):raise ValueError
                self.observations=OrderedDict((x.observation_id,x) for x in state.observations);self.quarantined=OrderedDict((x.observation_id,x) for x in state.quarantined);self.snapshots=OrderedDict((x.snapshot_id,x) for x in state.snapshots);self.cache.clear();self.recovery_restricted=False;return True
            except Exception:self.recovery_restricted=True;return False
    def replay_fingerprint(self):return deterministic_id("analytics_replay",*[x.observation_id for x in self.observations.values()],*[x.snapshot_id for x in self.snapshots.values()],METRIC_VERSION)

    def _build(self,query,items,excluded,source,epoch):
        n=len(items);values=[x.normalized_outcome_r for x in items];adequacy=self._adequacy(n,query.minimum_sample_size);quality=AnalyticsQualityState.INSUFFICIENT_DATA if not n else AnalyticsQualityState.LIMITED if adequacy in (SampleAdequacyState.INSUFFICIENT,SampleAdequacyState.LIMITED) else AnalyticsQualityState.VALID
        if not n:
            unavailable=self._undefined("INSUFFICIENT_SAMPLE",MetricAvailability.INSUFFICIENT_DATA);summary=ResearchPerformanceSummary(query.scope,0,unavailable,unavailable,unavailable,unavailable,unavailable,unavailable,unavailable,unavailable,unavailable,unavailable,0,0,unavailable,unavailable,adequacy,quality,query.start_time_utc,query.end_time_utc,query.as_of_time_utc);confidence=ConfidenceMetadata(0,0,adequacy,unavailable,None,None,"ANALYTICAL_95_PERCENT")
            trace=self._trace(query,(),excluded,quality);sid=deterministic_id("analytics_snapshot",query.query_id,source,METRIC_VERSION,epoch);return ResearchAnalyticsSnapshot(sid,query.query_id,query.scope,0,0,len(excluded),adequacy,summary,None,None,None,(),(),AnalyticsTrendState.INSUFFICIENT_DATA,quality,confidence,(),tuple(sorted(set(excluded))),query.start_time_utc,query.end_time_utc,query.as_of_time_utc,query.dataset_fingerprint,query.configuration_snapshot_id,source,(METRIC_VERSION,),VERSION,epoch,trace)
        positive=[v for v in values if v>self.configuration.zero_tolerance];negative=[v for v in values if v<-self.configuration.zero_tolerance];flat=[v for v in values if abs(v)<=self.configuration.zero_tolerance]
        cumulative=self._q(sum(values,ZERO));mean=self._q(cumulative/Decimal(n));med=self._q(Decimal(str(median(values))));rates=[self._q(Decimal(len(x))/Decimal(n)) for x in (positive,negative,flat)]
        variance=self._q(sum(((v-mean)*(v-mean) for v in values),ZERO)/Decimal(n));sd=self._sqrt(variance);distribution=self._distribution(items,values,mean,variance,sd);sequence=self._sequences(items);decline=self._decline(items);ratio=self._undefined("NO_NEGATIVE_OBSERVATIONS") if not negative else self._metric(sum(positive,ZERO)/abs(sum(negative,ZERO)))
        avg_pos=sum(positive,ZERO)/Decimal(len(positive)) if positive else ZERO;avg_neg=sum(negative,ZERO)/Decimal(len(negative)) if negative else ZERO;expectancy=self._q(rates[0]*avg_pos-rates[1]*abs(avg_neg));expectancy_metric=self._metric(expectancy,"ANALYTICS_VALID" if abs(expectancy-mean)<=self.configuration.precision else "EXPECTANCY_CONSISTENCY_WARNING")
        stability=self._undefined("ZERO_VARIANCE") if sd==ZERO else self._metric(mean/sd);down=[min(v,ZERO) for v in values];downside=self._sqrt(self._q(sum((v*v for v in down),ZERO)/Decimal(n)));down_stability=self._undefined("NO_DOWNSIDE_VARIATION") if downside==ZERO else self._metric(mean/downside);recovery=self._undefined("INVALID_DENOMINATOR") if decline.maximum_r_decline<=ZERO else self._metric(cumulative/decline.maximum_r_decline)
        summary=ResearchPerformanceSummary(query.scope,n,self._metric(cumulative),self._metric(mean),self._metric(med),expectancy_metric,self._metric(rates[0]),self._metric(rates[1]),self._metric(rates[2]),ratio,self._metric(decline.maximum_r_decline),recovery,sequence.maximum_positive_sequence,sequence.maximum_negative_sequence,stability,down_stability,adequacy,quality,query.start_time_utc,query.end_time_utc,query.as_of_time_utc)
        se=self._undefined("INSUFFICIENT_SAMPLE",MetricAvailability.INSUFFICIENT_DATA) if n<2 else self._metric(sd/Decimal(str(sqrt(n))));margin=self._q(Decimal("1.96")*se.value) if se.value is not None else None;confidence=ConfidenceMetadata(n,n,adequacy,se,self._q(mean-margin) if margin is not None else None,self._q(mean+margin) if margin is not None else None,"ANALYTICAL_95_PERCENT")
        durations=[Decimal(str(x.duration.total_seconds())) for x in items];duration_stats=(("average_seconds",self._q(sum(durations,ZERO)/Decimal(n))),("median_seconds",self._q(Decimal(str(median(durations))))),("minimum_seconds",min(durations)),("maximum_seconds",max(durations)))
        trend=self._trend(values);trace=self._trace(query,tuple(x.observation_id for x in items),excluded,quality);sid=deterministic_id("analytics_snapshot",query.query_id,source,METRIC_VERSION,epoch)
        return ResearchAnalyticsSnapshot(sid,query.query_id,query.scope,n,n,len(excluded),adequacy,summary,distribution,sequence,decline,duration_stats,(),trend,quality,confidence,tuple(x.observation_id for x in items),tuple(sorted(set(excluded))),query.start_time_utc,query.end_time_utc,query.as_of_time_utc,query.dataset_fingerprint,query.configuration_snapshot_id,source,(METRIC_VERSION,),VERSION,epoch,trace)

    def _validate(self,o,as_of):
        required=(o.hypothesis_id,o.strategy_id,o.strategy_version,o.subject_id,o.dataset_fingerprint,o.configuration_snapshot_id,o.lifecycle_snapshot_id,o.phase_vii_safety_snapshot_id)
        if not all(required):return "OUTCOME_MISSING_METADATA"
        if not o.normalized_outcome_r.is_finite() or o.outcome_classification in (OutcomeClassification.INVALID,OutcomeClassification.UNKNOWN):return "OUTCOME_INVALID"
        if o.opened_at_utc>o.closed_at_utc or o.closed_at_utc>o.known_at_utc or o.known_at_utc>as_of:return "OUTCOME_FUTURE"
        if o.configuration_snapshot_id!=self.configuration.configuration_snapshot_id:return "OUTCOME_CONFIGURATION_MISMATCH"
        return None
    def _validate_query(self,q):
        if q.start_time_utc>q.end_time_utc or q.end_time_utc>q.as_of_time_utc:return "ANALYTICS_QUERY_TEMPORAL_INVALID"
        if not q.dataset_fingerprint or q.configuration_snapshot_id!=self.configuration.configuration_snapshot_id:return "ANALYTICS_QUERY_LINEAGE_INVALID"
        if q.rolling_window is not None and q.rolling_window<1:return "ANALYTICS_ROLLING_WINDOW_INVALID"
        return None
    def _exclusion(self,o,q):
        if o.known_at_utc>q.as_of_time_utc:return "OUTCOME_FUTURE"
        if not q.start_time_utc<=o.closed_at_utc<=q.end_time_utc:return "OUTCOME_OUTSIDE_PERIOD"
        if o.dataset_fingerprint!=q.dataset_fingerprint:return "OUTCOME_DATASET_MISMATCH"
        if o.configuration_snapshot_id!=q.configuration_snapshot_id:return "OUTCOME_CONFIGURATION_MISMATCH"
        for key,value in q.filters:
            try:
                if str(getattr(o,self._field(key)))!=value:return "OUTCOME_SCOPE_MISMATCH"
            except ValueError:return "OUTCOME_SCOPE_MISMATCH"
        return None
    @staticmethod
    def _field(dimension):
        aliases={"strategy":"strategy_id","strategy_version":"strategy_version","variant":"variant_id","family":"family_id","subject":"subject_id","category":"category_id","regime":"regime_id","session":"session_id","timeframe":"timeframe_id","safety":"phase_vii_safety_state"};field=aliases.get(dimension,dimension)
        if field not in ResearchOutcomeObservation.__dataclass_fields__:raise ValueError("ANALYTICS_DIMENSION_UNSUPPORTED")
        return field
    def _adequacy(self,n,override=None):
        minimum=override or self.configuration.limited_sample
        if n<minimum:return SampleAdequacyState.INSUFFICIENT
        if n<self.configuration.adequate_sample:return SampleAdequacyState.LIMITED
        if n<self.configuration.strong_sample:return SampleAdequacyState.ADEQUATE
        return SampleAdequacyState.STRONG
    def _distribution(self,items,values,mean,variance,sd):
        q=lambda p:self._quantile(values,p);q25=q(Decimal(".25"));q75=q(Decimal(".75"));med=q(Decimal(".5"));deviations=[abs(v-med) for v in values];mad=self._quantile(deviations,Decimal(".5"));outliers=tuple(items[i].observation_id for i,v in enumerate(values) if mad>ZERO and abs(v-med)/mad>Decimal("3.5"));count=min(self.configuration.worst_best_n,len(values));ordered=sorted(values)
        return DistributionStatistics(min(values),max(values),mean,med,sd,variance,q25,q75,self._q(q75-q25),q(Decimal(".05")),q25,med,q75,q(Decimal(".95")),self._q(sum(ordered[:count],ZERO)/Decimal(count)),self._q(sum(ordered[-count:],ZERO)/Decimal(count)),outliers)
    def _quantile(self,values,p):
        ordered=sorted(values)
        if len(ordered)==1:return ordered[0]
        position=p*Decimal(len(ordered)-1);lower=int(position);upper=min(lower+1,len(ordered)-1);fraction=position-Decimal(lower);return self._q(ordered[lower]+(ordered[upper]-ordered[lower])*fraction)
    def _sequences(self,items):
        pos=[];neg=[];current_kind=None;count=0;magnitude=ZERO
        for item in items:
            kind="p" if item.outcome_classification is OutcomeClassification.POSITIVE else "n" if item.outcome_classification is OutcomeClassification.NEGATIVE else "f"
            if kind=="f":
                if current_kind and count:(pos if current_kind=="p" else neg).append((count,magnitude))
                current_kind=None;count=0;magnitude=ZERO;continue
            if kind!=current_kind:
                if current_kind and count:(pos if current_kind=="p" else neg).append((count,magnitude))
                current_kind=kind;count=0;magnitude=ZERO
            count+=1;magnitude+=abs(item.normalized_outcome_r)
        if current_kind and count:(pos if current_kind=="p" else neg).append((count,magnitude))
        def stats(seq):return (max((x[0] for x in seq),default=0),self._q(Decimal(sum(x[0] for x in seq))/Decimal(len(seq))) if seq else ZERO,max((x[1] for x in seq),default=ZERO),self._q(sum((x[1] for x in seq),ZERO)/Decimal(len(seq))) if seq else ZERO)
        nm,na,nmag,navg=stats(neg);pm,pa,pmag,pavg=stats(pos);last=items[-1].outcome_classification;cn=neg[-1][0] if neg and last is OutcomeClassification.NEGATIVE else 0;cp=pos[-1][0] if pos and last is OutcomeClassification.POSITIVE else 0
        return SequenceStatistics(cn,nm,na,len(neg),nmag,navg,cp,pm,pa,len(pos),pmag,pavg)
    def _decline(self,items):
        cumulative=ZERO;peak=ZERO;max_decline=ZERO;current=ZERO;peak_time=None;start=None;trough=None;recovery=None;path=[];max_start=None
        for item in items:
            cumulative=self._q(cumulative+item.normalized_outcome_r);path.append((item.known_at_utc,cumulative))
            if cumulative>=peak:
                if start is not None:recovery=item.known_at_utc
                peak=cumulative;peak_time=item.known_at_utc;start=None
            current=self._q(peak-cumulative)
            if current>ZERO and start is None:start=peak_time or item.known_at_utc
            if current>max_decline:max_decline=current;max_start=start;trough=item.known_at_utc;recovery=None
        decline_duration=(trough-max_start) if trough and max_start else None;recovery_duration=(recovery-trough) if recovery and trough else None
        return DeclineStatistics(tuple(path),peak,current,max_decline,max_start,trough,recovery,decline_duration,recovery_duration)
    def _trend(self,values):
        if len(values)<self.configuration.rolling_minimum*2:return AnalyticsTrendState.INSUFFICIENT_DATA
        half=len(values)//2;a=sum(values[:half],ZERO)/Decimal(half);b=sum(values[half:],ZERO)/Decimal(len(values)-half);delta=b-a
        return AnalyticsTrendState.IMPROVING if delta>self.configuration.trend_tolerance else AnalyticsTrendState.DETERIORATING if delta<-self.configuration.trend_tolerance else AnalyticsTrendState.STABLE
    def _q(self,value):return Decimal(value).quantize(self.configuration.precision)
    def _sqrt(self,value):
        with localcontext() as ctx:ctx.prec=28;return self._q(Decimal(value).sqrt())
    def _metric(self,value,reason="ANALYTICS_VALID"):return MetricValue(self._q(value),MetricAvailability.AVAILABLE,reason)
    @staticmethod
    def _undefined(reason,state=MetricAvailability.UNDEFINED):return MetricValue(None,state,reason)
    def _trace(self,q,included,excluded,quality):
        reason="ANALYTICS_VALID" if quality is AnalyticsQualityState.VALID else "ANALYTICS_LIMITED";evaluation=DecisionEvaluation("RESEARCH_ANALYTICS",DecisionStatus.PASSED,reason,f"Included {len(included)} immutable observations",included);tid=deterministic_id("analytics_trace",q.query_id,*included,*excluded,reason);return DecisionTrace(tid,q.query_id,q.as_of_time_utc,(evaluation,),DecisionOutcome.ACCEPTED,reason,q.as_of_time_utc,None)
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
