from __future__ import annotations

from unittest import TestCase
from unittest.mock import Mock, patch

from integrations.openai_model_discovery import (
    OpenAICompatibleAPIError,
    chat_completions_endpoint,
    fetch_replicate_models,
    fetch_together_models,
    models_endpoint,
    validate_openai_compatible_api_key,
    validate_paligemma_api_key,
    validate_openrouter_api_key,
)


class OpenAICompatibleApiValidationTests(TestCase):
    def test_together_catalog_uses_v1_models_and_bearer_auth(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {"data": [{"id": "black-forest-labs/FLUX.1-schnell"}]}
        with patch("integrations.openai_model_discovery.requests.get", return_value=response) as get:
            models = fetch_together_models("together-secret", "https://api.together.ai/v1")
        self.assertEqual(models, ["black-forest-labs/FLUX.1-schnell"])
        get.assert_called_once_with(
            "https://api.together.ai/v1/models",
            headers={"Accept": "application/json", "Authorization": "Bearer together-secret"},
            timeout=12,
        )

    def test_together_catalog_includes_http_error_detail_without_secret(self) -> None:
        response = Mock(status_code=500)
        response.text = "provider failure together-secret"
        with patch("integrations.openai_model_discovery.requests.get", return_value=response):
            with self.assertRaises(ValueError) as raised:
                fetch_together_models("together-secret", "https://api.together.ai/v1")
        self.assertIn("HTTP 500", str(raised.exception))
        self.assertNotIn("together-secret", str(raised.exception))

    def test_paligemma_validation_uses_integrated_nim_catalog(self) -> None:
        response = Mock(status_code=200)
        with patch("integrations.openai_model_discovery.requests.get", return_value=response) as get:
            validate_paligemma_api_key("nim-secret", "https://integrate.api.nvidia.com/v1")
        self.assertEqual(get.call_args.args[0], "https://integrate.api.nvidia.com/v1/models")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer nim-secret")

    def test_replicate_catalog_uses_native_results_endpoint_and_latest_version(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "results": [
                {"owner": "black-forest-labs", "name": "flux", "latest_version": {"id": "version-123"}},
                {"owner": "missing", "name": "no-version", "latest_version": None},
            ]
        }
        with patch("integrations.openai_model_discovery.requests.get", return_value=response) as get:
            models = fetch_replicate_models("r8_secret", "https://api.replicate.com/v1")

        self.assertEqual(models, ["black-forest-labs/flux:version-123"])
        get.assert_called_once_with(
            "https://api.replicate.com/v1/models",
            headers={"Accept": "application/json", "Authorization": "Bearer r8_secret"},
            timeout=12,
        )

    def test_openrouter_base_url_builds_official_endpoints_without_query_suffix(self) -> None:
        base_url = "https://openrouter.ai/api/v1?"

        self.assertEqual(
            models_endpoint(base_url),
            "https://openrouter.ai/api/v1/models",
        )
        self.assertEqual(
            chat_completions_endpoint(base_url),
            "https://openrouter.ai/api/v1/chat/completions",
        )

    def test_openrouter_404_explains_base_url_and_model_requirements(self) -> None:
        response = Mock(status_code=404)
        with patch("integrations.openai_model_discovery.requests.post", return_value=response):
            with self.assertRaises(OpenAICompatibleAPIError) as raised:
                validate_openai_compatible_api_key(
                    "sk-openrouter-test",
                    "https://openrouter.ai/api/v1",
                    "modelo-inexistente",
                )

        self.assertIn("https://openrouter.ai/api/v1", str(raised.exception))
        self.assertIn("openai/gpt-4o-mini", str(raised.exception))
        self.assertIn("chat/completions", str(raised.exception))

    def test_openrouter_validation_checks_key_and_model_catalog_without_chat_generation(self) -> None:
        key_response = Mock(status_code=200)
        models_response = Mock(status_code=200)
        models_response.json.return_value = {"data": [{"id": "google/gemini-3.7-flash"}]}
        with patch(
            "integrations.openai_model_discovery.requests.get",
            side_effect=[key_response, models_response],
        ) as get:
            validate_openrouter_api_key(
                "sk-openrouter-test",
                "https://openrouter.ai/api/v1",
                "google/gemini-3.7-flash",
            )

        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].args[0], "https://openrouter.ai/api/v1/key")
        self.assertEqual(get.call_args_list[1].args[0], "https://openrouter.ai/api/v1/models")
        self.assertEqual(
            get.call_args_list[0].kwargs["headers"]["Authorization"],
            "Bearer sk-openrouter-test",
        )

    def test_openrouter_validation_reports_model_not_in_catalog(self) -> None:
        key_response = Mock(status_code=200)
        models_response = Mock(status_code=200)
        models_response.json.return_value = {"data": [{"id": "google/gemini-3.7-flash"}]}
        with patch(
            "integrations.openai_model_discovery.requests.get",
            side_effect=[key_response, models_response],
        ):
            with self.assertRaises(OpenAICompatibleAPIError) as raised:
                validate_openrouter_api_key(
                    "sk-openrouter-test",
                    "https://openrouter.ai/api/v1?",
                    "modelo-inexistente",
                )

        self.assertIn("catálogo actual", str(raised.exception))

    def test_validation_posts_minimal_authenticated_chat_request(self) -> None:
        response = Mock(status_code=200)
        with patch("integrations.openai_model_discovery.requests.post", return_value=response) as post:
            validate_openai_compatible_api_key(
                "sk-test-secret",
                "https://integrate.api.nvidia.com/v1",
                "meta/llama-3.1-8b-instruct",
            )

        post.assert_called_once_with(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer sk-test-secret",
                "Content-Type": "application/json",
            },
            json={
                "model": "meta/llama-3.1-8b-instruct",
                "messages": [{"role": "user", "content": "Responda apenas OK."}],
                "max_tokens": 1,
                "temperature": 0,
            },
            timeout=12,
        )

    def test_validation_reports_rejected_api_key_without_exposing_it(self) -> None:
        secret = "sk-never-leak"
        response = Mock(status_code=401)
        with patch("integrations.openai_model_discovery.requests.post", return_value=response):
            with self.assertRaises(OpenAICompatibleAPIError) as raised:
                validate_openai_compatible_api_key(secret, "https://api.example.com/v1", "model-a")

        self.assertIn("API key", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))


if __name__ == "__main__":
    import unittest

    unittest.main()
