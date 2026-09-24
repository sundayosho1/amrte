from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
import pytest

from amrte.portfolio.correlation import *
from amrte.portfolio.risk import *
from amrte.risk.invalidation import ResearchDirection

NOW=datetime(2026,6,10,12,tzinfo=timezone.utc)

def mappings():
    return (
        InstrumentFactorMapping("FICTIONAL_AB",(FactorLeg("A",Decimal("1")),FactorLeg("B",Decimal("-1"))),"1",NOW-timedelta(days=2),"DS"),
        InstrumentFactorMapping("FICTIONAL_AC",(FactorLeg("A",Decimal("1")),FactorLeg("C",Decimal("-1"))),"1",NOW-timedelta(days=2),"DS"),
        InstrumentFactorMapping("FICTIONAL_XY",(FactorLeg("X",Decimal("1")),FactorLeg("Y",Decimal("-1"))),"1",NOW-timedelta(days=2),"DS"),
    )

def pregistry():
    cfg=PortfolioConfiguration(maximum_research_risk=Decimal("10"),maximum_gross_exposure=Decimal("10"),soft_risk_threshold=Decimal("8"),soft_gross_threshold=Decimal("8"),maximum_bullish_exposure=Decimal("10"),maximum_bearish_exposure=Decimal("10"),maximum_directional_imbalance=Decimal("10"),maximum_instrument_risk=Decimal("10"),maximum_instrument_exposure=Decimal("10"),maximum_factor_gross=Decimal("10"),maximum_factor_net=Decimal("10"),maximum_strategy_risk=Decimal("10"),maximum_strategy_exposure=Decimal("10"),maximum_family_risk=Decimal("10"),maximum_family_exposure=Decimal("10"),maximum_variant_risk=Decimal("10"),maximum_variant_exposure=Decimal("10"),configuration_snapshot_id="P22")
    return PortfolioExposureRegistry(cfg,DeterministicExposureDecomposer(mappings()))

def req(tag,instrument="FICTIONAL_AB",direction=ResearchDirection.BULLISH,amount=".4"):
    factors=("A","B") if instrument=="FICTIONAL_AB" else ("A","C") if instrument=="FICTIONAL_AC" else ("X","Y")
    return PortfolioAdmissionRequest.create("SNAP-"+tag,"17-"+tag,"18-"+tag,"19-"+tag,"S1","1","TREND",None,instrument,direction,"DS",factors,amount,amount,NOW,"P22")

def admit(r,q):
    d=r.assess(q); return d,r.commit(d,q,"SIG-"+q.request_id,NOW)

def series(instrument,values,offset=0,available_shift=0,fingerprint="FP"):
    obs=[]
    for i,v in enumerate(values):
        at=NOW-timedelta(minutes=(len(values)-i+offset)*15)
        obs.append(ReturnObservation(instrument,"M15",at,at+timedelta(minutes=available_shift),Decimal(str(v)),"SIMPLE_RETURN","DS",fingerprint,f"F-{instrument}-{i}"))
    return ReturnSeries.create(instrument,"M15",obs,"DS",fingerprint,NOW)

def engine(**kw):
    values=dict(minimum_observations=3,lookback_observations=10,stale_after_seconds=100000,maximum_cluster_exposure=Decimal(".6"),maximum_dependency_score=Decimal(".95"),configuration_snapshot_id="C23");values.update(kw);cfg=CorrelationConfiguration(**values)
    return CorrelationDependencyEngine(cfg,DeterministicExposureDecomposer(mappings()))

def test_configuration_and_provider_contract():
    assert engine().available()
    with pytest.raises(ValueError):CorrelationDependencyEngine(CorrelationConfiguration(minimum_observations=1))
    with pytest.raises(ValueError):CorrelationDependencyEngine(CorrelationConfiguration(strong_threshold=Decimal("NaN")))

def test_pearson_reference_positive_negative_symmetry_and_bounds():
    e=engine();a=series("FICTIONAL_AB",[1,2,3,4]);b=series("FICTIONAL_AC",[2,4,6,8]);n=series("FICTIONAL_XY",[-2,-4,-6,-8])
    assert e.pair(a,b).correlation==Decimal("1.0")
    assert e.pair(b,a).correlation==Decimal("1.0")
    assert e.pair(a,n).correlation==Decimal("-1.0")
    assert -1 <= e.pair(a,b).correlation <= 1

def test_timestamp_intersection_future_observations_excluded():
    e=engine();a=series("FICTIONAL_AB",[1,2,3,4]);b=series("FICTIONAL_AC",[2,4,6,8])
    future=ReturnObservation("FICTIONAL_AB","M15",NOW+timedelta(minutes=1),NOW+timedelta(minutes=1),Decimal("99"),"SIMPLE_RETURN","DS","FP","FUTURE")
    extended=ReturnSeries.create("FICTIONAL_AB","M15",a.observations+(future,),"DS","FP",NOW)
    assert e.pair(a,b).pair_id==e.pair(extended,b).pair_id

def test_insufficient_zero_variance_stale_and_lineage_fail_closed():
    e=engine();short=series("FICTIONAL_AB",[1,2]);other=series("FICTIONAL_AC",[1,2]);assert e.pair(short,other).health is CorrelationHealth.INSUFFICIENT_HISTORY
    flat=series("FICTIONAL_AB",[1,1,1]);vary=series("FICTIONAL_AC",[1,2,3]);assert e.pair(flat,vary).health is CorrelationHealth.ZERO_VARIANCE
    old=engine(stale_after_seconds=1);assert old.pair(series("FICTIONAL_AB",[1,2,3]),series("FICTIONAL_AC",[1,2,3])).health is CorrelationHealth.STALE
    assert e.pair(series("FICTIONAL_AB",[1,2,3]),series("FICTIONAL_AC",[1,2,3],fingerprint="OTHER")).health is CorrelationHealth.INVALID

def test_direction_adjustment_recognizes_reinforcement_and_offset():
    e=engine();a=series("FICTIONAL_AB",[1,2,3]);positive=series("FICTIONAL_AC",[2,4,6]);negative=series("FICTIONAL_XY",[-2,-4,-6])
    assert e.pair(a,positive,ResearchDirection.BULLISH,ResearchDirection.BULLISH).adjusted_dependency==1
    assert e.pair(a,positive,ResearchDirection.BULLISH,ResearchDirection.BEARISH).adjusted_dependency==-1
    assert e.pair(a,negative,ResearchDirection.BULLISH,ResearchDirection.BEARISH).adjusted_dependency==1

def test_factor_matrix_uses_prompt22_decomposer_and_is_immutable():
    r=pregistry();_,one=admit(r,req("A"));_,two=admit(r,req("B","FICTIONAL_AC",ResearchDirection.BEARISH,".2"));snap=r.snapshot(NOW);m=engine().factor_matrix(snap,(one,two),NOW)
    values={(x.instrument_id,x.factor_id):x.signed_exposure for x in m.cells};assert values[("FICTIONAL_AB","A")]==Decimal(".4") and values[("FICTIONAL_AC","A")]==Decimal("-.2")
    with pytest.raises(FrozenInstanceError):m.matrix_id="x"

def test_transitive_cluster_and_deterministic_identity():
    r=pregistry();records=[]
    for tag,inst in (("A","FICTIONAL_AB"),("B","FICTIONAL_AC"),("C","FICTIONAL_XY")):records.append(admit(r,req(tag,inst,amount=".1"))[1])
    data={x:series(x,[1,2,3,4]) for x in ("FICTIONAL_AB","FICTIONAL_AC","FICTIONAL_XY")};e=engine(maximum_cluster_exposure=Decimal("1"));s1=e.snapshot(r.snapshot(NOW),tuple(records),data,NOW);s2=e.snapshot(r.snapshot(NOW),tuple(reversed(records)),data,NOW)
    assert len(s1.clusters)==1 and len(s1.clusters[0].instrument_ids)==3 and s1.snapshot_id==s2.snapshot_id

def test_candidate_what_if_reduces_without_mutating_prompt22():
    r=pregistry();_,record=admit(r,req("A",amount=".4"));q=req("B","FICTIONAL_AC",amount=".4");p22=r.assess(q);data={"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3,4]),"FICTIONAL_AC":series("FICTIONAL_AC",[2,4,6,8])};e=engine();snap=e.snapshot(r.snapshot(NOW),(record,),data,NOW);before=(len(r.records),len(r.reservations));d=e.assess(q,p22,snap,(record,),data)
    assert d.outcome is CorrelationDecisionOutcome.REDUCE_FURTHER and d.approved_exposure==Decimal(".20") and d.approved_exposure<=p22.approved_exposure and before==(len(r.records),len(r.reservations))

def test_missing_required_series_blocks_and_high_score_never_grants_capacity():
    r=pregistry();_,record=admit(r,req("A",amount=".2"));q=req("B","FICTIONAL_AC",amount=".2");p22=r.assess(q);e=engine();snap=e.snapshot(r.snapshot(NOW),(record,),{"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3])},NOW);d=e.assess(q,p22,snap,(record,),{})
    assert d.outcome is CorrelationDecisionOutcome.BLOCK and d.approved_exposure==0

def test_prompt22_block_cannot_be_overridden():
    r=pregistry();q=req("A");blocked=replace(r.assess(q),outcome=AdmissionOutcome.BLOCK,approved_exposure=ZERO,approved_risk=ZERO);e=engine();snap=e.snapshot(r.snapshot(NOW),(),{},NOW);d=e.assess(q,blocked,snap,(),{})
    assert d.outcome is CorrelationDecisionOutcome.BLOCK and d.approved_exposure==0

def test_non_correlated_candidate_allowed_unchanged():
    r=pregistry();_,record=admit(r,req("A",amount=".2"));q=req("B","FICTIONAL_XY",amount=".2");p22=r.assess(q);data={"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3,4]),"FICTIONAL_XY":series("FICTIONAL_XY",[1,-1,1,-1])};e=engine();snap=e.snapshot(r.snapshot(NOW),(record,),data,NOW);d=e.assess(q,p22,snap,(record,),data)
    assert d.outcome is CorrelationDecisionOutcome.ALLOW_UNCHANGED and d.approved_exposure==p22.approved_exposure

def test_snapshot_decision_recovery_trace_and_prompt24_handoff():
    r=pregistry();q=req("A");p22=r.assess(q);e=engine();snap=e.snapshot(r.snapshot(NOW),(),{},NOW);d=e.assess(q,p22,snap,(),{});state=e.recovery_state()
    assert e.validate_recovery(state) and not e.validate_recovery({**state,"engine_version":"OLD"}) and d.decision_trace
    handoff=e.prompt24_handoff(d);assert handoff["approved_fictional_exposure"]==d.approved_exposure and handoff["correlation_risk_decision_id"]==d.decision_id

def test_bounded_state_determinism_isolation_and_safety_surface():
    e=engine(maximum_snapshots=1,maximum_decisions=1);r=pregistry();snap=r.snapshot(NOW);e.snapshot(snap,(),{},NOW);e.snapshot(snap,(),{},NOW+timedelta(minutes=1));assert len(e.snapshots)==1
    forbidden={"connect_broker","broker_login","read_account","place_order","modify_order","close_position","set_leverage","calculate_margin"};assert forbidden.isdisjoint(set(dir(e)))

@pytest.mark.parametrize("bad",[Decimal("NaN"),Decimal("Infinity")])
def test_invalid_return_values_fail_closed(bad):
    obs=[ReturnObservation("FICTIONAL_AB","M15",NOW-timedelta(minutes=i+1),NOW-timedelta(minutes=i+1),bad,"SIMPLE_RETURN","DS","FP",str(i)) for i in range(3)]
    a=ReturnSeries.create("FICTIONAL_AB","M15",obs,"DS","FP",NOW);b=series("FICTIONAL_AC",[1,2,3]);assert engine().pair(a,b).health in (CorrelationHealth.INVALID,CorrelationHealth.INSUFFICIENT_HISTORY)

def test_bounded_performance_fixture():
    e=engine(minimum_observations=20,lookback_observations=100);values=[math.sin(i/5) for i in range(100)];items=[series(f"I{i}",values) for i in range(12)];pairs=[e.pair(items[i],items[j]) for i in range(12) for j in range(i+1,12)];assert len(pairs)==66 and all(x.health is CorrelationHealth.HEALTHY for x in pairs)
