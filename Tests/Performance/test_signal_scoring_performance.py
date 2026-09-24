from time import perf_counter
from tracemalloc import get_traced_memory,start,stop

from amrte.strategies.framework import *
from amrte.strategies.scoring import CentralSignalScorer,ScoringConfiguration
from Tests.Unit.test_signal_scoring import context_and_results


def test_bounded_scoring_performance():
    scorer=CentralSignalScorer(configuration=ScoringConfiguration(maximum_cache_entries=32,maximum_history=32))
    _,context,detection,qualification=context_and_results();start();begin=perf_counter()
    generated=0
    for index in range(250):
        current=replace(context,evaluation_id=f"PERF-{index}")
        scorer.score(current,detection,qualification);generated+=1
    elapsed=perf_counter()-begin;_,peak=get_traced_memory();stop()
    assert generated==250 and scorer.cache_size==32 and len(scorer.history)==32
    assert elapsed<5 and peak<20_000_000
