from datetime import datetime, timedelta, timezone
from time import perf_counter

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.observation import InstrumentIdentity, ObservationProvenance, SourceIdentity, build_canonical_dataset, create_canonical_bar
from amrte.research.controlled_experimentation import ConfigurationStatus, VERSIONED_RESEARCH_CONFIGURATION_SCHEMA_VERSION, VersionedResearchConfiguration, versioned_research_configuration_schema_identity
from amrte.research.forward_runtime import ForwardResearchRuntime


def test_prompt51_forward_research_runtime_synthetic_load():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    instrument = InstrumentIdentity("FICTIONAL_P51_LOAD", "SYN_P51_LOAD")
    source = SourceIdentity("SRC-P51-LOAD", "CSV_BAR", "1.0", "P51_LOAD")
    observations = tuple(
        create_canonical_bar(
            instrument=instrument,
            source=source,
            timeframe="M15",
            period_start=start + timedelta(minutes=15 * index),
            period_end=start + timedelta(minutes=15 * (index + 1)),
            available_at=start + timedelta(minutes=15 * (index + 1)),
            received_at=start + timedelta(minutes=15 * (index + 1), seconds=1),
            open="100",
            high="103",
            low="99",
            close=str(100 + (index % 5)),
            volume="10",
            volume_kind="TICK_VOLUME",
            sequence=index + 1,
            provenance=ObservationProvenance(
                source_record_locator=f"row:{index}",
                raw_record_fingerprint=f"raw-{index}",
                transformations=("csv_field_mapping",),
            ),
        )
        for index in range(500)
    )
    dataset = build_canonical_dataset(observations)
    config = VersionedResearchConfiguration(
        "P51-LOAD-CONFIG",
        VERSIONED_RESEARCH_CONFIGURATION_SCHEMA_VERSION,
        versioned_research_configuration_schema_identity(),
        "P51-LOAD@research-v1",
        "BASE",
        "EXP",
        "PROMOTION",
        "CAND",
        {"strategies.s1_trend_pullback.minimum_adx": 21.0},
        {"strategies.s1_trend_pullback.minimum_adx": 1.0},
        "P51-LOAD-FP",
        start,
        ("EXP", "RESULT", "PROMOTION"),
        ConfigurationStatus.APPROVED_RESEARCH.value,
        ("BASE", "P51-LOAD-CONFIG"),
        "P51-LOAD-AUTHORITY",
    )
    runtime = ForwardResearchRuntime(clock=FixedClock(start), audit=InMemoryAuditSink())
    session = runtime.start_session(config, dataset, historical_cutoff_utc=start - timedelta(seconds=1), as_of=start)

    began = perf_counter()
    for item in observations:
        runtime.ingest_observation(session.session_id, item, dataset=dataset, logical_time=item.available_at)
    drift = runtime.detect_drift(session.session_id, baseline_mean="102.0")
    elapsed = perf_counter() - began

    assert len(runtime.envelopes) == 500
    assert len(runtime.decisions) > 450
    assert drift.sample_count == len(runtime.decisions)
    assert elapsed < 3.0
