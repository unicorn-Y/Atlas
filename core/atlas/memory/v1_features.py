"""MEMORY-V1 runtime policy; frozen implementations remain available to unit tests."""

from __future__ import annotations

DEFAULT_FROZEN_FEATURES = (
    "multimodal", "media_understanding", "passive_capture", "skill_evolution",
    "targeted_learning", "prediction", "utility", "strategy_updates",
    "learning_gate", "experience_distiller", "associations", "graph_retriever",
    "self_probe",
)
FROZEN_FEATURES_HEADER = "X-Memory-V1-Frozen-Features"


def frozen_features(config=None) -> frozenset[str]:
    if config is None:
        from atlas.config import get_config

        config = get_config()
    value = config.get("memory.v1.frozen_features", list(DEFAULT_FROZEN_FEATURES))
    if not isinstance(value, list) or any(
        not isinstance(item, str) or item not in DEFAULT_FROZEN_FEATURES for item in value
    ):
        raise ValueError("memory.v1.frozen_features must be a list of known feature names")
    return frozenset(value)


def is_frozen(feature: str, config=None) -> bool:
    return feature in frozen_features(config)
