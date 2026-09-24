"use strict";

function text(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    return String(value);
}

function yesNo(value) {
    return value ? "AVAILABLE" : "UNAVAILABLE";
}

function detailRow(label, value) {
    return `
        <div class="detail-row">
            <span>${label}</span>
            <strong>${text(value)}</strong>
        </div>
    `;
}

function renderAuthority(data) {
    const authority = data.authority;

    document.getElementById(
        "authority-details"
    ).innerHTML = [
        detailRow(
            "Controls available",
            yesNo(authority.controls_available)
        ),
        detailRow(
            "Mutation enabled",
            authority.mutation_enabled
                ? "YES"
                : "NO"
        ),
        detailRow(
            "Authoritative service",
            authority
                .authoritative_control_service_registered
                ? "REGISTERED"
                : "NOT REGISTERED"
        ),
        detailRow(
            "Reason",
            authority.reason
        ),
    ].join("");
}

function renderExecution(data) {
    const boundary = data.execution_boundary;

    document.getElementById(
        "execution-details"
    ).innerHTML = [
        detailRow(
            "Capability",
            boundary.capability
        ),
        detailRow(
            "Provider",
            boundary.provider
        ),
        detailRow(
            "Financial execution",
            boundary.financial_execution_available
                ? "AVAILABLE"
                : "NOT AVAILABLE"
        ),
    ].join("");
}

function renderControls(data) {
    const controls = data.governed_controls;
    const container = document.getElementById(
        "governed-controls"
    );

    document.getElementById(
        "control-count"
    ).textContent =
        `${controls.length} controls`;

    container.innerHTML = controls.map(
        control => `
            <article class="control-card unavailable">
                <div class="control-card-header">
                    <strong>
                        ${text(control.action)}
                    </strong>

                    <span class="status-pill unavailable">
                        ${
                            control.available
                                ? "AVAILABLE"
                                : "UNAVAILABLE"
                        }
                    </span>
                </div>

                <span class="control-category">
                    ${text(control.category)}
                </span>

                <p>
                    ${text(control.reason)}
                </p>
            </article>
        `
    ).join("");
}

function renderControlServices(data) {
    const container = document.getElementById(
        "control-services"
    );

    container.innerHTML = Object.entries(
        data.control_services
    ).map(
        ([name, available]) => `
            <article class="authority-item">
                <span>${name}</span>

                <strong class="${
                    available
                        ? "authority-present"
                        : "authority-absent"
                }">
                    ${
                        available
                            ? "REGISTERED"
                            : "NOT REGISTERED"
                    }
                </strong>
            </article>
        `
    ).join("");
}

function renderRegisteredServices(data) {
    const services = data.registered_services;
    const body = document.getElementById(
        "registered-services"
    );

    document.getElementById(
        "service-count"
    ).textContent =
        `${services.length} services`;

    body.innerHTML = services.map(
        service => `
            <article class="service-registry-card">
                <div class="service-registry-header">
                    <div class="service-registry-icon">
                        ${text(service.name)
                            .slice(0, 1)
                            .toUpperCase()}
                    </div>

                    <div class="service-registry-title">
                        <strong>
                            ${text(service.name)}
                        </strong>

                        <span class="service-status">
                            REGISTERED
                        </span>
                    </div>
                </div>

                <div class="service-registry-detail">
                    <span>Implementation</span>
                    <strong>
                        ${text(service.type)}
                    </strong>
                </div>

                <div class="service-registry-detail">
                    <span>Module</span>
                    <code>
                        ${text(service.module)}
                    </code>
                </div>
            </article>
        `
    ).join("");
}

async function loadResearchControls() {
    const response = await fetch(
        "/api/v1/research-controls",
        {
            method: "GET",
            headers: {
                "Accept": "application/json",
            },
        }
    );

    if (!response.ok) {
        throw new Error(
            `Research Controls API returned ${response.status}`
        );
    }

    const data = await response.json();

    document.getElementById(
        "runtime-state"
    ).textContent =
        data.runtime.state;

    const runtimeStatusDot =
        document.getElementById(
            "runtime-status-dot"
        );

    if (runtimeStatusDot) {
        runtimeStatusDot.classList.toggle(
            "running",
            data.runtime.state === "RUNNING"
        );
    }

    document.getElementById(
        "metric-runtime"
    ).textContent =
        data.runtime.state;

    document.getElementById(
        "metric-environment"
    ).textContent =
        data.runtime.environment;

    document.getElementById(
        "metric-authority"
    ).textContent =
        data.authority.controls_available
            ? "AVAILABLE"
            : "UNAVAILABLE";

    document.getElementById(
        "metric-execution"
    ).textContent =
        data.execution_boundary.capability;

    renderAuthority(data);
    renderExecution(data);
    renderControls(data);
    renderControlServices(data);
    renderRegisteredServices(data);
}

loadResearchControls().catch(error => {
    document.getElementById(
        "runtime-state"
    ).textContent = "ERROR";

    console.error(
        "AMRTE Research Controls:",
        error
    );
});
