"use strict";

(() => {
    const API_URL =
        "/api/v1/persistence-recovery";


    function byId(id) {
        return document.getElementById(id);
    }


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


    function booleanText(value) {
        return value ? "YES" : "NO";
    }


    function clear(element) {
        while (element.firstChild) {
            element.removeChild(
                element.firstChild
            );
        }
    }


    function detailRow(label, value) {
        const row =
            document.createElement("div");

        row.className = "detail-row";

        const key =
            document.createElement("span");

        key.textContent = label;

        const content =
            document.createElement("strong");

        content.textContent = text(value);

        row.appendChild(key);
        row.appendChild(content);

        return row;
    }


    function renderObject(id, values) {
        const container = byId(id);

        clear(container);

        for (
            const [label, value]
            of Object.entries(values || {})
        ) {
            container.appendChild(
                detailRow(
                    label,
                    value
                )
            );
        }
    }


    function label(name) {
        return String(name)
            .replaceAll("_", " ")
            .replace(
                /\b\w/g,
                character =>
                    character.toUpperCase()
            );
    }


    function renderHistory(history) {
        const body =
            byId("checkpoint-history");

        clear(body);

        const entries =
            Array.isArray(history)
                ? history
                : [];

        byId(
            "history-count"
        ).textContent =
            `${entries.length} GENERATIONS`;

        if (entries.length === 0) {
            const row =
                document.createElement("tr");

            const cell =
                document.createElement("td");

            cell.colSpan = 6;
            cell.textContent =
                "No checkpoint generations.";

            row.appendChild(cell);
            body.appendChild(row);

            return;
        }

        for (const entry of entries) {
            const row =
                document.createElement("tr");

            const values = [
                entry.sequence_number,
                entry.checkpoint_id,
                entry.previous_checkpoint_id,
                entry.recovery_epoch,
                entry.shutdown_status,
                entry.created_at
            ];

            for (const value of values) {
                const cell =
                    document.createElement("td");

                cell.textContent =
                    text(value);

                row.appendChild(cell);
            }

            body.appendChild(row);
        }
    }


    function render(payload) {
        byId(
            "runtime-state"
        ).textContent =
            text(
                payload.runtime.state
            );

        byId(
            "runtime-status-dot"
        ).classList.toggle(
            "running",
            payload.runtime.state
                === "RUNNING"
        );


        const chainValid =
            payload.chain_integrity.valid;

        byId(
            "chain-badge"
        ).textContent =
            chainValid
                ? "CHAIN VALID"
                : "CHAIN INVALID";

        byId(
            "chain-badge"
        ).classList.toggle(
            "success",
            chainValid
        );

        byId(
            "chain-badge"
        ).classList.toggle(
            "warning",
            !chainValid
        );


        byId(
            "metric-checkpoint"
        ).textContent =
            text(
                payload.checkpoint
                    .checkpoint_id
            );

        byId(
            "metric-chain"
        ).textContent =
            chainValid
                ? "VALID"
                : "INVALID";

        byId(
            "metric-epoch"
        ).textContent =
            text(
                payload.runtime
                    .recovery_epoch
            );

        byId(
            "metric-generations"
        ).textContent =
            text(
                payload.storage
                    .checkpoint_count
            );


        renderObject(
            "authority-details",
            {
                "Repository":
                    payload.authority
                        .repository,

                "Source":
                    payload.authority
                        .source,

                "Parallel repository":
                    booleanText(
                        payload.authority
                            .parallel_repository_created
                    ),

                "Mutation enabled":
                    booleanText(
                        payload.authority
                            .mutation_enabled
                    ),

                "Environment":
                    payload.runtime
                        .environment
            }
        );


        renderObject(
            "checkpoint-details",
            {
                "Available":
                    booleanText(
                        payload.checkpoint
                            .available
                    ),

                "Checkpoint ID":
                    payload.checkpoint
                        .checkpoint_id,

                "Sequence":
                    payload.checkpoint
                        .sequence_number,

                "Shutdown status":
                    payload.checkpoint
                        .shutdown_status,

                "Created":
                    payload.checkpoint
                        .created_at,

                "Configuration snapshot":
                    payload.checkpoint
                        .configuration_snapshot_id,

                "Dataset":
                    payload.checkpoint
                        .dataset_id
            }
        );


        renderObject(
            "lineage-details",
            {
                "Checkpoint ID":
                    payload.lineage
                        .checkpoint_id,

                "Previous checkpoint":
                    payload.lineage
                        .previous_checkpoint_id,

                "Sequence":
                    payload.lineage
                        .sequence_number,

                "Generation count":
                    payload.lineage
                        .generation_count,

                "Chain valid":
                    booleanText(
                        payload.chain_integrity
                            .valid
                    )
            }
        );


        renderObject(
            "configuration-details",
            {
                "Minimum interval (seconds)":
                    payload
                        .persistence_configuration
                        .minimum_interval_seconds,

                "Maximum uncheckpointed events":
                    payload
                        .persistence_configuration
                        .maximum_uncheckpointed_events,

                "Retention generations":
                    payload
                        .persistence_configuration
                        .retention_generations,

                "Maximum checkpoint bytes":
                    payload
                        .persistence_configuration
                        .maximum_checkpoint_bytes
            }
        );


        renderObject(
            "recovery-details",
            {
                "Required":
                    booleanText(
                        payload.recovery
                            .required
                    ),

                "Outcome":
                    payload.recovery
                        .outcome,

                "Confidence":
                    payload.recovery
                        .confidence,

                "Ready":
                    booleanText(
                        payload.recovery
                            .ready
                    ),

                "Fallback used":
                    booleanText(
                        payload.recovery
                            .used_fallback
                    ),

                "Recovery epoch":
                    payload.recovery
                        .recovery_epoch,

                "Checkpoint":
                    payload.recovery
                        .checkpoint_id
            }
        );


        renderObject(
            "recovery-readiness",
            {
                "Ready":
                    booleanText(
                        payload
                            .recovery_readiness
                            .ready
                    ),

                "Chain valid":
                    booleanText(
                        payload
                            .recovery_readiness
                            .chain_valid
                    ),

                "Runtime running":
                    booleanText(
                        payload
                            .recovery_readiness
                            .runtime_running
                    ),

                "Recovery report ready":
                    booleanText(
                        payload
                            .recovery_readiness
                            .recovery_report_ready
                    )
            }
        );


        renderObject(
            "storage-details",
            {
                "State root":
                    payload.storage
                        .state_root,

                "Health":
                    payload.storage
                        .health,

                "Checkpoint count":
                    payload.storage
                        .checkpoint_count,

                "Current present":
                    booleanText(
                        payload.storage
                            .current_present
                    ),

                "Previous present":
                    booleanText(
                        payload.storage
                            .previous_present
                    )
            }
        );


        renderObject(
            "execution-boundary",
            {
                "Capability":
                    payload
                        .execution_boundary
                        .capability,

                "Provider":
                    payload
                        .execution_boundary
                        .provider,

                "Financial execution":
                    booleanText(
                        payload
                            .execution_boundary
                            .financial_execution_available
                    )
            }
        );


        const safeguards = {};

        for (
            const [name, value]
            of Object.entries(
                payload
                    .durability_safeguards
                || {}
            )
        ) {
            safeguards[
                label(name)
            ] = (
                typeof value
                === "boolean"
                    ? booleanText(value)
                    : value
            );
        }

        renderObject(
            "durability-safeguards",
            safeguards
        );


        const capabilities = {};

        for (
            const [name, value]
            of Object.entries(
                payload.capabilities
                || {}
            )
        ) {
            capabilities[
                label(name)
            ] = booleanText(value);
        }

        renderObject(
            "capabilities",
            capabilities
        );


        renderHistory(
            payload.checkpoint_history
        );
    }


    function showError(error) {
        const panel =
            byId("error-panel");

        panel.hidden = false;

        byId(
            "error-message"
        ).textContent = (
            error instanceof Error
                ? error.message
                : String(error)
        );

        byId(
            "runtime-state"
        ).textContent = "ERROR";
    }


    async function load() {
        try {
            const response =
                await fetch(
                    API_URL,
                    {
                        method: "GET",
                        headers: {
                            "Accept":
                                "application/json"
                        }
                    }
                );

            if (!response.ok) {
                throw new Error(
                    `HTTP ${response.status}`
                );
            }

            const payload =
                await response.json();

            render(payload);

        } catch (error) {
            showError(error);
        }
    }


    load();
})();
