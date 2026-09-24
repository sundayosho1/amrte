from __future__ import annotations

from typing import Any


PRODUCT = "Operational Readiness & Evidence Console"
ENVIRONMENT = "RESEARCH"

IMPLEMENTED = "IMPLEMENTED"
CONFIGURED = "CONFIGURED"
OBSERVED = "OBSERVED"
QUALIFIED = "QUALIFIED"
UNAVAILABLE = "UNAVAILABLE"
NOT_VERIFIED = "NOT_VERIFIED"


def _domain(
    evidence_state: str,
    evidence: list[str],
    limitations: list[str],
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_state": evidence_state,
        "evidence": evidence,
        "limitations": limitations,
    }
    result.update(extra)
    return result


def operational_readiness_projection(
    runtime,
) -> dict[str, Any]:
    """
    Read-only operational readiness projection.

    This function reports evidence from the existing runtime authority.
    It does not start, stop, restart, checkpoint, recover, restore,
    diagnose, update, or otherwise mutate AMRTE.
    """

    engine = runtime.engine

    if engine is None:
        raise RuntimeError(
            "operational readiness requires the active "
            "application runtime"
        )

    execution = engine.registry.require("execution")
    execution_provider = type(execution).__name__

    recovery_report = runtime.recovery_report
    last_checkpoint = runtime.last_checkpoint

    recovery_evidence: list[str] = []
    recovery_limitations: list[str] = []

    if recovery_report is None:
        recovery_evidence.append(
            "No prior checkpoint recovery was required "
            "for this application lifecycle."
        )
        recovery_state = OBSERVED
    else:
        recovery_evidence.extend(
            [
                (
                    "Recovery outcome: "
                    f"{recovery_report.outcome.name}"
                ),
                (
                    "Recovery confidence: "
                    f"{recovery_report.confidence.name}"
                ),
                (
                    "Recovery epoch: "
                    f"{recovery_report.recovery_epoch}"
                ),
            ]
        )
        recovery_state = OBSERVED

    if last_checkpoint is not None:
        recovery_evidence.append(
            "Latest runtime checkpoint observed: "
            f"{last_checkpoint.checkpoint_id}"
        )
    else:
        recovery_limitations.append(
            "No runtime-owned checkpoint has been recorded "
            "during this application lifecycle."
        )

    domains = {
        "runtime_lifecycle": _domain(
            OBSERVED,
            [
                f"Runtime state: {runtime.state}",
                (
                    "Lifecycle authority: "
                    "PersistentResearchRuntime"
                ),
                "Web lifecycle owner: FastAPI lifespan",
                "CLI host: run_amrte.py",
            ],
            [
                "This endpoint reports lifecycle evidence only; "
                "it exposes no process-control operation."
            ],
        ),
        "persistence_recovery": _domain(
            recovery_state,
            recovery_evidence,
            recovery_limitations,
        ),
        "observability": _domain(
            CONFIGURED,
            [
                (
                    "Persistent JSONL log path: "
                    f"{runtime.log_path}"
                ),
                "Persistent logging is attached by "
                "PersistentResearchRuntime.",
            ],
            [
                "This projection does not mutate or rotate logs."
            ],
        ),
        "health_diagnostics": _domain(
            IMPLEMENTED,
            [
                "HealthService is registered with the "
                "authoritative runtime.",
                "DeploymentDiagnosticsEngine exists as an "
                "implemented deployment-domain capability.",
            ],
            [
                "DeploymentDiagnosticsEngine is not the "
                "authoritative runtime health owner.",
                "No deployment diagnostics engine is "
                "instantiated by this projection.",
            ],
        ),
        "windows_host": _domain(
            NOT_VERIFIED,
            [
                "Windows-compatible runtime and deployment "
                "guidance are present.",
                "Native Windows execution has been observed "
                "during controlled qualification work.",
            ],
            [
                "Full native Windows service/process-manager "
                "qualification has not been completed.",
                "An approved Windows service/process manager "
                "remains to be qualified for unattended "
                "operation and graceful shutdown.",
            ],
            native_windows_qualification=False,
        ),
        "research_safety": _domain(
            QUALIFIED,
            [
                f"Execution provider: {execution_provider}",
                "Runtime environment: RESEARCH",
                "Financial execution capability: disabled",
                "Broker connectivity: disabled",
                "Account connectivity: disabled",
            ],
            [],
        ),
    }

    return {
        "product": PRODUCT,
        "environment": ENVIRONMENT,
        "read_only": True,
        "domains": domains,
        "runtime_authority": {
            "authority": "PersistentResearchRuntime",
            "parallel_runtime_authority": False,
            "web_lifecycle_owner": "FastAPI lifespan",
            "cli_host": "run_amrte.py",
        },
        "execution_boundary": {
            "status": "PROHIBITED",
            "provider": execution_provider,
            "financial_execution": False,
            "broker_connectivity": False,
            "account_connectivity": False,
        },
        "deployment_diagnostics": {
            "implementation": "DeploymentDiagnosticsEngine",
            "runtime_authority": False,
            "runtime_active": False,
            "current_state_available": False,
        },
    }
