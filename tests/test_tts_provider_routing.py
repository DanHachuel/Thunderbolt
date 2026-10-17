"""1.0.02: encaminhamento do provider de narração após a descontinuação do Edge TTS.

Out/2026: a Microsoft passou a recusar o endpoint
wss://speech.platform.bing.com (HTTP 403) usado pela edge-tts <=7.2.8 do PyPI
— o fix só existe no branch principal do GitHub. "Azure TTS V1" do MPT é Edge
TTS; sem sufixo -V2 a voz cai no fallback azure_tts_v1 (edge). Estes testes
fixam a nova cadeia: credenciais Azure → Azure Speech real; sem credenciais →
bloqueio com mensagem clara; falhas do edge atribuídas no card como
"Edge TTS descontinuado" em vez de "API não identificada".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hermes_ui.voice_preview import EDGE_TTS_DEPRECATED_MESSAGE, resolve_narration_provider

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
TEXT_TO_IMAGES_SOURCE = (ROOT / "hermes_ui" / "text_to_images.py").read_text(encoding="utf-8")

AZURE_SETTINGS = {"azure_speech_key": "key", "azure_speech_region": "eastus"}


def test_v1_service_with_azure_credentials_uses_real_azure():
    # o user só usa Azure Speech: com credenciais, "Azure TTS V1" deixa de
    # significar edge e passa a usar o endpoint cognitiveservices real
    assert resolve_narration_provider("Azure TTS V1", AZURE_SETTINGS) == "azure_speech"
    assert resolve_narration_provider("", AZURE_SETTINGS) == "azure_speech"


def test_v2_service_always_uses_azure_speech():
    for service in ("Azure Speech SDK V2", "Azure speech", "Azure TTS V2"):
        assert resolve_narration_provider(service, {}) == "azure_speech"


def test_elevenlabs_maps_directly_without_azure_credentials():
    assert resolve_narration_provider("ElevenLabs", {}) == "elevenlabs"


def test_edge_without_credentials_is_blocked_with_clear_message():
    with pytest.raises(RuntimeError) as excinfo:
        resolve_narration_provider("Azure TTS V1", {})
    assert str(excinfo.value) == EDGE_TTS_DEPRECATED_MESSAGE
    assert "speech.platform.bing.com" in str(excinfo.value)


def test_local_chain_uses_resolved_provider_and_logs_it(tmp_path, monkeypatch, capsys):
    """A cadeia local (Remotion/text_to_images/web_images/blueprints) resolve o
    provider por credenciais e loga no stderr quem foi chamado antes de falhar."""
    import hermes_ui.text_to_images as text_to_images

    captured: list[tuple[str, str, str]] = []

    def fake_preview(chunk, provider, voice, settings):
        captured.append((provider, voice, chunk))
        path = tmp_path / f"chunk{len(captured)}.mp3"
        path.write_bytes(b"mp3")
        return path

    monkeypatch.setattr(text_to_images, "synthesize_preview", fake_preview)
    result = text_to_images.synthesize_text_to_images_audio(
        "Uma frase curta de teste.",
        {"voiceover_service": "Azure TTS V1", **AZURE_SETTINGS},
        "pt-BR-FranciscaNeural-Female",
        tmp_path / "out.mp3",
    )
    assert result == tmp_path / "out.mp3"
    assert captured[0][0] == "azure_speech", "não pode cair no edge com credenciais"
    assert "[tts] provider=azure_speech" in capsys.readouterr().err


def test_local_chain_blocks_edge_without_credentials(tmp_path):
    import hermes_ui.text_to_images as text_to_images

    with pytest.raises(RuntimeError) as excinfo:
        text_to_images.synthesize_text_to_images_audio(
            "Frase.",
            {"voiceover_service": "Azure TTS V1"},
            "pt-BR-FranciscaNeural-Female",
            tmp_path / "out.mp3",
        )
    assert "Edge TTS descontinuado" in str(excinfo.value)


def test_mpt_route_blocks_plain_voice_without_azure_credentials():
    from hermes_ui.pipeline_worker import _mpt_edge_narration_blocked_reason

    task = {"voice": "en-US-JennyNeural-Female", "generation_settings": {"voiceover_service": "Azure TTS V1", "voiceover_mode": "auto"}}
    reason = _mpt_edge_narration_blocked_reason(task, {})
    assert reason is not None
    assert "Edge TTS" in reason
    assert "-V2-" in reason


def test_mpt_route_with_azure_credentials_promotes_voice_and_does_not_block():
    from hermes_ui.pipeline_worker import _azure_speech_v2_voice_name, _mpt_edge_narration_blocked_reason

    task = {"voice": "en-US-JennyNeural-Female", "generation_settings": {"voiceover_service": "Azure TTS V1", "voiceover_mode": "auto"}}
    assert _mpt_edge_narration_blocked_reason(task, AZURE_SETTINGS) is None
    assert _azure_speech_v2_voice_name("en-US-JennyNeural-Female").endswith("-V2-Female")


def test_mpt_route_allows_v2_prefixed_and_explicit_modes():
    from hermes_ui.pipeline_worker import _mpt_edge_narration_blocked_reason

    v2 = {"voice": "en-US-AvaMultilingualNeural-V2-Female", "generation_settings": {"voiceover_mode": "auto"}}
    assert _mpt_edge_narration_blocked_reason(v2, {}) is None
    eleven = {"voice": "elevenlabs:21m00Tcm4TlvDq8ikWAM:arya", "generation_settings": {"voiceover_mode": "auto"}}
    assert _mpt_edge_narration_blocked_reason(eleven, {}) is None
    upload = {"voice": "en-US-JennyNeural-Female", "generation_settings": {"voiceover_mode": "upload"}}
    assert _mpt_edge_narration_blocked_reason(upload, {}) is None
    empty = {"voice": "", "generation_settings": {}}
    assert _mpt_edge_narration_blocked_reason(empty, {}) is None


def test_pipeline_calls_edge_guard_before_mpt_helper():
    assert "blocked_reason = _mpt_edge_narration_blocked_reason(" in PIPELINE_SOURCE
    # a cadeia local resolve por credenciais e loga o provider efectivo
    assert "resolve_narration_provider(settings.get(\"voiceover_service\"), settings)" in TEXT_TO_IMAGES_SOURCE
    assert "[tts] provider=" in TEXT_TO_IMAGES_SOURCE


def test_edge_403_from_bing_is_attributed_as_deprecated_provider():
    """O 403 real (reproduzido: aiohttp.WSServerHandshakeError com a URL do
    endpoint morto) deixa de cair em "API não identificada (falha anterior)"."""
    from hermes_ui.pipeline_worker import _failure_attribution, _failure_message

    error = (
        "403, message='Invalid response status', url='wss://speech.platform.bing.com/consumer/"
        "speech/synthesize/readaloud/edge/v1?TrustedClientToken=6A5AA1D4EAFF4E9FB37E23D68491D6F4"
        "&ConnectionId=23cfcb3f&Sec-MS-GEC=29EB4B0A&Sec-MS-GEC-Version=1-143.0.3650.75'"
    )
    metadata = _failure_attribution({"style_wide": "pexels"}, {}, "video", error=error)
    assert "Edge TTS" in metadata["failure_api"]
    assert "descontinuado pela Microsoft em Out/2026" in metadata["failure_api"]
    assert metadata["failure_provider"] == "edge_tts"
    assert metadata["failure_config_fields"] == "azure_speech_key, azure_speech_region"
    card = _failure_message("403, message='Invalid response status'", metadata)
    assert "Falha no provider: Edge TTS" in card
    assert "API não identificada" not in card


def test_edge_save_translates_403_into_deprecation_message(tmp_path, monkeypatch):
    """Previews com provider edge recebem a mensagem clara, não o stack do aiohttp."""
    import edge_tts

    import hermes_ui.voice_preview as voice_preview

    class _DeadEdgeCommunicate:
        def __init__(self, text, voice, **kwargs):
            pass

        def save(self, output):
            raise RuntimeError(
                "403, message='Invalid response status', "
                "url='wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1"
                "?TrustedClientToken=6A5AA&Sec-MS-GEC=29EB4B0A&Sec-MS-GEC-Version=1-143.0.3650.75'"
            )

    monkeypatch.setattr(edge_tts, "Communicate", _DeadEdgeCommunicate)
    with pytest.raises(RuntimeError) as excinfo:
        voice_preview._save_edge("texto", "pt-BR-FranciscaNeural", tmp_path / "edge.mp3", "+0%")
    assert "Edge TTS descontinuado" in str(excinfo.value)
