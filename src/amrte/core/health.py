from __future__ import annotations

from .types import HealthReport, HealthStatus


class HealthService:
    def assess(self, components: dict[str, HealthStatus], mandatory: tuple[str, ...]) -> HealthReport:
        reasons: list[str] = []
        for name in mandatory:
            status = components.get(name, HealthStatus.UNKNOWN)
            if status is not HealthStatus.HEALTHY:
                reasons.append(f"{name}:{status.name}")
        return HealthReport(components=dict(components), ready=not reasons, reasons=tuple(reasons))

