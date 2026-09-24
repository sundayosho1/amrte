"""Point-in-time correlation and dependency controls for fictional research only.

This module consumes immutable Prompt 7 return evidence and Prompt 22 portfolio
state.  It has no market-data acquisition, account, broker, or execution surface.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR, localcontext
from enum import Enum, auto
from math import fsum, isfinite, sqrt

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation, DecisionOutcome, DecisionStatus, DecisionTrace
from amrte.risk.invalidation import ResearchDirection
from amrte.risk.sizing import _decimal
from .risk import AdmissionOutcome, DeterministicExposureDecomposer, ICorrelationRiskProvider, PortfolioAdmissionRequest, PortfolioExposureRecord, PortfolioRiskDecision, PortfolioRiskSnapshot

CORRELATION_ENGINE_VERSION = "1.1"
RECOVERY_SCHEMA_VERSION = "2.0"
ZERO = Decimal("0")


class CorrelationMethod(Enum): PEARSON = auto()
class MissingDataPolicy(Enum): PAIRWISE_COMPLETE = auto(); STRICT_COMMON_WINDOW = auto(); BLOCK_IF_INCOMPLETE = auto()
class CorrelationHealth(Enum): HEALTHY = auto(); DEGRADED = auto(); STALE = auto(); INSUFFICIENT_HISTORY = auto(); ZERO_VARIANCE = auto(); PARTIAL = auto(); INVALID = auto(); UNKNOWN = auto()
class CorrelationState(Enum): STRONG_POSITIVE = auto(); MODERATE_POSITIVE = auto(); WEAK = auto(); MODERATE_NEGATIVE = auto(); STRONG_NEGATIVE = auto(); UNKNOWN = auto()
class DependencyStrength(Enum): LOW = auto(); MEDIUM = auto(); HIGH = auto(); CRITICAL = auto(); UNKNOWN = auto()
class CorrelationDecisionOutcome(Enum): ALLOW_UNCHANGED = auto(); REDUCE_FURTHER = auto(); BLOCK = auto(); NO_ACTION = auto(); INVALID = auto(); UNKNOWN = auto()
class CompositionPolicy(Enum): MOST_RESTRICTIVE_ONLY = auto(); PRIMARY_SOURCE_ONLY = auto(); OVERLAP_CAPPED = auto()
class WindowAggregationPolicy(Enum): MOST_RESTRICTIVE = auto(); WEIGHTED = auto()
class MissingWindowPolicy(Enum): BLOCK = auto(); RESTRICT = auto(); USE_AVAILABLE_IF_MINIMUM_REQUIRED_WINDOWS_MET = auto()
class ClusterLifecycleState(Enum): ABSENT = auto(); ENTRY_PENDING = auto(); ACTIVE = auto(); EXIT_PENDING = auto(); COOLDOWN = auto(); STALE_RESTRICTED = auto(); RECOVERY_RESTRICTED = auto(); UNKNOWN = auto(); INVALID = auto()


@dataclass(frozen=True)
class CorrelationWindow:
    window_id: str; observation_count: int; weight: Decimal = Decimal("1"); required: bool = True; enabled: bool = True


@dataclass(frozen=True)
class CorrelationConfiguration:
    method: CorrelationMethod = CorrelationMethod.PEARSON
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.PAIRWISE_COMPLETE
    lookback_observations: int = 60
    minimum_observations: int = 20
    stale_after_seconds: int = 7200
    moderate_threshold: Decimal = Decimal("0.50")
    strong_threshold: Decimal = Decimal("0.75")
    critical_threshold: Decimal = Decimal("0.90")
    cluster_entry_threshold: Decimal = Decimal("0.75")
    cluster_exit_threshold: Decimal = Decimal("0.60")
    entry_confirmation_count: int = 1
    exit_confirmation_count: int = 2
    cluster_release_cooldown_seconds: int = 0
    maximum_cluster_exposure: Decimal = Decimal("1.00")
    maximum_cluster_risk: Decimal = Decimal("1.00")
    maximum_cluster_members: int = 8
    maximum_cluster_portfolio_share: Decimal = Decimal("1.00")
    maximum_dependency_score: Decimal = Decimal("0.75")
    windows: tuple[CorrelationWindow,...] = ()
    window_aggregation_policy: WindowAggregationPolicy = WindowAggregationPolicy.MOST_RESTRICTIVE
    missing_window_policy: MissingWindowPolicy = MissingWindowPolicy.BLOCK
    minimum_valid_windows: int = 1
    unknown_is_blocking: bool = True
    composition_policy: CompositionPolicy = CompositionPolicy.MOST_RESTRICTIVE_ONLY
    exposure_step: Decimal = Decimal("0.01")
    maximum_snapshots: int = 256
    maximum_decisions: int = 512
    maximum_cache_entries: int = 256
    configuration_snapshot_id: str = "CORRELATION_DEFAULT_RESEARCH"

    def validate(self):
        errors=[]
        try:
            vals=tuple(_decimal(x) for x in (self.moderate_threshold,self.strong_threshold,self.critical_threshold,self.cluster_entry_threshold,self.cluster_exit_threshold,self.maximum_cluster_exposure,self.maximum_cluster_risk,self.maximum_cluster_portfolio_share,self.maximum_dependency_score,self.exposure_step))
            if any(not x.is_finite() for x in vals): errors.append("CORRELATION_NUMERICAL_INVALID")
            if not (ZERO <= vals[0] <= vals[1] <= vals[2] <= Decimal("1")): errors.append("CORRELATION_THRESHOLDS_INVALID")
            if not (ZERO <= vals[4] < vals[3] <= Decimal("1")): errors.append("CORRELATION_HYSTERESIS_INVALID")
            if vals[5] < 0 or vals[6] < 0 or not (ZERO <= vals[7] <= Decimal("1")) or not (ZERO <= vals[8] <= Decimal("1")) or vals[9] <= 0: errors.append("CORRELATION_LIMIT_INVALID")
        except (ValueError,ArithmeticError): errors.append("CORRELATION_NUMERICAL_INVALID")
        if self.lookback_observations < self.minimum_observations or self.minimum_observations < 2 or self.stale_after_seconds < 0: errors.append("CORRELATION_WINDOW_INVALID")
        if self.entry_confirmation_count<1 or self.exit_confirmation_count<1 or self.cluster_release_cooldown_seconds<0:errors.append("CORRELATION_LIFECYCLE_INVALID")
        if self.maximum_cluster_members<1:errors.append("CORRELATION_MEMBER_LIMIT_INVALID")
        enabled=tuple(x for x in self.windows if x.enabled)
        if enabled and (any(x.observation_count<2 or not _decimal(x.weight).is_finite() or x.weight<0 for x in enabled) or len({x.window_id for x in enabled})!=len(enabled)):errors.append("CORRELATION_WINDOWS_INVALID")
        if enabled and (self.minimum_valid_windows<1 or self.minimum_valid_windows>len(enabled)):errors.append("CORRELATION_MINIMUM_WINDOWS_INVALID")
        if min(self.maximum_snapshots,self.maximum_decisions,self.maximum_cache_entries) < 1: errors.append("CORRELATION_BOUND_INVALID")
        return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class ReturnObservation:
    instrument_id: str; timeframe: str; observation_time_utc: datetime; available_at_utc: datetime
    return_value: Decimal; return_type: str; dataset_id: str; dataset_fingerprint: str; source_snapshot_id: str; healthy: bool = True


@dataclass(frozen=True)
class ReturnSeries:
    series_id: str; instrument_id: str; timeframe: str; observations: tuple[ReturnObservation,...]
    dataset_id: str; dataset_fingerprint: str; as_of_timestamp_utc: datetime

    @classmethod
    def create(cls,instrument_id,timeframe,observations,dataset_id,dataset_fingerprint,as_of):
        admitted=tuple(sorted((x for x in observations if x.instrument_id==instrument_id and x.timeframe==timeframe and x.available_at_utc<=as_of and x.observation_time_utc<=as_of),key=lambda x:(x.observation_time_utc,x.source_snapshot_id)))
        sid=deterministic_id("return_series",instrument_id,timeframe,dataset_id,dataset_fingerprint,as_of.isoformat(),*(f"{x.observation_time_utc.isoformat()}:{x.return_value}" for x in admitted))
        return cls(sid,instrument_id,timeframe,admitted,dataset_id,dataset_fingerprint,as_of)


@dataclass(frozen=True)
class PairwiseCorrelationRecord:
    pair_id: str; instrument_a: str; instrument_b: str; correlation: Decimal|None; adjusted_dependency: Decimal|None
    aligned_observations: int; state: CorrelationState; strength: DependencyStrength; health: CorrelationHealth
    window_start_utc: datetime|None; window_end_utc: datetime|None; reason_codes: tuple[str,...]


@dataclass(frozen=True)
class CorrelationMatrixCell:
    row_instrument_id: str; column_instrument_id: str; correlation: Decimal|None
    adjusted_dependency: Decimal|None; pair_id: str|None; health: CorrelationHealth


@dataclass(frozen=True)
class CorrelationMatrixSnapshot:
    snapshot_id: str; instrument_ids: tuple[str,...]; cells: tuple[tuple[CorrelationMatrixCell,...],...]
    pairwise_correlation_ids: tuple[str,...]; timeframe: str; return_type: str; window_id: str
    observation_count: int; health: CorrelationHealth; as_of_timestamp_utc: datetime
    dataset_id: str; dataset_fingerprint: str; configuration_snapshot_id: str; engine_version: str; recovery_epoch: int


@dataclass(frozen=True)
class MultiWindowPairDependency:
    instrument_a: str; instrument_b: str; dependency: Decimal|None; valid_windows: int
    required_windows: int; influencing_window_ids: tuple[str,...]; health: CorrelationHealth


@dataclass(frozen=True)
class MultiWindowCorrelationSnapshot:
    snapshot_id: str; matrix_snapshot_ids: tuple[str,...]; windows: tuple[CorrelationWindow,...]
    aggregated_pairs: tuple[MultiWindowPairDependency,...]; aggregation_policy: WindowAggregationPolicy
    health: CorrelationHealth; valid_window_count: int; required_window_count: int
    restrictions: tuple[str,...]; as_of_timestamp_utc: datetime; configuration_snapshot_id: str; recovery_epoch: int


@dataclass(frozen=True)
class FactorExposureCell:
    instrument_id: str; factor_id: str; signed_exposure: Decimal


@dataclass(frozen=True)
class FactorExposureMatrixSnapshot:
    matrix_id: str; factors: tuple[str,...]; instruments: tuple[str,...]; cells: tuple[FactorExposureCell,...]
    portfolio_snapshot_id: str; as_of_timestamp_utc: datetime


@dataclass(frozen=True)
class CorrelationCluster:
    cluster_id: str; instrument_ids: tuple[str,...]; pair_ids: tuple[str,...]; gross_exposure: Decimal
    highest_dependency: Decimal; health: CorrelationHealth


@dataclass(frozen=True)
class PublishedClusterState:
    logical_id: str; version_id: str; member_ids: tuple[str,...]; state: ClusterLifecycleState
    previous_state: ClusterLifecycleState; entry_count: int; exit_count: int; last_counted_observation_id: str
    cooldown_start_utc: datetime|None; cooldown_until_utc: datetime|None; parent_version_ids: tuple[str,...]
    last_valid_correlation_snapshot_id: str; last_valid_portfolio_snapshot_id: str
    transitioned_at_utc: datetime; transition_reason: str; recovery_epoch: int


@dataclass(frozen=True)
class CorrelationRiskSnapshot:
    snapshot_id: str; portfolio_snapshot_id: str; factor_matrix_id: str; correlation_matrix_id: str; multi_window_snapshot_id: str|None; instruments: tuple[str,...]
    pairwise: tuple[PairwiseCorrelationRecord,...]; clusters: tuple[CorrelationCluster,...]
    published_clusters: tuple[PublishedClusterState,...]
    health: CorrelationHealth; restrictions: tuple[str,...]; reason_codes: tuple[str,...]
    dataset_id: str; dataset_fingerprint: str; as_of_timestamp_utc: datetime
    configuration_snapshot_id: str; engine_version: str; recovery_epoch: int


@dataclass(frozen=True)
class CandidateDependencyImpact:
    impact_id: str; request_id: str; correlated_instruments: tuple[str,...]; affected_cluster_ids: tuple[str,...]
    projected_cluster_exposure: Decimal; highest_adjusted_dependency: Decimal|None; health: CorrelationHealth


@dataclass(frozen=True)
class CorrelationRiskDecision:
    decision_id: str; request_id: str; portfolio_decision_id: str; correlation_snapshot_id: str
    proposed_exposure: Decimal; prompt22_approved_exposure: Decimal; approved_exposure: Decimal
    outcome: CorrelationDecisionOutcome; impact: CandidateDependencyImpact; reduction_applied: bool
    restrictions: tuple[str,...]; reason_codes: tuple[str,...]; as_of_timestamp_utc: datetime
    configuration_snapshot_id: str; engine_version: str; recovery_epoch: int; decision_trace: DecisionTrace


class CorrelationDependencyEngine(ICorrelationRiskProvider):
    def __init__(self,configuration=CorrelationConfiguration(),decomposer=None,audit=None):
        errors=configuration.validate()
        if errors: raise ValueError(";".join(errors))
        self.configuration=configuration; self.decomposer=decomposer or DeterministicExposureDecomposer(); self.audit=audit
        self.snapshots=OrderedDict(); self.decisions=OrderedDict(); self.matrices=OrderedDict(); self.multi_window_snapshots=OrderedDict(); self.cluster_versions=OrderedDict(); self.cluster_states=OrderedDict(); self._cache=OrderedDict(); self.recovery_restricted=False

    def available(self): return True

    def pair(self,a:ReturnSeries,b:ReturnSeries,direction_a=ResearchDirection.BULLISH,direction_b=ResearchDirection.BULLISH,as_of=None,window=None):
        as_of=as_of or min(a.as_of_timestamp_utc,b.as_of_timestamp_utc); cfg=self.configuration
        explicit_window=window is not None;window=window or CorrelationWindow("DEFAULT",cfg.lookback_observations)
        if a.dataset_id!=b.dataset_id or a.dataset_fingerprint!=b.dataset_fingerprint or a.timeframe!=b.timeframe:
            return self._bad_pair(a,b,CorrelationHealth.INVALID,"CORRELATION_LINEAGE_MISMATCH")
        left={x.observation_time_utc:x for x in a.observations if x.available_at_utc<=as_of and x.observation_time_utc<=as_of and x.healthy}
        right={x.observation_time_utc:x for x in b.observations if x.available_at_utc<=as_of and x.observation_time_utc<=as_of and x.healthy}
        keys=sorted(set(left)&set(right))[-window.observation_count:]
        if cfg.missing_data_policy is not MissingDataPolicy.PAIRWISE_COMPLETE and set(left)!=set(right):
            return self._bad_pair(a,b,CorrelationHealth.PARTIAL,"CORRELATION_ALIGNMENT_INCOMPLETE",len(keys))
        required=window.observation_count if explicit_window else cfg.minimum_observations
        if len(keys)<required:return self._bad_pair(a,b,CorrelationHealth.INSUFFICIENT_HISTORY,"CORRELATION_INSUFFICIENT_HISTORY",len(keys))
        end=keys[-1]
        if as_of-end>timedelta(seconds=cfg.stale_after_seconds):return self._bad_pair(a,b,CorrelationHealth.STALE,"CORRELATION_DATA_STALE",len(keys),keys[0],end)
        xs=[float(left[k].return_value) for k in keys]; ys=[float(right[k].return_value) for k in keys]
        if any(not isfinite(x) for x in xs+ys):return self._bad_pair(a,b,CorrelationHealth.INVALID,"CORRELATION_VALUE_INVALID",len(keys),keys[0],end)
        mx=fsum(xs)/len(xs); my=fsum(ys)/len(ys); dx=[x-mx for x in xs]; dy=[y-my for y in ys]; vx=fsum(x*x for x in dx); vy=fsum(y*y for y in dy)
        if vx<=0 or vy<=0:return self._bad_pair(a,b,CorrelationHealth.ZERO_VARIANCE,"CORRELATION_ZERO_VARIANCE",len(keys),keys[0],end)
        raw=max(-1.0,min(1.0,fsum(x*y for x,y in zip(dx,dy))/sqrt(vx*vy))); corr=Decimal(str(round(raw,12)))
        sign_a=Decimal("1") if direction_a is ResearchDirection.BULLISH else Decimal("-1"); sign_b=Decimal("1") if direction_b is ResearchDirection.BULLISH else Decimal("-1"); adjusted=corr*sign_a*sign_b
        state=self._state(corr); strength=self._strength(max(ZERO,adjusted)); pid=deterministic_id("correlation_pair",*sorted((a.instrument_id,b.instrument_id)),a.series_id,b.series_id,window.window_id,window.observation_count,str(corr),direction_a.name,direction_b.name,cfg.configuration_snapshot_id)
        return PairwiseCorrelationRecord(pid,a.instrument_id,b.instrument_id,corr,adjusted,len(keys),state,strength,CorrelationHealth.HEALTHY,keys[0],end,("CORRELATION_PAIR_HEALTHY",))

    def correlation_matrix(self,series_by_instrument,directions,as_of,window=None,recovery_epoch=0):
        cfg=self.configuration; explicit_window=window is not None;window=window or CorrelationWindow("DEFAULT",cfg.lookback_observations); instruments=tuple(sorted(set(series_by_instrument)|set(directions))); pairmap={}; pair_ids=[]
        for i,a_id in enumerate(instruments):
            for b_id in instruments[i+1:]:
                a=series_by_instrument.get(a_id);b=series_by_instrument.get(b_id)
                p=self._missing_pair(a_id,b_id) if not a or not b else self.pair(a,b,directions.get(a_id,ResearchDirection.BULLISH),directions.get(b_id,ResearchDirection.BULLISH),as_of,window if explicit_window else None)
                pairmap[(a_id,b_id)]=p;pair_ids.append(p.pair_id)
        rows=[];healths=[]
        for a_id in instruments:
            row=[]
            for b_id in instruments:
                if a_id==b_id:
                    s=series_by_instrument.get(a_id)
                    p=self._missing_pair(a_id,b_id) if not s else self.pair(s,s,directions.get(a_id,ResearchDirection.BULLISH),directions.get(a_id,ResearchDirection.BULLISH),as_of,window if explicit_window else None)
                    corr=Decimal("1") if p.health is CorrelationHealth.HEALTHY else None; dep=corr; pid=p.pair_id; h=p.health
                else:
                    p=pairmap[tuple(sorted((a_id,b_id)))];corr=p.correlation;dep=p.adjusted_dependency;pid=p.pair_id;h=p.health
                row.append(CorrelationMatrixCell(a_id,b_id,corr,dep,pid,h));healths.append(h)
            rows.append(tuple(row))
        health=self._aggregate_health(healths); sample=next(iter(series_by_instrument.values()),None);dataset=sample.dataset_id if sample else "UNKNOWN";fingerprint=sample.dataset_fingerprint if sample else "UNKNOWN";timeframe=sample.timeframe if sample else "UNKNOWN";rtype=sample.observations[0].return_type if sample and sample.observations else "UNKNOWN"
        sid=deterministic_id("correlation_matrix",*instruments,*sorted(pair_ids),timeframe,rtype,window.window_id,window.observation_count,as_of.isoformat(),dataset,fingerprint,cfg.configuration_snapshot_id,CORRELATION_ENGINE_VERSION,recovery_epoch)
        result=CorrelationMatrixSnapshot(sid,instruments,tuple(rows),tuple(sorted(set(pair_ids))),timeframe,rtype,window.window_id,window.observation_count,health,as_of,dataset,fingerprint,cfg.configuration_snapshot_id,CORRELATION_ENGINE_VERSION,recovery_epoch);self.matrices[sid]=result;self._bound();return result

    def multi_window(self,series_by_instrument,directions,as_of,recovery_epoch=0):
        cfg=self.configuration;windows=tuple(x for x in cfg.windows if x.enabled) or (CorrelationWindow("DEFAULT",cfg.lookback_observations),);matrices=tuple(self.correlation_matrix(series_by_instrument,directions,as_of,w,recovery_epoch) for w in windows);pairs=[];restrictions=[]
        for i,a in enumerate(matrices[0].instrument_ids if matrices else ()):
            for b in (matrices[0].instrument_ids if matrices else ())[i+1:]:
                items=[]
                for w,m in zip(windows,matrices):
                    ai=m.instrument_ids.index(a);bi=m.instrument_ids.index(b);c=m.cells[ai][bi]
                    if c.health is CorrelationHealth.HEALTHY and c.adjusted_dependency is not None:items.append((w,c.adjusted_dependency))
                    elif w.required:restrictions.append(f"CORRELATION_WINDOW_{w.window_id}_{c.health.name}")
                required=sum(1 for w in windows if w.required);valid=len(items)
                if valid<cfg.minimum_valid_windows or (cfg.missing_window_policy is MissingWindowPolicy.BLOCK and any(w.required and all(iw.window_id!=w.window_id for iw,_ in items) for w in windows)):
                    dep=None;health=CorrelationHealth.PARTIAL;influencing=()
                elif cfg.window_aggregation_policy is WindowAggregationPolicy.MOST_RESTRICTIVE:
                    dep=max((v for _,v in items),default=None);influencing=tuple(sorted(w.window_id for w,v in items if v==dep));health=CorrelationHealth.HEALTHY if valid==len(windows) else CorrelationHealth.DEGRADED
                else:
                    total=sum((w.weight for w,_ in items),ZERO);dep=(sum((v*w.weight for w,v in items),ZERO)/total) if total>0 else None;influencing=tuple(sorted(w.window_id for w,_ in items));health=CorrelationHealth.HEALTHY if valid==len(windows) else CorrelationHealth.DEGRADED
                pairs.append(MultiWindowPairDependency(a,b,dep,valid,required,influencing,health))
        health=self._aggregate_health([m.health for m in matrices]+[p.health for p in pairs]);sid=deterministic_id("multi_window_correlation",*(m.snapshot_id for m in matrices),cfg.window_aggregation_policy.name,cfg.missing_window_policy.name,cfg.minimum_valid_windows,as_of.isoformat(),cfg.configuration_snapshot_id,recovery_epoch)
        result=MultiWindowCorrelationSnapshot(sid,tuple(m.snapshot_id for m in matrices),windows,tuple(pairs),cfg.window_aggregation_policy,health,sum(1 for m in matrices if m.health is CorrelationHealth.HEALTHY),sum(1 for w in windows if w.required),tuple(sorted(set(restrictions))),as_of,cfg.configuration_snapshot_id,recovery_epoch);self.multi_window_snapshots[sid]=result;self._bound();self._record("multi_window_correlation_created",{"snapshot_id":sid});return result

    def factor_matrix(self,portfolio:PortfolioRiskSnapshot,records,as_of):
        cells=[]
        for item in sorted(records,key=lambda x:x.exposure_record_id):
            if item.updated_at_utc>as_of or item.remaining_exposure<=0: continue
            legs=self.decomposer.decompose(item.instrument_id,item.direction,item.remaining_exposure,as_of,item.dataset_id)
            if legs is None: continue
            cells.extend(FactorExposureCell(item.instrument_id,f,v) for f,v in legs)
        totals=defaultdict(lambda:ZERO)
        for c in cells: totals[(c.instrument_id,c.factor_id)]+=c.signed_exposure
        merged=tuple(FactorExposureCell(i,f,v) for (i,f),v in sorted(totals.items())); instruments=tuple(sorted({x.instrument_id for x in merged})); factors=tuple(sorted({x.factor_id for x in merged})); mid=deterministic_id("factor_exposure_matrix",portfolio.snapshot_id,*(f"{x.instrument_id}:{x.factor_id}:{x.signed_exposure}" for x in merged))
        return FactorExposureMatrixSnapshot(mid,factors,instruments,merged,portfolio.snapshot_id,as_of)

    def snapshot(self,portfolio:PortfolioRiskSnapshot,records,series_by_instrument,as_of,recovery_epoch=0):
        matrix=self.factor_matrix(portfolio,records,as_of); active={x.instrument_id:x for x in records if x.updated_at_utc<=as_of and x.remaining_exposure>0}; instruments=tuple(sorted(active)); pairs=[]; restrictions=[];directions={k:v.direction for k,v in active.items()}
        dataset_id=next((x.dataset_id for x in active.values()),"UNKNOWN"); fingerprint=next((x.dataset_fingerprint for x in series_by_instrument.values()),"UNKNOWN")
        for index,a_id in enumerate(instruments):
            for b_id in instruments[index+1:]:
                a=series_by_instrument.get(a_id); b=series_by_instrument.get(b_id)
                if not a or not b: p=self._missing_pair(a_id,b_id)
                else:p=self.pair(a,b,active[a_id].direction,active[b_id].direction,as_of)
                pairs.append(p)
                if p.health is not CorrelationHealth.HEALTHY:restrictions.append(f"CORRELATION_{p.health.name}")
        correlation_matrix=self.correlation_matrix({k:v for k,v in series_by_instrument.items() if k in active},directions,as_of,recovery_epoch=recovery_epoch);multi=self.multi_window({k:v for k,v in series_by_instrument.items() if k in active},directions,as_of,recovery_epoch) if self.configuration.windows else None
        clusters=self._clusters(tuple(pairs),active);retained=self._clusters(tuple(pairs),active,self.configuration.cluster_exit_threshold)
        health=CorrelationHealth.HEALTHY if not restrictions else CorrelationHealth.PARTIAL if pairs else CorrelationHealth.UNKNOWN
        observation_id=deterministic_id("cluster_observation",correlation_matrix.snapshot_id,portfolio.snapshot_id,as_of.isoformat());published=self._update_cluster_lifecycle(clusters,retained,health,observation_id,correlation_matrix.snapshot_id,portfolio.snapshot_id,as_of,recovery_epoch)
        sid=deterministic_id("correlation_risk_snapshot",portfolio.snapshot_id,matrix.matrix_id,correlation_matrix.snapshot_id,multi.snapshot_id if multi else "NONE",*(x.pair_id for x in pairs),*(x.version_id for x in published),as_of.isoformat(),self.configuration.configuration_snapshot_id,CORRELATION_ENGINE_VERSION,recovery_epoch)
        result=CorrelationRiskSnapshot(sid,portfolio.snapshot_id,matrix.matrix_id,correlation_matrix.snapshot_id,multi.snapshot_id if multi else None,instruments,tuple(pairs),clusters,published,health,tuple(sorted(set(restrictions))),tuple("CORRELATION_SNAPSHOT_CREATED" for _ in (0,)),dataset_id,fingerprint,as_of,self.configuration.configuration_snapshot_id,CORRELATION_ENGINE_VERSION,recovery_epoch)
        self.snapshots[sid]=result; self._bound(); self._record("correlation_snapshot_created",{"snapshot_id":sid}); return result

    def assess(self,request:PortfolioAdmissionRequest,portfolio_decision:PortfolioRiskDecision,snapshot:CorrelationRiskSnapshot,records,series_by_instrument):
        cfg=self.configuration; as_of=request.as_of_timestamp_utc; approved=min(max(ZERO,_decimal(request.proposed_exposure)),portfolio_decision.approved_exposure); reasons=[]; restrictions=[]; correlated=[]; affected=[]; highest=None; projected=approved
        no_action=_decimal(request.proposed_exposure)<=0 or portfolio_decision.outcome is AdmissionOutcome.NO_ACTION
        invalid=self.recovery_restricted or portfolio_decision.outcome not in (AdmissionOutcome.ALLOW_FULL,AdmissionOutcome.ALLOW_REDUCED,AdmissionOutcome.NO_ACTION) or snapshot.as_of_timestamp_utc>as_of or request.configuration_snapshot_id not in (portfolio_decision.configuration_snapshot_id,snapshot.configuration_snapshot_id)
        active={x.instrument_id:x for x in records if x.updated_at_utc<=as_of and x.remaining_exposure>0}
        candidate_series=series_by_instrument.get(request.instrument_id)
        pair_health=CorrelationHealth.HEALTHY
        for instrument,item in sorted(active.items()):
            other=series_by_instrument.get(instrument)
            if not candidate_series or not other:p=self._missing_pair(request.instrument_id,instrument);dep=None
            elif cfg.windows:dep,pair_health=self._candidate_multi_dependency(candidate_series,other,request.direction,item.direction,as_of);p=None
            else:p=self.pair(candidate_series,other,request.direction,item.direction,as_of);dep=p.adjusted_dependency
            health=pair_health if cfg.windows and p is None else p.health
            if health is not CorrelationHealth.HEALTHY: pair_health=health; restrictions.append(f"CORRELATION_{health.name}"); continue
            dep=max(ZERO,dep or ZERO)
            if highest is None or dep>highest: highest=dep
            if dep>=cfg.cluster_entry_threshold: correlated.append(instrument); projected+=item.remaining_exposure
        cluster_existing_exposure=sum((x.remaining_exposure for k,x in active.items() if k in correlated),ZERO);cluster_existing_risk=sum((x.current_risk for k,x in active.items() if k in correlated),ZERO);candidate_risk_ratio=(portfolio_decision.approved_risk/portfolio_decision.approved_exposure) if portfolio_decision.approved_exposure>0 else ZERO;member_count=len(correlated)+(0 if request.instrument_id in correlated else 1);total= snapshot and sum((x.remaining_exposure for x in active.values()),ZERO)
        capacities=[cfg.maximum_cluster_exposure-cluster_existing_exposure]
        if candidate_risk_ratio>0:capacities.append((cfg.maximum_cluster_risk-cluster_existing_risk)/candidate_risk_ratio)
        elif cluster_existing_risk>cfg.maximum_cluster_risk:capacities.append(ZERO)
        if cfg.maximum_cluster_portfolio_share<1:
            share_capacity=(cfg.maximum_cluster_portfolio_share*total-cluster_existing_exposure)/(Decimal("1")-cfg.maximum_cluster_portfolio_share);capacities.append(share_capacity)
        allowed=self._floor(max(ZERO,min([approved]+capacities)))
        if no_action:approved=ZERO;outcome=CorrelationDecisionOutcome.NO_ACTION;reasons.append("CORRELATION_NO_ACTION")
        elif invalid: approved=ZERO; outcome=CorrelationDecisionOutcome.BLOCK; reasons.append("CORRELATION_UPSTREAM_BLOCK")
        elif pair_health is not CorrelationHealth.HEALTHY and cfg.unknown_is_blocking: approved=ZERO; outcome=CorrelationDecisionOutcome.BLOCK; reasons.append("CORRELATION_REQUIRED_DATA_UNAVAILABLE")
        elif correlated and member_count>cfg.maximum_cluster_members:approved=ZERO;outcome=CorrelationDecisionOutcome.BLOCK;reasons.append("CORRELATION_CLUSTER_MEMBER_LIMIT")
        elif correlated and (allowed<approved or projected>cfg.maximum_cluster_exposure or cluster_existing_risk+portfolio_decision.approved_risk>cfg.maximum_cluster_risk):
            approved=allowed; outcome=CorrelationDecisionOutcome.REDUCE_FURTHER if approved>0 else CorrelationDecisionOutcome.BLOCK; reasons.append("CORRELATION_CLUSTER_LIMIT")
        else: outcome=CorrelationDecisionOutcome.ALLOW_UNCHANGED; reasons.append("CORRELATION_ALLOW_UNCHANGED")
        reduction=approved<portfolio_decision.approved_exposure
        for c in snapshot.clusters:
            if set(c.instrument_ids)&set(correlated): affected.append(c.cluster_id)
        impact_id=deterministic_id("candidate_dependency_impact",request.request_id,snapshot.snapshot_id,*correlated,str(projected),str(highest))
        impact=CandidateDependencyImpact(impact_id,request.request_id,tuple(correlated),tuple(sorted(affected)),projected,highest,pair_health)
        did=deterministic_id("correlation_risk_decision",request.request_id,portfolio_decision.decision_id,snapshot.snapshot_id,outcome.name,str(approved),cfg.configuration_snapshot_id)
        status=DecisionStatus.PASSED if outcome in (CorrelationDecisionOutcome.ALLOW_UNCHANGED,CorrelationDecisionOutcome.NO_ACTION) else DecisionStatus.FAILED; checks=(DecisionEvaluation("PROMPT22_PRECEDENCE",status,"CORRELATION_CANNOT_INCREASE_EXPOSURE","Prompt 23 approval is bounded by Prompt 22",(portfolio_decision.decision_id,)),DecisionEvaluation("DEPENDENCY_WHAT_IF",status,reasons[-1],"Candidate evaluated without mutating portfolio state",(snapshot.snapshot_id,impact_id)))
        trace=DecisionTrace(did,request.strategy_decision_snapshot_id,as_of,checks,DecisionOutcome.ACCEPTED if status is DecisionStatus.PASSED else DecisionOutcome.NO_ACTION,reasons[-1],as_of,"CORRELATION_DEPENDENCY" if status is DecisionStatus.FAILED else None)
        decision=CorrelationRiskDecision(did,request.request_id,portfolio_decision.decision_id,snapshot.snapshot_id,request.proposed_exposure,portfolio_decision.approved_exposure,approved,outcome,impact,reduction,tuple(sorted(set(restrictions))),tuple(reasons),as_of,cfg.configuration_snapshot_id,CORRELATION_ENGINE_VERSION,request.recovery_epoch,trace)
        self.decisions[did]=decision; self._bound(); self._record("correlation_risk_decision_created",{"decision_id":did,"outcome":outcome.name}); return decision

    def recovery_state(self):
        return {"schema_version":RECOVERY_SCHEMA_VERSION,"engine_version":CORRELATION_ENGINE_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"cluster_states":tuple(self.cluster_states.values()),"cluster_versions":tuple(self.cluster_versions.values()),"last_snapshot_id":next(reversed(self.snapshots),None),"last_matrix_id":next(reversed(self.matrices),None)}
    def validate_recovery(self,state):
        if state.get("schema_version")!=RECOVERY_SCHEMA_VERSION or state.get("engine_version")!=CORRELATION_ENGINE_VERSION or state.get("configuration_snapshot_id")!=self.configuration.configuration_snapshot_id:return False
        states=tuple(state.get("cluster_states",()));versions=tuple(state.get("cluster_versions",()))
        if len({x.logical_id for x in states})!=len(states) or len({x.version_id for x in versions})!=len(versions):return False
        for x in states:
            if x.entry_count<0 or x.exit_count<0 or (x.cooldown_start_utc and x.cooldown_until_utc and x.cooldown_until_utc<x.cooldown_start_utc):return False
        return True
    def restore(self,state):
        if not self.validate_recovery(state):self.recovery_restricted=True;return False
        states=tuple(state.get("cluster_states",()));versions=tuple(state.get("cluster_versions",()));self.cluster_states=OrderedDict((x.logical_id,x) for x in states);self.cluster_versions=OrderedDict((x.version_id,x) for x in versions);self.recovery_restricted=False;return True
    def prompt24_handoff(self,decision):
        snapshot=self.snapshots.get(decision.correlation_snapshot_id)
        return {"correlation_risk_snapshot_id":decision.correlation_snapshot_id,"correlation_risk_decision_id":decision.decision_id,"correlation_matrix_snapshot_id":snapshot.correlation_matrix_id if snapshot else None,"multi_window_correlation_snapshot_id":snapshot.multi_window_snapshot_id if snapshot else None,"factor_exposure_matrix_snapshot_id":snapshot.factor_matrix_id if snapshot else None,"published_cluster_version_ids":tuple(x.version_id for x in snapshot.published_clusters) if snapshot else (),"approved_fictional_exposure":decision.approved_exposure,"restrictions":decision.restrictions,"health":snapshot.health.name if snapshot else "UNKNOWN","as_of_timestamp_utc":decision.as_of_timestamp_utc,"configuration_snapshot_id":decision.configuration_snapshot_id,"engine_version":CORRELATION_ENGINE_VERSION,"recovery_epoch":decision.recovery_epoch}

    def _update_cluster_lifecycle(self,raw_clusters,retained_clusters,health,observation_id,correlation_snapshot_id,portfolio_snapshot_id,as_of,recovery_epoch):
        cfg=self.configuration;raw={tuple(x.instrument_ids):x for x in raw_clusters};retained={tuple(x.instrument_ids):x for x in retained_clusters};all_keys=set(raw)|set(retained)|{tuple(x.member_ids) for x in self.cluster_states.values()};published=[]
        for members in sorted(all_keys):
            logical=deterministic_id("published_cluster",*members,cfg.configuration_snapshot_id);previous=self.cluster_states.get(logical);present=members in raw;held=members in retained;prev_state=previous.state if previous else ClusterLifecycleState.ABSENT;entry=previous.entry_count if previous else 0;exit_count=previous.exit_count if previous else 0;cool_start=previous.cooldown_start_utc if previous else None;cool_until=previous.cooldown_until_utc if previous else None;reason="CLUSTER_UNCHANGED";state=prev_state
            if previous and previous.last_counted_observation_id==observation_id:published.append(previous);continue
            unhealthy=health not in (CorrelationHealth.HEALTHY,CorrelationHealth.DEGRADED)
            if unhealthy and prev_state in (ClusterLifecycleState.ACTIVE,ClusterLifecycleState.EXIT_PENDING,ClusterLifecycleState.STALE_RESTRICTED):state=ClusterLifecycleState.STALE_RESTRICTED;reason="CLUSTER_DATA_STALE_RESTRICTED"
            elif present:
                exit_count=0;entry=entry+1
                if prev_state in (ClusterLifecycleState.ACTIVE,ClusterLifecycleState.STALE_RESTRICTED):state=ClusterLifecycleState.ACTIVE;reason="CLUSTER_ACTIVE_CONFIRMED"
                elif entry>=cfg.entry_confirmation_count:state=ClusterLifecycleState.ACTIVE;reason="CLUSTER_ENTRY_CONFIRMED"
                else:state=ClusterLifecycleState.ENTRY_PENDING;reason="CLUSTER_ENTRY_PENDING"
            elif held and prev_state in (ClusterLifecycleState.ACTIVE,ClusterLifecycleState.STALE_RESTRICTED,ClusterLifecycleState.EXIT_PENDING):state=ClusterLifecycleState.ACTIVE;exit_count=0;reason="CLUSTER_HYSTERESIS_RETAINED"
            elif prev_state in (ClusterLifecycleState.ACTIVE,ClusterLifecycleState.STALE_RESTRICTED,ClusterLifecycleState.EXIT_PENDING):
                exit_count+=1;entry=0
                if exit_count>=cfg.exit_confirmation_count:
                    state=ClusterLifecycleState.COOLDOWN;cool_start=as_of;cool_until=as_of+timedelta(seconds=cfg.cluster_release_cooldown_seconds);reason="CLUSTER_EXIT_CONFIRMED"
                else:state=ClusterLifecycleState.EXIT_PENDING;reason="CLUSTER_EXIT_PENDING"
            elif prev_state is ClusterLifecycleState.COOLDOWN:
                if cool_until and as_of>=cool_until:state=ClusterLifecycleState.ABSENT;reason="CLUSTER_COOLDOWN_COMPLETED"
                else:state=ClusterLifecycleState.COOLDOWN;reason="CLUSTER_COOLDOWN_ACTIVE"
            else:state=ClusterLifecycleState.ABSENT;reason="CLUSTER_ABSENT"
            parents=tuple(sorted(x.version_id for x in self.cluster_states.values() if set(x.member_ids)&set(members)))
            version=deterministic_id("published_cluster_version",logical,previous.version_id if previous else "NONE",state.name,entry,exit_count,observation_id,as_of.isoformat(),recovery_epoch)
            current=PublishedClusterState(logical,version,members,state,prev_state,entry,exit_count,observation_id,cool_start,cool_until,parents,correlation_snapshot_id,portfolio_snapshot_id,as_of,reason,recovery_epoch);self.cluster_states[logical]=current;self.cluster_versions[version]=current;published.append(current)
            if state is not prev_state:self._record("correlation_cluster_transition",{"logical_id":logical,"previous":prev_state.name,"current":state.name,"reason":reason})
        return tuple(sorted((x for x in published if x.state is not ClusterLifecycleState.ABSENT),key=lambda x:x.logical_id))

    def _candidate_multi_dependency(self,a,b,direction_a,direction_b,as_of):
        cfg=self.configuration;items=[];required_missing=False
        for window in (x for x in cfg.windows if x.enabled):
            pair=self.pair(a,b,direction_a,direction_b,as_of,window)
            if pair.health is CorrelationHealth.HEALTHY and pair.adjusted_dependency is not None:items.append((window,pair.adjusted_dependency))
            elif window.required:required_missing=True
        if len(items)<cfg.minimum_valid_windows or (required_missing and cfg.missing_window_policy is MissingWindowPolicy.BLOCK):return None,CorrelationHealth.PARTIAL
        if cfg.window_aggregation_policy is WindowAggregationPolicy.MOST_RESTRICTIVE:return max(v for _,v in items),CorrelationHealth.HEALTHY if not required_missing else CorrelationHealth.DEGRADED
        weight=sum((w.weight for w,_ in items),ZERO)
        return ((sum((w.weight*v for w,v in items),ZERO)/weight) if weight>0 else None,CorrelationHealth.HEALTHY if not required_missing else CorrelationHealth.DEGRADED)

    def _clusters(self,pairs,active,threshold=None):
        threshold=self.configuration.cluster_entry_threshold if threshold is None else threshold
        parent={x:x for x in active}
        def find(x):
            while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
            return x
        def union(a,b):
            ra,rb=find(a),find(b)
            if ra!=rb: parent[max(ra,rb)]=min(ra,rb)
        eligible=[]
        for p in pairs:
            if p.health is CorrelationHealth.HEALTHY and (p.adjusted_dependency or ZERO)>=threshold: union(p.instrument_a,p.instrument_b); eligible.append(p)
        groups=defaultdict(list)
        for x in sorted(active):groups[find(x)].append(x)
        out=[]
        for members in groups.values():
            if len(members)<2:continue
            ids=tuple(members); selected=tuple(sorted(p.pair_id for p in eligible if p.instrument_a in ids and p.instrument_b in ids)); gross=sum((active[x].remaining_exposure for x in ids),ZERO); high=max((p.adjusted_dependency for p in eligible if p.pair_id in selected),default=ZERO); cid=deterministic_id("correlation_cluster",*ids,*selected,self.configuration.configuration_snapshot_id)
            out.append(CorrelationCluster(cid,ids,selected,gross,high,CorrelationHealth.HEALTHY))
        return tuple(sorted(out,key=lambda x:x.cluster_id))
    def _state(self,value):
        if value>=self.configuration.strong_threshold:return CorrelationState.STRONG_POSITIVE
        if value>=self.configuration.moderate_threshold:return CorrelationState.MODERATE_POSITIVE
        if value<=-self.configuration.strong_threshold:return CorrelationState.STRONG_NEGATIVE
        if value<=-self.configuration.moderate_threshold:return CorrelationState.MODERATE_NEGATIVE
        return CorrelationState.WEAK
    def _strength(self,value):
        if value>=self.configuration.critical_threshold:return DependencyStrength.CRITICAL
        if value>=self.configuration.strong_threshold:return DependencyStrength.HIGH
        if value>=self.configuration.moderate_threshold:return DependencyStrength.MEDIUM
        return DependencyStrength.LOW
    def _aggregate_health(self,healths):
        values=tuple(healths)
        if not values:return CorrelationHealth.UNKNOWN
        for state in (CorrelationHealth.INVALID,CorrelationHealth.STALE,CorrelationHealth.INSUFFICIENT_HISTORY,CorrelationHealth.ZERO_VARIANCE):
            if all(x is state for x in values):return state
        if any(x is CorrelationHealth.INVALID for x in values):return CorrelationHealth.INVALID
        if all(x is CorrelationHealth.HEALTHY for x in values):return CorrelationHealth.HEALTHY
        if any(x in (CorrelationHealth.STALE,CorrelationHealth.INSUFFICIENT_HISTORY,CorrelationHealth.ZERO_VARIANCE,CorrelationHealth.PARTIAL,CorrelationHealth.UNKNOWN) for x in values):return CorrelationHealth.PARTIAL
        return CorrelationHealth.DEGRADED
    def _bad_pair(self,a,b,health,reason,count=0,start=None,end=None):
        aid=a.instrument_id if a else "MISSING_A"; bid=b.instrument_id if b else "MISSING_B"; pid=deterministic_id("correlation_pair_unavailable",*sorted((aid,bid)),health.name,reason,count)
        return PairwiseCorrelationRecord(pid,aid,bid,None,None,count,CorrelationState.UNKNOWN,DependencyStrength.UNKNOWN,health,start,end,(reason,))
    def _missing_pair(self,a,b):
        return self._bad_pair(type("S",(),{"instrument_id":a})(),type("S",(),{"instrument_id":b})(),CorrelationHealth.INSUFFICIENT_HISTORY,"CORRELATION_SERIES_UNAVAILABLE")
    def _floor(self,value):
        with localcontext() as ctx:ctx.prec=28; return (_decimal(value)/self.configuration.exposure_step).to_integral_value(rounding=ROUND_FLOOR)*self.configuration.exposure_step
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def _bound(self):
        for store,limit in ((self.snapshots,self.configuration.maximum_snapshots),(self.matrices,self.configuration.maximum_snapshots),(self.multi_window_snapshots,self.configuration.maximum_snapshots),(self.cluster_versions,self.configuration.maximum_snapshots*4),(self.cluster_states,self.configuration.maximum_snapshots),(self.decisions,self.configuration.maximum_decisions),(self._cache,self.configuration.maximum_cache_entries)):
            while len(store)>limit:store.popitem(last=False)
