from dataclasses import replace
from time import perf_counter

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.decision_runtime import (
    MasterResearchDecisionOrchestrator,
    ResearchProcessingContext,
    stage_records_for_protection_snapshot,
)
from Tests.Unit.test_events import NOW
from Tests.Unit.test_research_decision_runtime import DATASET_FINGERPRINT, DATASET_ID, protected_snapshot


def test_prompt46_research_decision_runtime_is_bounded_under_synthetic_load():
    source = protected_snapshot()
    runtime = MasterResearchDecisionOrchestrator(
        clock=FixedClock(NOW),
        audit=InMemoryAuditSink(),
        maximum_decisions=5,
    )

    started = perf_counter()
    for index in range(20):
        snapshot = source
        records = tuple(
            replace(item, evidence_fingerprint=f"{item.evidence_fingerprint}-{index}")
            for item in stage_records_for_protection_snapshot(
                snapshot,
                dataset_id=DATASET_ID,
                dataset_fingerprint=DATASET_FINGERPRINT,
            )
        )
        context = ResearchProcessingContext.create(
            created_at_utc=NOW,
            dataset_id=DATASET_ID,
            dataset_fingerprint=DATASET_FINGERPRINT,
            knowledge_cutoff_utc=snapshot.knowledge_cutoff_utc,
            configuration_identity=snapshot.configuration_identity,
            recovery_epoch=snapshot.recovery_epoch,
            p45_protection_snapshot_id=snapshot.protection_snapshot_id,
            stage_records=records,
        )
        runtime.decide(context, snapshot)
    elapsed = perf_counter() - started

    assert runtime.metrics["contexts_received"] == 20
    assert runtime.metrics["decisions_published"] == 20
    assert len(runtime.contexts) <= 5
    assert len(runtime.decisions) <= 5
    assert len(runtime.traces) <= 5
    assert len(runtime.ledger_entries) <= 5
    assert elapsed < 5.0
