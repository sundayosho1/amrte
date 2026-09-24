"use strict";

const ENDPOINT = "/api/v1/health-diagnostics";


function byId(id) {
    return document.getElementById(id);
}


function text(id, value) {
    const element = byId(id);

    if (!element) {
        return;
    }

    if (
        value === null
        || value === undefined
        || value === ""
    ) {
        element.textContent = "?";
        return;
    }

    element.textContent = String(value);
}


function yesNo(value) {
    return value ? "YES" : "NO";
}


function allowed(value) {
    return value ? "AVAILABLE" : "UNAVAILABLE";
}


function renderServices(services) {
    const target = byId(
        "mandatory-services"
    );

    const rows = Object.entries(
        services || {}
    )
        .sort(([left], [right]) =>
            left.localeCompare(right)
        )
        .map(([name, item]) => `
            <tr>
                <td>${escapeHtml(name)}</td>
                <td>${escapeHtml(item.type || "?")}</td>
                <td>${escapeHtml(item.status || "UNKNOWN")}</td>
            </tr>
        `)
        .join("");

    target.innerHTML = `
        <table>
            <thead>
                <tr>
                    <th>Service</th>
                    <th>Authority</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;
}


function renderCapabilities(capabilities) {
    const target = byId(
        "diagnostic-capabilities"
    );

    const labels = {
        view_health: "View health",
        view_service_status:
            "View service status",
        view_observability_health:
            "View observability health",
        view_persistence_health:
            "View persistence health",
        run_diagnostics:
            "Diagnostic execution",
        resolve_alerts:
            "Alert resolution",
        prepare_updates:
            "Update preparation",
        restore_state:
            "State restoration",
        mutate_health:
            "Health mutation",
    };

    const rows = Object.entries(
        capabilities || {}
    )
        .map(([name, value]) => `
            <tr>
                <td>${escapeHtml(labels[name] || name)}</td>
                <td>${escapeHtml(allowed(value))}</td>
            </tr>
        `)
        .join("");

    target.innerHTML = `
        <table>
            <thead>
                <tr>
                    <th>Capability</th>
                    <th>Availability</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;
}


function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function render(payload) {
    text(
        "engine-state",
        payload.runtime.state
    );

    text(
        "runtime-environment",
        payload.runtime.environment
    );

    text(
        "runtime-version",
        payload.runtime.version
    );

    text(
        "readiness-value",
        payload.readiness.ready
            ? "READY"
            : "NOT READY"
    );

    text(
        "readiness-badge",
        payload.readiness.ready
            ? "READY"
            : "NOT READY"
    );

    text(
        "readiness-reasons",
        payload.readiness.reasons.length
            ? payload.readiness.reasons.join(", ")
            : "NONE"
    );

    renderServices(
        payload.mandatory_services
    );

    text(
        "observability-status",
        payload.observability.status
    );

    text(
        "observability-chain",
        yesNo(
            payload.observability.chain_valid
        )
    );

    text(
        "dropped-diagnostics",
        payload.observability
            .dropped_diagnostics
    );

    text(
        "repository-type",
        payload.persistence.repository
    );

    text(
        "storage-health",
        payload.persistence.storage_health
    );

    text(
        "persistence-chain",
        yesNo(
            payload.persistence.chain_valid
        )
    );

    text(
        "recovery-ready",
        yesNo(
            payload.recovery.ready
        )
    );

    text(
        "recovery-epoch",
        payload.recovery.epoch
    );

    text(
        "configuration-snapshot",
        payload.configuration.snapshot_id
    );

    text(
        "configuration-hash",
        payload.configuration.configuration_hash
    );

    text(
        "configuration-validation",
        payload.configuration.validation_status
    );

    text(
        "configuration-schema",
        payload.configuration.schema_version
    );

    text(
        "execution-status",
        payload.execution_boundary.status
    );

    text(
        "execution-provider",
        payload.execution_boundary.provider
    );

    text(
        "financial-execution",
        allowed(
            payload.execution_boundary
                .financial_execution
        )
    );

    text(
        "broker-connectivity",
        allowed(
            payload.execution_boundary
                .broker_connectivity
        )
    );

    text(
        "account-connectivity",
        allowed(
            payload.execution_boundary
                .account_connectivity
        )
    );

    renderCapabilities(
        payload.capabilities
    );

    text(
        "health-service",
        payload.authority.health_service
    );

    text(
        "health-source",
        payload.authority.source
    );

    text(
        "parallel-health",
        yesNo(
            payload.authority
                .parallel_health_engine
        )
    );

    text(
        "diagnostic-execution",
        yesNo(
            payload.authority
                .diagnostic_execution
        )
    );
}


async function loadHealthDiagnostics() {
    try {
        const response = await fetch(
            ENDPOINT,
            {
                method: "GET",
                headers: {
                    "Accept":
                        "application/json",
                },
            }
        );

        if (!response.ok) {
            throw new Error(
                `HTTP ${response.status}`
            );
        }

        const payload = await response.json();

        render(payload);

    } catch (error) {
        const notice = byId(
            "health-diagnostics-error"
        );

        if (notice) {
            notice.hidden = false;
        }

        console.error(
            "Health diagnostics unavailable",
            error
        );
    }
}


document.addEventListener(
    "DOMContentLoaded",
    loadHealthDiagnostics
);
