from datetime import datetime, timedelta, timezone
from time import perf_counter

from amrte.market.observation import (
    CanonicalDatasetReplay,
    InstrumentIdentity,
    SourceIdentity,
    build_canonical_dataset,
    create_canonical_bar,
)


def test_prompt39_canonical_dataset_build_and_replay_are_bounded():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    instrument = InstrumentIdentity("FICTIONAL_ALPHA", "SYN_ALPHA")
    source = SourceIdentity("OFFLINE-PERF", "CSV_BAR", "1.0", "PERF")
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
            high=101 + index / 10000,
            low=99 + index / 10000,
            close=100.5 + index / 10000,
            volume=index,
            volume_kind="TICK_VOLUME",
            sequence=index + 1,
        )
        for index in range(5000)
    )

    began = perf_counter()
    dataset = build_canonical_dataset(observations)
    replayed = CanonicalDatasetReplay(dataset).available_as_of(observations[-1].available_at)
    elapsed = perf_counter() - began

    assert dataset.manifest.observation_count == 5000
    assert len(replayed) == 5000
    assert elapsed < 5.0
