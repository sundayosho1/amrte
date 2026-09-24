from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_runtime_composition_endpoint_is_read_only():
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/runtime-composition")

        assert response.status_code == 200
        payload = response.json()

        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["composition_available"] is True
        assert payload["registry_frozen"] is True
        assert payload["validated"] is True

        for method in (
            client.post,
            client.put,
            client.patch,
            client.delete,
        ):
            assert method("/api/v1/runtime-composition").status_code == 405


def test_runtime_composition_inventory_exposes_core_components():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/runtime-composition").json()

    components = {
        item["component_id"]: item
        for item in payload["components"]
    }

    expected = {
        "audit",
        "clock",
        "composition",
        "configuration",
        "data_trust",
        "execution",
        "health",
        "market_data_configured_dataset",
        "market_data_contract",
        "market_data_source_adapter_framework",
        "market_dataset_authority",
        "market_event_context",
        "market_features",
        "market_intelligence",
        "market_regime",
        "market_session",
        "market_structure",
        "observation_quality",
        "observability",
        "random",
        "research_reliability",
        "research_candidate_runtime",
        "central_scoring",
        "candidate_comparison",
        "strategy_arbitration",
        "post_scoring_research_assessment",
        "research_risk",
        "portfolio_context",
        "correlation_analysis",
        "concentration_analysis",
        "portfolio_restrictions",
        "portfolio_research_snapshot",
        "protection_input_monitor",
        "strategy_health_protection",
        "temporal_safety_protection",
        "lifecycle_protection",
        "dependency_protection",
        "system_safety_protection",
        "research_protection",
        "research_protection_snapshot",
        "research_processing_context",
        "stage_evidence_verification",
        "master_research_decision",
        "research_decision_trace",
        "research_decision_ledger",
        "evidence_validation",
        "evidence_serialization",
        "research_evidence_ledger",
        "ledger_integrity_verification",
        "evidence_reconstruction",
        "outcome_window_manager",
        "outcome_evidence_validator",
        "research_outcome_attribution",
        "cohort_analytics",
        "research_performance_intelligence",
        "research_performance_snapshot",
        "improvement_evidence_validator",
        "research_pattern_analysis",
        "research_stability_analysis",
        "research_failure_clustering",
        "improvement_hypothesis_generation",
        "research_improvement_snapshot",
        "experiment_registry",
        "experiment_specification_validator",
        "dataset_partition_manager",
        "research_experiment_runtime",
        "historical_validation",
        "out_of_sample_validation",
        "walk_forward_validation",
        "robustness_validation",
        "sensitivity_validation",
        "configuration_comparison",
        "research_promotion_assessment",
        "versioned_research_configuration",
        "forward_observation_stream",
        "forward_session_registry",
        "forward_research_runtime",
        "shadow_research_comparison",
        "forward_drift_monitor",
        "forward_runtime_recovery",
        "state",
        "research_pipeline",
        "strategy_evaluation",
        "strategy_registry",
        "temporal_quality",
    }

    assert set(components) == expected
    assert components["execution"]["required"] is True
    assert components["execution"]["active"] is True
    assert components["market_data_contract"]["required"] is True
    assert components["market_data_contract"]["active"] is True
    assert components["market_dataset_authority"]["active"] is True
    assert components["market_data_configured_dataset"]["status"] == "UNAVAILABLE"
    assert components["observation_quality"]["active"] is True
    assert components["research_reliability"]["active"] is True
    assert components["temporal_quality"]["active"] is True
    assert components["data_trust"]["active"] is True
    assert components["market_structure"]["active"] is True
    assert components["market_features"]["active"] is True
    assert components["market_session"]["active"] is True
    assert components["market_event_context"]["active"] is True
    assert components["market_regime"]["active"] is True
    assert components["market_intelligence"]["active"] is True
    assert components["strategy_registry"]["active"] is True
    assert components["strategy_evaluation"]["active"] is True
    assert components["research_candidate_runtime"]["active"] is True
    assert components["central_scoring"]["active"] is True
    assert components["candidate_comparison"]["active"] is True
    assert components["strategy_arbitration"]["active"] is True
    assert components["post_scoring_research_assessment"]["active"] is True
    assert components["research_risk"]["active"] is True
    assert components["portfolio_context"]["active"] is True
    assert components["correlation_analysis"]["active"] is True
    assert components["concentration_analysis"]["active"] is True
    assert components["portfolio_restrictions"]["active"] is True
    assert components["portfolio_research_snapshot"]["active"] is True
    assert components["protection_input_monitor"]["active"] is True
    assert components["strategy_health_protection"]["active"] is True
    assert components["temporal_safety_protection"]["active"] is True
    assert components["lifecycle_protection"]["active"] is True
    assert components["dependency_protection"]["active"] is True
    assert components["system_safety_protection"]["active"] is True
    assert components["research_protection"]["active"] is True
    assert components["research_protection_snapshot"]["active"] is True
    assert components["research_processing_context"]["active"] is True
    assert components["stage_evidence_verification"]["active"] is True
    assert components["master_research_decision"]["active"] is True
    assert components["research_decision_trace"]["active"] is True
    assert components["research_decision_ledger"]["active"] is True
    assert components["evidence_validation"]["active"] is True
    assert components["evidence_serialization"]["active"] is True
    assert components["research_evidence_ledger"]["active"] is True
    assert components["ledger_integrity_verification"]["active"] is True
    assert components["evidence_reconstruction"]["active"] is True
    assert components["outcome_window_manager"]["active"] is True
    assert components["outcome_evidence_validator"]["active"] is True
    assert components["research_outcome_attribution"]["active"] is True
    assert components["cohort_analytics"]["active"] is True
    assert components["research_performance_intelligence"]["active"] is True
    assert components["research_performance_snapshot"]["active"] is True
    assert components["improvement_evidence_validator"]["active"] is True
    assert components["research_pattern_analysis"]["active"] is True
    assert components["research_stability_analysis"]["active"] is True
    assert components["research_failure_clustering"]["active"] is True
    assert components["improvement_hypothesis_generation"]["active"] is True
    assert components["research_improvement_snapshot"]["active"] is True
    assert components["experiment_registry"]["active"] is True
    assert components["experiment_specification_validator"]["active"] is True
    assert components["dataset_partition_manager"]["active"] is True
    assert components["research_experiment_runtime"]["active"] is True
    assert components["historical_validation"]["active"] is True
    assert components["out_of_sample_validation"]["active"] is True
    assert components["walk_forward_validation"]["active"] is True
    assert components["robustness_validation"]["active"] is True
    assert components["sensitivity_validation"]["active"] is True
    assert components["configuration_comparison"]["active"] is True
    assert components["research_promotion_assessment"]["active"] is True
    assert components["versioned_research_configuration"]["active"] is True
    assert components["forward_observation_stream"]["active"] is True
    assert components["forward_session_registry"]["active"] is True
    assert components["forward_research_runtime"]["active"] is True
    assert components["shadow_research_comparison"]["active"] is True
    assert components["forward_drift_monitor"]["active"] is True
    assert components["forward_runtime_recovery"]["active"] is True
    assert components["data_trust"]["persistence_participant"] is True
    assert components["data_trust"]["recovery_participant"] is True
    assert components["market_intelligence"]["persistence_participant"] is True
    assert components["market_intelligence"]["recovery_participant"] is True
    assert components["strategy_evaluation"]["persistence_participant"] is True
    assert components["research_candidate_runtime"]["recovery_participant"] is True
    assert components["central_scoring"]["persistence_participant"] is True
    assert components["post_scoring_research_assessment"]["recovery_participant"] is True
    assert components["research_risk"]["persistence_participant"] is True
    assert components["portfolio_research_snapshot"]["recovery_participant"] is True
    assert components["research_protection"]["persistence_participant"] is True
    assert components["research_protection_snapshot"]["recovery_participant"] is True
    assert components["master_research_decision"]["persistence_participant"] is True
    assert components["research_decision_ledger"]["recovery_participant"] is True
    assert components["research_evidence_ledger"]["persistence_participant"] is True
    assert components["evidence_reconstruction"]["recovery_participant"] is True
    assert components["outcome_window_manager"]["persistence_participant"] is True
    assert components["research_outcome_attribution"]["recovery_participant"] is True
    assert components["research_performance_snapshot"]["persistence_participant"] is True
    assert components["improvement_evidence_validator"]["persistence_participant"] is True
    assert components["improvement_hypothesis_generation"]["recovery_participant"] is True
    assert components["research_improvement_snapshot"]["persistence_participant"] is True
    assert components["experiment_registry"]["persistence_participant"] is True
    assert components["research_experiment_runtime"]["recovery_participant"] is True
    assert components["versioned_research_configuration"]["persistence_participant"] is True
    assert components["forward_research_runtime"]["persistence_participant"] is True
    assert components["forward_runtime_recovery"]["recovery_participant"] is True
    assert components["state"]["persistence_participant"] is True
    assert components["state"]["recovery_participant"] is True


def test_runtime_composition_dependency_and_order_diagnostics_are_deterministic():
    app = create_app()

    with TestClient(app) as client:
        first = client.get("/api/v1/runtime-composition").json()
        second = client.get("/api/v1/runtime-composition").json()

    assert first["initialization_order"] == second["initialization_order"]
    assert first["shutdown_order"] == second["shutdown_order"]
    assert first["shutdown_order"] == list(
        reversed(first["initialization_order"])
    )
    assert "clock" in first["initialization_order"]
    assert (
        first["initialization_order"].index("clock")
        < first["initialization_order"].index("configuration")
    )


def test_runtime_composition_reports_research_pipeline_not_active():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/runtime-composition").json()

    pipeline = payload["research_pipeline"]

    assert pipeline["registered"] is True
    assert pipeline["active"] is False
    assert pipeline["status"] == "UNAVAILABLE"
    assert pipeline["ready"] is False


def test_system_health_distinguishes_core_component_and_pipeline_state():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/system/health").json()

    assert payload["status"] == "HEALTHY"
    assert payload["core_runtime_state"] == "RUNNING"
    assert payload["component_readiness"]["ready"] is True
    assert payload["component_health"]["ready"] is True
    assert payload["research_pipeline"]["active"] is False
    assert payload["research_pipeline"]["status"] == "UNAVAILABLE"


def test_health_diagnostics_includes_composition_summary():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/health-diagnostics").json()

    composition = payload["composition"]

    assert composition["available"] is True
    assert composition["readiness"]["ready"] is True
    assert composition["component_count"] >= 9
    assert composition["research_pipeline"]["active"] is False
