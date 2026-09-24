"use strict";

function text(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "?";
    }

    return String(value);
}

function state(value) {
    return value ? "YES" : "NO";
}

function registered(value) {
    return value
        ? "REGISTERED"
        : "NOT REGISTERED";
}

function available(value) {
    return value
        ? "AVAILABLE"
        : "UNAVAILABLE";
}

function detailRow(label, value) {
    return `
        <div class="detail-row">
            <span>${label}</span>
            <strong>${text(value)}</strong>
        </div>
    `;
}

function renderDataset(data) {
    const dataset = data.dataset_identity;

    document.getElementById(
        "dataset-details"
    ).innerHTML = [
        detailRow(
            "Configured dataset",
            dataset.configured_dataset_id
        ),
        detailRow(
            "Persistence dataset",
            dataset.persistence_dataset_id
        ),
        detailRow(
            "Persistence fingerprint",
            dataset.persistence_dataset_fingerprint
        ),
        detailRow(
            "Runtime provider",
            registered(
                dataset.runtime_dataset_provider_registered
            )
        ),
        detailRow(
            "Runtime dataset service",
            dataset.runtime_dataset_service
        ),
    ].join("");
}

function renderProviderPolicy(data) {
    const policy = data.provider_policy;

    document.getElementById(
        "provider-details"
    ).innerHTML = [
        detailRow(
            "Market-data provider",
            policy.market_data_provider_type
        ),
        detailRow(
            "Market data offline",
            state(policy.market_data_offline)
        ),
        detailRow(
            "Event provider",
            policy.event_provider_type
        ),
        detailRow(
            "Events offline",
            state(policy.events_offline)
        ),
        detailRow(
            "Runtime event provider",
            registered(
                policy.event_provider_registered
            )
        ),
        detailRow(
            "Runtime event service",
            policy.runtime_event_service
        ),
    ].join("");
}

function renderTemporal(data) {
    const temporal = data.temporal_integrity;

    document.getElementById(
        "temporal-details"
    ).innerHTML = [
        detailRow(
            "No look ahead",
            state(temporal.no_look_ahead)
        ),
        detailRow(
            "Configured value",
            state(temporal.configured_value)
        ),
        detailRow(
            "As-of market data",
            available(
                temporal.as_of_market_data_supported
            )
        ),
        detailRow(
            "As-of historical events",
            available(
                temporal
                    .as_of_historical_events_supported
            )
        ),
    ].join("");
}

function renderReplay(data) {
    const replay = data.replay_authority;

    document.getElementById(
        "replay-details"
    ).innerHTML = [
        detailRow(
            "Authoritative service",
            registered(
                replay
                    .authoritative_replay_service_registered
            )
        ),
        detailRow(
            "Runtime replay service",
            replay.runtime_replay_service
        ),
        detailRow(
            "Replay control",
            available(
                replay.replay_control_available
            )
        ),
        detailRow(
            "Mutation enabled",
            state(replay.mutation_enabled)
        ),
        detailRow(
            "Reason",
            replay.reason
        ),
    ].join("");
}

function renderConfiguration(data) {
    const config = data.configuration;

    document.getElementById(
        "configuration-details"
    ).innerHTML = [
        detailRow(
            "Runtime mode",
            config.runtime_mode
        ),
        detailRow(
            "Snapshot ID",
            config.configuration_snapshot_id
        ),
        detailRow(
            "Configuration hash",
            config.configuration_hash
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

function renderCapabilities(data) {
    const capabilities =
        data.implemented_capabilities;

    const container = document.getElementById(
        "implemented-capabilities"
    );

    document.getElementById(
        "capability-count"
    ).textContent =
        `${capabilities.length} capabilities`;

    container.innerHTML = capabilities.map(
        capability => `
            <article class="control-card">
                <div class="control-card-header">
                    <strong>
                        ${text(capability.capability)}
                    </strong>

                    <span class="status-pill ${
                        capability.runtime_authoritative
                            ? ""
                            : "unavailable"
                    }">
                        ${
                            capability.runtime_authoritative
                                ? "AUTHORITATIVE"
                                : "NON-AUTHORITATIVE"
                        }
                    </span>
                </div>

                <span class="control-category">
                    ${text(capability.component)}
                </span>

                <p>
                    Implementation:
                    ${
                        capability.implemented
                            ? "AVAILABLE"
                            : "UNAVAILABLE"
                    }
                </p>
            </article>
        `
    ).join("");
}

function renderRegisteredServices(data) {
    const services = data.registered_services;

    const container = document.getElementById(
        "registered-services"
    );

    const entries = Array.isArray(services)
        ? services.map(
            service => [
                service.name,
                service,
            ]
        )
        : Object.entries(services);

    document.getElementById(
        "service-count"
    ).textContent =
        `${entries.length} services`;

    container.innerHTML = entries.map(
        ([name, service]) => `
            <article class="service-registry-card">
                <div class="service-registry-header">
                    <div class="service-registry-icon">
                        ${text(name)
                            .slice(0, 1)
                            .toUpperCase()}
                    </div>

                    <div class="service-registry-title">
                        <strong>
                            ${text(name)}
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

async function loadDatasetReplay() {
    const response = await fetch(
        "/api/v1/dataset-replay",
        {
            method: "GET",
            headers: {
                "Accept": "application/json",
            },
        }
    );

    if (!response.ok) {
        throw new Error(
            `Dataset & Replay API returned ${response.status}`
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
        "metric-dataset"
    ).textContent =
        text(
            data.dataset_identity
                .configured_dataset_id
        );

    document.getElementById(
        "metric-provider"
    ).textContent =
        text(
            data.provider_policy
                .market_data_provider_type
        );

    document.getElementById(
        "metric-temporal"
    ).textContent =
        data.temporal_integrity.no_look_ahead
            ? "ENFORCED"
            : "NOT ENFORCED";

    document.getElementById(
        "metric-replay"
    ).textContent =
        data.replay_authority
            .authoritative_replay_service_registered
            ? "REGISTERED"
            : "NOT REGISTERED";

    renderDataset(data);
    renderProviderPolicy(data);
    renderTemporal(data);
    renderReplay(data);
    renderConfiguration(data);
    renderExecution(data);
    renderCapabilities(data);
    renderRegisteredServices(data);
}

loadDatasetReplay().catch(error => {
    document.getElementById(
        "runtime-state"
    ).textContent = "ERROR";

    console.error(
        "AMRTE Dataset & Replay:",
        error
    );
});
