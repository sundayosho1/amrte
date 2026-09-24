from time import perf_counter
from tracemalloc import get_traced_memory,start,stop
from amrte.strategies.strategy_arbitration import *
from amrte.strategies.framework import SignalDirection,StrategyFamily
from Tests.Unit.test_strategy_arbitration import baseline,metadata,opinion_eval

def test_prompt16_pairwise_performance_is_bounded():
    intel,base=baseline();evaluations=[];metas={}
    for i in range(30):
        sid=f"S{i}";family=(StrategyFamily.TREND,StrategyFamily.BREAKOUT,StrategyFamily.MEAN_REVERSION)[i%3];direction=SignalDirection.LONG_BIAS if i%2==0 else SignalDirection.SHORT_BIAS;evaluations.append(opinion_eval(base,sid,family,direction,score=60+i));metas[sid]=metadata(sid,family,("TREND",))
    arb=StrategyArbitrationEngine();start();begin=perf_counter();result=arb.arbitrate(intel,tuple(reversed(evaluations)),metas);elapsed=perf_counter()-begin;_,peak=get_traced_memory();stop()
    assert len(result.assessments)==435 and elapsed<5 and peak<20_000_000 and result.decision.outcome in ArbitrationOutcome
