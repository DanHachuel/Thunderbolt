from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from hermes_ui import api_key_tests


class ApiKeyDiagnosticsTests(unittest.TestCase):
    def response(self, status_code: int) -> Mock:
        response = Mock()
        response.status_code = status_code
        response.text = "provider error SECRET-KEY-123"
        return response

    def test_missing_credentials_do_not_call_network(self):
        with patch.object(api_key_tests.requests, "get") as get:
            result = api_key_tests.test_apify_credentials("")
        self.assertEqual(result["status"], "missing")
        get.assert_not_called()

    def test_apify_uses_read_only_authenticated_endpoint(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_apify_credentials("SECRET-KEY-123")
        self.assertEqual(result["status"], "success")
        get.assert_called_once_with(
            "https://api.apify.com/v2/users/me",
            timeout=api_key_tests.DEFAULT_TIMEOUT,
            headers={"Authorization": "Bearer SECRET-KEY-123"},
        )
        self.assertNotIn("SECRET-KEY-123", result["message"])

    def test_kalodata_missing_key_does_not_call_network(self):
        with patch.object(api_key_tests.requests, "post") as post:
            result = api_key_tests.test_kalodata_credentials("")
        self.assertEqual(result["status"], "missing")
        post.assert_not_called()

    def test_kalodata_uses_video_rank_with_documented_secret_key_and_bearer_auth(self):
        with patch.object(api_key_tests.requests, "post", return_value=self.response(200)) as post:
            result = api_key_tests.test_kalodata_credentials("SECRET-KEY-123")
        self.assertEqual(result["status"], "success")
        post.assert_called_once_with(
            "https://www.kalodata.com/openapi/v1/tiktok/video/rank",
            timeout=api_key_tests.DEFAULT_TIMEOUT,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "secret-key": "SECRET-KEY-123",
                "Authorization": "Bearer SECRET-KEY-123",
            },
            json={
                "region": "US",
                "language": "en-US",
                "currency": "USD",
                "date_range": "last7Day",
                "page_number": 1,
                "page_size": 1,
            },
        )
        self.assertNotIn("SECRET-KEY-123", str(result))

    def test_kalodata_invalid_credentials_are_reported_without_response_body(self):
        with patch.object(api_key_tests.requests, "post", return_value=self.response(401)) as post:
            result = api_key_tests.test_kalodata_credentials("SECRET-KEY-123", "https://www.kalodata.com/openapi/v1")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["status_code"], 401)
        self.assertNotIn("provider error", str(result))
        self.assertEqual(post.call_args.args[0], "https://www.kalodata.com/openapi/v1/tiktok/video/rank")

    def test_kalodata_rejects_invalid_base_url_without_network(self):
        with patch.object(api_key_tests.requests, "post") as post:
            result = api_key_tests.test_kalodata_credentials("SECRET-KEY-123", "not a url")
        self.assertEqual(result["status"], "error")
        post.assert_not_called()

    def test_together_media_test_uses_models_without_requiring_model_selection(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_media_provider_card({
                "provider": "together_ai",
                "api_key": "together-secret",
                "base_url": "https://api.together.ai/v1",
                "model": "",
            })
        self.assertEqual(result["status"], "success")
        self.assertEqual(get.call_args.args[0], "https://api.together.ai/v1/models")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer together-secret"})
        self.assertNotIn("together-secret", str(result))

    def test_innertube_uses_public_read_only_guide_request(self):
        with patch.object(api_key_tests.requests, "post", return_value=self.response(200)) as post:
            result = api_key_tests.test_innertube_api_key("SECRET-KEY-123")
        self.assertEqual(result["status"], "success")
        self.assertEqual(post.call_args.args[0], "https://www.youtube.com/youtubei/v1/guide?key=SECRET-KEY-123")
        self.assertEqual(post.call_args.kwargs["json"]["context"]["client"]["clientName"], "WEB")
        self.assertNotIn("SECRET-KEY-123", str(result))

    def test_innertube_missing_key_does_not_call_network(self):
        with patch.object(api_key_tests.requests, "post") as post:
            result = api_key_tests.test_innertube_api_key("")
        self.assertEqual(result["status"], "missing")
        post.assert_not_called()

    def test_provider_statuses_are_classified_without_raw_response_text(self):
        for status_code, expected in ((200, "success"), (204, "success"), (401, "error"), (403, "error"), (500, "error")):
            with self.subTest(status_code=status_code), patch.object(api_key_tests.requests, "get", return_value=self.response(status_code)):
                result = api_key_tests.test_elevenlabs_credentials("SECRET-KEY-123")
            self.assertEqual(result["status"], expected)
            self.assertNotIn("SECRET-KEY-123", str(result))
            self.assertNotIn("provider error", str(result))

    def test_network_failure_is_safe(self):
        with patch.object(api_key_tests.requests, "get", side_effect=api_key_tests.requests.RequestException("SECRET-KEY-123")):
            result = api_key_tests.test_postiz_credentials("SECRET-KEY-123")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "Não foi possível contactar o serviço.")
        self.assertNotIn("SECRET-KEY-123", str(result))

    def test_kaggle_credentials_check_requested_kernel_through_official_runner(self):
        from app.modules.niche_finder import kaggle_runner

        runner = Mock()
        runner.kernel_ref = "user/thunderbolt"
        with patch.object(kaggle_runner, "KaggleNicheRunner", return_value=runner) as constructor:
            result = api_key_tests.test_kaggle_credentials("user", "SECRET-KEY-123", "thunderbolt")

        constructor.assert_called_once_with("user", "SECRET-KEY-123", "thunderbolt")
        runner.api.kernels_status.assert_called_once_with("user/thunderbolt")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["status_code"], 200)
        self.assertIn("user/thunderbolt", result["message"])
        self.assertNotIn("SECRET-KEY-123", str(result))

    def test_kaggle_missing_slug_does_not_create_runner(self):
        from app.modules.niche_finder import kaggle_runner

        with patch.object(kaggle_runner, "KaggleNicheRunner") as constructor:
            result = api_key_tests.test_kaggle_credentials("user", "key", "")
        self.assertEqual(result["status"], "missing")
        self.assertIn("slug", result["message"].lower())
        constructor.assert_not_called()

    def test_kaggle_modern_token_does_not_require_username(self):
        from app.modules.niche_finder import kaggle_runner

        runner = Mock()
        runner.kernel_ref = "token-owner/thunderbolt"
        with patch.object(kaggle_runner, "KaggleNicheRunner", return_value=runner) as constructor:
            result = api_key_tests.test_kaggle_credentials("", "KGAT_example-token", "thunderbolt")
        constructor.assert_called_once_with("", "KGAT_example-token", "thunderbolt")
        runner.api.kernels_status.assert_called_once_with("token-owner/thunderbolt")
        self.assertEqual(result["status"], "success")
        self.assertIn("token-owner/thunderbolt", result["message"])

    def test_kaggle_404_and_permission_errors_are_clear_and_redacted(self):
        from app.modules.niche_finder import kaggle_runner

        runner = Mock()
        runner.kernel_ref = "user/missing-kernel"
        not_found = api_key_tests.requests.HTTPError("404 Not Found SECRET-KEY-123")
        not_found.response = self.response(404)
        runner.api.kernels_status.side_effect = not_found
        with patch.object(kaggle_runner, "KaggleNicheRunner", return_value=runner):
            missing = api_key_tests.test_kaggle_credentials("user", "SECRET-KEY-123", "missing-kernel")
        self.assertEqual(missing["status"], "error")
        self.assertEqual(missing["status_code"], 404)
        self.assertIn("não foi encontrada", missing["message"])
        self.assertNotIn("SECRET-KEY-123", str(missing))

        runner = Mock()
        runner.kernel_ref = "user/private-kernel"
        cause = api_key_tests.requests.HTTPError("403 Forbidden")
        cause.response = self.response(403)
        denied = ValueError("Cannot access kernel 'user/private-kernel' (Permission 'kernels.get' was denied).")
        denied.__cause__ = cause
        runner.api.kernels_status.side_effect = denied
        with patch.object(kaggle_runner, "KaggleNicheRunner", return_value=runner):
            forbidden = api_key_tests.test_kaggle_credentials("user", "SECRET-KEY-123", "private-kernel")
        self.assertEqual(forbidden["status"], "error")
        self.assertEqual(forbidden["status_code"], 403)
        self.assertIn("pública/acessível", forbidden["message"])
        self.assertNotIn("SECRET-KEY-123", str(forbidden))

    def test_read_only_endpoints_for_nano_upload_post_and_postiz(self):
        cases = [
            (lambda: api_key_tests.test_nano_banana_credentials("key", "gemini-3.1-flash-image"), "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image"),
            (lambda: api_key_tests.test_upload_post_credentials("key"), "https://api.upload-post.com/api/uploadposts/me"),
            (lambda: api_key_tests.test_postiz_credentials("key"), "https://api.postiz.com/public/v1/integrations"),
        ]
        for factory, expected_url in cases:
            with self.subTest(expected_url=expected_url), patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
                result = factory()
            self.assertEqual(result["status"], "success")
            self.assertEqual(get.call_args.args[0], expected_url)

    def test_google_lyria_uses_model_metadata_without_generating_audio(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_google_lyria_credentials("SECRET-KEY-123", "lyria-3-clip-preview")
        self.assertEqual(result["status"], "success")
        self.assertEqual(get.call_args.args[0], "https://generativelanguage.googleapis.com/v1beta/models/lyria-3-clip-preview")
        self.assertEqual(get.call_args.kwargs["headers"], {"x-goog-api-key": "SECRET-KEY-123"})
        self.assertNotIn("SECRET-KEY-123", str(result))

    def test_azure_uses_voice_listing_not_synthesis(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_azure_speech_credentials("key", "eastus")
        self.assertEqual(result["status"], "success")
        self.assertIn("/tts/cognitiveservices/voices/list", get.call_args.args[0])
        self.assertEqual(get.call_args.kwargs["headers"], {"Ocp-Apim-Subscription-Key": "key"})

    def test_tiktok_requires_oauth_token_instead_of_faking_client_secret_validation(self):
        with patch.object(api_key_tests.requests, "get") as get:
            result = api_key_tests.test_tiktok_credentials("client", "secret", "")
        self.assertEqual(result["status"], "unsupported")
        get.assert_not_called()

    def test_tiktok_calls_read_only_user_info_when_oauth_token_exists(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_tiktok_credentials("client", "secret", "oauth-token")
        self.assertEqual(result["status"], "success")
        self.assertEqual(get.call_args.args[0], "https://open.tiktokapis.com/v2/user/info/?fields=open_id")
        self.assertNotIn("oauth-token", str(result))

    def test_suno_does_not_start_a_generation_to_test_credentials(self):
        with patch.object(api_key_tests.requests, "post") as post:
            result = api_key_tests.test_suno_credentials("key", "https://example.test", "/api/generate")
        self.assertEqual(result["status"], "unsupported")
        post.assert_not_called()

    def test_material_sources_use_read_only_calls_and_unsupported_fallback(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_material_source_credentials("pexels", "key")
        self.assertEqual(result["status"], "success")
        self.assertEqual(get.call_args.args[0], "https://api.pexels.com/v1/curated")
        with patch.object(api_key_tests.requests, "get") as get:
            result = api_key_tests.test_material_source_credentials("wavespeed", "key")
        self.assertEqual(result["status"], "unsupported")
        get.assert_not_called()

    def test_media_provider_diagnostics_are_read_only_and_provider_aware(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_media_provider_card({
                "provider": "huggingface",
                "api_key": "hf-secret",
                "model": "black-forest-labs/FLUX.1-dev",
                "base_url": "https://router.huggingface.co/v1",
            })
        self.assertEqual(result["status"], "success")
        self.assertEqual(get.call_args.args[0], "https://huggingface.co/api/models")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer hf-secret"})
        self.assertEqual(get.call_args.kwargs["params"], {"pipeline_tag": "text-to-image", "limit": 1})
        self.assertNotIn("hf-secret", str(result))

        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_media_provider_card({
                "provider": "inferenceport",
                "base_url": "http://localhost:8080/v1",
                "model": "flux",
            })
        self.assertEqual(result["status"], "success")
        self.assertEqual(get.call_args.args[0], "http://localhost:8080/v1/models")

    def test_kie_media_diagnostic_uses_read_only_credit_endpoint(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_media_provider_card({
                "provider": "kie_ai",
                "api_key": "kie-secret",
                "base_url": "https://api.kie.ai/api/v1",
            })
        self.assertEqual(result["status"], "success")
        self.assertEqual(get.call_args.args[0], "https://api.kie.ai/api/v1/chat/credit")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer kie-secret"})
        self.assertNotIn("kie-secret", str(result))

    def test_fal_media_diagnostic_uses_models_api_and_key_auth(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_media_provider_card({
                "provider": "fal_ai",
                "api_key": "fal-secret",
                "model": "fal-ai/flux/dev",
                "base_url": "https://queue.fal.run",
            })
        self.assertEqual(result["status"], "success")
        self.assertEqual(get.call_args.args[0], "https://api.fal.ai/v1/models")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Key fal-secret"})
        self.assertNotIn("fal-secret", str(result))

    def test_heygen_media_diagnostic_uses_read_only_account_endpoint(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_media_provider_card({
                "provider": "heygen",
                "api_key": "heygen-secret",
                "base_url": "https://api.heygen.com",
            })
        self.assertEqual(result["status"], "success")
        self.assertEqual(get.call_args.args[0], "https://api.heygen.com/v3/users/me")
        self.assertEqual(get.call_args.kwargs["headers"], {"X-Api-Key": "heygen-secret"})
        self.assertNotIn("heygen-secret", str(result))

    def test_cloudflare_media_diagnostic_requires_account_id_without_network(self):
        with patch.object(api_key_tests.requests, "get") as get:
            result = api_key_tests.test_media_provider_card({
                "provider": "cloudflare_workers_ai",
                "api_key": "token",
                "base_url": "https://api.cloudflare.com/client/v4",
                "model": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
            })
        self.assertEqual(result["status"], "missing")
        get.assert_not_called()

    def test_cloudflare_media_diagnostic_uses_internal_models_endpoint(self):
        with patch.object(api_key_tests.requests, "get", return_value=self.response(200)) as get:
            result = api_key_tests.test_media_provider_card({
                "provider": "cloudflare_workers_ai",
                "api_key": "token",
                "base_url": "https://custom.example.invalid/ignored",
                "account_id": "account-123",
                "model": "@cf/meta/llama-3.1-8b-instruct",
            })
        self.assertEqual(result["status"], "success")
        self.assertEqual(get.call_args.args[0], "https://api.cloudflare.com/client/v4/accounts/account-123/ai/models/search")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer token"})
        self.assertNotIn("custom.example", get.call_args.args[0])

    def test_cloudflare_diagnostic_distinguishes_token_and_permission_errors(self):
        for status_code, expected in (
            (401, "rejeitado ou está expirado"),
            (403, "permissão Workers AI Read ou Workers AI Write"),
        ):
            with self.subTest(status_code=status_code), patch.object(api_key_tests.requests, "get", return_value=self.response(status_code)):
                result = api_key_tests.test_media_provider_card({
                    "provider": "cloudflare_workers_ai",
                    "api_key": "token",
                    "account_id": "account-123",
                })
            self.assertEqual(result["status"], "error")
            self.assertIn(expected, result["message"])


if __name__ == "__main__":
    unittest.main()
