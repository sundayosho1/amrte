from dataclasses import FrozenInstanceError,replace
from math import inf,nan

import pytest

from amrte.core.clock import FixedClock
from amrte.core.identity import deterministic_id
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.strategies.framework import *
from amrte.strategies.scoring import *
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_framework import TestStrategy,intelligence,orchestrator


def context_and_results(strategy_id="TEST",qualify=QualificationState.QUALIFIED):
    strategy=TestStrategy(strategy_id,qualify=qualify);intel=intelligence()
    context=StrategyEvaluationContext(deterministic_id("eval",strategy_id),strategy_id,intel.instrument_id,intel.as_of_timestamp_utc,intel,intel.configuration_snapshot_id,None,EvaluationReason.NEW_BAR,intel.recovery_epoch)
    detection=strategy.detect(context);qualification=strategy.qualify(context,detection)
    return strategy,context,detection,qualification


def score(**kwargs):
    strategy,context,detection,qualification=context_and_results()
    scorer=CentralSignalScorer(**kwargs)
    return scorer,scorer.score(context,detection,qualification),context,detection,qualification


def test_registry_default_models_identity_and_duplicate_rejection():
    registry=ScoringModelRegistry();model=default_model(StrategyFamily.TREND);registry.register(model)
    assert registry.get(model.scoring_model_id) is model and registry.resolve(StrategyFamily.TREND) is model
    with pytest.raises(ValueError,match="DUPLICATE_SCORING_MODEL_ID"):registry.register(model)


def test_model_validation_weights_dependencies_and_cycles():
    n=NormalizationConfiguration()
    with pytest.raises(ValueError,match="INVALID_WEIGHT"):
        r=ScoringModelRegistry();r.register(ScoringModel("M","1","1","H",StrategyFamily.CUSTOM,(FactorDefinition("A",FactorGroup.CUSTOM,-1,normalization=n),)))
    with pytest.raises(ValueError,match="ZERO_EFFECTIVE_MODEL"):
        r=ScoringModelRegistry();r.register(ScoringModel("M","1","1","H",StrategyFamily.CUSTOM,(FactorDefinition("A",FactorGroup.CUSTOM,0,normalization=n),)))
    factors=(FactorDefinition("A",FactorGroup.CUSTOM,1,dependencies=("B",)),FactorDefinition("B",FactorGroup.CUSTOM,1,dependencies=("A",)))
    with pytest.raises(ValueError,match="DEPENDENCY_CYCLE"):
        r=ScoringModelRegistry();r.register(ScoringModel("M","1","1","H",StrategyFamily.CUSTOM,factors))


@pytest.mark.parametrize("method,value,expected",[
 (NormalizationMethod.LINEAR,50,50),(NormalizationMethod.BOUNDED_LINEAR,150,100),
 (NormalizationMethod.PERCENTILE_BASED,25,25),(NormalizationMethod.BOOLEAN,1,100),
 (NormalizationMethod.DISTANCE_FROM_TARGET,50,100),(NormalizationMethod.PIECEWISE_LINEAR,50,100)])
def test_normalization_methods(method,value,expected):
    config=NormalizationConfiguration(method,0,100,50)
    assert normalize(value,config)==expected


def test_categorical_directional_clamping_and_invalid_values():
    config=NormalizationConfiguration(NormalizationMethod.CATEGORICAL,0,100,categories=(("UP",90),))
    assert normalize("UP",config)==90
    assert normalize(25,NormalizationConfiguration(direction=-1))==75
    with pytest.raises(ValueError):normalize(nan,NormalizationConfiguration())
    with pytest.raises(ValueError):normalize(inf,NormalizationConfiguration())


def test_central_score_decomposition_identity_immutability_and_lineage():
    scorer,result,context,_,_=score()
    assert 0<=result.overall_score<=100
    assert all(0<=value<=100 for value in (result.confidence,result.quality,result.completeness,result.agreement,result.uncertainty))
    assert result.scoring_model_id and result.score_version_id and result.logical_score_id
    assert result.market_intelligence_snapshot_id==context.market_intelligence.market_intelligence_snapshot_id
    assert result.configuration_snapshot_id==scorer.configuration.configuration_snapshot_id
    assert "SCORE_IS_RESEARCH_QUALITY_NOT_PROFIT_PROBABILITY" in result.explanation
    with pytest.raises(FrozenInstanceError):result.overall_score=99


def test_factors_are_explicit_and_deferred_inputs_are_not_fabricated():
    _,result,_,_,_=score();by_id={factor.factor_id:factor for factor in result.factor_scores}
    assert by_id["REGIME"].source_module=="Prompt8" and by_id["STRUCTURE"].source_module=="Prompt6"
    assert by_id["SESSION"].source_module=="Prompt9" and by_id["NEWS_CONTEXT"].source_module=="Prompt10"
    assert by_id["RISK_REWARD"].raw_value is None and by_id["RISK_REWARD"].availability is FactorAvailability.NOT_APPLICABLE
    assert by_id["CORRELATION"].raw_value is None and by_id["CORRELATION"].source_module=="PHASE_V"


def test_missing_not_zero_and_not_applicable_not_missing():
    _,result,_,_,_=score();by_id={factor.factor_id:factor for factor in result.factor_scores}
    assert by_id["RISK_REWARD"].normalized_value is None
    assert not any("RISK_REWARD" in reason for reason in result.missing_reasons)


def test_mandatory_missing_returns_unavailable_and_orchestrator_stops():
    registry=ScoringModelRegistry();model=ScoringModel("M","1","1","H",StrategyFamily.CUSTOM,(FactorDefinition("UNOWNED",FactorGroup.CUSTOM,1,FactorRequirement.MANDATORY),));registry.register(model)
    scorer,result,_,_,_=score(registry=registry)
    assert result.score_health is ScoreHealth.UNAVAILABLE and result.overall_score==0
    strategy=TestStrategy();engine,_=orchestrator(strategy,scorer=scorer);evaluation=engine.evaluate(strategy,intelligence())
    assert evaluation.final_action is FinalResearchAction.NO_ACTION and evaluation.candidate is None and evaluation.research_signal is None


def test_optional_policies_completeness_and_penalty():
    registry=ScoringModelRegistry();model=ScoringModel("M","1","1","H",StrategyFamily.CUSTOM,(
      FactorDefinition("SETUP_QUALITY",FactorGroup.SETUP_QUALITY,1,FactorRequirement.MANDATORY),
      FactorDefinition("OPTIONAL",FactorGroup.CUSTOM,1,FactorRequirement.OPTIONAL)));registry.register(model)
    config=ScoringConfiguration(missing_optional_policy=MissingFactorPolicy.PENALIZE_MISSING_OPTIONAL,missing_optional_penalty=7,minimum_completeness=0)
    _,result,_,_,_=score(registry=registry,configuration=config)
    assert result.missing_evidence_penalty==7 and result.completeness==50 and result.score_health is ScoreHealth.DEGRADED


def test_group_cap_and_weight_normalization():
    registry=ScoringModelRegistry();model=ScoringModel("M","1","1","H",StrategyFamily.CUSTOM,(
      FactorDefinition("SETUP_QUALITY",FactorGroup.SETUP_QUALITY,3,FactorRequirement.MANDATORY),
      FactorDefinition("SETUP_QUALITY_2",FactorGroup.SETUP_QUALITY,2,FactorRequirement.OPTIONAL)));registry.register(model)
    config=ScoringConfiguration(group_caps=(("SETUP_QUALITY",60),),minimum_completeness=0)
    _,result,_,_,_=score(registry=registry,configuration=config)
    assert result.group_scores["SETUP_QUALITY"]<=60


def test_conflict_penalty_and_explanation():
    strategy,context,detection,qualification=context_and_results();conflict=replace(detection.evidence[0],evidence_id="CONFLICT",category=EvidenceCategory.CONFLICTING,strength=90)
    detection=replace(detection,conflicting_evidence=(conflict,));result=CentralSignalScorer().score(context,detection,qualification)
    assert result.conflict_penalty>0 and result.conflicts and "EVIDENCE_DIRECTION_CONFLICT" in result.conflicting_reasons


def test_cache_is_bounded_isolated_and_deterministic():
    config=ScoringConfiguration(maximum_cache_entries=1,maximum_history=2);scorer,result,context,detection,qualification=score(configuration=config)
    again=scorer.score(context,detection,qualification)
    assert again is result and scorer.cache_hits==1 and scorer.cache_size==1
    altered=replace(context,evaluation_id="OTHER")
    scorer.score(altered,detection,qualification)
    assert scorer.cache_size==1 and scorer.cache_misses==2


def test_configuration_change_and_model_version_change_score_identity():
    _,first,context,detection,qualification=score()
    second=CentralSignalScorer(configuration=ScoringConfiguration(configuration_snapshot_id="CONFIG_B")).score(context,detection,qualification)
    registry=ScoringModelRegistry();model=replace(default_model(StrategyFamily.CUSTOM),scoring_model_id="M2",scoring_model_version="2");registry.register(model)
    third=CentralSignalScorer(registry=registry).score(context,detection,qualification)
    assert len({first.score_version_id,second.score_version_id,third.score_version_id})==3 and first.configuration_snapshot_id!="CONFIG_B"


def test_recovery_validation_and_deterministic_rebuild():
    scorer,first,context,detection,qualification=score();state=scorer.recovery_state()
    replay=CentralSignalScorer();second=replay.score(context,detection,qualification)
    assert scorer.validate_recovery(state) and not scorer.validate_recovery({"engine_version":"BAD"})
    assert first.signal_score_id==second.signal_score_id


def test_observability_events_and_strategy_isolation():
    audit=InMemoryAuditSink();scorer,result,_,_,_=score(audit=audit,strategy_families={"TEST":StrategyFamily.TREND})
    assert result.scoring_model_id.endswith("TREND_RESEARCH_SCORE")
    assert {name for name,_ in audit.events}>={"scoring_started","scoring_completed"}


def test_invalid_qualification_cannot_be_rescued():
    _,context,detection,qualification=context_and_results(qualify=QualificationState.REJECTED)
    result=CentralSignalScorer().score(context,detection,qualification)
    assert result.score_health is ScoreHealth.UNAVAILABLE and result.overall_score==0


def test_temporal_lineage_does_not_accept_future_outcome_inputs():
    _,result,context,_,_=score()
    assert all("outcome" not in factor.source_module.lower() for factor in result.factor_scores)
    assert result.market_intelligence_snapshot_id==context.market_intelligence.market_intelligence_snapshot_id


def test_multi_instrument_cache_isolation():
    scorer,first,context,detection,qualification=score();other=replace(context,instrument_id="FICTIONAL_BETA",evaluation_id="B")
    second=scorer.score(other,replace(detection,instrument_id="FICTIONAL_BETA"),qualification)
    assert first.signal_score_id!=second.signal_score_id and scorer.cache_misses==2


def test_score_has_no_order_or_position_sizing_capability():
    forbidden={"place_order","submit_order","size_position","broker","account_login"}
    assert forbidden.isdisjoint(set(dir(CentralSignalScorer)))

