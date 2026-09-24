from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum,auto

from amrte.core.identity import deterministic_id
from amrte.core.interfaces import IAuditSink,IClock
from amrte.core.observability import DecisionTraceBuilder
from amrte.core.observability_types import DecisionOutcome,DecisionStatus,DecisionTrace
from .events import NewsRiskHealth,NewsRiskSnapshot,NewsPolicyState
from .features import FeatureHealth,FeatureSnapshot
from .models import DataHealth,MarketDataSnapshot
from .regime import PrimaryRegime,RegimeHealth,RegimeSnapshot
from .session import SessionHealth,SessionSnapshot,TemporalRestriction
from .structure import StructureHealth,StructureSnapshot

INTELLIGENCE_SCHEMA_VERSION="1.0"

class IntelligenceHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();UNTRUSTED=auto();UNAVAILABLE=auto();UNKNOWN=auto()
class IntelligenceAvailability(Enum):AVAILABLE=auto();AVAILABLE_WITH_RESTRICTIONS=auto();NOT_AVAILABLE=auto();UNKNOWN=auto()

@dataclass(frozen=True)
class MarketIntelligenceSnapshot:
    market_intelligence_snapshot_id:str;created_at:datetime;as_of_timestamp_utc:datetime
    experiment_id:str;dataset_id:str;dataset_fingerprint:str;instrument_id:str
    market_data_snapshot_id:str;structure_snapshot_id:str;feature_snapshot_id:str
    regime_snapshot_id:str;session_snapshot_id:str;news_risk_snapshot_id:str
    market_data:MarketDataSnapshot;structure:StructureSnapshot;features:FeatureSnapshot
    regime:RegimeSnapshot;session:SessionSnapshot;news_risk:NewsRiskSnapshot
    data_health:DataHealth;structure_health:StructureHealth;feature_health:FeatureHealth
    regime_health:RegimeHealth;session_health:SessionHealth;news_risk_health:NewsRiskHealth
    overall_intelligence_health:IntelligenceHealth;intelligence_availability:IntelligenceAvailability
    restrictions:tuple[str,...];reason_codes:tuple[str,...];warnings:tuple[str,...]
    decision_trace:DecisionTrace;configuration_snapshot_id:str;recovery_epoch:int
    intelligence_schema_version:str=INTELLIGENCE_SCHEMA_VERSION


class MarketIntelligenceAssembler:
    def __init__(self,clock:IClock,audit:IAuditSink):self.clock=clock;self.audit=audit
    def validate_lineage(self,market,structure,features,regime,session,news)->tuple[bool,tuple[str,...]]:
        reasons=[]
        values=(market,structure,features,regime)
        if len({item.dataset_id for item in values})!=1:reasons.append("DATASET_ID_MISMATCH")
        if len({item.dataset_fingerprint for item in values})!=1:reasons.append("DATASET_FINGERPRINT_MISMATCH")
        if len({item.instrument_id for item in (*values,session,news)})!=1:reasons.append("INSTRUMENT_MISMATCH")
        timestamps=(market.as_of_timestamp,structure.as_of_timestamp,features.as_of_timestamp,regime.as_of_timestamp,session.as_of_timestamp_utc,news.as_of_timestamp_utc)
        if len(set(timestamps))!=1:reasons.append("AS_OF_MISMATCH")
        configs=(market.configuration_snapshot_id,structure.configuration_snapshot_id,features.configuration_snapshot_id,regime.configuration_snapshot_id,session.configuration_snapshot_id,news.configuration_snapshot_id)
        if len(set(configs))!=1:reasons.append("CONFIGURATION_MISMATCH")
        epochs=(market.recovery_epoch,structure.recovery_epoch,features.recovery_epoch,regime.recovery_epoch,session.recovery_epoch,news.recovery_epoch)
        if len(set(epochs))!=1:reasons.append("RECOVERY_EPOCH_MISMATCH")
        if structure.source_market_data_snapshot_id!=market.snapshot_id:reasons.append("STRUCTURE_LINEAGE_MISMATCH")
        if features.source_market_data_snapshot_id!=market.snapshot_id or features.source_structure_snapshot_id not in (None,structure.structure_snapshot_id):reasons.append("FEATURE_LINEAGE_MISMATCH")
        if regime.source_market_data_snapshot_id!=market.snapshot_id or regime.source_structure_snapshot_id!=structure.structure_snapshot_id or regime.source_feature_snapshot_id!=features.feature_snapshot_id:reasons.append("REGIME_LINEAGE_MISMATCH")
        if session.source_market_data_snapshot_id!=market.snapshot_id:reasons.append("SESSION_LINEAGE_MISMATCH")
        return not reasons,tuple(reasons)
    def assemble(self,market:MarketDataSnapshot,structure:StructureSnapshot,features:FeatureSnapshot,regime:RegimeSnapshot,session:SessionSnapshot,news:NewsRiskSnapshot)->MarketIntelligenceSnapshot|None:
        valid,reasons=self.validate_lineage(market,structure,features,regime,session,news)
        if not valid:self.audit.record("market_intelligence_rejected",{"reasons":reasons});return None
        restrictions=[];warnings=[]
        critical=market.data_health in (DataHealth.INVALID,DataHealth.UNAVAILABLE,DataHealth.STALE) or structure.overall_structure_health in (StructureHealth.INVALID_INPUT,StructureHealth.INSUFFICIENT_HISTORY) or features.health in (FeatureHealth.INVALID_INPUT,FeatureHealth.INSUFFICIENT_HISTORY,FeatureHealth.STALE,FeatureHealth.UNAVAILABLE)
        unavailable=news.news_risk_health in (NewsRiskHealth.UNAVAILABLE,NewsRiskHealth.INVALID) or session.session_health in (SessionHealth.UNAVAILABLE,SessionHealth.INVALID_CONFIGURATION)
        restricted=regime.regime_health is not RegimeHealth.HEALTHY or session.session_health is not SessionHealth.HEALTHY or news.news_risk_health is not NewsRiskHealth.HEALTHY or session.temporal_restriction is not TemporalRestriction.ALLOW_CONTEXT or news.policy_state is not NewsPolicyState.ALLOW_CONTEXT
        if critical:health=IntelligenceHealth.UNTRUSTED;availability=IntelligenceAvailability.NOT_AVAILABLE;restrictions.append("MANDATORY_COMPONENT_UNTRUSTED")
        elif unavailable:health=IntelligenceHealth.UNAVAILABLE;availability=IntelligenceAvailability.NOT_AVAILABLE;restrictions.append("MANDATORY_COMPONENT_UNAVAILABLE")
        elif restricted:health=IntelligenceHealth.RESTRICTED;availability=IntelligenceAvailability.AVAILABLE_WITH_RESTRICTIONS;restrictions.extend((session.temporal_restriction.name,news.policy_state.name,regime.primary_regime.name))
        elif any(value.name in ("DEGRADED","VALID_WITH_WARNINGS") for value in (market.data_health,structure.overall_structure_health,features.health,regime.regime_health,session.session_health,news.news_risk_health)):
            health=IntelligenceHealth.DEGRADED;availability=IntelligenceAvailability.AVAILABLE_WITH_RESTRICTIONS;restrictions.append("DEGRADED_COMPONENT")
        else:health=IntelligenceHealth.HEALTHY;availability=IntelligenceAvailability.AVAILABLE
        if regime.primary_regime in (PrimaryRegime.ABNORMAL,PrimaryRegime.UNKNOWN):
            health=IntelligenceHealth.RESTRICTED if health is IntelligenceHealth.HEALTHY else health;availability=IntelligenceAvailability.NOT_AVAILABLE;restrictions.append("REGIME_NOT_ORDINARY")
        trace=DecisionTraceBuilder(self.clock,deterministic_id("intelligence_decision",market.snapshot_id,news.news_risk_snapshot_id),deterministic_id("correlation",market.snapshot_id,"phase2"))
        trace_open=True
        for gate,status in (("data",market.data_health),("structure",structure.overall_structure_health),("features",features.health),("regime",regime.regime_health),("session",session.session_health),("news",news.news_risk_health)):
            if not trace_open:break
            passed=status.name in ("HEALTHY","VALID","VALID_WITH_WARNINGS")
            trace.evaluate(gate,DecisionStatus.PASSED if passed else DecisionStatus.FAILED,status.name,"authoritative Phase II component")
            trace_open=passed
        if trace_open:trace.evaluate("availability",DecisionStatus.PASSED if availability is IntelligenceAvailability.AVAILABLE else DecisionStatus.FAILED,availability.name,"no execution authorization")
        decision_trace=trace.complete(DecisionOutcome.NO_ACTION,"unified research intelligence only")
        identity=deterministic_id("market_intel",market.snapshot_id,structure.structure_snapshot_id,features.feature_snapshot_id,regime.regime_snapshot_id,session.session_snapshot_id,news.news_risk_snapshot_id,INTELLIGENCE_SCHEMA_VERSION)
        result=MarketIntelligenceSnapshot(identity,self.clock.now(),market.as_of_timestamp,market.experiment_id,market.dataset_id,market.dataset_fingerprint,market.instrument_id,
            market.snapshot_id,structure.structure_snapshot_id,features.feature_snapshot_id,regime.regime_snapshot_id,session.session_snapshot_id,news.news_risk_snapshot_id,
            market,structure,features,regime,session,news,market.data_health,structure.overall_structure_health,features.health,regime.regime_health,session.session_health,news.news_risk_health,
            health,availability,tuple(dict.fromkeys(restrictions)),tuple(reasons or (health.name,availability.name)),tuple(warnings),decision_trace,market.configuration_snapshot_id,market.recovery_epoch)
        self.audit.record("market_intelligence_snapshot_created",{"snapshot_id":identity,"health":health.name,"availability":availability.name});return result
