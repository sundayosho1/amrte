"use strict";

const byId = (id) => document.getElementById(id);

function text(id, value) {
    const element = byId(id);
    if (element) {
        element.textContent =
            value === null || value === undefined || value === ""
                ? "—"
                : String(value);
    }
}

function yesNo(value) {
    return value ? "Yes" : "No";
}

async function loadDashboard() {
    const statusText = byId("runtime-status-text");
    const statusDot = byId("runtime-status-dot");

    try {
        const response = await fetch(
            "/api/v1/dashboard/summary",
            {
                method: "GET",
                headers: {
                    "Accept": "application/json"
                },
                cache: "no-store"
            }
        );

        if (!response.ok) {
            throw new Error(
                `Dashboard API returned ${response.status}`
            );
        }

        const data = await response.json();

        text("runtime-state", data.runtime.state);
        text(
            "runtime-operational",
            yesNo(data.runtime.operational)
        );

        text(
            "configuration-status",
            data.configuration.validation_status
        );
        text(
            "configuration-profile",
            data.configuration.selected_profile
        );
        text(
            "configuration-schema",
            data.configuration.schema_version
        );
        text(
            "configuration-snapshot",
            data.configuration.snapshot_id
        );
        text(
            "configuration-hash",
            data.configuration.configuration_hash
        );

        text(
            "recovery-outcome",
            data.recovery.outcome
        );
        text(
            "recovery-confidence",
            data.recovery.confidence
        );
        text(
            "recovery-ready",
            yesNo(data.recovery.ready)
        );
        text(
            "recovery-epoch",
            data.recovery.recovery_epoch
        );
        text(
            "recovered-checkpoint",
            data.recovery.checkpoint_id
        );

        text(
            "checkpoint-id",
            data.checkpoint.checkpoint_id
        );
        text(
            "checkpoint-sequence",
            data.checkpoint.sequence_number
        );
        text(
            "checkpoint-previous",
            data.checkpoint.previous_checkpoint_id
        );
        text(
            "checkpoint-shutdown",
            data.checkpoint.shutdown_status
        );

        text(
            "chain-valid",
            yesNo(data.persistence.chain_valid)
        );
        text(
            "fallback-used",
            yesNo(data.persistence.fallback_used)
        );

        text(
            "environment",
            data.application.environment
        );
        text(
            "research-mode",
            data.application.research_mode
        );
        text(
            "execution-mode",
            data.application.execution
        );
        text(
            "application-version",
            data.application.version
        );

        statusText.textContent = data.runtime.state;

        if (data.runtime.state === "RUNNING") {
            statusDot.classList.add("running");
        } else {
            statusDot.classList.remove("running");
        }

    } catch (error) {
        statusText.textContent = "UNAVAILABLE";
        statusText.classList.add("error");

        const banner = byId("dashboard-error");

        if (banner) {
            banner.hidden = false;
            banner.textContent =
                `Dashboard data unavailable: ${error.message}`;
        }
    }
}

document.addEventListener(
    "DOMContentLoaded",
    loadDashboard
);
