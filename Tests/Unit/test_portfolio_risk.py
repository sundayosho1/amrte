from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.portfolio.risk import *
from amrte.risk.invalidation import ResearchDirection,ThesisState
from amrte.risk.exit_management import ExitManagementState
from amrte.risk.protection import ProtectiveManagementState,BreakEvenState,TrailingState

NOW=datetime(2026,6,10,12,tzinfo=timezone.utc)

def mappings():
    return (InstrumentFactorMapping("FICTIONAL_AB",(FactorLeg("FACTOR_A",Decimal("1")),FactorLeg("FACTOR_B",Decimal("-1"))),"1",NOW,"DATASET-A"),InstrumentFactorMapping("FICTIONAL_AC",(FactorLeg("FACTOR_A",Decimal("1")),FactorLeg("FACTOR_C",Decimal("-1"))),"1",NOW,"DATASET-A"))

def registry(**kwargs):
    cfg=PortfolioConfiguration(maximum_research_risk=Decimal("1"),maximum_gross_exposure=Decimal("1"),soft_risk_threshold=Decimal(".8"),soft_gross_threshold=Decimal(".8"),maximum_bullish_exposure=Decimal("1"),maximum_bearish_exposure=Decimal("1"),maximum_directional_imbalance=Decimal("1"),maximum_instrument_risk=Decimal("1"),maximum_instrument_exposure=Decimal("1"),maximum_factor_gross=Decimal("1"),maximum_factor_net=Decimal("1"),maximum_strategy_risk=Decimal("1"),maximum_strategy_exposure=Decimal("1"),maximum_family_risk=Decimal("1"),maximum_family_exposure=Decimal("1"),maximum_variant_risk=Decimal("1"),maximum_variant_exposure=Decimal("1"),**kwargs)
    return PortfolioExposureRegistry(cfg,DeterministicExposureDecomposer(mappings()))

def request(tag="A",exposure="0.4",risk=None,direction=ResearchDirection.BULLISH,instrument="FICTIONAL_AB",strategy="S1",family="TREND",variant=None,at=NOW):
    return PortfolioAdmissionRequest.create(f"SNAP-{tag}",f"P17-{tag}",f"P18-{tag}",f"P19-{tag}",strategy,"1",family,variant,instrument,direction,"DATASET-A",("FACTOR_A","FACTOR_B") if instrument=="FICTIONAL_AB" else ("FACTOR_A","FACTOR_C"),exposure,risk or exposure,at)

def admit(r,req):
    decision=r.assess(req);record=r.commit(decision,req,f"SIGNAL-{req.request_id}",req.as_of_timestamp_utc);return decision,record

def test_empty_snapshot_and_immutability():
    r=registry();s=r.snapshot(NOW);assert s.gross_exposure==0 and s.total_open_research_risk==0 and s.health is PortfolioHealth.HEALTHY
    with pytest.raises(FrozenInstanceError):s.gross_exposure=1

def test_full_admission_commit_and_aggregate_exposure():
    r=registry();d,record=admit(r,request());s=r.snapshot(NOW);assert d.outcome is AdmissionOutcome.ALLOW_FULL and record.status is ExposureStatus.ACTIVE and s.gross_exposure==Decimal(".4") and s.net_directional_exposure==Decimal(".4") and s.total_open_research_risk==Decimal(".4")

def test_bull_bear_gross_and_net_remain_distinct():
    r=registry();admit(r,request("A",".4"));admit(r,request("B",".4",direction=ResearchDirection.BEARISH,strategy="S2",family="BREAKOUT"));s=r.snapshot(NOW);assert s.gross_exposure==Decimal(".8") and s.net_directional_exposure==0 and s.bullish_exposure==s.bearish_exposure==Decimal(".4")

def test_instrument_strategy_family_variant_aggregation():
    r=registry();admit(r,request("A",".2",strategy="S2",family="BREAKOUT",variant="IMMEDIATE"));admit(r,request("B",".3",strategy="S2",family="BREAKOUT",variant="RETEST"));s=r.snapshot(NOW);assert dict(s.instrument_exposure)["FICTIONAL_AB"]==Decimal(".5") and dict(s.strategy_exposure)["S2"]==Decimal(".5") and dict(s.strategy_family_exposure)["BREAKOUT"]==Decimal(".5") and dict(s.strategy_variant_exposure)=={"IMMEDIATE":Decimal(".2"),"RETEST":Decimal(".3")}

def test_factor_signs_and_direct_concentration_without_correlation():
    r=registry();admit(r,request("A",".4"));s=r.snapshot(NOW);f={x.factor_id:x for x in s.factor_exposure};assert f["FACTOR_A"].long_exposure==Decimal(".4") and f["FACTOR_B"].short_exposure==Decimal(".4") and not ICorrelationRiskProvider().available()
    r2=registry();admit(r2,request("B",".4",direction=ResearchDirection.BEARISH));f={x.factor_id:x for x in r2.snapshot(NOW).factor_exposure};assert f["FACTOR_A"].short_exposure==Decimal(".4") and f["FACTOR_B"].long_exposure==Decimal(".4")

def test_missing_factor_mapping_fails_closed():
    r=PortfolioExposureRegistry(replace(registry().configuration,maximum_research_risk=Decimal("10"),maximum_gross_exposure=Decimal("10")));d=r.assess(request());assert d.outcome is AdmissionOutcome.BLOCK and d.binding_constraint is BindingConstraint.DATA

def test_global_limit_full_reduced_and_blocked():
    r=registry();admit(r,request("A",".7"));blocked=r.assess(request("B",".7"));assert blocked.outcome is AdmissionOutcome.BLOCK
    rr=registry(reduction_policy=ReductionPolicy.REDUCE_TO_CAPACITY);admit(rr,request("A",".7"));reduced=rr.assess(request("B",".7"));assert reduced.outcome is AdmissionOutcome.ALLOW_REDUCED and reduced.approved_exposure==Decimal(".30")

def test_reservations_prevent_double_spend_and_commit_removes_reserved_risk():
    r=registry();a=request("A",".7");da=r.assess(a);b=request("B",".7");db=r.assess(b);assert da.reservation_id and db.outcome is AdmissionOutcome.BLOCK and r.snapshot(NOW).reserved_research_risk==Decimal(".7")
    r.commit(da,a,"SIG-A",NOW);assert r.snapshot(NOW).reserved_research_risk==0 and r.snapshot(NOW).total_open_research_risk==Decimal(".7")

def test_release_expiry_and_duplicate_release():
    r=registry(reservation_ttl_seconds=60);d=r.assess(request());assert r.release(d.reservation_id,NOW+timedelta(seconds=1)) and not r.release(d.reservation_id,NOW+timedelta(seconds=2))
    d2=r.assess(request("B"));assert r.expire_reservations(NOW+timedelta(seconds=61))==1 and r.reservations[d2.reservation_id].status is ReservationStatus.EXPIRED

def test_duplicate_request_and_admission_are_idempotent():
    r=registry();q=request();d1=r.assess(q);d2=r.assess(q);assert d1.reservation_id==d2.reservation_id;one=r.commit(d1,q,"SIG",NOW);two=r.commit(d1,q,"SIG",NOW);assert one.exposure_record_id==two.exposure_record_id and len(r.records)==1

def test_config_rejects_negative_nan_infinity_and_soft_above_hard():
    for value in (Decimal("-1"),Decimal("NaN"),Decimal("Infinity")):
        with pytest.raises(ValueError):PortfolioExposureRegistry(PortfolioConfiguration(maximum_research_risk=value))
    with pytest.raises(ValueError):PortfolioExposureRegistry(PortfolioConfiguration(maximum_research_risk=Decimal("1"),soft_risk_threshold=Decimal("2")))

def test_at_limit_and_over_limit_states():
    r=registry();admit(r,request("A","1"));assert r.snapshot(NOW).health is PortfolioHealth.AT_LIMIT
    r.configuration=replace(r.configuration,maximum_research_risk=Decimal(".5"),maximum_gross_exposure=Decimal(".5"),soft_risk_threshold=Decimal(".4"),soft_gross_threshold=Decimal(".4"));s=r.snapshot(NOW+timedelta(minutes=1));assert s.health is PortfolioHealth.OVER_LIMIT and r.assess(request("B",".1",at=NOW+timedelta(minutes=1))).outcome is AdmissionOutcome.BLOCK

def states(record,remaining,at=NOW):
    remaining=Decimal(str(remaining))
    exit_state=ExitManagementState("EXIT",record.initial_approved_exposure,remaining,(),(),remaining>0,remaining if remaining>0 else Decimal("0"),ThesisState.THESIS_INTACT,None,None,at,"EXIT_DEFAULT_RESEARCH",0)
    protection=ProtectiveManagementState("EXIT","BOUNDARY",Decimal("100"),Decimal("98"),remaining,BreakEvenState.ACTIVATED,TrailingState.ACTIVE,at,None,remaining==0,remaining>0,"PROTECTION_DEFAULT_RESEARCH",0)
    return exit_state,protection

def test_partial_runner_protective_and_terminal_reconciliation():
    r=registry();_,record=admit(r,request());exit_state,protection=states(record,".2");ok,_=r.reconcile(record.exposure_record_id,exit_state,protection,NOW,current_risk=Decimal(".1"));updated=r.records[record.exposure_record_id];assert ok and updated.remaining_exposure==Decimal(".2") and updated.current_risk==Decimal(".1") and updated.status is ExposureStatus.PROTECTED
    exit_state,protection=states(updated,"0",NOW+timedelta(minutes=1));assert r.reconcile(record.exposure_record_id,exit_state,protection,NOW+timedelta(minutes=1))[0] and r.records[record.exposure_record_id].status is ExposureStatus.CLOSED

def test_future_reconciliation_cannot_release_historical_capacity():
    r=registry();_,record=admit(r,request());future=NOW+timedelta(hours=1);exit_state,protection=states(record,"0",future);before=r.snapshot(NOW);assert not r.reconcile(record.exposure_record_id,exit_state,protection,NOW)[0] and r.snapshot(NOW).snapshot_id==before.snapshot_id

def test_reconciliation_never_increases_exposure_or_risk():
    r=registry();_,record=admit(r,request());exit_state,protection=states(record,".9");r.reconcile(record.exposure_record_id,exit_state,protection,NOW,current_risk=Decimal(".9"));updated=r.records[record.exposure_record_id];assert updated.remaining_exposure==record.remaining_exposure and updated.current_risk==record.current_risk

def test_ghost_missing_and_incomplete_capacity():
    r=registry();_,record=admit(r,request());assert r.detect_inconsistencies(())==("PORTFOLIO_GHOST_EXPOSURE",) and r.assess(request("B",".1")).outcome is AdmissionOutcome.BLOCK
    r=registry();assert r.detect_inconsistencies(("MISSING",))==("PORTFOLIO_MISSING_EXPOSURE",)

def test_recovery_preserves_active_records_and_reservations():
    r=registry();admit(r,request("A",".4"));d=r.assess(request("B",".2"));saved=r.recovery_state();restored=registry();assert restored.restore(saved) and restored.snapshot(NOW).gross_exposure==Decimal(".4") and restored.snapshot(NOW).reserved_research_risk==Decimal(".2") and d.reservation_id in restored.reservations

def test_corrupt_and_incompatible_recovery_fail_closed():
    r=registry();saved=r.recovery_state();assert not registry().restore({**saved,"engine_version":"OLD"});bad={**saved,"records":saved["records"]+saved["records"]};assert registry().restore(bad) is True
    _,record=admit(r,request());bad={**r.recovery_state(),"records":(record,record)};assert not registry().restore(bad)

def test_snapshot_order_independent_and_deterministic():
    a=registry();admit(a,request("A",".2"));admit(a,request("B",".3",instrument="FICTIONAL_AC",strategy="S2",family="BREAKOUT"));s1=a.snapshot(NOW)
    b=registry();admit(b,request("B",".3",instrument="FICTIONAL_AC",strategy="S2",family="BREAKOUT"));admit(b,request("A",".2"));s2=b.snapshot(NOW);assert s1.gross_exposure==s2.gross_exposure and s1.instrument_exposure==s2.instrument_exposure

def test_observability_trace_bounded_state_and_safety_surface():
    audit=InMemoryAuditSink();base=registry().configuration;cfg=replace(base,maximum_records=1,maximum_reservations=1,maximum_snapshots=1,maximum_ledger_events=2,maximum_cache_entries=1);r=PortfolioExposureRegistry(cfg,DeterministicExposureDecomposer(mappings()),audit);d,record=admit(r,request());assert d.decision_trace and len(r.records)<=1 and len(r.reservations)<=1 and any(x[0]=="portfolio_exposure_admitted" for x in audit.events)
    forbidden={"connect_broker","broker_login","read_account","read_live_positions","calculate_margin","set_leverage","place_order","modify_order","close_position","convert_live_currency"};assert forbidden.isdisjoint(set(dir(PortfolioExposureRegistry)))
