"use strict";

const API = "/api/v1/research-governance";

const text = (value) => {
    if (value === null || value === undefined) {
        return "â€”";
    }

    if (typeof value === "boolean") {
        return value ? "TRUE" : "FALSE";
    }

    return String(value);
};

const escapeHtml = (value) =>
    text(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

const rows = (value) => {
    if (value === null || value === undefined) {
        return '<p class="muted">Not available.</p>';
    }

    if (Array.isArray(value)) {
        if (value.length === 0) {
            return '<p class="muted">None.</p>';
        }

        return `
            <div class="table-wrap">
                <table>
                    <tbody>
                        ${value.map((item) => `
                            <tr>
                                <td>${escapeHtml(item)}</td>
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            </div>
        `;
    }

    if (typeof value !== "object") {
        return `<p>${escapeHtml(value)}</p>`;
    }

    return `
        <div class="table-wrap">
            <table>
                <tbody>
                    ${Object.entries(value).map(([key, item]) => `
                        <tr>
                            <th>${escapeHtml(key.replaceAll("_", " "))}</th>
                            <td>${
                                typeof item === "object" && item !== null
                                    ? rows(item)
                                    : escapeHtml(item)
                            }</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>
    `;
};

const setHtml = (id, value) => {
    const element = document.getElementById(id);

    if (element) {
        element.innerHTML = rows(value);
    }
};

const capabilityCard = (name, capability) => `
    <article class="panel">
        <div class="panel-header">
            <div>
                <div class="eyebrow">CAPABILITY</div>
                <h3>${escapeHtml(name.replaceAll("_", " "))}</h3>
            </div>
            <span class="badge">
                ${escapeHtml(capability?.status ?? "AVAILABLE_NOT_ACTIVATED")}
            </span>
        </div>

        <div class="metric-grid">
            <div class="metric-card">
                <span class="metric-label">IMPLEMENTED</span>
                <strong>${escapeHtml(capability?.implemented)}</strong>
            </div>

            <div class="metric-card">
                <span class="metric-label">RUNTIME-ACTIVE</span>
                <strong>${escapeHtml(capability?.runtime_active)}</strong>
            </div>

            <div class="metric-card">
                <span class="metric-label">CURRENT-STATE-AVAILABLE</span>
                <strong>${escapeHtml(
                    capability?.current_state_available
                )}</strong>
            </div>

            <div class="metric-card">
                <span class="metric-label">RUNTIME AUTHORITY</span>
                <strong>${escapeHtml(
                    capability?.runtime_authority
                )}</strong>
            </div>
        </div>
    </article>
`;

const renderCapabilities = (data) => {
    const root = document.getElementById(
        "governance-capabilities"
    );

    if (!root) {
        return;
    }

    const capabilityList =
        Array.isArray(data.governance_capabilities)
            ? data.governance_capabilities
            : Object.values(
                  data.governance_capabilities ??
                  data.capabilities ??
                  {}
              );

    const capabilities =
        Object.fromEntries(
            capabilityList
                .filter(
                    (item) =>
                        item &&
                        typeof item.capability === "string"
                )
                .map(
                    (item) => [
                        item.capability,
                        item,
                    ]
                )
        );

    const required = [
        "research_lifecycle",
        "system_safety",
        "observation_quality",
        "research_reliability",
        "temporal_quality_protection",
    ];

    root.innerHTML = required.map((name) =>
        capabilityCard(
            name,
            capabilities[name] ?? {}
        )
    ).join("");
};

const renderAuthority = (data) => {
    const capabilityList =
        Array.isArray(data.governance_capabilities)
            ? data.governance_capabilities
            : Object.values(
                  data.governance_capabilities ??
                  data.capabilities ??
                  {}
              );

    const capabilities =
        Object.fromEntries(
            capabilityList
                .filter(
                    (item) =>
                        item &&
                        typeof item.capability === "string"
                )
                .map(
                    (item) => [
                        item.capability,
                        item,
                    ]
                )
        );

    const values = Object.values(capabilities);

    const implemented =
        values.length > 0 &&
        values.every((item) => item.implemented === true);

    const runtimeActive =
        values.some((item) => item.runtime_active === true);

    const currentState =
        values.some(
            (item) => item.current_state_available === true
        );

    const status =
        values.length > 0
            ? (
                values[0].status ??
                "AVAILABLE_NOT_ACTIVATED"
            )
            : "AVAILABLE_NOT_ACTIVATED";

    const mapping = {
        "authority-implemented": implemented,
        "authority-runtime-active": runtimeActive,
        "authority-current-state": currentState,
        "authority-status": status,
    };

    for (const [id, value] of Object.entries(mapping)) {
        const element = document.getElementById(id);

        if (element) {
            element.textContent = text(value);
        }
    }
};

const render = (data) => {
    renderAuthority(data);
    renderCapabilities(data);

    setHtml(
        "lifecycle-governance",
        data.lifecycle_governance ??
        data.research_lifecycle
    );

    setHtml(
        "system-safety",
        data.system_safety
    );

    setHtml(
        "observation-quality",
        data.quality_protection?.observation_quality ??
        data.observation_quality
    );

    setHtml(
        "research-reliability",
        data.quality_protection?.research_reliability ??
        data.research_reliability
    );

    setHtml(
        "temporal-quality",
        data.quality_protection?.temporal_quality ??
        data.temporal_quality ??
        data.temporal_quality_protection
    );

    setHtml(
        "promotion-governance",
        data.promotion_governance
    );

    setHtml(
        "recovery-governance",
        data.recovery_governance
    );

    setHtml(
        "configuration-safeguards",
        data.configuration_safeguards
    );

    setHtml(
        "execution-boundary",
        data.execution_boundary
    );
};

const loadGovernance = async () => {
    const error =
        document.getElementById(
            "research-governance-error"
        );

    try {
        const response = await fetch(
            "/api/v1/research-governance",
            {
                method: "GET",
                headers: {
                    "Accept": "application/json",
                },
            }
        );

        if (!response.ok) {
            throw new Error(
                `Governance API returned ${response.status}`
            );
        }

        const data = await response.json();
        render(data);
    } catch (failure) {
        if (error) {
            error.hidden = false;
            error.textContent =
                `Unable to load governance assurance: ${
                    failure.message
                }`;
        }
    }
};

loadGovernance();