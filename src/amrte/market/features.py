from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from statistics import fmean
from types import MappingProxyType
from typing import Iterable, Mapping

from amrte.core.identity import deterministic_id
from amrte.core.interfaces import IAuditSink, IClock
from .models import BarState, DataHealth, MarketDataSnapshot, NormalizedBar, SynchronizationStatus

FEATURE_ENGINE_VERSION = "1.1"
EPSILON = 1e-12


class FeatureHealth(Enum):
    VALID = auto(); VALID_WITH_WARNINGS = auto(); INSUFFICIENT_HISTORY = auto()
    INVALID_INPUT = auto(); STALE = auto(); UNSYNCHRONIZED = auto()
    NUMERICAL_ERROR = auto(); CALCULATION_ERROR = auto(); UNAVAILABLE = auto(); UNKNOWN = auto()


class WarmupState(Enum): NOT_STARTED = auto(); WARMING_UP = auto(); READY = auto(); INSUFFICIENT_HISTORY = auto(); FAILED = auto()
class PriceSource(Enum): OPEN = auto(); HIGH = auto(); LOW = auto(); CLOSE = auto(); MEDIAN_PRICE = auto(); TYPICAL_PRICE = auto(); WEIGHTED_CLOSE = auto()
class ReturnType(Enum): SIMPLE_RETURN = auto(); LOG_RETURN = auto()
class CandleDirection(Enum): UP = auto(); DOWN = auto(); FLAT = auto()
class FeatureRequirement(Enum): MANDATORY = auto(); OPTIONAL = auto()


@dataclass(frozen=True)
class WarmupMetadata:
    state: WarmupState; required_observations: int; available_observations: int
    warmup_complete: bool; first_valid_timestamp: datetime | None


@dataclass(frozen=True)
class FeatureValue:
    value: float | str | None
    health: FeatureHealth
    as_of_timestamp: datetime
    source_bar_id: str | None
    warmup: WarmupMetadata
    warnings: tuple[str, ...] = ()
    units: str = ""


def canonical_parameters(parameters: Mapping[str, object]) -> str:
    return json.dumps(dict(parameters), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=lambda value: value.name if isinstance(value, Enum) else str(value))


@dataclass(frozen=True)
class FeatureKey:
    dataset_fingerprint: str; instrument_id: str; timeframe: str; feature_type: str
    canonical_parameters: str; price_source: PriceSource; bar_state: BarState
    shift: int; as_of_timestamp: datetime; engine_version: str = FEATURE_ENGINE_VERSION
    configuration_hash: str = ""

    @classmethod
    def create(cls, dataset_fingerprint: str, instrument_id: str, timeframe: str,
               feature_type: str, parameters: Mapping[str, object], price_source: PriceSource,
               bar_state: BarState, shift: int, as_of_timestamp: datetime,
               configuration_hash: str = "") -> "FeatureKey":
        return cls(dataset_fingerprint, instrument_id, timeframe, feature_type.upper(),
                   canonical_parameters(parameters), price_source, bar_state, shift,
                   as_of_timestamp, FEATURE_ENGINE_VERSION, configuration_hash)

    @property
    def identity(self) -> str:
        return deterministic_id("feature", self.dataset_fingerprint, self.instrument_id,
            self.timeframe, self.feature_type, self.canonical_parameters, self.price_source.name,
            self.bar_state.name, self.shift, self.as_of_timestamp.isoformat(),
            self.engine_version, self.configuration_hash)


class FeatureCache:
    def __init__(self, maximum_entries: int = 512):
        if maximum_entries < 1: raise ValueError("maximum_entries must be positive")
        self.maximum_entries = maximum_entries; self._items: OrderedDict[FeatureKey, FeatureValue] = OrderedDict()
    def get(self, key: FeatureKey) -> FeatureValue | None:
        value = self._items.get(key)
        if value is not None: self._items.move_to_end(key)
        return value
    def put(self, key: FeatureKey, value: FeatureValue) -> None:
        self._items[key] = value; self._items.move_to_end(key)
        while len(self._items) > self.maximum_entries: self._items.popitem(last=False)
    def clear(self) -> int:
        count = len(self._items); self._items.clear(); return count
    def __len__(self): return len(self._items)


class FeatureDependencyGraph:
    def __init__(self): self._dependencies: dict[str, set[str]] = {}
    def add(self, feature: str, dependencies: Iterable[str] = ()) -> None:
        self._dependencies[feature] = set(dependencies); self.validate()
    def validate(self) -> None:
        visiting: set[str] = set(); visited: set[str] = set()
        def walk(node: str):
            if node in visiting: raise ValueError("FEATURE_DEPENDENCY_CYCLE")
            if node in visited: return
            visiting.add(node)
            for dependency in self._dependencies.get(node, ()): walk(dependency)
            visiting.remove(node); visited.add(node)
        for node in self._dependencies: walk(node)


@dataclass(frozen=True)
class FeatureRequest:
    name: str; parameters: Mapping[str, object]; requirement: FeatureRequirement = FeatureRequirement.MANDATORY
    price_source: PriceSource = PriceSource.CLOSE; bar_state: BarState = BarState.CLOSED_BAR; shift: int = 0
    def __post_init__(self): object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class FeatureSnapshot:
    feature_snapshot_id: str; created_at: datetime; as_of_timestamp: datetime
    experiment_id: str; dataset_id: str; dataset_fingerprint: str; instrument_id: str
    source_market_data_snapshot_id: str; source_structure_snapshot_id: str | None
    features: Mapping[str, Mapping[str, FeatureValue]]; health: FeatureHealth
    warnings: tuple[str, ...]; configuration_snapshot_id: str; recovery_epoch: int
    def __post_init__(self):
        frozen = {role: MappingProxyType(dict(values)) for role, values in self.features.items()}
        object.__setattr__(self, "features", MappingProxyType(frozen))


class TemporalSeriesHealth(Enum):
    HEALTHY=auto();DEGRADED=auto();INCOMPLETE=auto();INSUFFICIENT_HISTORY=auto();INVALID_INPUT=auto();UNAVAILABLE=auto();UNKNOWN=auto()


@dataclass(frozen=True)
class TemporalFeatureObservation:
    observation_id:str;instrument_id:str;role:str;timeframe:str;bar_time_utc:datetime
    available_at_utc:datetime;as_of_timestamp_utc:datetime;feature_set_id:str
    feature_snapshot_id:str;values:Mapping[str,FeatureValue];health:TemporalSeriesHealth
    closed_bar_state:BarState;dataset_fingerprint:str;configuration_snapshot_id:str;recovery_epoch:int
    def __post_init__(self):object.__setattr__(self,"values",MappingProxyType(dict(self.values)))


@dataclass(frozen=True)
class TemporalFeatureSeries:
    series_id:str;instrument_id:str;role:str;timeframe:str;start_time_utc:datetime|None
    end_time_utc:datetime|None;as_of_timestamp_utc:datetime;observations:tuple[TemporalFeatureObservation,...]
    observation_count:int;required_lookback:int;available_lookback:int;missing_observations:int
    valid_observations:int;completeness:float;health:TemporalSeriesHealth
    dataset_fingerprint:str;configuration_snapshot_id:str;feature_engine_version:str;recovery_epoch:int


class TemporalFeatureSeriesStore:
    """Bounded as-of index over existing authoritative Prompt 7 snapshots."""
    def __init__(self,maximum_observations:int=512,maximum_cache_entries:int=256,audit=None):
        if min(maximum_observations,maximum_cache_entries)<1:raise ValueError("INVALID_TEMPORAL_SERIES_BOUND")
        self.maximum_observations=maximum_observations;self.maximum_cache_entries=maximum_cache_entries;self.audit=audit
        self._observations={};self._cache=OrderedDict();self.cache_hits=0;self.cache_misses=0
    def admit(self,snapshot:FeatureSnapshot,role:str,timeframe:str,*,closed_bar_state:BarState=BarState.CLOSED_BAR):
        if role not in snapshot.features:raise ValueError("UNKNOWN_FEATURE_ROLE")
        values=snapshot.features[role]
        valid=sum(value.health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS) and value.as_of_timestamp<=snapshot.as_of_timestamp for value in values.values())
        health=TemporalSeriesHealth.HEALTHY if values and valid==len(values) else TemporalSeriesHealth.DEGRADED if valid else TemporalSeriesHealth.UNAVAILABLE
        feature_set_id=deterministic_id("temporal_feature_set",snapshot.dataset_fingerprint,snapshot.instrument_id,role,*sorted(values))
        identity=deterministic_id("temporal_feature_observation",snapshot.feature_snapshot_id,role,timeframe,snapshot.as_of_timestamp.isoformat(),closed_bar_state.name,feature_set_id)
        result=TemporalFeatureObservation(identity,snapshot.instrument_id,role,timeframe,snapshot.as_of_timestamp,snapshot.as_of_timestamp,snapshot.as_of_timestamp,feature_set_id,snapshot.feature_snapshot_id,values,health,closed_bar_state,snapshot.dataset_fingerprint,snapshot.configuration_snapshot_id,snapshot.recovery_epoch)
        key=(snapshot.dataset_fingerprint,snapshot.instrument_id,role,timeframe,snapshot.configuration_snapshot_id);items=self._observations.setdefault(key,[])
        if not any(item.observation_id==identity for item in items):items.append(result);items.sort(key=lambda item:(item.available_at_utc,item.observation_id));del items[:-self.maximum_observations]
        self._cache.clear()
        if self.audit:self.audit.record("temporal_feature_observation_admitted",{"observation_id":identity,"role":role})
        return result
    def query(self,*,dataset_fingerprint:str,instrument_id:str,role:str,timeframe:str,as_of:datetime,lookback:int,required_features:tuple[str,...],configuration_snapshot_id:str,closed_bar_only:bool=True):
        if lookback<1 or lookback>self.maximum_observations:raise ValueError("INVALID_TEMPORAL_LOOKBACK")
        cache_key=(dataset_fingerprint,instrument_id,role,timeframe,as_of.isoformat(),lookback,required_features,configuration_snapshot_id,closed_bar_only,FEATURE_ENGINE_VERSION)
        if cache_key in self._cache:self.cache_hits+=1;self._cache.move_to_end(cache_key);return self._cache[cache_key]
        self.cache_misses+=1;key=(dataset_fingerprint,instrument_id,role,timeframe,configuration_snapshot_id)
        available=[item for item in self._observations.get(key,()) if item.available_at_utc<=as_of and item.as_of_timestamp_utc<=as_of][-lookback:]
        accepted=[]
        for item in available:
            names={name.split(":",1)[0] for name in item.values}
            if all(name in names for name in required_features) and (not closed_bar_only or item.closed_bar_state is BarState.CLOSED_BAR):accepted.append(item)
        valid=len(accepted);missing=max(0,lookback-valid);completeness=valid/lookback
        if not available:health=TemporalSeriesHealth.UNAVAILABLE
        elif valid<lookback:health=TemporalSeriesHealth.INSUFFICIENT_HISTORY if valid==len(available) else TemporalSeriesHealth.INCOMPLETE
        elif any(item.health is not TemporalSeriesHealth.HEALTHY for item in accepted):health=TemporalSeriesHealth.DEGRADED
        else:health=TemporalSeriesHealth.HEALTHY
        identity=deterministic_id("temporal_feature_series",dataset_fingerprint,instrument_id,role,timeframe,as_of.isoformat(),lookback,configuration_snapshot_id,FEATURE_ENGINE_VERSION,*(item.observation_id for item in accepted))
        result=TemporalFeatureSeries(identity,instrument_id,role,timeframe,accepted[0].bar_time_utc if accepted else None,accepted[-1].bar_time_utc if accepted else None,as_of,tuple(accepted),valid,lookback,len(available),missing,valid,completeness,health,dataset_fingerprint,configuration_snapshot_id,FEATURE_ENGINE_VERSION,accepted[-1].recovery_epoch if accepted else 0)
        self._cache[cache_key]=result;self._cache.move_to_end(cache_key)
        while len(self._cache)>self.maximum_cache_entries:self._cache.popitem(last=False)
        if self.audit:self.audit.record("temporal_feature_series_created" if health is TemporalSeriesHealth.HEALTHY else "temporal_feature_series_incomplete",{"series_id":identity,"health":health.name})
        return result
    def rebuild(self,snapshots,role,timeframe,**query):
        self._observations.clear();self._cache.clear()
        for snapshot in snapshots:self.admit(snapshot,role,timeframe)
        return self.query(role=role,timeframe=timeframe,**query)
    @property
    def observation_count(self):return sum(len(values) for values in self._observations.values())
    @property
    def cache_size(self):return len(self._cache)
    def recovery_state(self):return {"feature_engine_version":FEATURE_ENGINE_VERSION,"maximum_observations":self.maximum_observations,"series_keys":tuple(sorted(self._observations))}
    def validate_recovery(self,state):return state.get("feature_engine_version")==FEATURE_ENGINE_VERSION and state.get("maximum_observations")==self.maximum_observations


def price(bar: NormalizedBar, source: PriceSource) -> float:
    if source is PriceSource.OPEN: return bar.open
    if source is PriceSource.HIGH: return bar.high
    if source is PriceSource.LOW: return bar.low
    if source is PriceSource.CLOSE: return bar.close
    if source is PriceSource.MEDIAN_PRICE: return (bar.high+bar.low)/2
    if source is PriceSource.TYPICAL_PRICE: return (bar.high+bar.low+bar.close)/3
    return (bar.high+bar.low+2*bar.close)/4


def _finite(value: float) -> float | None: return value if math.isfinite(value) else None


def ema_series(values: Iterable[float], period: int) -> tuple[float | None, ...]:
    data = tuple(values)
    if period <= 0: raise ValueError("period must be positive")
    output: list[float | None] = [None]*len(data)
    if len(data) < period: return tuple(output)
    seed = fmean(data[:period]); output[period-1] = seed; alpha = 2/(period+1); current = seed
    for index in range(period, len(data)):
        current = data[index]*alpha + current*(1-alpha); output[index] = current
    return tuple(output)


def true_range_series(bars: tuple[NormalizedBar, ...]) -> tuple[float, ...]:
    result=[]
    for index, bar in enumerate(bars):
        result.append(bar.high-bar.low if index == 0 else max(bar.high-bar.low,
            abs(bar.high-bars[index-1].close), abs(bar.low-bars[index-1].close)))
    return tuple(result)


def wilder_series(values: Iterable[float], period: int) -> tuple[float | None, ...]:
    data=tuple(values); output=[None]*len(data)
    if period <= 0: raise ValueError("period must be positive")
    if len(data)<period: return tuple(output)
    current=fmean(data[:period]); output[period-1]=current
    for i in range(period,len(data)):
        current=(current*(period-1)+data[i])/period; output[i]=current
    return tuple(output)


def atr_series(bars: tuple[NormalizedBar, ...], period: int) -> tuple[float | None, ...]:
    return wilder_series(true_range_series(bars), period)


def directional_series(bars: tuple[NormalizedBar, ...], period: int) -> tuple[tuple[float | None,...],tuple[float | None,...],tuple[float | None,...]]:
    plus=[0.0]; minus=[0.0]
    for previous,current in zip(bars,bars[1:]):
        up=current.high-previous.high; down=previous.low-current.low
        plus.append(up if up>down and up>0 else 0.0); minus.append(down if down>up and down>0 else 0.0)
    atr=atr_series(bars,period); psm=wilder_series(plus,period); msm=wilder_series(minus,period)
    pdi=[]; mdi=[]; dx=[]
    for a,p,m in zip(atr,psm,msm):
        if a is None or p is None or m is None or abs(a)<EPSILON: pdi.append(None); mdi.append(None); dx.append(None); continue
        pv=100*p/a; mv=100*m/a; pdi.append(pv); mdi.append(mv)
        dx.append(0.0 if abs(pv+mv)<EPSILON else 100*abs(pv-mv)/(pv+mv))
    valid_dx=[item for item in dx if item is not None]; adx_valid=wilder_series(valid_dx,period)
    adx=[None]*len(dx); cursor=0
    for i,item in enumerate(dx):
        if item is not None: adx[i]=adx_valid[cursor]; cursor+=1
    return tuple(pdi),tuple(mdi),tuple(adx)


def rsi_series(values: Iterable[float], period: int) -> tuple[float | None,...]:
    data=tuple(values); output=[None]*len(data)
    if period<=0: raise ValueError("period must be positive")
    if len(data)<=period: return tuple(output)
    gains=[max(data[i]-data[i-1],0.0) for i in range(1,len(data))]
    losses=[max(data[i-1]-data[i],0.0) for i in range(1,len(data))]
    avg_gain=fmean(gains[:period]); avg_loss=fmean(losses[:period])
    def score(g,l):
        if abs(g)<EPSILON and abs(l)<EPSILON: return 50.0
        if abs(l)<EPSILON: return 100.0
        if abs(g)<EPSILON: return 0.0
        return 100-100/(1+g/l)
    output[period]=score(avg_gain,avg_loss)
    for i in range(period+1,len(data)):
        avg_gain=(avg_gain*(period-1)+gains[i-1])/period
        avg_loss=(avg_loss*(period-1)+losses[i-1])/period
        output[i]=score(avg_gain,avg_loss)
    return tuple(output)


def macd_series(values: Iterable[float], fast: int, slow: int, signal: int):
    if fast<=0 or slow<=0 or signal<=0 or fast>=slow: raise ValueError("invalid MACD periods")
    values=tuple(values); ef=ema_series(values,fast); es=ema_series(values,slow)
    main=[None if a is None or b is None else a-b for a,b in zip(ef,es)]
    valid=[item for item in main if item is not None]; signal_valid=ema_series(valid,signal)
    sig=[None]*len(main); cursor=0
    for i,item in enumerate(main):
        if item is not None: sig[i]=signal_valid[cursor]; cursor+=1
    hist=[None if a is None or b is None else a-b for a,b in zip(main,sig)]
    return tuple(main),tuple(sig),tuple(hist)


def bollinger_series(values: Iterable[float], period: int, deviation: float):
    data=tuple(values)
    if period<=0 or deviation<=0: raise ValueError("invalid Bollinger parameters")
    middle=[None]*len(data); upper=[None]*len(data); lower=[None]*len(data)
    for i in range(period-1,len(data)):
        window=data[i-period+1:i+1]; mean=fmean(window)
        variance=fmean((item-mean)**2 for item in window)  # population convention
        std=math.sqrt(max(0.0,variance)); middle[i]=mean; upper[i]=mean+deviation*std; lower[i]=mean-deviation*std
    return tuple(middle),tuple(upper),tuple(lower)


def returns(values: Iterable[float], kind: ReturnType) -> tuple[float | None,...]:
    data=tuple(values); result=[None]
    for prior,current in zip(data,data[1:]):
        if prior<=0 or (kind is ReturnType.LOG_RETURN and current<=0): result.append(None); continue
        ratio=current/prior; result.append(ratio-1 if kind is ReturnType.SIMPLE_RETURN else math.log(ratio))
    return tuple(result)


def rolling_volatility(values: Iterable[float], window: int, kind: ReturnType=ReturnType.LOG_RETURN):
    changes=returns(values,kind); result=[None]*len(changes)
    for i in range(window,len(changes)):
        sample=changes[i-window+1:i+1]
        if any(item is None for item in sample): continue
        mean=fmean(sample); variance=fmean((item-mean)**2 for item in sample); result[i]=math.sqrt(max(0.0,variance))
    return tuple(result)


def percentile_rank(history: Iterable[float], current: float) -> float:
    data=tuple(history)
    if not data: raise ValueError("percentile history is empty")
    below=sum(item<current for item in data); equal=sum(abs(item-current)<=EPSILON for item in data)
    return 100*(below+0.5*equal)/len(data)


class FeatureEngine:
    def __init__(self, clock: IClock, audit: IAuditSink, *, maximum_cache_entries: int=512):
        self.clock=clock; self.audit=audit; self.cache=FeatureCache(maximum_cache_entries)
        self.graph=FeatureDependencyGraph()
        self.graph.add("ATR",("TRUE_RANGE",)); self.graph.add("ADX",("ATR","DIRECTIONAL_MOVEMENT"))
        self.graph.add("MACD",("EMA_FAST","EMA_SLOW")); self.graph.add("RANGE_ATR",("ATR",))
        self._last_snapshot_id: str | None=None

    def _eligible(self,bars: tuple[NormalizedBar,...], state: BarState, as_of: datetime):
        return tuple(bar for bar in bars if bar.open_time<=as_of and
            (state is not BarState.CLOSED_BAR or (bar.bar_state is BarState.CLOSED_BAR and bar.close_time is not None and bar.close_time<=as_of)))

    def calculate(self,snapshot: MarketDataSnapshot,timeframe: str,bars: tuple[NormalizedBar,...],request: FeatureRequest,*,configuration_hash: str="") -> FeatureValue:
        as_of=snapshot.as_of_timestamp; eligible=self._eligible(bars,request.bar_state,as_of)
        key=FeatureKey.create(snapshot.dataset_fingerprint,snapshot.instrument_id,timeframe,request.name,
            request.parameters,request.price_source,request.bar_state,request.shift,as_of,configuration_hash)
        cached=self.cache.get(key)
        if cached is not None: return cached
        if request.shift<0: return self._value(None,FeatureHealth.INVALID_INPUT,as_of,None,1,len(eligible),("negative shift",))
        try: value=self._calculate(eligible,request,as_of)
        except (ValueError,ArithmeticError,OverflowError) as exc:
            value=self._value(None,FeatureHealth.CALCULATION_ERROR,as_of,eligible[-1].bar_id if eligible else None,1,len(eligible),(str(exc),))
        if isinstance(value.value,float) and not math.isfinite(value.value):
            value=self._value(None,FeatureHealth.NUMERICAL_ERROR,as_of,value.source_bar_id,value.warmup.required_observations,len(eligible),("non-finite result",))
        self.cache.put(key,value); return value

    def _calculate(self,bars: tuple[NormalizedBar,...],request: FeatureRequest,as_of: datetime) -> FeatureValue:
        name=request.name.upper(); p=dict(request.parameters); shift=request.shift; values=tuple(price(bar,request.price_source) for bar in bars)
        index=len(bars)-1-shift; source=bars[index].bar_id if index>=0 else None
        def select(series,required,units=""):
            if index<0 or len(bars)<required or index>=len(series) or series[index] is None:
                return self._value(None,FeatureHealth.INSUFFICIENT_HISTORY,as_of,source,required,len(bars),(),units)
            return self._value(float(series[index]),FeatureHealth.VALID,as_of,source,required,len(bars),(),units)
        if name=="EMA": return select(ema_series(values,int(p["period"])),int(p["period"]),"price")
        if name=="TRUE_RANGE": return select(true_range_series(bars),1,"price")
        if name in ("ATR","ATR_PERCENT_PRICE"):
            period=int(p["period"]); raw=atr_series(bars,period); selected=select(raw,period,"price")
            if name=="ATR" or selected.value is None:return selected
            reference=values[index]
            return self._safe_ratio(float(selected.value)*100,reference,as_of,source,period,len(bars),"percent")
        if name in ("PLUS_DI","MINUS_DI","ADX"):
            period=int(p["period"]); plus,minus,adx=directional_series(bars,period)
            return select({"PLUS_DI":plus,"MINUS_DI":minus,"ADX":adx}[name],period*2-1,"0-100")
        if name=="RSI":
            period=int(p["period"]); return select(rsi_series(values,period),period+1,"0-100")
        if name.startswith("MACD_"):
            fast,slow,signal=int(p["fast"]),int(p["slow"]),int(p["signal"])
            main,sig,hist=macd_series(values,fast,slow,signal)
            if name=="MACD_HISTOGRAM_SLOPE":
                selected=select(hist,slow+signal,"price/bar")
                if selected.value is None or index<1 or hist[index-1] is None:return selected
                return self._value(float(hist[index])-float(hist[index-1]),FeatureHealth.VALID,as_of,source,slow+signal,len(bars),(),"price/bar")
            return select({"MACD_MAIN":main,"MACD_SIGNAL":sig,"MACD_HISTOGRAM":hist}[name],slow+signal-1,"price")
        if name.startswith("BOLLINGER_"):
            period=int(p["period"]); middle,upper,lower=bollinger_series(values,period,float(p["deviation"])); required=period
            if name=="BOLLINGER_MIDDLE":return select(middle,required,"price")
            if name=="BOLLINGER_UPPER":return select(upper,required,"price")
            if name=="BOLLINGER_LOWER":return select(lower,required,"price")
            if index<0 or len(bars)<required or middle[index] is None:return select(middle,required)
            width=float(upper[index])-float(lower[index])
            if name=="BOLLINGER_BANDWIDTH":return self._safe_ratio(width,abs(float(middle[index])),as_of,source,required,len(bars),"ratio")
            if name=="BOLLINGER_PERCENT_B":return self._safe_ratio(values[index]-float(lower[index]),width,as_of,source,required,len(bars),"ratio")
            return self._safe_ratio(values[index]-float(middle[index]),width/2,as_of,source,required,len(bars),"band-standard-width")
        if name.startswith("CANDLE_"):
            if index<0:return select((),1)
            bar=bars[index]; candle_range=bar.high-bar.low; body=abs(bar.close-bar.open)
            mapping={"CANDLE_RANGE":candle_range,"CANDLE_BODY":body,
                     "CANDLE_UPPER_WICK":bar.high-max(bar.open,bar.close),
                     "CANDLE_LOWER_WICK":min(bar.open,bar.close)-bar.low}
            if name in mapping:return self._value(mapping[name],FeatureHealth.VALID,as_of,source,1,len(bars),(),"price")
            if name=="CANDLE_DIRECTION":return self._value((CandleDirection.UP if bar.close>bar.open else CandleDirection.DOWN if bar.close<bar.open else CandleDirection.FLAT).name,FeatureHealth.VALID,as_of,source,1,len(bars))
            numerator={"CANDLE_BODY_RATIO":body,"CANDLE_UPPER_WICK_RATIO":mapping["CANDLE_UPPER_WICK"],"CANDLE_LOWER_WICK_RATIO":mapping["CANDLE_LOWER_WICK"]}[name]
            return self._safe_ratio(numerator,candle_range,as_of,source,1,len(bars),"ratio")
        if name in ("SIMPLE_RETURN","LOG_RETURN"):
            kind=ReturnType[name]; return select(returns(values,kind),2,"ratio")
        if name=="ROC":
            period=int(p["period"])
            if index-period<0:return select((),period+1)
            return self._safe_ratio((values[index]-values[index-period])*100,values[index-period],as_of,source,period+1,len(bars),"percent")
        if name in ("RAW_DISPLACEMENT","PERCENTAGE_DISPLACEMENT","ATR_ADJUSTED_DISPLACEMENT"):
            period=int(p["period"])
            if index-period<0:return select((),period+1)
            raw=values[index]-values[index-period]
            if name=="RAW_DISPLACEMENT":return self._value(raw,FeatureHealth.VALID,as_of,source,period+1,len(bars),(),"price")
            if name=="PERCENTAGE_DISPLACEMENT":return self._safe_ratio(raw*100,values[index-period],as_of,source,period+1,len(bars),"percent")
            atr=atr_series(bars,int(p["atr_period"]))[index]
            return self._safe_ratio(raw,atr or 0,as_of,source,max(period+1,int(p["atr_period"])),len(bars),"ATR-multiple")
        if name in ("EMA_SEPARATION","EMA_SLOPE","PRICE_DISTANCE_EMA"):
            period=int(p["period"]); ema=ema_series(values,period)
            if name=="PRICE_DISTANCE_EMA":
                if index<0 or ema[index] is None:return select(ema,period)
                return self._value(values[index]-float(ema[index]),FeatureHealth.VALID,as_of,source,period,len(bars),(),"price")
            if name=="EMA_SLOPE":
                lookback=int(p["lookback"])
                if index-lookback<0 or ema[index] is None or ema[index-lookback] is None:return select((),period+lookback)
                return self._value((float(ema[index])-float(ema[index-lookback]))/lookback,FeatureHealth.VALID,as_of,source,period+lookback,len(bars),(),"price/bar")
            second=int(p["second_period"]); other=ema_series(values,second)
            if index<0 or ema[index] is None or other[index] is None:return select((),max(period,second))
            return self._value(float(ema[index])-float(other[index]),FeatureHealth.VALID,as_of,source,max(period,second),len(bars),(),"price")
        if name in ("REALIZED_VOLATILITY","VOLATILITY_PERCENTILE","VOLATILITY_EXPANSION_RATIO"):
            window=int(p["window"]); kind=ReturnType[str(p.get("return_type","LOG_RETURN"))]
            vol=rolling_volatility(values,window,kind)
            if name=="REALIZED_VOLATILITY":return select(vol,window+1,"return-standard-deviation")
            history_window=int(p.get("percentile_window",window)); current=vol[index] if index>=0 else None
            history=[item for item in vol[max(0,index-history_window+1):index+1] if item is not None]
            if current is None or len(history)<2:return select((),window+2)
            if name=="VOLATILITY_PERCENTILE":return self._value(percentile_rank(history,float(current)),FeatureHealth.VALID,as_of,source,window+2,len(bars),(),"percentile")
            baseline=fmean(history[:-1]) if len(history)>1 else 0
            return self._safe_ratio(float(current),baseline,as_of,source,window+2,len(bars),"ratio")
        if name in ("RANGE_WIDTH","RANGE_PERCENT_PRICE","RANGE_ATR"):
            window=int(p["window"])
            if index-window+1<0:return select((),window)
            selected=bars[index-window+1:index+1]; raw=max(item.high for item in selected)-min(item.low for item in selected)
            if name=="RANGE_WIDTH":return self._value(raw,FeatureHealth.VALID,as_of,source,window,len(bars),(),"price")
            if name=="RANGE_PERCENT_PRICE":return self._safe_ratio(raw*100,values[index],as_of,source,window,len(bars),"percent")
            atr=atr_series(bars,int(p["atr_period"]))[index]
            return self._safe_ratio(raw,atr or 0,as_of,source,max(window,int(p["atr_period"])),len(bars),"ATR-multiple")
        return self._value(None,FeatureHealth.UNAVAILABLE,as_of,source,1,len(bars),("unknown feature",))

    def snapshot(self,source: MarketDataSnapshot,requests: Iterable[FeatureRequest],*,configuration_hash: str="",structure_snapshot_id: str|None=None) -> FeatureSnapshot | None:
        self.audit.record("feature_calculation_started",{"source_snapshot_id":source.snapshot_id})
        if source.data_health is not DataHealth.HEALTHY or source.synchronization_status is not SynchronizationStatus.SYNCHRONIZED:
            self.audit.record("feature_snapshot_rejected",{"reason":"FEATURE_INVALID_INPUT"}); return None
        roles={"context":source.context_bars,"strategy":source.strategy_bars,"execution":source.execution_bars}
        requested=tuple(requests); output={}; warnings=[]; mandatory_failures=[]
        for role,bars in roles.items():
            timeframe=bars[0].timeframe if bars else "UNKNOWN"; values={}
            for request in requested:
                label=f"{request.name.upper()}:{canonical_parameters(request.parameters)}:{request.shift}"
                result=self.calculate(source,timeframe,bars,request,configuration_hash=configuration_hash); values[label]=result
                if result.health is not FeatureHealth.VALID:
                    warnings.append(f"{role}:{request.name}:{result.health.name}")
                    if request.requirement is FeatureRequirement.MANDATORY: mandatory_failures.append(result.health)
            output[role]=values
        priority=(FeatureHealth.INVALID_INPUT,FeatureHealth.NUMERICAL_ERROR,FeatureHealth.CALCULATION_ERROR,
                  FeatureHealth.UNAVAILABLE,FeatureHealth.UNSYNCHRONIZED,FeatureHealth.STALE,
                  FeatureHealth.INSUFFICIENT_HISTORY,FeatureHealth.UNKNOWN)
        health=next((item for item in priority if item in mandatory_failures),
                    FeatureHealth.VALID_WITH_WARNINGS if warnings else FeatureHealth.VALID)
        identity=deterministic_id("feature_snapshot",source.snapshot_id,structure_snapshot_id or "",configuration_hash,
                                  FEATURE_ENGINE_VERSION,*[f"{r.name}:{canonical_parameters(r.parameters)}:{r.price_source.name}:{r.bar_state.name}:{r.shift}:{r.requirement.name}" for r in requested])
        result=FeatureSnapshot(identity,self.clock.now(),source.as_of_timestamp,source.experiment_id,
            source.dataset_id,source.dataset_fingerprint,source.instrument_id,source.snapshot_id,
            structure_snapshot_id,output,health,tuple(warnings),source.configuration_snapshot_id,source.recovery_epoch)
        self._last_snapshot_id=result.feature_snapshot_id
        self.audit.record("feature_snapshot_created",{"feature_snapshot_id":identity,"health":health.name})
        return result

    def rebuild(self,*args,**kwargs):
        self.audit.record("feature_rebuild_started",{}); self.cache.clear(); result=self.snapshot(*args,**kwargs)
        self.audit.record("feature_rebuild_completed",{"success":result is not None}); return result
    def readiness(self,snapshot: FeatureSnapshot|None):
        return (snapshot is not None and snapshot.health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS),
                () if snapshot is not None and snapshot.health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS) else ("features:NOT_READY",))
    def recovery_state(self): return {"feature_engine_version":FEATURE_ENGINE_VERSION,"last_feature_snapshot_id":self._last_snapshot_id,"cache_entries":len(self.cache)}

    def _value(self,value,health,as_of,source,required,available,warnings=(),units=""):
        state=WarmupState.READY if health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS) else WarmupState.INSUFFICIENT_HISTORY if health is FeatureHealth.INSUFFICIENT_HISTORY else WarmupState.FAILED
        return FeatureValue(value,health,as_of,source,WarmupMetadata(state,required,available,state is WarmupState.READY,as_of if state is WarmupState.READY else None),tuple(warnings),units)
    def _safe_ratio(self,numerator,denominator,as_of,source,required,available,units):
        if denominator is None or not math.isfinite(float(denominator)) or abs(float(denominator))<EPSILON:
            return self._value(None,FeatureHealth.NUMERICAL_ERROR,as_of,source,required,available,("zero or invalid denominator",),units)
        value=float(numerator)/float(denominator)
        return self._value(value,FeatureHealth.VALID if math.isfinite(value) else FeatureHealth.NUMERICAL_ERROR,as_of,source,required,available,(),units)
