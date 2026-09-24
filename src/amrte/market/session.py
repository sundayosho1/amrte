from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from enum import Enum, auto
from types import MappingProxyType
from typing import Mapping, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from amrte.core.identity import deterministic_id
from amrte.core.interfaces import IAuditSink, IClock
from amrte.core.observability import DecisionTraceBuilder
from amrte.core.observability_types import DecisionOutcome, DecisionStatus, DecisionTrace
from .models import DataHealth, MarketDataSnapshot, SpreadHealth, SynchronizationStatus

SESSION_ENGINE_VERSION = "1.0"


class TimeHealth(Enum):
    HEALTHY=auto(); DEGRADED=auto(); AMBIGUOUS=auto(); NONEXISTENT_LOCAL_TIME=auto()
    INCONSISTENT=auto(); UNAVAILABLE=auto(); INVALID=auto(); UNKNOWN=auto()


class SessionType(Enum):
    ASIAN=auto(); LONDON=auto(); NEW_YORK=auto(); LONDON_NEW_YORK_OVERLAP=auto()
    CUSTOM=auto(); OUT_OF_SESSION=auto(); MULTIPLE_ACTIVE=auto()


class SessionHealth(Enum):
    HEALTHY=auto(); DEGRADED=auto(); RESTRICTED=auto(); TIME_AMBIGUOUS=auto()
    CALENDAR_UNAVAILABLE=auto(); INVALID_CONFIGURATION=auto(); UNAVAILABLE=auto(); UNKNOWN=auto()


class ExpectedAvailability(Enum): EXPECTED_OPEN=auto(); EXPECTED_CLOSED=auto(); RESTRICTED_WINDOW=auto(); UNKNOWN=auto()
class CalendarDayState(Enum): OPEN=auto(); CLOSED=auto(); SHORTENED=auto(); DELAYED_OPEN=auto(); UNKNOWN=auto()
class FridayRestrictionState(Enum): NORMAL=auto(); NEW_ACTIVITY_RESTRICTED=auto(); MANAGEMENT_ONLY_REFERENCE=auto(); NO_NEW_RISK_REFERENCE=auto(); EXPECTED_CLOSURE_APPROACHING=auto()
class MondayReopeningState(Enum): NOT_APPLICABLE=auto(); WAITING_FOR_OPEN=auto(); INITIAL_REOPEN_WINDOW=auto(); DATA_REVALIDATION=auto(); NORMALIZATION_PENDING=auto(); READY=auto(); UNKNOWN=auto()
class RolloverState(Enum): NORMAL=auto(); APPROACHING=auto(); ACTIVE=auto(); RECOVERY=auto(); UNKNOWN=auto()
class TemporalRestriction(Enum): ALLOW_CONTEXT=auto(); RESTRICT_CONTEXT=auto(); BLOCK_SESSION_DEPENDENT_ACTIVITY=auto(); UNKNOWN=auto()
class SessionEligibility(Enum): ELIGIBLE=auto(); CONDITIONAL=auto(); RESTRICTED=auto(); BLOCKED=auto(); UNKNOWN=auto()


@dataclass(frozen=True)
class TimeContext:
    utc_instant: datetime
    data_source_time: datetime
    data_source_timezone: str
    reference_time: datetime
    reference_timezone: str
    research_clock_time: datetime
    offset_from_utc_minutes: int
    dst_active: bool
    fold: int
    health: TimeHealth
    configuration_snapshot_id: str


@dataclass(frozen=True)
class LocalTimeResolution:
    instant_utc: datetime | None
    health: TimeHealth
    candidates_utc: tuple[datetime, ...] = ()


@dataclass(frozen=True)
class SessionDefinition:
    session_id: str
    session_type: SessionType
    name: str
    timezone_name: str
    local_open: time
    local_close: time
    active_weekdays: frozenset[int]
    priority: int = 0
    enabled: bool = True
    tags: tuple[str, ...] = ()

    def validate(self) -> tuple[str, ...]:
        errors=[]
        if not self.session_id.strip(): errors.append("SESSION_ID_REQUIRED")
        if not self.active_weekdays or any(day not in range(7) for day in self.active_weekdays): errors.append("INVALID_WEEKDAY")
        try: ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError): errors.append("TIMEZONE_INVALID")
        if self.local_open==self.local_close: errors.append("ZERO_LENGTH_SESSION")
        return tuple(errors)


@dataclass(frozen=True)
class CalendarProvenance:
    calendar_id: str; version: str; source: str
    effective_start: date | None = None; effective_end: date | None = None
    last_updated: datetime | None = None


@dataclass(frozen=True)
class CalendarDecision:
    state: CalendarDayState
    open_time: time | None = None
    close_time: time | None = None
    reason: str = ""
    provenance: CalendarProvenance | None = None


class IMarketCalendar(Protocol):
    def resolve(self, local_date: date, instrument_id: str) -> CalendarDecision: ...


class ConfiguredMarketCalendar:
    """Offline calendar. Unknown dates are never fabricated as holidays or opens."""
    def __init__(self, decisions: Mapping[date,CalendarDecision], provenance:CalendarProvenance):
        self._decisions=dict(decisions); self.provenance=provenance
    def resolve(self, local_date:date,instrument_id:str)->CalendarDecision:
        return self._decisions.get(local_date,CalendarDecision(CalendarDayState.UNKNOWN,reason="CALENDAR_UNKNOWN",provenance=self.provenance))


class WeekdayFallbackCalendar:
    """Explicit fallback policy; weekdays are assumed open and weekends closed."""
    def __init__(self,provenance:CalendarProvenance|None=None): self.provenance=provenance
    def resolve(self,local_date:date,instrument_id:str)->CalendarDecision:
        state=CalendarDayState.CLOSED if local_date.weekday()>=5 else CalendarDayState.OPEN
        return CalendarDecision(state,reason="EXPLICIT_WEEKDAY_FALLBACK",provenance=self.provenance)


@dataclass(frozen=True)
class ExpectedAvailabilityContext:
    state: ExpectedAvailability; expected_closure: bool; reason_codes: tuple[str,...]
    calendar_id: str | None; calendar_version: str | None


@dataclass(frozen=True)
class FridayCutoff:
    timezone_name: str="America/New_York"; cutoff:time=time(16,0); warning_minutes:int=60
    restriction:FridayRestrictionState=FridayRestrictionState.NEW_ACTIVITY_RESTRICTED


@dataclass(frozen=True)
class RolloverWindow:
    timezone_name:str="America/New_York"; start:time=time(16,55); end:time=time(17,10)
    weekdays:frozenset[int]=frozenset({0,1,2,3,4}); pre_minutes:int=15; post_minutes:int=15


@dataclass(frozen=True)
class SessionConfiguration:
    reference_timezone:str="UTC"
    data_source_timezone:str="UTC"
    sessions:tuple[SessionDefinition,...]=()
    trading_day_timezone:str="America/New_York"
    trading_day_boundary:time=time(17,0)
    trading_week_timezone:str="America/New_York"
    trading_week_start_weekday:int=6
    trading_week_start:time=time(17,0)
    weekend_days:frozenset[int]=frozenset({5,6})
    friday_cutoff:FridayCutoff=FridayCutoff()
    monday_reopen_delay_minutes:int=30
    minimum_reopen_observations:int=1
    rollover_windows:tuple[RolloverWindow,...]=(RolloverWindow(),)
    strategy_eligibility:Mapping[str,Mapping[str,SessionEligibility]]|None=None
    instrument_session_overrides:Mapping[str,tuple[SessionDefinition,...]]|None=None
    calendar_required:bool=False
    strict:bool=True
    maximum_cache_entries:int=512
    maximum_clock_jump_minutes:int=1440

    def validate(self)->tuple[str,...]:
        errors=[]
        for value in (self.reference_timezone,self.data_source_timezone,self.trading_day_timezone,self.trading_week_timezone,self.friday_cutoff.timezone_name):
            try: ZoneInfo(value)
            except (ZoneInfoNotFoundError,ValueError): errors.append(f"TIMEZONE_INVALID:{value}")
        ids=[item.session_id for item in self.sessions]
        if len(ids)!=len(set(ids)):errors.append("DUPLICATE_SESSION_ID")
        for item in self.sessions:errors.extend(item.validate())
        if self.trading_week_start_weekday not in range(7):errors.append("INVALID_TRADING_WEEKDAY")
        if min(self.monday_reopen_delay_minutes,self.minimum_reopen_observations,self.maximum_cache_entries,self.maximum_clock_jump_minutes)<0:errors.append("NEGATIVE_CONFIGURATION")
        return tuple(errors)


@dataclass(frozen=True)
class SessionSnapshot:
    session_snapshot_id:str; created_at:datetime; as_of_timestamp_utc:datetime
    experiment_id:str; dataset_id:str; dataset_fingerprint:str; instrument_id:str
    source_market_data_snapshot_id:str; time_context:TimeContext
    primary_session:SessionType; active_sessions:tuple[str,...]; is_overlap:bool
    expected_availability:ExpectedAvailabilityContext
    is_trading_day:bool; trading_day_id:str; trading_week_id:str
    is_friday:bool; friday_restriction:FridayRestrictionState; is_weekend:bool
    monday_reopening:MondayReopeningState; rollover:RolloverState
    minutes_since_session_open:int|None; minutes_to_session_close:int|None; minutes_to_next_session_open:int|None
    session_health:SessionHealth; temporal_restriction:TemporalRestriction
    strategy_family_eligibility:Mapping[str,SessionEligibility]
    reason_codes:tuple[str,...]; warnings:tuple[str,...]; calendar_provenance:CalendarProvenance|None
    decision_trace:DecisionTrace; configuration_snapshot_id:str; recovery_epoch:int
    timezone_database_version:str; session_engine_version:str=SESSION_ENGINE_VERSION

    def __post_init__(self):object.__setattr__(self,"strategy_family_eligibility",MappingProxyType(dict(self.strategy_family_eligibility)))


class TimeZoneService:
    def __init__(self,maximum_cache_entries:int=128):
        self._zones:dict[str,tzinfo]={"UTC":timezone.utc};self.maximum_cache_entries=max(1,maximum_cache_entries)
    def zone(self,name:str)->tzinfo:
        if name not in self._zones:
            if len(self._zones)>=self.maximum_cache_entries:
                oldest=next((key for key in self._zones if key!="UTC"),None)
                if oldest is not None:self._zones.pop(oldest)
            self._zones[name]=ZoneInfo(name)
        return self._zones[name]
    def from_utc(self,instant:datetime,timezone_name:str)->datetime:
        if instant.tzinfo is None:raise ValueError("TIME_INVALID_INPUT")
        return instant.astimezone(timezone.utc).astimezone(self.zone(timezone_name))
    def resolve_local(self,wall_time:datetime,timezone_name:str,*,fold:int|None=None)->LocalTimeResolution:
        if wall_time.tzinfo is not None:return LocalTimeResolution(None,TimeHealth.INVALID)
        try:zone=self.zone(timezone_name)
        except (ZoneInfoNotFoundError,ValueError):return LocalTimeResolution(None,TimeHealth.UNAVAILABLE)
        candidates=[]
        for candidate_fold in (0,1):
            aware=wall_time.replace(tzinfo=zone,fold=candidate_fold)
            utc=aware.astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None)==wall_time and utc not in candidates:candidates.append(utc)
        if not candidates:return LocalTimeResolution(None,TimeHealth.NONEXISTENT_LOCAL_TIME)
        if len(candidates)>1:
            if fold is None:return LocalTimeResolution(None,TimeHealth.AMBIGUOUS,tuple(candidates))
            if fold not in (0,1):return LocalTimeResolution(None,TimeHealth.INVALID,tuple(candidates))
            return LocalTimeResolution(candidates[fold],TimeHealth.HEALTHY,tuple(candidates))
        return LocalTimeResolution(candidates[0],TimeHealth.HEALTHY,tuple(candidates))


class SessionEngine:
    def __init__(self,clock:IClock,audit:IAuditSink,configuration:SessionConfiguration,calendar:IMarketCalendar|None=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.clock=clock; self.audit=audit; self.configuration=configuration; self.calendar=calendar
        self.timezones=TimeZoneService(configuration.maximum_cache_entries); self._last_instant:datetime|None=None; self._last_snapshot:SessionSnapshot|None=None
        self._cache:dict[tuple,tuple[tuple[SessionDefinition,datetime,datetime],...]]={}
        self.audit.record("time_engine_initialized",{"session_engine_version":SESSION_ENGINE_VERSION})

    def normalize_data_source_time(self,value:datetime,timezone_name:str|None=None,*,fold:int|None=None)->LocalTimeResolution:
        if value.tzinfo is not None:return LocalTimeResolution(value.astimezone(timezone.utc),TimeHealth.HEALTHY,(value.astimezone(timezone.utc),))
        result=self.timezones.resolve_local(value,timezone_name or self.configuration.data_source_timezone,fold=fold)
        if result.health is not TimeHealth.HEALTHY:self.audit.record("time_conversion_failed",{"health":result.health.name})
        return result

    def time_context(self,instant:datetime,configuration_snapshot_id:str)->TimeContext:
        if instant.tzinfo is None:raise ValueError("TIME_INVALID_INPUT")
        utc=instant.astimezone(timezone.utc); source=self.timezones.from_utc(utc,self.configuration.data_source_timezone)
        reference=self.timezones.from_utc(utc,self.configuration.reference_timezone)
        offset=int((reference.utcoffset() or timedelta()).total_seconds()/60)
        return TimeContext(utc,source,self.configuration.data_source_timezone,reference,self.configuration.reference_timezone,
            self.clock.now().astimezone(timezone.utc),offset,bool(reference.dst()),reference.fold,TimeHealth.HEALTHY,configuration_snapshot_id)

    def _definitions(self,instrument_id:str)->tuple[SessionDefinition,...]:
        overrides=(self.configuration.instrument_session_overrides or {}).get(instrument_id)
        return overrides if overrides is not None else self.configuration.sessions

    def _window(self,definition:SessionDefinition,utc:datetime)->tuple[datetime,datetime]|None:
        local=utc.astimezone(self.timezones.zone(definition.timezone_name)); day=local.date()
        candidate_days=(day,day-timedelta(days=1)) if definition.local_open>definition.local_close else (day,)
        for opening_day in candidate_days:
            if opening_day.weekday() not in definition.active_weekdays:continue
            open_local=datetime.combine(opening_day,definition.local_open)
            close_day=opening_day+timedelta(days=1) if definition.local_open>definition.local_close else opening_day
            close_local=datetime.combine(close_day,definition.local_close)
            opened=self.timezones.resolve_local(open_local,definition.timezone_name,fold=0)
            closed=self.timezones.resolve_local(close_local,definition.timezone_name,fold=1)
            if opened.instant_utc is not None and closed.instant_utc is not None and opened.instant_utc<=utc<closed.instant_utc:return opened.instant_utc,closed.instant_utc
        return None

    def _active(self,utc:datetime,instrument_id:str):
        active=[]
        for definition in self._definitions(instrument_id):
            if not definition.enabled:continue
            window=self._window(definition,utc)
            if window:active.append((definition,*window))
        return tuple(sorted(active,key=lambda item:(-item[0].priority,item[0].session_id)))

    def _next_open(self,utc:datetime,instrument_id:str)->int|None:
        best=None
        for minute in range(1,7*24*60+1):
            probe=utc+timedelta(minutes=minute)
            if self._active(probe,instrument_id):best=minute;break
        return best

    def trading_day_id(self,utc:datetime)->str:
        local=utc.astimezone(self.timezones.zone(self.configuration.trading_day_timezone))
        label=local.date() if local.timetz().replace(tzinfo=None)>=self.configuration.trading_day_boundary else local.date()-timedelta(days=1)
        return "TD-"+label.isoformat()

    def trading_week_id(self,utc:datetime)->str:
        local=utc.astimezone(self.timezones.zone(self.configuration.trading_week_timezone)); boundary=self.configuration.trading_week_start
        days=(local.weekday()-self.configuration.trading_week_start_weekday)%7
        start_date=local.date()-timedelta(days=days)
        if days==0 and local.timetz().replace(tzinfo=None)<boundary:start_date-=timedelta(days=7)
        return "TW-"+start_date.isoformat()

    def _rollover(self,utc:datetime)->RolloverState:
        for item in self.configuration.rollover_windows:
            local=utc.astimezone(self.timezones.zone(item.timezone_name)); now=local.timetz().replace(tzinfo=None)
            if local.weekday() not in item.weekdays:continue
            anchor=datetime.combine(local.date(),item.start); end=datetime.combine(local.date(),item.end)
            if item.start>item.end:end+=timedelta(days=1)
            naive=local.replace(tzinfo=None)
            if anchor<=naive<end:return RolloverState.ACTIVE
            if anchor-timedelta(minutes=item.pre_minutes)<=naive<anchor:return RolloverState.APPROACHING
            if end<=naive<end+timedelta(minutes=item.post_minutes):return RolloverState.RECOVERY
        return RolloverState.NORMAL

    def _eligibility(self,primary:SessionType,active:tuple[str,...],restriction:TemporalRestriction)->dict[str,SessionEligibility]:
        families=self.configuration.strategy_eligibility or {}
        result={}
        for family,policy in families.items():
            states=[policy.get(session,SessionEligibility.UNKNOWN) for session in active]
            state=states[0] if states else policy.get(primary.name,SessionEligibility.UNKNOWN)
            if restriction is TemporalRestriction.BLOCK_SESSION_DEPENDENT_ACTIVITY:state=SessionEligibility.BLOCKED
            elif restriction is TemporalRestriction.RESTRICT_CONTEXT and state is SessionEligibility.ELIGIBLE:state=SessionEligibility.RESTRICTED
            result[family]=state
        return result

    def analyze(self,market:MarketDataSnapshot,*,closed_observations_after_reopen:int=0)->SessionSnapshot|None:
        utc=market.as_of_timestamp
        if utc.tzinfo is None:
            self.audit.record("time_conversion_failed",{"reason":"TIME_INVALID"});return None
        utc=utc.astimezone(timezone.utc); reasons=[]; warnings=[]
        discontinuity=False
        if self._last_instant is not None:
            delta=(utc-self._last_instant).total_seconds()/60
            discontinuity=delta<0 or delta>self.configuration.maximum_clock_jump_minutes
            if discontinuity:reasons.append("CLOCK_DISCONTINUITY")
        context=self.time_context(utc,market.configuration_snapshot_id); active=self._active(utc,market.instrument_id)
        active_ids=tuple(item[0].session_id for item in active)
        types={item[0].session_type for item in active}
        overlap=SessionType.LONDON in types and SessionType.NEW_YORK in types
        if overlap:primary=SessionType.LONDON_NEW_YORK_OVERLAP;reasons.append("SESSION_OVERLAP")
        elif not active:primary=SessionType.OUT_OF_SESSION;reasons.append("OUT_OF_SESSION")
        elif len(active)>1:primary=active[0][0].session_type;reasons.append("MULTIPLE_ACTIVE")
        else:primary=active[0][0].session_type;reasons.append("SESSION_ACTIVE")
        reference_date=context.reference_time.date(); weekend=reference_date.weekday() in self.configuration.weekend_days
        calendar_decision=self.calendar.resolve(reference_date,market.instrument_id) if self.calendar else CalendarDecision(CalendarDayState.UNKNOWN,reason="CALENDAR_UNKNOWN")
        if weekend or calendar_decision.state is CalendarDayState.CLOSED:
            availability=ExpectedAvailability.EXPECTED_CLOSED;reasons.append("EXPECTED_WEEKEND_CLOSURE" if weekend else "EXPECTED_MARKET_CLOSED")
        elif calendar_decision.state in (CalendarDayState.OPEN,CalendarDayState.SHORTENED,CalendarDayState.DELAYED_OPEN):availability=ExpectedAvailability.EXPECTED_OPEN
        else:availability=ExpectedAvailability.UNKNOWN;reasons.append("CALENDAR_UNKNOWN")
        provenance=calendar_decision.provenance
        availability_context=ExpectedAvailabilityContext(availability,availability is ExpectedAvailability.EXPECTED_CLOSED,tuple(reasons),
            provenance.calendar_id if provenance else None,provenance.version if provenance else None)
        friday_local=utc.astimezone(self.timezones.zone(self.configuration.friday_cutoff.timezone_name)); is_friday=friday_local.weekday()==4
        friday=self.configuration.friday_cutoff.restriction if is_friday and friday_local.timetz().replace(tzinfo=None)>=self.configuration.friday_cutoff.cutoff else FridayRestrictionState.NORMAL
        if friday is not FridayRestrictionState.NORMAL:reasons.append("FRIDAY_RESTRICTION_ACTIVE")
        rollover=self._rollover(utc)
        if rollover is RolloverState.ACTIVE:reasons.append("ROLLOVER_ACTIVE")
        monday=MondayReopeningState.NOT_APPLICABLE
        if context.reference_time.weekday()==0:
            if not active:monday=MondayReopeningState.WAITING_FOR_OPEN
            else:
                since=min(int((utc-item[1]).total_seconds()/60) for item in active)
                if since<self.configuration.monday_reopen_delay_minutes:monday=MondayReopeningState.INITIAL_REOPEN_WINDOW
                elif market.data_health is not DataHealth.HEALTHY or market.synchronization_status is not SynchronizationStatus.SYNCHRONIZED:monday=MondayReopeningState.DATA_REVALIDATION
                elif closed_observations_after_reopen<self.configuration.minimum_reopen_observations:monday=MondayReopeningState.NORMALIZATION_PENDING
                elif market.bid_ask_state.health is SpreadHealth.EXTREME:monday=MondayReopeningState.NORMALIZATION_PENDING
                else:monday=MondayReopeningState.READY
            if monday is not MondayReopeningState.READY:reasons.append("MONDAY_DATA_NOT_READY")
        health=SessionHealth.HEALTHY
        if discontinuity:health=SessionHealth.RESTRICTED
        if availability is ExpectedAvailability.UNKNOWN and self.configuration.calendar_required:health=SessionHealth.CALENDAR_UNAVAILABLE
        restriction=TemporalRestriction.ALLOW_CONTEXT
        if health is not SessionHealth.HEALTHY or availability is ExpectedAvailability.UNKNOWN:restriction=TemporalRestriction.BLOCK_SESSION_DEPENDENT_ACTIVITY
        elif availability is ExpectedAvailability.EXPECTED_CLOSED or friday is not FridayRestrictionState.NORMAL or rollover is not RolloverState.NORMAL or monday not in (MondayReopeningState.NOT_APPLICABLE,MondayReopeningState.READY):restriction=TemporalRestriction.RESTRICT_CONTEXT
        eligibility=self._eligibility(primary,active_ids,restriction)
        trace=DecisionTraceBuilder(self.clock,deterministic_id("session_decision",market.snapshot_id),deterministic_id("correlation",market.snapshot_id,"session"))
        trace.evaluate("time",DecisionStatus.PASSED if context.health is TimeHealth.HEALTHY else DecisionStatus.FAILED,context.health.name,utc.isoformat())
        trace.evaluate("sessions",DecisionStatus.PASSED,"SESSIONS_RESOLVED",",".join(active_ids) or "OUT_OF_SESSION")
        trace.evaluate("restriction",DecisionStatus.PASSED if restriction is TemporalRestriction.ALLOW_CONTEXT else DecisionStatus.FAILED,restriction.name,"temporal metadata only")
        decision_trace=trace.complete(DecisionOutcome.NO_ACTION,"session intelligence cannot authorize activity")
        since_open=min((int((utc-item[1]).total_seconds()/60) for item in active),default=None)
        to_close=min((int((item[2]-utc).total_seconds()/60) for item in active),default=None)
        identity=deterministic_id("session",market.snapshot_id,market.configuration_snapshot_id,SESSION_ENGINE_VERSION,
            primary.name,"|".join(active_ids),self.trading_day_id(utc),self.trading_week_id(utc),calendar_decision.state.name)
        result=SessionSnapshot(identity,self.clock.now(),utc,market.experiment_id,market.dataset_id,market.dataset_fingerprint,
            market.instrument_id,market.snapshot_id,context,primary,active_ids,overlap,availability_context,not weekend,
            self.trading_day_id(utc),self.trading_week_id(utc),is_friday,friday,weekend,monday,rollover,since_open,to_close,
            self._next_open(utc,market.instrument_id) if not active else 0,health,restriction,eligibility,tuple(dict.fromkeys(reasons)),tuple(warnings),
            provenance,decision_trace,market.configuration_snapshot_id,market.recovery_epoch,"system-zoneinfo")
        self._last_instant=utc;self._last_snapshot=result
        self.audit.record("session_snapshot_created",{"session_snapshot_id":identity,"primary":primary.name,"health":health.name})
        return result

    def recovery_state(self)->Mapping[str,object]:
        if self._last_snapshot is None:return {"session_engine_version":SESSION_ENGINE_VERSION}
        return {"session_engine_version":SESSION_ENGINE_VERSION,"latest_session_snapshot_id":self._last_snapshot.session_snapshot_id,
            "last_processed_utc":self._last_snapshot.as_of_timestamp_utc.isoformat(),"active_sessions":self._last_snapshot.active_sessions,
            "trading_day_id":self._last_snapshot.trading_day_id,"trading_week_id":self._last_snapshot.trading_week_id,
            "configuration_snapshot_id":self._last_snapshot.configuration_snapshot_id,"dataset_fingerprint":self._last_snapshot.dataset_fingerprint}

    def validate_recovery(self,state:Mapping[str,object],dataset_fingerprint:str,configuration_snapshot_id:str)->bool:
        return state.get("session_engine_version")==SESSION_ENGINE_VERSION and state.get("dataset_fingerprint")==dataset_fingerprint and state.get("configuration_snapshot_id")==configuration_snapshot_id

    def readiness(self,snapshot:SessionSnapshot|None):
        ready=snapshot is not None and snapshot.session_health is SessionHealth.HEALTHY and snapshot.time_context.health is TimeHealth.HEALTHY
        return ready,() if ready else ("session:NOT_READY",)
