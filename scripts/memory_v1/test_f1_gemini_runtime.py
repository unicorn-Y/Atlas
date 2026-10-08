from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import gemini_runtime as runtime


class GeminiIsolationTests(unittest.TestCase):
    def test_user_settings_copy_only_gemini_model_custom_provider_and_memory_model(self) -> None:
        with tempfile.TemporaryDirectory(prefix="f1d-gemini-settings-") as temp:
            path = Path(temp) / "user-settings.json"
            path.write_text(json.dumps({
                "custom_models": [
                    {
                        "id": "gemini-3.8-flash",
                        "name": "Gemini",
                        "provider": "custom",
                        "litellm_model": "gemini-3.8-flash",
                        "category": "fast",
                        "custom": True,
                        "api_key": "must-not-copy-model-secret",
                    },
                    {"id": "other-model", "provider": "other"},
                ],
                "providers": {
                    "custom": {
                        "base_url": "http://127.0.0.1:8045/v1",
                        "keys": [{
                            "id": "k_test",
                            "label": "Antigravity",
                            "added_at": "2026-10-09T00:00:00Z",
                            "secret": "must-not-copy-provider-secret",
                        }],
                        "api_mode_override": "chat_completions",
                        "api_mode_probe": {"token": "must-not-copy-probe-secret"},
                        "api_key": "must-not-copy-provider-secret",
                    },
                    "other": {"base_url": "https://invalid.example", "keys": []},
                },
                "memory_model": "gemini-3.8-flash",
                "selected_model": "other-model",
                "api_key": "must-not-copy-gateway-secret",
                "gateway_base_url": "https://invalid.example",
                "unrelated": True,
            }), encoding="utf-8")

            settings = runtime.read_isolated_model_settings(path)

        self.assertEqual("gemini-3.8-flash", settings["memory_model"])
        self.assertEqual([{
            "id": "gemini-3.8-flash",
            "name": "Gemini",
            "provider": "custom",
            "litellm_model": "gemini-3.8-flash",
            "category": "fast",
            "custom": True,
        }], settings["custom_models"])
        self.assertEqual({
            "custom": {
                "base_url": "http://127.0.0.1:8045/v1",
                "keys": [{"id": "k_test", "label": "Antigravity", "added_at": "2026-10-09T00:00:00Z"}],
                "api_mode_override": "chat_completions",
            },
        }, settings["providers"])
        self.assertNotIn("api_key", settings)
        self.assertNotIn("selected_model", settings)
        self.assertNotIn("must-not-copy", json.dumps(settings))

    def test_isolated_settings_file_contains_exactly_three_safe_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="f1d-atlas-root-") as temp:
            atlas_data_root = Path(temp) / "atlas-data"
            settings = {
                "custom_models": [{
                    "id": "gemini-3.8-flash",
                    "name": "Gemini",
                    "provider": "custom",
                    "litellm_model": "gemini-3.8-flash",
                    "category": "fast",
                    "custom": True,
                }],
                "providers": {"custom": {"base_url": "http://127.0.0.1:8045/v1", "keys": [{"id": "k_test"}]}},
                "memory_model": "gemini-3.8-flash",
            }

            path = runtime.write_isolated_user_settings(atlas_data_root, settings)

            self.assertEqual(atlas_data_root.resolve(), path.parents[1].resolve())
            self.assertEqual(settings, json.loads(path.read_text(encoding="utf-8")))

    def test_isolated_settings_writer_rejects_nested_secret_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="f1d-atlas-root-") as temp:
            settings = {
                "custom_models": [{"id": "gemini-3.8-flash", "api_key": "must-not-copy"}],
                "providers": {"custom": {"base_url": "http://127.0.0.1:8045/v1", "keys": []}},
                "memory_model": "gemini-3.8-flash",
            }

            with self.assertRaisesRegex(ValueError, "nested fields"):
                runtime.write_isolated_user_settings(Path(temp), settings)

    def test_raw_config_gateway_secrets_are_cleared_before_atlas_config(self) -> None:
        raw_config = {"models": {"gateway": {
            "base_url": "https://wrong.example/v1",
            "api_key": "must-not-use-gateway-secret",
        }}}

        runtime.clear_gateway_fallback_config(raw_config)

        self.assertEqual("", raw_config["models"]["gateway"]["base_url"])
        self.assertEqual("", raw_config["models"]["gateway"]["api_key"])

    def test_inherited_gateway_credentials_are_removed_from_runtime_environment(self) -> None:
        with patch.dict(os.environ, {
            "ATLAS_API_KEY": "inherited-secret",
            "ATLAS_API_BASE": "https://wrong.example/v1",
        }):
            runtime.clear_inherited_gateway_credentials()

            self.assertNotIn("ATLAS_API_KEY", os.environ)
            self.assertNotIn("ATLAS_API_BASE", os.environ)

    def test_route_preflight_records_presence_without_exposing_key(self) -> None:
        class StubModelManager:
            current_model = "gemini-3.8-flash"
            gateway_api_key = ""

            @staticmethod
            def list_models():
                return [{"id": "gemini-3.8-flash", "provider": "custom"}]

            @staticmethod
            def provider_config(provider_id: str):
                return {"base_url": "http://127.0.0.1:8045/v1"}

            @staticmethod
            def resolve_api_key(provider_id: str):
                return "keyring-secret-must-not-be-recorded"

        status = runtime.validate_f1_model_route(
            StubModelManager(), {"memory_model": "gemini-3.8-flash"},
        )

        self.assertEqual("gemini-3.8-flash", status["model_id"])
        self.assertEqual("127.0.0.1:8045", status["provider_endpoint_host"])
        self.assertTrue(status["credential_present"])
        self.assertFalse(status["credential_value_recorded"])
        self.assertNotIn("/v1", json.dumps(status))
        self.assertNotIn("keyring-secret", json.dumps(status))

    def test_route_preflight_rejects_gateway_fallback_secret(self) -> None:
        class StubModelManager:
            current_model = "gemini-3.8-flash"
            gateway_api_key = "gateway-secret-must-not-be-used"

            @staticmethod
            def list_models():
                return [{"id": "gemini-3.8-flash", "provider": "custom"}]

            @staticmethod
            def provider_config(provider_id: str):
                return {"base_url": "http://127.0.0.1:8045/v1"}

            @staticmethod
            def resolve_api_key(provider_id: str):
                return "keyring-secret"

        with self.assertRaisesRegex(RuntimeError, "gateway credential"):
            runtime.validate_f1_model_route(
                StubModelManager(), {"memory_model": "gemini-3.8-flash"},
            )

    def test_bootstrap_uses_gemini_model_manager_without_persisting_selection(self) -> None:
        core = Path(r"D:\Atlas\core")
        if str(core) not in sys.path:
            sys.path.insert(0, str(core))
        from atlas.config import AtlasConfig
        from atlas.models import ModelManager

        settings = {
            "custom_models": [{
                "id": "gemini-3.8-flash",
                "name": "Gemini",
                "provider": "custom",
                "litellm_model": "gemini-3.8-flash",
                "category": "fast",
                "custom": True,
            }],
            "providers": {"custom": {
                "base_url": "http://127.0.0.1:8045/v1",
                "keys": [{"id": "k_test", "label": "test", "added_at": "2026-10-09"}],
            }},
            "memory_model": "gemini-3.8-flash",
        }
        with tempfile.TemporaryDirectory(prefix="f1d-bootstrap-") as temp:
            settings_path = runtime.write_isolated_user_settings(Path(temp), settings)
            config = AtlasConfig({"models": {"gateway": {"base_url": "", "api_key": ""}}})
            with patch.dict(os.environ, {"ATLAS_DATA_DIR": temp}):
                with patch.object(ModelManager, "resolve_api_key", return_value="test-keyring-secret") as keyring_lookup:
                    manager, route = runtime.bootstrap_model_manager(config, settings, settings_path)
            keyring_lookup.assert_called_once_with("custom")

            self.assertEqual("gemini-3.8-flash", manager.current_model)
            self.assertEqual("gemini-3.8-flash", route["observer_model_id"])
            self.assertTrue(route["credential_present"])
            self.assertNotIn("test-keyring-secret", json.dumps(route))
            self.assertEqual(settings, json.loads(settings_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
