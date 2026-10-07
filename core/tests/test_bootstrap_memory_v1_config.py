from __future__ import annotations

import pytest

from atlas.config import AtlasConfig
from atlas.memory.v1_features import DEFAULT_FROZEN_FEATURES, frozen_features


def test_memory_v1_config_defaults_are_stable_and_closed() -> None:
    config = AtlasConfig()

    assert config.unified_service_dir == r"D:\MemoryOS"
    assert config.memory_v1_recall_timeout_seconds == 1.0
    assert config.memory_v1_observer_daily_token_budget == 50_000
    assert frozen_features(config) == frozenset(DEFAULT_FROZEN_FEATURES)


def test_memory_v1_frozen_features_accepts_explicit_empty_list() -> None:
    assert frozen_features(AtlasConfig({"memory": {"v1": {"frozen_features": []}}})) == frozenset()


@pytest.mark.parametrize("value", ["all", ["unknown"], [1]])
def test_memory_v1_frozen_features_rejects_invalid_values(value) -> None:
    config = AtlasConfig({"memory": {"v1": {"frozen_features": value}}})

    with pytest.raises(ValueError, match="known feature names"):
        frozen_features(config)
