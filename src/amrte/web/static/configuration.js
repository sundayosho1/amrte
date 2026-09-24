"use strict";

const byId = (id) => document.getElementById(id);

let configurationData = null;
let safeguardData = null;

function text(id, value) {
    const element = byId(id);

    if (!element) {
        return;
    }

    element.textContent =
        value === null ||
        value === undefined ||
        value === ""
            ? "—"
            : String(value);
}

function displayValue(value) {
    if (value === null || value === undefined) {
        return "—";
    }

    if (Array.isArray(value)) {
        if (value.length === 0) {
            return "[]";
        }

        return value
            .map((item) => displayValue(item))
            .join(", ");
    }

    if (typeof value === "boolean") {
        return value ? "True" : "False";
    }

    if (typeof value === "object") {
        return JSON.stringify(value);
    }

    return String(value);
}

function provenanceClass(provenance) {
    if (provenance === "HARD_CONSTRAINT") {
        return "hard";
    }

    if (provenance === "PROFILE") {
        return "profile";
    }

    return "default";
}

function renderProvenance() {
    const container = byId("provenance-summary");

    if (!container || !configurationData) {
        return;
    }

    container.innerHTML = "";

    const provenance =
        configurationData.statistics.provenance;

    for (const [name, count] of Object.entries(provenance)) {
        const item = document.createElement("div");
        item.className = "provenance-item";

        const label = document.createElement("span");
        label.className =
            `provenance-badge ${provenanceClass(name)}`;
        label.textContent = name;

        const value = document.createElement("strong");
        value.textContent = String(count);

        item.append(label, value);
        container.appendChild(item);
    }
}

function renderSafeguards() {
    const container = byId("safeguard-grid");

    if (!container || !safeguardData) {
        return;
    }

    container.innerHTML = "";

    text(
        "execution-badge",
        safeguardData.execution
    );

    for (const safeguard of safeguardData.safeguards) {
        const item = document.createElement("div");
        item.className = "safeguard-item";

        const key = document.createElement("div");
        key.className = "safeguard-key";
        key.textContent = safeguard.key;

        const bottom = document.createElement("div");
        bottom.className = "safeguard-bottom";

        const value = document.createElement("strong");
        value.className = safeguard.value
            ? "value-warning"
            : "value-safe";
        value.textContent = displayValue(
            safeguard.value
        );

        const source = document.createElement("span");
        source.className =
            "provenance-badge hard";
        source.textContent = safeguard.provenance;

        bottom.append(value, source);
        item.append(key, bottom);
        container.appendChild(item);
    }
}

function populateSectionFilter() {
    const select = byId("config-section-filter");

    if (!select || !configurationData) {
        return;
    }

    for (const section of configurationData.sections) {
        const option = document.createElement("option");
        option.value = section.name;
        option.textContent =
            `${section.name} (${section.parameter_count})`;
        select.appendChild(option);
    }
}

function filteredSections() {
    if (!configurationData) {
        return [];
    }

    const query = (
        byId("config-search")?.value || ""
    )
        .trim()
        .toLowerCase();

    const sectionFilter =
        byId("config-section-filter")?.value || "";

    const provenanceFilter =
        byId("config-provenance-filter")?.value || "";

    return configurationData.sections
        .filter(
            (section) =>
                !sectionFilter ||
                section.name === sectionFilter
        )
        .map((section) => {
            const parameters = section.parameters.filter(
                (parameter) => {
                    if (
                        provenanceFilter &&
                        parameter.provenance !==
                            provenanceFilter
                    ) {
                        return false;
                    }

                    if (!query) {
                        return true;
                    }

                    const haystack = [
                        parameter.key,
                        parameter.name,
                        displayValue(parameter.value),
                        parameter.value_type,
                        parameter.provenance,
                    ]
                        .join(" ")
                        .toLowerCase();

                    return haystack.includes(query);
                }
            );

            return {
                ...section,
                parameters,
            };
        })
        .filter(
            (section) => section.parameters.length > 0
        );
}

function renderConfiguration() {
    const container = byId(
        "configuration-sections"
    );
    const empty = byId("configuration-empty");

    if (!container || !configurationData) {
        return;
    }

    const sections = filteredSections();

    container.innerHTML = "";

    let visibleCount = 0;

    for (const section of sections) {
        visibleCount += section.parameters.length;

        const group = document.createElement("section");
        group.className = "config-section";

        const heading = document.createElement("div");
        heading.className = "config-section-heading";

        const title = document.createElement("strong");
        title.textContent = section.name;

        const count = document.createElement("span");
        count.textContent =
            `${section.parameters.length} parameters`;

        heading.append(title, count);

        const tableWrap = document.createElement("div");
        tableWrap.className = "config-table-wrap";

        const table = document.createElement("table");
        table.className = "config-table";

        table.innerHTML = `
            <thead>
                <tr>
                    <th>Parameter</th>
                    <th>Value</th>
                    <th>Type</th>
                    <th>Provenance</th>
                </tr>
            </thead>
        `;

        const body = document.createElement("tbody");

        for (const parameter of section.parameters) {
            const row = document.createElement("tr");

            const keyCell =
                document.createElement("td");
            keyCell.className = "parameter-key";
            keyCell.textContent = parameter.key;

            const valueCell =
                document.createElement("td");
            valueCell.className = "parameter-value";
            valueCell.textContent = displayValue(
                parameter.value
            );

            const typeCell =
                document.createElement("td");
            typeCell.className = "parameter-type";
            typeCell.textContent =
                parameter.value_type;

            const provenanceCell =
                document.createElement("td");

            const badge =
                document.createElement("span");
            badge.className =
                `provenance-badge ${
                    provenanceClass(
                        parameter.provenance
                    )
                }`;
            badge.textContent =
                parameter.provenance;

            provenanceCell.appendChild(badge);

            row.append(
                keyCell,
                valueCell,
                typeCell,
                provenanceCell
            );

            body.appendChild(row);
        }

        table.appendChild(body);
        tableWrap.appendChild(table);
        group.append(heading, tableWrap);
        container.appendChild(group);
    }

    text(
        "visible-parameter-count",
        `${visibleCount} visible`
    );

    if (empty) {
        empty.hidden = visibleCount !== 0;
    }
}

function bindFilters() {
    const controls = [
        byId("config-search"),
        byId("config-section-filter"),
        byId("config-provenance-filter"),
    ];

    for (const control of controls) {
        if (!control) {
            continue;
        }

        control.addEventListener(
            control.tagName === "INPUT"
                ? "input"
                : "change",
            renderConfiguration
        );
    }
}

async function fetchJson(url) {
    const response = await fetch(url, {
        method: "GET",
        headers: {
            "Accept": "application/json",
        },
        cache: "no-store",
    });

    if (!response.ok) {
        throw new Error(
            `${url} returned ${response.status}`
        );
    }

    return response.json();
}

async function loadConfiguration() {
    const status = byId(
        "configuration-top-status"
    );
    const dot = byId("runtime-status-dot");

    try {
        [
            configurationData,
            safeguardData,
        ] = await Promise.all([
            fetchJson("/api/v1/configuration"),
            fetchJson(
                "/api/v1/configuration/safeguards"
            ),
        ]);

        text(
            "config-profile",
            configurationData.profile.selected
        );
        text(
            "config-validation",
            configurationData.validation.status
        );
        text(
            "config-warning-count",
            configurationData.validation.warning_count
        );
        text(
            "config-parameter-count",
            configurationData.statistics.parameter_count
        );
        text(
            "config-section-count",
            configurationData.statistics.section_count
        );
        text(
            "config-override-count",
            configurationData.statistics
                .overridden_parameter_count
        );

        text(
            "config-schema",
            configurationData.metadata.schema_version
        );
        text(
            "config-snapshot",
            configurationData.metadata.snapshot_id
        );
        text(
            "config-hash",
            configurationData.metadata.configuration_hash
        );
        text(
            "config-environment",
            configurationData.metadata.runtime_environment
        );
        text(
            "config-version",
            configurationData.metadata.application_version
        );

        status.textContent =
            configurationData.validation.status;

        if (configurationData.validation.valid) {
            dot.classList.add("running");
        }

        renderProvenance();
        renderSafeguards();
        populateSectionFilter();
        bindFilters();
        renderConfiguration();

    } catch (error) {
        status.textContent = "UNAVAILABLE";
        status.classList.add("error");

        const banner = byId(
            "configuration-error"
        );

        if (banner) {
            banner.hidden = false;
            banner.textContent =
                `Configuration unavailable: ${error.message}`;
        }
    }
}

document.addEventListener(
    "DOMContentLoaded",
    loadConfiguration
);
