from datetime import datetime, timedelta, timezone
from time import perf_counter

from amrte.market.observation import InstrumentIdentity, ObservationProvenance, SourceIdentity, build_canonical_dataset, create_canonical_bar
from amrte.research.data_quality_runtime import DataQualityTrustRuntime


def test_prompt40_bounded_synthetic_ingestion_soak():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    instrument = InstrumentIdentity("FICTIONAL_ALPHA", "SYN_ALPHA")
    source = SourceIdentity("OFFLINE-P40-PERF", "CSV_BAR", "1.0", "P40_PERF")
    observations = tuple(
        create_canonical_bar(
            instrument=instrument,
            source=source,
            timeframe="M15",
            period_start=start + timedelta(minutes=15 * index),
            period_end=start + timedelta(minutes=15 * (index + 1)),
            available_at=start + timedelta(minutes=15 * (index + 1)),
            received_at=start + timedelta(minutes=15 * (index + 1), seconds=1),
            open=100 + index / 10000,
            high=102 + index / 10000,
            low=99 + index / 10000,
            close=101 + index / 10000,
            volume=index,
            volume_kind="TICK_VOLUME",
            sequence=index + 1,
            provenance=ObservationProvenance(
                source_record_locator=f"row:{index}",
                raw_record_fingerprint=f"raw-{index}",
                transformations=("csv_field_mapping",),
            ),
        )
        for index in range(1000)
    )
    dataset = build_canonical_dataset(observations)
    runtime = DataQualityTrustRuntime()

    began = perf_counter()
    report = runtime.ingest_dataset(dataset, logical_time=observations[-1].available_at)
    elapsed = perf_counter() - began

    assert report.received == 1000
    assert report.trusted > 0
    assert report.rejected == 0
    assert len(runtime.snapshots) <= runtime.configuration.maximum_snapshots
    assert len(runtime.source_health) <= runtime.configuration.maximum_snapshots
    assert elapsed < 5.0
