"use strict";

const ENDPOINT = "/api/v1/research-lifecycle-quality";

const DOMAIN_LABELS = {
    research_lifecycle: "Research Lifecycle",
    observation_quality: "Observation Quality",
    research_reliability: "Research Reliability",
    temporal_quality: "Temporal Quality",
    system_safety: "System Safety",
};

function text(value) {
    if (value === true) {
        return "Yes";
    }

    if (value === false) {
        return "No";
    }

    if (value === null || value === undefined) {
        return "UNAVAILABLE";
    }

    return String(value);
}

function renderDomains(payload) {
    const grid = document.getElementById("domain-grid");

    if (!grid) {
        return;
    }

    grid.replaceChildren();

    for (const [key, domain] of Object.entries(payload.domains || {})) {
        const card = document.createElement("article");
        card.className = "card";

        const title = document.createElement("h3");
        title.textContent = DOMAIN_LABELS[key] || key;

        const implementation = document.createElement("p");
        implementation.textContent =
            `Implementation: ${text(domain.implementation_state)}`;

        const active = document.createElement("p");
        active.textContent =
            `Runtime Active: ${text(domain.runtime_active)}`;

        const authority = document.createElement("p");
        authority.textContent =
            `Runtime Authority: ${text(domain.runtime_authority)}`;

        const current = document.createElement("p");
        current.textContent =
            `Current State: ${
                domain.current_state_available
                    ? "AVAILABLE"
                    : "UNAVAILABLE"
            }`;

        const version = document.createElement("p");
        version.textContent =
            `Engine Version: ${text(domain.engine_version)}`;

        card.append(
            title,
            implementation,
            active,
            authority,
            current,
            version,
        );

        grid.appendChild(card);
    }
}

function renderSafety(payload) {
    const status = document.getElementById("evidence-status");

    if (!status) {
        return;
    }

    const currentState = payload.current_state || {};
    const boundary = payload.safety_boundary || {};

    status.textContent =
        `Evidence loaded. Environment: ${text(boundary.environment)}. ` +
        `Current State: ${text(currentState.status)}.`;
}

async function loadAssuranceEvidence() {
    const status = document.getElementById("evidence-status");

    try {
        const response = await fetch(ENDPOINT, {
            headers: {
                Accept: "application/json",
            },
        });

        if (!response.ok) {
            throw new Error(
                `Evidence request failed with HTTP ${response.status}`
            );
        }

        const payload = await response.json();

        renderDomains(payload);
        renderSafety(payload);
    } catch (error) {
        if (status) {
            status.textContent =
                "Assurance evidence is currently unavailable.";
        }

        console.error(error);
    }
}

document.addEventListener(
    "DOMContentLoaded",
    loadAssuranceEvidence,
);
