from time import perf_counter

from Tests.Unit.test_research_decision_runtime import protected_snapshot
from Tests.Unit.test_research_evidence_ledger import commit_one, ledger


def test_prompt47_research_evidence_ledger_scales_beyond_p46_runtime_retention(tmp_path):
    target = ledger(tmp_path, max_recent=8)
    snapshot = protected_snapshot()

    started = perf_counter()
    for index in range(150):
        commit_one(target, index + 1, snapshot=snapshot)
    append_elapsed = perf_counter() - started

    verify_started = perf_counter()
    verification = target.verify_ledger()
    verify_elapsed = perf_counter() - verify_started

    reconstruct_started = perf_counter()
    latest = target.query(sequence_start=150, sequence_end=150)[0]
    bundle = target.reconstruct_by_record_id(latest.evidence_record_id)
    reconstruct_elapsed = perf_counter() - reconstruct_started

    assert verification.status.value == "VERIFIED"
    assert verification.checked_count == 150
    assert target.diagnostics()["ledger_record_count"] == 150
    assert target.diagnostics()["memory"]["recent_record_cache_size"] <= 8
    assert bundle.record.ledger_sequence == 150
    assert append_elapsed < 30.0
    assert verify_elapsed < 5.0
    assert reconstruct_elapsed < 2.0
