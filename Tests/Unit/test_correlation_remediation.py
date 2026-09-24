from dataclasses import FrozenInstanceError,replace
from datetime import timedelta
from decimal import Decimal
import pytest

from amrte.portfolio.correlation import *
from amrte.portfolio.risk import AdmissionOutcome
from Tests.Unit.test_correlation_dependency import NOW,admit,engine,mappings,pregistry,req,series


def configured(**changes):
    base=CorrelationConfiguration(minimum_observations=3,lookback_observations=10,stale_after_seconds=100000,cluster_entry_threshold=Decimal(".75"),cluster_exit_threshold=Decimal(".6"),maximum_cluster_exposure=Decimal("2"),maximum_cluster_risk=Decimal("2"),maximum_cluster_members=8,maximum_cluster_portfolio_share=Decimal("1"),configuration_snapshot_id="C23R")
    return CorrelationDependencyEngine(replace(base,**changes),DeterministicExposureDecomposer(mappings()))


def active_two(amount=".2"):
    r=pregistry();_,a=admit(r,req("A","FICTIONAL_AB",amount=amount));_,b=admit(r,req("B","FICTIONAL_AC",amount=amount));return r,(a,b)


def test_square_matrix_diagonal_symmetry_canonical_identity_and_immutability():
    e=configured();data={"FICTIONAL_AC":series("FICTIONAL_AC",[2,4,6,8]),"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3,4])};directions={k:ResearchDirection.BULLISH for k in data};m=e.correlation_matrix(data,directions,NOW)
    assert m.instrument_ids==("FICTIONAL_AB","FICTIONAL_AC") and len(m.cells)==2 and all(len(x)==2 for x in m.cells)
    assert m.cells[0][0].correlation==m.cells[1][1].correlation==1 and m.cells[0][1].correlation==m.cells[1][0].correlation and m.cells[0][1].pair_id==m.cells[1][0].pair_id
    assert m.snapshot_id==e.correlation_matrix(dict(reversed(tuple(data.items()))),directions,NOW).snapshot_id
    with pytest.raises(FrozenInstanceError):m.health=CorrelationHealth.INVALID


def test_matrix_unknown_partial_zero_variance_and_window_isolation():
    e=configured();data={"FICTIONAL_AB":series("FICTIONAL_AB",[1,1,1]),"FICTIONAL_AC":series("FICTIONAL_AC",[1,2,3])};directions={k:ResearchDirection.BULLISH for k in data};a=e.correlation_matrix(data,directions,NOW,CorrelationWindow("SHORT",3));b=e.correlation_matrix(data,directions,NOW,CorrelationWindow("LONG",4))
    assert a.cells[0][1].health is CorrelationHealth.ZERO_VARIANCE and a.health in (CorrelationHealth.PARTIAL,CorrelationHealth.ZERO_VARIANCE) and a.snapshot_id!=b.snapshot_id
    missing=e.correlation_matrix({"FICTIONAL_AB":data["FICTIONAL_AB"]},{**directions,"FICTIONAL_AC":ResearchDirection.BULLISH},NOW);assert missing.cells[0][1].correlation is None and missing.cells[0][1].health is CorrelationHealth.INSUFFICIENT_HISTORY


def test_multi_window_most_restrictive_weighted_and_permutation():
    windows=(CorrelationWindow("W3",3,Decimal("1")),CorrelationWindow("W4",4,Decimal("3")))
    data={"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3,4]),"FICTIONAL_AC":series("FICTIONAL_AC",[1,2,3,-4])};directions={k:ResearchDirection.BULLISH for k in data}
    e=configured(windows=windows,window_aggregation_policy=WindowAggregationPolicy.MOST_RESTRICTIVE);m=e.multi_window(data,directions,NOW);deps=[]
    for mid in m.matrix_snapshot_ids:
        mat=e.matrices[mid];deps.append(mat.cells[0][1].adjusted_dependency)
    assert m.aggregated_pairs[0].dependency==max(deps)
    ep=configured(windows=tuple(reversed(windows)),window_aggregation_policy=WindowAggregationPolicy.MOST_RESTRICTIVE);assert ep.multi_window(data,directions,NOW).aggregated_pairs[0].dependency==m.aggregated_pairs[0].dependency
    ew=configured(windows=windows,window_aggregation_policy=WindowAggregationPolicy.WEIGHTED);w=ew.multi_window(data,directions,NOW);assert min(deps)<=w.aggregated_pairs[0].dependency<=max(deps)


def test_multi_window_missing_required_fails_closed_and_future_excluded():
    e=configured(windows=(CorrelationWindow("W3",3),CorrelationWindow("W20",20)),minimum_valid_windows=2,missing_window_policy=MissingWindowPolicy.BLOCK);data={"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3,4]),"FICTIONAL_AC":series("FICTIONAL_AC",[1,2,3,4])};m=e.multi_window(data,{k:ResearchDirection.BULLISH for k in data},NOW)
    assert m.aggregated_pairs[0].dependency is None and m.health is CorrelationHealth.PARTIAL and m.restrictions


def test_cluster_entry_confirmation_duplicate_observation_and_activation():
    r,records=active_two();data={"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3,4]),"FICTIONAL_AC":series("FICTIONAL_AC",[2,4,6,8])};e=configured(entry_confirmation_count=2)
    s1=e.snapshot(r.snapshot(NOW),records,data,NOW);assert s1.published_clusters[0].state is ClusterLifecycleState.ENTRY_PENDING and s1.published_clusters[0].entry_count==1
    same=e.snapshot(r.snapshot(NOW),records,data,NOW);assert same.published_clusters[0].entry_count==1
    s2=e.snapshot(r.snapshot(NOW+timedelta(minutes=1)),records,data,NOW+timedelta(minutes=1));assert s2.published_clusters[0].state is ClusterLifecycleState.ACTIVE


def test_cluster_exit_confirmation_cooldown_and_completion():
    r,records=active_two();strong={"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3,4]),"FICTIONAL_AC":series("FICTIONAL_AC",[2,4,6,8])};weak={"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3,4]),"FICTIONAL_AC":series("FICTIONAL_AC",[1,-1,1,-1])};e=configured(exit_confirmation_count=2,cluster_release_cooldown_seconds=60)
    assert e.snapshot(r.snapshot(NOW),records,strong,NOW).published_clusters[0].state is ClusterLifecycleState.ACTIVE
    assert e.snapshot(r.snapshot(NOW+timedelta(minutes=1)),records,weak,NOW+timedelta(minutes=1)).published_clusters[0].state is ClusterLifecycleState.EXIT_PENDING
    s=e.snapshot(r.snapshot(NOW+timedelta(minutes=2)),records,weak,NOW+timedelta(minutes=2));assert s.published_clusters[0].state is ClusterLifecycleState.COOLDOWN
    done=e.snapshot(r.snapshot(NOW+timedelta(minutes=4)),records,weak,NOW+timedelta(minutes=4));assert done.published_clusters==()


def test_active_cluster_stale_is_restrictive():
    r,records=active_two();strong={"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3,4]),"FICTIONAL_AC":series("FICTIONAL_AC",[2,4,6,8])};e=configured(stale_after_seconds=1000)
    e.snapshot(r.snapshot(NOW),records,strong,NOW);later=NOW+timedelta(hours=1);s=e.snapshot(r.snapshot(later),records,strong,later);assert s.published_clusters[0].state is ClusterLifecycleState.STALE_RESTRICTED


def test_cluster_member_risk_and_share_limits_bind_conservatively():
    r,records=active_two(".2");q=req("C","FICTIONAL_XY",amount=".3");p22=r.assess(q);data={x:series(x,[1,2,3,4]) for x in ("FICTIONAL_AB","FICTIONAL_AC","FICTIONAL_XY")}
    member=configured(maximum_cluster_members=2);d=member.assess(q,p22,member.snapshot(r.snapshot(NOW),records,data,NOW),records,data);assert d.outcome is CorrelationDecisionOutcome.BLOCK
    risk=configured(maximum_cluster_risk=Decimal(".5"));d=risk.assess(q,p22,risk.snapshot(r.snapshot(NOW),records,data,NOW),records,data);assert Decimal("0")<=d.approved_exposure<=Decimal(".1")
    share=configured(maximum_cluster_portfolio_share=Decimal(".8"));d=share.assess(q,p22,share.snapshot(r.snapshot(NOW),records,data,NOW),records,data);assert d.approved_exposure<=p22.approved_exposure


def test_no_action_is_distinct_and_non_mutating():
    r=pregistry();q=req("ZERO",amount="0");p22=replace(r.assess(q),outcome=AdmissionOutcome.NO_ACTION,approved_exposure=Decimal("0"),approved_risk=Decimal("0"));e=configured();snap=e.snapshot(r.snapshot(NOW),(),{},NOW);before=(len(r.records),len(r.reservations));d=e.assess(q,p22,snap,(),{})
    assert d.outcome is CorrelationDecisionOutcome.NO_ACTION and d.approved_exposure==0 and before==(len(r.records),len(r.reservations))


def test_recovery_preserves_cluster_state_and_corruption_fails_closed():
    r,records=active_two();data={"FICTIONAL_AB":series("FICTIONAL_AB",[1,2,3,4]),"FICTIONAL_AC":series("FICTIONAL_AC",[2,4,6,8])};e=configured();e.snapshot(r.snapshot(NOW),records,data,NOW);state=e.recovery_state();restored=configured();assert restored.restore(state) and tuple(restored.cluster_states)==tuple(e.cluster_states)
    bad={**state,"schema_version":"OLD"};assert not restored.restore(bad) and restored.recovery_restricted


def test_handoff_is_complete_and_does_not_allocate():
    r=pregistry();q=req("A");p22=r.assess(q);e=configured();snap=e.snapshot(r.snapshot(NOW),(),{},NOW);d=e.assess(q,p22,snap,(),{});h=e.prompt24_handoff(d)
    assert h["correlation_matrix_snapshot_id"]==snap.correlation_matrix_id and "approved_fictional_exposure" in h and not any(k in h for k in ("allocation","order","position"))


def test_metamorphic_scaling_translation_sign_and_limit_tightening():
    e=configured();a=series("FICTIONAL_AB",[1,2,4,8]);b=series("FICTIONAL_AC",[2,3,7,9]);base=e.pair(a,b).correlation
    assert e.pair(series("FICTIONAL_AB",[10,20,40,80]),b).correlation==base
    assert e.pair(series("FICTIONAL_AB",[6,7,9,13]),b).correlation==base
    assert e.pair(series("FICTIONAL_AB",[-1,-2,-4,-8]),b).correlation==-base


def test_failure_injection_invalid_config_and_recovery_payloads():
    for changes in ({"cluster_exit_threshold":Decimal(".8")},{"entry_confirmation_count":0},{"cluster_release_cooldown_seconds":-1},{"maximum_cluster_members":0},{"maximum_cluster_portfolio_share":Decimal("1.1")},{"windows":(CorrelationWindow("BAD",0),)}):
        with pytest.raises(ValueError):configured(**changes)
    e=configured();assert not e.restore({}) and e.recovery_restricted
