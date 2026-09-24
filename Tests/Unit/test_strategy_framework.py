from dataclasses import FrozenInstanceError,replace
from datetime import timedelta

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.intelligence import IntelligenceAvailability,IntelligenceHealth
from amrte.strategies.framework import *
from Tests.Integration.test_intelligence_integration import chain
from Tests.Unit.test_events import NOW


def intelligence():
    values,audit=chain()
    from amrte.market.intelligence import MarketIntelligenceAssembler
    return MarketIntelligenceAssembler(FixedClock(NOW),audit).assemble(*values)


def metadata(strategy_id="TEST",family=StrategyFamily.CUSTOM,features=()):
    identity=StrategyIdentity(strategy_id,family,f"{strategy_id} Strategy","1.0",required_capabilities=("PHASE2_INTELLIGENCE",))
    requirements=(StrategyRequirement("R1",RequirementType.MANDATORY,EvidenceSource.REGIME,"REGIME"),)
    return StrategyMetadata(identity,"Deterministic fictional test strategy",("H1",),features,("DIRECTION",),("TREND",),True,True,IntelligenceHealth.HEALTHY,requirements)


def evidence(context,category=EvidenceCategory.SUPPORTING,availability=EvidenceAvailability.AVAILABLE):
    return SignalEvidence(deterministic_id("evidence",context.evaluation_id,category.name),"FICTIONAL_TEST",category,EvidenceSource.REGIME,
        context.market_intelligence.regime_snapshot_id,context.instrument_id,"H1",None if availability is not EvidenceAvailability.AVAILABLE else "TREND",
        "TREND",SignalDirection.LONG_BIAS,80 if availability is EvidenceAvailability.AVAILABLE else None,availability,
        "HEALTHY" if availability is EvidenceAvailability.AVAILABLE else "UNAVAILABLE",category.name)


class TestStrategy:
    __test__=False
    def __init__(self,strategy_id="TEST",*,app=ApplicabilityState.APPLICABLE,detect=DetectionState.DETECTED,
                 qualify=QualificationState.QUALIFIED,direction=SignalDirection.LONG_BIAS,raise_error=False,features=()):
        self._metadata=metadata(strategy_id,features=features);self.app=app;self.detect_state=detect;self.qualify_state=qualify;self.signal_direction=direction;self.raise_error=raise_error
    @property
    def metadata(self):return self._metadata
    def applicability(self,context):
        if self.raise_error:raise RuntimeError("INJECTED_STRATEGY_FAILURE")
        return StrategyApplicability(deterministic_id("applicability",context.evaluation_id),self.metadata.identity.strategy_id,self.app,CapabilityStatus.SUPPORTED,(self.app.name,),())
    def detect(self,context):
        item=evidence(context);missing=(evidence(context,EvidenceCategory.MISSING,EvidenceAvailability.UNAVAILABLE),) if self.detect_state is DetectionState.INCOMPLETE else ()
        return DetectionResult(deterministic_id("detection",context.evaluation_id),context.strategy_id,context.instrument_id,context.as_of_timestamp_utc,self.detect_state,(item,),missing,(),context.market_intelligence.market_intelligence_snapshot_id,context.strategy_configuration_snapshot_id)
    def qualify(self,context,detection):
        return QualificationResult(deterministic_id("qualification",context.evaluation_id),context.strategy_id,self.qualify_state,("R1",) if self.qualify_state is QualificationState.QUALIFIED else (),
            ("R1",) if self.qualify_state is QualificationState.REJECTED else (),(),(),("R1",) if self.qualify_state is QualificationState.BLOCKED else ())
    def direction(self,context,detection):return self.signal_direction


def orchestrator(*strategies,configuration=None,gates=None,scorer=None):
    registry=StrategyRegistry()
    for strategy in strategies or (TestStrategy(),):registry.register(strategy)
    audit=InMemoryAuditSink();return StrategyOrchestrator(FixedClock(NOW),audit,registry,configuration or StrategyFrameworkConfiguration(),scorer,gates),audit


def test_registry_metadata_requirements_and_deterministic_order():
    registry=StrategyRegistry();b=TestStrategy("B");a=TestStrategy("A")
    registry.register(b);registry.register(a)
    assert tuple(item.metadata.identity.strategy_id for item in registry.all())==("A","B")
    assert a.metadata.requirements[0].requirement_type is RequirementType.MANDATORY
    with pytest.raises(ValueError):registry.register(a)


def test_configuration_validation():
    assert not StrategyFrameworkConfiguration().validate()
    with pytest.raises(ValueError):orchestrator(configuration=StrategyFrameworkConfiguration(candidate_ttl_minutes=0))
    with pytest.raises(ValueError):orchestrator(configuration=StrategyFrameworkConfiguration(allowed_instruments=("EURUSD",)))


@pytest.mark.parametrize("app,action",[(ApplicabilityState.NOT_APPLICABLE,FinalResearchAction.BLOCKED),(ApplicabilityState.BLOCKED,FinalResearchAction.BLOCKED),(ApplicabilityState.UNKNOWN,FinalResearchAction.BLOCKED)])
def test_non_applicable_states_fail_closed(app,action):
    engine,_=orchestrator(TestStrategy(app=app));result=engine.evaluate(engine.registry.all()[0],intelligence())
    assert result.final_action is action and result.research_signal is None


def test_disabled_and_instrument_restrictions():
    engine,_=orchestrator(configuration=StrategyFrameworkConfiguration(enabled=False));result=engine.evaluate(engine.registry.all()[0],intelligence())
    assert result.applicability.state is ApplicabilityState.NOT_APPLICABLE
    engine,_=orchestrator(configuration=StrategyFrameworkConfiguration(allowed_instruments=("FICTIONAL_BETA",)))
    assert engine.evaluate(engine.registry.all()[0],intelligence()).final_action is FinalResearchAction.BLOCKED


@pytest.mark.parametrize("state,outcome",[(DetectionState.NOT_DETECTED,EvaluationOutcome.NO_ACTION),(DetectionState.INCOMPLETE,EvaluationOutcome.BLOCKED),(DetectionState.BLOCKED,EvaluationOutcome.BLOCKED),(DetectionState.UNKNOWN,EvaluationOutcome.BLOCKED)])
def test_detection_states(state,outcome):
    strategy=TestStrategy(detect=state);engine,_=orchestrator(strategy);result=engine.evaluate(strategy,intelligence())
    assert result.outcome is outcome and result.research_signal is None


@pytest.mark.parametrize("state",[QualificationState.REJECTED,QualificationState.BLOCKED,QualificationState.INCOMPLETE,QualificationState.UNKNOWN])
def test_unqualified_states_never_create_signal(state):
    strategy=TestStrategy(qualify=state);engine,_=orchestrator(strategy);result=engine.evaluate(strategy,intelligence())
    assert result.final_action is FinalResearchAction.NO_ACTION and result.research_signal is None


def test_evidence_provenance_and_missing_not_zero():
    strategy=TestStrategy(detect=DetectionState.INCOMPLETE);engine,_=orchestrator(strategy);result=engine.evaluate(strategy,intelligence())
    missing=result.detection.missing_evidence[0]
    assert missing.source_snapshot_id and missing.availability is EvidenceAvailability.UNAVAILABLE and missing.observed_value is None and missing.strength is None


def test_scoring_candidate_signal_identity_immutability_and_unavailable_gates():
    strategy=TestStrategy();engine,_=orchestrator(strategy);intel=intelligence();first=engine.evaluate(strategy,intel);second=engine.evaluate(strategy,intel)
    assert first is second and first.candidate.signal_candidate_id==second.candidate.signal_candidate_id
    assert first.score.explanation[-1]=="SCORE_NOT_PROFIT_PROBABILITY" and 0<=first.score.overall_score<=100
    assert first.research_signal.final_research_action is FinalResearchAction.RESEARCH_SIGNAL
    assert first.research_signal.risk_gate_status is GateStatus.UNAVAILABLE and first.research_signal.execution_gate_status is GateStatus.UNAVAILABLE
    assert first.decision_trace.outcome.name=="NO_ACTION"
    with pytest.raises(FrozenInstanceError):first.candidate.direction=SignalDirection.SHORT_BIAS


class BlockedGate:
    gate_type=GateType.RISK
    def evaluate(self,candidate,context):return GateResult("G",self.gate_type,GateStatus.BLOCKED,("RISK_BLOCK",),("TEST_BLOCK",),"Test","1")


def test_high_score_cannot_override_blocked_gate():
    strategy=TestStrategy();gates=(BlockedGate(),UnavailableStrategyGate(GateType.PORTFOLIO),UnavailableStrategyGate(GateType.EXECUTION))
    engine,_=orchestrator(strategy,gates=gates);result=engine.evaluate(strategy,intelligence())
    assert result.score.overall_score>0 and result.final_action is FinalResearchAction.BLOCKED and result.research_signal is None


@pytest.mark.parametrize("direction",list(SignalDirection))
def test_direction_model(direction):
    strategy=TestStrategy(direction=direction);engine,_=orchestrator(strategy)
    assert engine.evaluate(strategy,intelligence()).candidate.direction is direction


def test_candidate_expiration_and_invalidation_create_versions():
    strategy=TestStrategy();engine,_=orchestrator(strategy);candidate=engine.evaluate(strategy,intelligence()).candidate
    expired=engine.transition_candidate(candidate,CandidateStatus.EXPIRED,candidate.expires_at_utc,"TTL_EXPIRED")
    invalidated=engine.transition_candidate(candidate,CandidateStatus.INVALIDATED,NOW,"REGIME_CHANGED")
    assert candidate.candidate_status is CandidateStatus.QUALIFIED and expired.signal_version_id!=candidate.signal_version_id
    assert invalidated.candidate_status is CandidateStatus.INVALIDATED
    with pytest.raises(ValueError):engine.transition_candidate(candidate,CandidateStatus.EXPIRED,NOW,"EARLY")


def test_lifecycle_rejects_illegal_transition():
    validate_transition(SignalLifecycleState.NOT_EVALUATED,SignalLifecycleState.DETECTED)
    with pytest.raises(ValueError):validate_transition(SignalLifecycleState.NOT_DETECTED,SignalLifecycleState.RESEARCH_SIGNAL)


def test_phase2_restriction_cannot_be_weakened_and_future_intelligence_blocked():
    strategy=TestStrategy();engine,_=orchestrator(strategy);intel=intelligence()
    restricted=replace(intel,intelligence_availability=IntelligenceAvailability.NOT_AVAILABLE,overall_intelligence_health=IntelligenceHealth.UNTRUSTED)
    assert engine.evaluate(strategy,restricted).final_action is FinalResearchAction.BLOCKED
    future=replace(intel,as_of_timestamp_utc=NOW+timedelta(minutes=1),market_intelligence_snapshot_id="FUTURE")
    assert engine.evaluate(strategy,future).final_action is FinalResearchAction.BLOCKED


def test_strategy_exception_isolated_and_no_action():
    good=TestStrategy("GOOD");bad=TestStrategy("BAD",raise_error=True);engine,audit=orchestrator(good,bad)
    results=engine.evaluate_all(intelligence())
    assert {item.strategy_id:item.outcome for item in results}=={"BAD":EvaluationOutcome.ERROR,"GOOD":EvaluationOutcome.COMPLETED}
    assert next(item for item in results if item.strategy_id=="BAD").final_action is FinalResearchAction.NO_ACTION
    assert "strategy_evaluation_failed" in {name for name,_ in audit.events}


def test_multi_strategy_instrument_state_isolation_and_bounds():
    a=TestStrategy("A");b=TestStrategy("B");engine,_=orchestrator(a,b,configuration=StrategyFrameworkConfiguration(maximum_cache_entries=2,maximum_history=2))
    engine.evaluate_all(intelligence());assert len(engine.history)==2
    assert engine.state("A","FICTIONAL_ALPHA").strategy_id=="A" and engine.state("B","FICTIONAL_ALPHA").strategy_id=="B"
    assert engine.cache_size==2


def test_recovery_validation_and_deterministic_replay():
    strategy=TestStrategy();engine,_=orchestrator(strategy);first=engine.evaluate(strategy,intelligence());state=engine.recovery_state()
    assert engine.validate_recovery(state) and not engine.validate_recovery({"strategy_framework_version":"OTHER"})
    replay,_=orchestrator(TestStrategy());second=replay.evaluate(replay.registry.all()[0],intelligence())
    assert first.evaluation_id==second.evaluation_id and first.candidate.logical_signal_id==second.candidate.logical_signal_id


def test_unsupported_required_feature_blocks():
    strategy=TestStrategy(features=("NONEXISTENT",));engine,_=orchestrator(strategy);result=engine.evaluate(strategy,intelligence())
    assert result.applicability.capability_status is CapabilityStatus.UNAVAILABLE and result.final_action is FinalResearchAction.BLOCKED
