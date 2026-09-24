from .types import Capability


class CapabilityRegistry:
    def __init__(self, available: set[Capability] | None = None):
        prohibited = {
            Capability.LIVE_BROKER_EXECUTION_AVAILABLE,
            Capability.DEMO_BROKER_EXECUTION_AVAILABLE,
        }
        self._available = frozenset((available or set()) - prohibited)

    def has(self, capability: Capability) -> bool:
        return capability in self._available

    def snapshot(self) -> dict[str, bool]:
        return {item.name: self.has(item) for item in Capability}

