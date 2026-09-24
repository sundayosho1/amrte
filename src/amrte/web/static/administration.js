(() => {
    "use strict";

    const endpoint = "/api/v1/administration";

    const byId = (id) => document.getElementById(id);

    const text = (id, value) => {
        const node = byId(id);

        if (!node) {
            return;
        }

        node.textContent =
            value === null || value === undefined
                ? "UNAVAILABLE"
                : String(value);
    };

    const yesNo = (value) =>
        value ? "YES" : "NO";

    const allowed = (value) =>
        value ? "ALLOWED" : "PROHIBITED";

    const renderServices = (services) => {
        const container = byId(
            "registered-services"
        );

        if (!container) {
            return;
        }

        container.replaceChildren();

        for (const service of services || []) {
            const item =
                document.createElement("div");

            item.className = "detail-item";

            const label =
                document.createElement("span");

            label.textContent = service.name;

            const value =
                document.createElement("strong");

            value.textContent = service.type;

            item.append(
                label,
                value
            );

            container.appendChild(item);
        }

        text(
            "service-count",
            `${(services || []).length} SERVICES`
        );
    };

    const renderCapabilities = (
        capabilities
    ) => {
        const container = byId(
            "capability-list"
        );

        if (!container) {
            return;
        }

        container.replaceChildren();

        for (
            const [name, value]
            of Object.entries(
                capabilities || {}
            )
        ) {
            const item =
                document.createElement("div");

            item.className = "detail-item";

            const label =
                document.createElement("span");

            label.textContent =
                name
                    .replaceAll("_", " ")
                    .toUpperCase();

            const result =
                document.createElement("strong");

            result.textContent =
                allowed(Boolean(value));

            item.append(
                label,
                result
            );

            container.appendChild(item);
        }
    };

    const render = (body) => {
        text(
            "system-version",
            body.system_identity?.version
        );

        text(
            "system-environment",
            body.system_identity?.environment
        );

        text(
            "runtime-state",
            body.runtime?.state
        );

        text(
            "execution-status",
            body.execution_boundary?.status
        );

        text(
            "configuration-snapshot",
            body.configuration?.snapshot_id
        );

        text(
            "configuration-hash",
            body.configuration?.configuration_hash
        );

        text(
            "experiment-id",
            body.system_identity?.experiment_id
        );

        text(
            "dataset-id",
            body.system_identity?.dataset_id
        );

        text(
            "repository-type",
            body.persistence?.repository
        );

        text(
            "chain-valid",
            yesNo(
                Boolean(
                    body.persistence?.chain_valid
                )
            )
        );

        text(
            "persistence-mutation",
            allowed(
                Boolean(
                    body.persistence?.mutation_allowed
                )
            )
        );

        text(
            "administration-rbac",
            yesNo(
                Boolean(
                    body.permissions?.administration_rbac
                )
            )
        );

        text(
            "claims-authority",
            yesNo(
                Boolean(
                    body.permissions?.claims_authority
                )
            )
        );

        text(
            "invented-permissions",
            yesNo(
                Boolean(
                    body.permissions?.invented_permissions
                )
            )
        );

        text(
            "execution-provider",
            body.execution_boundary?.provider
        );

        text(
            "financial-execution",
            allowed(
                Boolean(
                    body.execution_boundary
                        ?.financial_execution
                )
            )
        );

        text(
            "broker-connectivity",
            allowed(
                Boolean(
                    body.execution_boundary
                        ?.broker_connectivity
                )
            )
        );

        text(
            "account-connectivity",
            allowed(
                Boolean(
                    body.execution_boundary
                        ?.account_connectivity
                )
            )
        );

        renderServices(
            body.registered_services
        );

        renderCapabilities(
            body.capabilities
        );
    };

    const load = async () => {
        try {
            const response = await fetch(
                endpoint,
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
                    `Administration request failed: ${
                        response.status
                    }`
                );
            }

            const body =
                await response.json();

            render(body);
        } catch (error) {
            const banner = byId(
                "administration-error"
            );

            if (banner) {
                banner.hidden = false;
            }

            console.error(
                "Administration projection unavailable.",
                error
            );
        }
    };

    load();
})();
