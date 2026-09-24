from datetime import datetime, timezone

import pytest

from amrte.core.clock import FixedClock
from amrte.core.config_engine import (
    ConfigurationValidator, MasterConfigurationEngine, canonical_serialize,
    classify_schema, configuration_hash, diff_snapshots,
)
from amrte.core.config_schema import HARD_SAFETY_VALUES, SCHEMA
from amrte.core.constants import CONFIG_SCHEMA_VERSION, MAX_CONCURRENT_SCENARIOS, MAX_RESEARCH_RESOURCE_LOAD
from amrte.core.types import (
    ConfigurationSource, ResearchProfile, SchemaCompatibility,
    ValidationStatus,
)
from amrte.infrastructure.local import InMemoryAuditSink


@pytest.fixture
def engine():
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    return MasterConfigurationEngine(clock, InMemoryAuditSink())


@pytest.mark.parametrize("profile,score,count,load", [
    (ResearchProfile.CONSERVATIVE, 0.85, 1, 0.25),
    (ResearchProfile.BALANCED, 0.70, 3, 0.50),
    (ResearchProfile.AGGRESSIVE, 0.60, 5, 0.75),
    (ResearchProfile.CUSTOM, 0.70, 3, 0.50),
])
def test_all_profiles_resolve(engine, profile, score, count, load):
    result = engine.build_candidate(profile)
    assert result.success
    assert result.value.selected_profile is profile
    assert result.value.values["research.minimum_quality_score"] == score
    assert result.value.values["research.max_concurrent_scenarios"] == count
    assert result.value.values["research.max_resource_load"] == load


def test_custom_uses_same_schema_validation(engine):
    valid = engine.build_candidate(ResearchProfile.CUSTOM, custom={"research.max_concurrent_scenarios": 4})
    invalid = engine.build_candidate(ResearchProfile.CUSTOM, custom={"research.max_concurrent_scenarios": -1})
    assert valid.success and valid.value.values["research.max_concurrent_scenarios"] == 4
    assert not invalid.success and invalid.error.code == "CONFIGURATION_INVALID"


def test_precedence_and_provenance(engine):
    result = engine.build_candidate(
        strategy={"research.minimum_quality_score": 0.74},
        instrument={"research.minimum_quality_score": 0.77},
        runtime={"research.minimum_quality_score": 0.80},
    )
    snapshot = result.value
    assert snapshot.values["research.minimum_quality_score"] == 0.80
    assert snapshot.provenance["research.minimum_quality_score"] == ConfigurationSource.RUNTIME_RESTRICTION.name
    assert snapshot.overridden_sources["research.minimum_quality_score"] == (
        "GLOBAL_DEFAULT", "PROFILE", "STRATEGY_OVERRIDE", "INSTRUMENT_OVERRIDE"
    )


@pytest.mark.parametrize("key,bad", [
    ("broker.live_execution", True),
    ("broker.demo_execution", True),
    ("broker.authentication", True),
    ("execution.available", True),
    ("protection.enabled", False),
    ("protection.fail_closed", False),
    ("safety.martingale", True),
    ("safety.unlimited_exposure", True),
])
def test_hard_safety_cannot_be_overridden(engine, key, bad):
    result = engine.build_candidate(ResearchProfile.AGGRESSIVE, custom={key: bad})
    assert not result.success and result.error.code == "HARD_SAFETY_OVERRIDE"


def test_restrict_only_setting_cannot_be_weakened(engine):
    result = engine.build_candidate(custom={"general.strict_validation": False})
    assert not result.success and result.error.code == "RESTRICTION_WEAKENED"


@pytest.mark.parametrize("key,bad", [
    ("research.max_resource_load", -0.01),
    ("research.max_resource_load", 1.01),
    ("research.minimum_quality_score", 1.1),
    ("research.max_concurrent_scenarios", 0),
    ("optimization.maximum_runs", -1),
    ("general.scheduler_seconds", 0),
])
def test_numeric_bounds_are_enforced(engine, key, bad):
    result = engine.build_candidate(custom={key: bad})
    assert not result.success and result.error.code == "CONFIGURATION_INVALID"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_rejected(engine, bad):
    result = engine.build_candidate(custom={"research.max_resource_load": bad})
    assert not result.success


def test_invalid_timeframe_and_order_rejected(engine):
    invalid_name = engine.build_candidate(custom={"timeframes.context": "M5"})
    invalid_order = engine.build_candidate(custom={
        "timeframes.context": "M15", "timeframes.strategy": "H1", "timeframes.execution": "H4"
    })
    assert not invalid_name.success and not invalid_order.success


def test_only_fictional_instruments_allowed(engine):
    assert engine.build_candidate(custom={"instruments.enabled": ("FICTIONAL_BETA",)}).success
    assert not engine.build_candidate(custom={"instruments.enabled": ("EURUSD",)}).success
    assert not engine.build_candidate(custom={"instruments.enabled": ()}).success


def test_research_unit_floor_must_not_exceed_start(engine):
    result = engine.build_candidate(custom={"research.starting_units": 10.0, "research.minimum_units": 11.0})
    assert not result.success


def test_unknown_field_and_secret_like_field_rejected(engine):
    assert not engine.build_candidate(custom={"MaxPortolioRisk": 5}).success
    assert not engine.build_candidate(custom={"provider.api_key": "secret"}).success


def test_deprecated_field_warns_without_silent_repair(engine):
    result = engine.build_candidate(custom={"legacy.timer_interval": 30})
    assert result.success
    assert result.value.validation_status is ValidationStatus.VALID_WITH_WARNINGS
    assert "deprecated configuration field" in result.value.warnings


def test_schema_classification_and_rejection(engine):
    assert classify_schema(CONFIG_SCHEMA_VERSION) is SchemaCompatibility.CURRENT
    assert classify_schema("1.9") is SchemaCompatibility.COMPATIBLE
    assert classify_schema("0.9") is SchemaCompatibility.MIGRATION_REQUIRED
    assert classify_schema("2.0") is SchemaCompatibility.INCOMPATIBLE
    assert classify_schema(None) is SchemaCompatibility.CORRUPTED
    assert not engine.build_candidate(schema_version="2.0").success


def test_snapshot_is_immutable(engine):
    snapshot = engine.build_candidate().value
    with pytest.raises(TypeError): snapshot.values["general.enabled"] = False
    with pytest.raises(TypeError): snapshot.provenance["general.enabled"] = "changed"


def test_hash_and_serialization_are_deterministic(engine):
    first = engine.build_candidate().value
    second = engine.build_candidate().value
    assert first.configuration_hash == second.configuration_hash
    assert first.snapshot_id == second.snapshot_id
    assert canonical_serialize({"b": 2, "a": 1}, ResearchProfile.BALANCED) == \
           canonical_serialize({"a": 1, "b": 2}, ResearchProfile.BALANCED)
    assert configuration_hash({"b": 2, "a": 1}, ResearchProfile.BALANCED) == \
           configuration_hash({"a": 1, "b": 2}, ResearchProfile.BALANCED)


def test_profile_hashes_differ(engine):
    hashes = {engine.build_candidate(profile).value.configuration_hash for profile in ResearchProfile}
    assert len(hashes) == 4


def test_diff_reports_values_sources_and_safety(engine):
    a = engine.build_candidate(ResearchProfile.BALANCED).value
    b = engine.build_candidate(ResearchProfile.CONSERVATIVE).value
    diff = diff_snapshots(a, b)
    assert "research.max_resource_load" in diff.changed
    assert diff.added == {} and diff.removed == {}
    assert diff.safety_relevant == ()


def test_safe_activation_required_and_switch_is_atomic(engine):
    candidate = engine.build_candidate().value
    assert not engine.activate(candidate, safe_boundary=False).success
    assert engine.active_snapshot is None
    assert engine.activate(candidate, safe_boundary=True).success
    assert engine.active_snapshot is candidate


def test_invalid_candidate_rolls_back(engine):
    initial = engine.switch_profile(ResearchProfile.BALANCED, safe_boundary=True)
    assert initial.success
    retained = engine.active_snapshot
    rejected = engine.switch_profile(ResearchProfile.CUSTOM, safe_boundary=True,
                                     custom={"research.max_resource_load": 2.0})
    assert not rejected.success
    assert engine.active_snapshot is retained
    assert engine.last_valid_snapshot is retained


def test_profile_comparison_is_configuration_only(engine):
    snapshots = {profile.name: engine.build_candidate(profile).value for profile in ResearchProfile}
    assert snapshots["CONSERVATIVE"].values["research.max_resource_load"] < \
           snapshots["BALANCED"].values["research.max_resource_load"] < \
           snapshots["AGGRESSIVE"].values["research.max_resource_load"]
    for snapshot in snapshots.values():
        assert all(snapshot.values[key] == expected for key, expected in HARD_SAFETY_VALUES.items())
        assert snapshot.values["research.max_resource_load"] <= MAX_RESEARCH_RESOURCE_LOAD
        assert snapshot.values["research.max_concurrent_scenarios"] <= MAX_CONCURRENT_SCENARIOS


def test_schema_definitions_have_explicit_units_and_policies():
    assert SCHEMA
    for definition in SCHEMA.values():
        assert definition.unit
        assert definition.override_policy is not None


def test_validator_returns_structured_issues():
    values = {key: definition.default for key, definition in SCHEMA.items()
              if definition.deprecated_replacement is None}
    values["research.max_resource_load"] = -1.0
    validation = ConfigurationValidator().validate(values)
    assert validation.status is ValidationStatus.INVALID
    issue = next(item for item in validation.issues if item.path == "research.max_resource_load")
    assert issue.code == "BELOW_MINIMUM" and issue.constraint == ">=0.0"


def test_seed_persists_in_snapshot(engine):
    snapshot = engine.build_candidate(custom={"research.seed": 123, "simulation.seed": 456}).value
    assert snapshot.values["research.seed"] == 123
    assert snapshot.values["simulation.seed"] == 456


def test_checkpoint_policy_cannot_disable_recoverability(engine):
    snapshot = engine.build_candidate().value
    assert snapshot.values["persistence.retention_generations"] >= 2
    assert snapshot.values["persistence.maximum_uncheckpointed_events"] >= 1
    assert not engine.build_candidate(custom={"persistence.retention_generations": 1}).success
    assert not engine.build_candidate(custom={"persistence.maximum_uncheckpointed_events": 0}).success
