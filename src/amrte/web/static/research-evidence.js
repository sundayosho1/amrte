"use strict";

const CAPABILITY_IDS = Object.freeze([
    "research_performance_analytics",
    "deterministic_experiments",
    "robustness_validation",
    "research_lifecycle",
    "observation_quality",
    "research_reliability",
    "temporal_quality_protection",
    "system_safety",
]);

function byId(id) {
    return document.getElementById(id);
}

function text(id, value) {
    const element = byId(id);

    if (!element) {
        return;
    }

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        element.textContent = "?";
        return;
    }

    element.textContent = String(value);
}

function booleanState(value) {
    return value === true ? "YES" : "NO";
}

function capabilityLabel(identifier) {
    return String(identifier)
        .split("_")
        .map((part) => {
            if (!part) {
                return "";
            }

            return (
                part.charAt(0).toUpperCase() +
                part.slice(1)
            );
        })
        .join(" ");
}

function renderCapabilities(capabilities) {
    const container = byId(
        "research-capability-list"
    );

    if (!container) {
        return;
    }

    container.replaceChildren();

    const source = Array.isArray(capabilities)
        ? capabilities
        : [];

    for (const expectedId of CAPABILITY_IDS) {
        const capability = source.find(
            (item) => item.capability === expectedId
        );

        const item = document.createElement("div");
        item.className = "detail-item";

        const heading = document.createElement("span");
        heading.textContent = capabilityLabel(
            expectedId
        );

        const status = document.createElement(
            "strong"
        );

        status.textContent = capability
            ? String(capability.status)
            : "UNAVAILABLE";

        item.append(heading, status);

        const details = document.createElement("span");
        details.textContent = capability
            ? (
                "Implemented: " +
                booleanState(capability.implemented) +
                " | Runtime Active: " +
                booleanState(capability.runtime_active) +
                " | Evidence Available: " +
                booleanState(capability.evidence_available)
            )
            : (
                "Implemented: NO" +
                " | Runtime Active: NO" +
                " | Evidence Available: NO"
            );

        item.append(details);
        container.append(item);
    }
}

function renderResearchEvidence(data) {
    const runtime = data.runtime || {};
    const configuration = data.configuration || {};
    const boundary = data.execution_boundary || {};

    text(
        "runtime-state",
        runtime.state
    );

    text(
        "runtime-environment",
        runtime.environment
    );

    text(
        "runtime-version",
        runtime.version
    );

    text(
        "configuration-snapshot",
        configuration.snapshot_id
    );

    text(
        "configuration-hash",
        configuration.configuration_hash
    );

    text(
        "execution-boundary",
        boundary.status
    );

    text(
        "execution-provider",
        boundary.provider
    );

    text(
        "financial-execution",
        boundary.financial_execution === false
            ? "PROHIBITED"
            : "UNAVAILABLE"
    );

    text(
        "broker-connectivity",
        boundary.broker_connectivity === false
            ? "PROHIBITED"
            : "UNAVAILABLE"
    );

    text(
        "account-connectivity",
        boundary.account_connectivity === false
            ? "PROHIBITED"
            : "UNAVAILABLE"
    );

    renderCapabilities(data.research_capabilities);
}

function showError() {
    const error = byId(
        "research-evidence-error"
    );

    if (error) {
        error.hidden = false;
    }
}

async function loadResearchEvidence() {
    try {
        const response = await fetch(
            "/api/v1/research-evidence",
            {
                method: "GET",
                headers: {
                    "Accept": "application/json",
                },
            }
        );

        if (!response.ok) {
            throw new Error(
                "Research evidence projection unavailable"
            );
        }

        const data = await response.json();

        renderResearchEvidence(data);
    }
    catch (_error) {
        showError();
    }
}

loadResearchEvidence();

