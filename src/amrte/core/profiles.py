from types import MappingProxyType

from .types import ResearchProfile


PROFILE_DELTAS = MappingProxyType({
    ResearchProfile.CONSERVATIVE: MappingProxyType({
        "research.minimum_quality_score": 0.85,
        "research.max_concurrent_scenarios": 1,
        "research.max_resource_load": 0.25,
    }),
    ResearchProfile.BALANCED: MappingProxyType({
        "research.minimum_quality_score": 0.70,
        "research.max_concurrent_scenarios": 3,
        "research.max_resource_load": 0.50,
    }),
    ResearchProfile.AGGRESSIVE: MappingProxyType({
        "research.minimum_quality_score": 0.60,
        "research.max_concurrent_scenarios": 5,
        "research.max_resource_load": 0.75,
    }),
    ResearchProfile.CUSTOM: MappingProxyType({}),
})

