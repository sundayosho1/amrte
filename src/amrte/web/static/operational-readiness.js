"use strict";

const API = "/api/v1/operational-readiness";

const byId = (id) => document.getElementById(id);

const text = (value) => {
    if (value === null || value === undefined) {
        return "—";
    }

    if (typeof value === "boolean") {
        return value ? "YES" : "NO";
    }

    return String(value);
};

const setText = (id, value) => {
    const element = byId(id);

    if (element) {
        element.textContent = text(value);
    }
};

const renderList = (id, values, emptyText) => {
    const root = byId(id);

    if (!root) {
        return;
    }

    root.innerHTML = "";

    const items = Array.isArray(values) ? values : [];

    if (items.length === 0) {
        const paragraph = document.createElement("p");
        paragraph.textContent = emptyText;
        root.appendChild(paragraph);
        return;
    }

    const list = document.createElement("ul");

    items.forEach((value) => {
        const item = document.createElement("li");
        item.textContent = text(value);
        list.appendChild(item);
    });

    root.appendChild(list);
};

const renderDomain = (name, domain) => {
    const value = domain || {};

    setText(
        `${name}-state`,
        value.evidence_state
    );

    renderList(
        `${name}-evidence`,
        value.evidence,
        "No evidence reported."
    );

    renderList(
        `${name}-limitations`,
        value.limitations,
        "No limitations reported."
    );
};

const render = (data) => {
    const authority = data.runtime_authority || {};
    const boundary = data.execution_boundary || {};
    const deployment = data.deployment_diagnostics || {};
    const domains = data.domains || {};
    const windows = domains.windows_host || {};

    setText(
        "runtime-environment",
        data.environment
    );

    setText(
        "runtime-authority",
        authority.authority
    );

    setText(
        "execution-status",
        boundary.status
    );

    setText(
        "windows-native-status",
        windows.native_windows_qualification
            ? "QUALIFIED"
            : "NOT VERIFIED"
    );

    renderDomain(
        "runtime-lifecycle",
        domains.runtime_lifecycle
    );

    renderDomain(
        "persistence-recovery",
        domains.persistence_recovery
    );

    renderDomain(
        "observability",
        domains.observability
    );

    renderDomain(
        "health-diagnostics",
        domains.health_diagnostics
    );

    renderDomain(
        "windows-host",
        domains.windows_host
    );

    renderDomain(
        "research-safety",
        domains.research_safety
    );

    setText(
        "deployment-implementation",
        deployment.implementation
    );

    setText(
        "deployment-authority",
        deployment.runtime_authority
    );

    setText(
        "deployment-active",
        deployment.runtime_active
    );

    setText(
        "deployment-current-state",
        deployment.current_state_available
    );
};

const showError = (failure) => {
    const error = byId(
        "operational-readiness-error"
    );

    if (!error) {
        return;
    }

    error.hidden = false;
    error.textContent =
        `Unable to load operational readiness evidence: ${
            failure instanceof Error
                ? failure.message
                : String(failure)
        }`;
};

const loadOperationalReadiness = async () => {
    try {
        const response = await fetch(
            API,
            {
                method: "GET",
                headers: {
                    "Accept": "application/json"
                }
            }
        );

        if (!response.ok) {
            throw new Error(
                `HTTP ${response.status}`
            );
        }

        const data = await response.json();

        render(data);
    } catch (failure) {
        showError(failure);
    }
};

loadOperationalReadiness();
