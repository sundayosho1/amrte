from decimal import Decimal

from Tests.Unit.test_research_outcome_performance import evidence_record, future_path, runtime


def test_prompt48_outcome_attribution_load_is_bounded(tmp_path):
    target, p47 = runtime(tmp_path, max_items=256)
    for index in range(80):
        record = evidence_record(p47, index + 1)
        observations = future_path(record, (101 + index % 3, 102 + index % 3, 103 + index % 3))
        window = target.update_window(record, observations, evaluation_time=observations[-1].received_at)
        target.attribute(record, window, observations, historical_reference_value=Decimal("100"))

    snapshot = target.publish_snapshot()
    diagnostics = target.diagnostics()

    assert snapshot.mature_outcome_count == 80
    assert snapshot.decision_count == 80
    assert diagnostics["memory"]["windows"] <= 256
    assert diagnostics["memory"]["attributions"] <= 256
    assert diagnostics["financial_execution"] == "NONE"
    assert target.incremental_equals_full_rebuild()
