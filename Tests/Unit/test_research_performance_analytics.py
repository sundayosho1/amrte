from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from amrte.analytics.performance import *
from amrte.infrastructure.local import InMemoryAuditSink


NOW = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)


def engine(config=None, audit=None):
    return ResearchPerformanceAnalyticsEngine(config or AnalyticsConfiguration(limited_sample=2, adequate_sample=4, strong_sample=8, segmented_minimum=2, rolling_minimum=2), audit=audit)


def observation(tag, value, second, **changes):
    opened=NOW+timedelta(seconds=second);closed=opened+timedelta(minutes=5);known=closed+timedelta(seconds=1)
    values=dict(hypothesis_id=f"H-{tag}",strategy_id="S1",strategy_version="1",variant_id="V1",family_id="F1",subject_id="SUB-A",category_id="CAT-A",regime_id="REG-A",session_id="SES-A",timeframe_id="TF-A",normalized_outcome_r=value,opened_at_utc=opened,closed_at_utc=closed,known_at_utc=known,dataset_fingerprint="DATA-A",configuration_snapshot_id="NEUTRAL_ANALYTICS_DEFAULT",lifecycle_snapshot_id=f"L-{tag}",phase_vii_safety_snapshot_id=f"P7-{tag}",phase_vii_safety_state="NORMAL")
    values.update(changes);return ResearchOutcomeObservation.create(**values)


def ingest_values(target, values):
    items=[]
    for i,value in enumerate(values):
        item=observation(str(i), value, i);assert target.ingest(item,item.known_at_utc)==(True,"OUTCOME_INCLUDED");items.append(item)
    return items


def query(as_of=None, **changes):
    values=dict(scope=AnalyticsScope.GLOBAL,start_time_utc=NOW,end_time_utc=NOW+timedelta(days=1),as_of_time_utc=as_of or NOW+timedelta(days=1),dataset_fingerprint="DATA-A",configuration_snapshot_id="NEUTRAL_ANALYTICS_DEFAULT")
    values.update(changes);return ResearchAnalyticsQuery.create(**values)


def test_configuration_and_metric_registry_validation():
    with pytest.raises(ValueError):ResearchPerformanceAnalyticsEngine(AnalyticsConfiguration(limited_sample=10,adequate_sample=5))
    registry=AnalyticsMetricRegistry.default();assert registry.resolve("AVERAGE_R").definition_version==METRIC_VERSION
    with pytest.raises(ValueError):registry.register(registry.resolve("AVERAGE_R"))


def test_observation_identity_classification_and_immutability():
    positive=observation("P","1",1);flat=observation("F","0.000000001",2);negative=observation("N","-1",3)
    assert positive.outcome_classification is OutcomeClassification.POSITIVE
    assert flat.outcome_classification is OutcomeClassification.FLAT
    assert negative.outcome_classification is OutcomeClassification.NEGATIVE
    assert positive.observation_id==observation("P","1",1).observation_id
    with pytest.raises(FrozenInstanceError):positive.normalized_outcome_r=Decimal("3")


def test_invalid_future_missing_and_duplicate_observations_are_excluded():
    target=engine();valid=observation("V","1",1)
    assert target.ingest(valid,valid.known_at_utc)[0]
    assert target.ingest(valid,valid.known_at_utc)==(False,"OUTCOME_DUPLICATE")
    nan=observation("NAN","NaN",2);assert target.ingest(nan,nan.known_at_utc)==(False,"OUTCOME_INVALID")
    future=observation("F","1",3);assert target.ingest(future,future.closed_at_utc)==(False,"OUTCOME_FUTURE")
    missing=replace(observation("M","1",4),strategy_id="");assert target.ingest(missing,missing.known_at_utc)==(False,"OUTCOME_MISSING_METADATA")


def test_golden_core_metrics_expectancy_and_rate_conservation():
    target=engine();ingest_values(target,["2","1","0","-1"]);snap=target.calculate(query())
    s=snap.summary
    assert s.cumulative_normalized_outcome.value==Decimal("2.00000000")
    assert s.average_r.value==s.expectancy_r.value==Decimal("0.50000000")
    assert s.median_r.value==Decimal("0.50000000")
    assert s.positive_outcome_rate.value==Decimal("0.50000000")
    assert s.negative_outcome_rate.value==Decimal("0.25000000")
    assert s.flat_outcome_rate.value==Decimal("0.25000000")
    assert sum((s.positive_outcome_rate.value,s.negative_outcome_rate.value,s.flat_outcome_rate.value),ZERO)==ONE
    assert s.positive_negative_magnitude_ratio.value==Decimal("3.00000000")


def test_denominator_safety_does_not_fabricate_infinity_or_zero():
    target=engine();ingest_values(target,["1","2"]);snap=target.calculate(query())
    ratio=snap.summary.positive_negative_magnitude_ratio
    assert ratio.value is None and ratio.availability is MetricAvailability.UNDEFINED and ratio.reason_code=="NO_NEGATIVE_OBSERVATIONS"


def test_distribution_quantiles_tails_and_outliers_preserve_raw_data():
    target=engine();items=ingest_values(target,["-2","-1","0","1","2","100"]);snap=target.calculate(query());d=snap.distribution_statistics
    assert d.minimum_r==Decimal("-2") and d.maximum_r==Decimal("100")
    assert d.quantile_50==Decimal("0.50000000")
    assert items[-1].observation_id in d.outlier_observation_ids
    assert len(snap.included_observation_ids)==6


def test_cumulative_path_decline_and_recovery_are_dimensionless():
    target=engine();ingest_values(target,["2","-1","-2","3"]);snap=target.calculate(query());d=snap.decline_statistics
    assert tuple(x[1] for x in d.cumulative_path)==(Decimal("2.00000000"),Decimal("1.00000000"),Decimal("-1.00000000"),Decimal("2.00000000"))
    assert d.maximum_r_decline==Decimal("3.00000000")
    assert snap.summary.recovery_ratio.value==Decimal("0.66666667")


def test_sequence_statistics_flat_breaks_sequences():
    target=engine();ingest_values(target,["1","2","0","-1","-2","-3","1"]);s=target.calculate(query()).sequence_statistics
    assert s.maximum_positive_sequence==2 and s.maximum_negative_sequence==3
    assert s.negative_sequence_count==1 and s.positive_sequence_count==2
    assert s.maximum_adverse_sequence_r==Decimal("6")


def test_duration_confidence_and_sample_adequacy():
    target=engine();ingest_values(target,["1","-1","2","-2"]);snap=target.calculate(query())
    assert snap.sample_adequacy_state is SampleAdequacyState.ADEQUATE
    assert dict(snap.duration_statistics)["average_seconds"]==Decimal("300.00000000")
    assert snap.confidence_metadata.standard_error.value is not None


def test_point_in_time_future_outcome_protection():
    target=engine();items=ingest_values(target,["1","-1"]);as_of=items[0].known_at_utc
    snap=target.calculate(query(as_of=as_of,end_time_utc=as_of))
    assert snap.valid_observation_count==1 and items[1].observation_id not in snap.included_observation_ids
    assert "OUTCOME_FUTURE" in snap.excluded_reason_codes


def test_dataset_configuration_and_strategy_version_isolation():
    target=engine();a=observation("A","1",1);b=observation("B","2",2,strategy_version="2");c=observation("C","3",3,dataset_fingerprint="DATA-B")
    for x in (a,b,c):assert target.ingest(x,x.known_at_utc)[0]
    version_one=target.calculate(query(filters={"strategy_version":"1"}));assert version_one.valid_observation_count==1
    data_a=target.calculate(query());assert data_a.valid_observation_count==2 and "OUTCOME_DATASET_MISMATCH" in data_a.excluded_reason_codes


def test_segmentation_and_sparse_cells_preserve_count_conservation():
    target=engine();items=[]
    for i,(strategy,value) in enumerate((("S1","1"),("S1","-1"),("S2","2"),("S2","1"))):
        x=observation(str(i),value,i,strategy_id=strategy);target.ingest(x,x.known_at_utc);items.append(x)
    segments=target.segment(query(),"strategy")
    assert sum(x.summary.observation_count for x in segments)==4
    assert {x.dimension_value for x in segments}=={"S1","S2"}


def test_rolling_and_expanding_are_distinct_and_deterministic():
    target=engine();ingest_values(target,["1","1","-1","-1"]);lifetime=target.calculate(query());rolling=target.rolling(query(),(2,3))
    assert lifetime.summary.average_r.value==ZERO
    assert rolling[0].window_size==2 and rolling[0].summary.average_r.value==Decimal("-1.00000000")
    assert target.calculate(query()).snapshot_id==lifetime.snapshot_id


def test_trend_is_descriptive_and_has_no_permission_surface():
    target=engine();ingest_values(target,["-2","-1","1","2"]);snap=target.calculate(query())
    assert snap.analytics_trend_state is AnalyticsTrendState.IMPROVING
    forbidden={"increase_permission","increase_allocation","resume_strategy","clear_cooldown","close_circuit","place_order","submit_trade"}
    assert forbidden.isdisjoint(set(dir(target)))


def test_comparison_validity_and_deltas():
    target=engine();ingest_values(target,["1","2","-1","0"]);left=target.calculate(query(filters={"strategy":"S1"}));right=target.calculate(query(filters={"subject":"SUB-A"}))
    comparison=target.compare(left,right)
    assert comparison.validity=="VALID" and comparison.average_r_delta.value==ZERO
    incompatible=replace(right,dataset_fingerprint="OTHER")
    assert target.compare(left,incompatible).validity=="COMPARISON_INVALID"


def test_top_n_contribution_is_descriptive_and_denominator_safe():
    target=engine();ingest_values(target,["4","2","-3","-1","0"]);snap=target.calculate(query());result=target.contribution(snap,1)
    assert result.top_positive_r==Decimal("4.00000000") and result.top_negative_r==Decimal("-3.00000000")
    assert result.positive_share.value==Decimal("0.66666667") and result.negative_share.value==Decimal("0.75000000")


def test_phase_vii_attribution_phase_viii_snapshot_and_prompt32_handoff():
    target=engine();ingest_values(target,["1","-1","2","0"]);base=query();global_snapshot=target.calculate(base);segments=target.segment(base,"safety");rolling=target.rolling(base,(2,))
    phase8=target.phase_viii_snapshot(global_snapshot,segments,rolling,"PHASE-VII-AUTHORITATIVE")
    handoff=target.prompt32_handoff(phase8)
    assert phase8.phase_vii_safety_snapshot_id=="PHASE-VII-AUTHORITATIVE"
    assert handoff.phase_viii_snapshot_id==phase8.snapshot_id


def test_reconciliation_detects_tampering_without_mutating_upstream():
    target=engine();ingest_values(target,["1","-1"]);snap=target.calculate(query())
    assert target.reconcile(snap)==(ReconciliationOutcome.CONSISTENT,())
    corrupt=replace(snap,valid_observation_count=99)
    assert target.reconcile(corrupt)[0] is ReconciliationOutcome.FAILED_CLOSED
    assert len(target.observations)==2


def test_recovery_restart_and_replay_are_deterministic():
    target=engine();ingest_values(target,["1","-1","2"]);snap=target.calculate(query(),recovery_epoch=3);fingerprint=target.replay_fingerprint();state=target.recovery_state(3)
    restored=engine();assert restored.restore(state,3)
    assert restored.replay_fingerprint()==fingerprint and restored.snapshots[snap.snapshot_id]==snap
    invalid=engine();assert not invalid.restore(replace(state,recovery_epoch=4),3) and invalid.recovery_restricted


def test_cache_is_bounded_and_isolated_by_provenance():
    target=engine(AnalyticsConfiguration(limited_sample=1,adequate_sample=2,strong_sample=3,rolling_minimum=1,maximum_cache_entries=2));ingest_values(target,["1"])
    for i in range(3):target.calculate(query(filters={"session":f"S{i}"}))
    assert len(target.cache)==2
    with pytest.raises(ValueError):target.calculate(query(dataset_fingerprint=""))


def test_incremental_and_full_recomputation_are_equivalent():
    target=engine();ingest_values(target,["1","-2","3","0"]);q=query();incremental=target.calculate(q);full=target.calculate(q,full_recompute=True)
    assert incremental.summary==full.summary and incremental.source_fingerprint==full.source_fingerprint


def test_audit_trace_and_neutral_safety_boundary():
    audit=InMemoryAuditSink();target=engine(audit=audit);ingest_values(target,["1","-1"]);snap=target.calculate(query())
    assert snap.decision_trace.evaluations and any(x[0]=="analytics_snapshot_published" for x in audit.events)
    forbidden={"broker_login","account_balance","place_order","fill_order","open_position","close_position","set_leverage","calculate_margin","monetary_pnl","financial_drawdown"}
    assert forbidden.isdisjoint(set(dir(ResearchPerformanceAnalyticsEngine)))
