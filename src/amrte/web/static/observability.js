(() => {
    "use strict";

    const API_URL = "/api/v1/observability";

    let events = [];


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
        const row = document.createElement("div");
        row.className = "detail-row";

        const key = document.createElement("span");
        key.textContent = label;

        const data = document.createElement("strong");
        data.textContent = text(value);

        row.appendChild(key);
        row.appendChild(data);

        return row;
    }


    function renderObject(elementId, object) {
        const container = byId(elementId);
        clear(container);

        const entries = Object.entries(
            object || {}
        );

        if (entries.length === 0) {
            container.appendChild(
                detailRow(
                    "Status",
                    "No retained values"
                )
            );
            return;
        }

        for (const [key, value] of entries) {
            container.appendChild(
                detailRow(
                    key,
                    value
                )
            );
        }
    }


    function renderServices(services) {
        const container = byId(
            "registered-services"
        );

        clear(container);

        for (const service of services || []) {
            container.appendChild(
                detailRow(
                    service,
                    "REGISTERED"
                )
            );
        }
    }


    function renderCapabilities(capabilities) {
        const container = byId("capabilities");
        clear(container);

        for (
            const [name, enabled]
            of Object.entries(capabilities || {})
        ) {
            container.appendChild(
                detailRow(
                    name,
                    booleanText(enabled)
                )
            );
        }
    }


    function eventSearchText(event) {
        return [
            event.event_sequence,
            event.severity,
            event.category,
            event.event_code,
            event.module,
            event.message,
            event.correlation_id
        ]
            .map(text)
            .join(" ")
            .toLowerCase();
    }


    function renderEvents(filter = "") {
        const body = byId(
            "event-table-body"
        );

        clear(body);

        const normalized = filter
            .trim()
            .toLowerCase();

        const filtered = events.filter(
            (event) => {
                if (!normalized) {
                    return true;
                }

                return eventSearchText(
                    event
                ).includes(normalized);
            }
        );


        if (filtered.length === 0) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");

            cell.colSpan = 7;
            cell.textContent = "No matching events.";

            row.appendChild(cell);
            body.appendChild(row);

            return;
        }


        for (const event of filtered) {
            const row = document.createElement("tr");

            const values = [
                event.event_sequence,
                event.severity,
                event.category,
                event.event_code,
                event.module,
                event.message,
                event.correlation_id
            ];

            for (const value of values) {
                const cell = document.createElement("td");
                cell.textContent = text(value);
                row.appendChild(cell);
            }

            body.appendChild(row);
        }
    }


    function render(payload) {
        byId(
            "runtime-status"
        ).textContent = text(
            payload.runtime.state
        );

        byId(
            "observability-health"
        ).textContent = text(
            payload.health.observability
        );

        byId(
            "chain-valid"
        ).textContent = (
            payload.health.chain_valid
                ? "VALID"
                : "INVALID"
        );

        byId(
            "retained-events"
        ).textContent = text(
            payload.retention.retained_event_count
        );

        byId(
            "recovery-epoch"
        ).textContent = text(
            payload.runtime.recovery_epoch
        );


        renderObject(
            "authority-details",
            {
                "Service":
                    payload.authority.service,

                "Registered":
                    booleanText(
                        payload.authority.registered
                    ),

                "Source":
                    payload.authority.source,

                "Parallel service":
                    booleanText(
                        payload.authority
                            .parallel_service_created
                    ),

                "Mutation enabled":
                    booleanText(
                        payload.authority
                            .mutation_enabled
                    )
            }
        );


        renderObject(
            "execution-boundary",
            {
                "Capability":
                    payload.execution_boundary
                        .capability,

                "Provider":
                    payload.execution_boundary
                        .provider,

                "Financial execution":
                    booleanText(
                        payload.execution_boundary
                            .financial_execution_available
                    )
            }
        );


        renderObject(
            "severity-statistics",
            payload.statistics.severity
        );

        renderObject(
            "category-statistics",
            payload.statistics.category
        );

        renderObject(
            "classification-statistics",
            payload.statistics.classification
        );

        renderServices(
            payload.registered_services
        );

        renderCapabilities(
            payload.capabilities
        );


        events = payload.events || [];

        renderEvents(
            byId("event-search").value
        );
    }


    function showError(error) {
        const panel = byId("error-panel");

        panel.hidden = false;

        byId(
            "error-message"
        ).textContent = (
            error instanceof Error
                ? error.message
                : String(error)
        );
    }


    async function load() {
        try {
            const response = await fetch(
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

            const payload = await response.json();

            render(payload);

        } catch (error) {
            showError(error);
        }
    }


    byId(
        "event-search"
    ).addEventListener(
        "input",
        (event) => {
            renderEvents(
                event.target.value
            );
        }
    );


    load();
})();
