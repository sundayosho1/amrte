from time import perf_counter

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.protection_runtime import (
    ResearchProtectionRuntime,
    ResearchProtectionRuntimeConfiguration,
)
from Tests.Unit.test_research_protection_runtime import healthy_evidence, p44_snapshot, unrestricted_p44


def test_prompt45_research_protection_runtime_is_bounded_under_synthetic_load():
    source = unrestricted_p44(p44_snapshot())
    runtime = ResearchProtectionRuntime(
        ResearchProtectionRuntimeConfiguration(
            maximum_snapshots=5,
            maximum_restrictions=12,
            maximum_cooldowns=5,
        ),
        clock=FixedClock(source.as_of_timestamp_utc),
        audit=InMemoryAuditSink(),
    )

    started = perf_counter()
    for index in range(20):
        snapshot = source if index == 0 else unrestricted_p44(p44_snapshot())
        evidence = healthy_evidence(
            snapshot,
            reliability_stage="WATCH" if index % 3 == 0 else "NORMAL",
            strategy_health="DEGRADED" if index % 5 == 0 else "HEALTHY",
        )
        runtime.assess(snapshot, evidence)
    elapsed = perf_counter() - started

    assert runtime.metrics["p44_snapshots_received"] == 20
    assert runtime.metrics["protection_assessments"] >= 1
    assert len(runtime.snapshots) <= 5
    assert len(runtime.restrictions) <= 12
    assert len(runtime.cooldowns) <= 5
    assert elapsed < 5.0
