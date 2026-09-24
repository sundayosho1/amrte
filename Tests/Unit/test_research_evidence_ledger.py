from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from amrte.core.clock import FixedClock
from amrte.core.identity import deterministic_id
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.decision_runtime import MasterResearchDecisionOrchestrator, ResearchProcessingContext, stage_records_for_protection_snapshot
from amrte.research.evidence_ledger import (
    EvidenceRecordType,
    LedgerCommitAcceptance,
    LedgerConflictError,
    LedgerValidationError,
    LedgerVerificationStatus,
    ReplayVerificationStatus,
    ResearchDecisionEvidenceLedger,
    ResearchEvidenceReleaseProvenance,
    canonical_json,
    ledger_integrity_state_schema_identity,
    replay_verification_evidence_schema_identity,
    research_decision_evidence_bundle_schema_identity,
    research_decision_evidence_record_schema_identity,
    research_evidence_genesis_identity,
)
from Tests.Unit.test_events import NOW
from Tests.Unit.test_research_decision_runtime import DATASET_FINGERPRINT, DATASET_ID, context_for, protected_snapshot


def release(pipeline="P46_MASTER_RESEARCH_DECISION_RUNTIME"):
    return ResearchEvidenceReleaseProvenance(
        "0.27.0",
        "1be7ff885d3a40081819cd427b177631194b66f3",
        "SOURCE",
        "DEPS",
        "RESOLVED",
        pipeline,
    )


def ledger(tmp_path, *, failure_stage=None, pipeline="P46_MASTER_RESEARCH_DECISION_RUNTIME", max_recent=8):
    return ResearchDecisionEvidenceLedger(
        root=tmp_path / "ledger",
        clock=FixedClock(NOW),
        audit=InMemoryAuditSink(),
        release_provenance=release(pipeline),
        max_recent_records=max_recent,
        failure_stage=failure_stage,
    )


def p46_result(index=0, *, snapshot=None, runtime=None):
    snapshot = snapshot or protected_snapshot()
    records = list(stage_records_for_protection_snapshot(snapshot, dataset_id=DATASET_ID, dataset_fingerprint=DATASET_FINGERPRINT))
    if index:
        records = [replace(item, evidence_fingerprint=f"{item.evidence_fingerprint}-{index}") for item in records]
    context = ResearchProcessingContext.create(
        created_at_utc=NOW + timedelta(seconds=index),
        dataset_id=DATASET_ID,
        dataset_fingerprint=DATASET_FINGERPRINT,
        knowledge_cutoff_utc=snapshot.knowledge_cutoff_utc,
        configuration_identity=snapshot.configuration_identity,
        recovery_epoch=snapshot.recovery_epoch,
        p45_protection_snapshot_id=snapshot.protection_snapshot_id,
        stage_records=tuple(records),
    )
    runtime = runtime or MasterResearchDecisionOrchestrator(clock=FixedClock(NOW), audit=InMemoryAuditSink(), maximum_decisions=2)
    return runtime.decide(context, snapshot)


def commit_one(target, index=0, *, snapshot=None, runtime=None):
    result = p46_result(index, snapshot=snapshot, runtime=runtime)
    return target.commit_decision_evidence(result.context, result.decision, result.trace)


def record_file(target, record):
    return target.records_dir / f"{record.ledger_sequence:012d}-{record.evidence_record_id}.json"


def mutate_json(path, mutator):
    raw = json.loads(path.read_text(encoding="utf-8"))
    mutator(raw)
    path.write_text(canonical_json(raw) + "\n", encoding="utf-8")


def test_schema_policy_and_genesis_identities_are_deterministic():
    assert research_decision_evidence_record_schema_identity() == research_decision_evidence_record_schema_identity()
    assert research_decision_evidence_bundle_schema_identity() == research_decision_evidence_bundle_schema_identity()
    assert ledger_integrity_state_schema_identity() == ledger_integrity_state_schema_identity()
    assert replay_verification_evidence_schema_identity() == replay_verification_evidence_schema_identity()
    assert research_evidence_genesis_identity() == research_evidence_genesis_identity()
    assert len(
        {
            research_decision_evidence_record_schema_identity(),
            research_decision_evidence_bundle_schema_identity(),
            ledger_integrity_state_schema_identity(),
            replay_verification_evidence_schema_identity(),
        }
    ) == 4


def test_append_only_record_is_deterministic_immutable_and_hash_chained(tmp_path):
    target = ledger(tmp_path)
    committed = commit_one(target)
    record = committed.record

    assert committed.acceptance is LedgerCommitAcceptance.COMMITTED
    assert record.ledger_sequence == 1
    assert record.previous_record_hash == target.genesis_identity
    assert record.record_hash == target.diagnostics()["ledger_head"]
    assert record.completeness == "COMPLETE"
    assert target.verify_ledger().status is LedgerVerificationStatus.VERIFIED
    with pytest.raises(FrozenInstanceError):
        record.final_classification = "MUTATED"


def test_duplicate_ingestion_returns_existing_without_append(tmp_path):
    target = ledger(tmp_path)
    result = p46_result()
    first = target.commit_decision_evidence(result.context, result.decision, result.trace)
    duplicate = target.commit_decision_evidence(result.context, result.decision, result.trace)

    assert duplicate.acceptance is LedgerCommitAcceptance.DUPLICATE
    assert duplicate.record.evidence_record_id == first.record.evidence_record_id
    assert target.diagnostics()["ledger_record_count"] == 1
    assert target.metrics["duplicate_count"] == 1


def test_invalid_trace_decision_context_and_configuration_fail_closed(tmp_path):
    result = p46_result()
    target = ledger(tmp_path)
    bad_trace = replace(result.trace, trace_id="bad")
    with pytest.raises(LedgerValidationError):
        target.commit_decision_evidence(result.context, result.decision, bad_trace)

    other = p46_result(1)
    with pytest.raises(LedgerValidationError):
        target.commit_decision_evidence(result.context, other.decision, result.trace)

    bad_decision = replace(result.decision, configuration_identity="other")
    with pytest.raises(LedgerValidationError):
        target.commit_decision_evidence(result.context, bad_decision, result.trace)


def test_same_decision_different_trace_conflict_fails_closed(tmp_path):
    result = p46_result()
    target = ledger(tmp_path)
    target.commit_decision_evidence(result.context, result.decision, result.trace)
    new_fingerprint = result.trace.trace_fingerprint + "-changed"
    conflicting_trace = replace(
        result.trace,
        trace_fingerprint=new_fingerprint,
        trace_id=deterministic_id("p46_research_decision_trace", new_fingerprint),
    )

    with pytest.raises(LedgerConflictError):
        target.commit_decision_evidence(result.context, result.decision, conflicting_trace)


@pytest.mark.parametrize(
    "mutator,reason",
    [
        (lambda raw: raw.__setitem__("reason_codes", ["MUTATED"]), "P47_EVIDENCE_FINGERPRINT_MISMATCH"),
        (lambda raw: raw.__setitem__("previous_record_hash", "bad"), "P47_PREVIOUS_HASH_MISMATCH"),
        (lambda raw: raw.__setitem__("ledger_sequence", 99), "P47_RECORD_DELETION_DETECTED"),
        (lambda raw: raw.__setitem__("record_hash", "bad"), "P47_RECORD_HASH_MISMATCH"),
    ],
)
def test_content_previous_hash_sequence_and_record_hash_mutation_are_detected(tmp_path, mutator, reason):
    target = ledger(tmp_path)
    committed = commit_one(target)
    mutate_json(record_file(target, committed.record), mutator)
    result = target.verify_ledger()

    assert result.status is LedgerVerificationStatus.INVALID
    assert reason in result.reason_codes
    assert target.component_health(None).name == "RESTRICTED"


def test_deletion_insertion_duplicate_sequence_and_head_mismatch_are_detected(tmp_path):
    target = ledger(tmp_path)
    first = commit_one(target, 1)
    second = commit_one(target, 2)

    record_file(target, first.record).unlink()
    deleted = target.verify_ledger()
    assert "P47_RECORD_DELETION_DETECTED" in deleted.reason_codes

    target = ledger(tmp_path / "fresh")
    first = commit_one(target, 1)
    extra = record_file(target, first.record).with_name("000000000002-extra.json")
    extra.write_text(record_file(target, first.record).read_text(encoding="utf-8"), encoding="utf-8")
    mutate_json(extra, lambda raw: raw.__setitem__("ledger_sequence", 2))
    inserted = target.verify_ledger()
    assert "P47_UNCOMMITTED_RECORD_PRESENT" in inserted.reason_codes

    target = ledger(tmp_path / "dup")
    first = commit_one(target, 1)
    second = commit_one(target, 2)
    mutate_json(record_file(target, second.record), lambda raw: raw.__setitem__("ledger_sequence", 1))
    duplicate = target.verify_ledger()
    assert "P47_SEQUENCE_CONFLICT" in duplicate.reason_codes

    target = ledger(tmp_path / "head")
    commit_one(target, 1)
    mutate_json(target.head_path, lambda raw: raw.__setitem__("ledger_head", "bad"))
    head = target.verify_ledger()
    assert "P47_HEAD_MISMATCH" in head.reason_codes


def test_partial_write_recovery_quarantines_uncommitted_or_temporary_records(tmp_path):
    result = p46_result()
    failing = ledger(tmp_path / "partial", failure_stage="after_record_write")
    with pytest.raises(OSError):
        failing.commit_decision_evidence(result.context, result.decision, result.trace)
    recovered = ledger(tmp_path / "partial")
    recovery = recovered.recover()
    assert recovery.status is LedgerVerificationStatus.VERIFIED
    assert recovered.diagnostics()["ledger_record_count"] == 0

    failing_temp = ledger(tmp_path / "temp", failure_stage="during_record_write")
    with pytest.raises(OSError):
        failing_temp.commit_decision_evidence(result.context, result.decision, result.trace)
    recovered_temp = ledger(tmp_path / "temp")
    assert recovered_temp.recover().status is LedgerVerificationStatus.VERIFIED

    committed_then_failed = ledger(tmp_path / "after-head", failure_stage="after_head_update")
    with pytest.raises(OSError):
        committed_then_failed.commit_decision_evidence(result.context, result.decision, result.trace)
    restored = ledger(tmp_path / "after-head")
    assert restored.recover().status is LedgerVerificationStatus.VERIFIED
    assert restored.diagnostics()["ledger_record_count"] == 1


def test_restart_verification_and_append_after_restart(tmp_path):
    first = ledger(tmp_path)
    commit_one(first, 1)
    assert first.verify_ledger().status is LedgerVerificationStatus.VERIFIED

    restarted = ledger(tmp_path)
    assert restarted.recover().status is LedgerVerificationStatus.VERIFIED
    commit_one(restarted, 2)
    assert restarted.verify_ledger().status is LedgerVerificationStatus.VERIFIED
    assert restarted.diagnostics()["ledger_record_count"] == 2


def test_reconstruction_by_record_decision_and_trace_is_read_only(tmp_path):
    target = ledger(tmp_path)
    committed = commit_one(target)
    by_record = target.reconstruct_by_record_id(committed.record.evidence_record_id)
    by_decision = target.reconstruct_by_decision_id(committed.record.decision_id)
    by_trace = target.reconstruct_by_trace_id(committed.record.trace_id)

    assert by_record.record.evidence_record_id == by_decision.record.evidence_record_id == by_trace.record.evidence_record_id
    assert by_record.reconstruction_recomputed_decision is False
    assert by_record.integrity.status is LedgerVerificationStatus.VERIFIED


def test_replay_match_divergence_and_cross_version_are_recorded_without_rewriting_original(tmp_path):
    target = ledger(tmp_path)
    result = p46_result()
    committed = target.commit_decision_evidence(result.context, result.decision, result.trace)
    original_hash = committed.record.record_hash

    match = target.verify_replay(committed.record.evidence_record_id, result.decision, result.trace)
    assert match.status == ReplayVerificationStatus.MATCH.value

    diverged_decision = replace(result.decision, decision_fingerprint="different")
    divergence = target.verify_replay(committed.record.evidence_record_id, diverged_decision, result.trace)
    assert divergence.status == ReplayVerificationStatus.DIVERGED.value

    cross = target.verify_replay(committed.record.evidence_record_id, result.decision, result.trace, pipeline_identity="P47_CROSS_VERSION")
    assert cross.status == ReplayVerificationStatus.CROSS_VERSION_REPLAY.value

    original = target.get_record(committed.record.evidence_record_id)
    assert original.record_hash == original_hash
    assert target.diagnostics()["ledger_record_count"] == 4


def test_correction_supersession_and_invalidation_preserve_original(tmp_path):
    target = ledger(tmp_path)
    original = commit_one(target).record
    correction = target.append_correction(original.evidence_record_id, "P47_CORRECTION_TEST").record
    supersession = target.append_supersession(original.evidence_record_id, "P47_SUPERSESSION_TEST").record
    invalidation = target.append_invalidation(original.evidence_record_id, "P47_INVALIDATION_TEST").record

    assert correction.correction_of_record_id == original.evidence_record_id
    assert supersession.supersedes_record_id == original.evidence_record_id
    assert invalidation.invalidates_record_id == original.evidence_record_id
    assert target.get_record(original.evidence_record_id).record_hash == original.record_hash


def test_runtime_eviction_does_not_destroy_ledger_history(tmp_path):
    snapshot = protected_snapshot()
    p46 = MasterResearchDecisionOrchestrator(clock=FixedClock(NOW), audit=InMemoryAuditSink(), maximum_decisions=1)
    target = ledger(tmp_path)
    committed_ids = []
    for index in range(6):
        result = p46_result(index, snapshot=snapshot, runtime=p46)
        committed_ids.append(target.commit_decision_evidence(result.context, result.decision, result.trace).record.evidence_record_id)

    assert len(p46.decisions) == 1
    assert target.diagnostics()["ledger_record_count"] == 6
    for record_id in committed_ids:
        assert target.reconstruct_by_record_id(record_id).record.evidence_record_id == record_id


def test_no_action_rejected_restricted_eligible_and_failed_evidence_states(tmp_path):
    target = ledger(tmp_path)
    eligible_result = p46_result(1)
    eligible = target.commit_decision_evidence(eligible_result.context, eligible_result.decision, eligible_result.trace).record
    no_action_snapshot = protected_snapshot()
    no_action_records = tuple(
        replace(item, stage_decision="NO_ACTION") if item.stage == "P44_PORTFOLIO_SNAPSHOT" else item
        for item in stage_records_for_protection_snapshot(no_action_snapshot, dataset_id=DATASET_ID, dataset_fingerprint=DATASET_FINGERPRINT)
    )
    no_action_context = context_for(no_action_snapshot, no_action_records)
    no_action_result = MasterResearchDecisionOrchestrator(clock=FixedClock(NOW), audit=InMemoryAuditSink()).decide(no_action_context, no_action_snapshot)
    restricted_result = p46_result(2, snapshot=protected_snapshot(reliability_stage="WATCH"))
    rejected_result = p46_result(3, snapshot=protected_snapshot(system_safety_state="EMERGENCY_STOP"))

    failed_snapshot = protected_snapshot()
    failed_records = tuple(item for item in stage_records_for_protection_snapshot(failed_snapshot, dataset_id=DATASET_ID, dataset_fingerprint=DATASET_FINGERPRINT) if item.stage != "P40_QUALITY_TRUST")
    failed_context = context_for(failed_snapshot, failed_records)
    failed_result = MasterResearchDecisionOrchestrator(clock=FixedClock(NOW), audit=InMemoryAuditSink()).decide(failed_context, failed_snapshot)

    for result in (no_action_result, restricted_result, rejected_result, failed_result):
        target.commit_decision_evidence(result.context, result.decision, result.trace)

    classifications = {record.final_classification: record for record in target.query(limit=10)}
    assert classifications["ELIGIBLE_RESEARCH"].evidence_record_id == eligible.evidence_record_id
    assert classifications["NO_ACTION"].completeness == "COMPLETE"
    assert classifications["RESTRICTED"].completeness == "COMPLETE"
    assert classifications["REJECTED"].completeness == "COMPLETE"
    assert classifications["FAILED"].completeness == "INCOMPLETE"
    assert "P47_FAILED_DECISION_AVAILABLE_EVIDENCE_ONLY" in classifications["FAILED"].completeness_reasons


def test_bounded_query_pagination_and_memory_cache(tmp_path):
    target = ledger(tmp_path, max_recent=3)
    snapshot = protected_snapshot()
    for index in range(10):
        commit_one(target, index + 1, snapshot=snapshot)

    first_page = target.query(offset=0, limit=4)
    second_page = target.query(offset=4, limit=4)
    assert [item.ledger_sequence for item in first_page] == [1, 2, 3, 4]
    assert [item.ledger_sequence for item in second_page] == [5, 6, 7, 8]
    assert target.diagnostics()["memory"]["recent_record_cache_size"] <= 3


def test_scale_append_verify_and_reconstruct_remain_bounded(tmp_path):
    target = ledger(tmp_path, max_recent=5)
    snapshot = protected_snapshot()
    for index in range(120):
        commit_one(target, index + 1, snapshot=snapshot)
    verification = target.verify_ledger()
    latest = target.query(sequence_start=120, sequence_end=120)[0]
    bundle = target.reconstruct_by_record_id(latest.evidence_record_id)

    assert verification.status is LedgerVerificationStatus.VERIFIED
    assert verification.checked_count == 120
    assert bundle.record.ledger_sequence == 120
    assert target.diagnostics()["memory"]["recent_record_cache_size"] <= 5


def test_windows_safe_relative_paths_and_financial_execution_boundary(tmp_path):
    target = ledger(tmp_path)
    diagnostics = target.diagnostics()
    assert str(target.root).startswith(str(tmp_path))
    assert diagnostics["financial_execution"] == "NONE"
    assert not hasattr(target, "submit_order")
    assert not hasattr(target, "open_position")
    assert not hasattr(target, "allocate_capital")
