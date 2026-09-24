from __future__ import annotations

from typing import Any, TypeVar

T = TypeVar("T")


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: dict[str, Any] = {}
        self._sealed = False

    def register(self, name: str, service: Any) -> None:
        if self._sealed:
            raise RuntimeError("service registry is sealed")
        if not name or service is None or name in self._services:
            raise ValueError("service registration must be unique and non-null")
        self._services[name] = service

    def require(self, name: str) -> Any:
        if name not in self._services:
            raise KeyError(f"mandatory service missing: {name}")
        return self._services[name]

    def seal(self) -> None:
        self._sealed = True

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._services))

