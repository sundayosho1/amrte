from dataclasses import replace

from Tests.Unit.test_research_improvement_intelligence import analyze, p48_evidence, runtime


def test_prompt49_improvement_analysis_load_is_bounded(tmp_path):
    target = runtime(tmp_path, max_items=256)

    def mutate(i, attr):
        return replace(
            attr,
            strategy_id="S1" if i % 4 in {0, 1} else "S2",
            strategy_version="1",
            regime_at_decision="RANGE" if i % 3 == 0 else "TREND",
            session_at_decision="ASIA" if i % 5 == 0 else "US",
            score_band="HIGH" if i % 2 == 0 else "LOW",
        )

    values = tuple(-5 if i % 4 in {0, 1} else 5 for i in range(80))
    snapshot, attributions = p48_evidence(tmp_path, values, mutate=mutate)
    improvement = analyze(target, snapshot, attributions)
    diagnostics = target.diagnostics()

    assert improvement.candidate_count > 0
    assert diagnostics["memory"]["candidates"] <= 256
    assert diagnostics["memory"]["clusters"] <= 256
    assert diagnostics["financial_execution"] == "NONE"
    assert target.incremental_equals_full_rebuild()
