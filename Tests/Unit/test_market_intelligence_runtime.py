from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.events import (
    DeterministicEventProvider,
    EconomicEvent,
    EventCategory,
    EventImportance,
    EventWindowPolicy,
    NewsRiskConfiguration,
    NewsRiskEngine,
    TimeZoneService,
)
from amrte.market.intelligence_runtime import (
    MarketIntelligenceRuntime,
    RuntimeAcceptance,
    market_intelligence_schema_identity,
)
from amrte.market.observation import (
    InstrumentIdentity,
    ObservationProvenance,
    SourceIdentity,
    build_canonical_dataset,
    create_canonical_bar,
)
from amrte.market.regime import RegimeConfiguration, RegimeEngine
from amrte.market.structure import MarketStructureEngine, StructureConfiguration
from amrte.research.data_quality_runtime import DataQualityTrustRuntime, TrustStatus


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)


def _source(name: str = "OFFLINE-P41") -> SourceIdentity:
    return SourceIdentity(name, "CSV_BAR", "1.0", "P41_FIXTURE", "1")


def _instrument(name: str = "FICTIONAL_ALPHA") -> InstrumentIdentity:
    return InstrumentIdentity(name, f"SYN_{name}")


def _observation(index: int, *, instrument_id: str = "FICTIONAL_ALPHA", source_id: str = "OFFLINE-P41"):
    start = START + timedelta(minutes=15 * index)
    close = [100, 103, 99, 104, 98, 105, 101, 106, 100, 107, 102, 108, 103, 109, 104, 110][index % 16]
    return create_canonical_bar(
        instrument=_instrument(instrument_id),
        source=_source(source_id),
        timeframe="M15",
        period_start=start,
        period_end=start + timedelta(minutes=15),
        available_at=start + timedelta(minutes=15),
        received_at=start + timedelta(minutes=15, seconds=1),
        open=close - 0.25,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=index + 1,
        volume_kind="TICK_VOLUME",
        sequence=index + 1,
        provenance=ObservationProvenance(
            source_record_locator=f"row:{index}",
            raw_record_fingerprint=f"raw-{instrument_id}-{index}",
            transformations=("csv_field_mapping",),
        ),
    )


def _trusted_pairs(count: int = 14, *, instrument_id: str = "FICTIONAL_ALPHA", source_id: str = "OFFLINE-P41"):
    observations = tuple(_observation(index, instrument_id=instrument_id, source_id=source_id) for index in range(count))
    dataset = build_canonical_dataset(observations)
    quality_runtime = DataQualityTrustRuntime()
    pairs = []
    for item in observations:
        trusted = quality_runtime.ingest_observation(item, dataset=dataset, logical_time=item.available_at)
        if trusted.trust_status in (TrustStatus.TRUSTED, TrustStatus.TRUSTED_WITH_WARNINGS) and trusted.authoritative_effect_applied:
            pairs.append((trusted, item))
    return dataset, tuple(pairs)


def _runtime(*, news_engine=None) -> MarketIntelligenceRuntime:
    clock = FixedClock(START)
    audit = InMemoryAuditSink()
    return MarketIntelligenceRuntime(
        clock=clock,
        audit=audit,
        structure_engine=MarketStructureEngine(
            clock,
            audit,
            StructureConfiguration(left_bars=1, right_bars=1, minimum_structural_evidence=1, consolidation_window=3),
        ),
        regime_engine=RegimeEngine(
            clock,
            audit,
            RegimeConfiguration(confirmation_observations=1, minimum_classification_margin=0, cooldown_observations=0),
        ),
        news_engine=news_engine,
    )


def test_schema_identity_is_stable_and_distinct_from_upstream_contracts():
    assert market_intelligence_schema_identity() == market_intelligence_schema_identity()


def test_trusted_observation_boundary_accepts_only_p40_trusted_evidence():
    dataset, pairs = _trusted_pairs()
    trusted, observation = pairs[-1]
    runtime = _runtime()

    accepted = runtime.process_trusted_observation(trusted, observation, dataset=dataset)
    assert accepted.acceptance is RuntimeAcceptance.ACCEPTED
    assert accepted.snapshot is not None
    assert accepted.snapshot.trusted_observation_id == trusted.trusted_observation_id
    assert accepted.snapshot.observation_fingerprint == observation.observation_fingerprint
    assert accepted.snapshot.financial_execution == "NONE"

    restricted = replace(trusted, trust_status=TrustStatus.RESTRICTED)
    blocked = _runtime().process_trusted_observation(restricted, observation, dataset=dataset)
    assert blocked.acceptance is RuntimeAcceptance.BLOCKED
    assert any("RESTRICTED" in reason for reason in blocked.reason_codes)

    tampered = replace(observation, observation_fingerprint="tampered")
    mismatch = _runtime().process_trusted_observation(trusted, tampered, dataset=dataset)
    assert mismatch.acceptance is RuntimeAcceptance.BLOCKED
    assert any("FINGERPRINT" in reason for reason in mismatch.reason_codes)

    assert not hasattr(runtime, "process_raw_bar")
    assert not hasattr(runtime, "process_raw_observation")


def test_point_in_time_snapshot_does_not_change_after_future_observations_arrive():
    dataset, pairs = _trusted_pairs()
    runtime = _runtime()

    first = runtime.process_trusted_observation(*pairs[0], dataset=dataset).snapshot
    first_fingerprint = first.snapshot_fingerprint
    first_bar_ids = tuple(bar.bar_id for bar in first.market_intelligence.market_data.context_bars)

    for trusted, observation in pairs[1:]:
        runtime.process_trusted_observation(trusted, observation, dataset=dataset)

    assert first.snapshot_fingerprint == first_fingerprint
    assert tuple(bar.bar_id for bar in first.market_intelligence.market_data.context_bars) == first_bar_ids
    assert all(
        value.as_of_timestamp <= first.knowledge_cutoff_utc
        for role in first.market_intelligence.features.features.values()
        for value in role.values()
    )


def test_event_visibility_respects_first_known_time():
    event = EconomicEvent(
        "evt-1",
        "evt-1-v1",
        "provider-1",
        "High impact fixture",
        EventCategory.EMPLOYMENT,
        "US",
        ("USD",),
        START + timedelta(hours=2, minutes=30),
        START + timedelta(hours=1, minutes=45),
        START + timedelta(hours=1, minutes=45),
        EventImportance.HIGH,
    )
    config = NewsRiskConfiguration(
        windows={importance: EventWindowPolicy(180, 30, 30, 90, 30) for importance in EventImportance},
        instrument_dimensions={"FICTIONAL_ALPHA": ("USD",)},
    )
    provider = DeterministicEventProvider(
        (event,),
        coverage_start_utc=START - timedelta(days=1),
        coverage_end_utc=START + timedelta(days=1),
        imported_at_utc=START,
    )
    clock = FixedClock(START)
    audit = InMemoryAuditSink()
    news = NewsRiskEngine(clock, audit, TimeZoneService(), provider, config)
    runtime = _runtime(news_engine=news)
    dataset, pairs = _trusted_pairs()

    before = runtime.process_trusted_observation(*pairs[0], dataset=dataset).snapshot
    after = runtime.process_trusted_observation(*pairs[1], dataset=dataset).snapshot

    assert before.knowledge_cutoff_utc < event.first_known_at_utc
    assert before.market_intelligence.news_risk.relevant_events == ()
    assert after.knowledge_cutoff_utc >= event.first_known_at_utc
    assert tuple(item.logical_event_id for item in after.market_intelligence.news_risk.relevant_events) == ("evt-1",)


def test_scope_isolation_and_recovery_equivalence():
    alpha_dataset, alpha_pairs = _trusted_pairs(instrument_id="FICTIONAL_ALPHA", source_id="SRC-A")
    beta_dataset, beta_pairs = _trusted_pairs(instrument_id="FICTIONAL_BETA", source_id="SRC-B")
    runtime = _runtime()

    alpha = runtime.process_trusted_observation(*alpha_pairs[-1], dataset=alpha_dataset).snapshot
    beta = runtime.process_trusted_observation(*beta_pairs[-1], dataset=beta_dataset).snapshot
    assert alpha.instrument_id == "FICTIONAL_ALPHA"
    assert beta.instrument_id == "FICTIONAL_BETA"
    assert runtime.diagnostics()["scope_count"] == 2

    dataset, pairs = _trusted_pairs()
    continuous = _runtime()
    restored = _runtime()
    for pair in pairs[:4]:
        continuous.process_trusted_observation(*pair, dataset=dataset)
    state = continuous.recovery_state(0)
    assert restored.restore(state, 0)
    assert restored.reconcile(0) == ()

    continuous_result = continuous.process_trusted_observation(*pairs[4], dataset=dataset).snapshot
    restored_result = restored.process_trusted_observation(*pairs[4], dataset=dataset).snapshot
    assert restored_result.unified_snapshot_id == continuous_result.unified_snapshot_id
    assert restored_result.snapshot_fingerprint == continuous_result.snapshot_fingerprint
