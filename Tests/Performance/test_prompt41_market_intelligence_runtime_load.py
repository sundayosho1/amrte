from time import perf_counter

from Tests.Unit.test_market_intelligence_runtime import _runtime, _trusted_pairs
from amrte.market.intelligence_runtime import RuntimeAcceptance


def test_prompt41_bounded_trusted_intelligence_soak():
    dataset, pairs = _trusted_pairs(180)
    runtime = _runtime()

    began = perf_counter()
    results = [
        runtime.process_trusted_observation(trusted, observation, dataset=dataset)
        for trusted, observation in pairs
    ]
    elapsed = perf_counter() - began

    assert pairs
    assert all(result.acceptance is RuntimeAcceptance.ACCEPTED for result in results)
    assert runtime.diagnostics()["snapshot_count"] == len(results)
    assert len(runtime.snapshots) <= runtime.configuration.maximum_snapshots
    assert elapsed < 5.0
