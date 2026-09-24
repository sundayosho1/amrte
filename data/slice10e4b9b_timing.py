import gc
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from tracemalloc import (
    get_traced_memory,
    start,
    stop,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amrte.risk.sizing import (
    RiskSizingConfiguration,
    RiskSizingEngine,
)

from Tests.Unit.test_risk_sizing import inputs

RUNS = 5
ITERATIONS = 200

print(f"PROJECT_ROOT={PROJECT_ROOT}")
print(
    "PROJECT_ROOT_ON_SYS_PATH="
    + str(str(PROJECT_ROOT) in sys.path)
)

def execute(traced):
    engine = RiskSizingEngine(
        RiskSizingConfiguration(
            maximum_cache_entries=64,
            maximum_decisions=64,
            maximum_budgets=64,
        )
    )

    if traced:
        start()

    begin = perf_counter()

    for i in range(ITERATIONS):
        snap, cap, dist, _ = inputs(
            distance=str(
                1 + (i % 9) / 10
            )
        )

        snap = replace(
            snap,
            snapshot_id=f"RISK-{i}",
        )

        engine.size(
            snap,
            cap,
            dist,
        )

    elapsed = perf_counter() - begin

    if traced:
        _, peak = get_traced_memory()
        stop()
    else:
        peak = 0

    return (
        elapsed,
        peak,
        len(engine._decisions),
        len(engine._budgets),
        len(engine._cache),
    )

print("TIMING_RUNS=5")
print("ITERATIONS_PER_RUN=200")

gc.collect()

untraced = []

for run in range(1, RUNS + 1):
    gc.collect()

    result = execute(False)

    untraced.append(
        result[0]
    )

    print(
        f"UNTRACED_RUN_{run}_SECONDS="
        f"{result[0]:.9f}"
    )

    print(
        f"UNTRACED_RUN_{run}_BOUNDS="
        f"{result[2]}/{result[3]}/{result[4]}"
    )

traced = []

for run in range(1, RUNS + 1):
    gc.collect()

    result = execute(True)

    traced.append(
        result[0]
    )

    print(
        f"TRACED_RUN_{run}_SECONDS="
        f"{result[0]:.9f}"
    )

    print(
        f"TRACED_RUN_{run}_PEAK_BYTES="
        f"{result[1]}"
    )

    print(
        f"TRACED_RUN_{run}_BOUNDS="
        f"{result[2]}/{result[3]}/{result[4]}"
    )

print(
    "UNTRACED_MIN_SECONDS="
    f"{min(untraced):.9f}"
)

print(
    "UNTRACED_MEDIAN_SECONDS="
    f"{statistics.median(untraced):.9f}"
)

print(
    "UNTRACED_MAX_SECONDS="
    f"{max(untraced):.9f}"
)

print(
    "TRACED_MIN_SECONDS="
    f"{min(traced):.9f}"
)

print(
    "TRACED_MEDIAN_SECONDS="
    f"{statistics.median(traced):.9f}"
)

print(
    "TRACED_MAX_SECONDS="
    f"{max(traced):.9f}"
)

print(
    "TRACED_PASS_COUNT="
    + str(
        sum(
            value < 5.0
            for value in traced
        )
    )
)

print(
    "UNTRACED_PASS_COUNT="
    + str(
        sum(
            value < 5.0
            for value in untraced
        )
    )
)

print(
    "ALL_BOUNDED_RUNS_COMPLETE=True"
)
