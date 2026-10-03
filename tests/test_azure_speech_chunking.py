from __future__ import annotations

import importlib.util
import pytest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHUNKED = _load_module(ROOT / "seed" / "skills" / "azure_tts_chunked.py", "azure_tts_chunked_test")
MPT_AGENT = _load_module(ROOT / "seed" / "skills" / "mpt_agent.py", "mpt_agent_test")


def test_mpt_agent_requires_moneyprinter_moviepy_release(tmp_path, monkeypatch):
    calls = []

    def fake_run_checked(command, *, cwd):
        calls.append((command, cwd))

    monkeypatch.setattr(MPT_AGENT, "run_checked", fake_run_checked)
    MPT_AGENT.ensure_moviepy(tmp_path, "uv")

    command, cwd = calls[0]
    assert cwd == tmp_path
    assert command[:4] == ["uv", "run", "--with", "moviepy==2.2.1"]
    # O mpt_agent passou a reportar a versão instalada (importlib.metadata) em
    # vez de afirmar moviepy.__version__ dentro do comando.
    assert command[-2:] == ["-c", "import importlib.metadata; print(f\"moviepy {importlib.metadata.version('moviepy')}\")"]


def test_split_text_keeps_chunks_below_safe_request_size():
    text = "Parágrafo inicial. " + ("palavra " * 700) + "Fim."
    chunks = CHUNKED.split_text(text, limit=1800)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 1800 for chunk in chunks)
    assert "Parágrafo inicial" in chunks[0]
    assert "Fim" in chunks[-1]


def test_split_text_handles_newlines_and_long_unbroken_tokens():
    chunks = CHUNKED.split_text("linha um\nlinha dois\n" + ("x" * 5000), limit=500)
    assert len(chunks) > 2
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "linha um" in chunks[0]
    assert chunks[-1] == "x" * 500


def test_build_ssml_escapes_voice_and_text_without_invalid_f_string():
    ssml = CHUNKED._build_ssml('Capital & <cashflow>', 'en-US-Test "Voice"', 1.0)

    assert 'name="en-US-Test &quot;Voice&quot;"' in ssml
    assert 'Capital &amp; &lt;cashflow&gt;' in ssml


def test_mpt_agent_applies_azure_environment_to_azure_toml_section(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[app]\npexels_api_keys = []\n\n[azure]\nspeech_key = ""\nspeech_region = ""\n', encoding="utf-8")
    monkeypatch.setenv("MPT_AZURE_SPEECH_KEY", "azure-test-key")
    monkeypatch.setenv("MPT_AZURE_SPEECH_REGION", "eastus")

    MPT_AGENT.apply_environment_config(config_path)

    assert MPT_AGENT._toml_section_value(config_path, "azure", "speech_key") == "azure-test-key"
    assert MPT_AGENT._toml_section_value(config_path, "azure", "speech_region") == "eastus"


def test_mpt_agent_prepares_azure_audio_without_logging_credentials(tmp_path, monkeypatch):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    config_path = root / "config.toml"
    config_path.write_text('[azure]\nspeech_key = "azure-secret"\nspeech_region = "eastus"\n', encoding="utf-8")
    task_dir = root / "storage" / "tasks" / "task-1"
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"prepared-audio")
        return SimpleNamespace(returncode=0, stdout="AZURE_CHUNK_COUNT=4\n")

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    result = MPT_AGENT._prepare_azure_v2_chunked_audio(
        root,
        config_path,
        task_dir,
        [
            "--video-script",
            "Roteiro longo preparado",
            "--voice-name",
            "en-US-BrianMultilingualNeural-V2-Male",
            "--voice-rate",
            "1.25",
        ],
        "/usr/bin/uv",
    )

    assert result == task_dir / "azure-v2-audio.mp3"
    command = captured["command"]
    assert command[command.index("--project") + 1] == str(root)
    assert command[command.index("--voice") + 1] == "en-US-BrianMultilingualNeural"
    assert command[command.index("--rate") + 1] == "1.25"
    environment = captured["env"]
    assert environment["AZURE_SPEECH_KEY"] == "azure-secret"
    assert environment["AZURE_SPEECH_REGION"] == "eastus"
    assert "azure-secret" not in str(captured["command"])


def test_synthesise_chunk_supports_speech_sdk_without_close_method(tmp_path, monkeypatch):
    target = tmp_path / "segment.mp3"
    monkeypatch.setenv("AZURE_SPEECH_KEY", "azure-test-key")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "eastus")

    class Result:
        reason = "completed"

    class AsyncResult:
        def get(self):
            target.write_bytes(b"audio")
            return Result()

    class SpeechConfig:
        def __init__(self, **_kwargs):
            self.speech_synthesis_voice_name = ""

        def set_speech_synthesis_output_format(self, _format):
            return None

    class AudioOutputConfig:
        def __init__(self, **_kwargs):
            return None

    class SpeechSynthesizer:
        def __init__(self, **_kwargs):
            return None

        def speak_ssml_async(self, _ssml):
            return AsyncResult()

    fake_speech_sdk = SimpleNamespace(
        ResultReason=SimpleNamespace(SynthesizingAudioCompleted="completed"),
        SpeechSynthesisOutputFormat=SimpleNamespace(Audio48Khz192KBitRateMonoMp3="mp3"),
        SpeechConfig=SpeechConfig,
        SpeechSynthesizer=SpeechSynthesizer,
        audio=SimpleNamespace(AudioOutputConfig=AudioOutputConfig),
    )

    CHUNKED._synthesise_chunk(fake_speech_sdk, "Texto", "en-US-TestNeural", 1.0, target)

    assert target.read_bytes() == b"audio"


def test_mpt_agent_does_not_prepare_audio_without_azure_v2_voice(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[azure]\nspeech_key = "secret"\nspeech_region = "eastus"\n', encoding="utf-8")
    monkeypatch.setattr(MPT_AGENT.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("não deve chamar Azure")))
    assert MPT_AGENT._prepare_azure_v2_chunked_audio(
        tmp_path,
        config_path,
        tmp_path / "task",
        ["--video-script", "Roteiro", "--voice-name", "en-US-BrianMultilingualNeural-Male"],
        "/usr/bin/uv",
    ) is None


def test_generate_video_injects_chunked_audio_into_moneyprinter_command(tmp_path, monkeypatch):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    prepared_audio = tmp_path / "azure-v2-audio.mp3"
    prepared_audio.write_bytes(b"audio")
    captured: dict[str, object] = {}

    monkeypatch.setattr(MPT_AGENT.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(MPT_AGENT, "run_checked", lambda *args, **kwargs: None)
    monkeypatch.setattr(MPT_AGENT, "_prepare_azure_v2_chunked_audio", lambda *args, **kwargs: prepared_audio)

    def fake_run(command, **kwargs):
        captured["command"] = command
        task_id = command[command.index("--task-id") + 1]
        output = root / "storage" / "tasks" / task_id / "final-video.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    videos, task_dir, _log_path, _result_path = MPT_AGENT.generate_video(
        root,
        "Tema longo",
        [
            "--video-source",
            "pexels",
            "--video-script",
            "Roteiro preparado",
            "--voice-name",
            "en-US-BrianMultilingualNeural-V2-Male",
        ],
    )

    command = captured["command"]
    assert command[command.index("--custom-audio-file") + 1] == str(prepared_audio)
    assert command[command.index("--voice-name") + 1] == "en-US-BrianMultilingualNeural-V2-Male"
    assert videos == [task_dir / "final-video.mp4"]


def test_chunk_character_limit_is_conservative_and_rate_aware():
    assert CHUNKED.chunk_character_limit(0.25) == 225
    assert CHUNKED.chunk_character_limit(1.0) == 900
    assert CHUNKED.chunk_character_limit(4.0) == 900
    slow_chunks = CHUNKED.split_text("palavra " * 1000, limit=CHUNKED.chunk_character_limit(0.25))
    assert len(slow_chunks) > 1
    assert all(len(chunk) <= 225 for chunk in slow_chunks)


def test_prepare_rejects_audio_without_segment_count_and_redacts_credentials(tmp_path, monkeypatch):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    config_path = root / "config.toml"
    config_path.write_text(
        '[azure]\nspeech_key = "azure-secret"\nspeech_region = "eastus"\n',
        encoding="utf-8",
    )
    task_dir = root / "storage" / "tasks" / "task-fail"

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"audio-without-proof")
        return SimpleNamespace(
            returncode=0,
            stdout="Azure Speech V2 chunked synthesis failed: azure-secret eastus\n",
        )

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    with pytest.raises(MPT_AGENT.SkillError) as raised:
        MPT_AGENT._prepare_azure_v2_chunked_audio(
            root,
            config_path,
            task_dir,
            [
                "--video-script",
                "Roteiro longo",
                "--voice-name",
                "en-US-BrianMultilingualNeural-v2-Male",
            ],
            "/usr/bin/uv",
        )
    assert "azure-secret" not in str(raised.value)
    assert "eastus" not in str(raised.value)
    assert "não confirmou segmentos" in str(raised.value)


def test_generate_video_stops_before_upstream_when_chunked_audio_is_unavailable(tmp_path, monkeypatch):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "config.toml").write_text(
        '[azure]\nspeech_key = "key"\nspeech_region = "eastus"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(MPT_AGENT.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(MPT_AGENT, "run_checked", lambda *args, **kwargs: None)
    monkeypatch.setattr(MPT_AGENT, "_prepare_azure_v2_chunked_audio", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        MPT_AGENT.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("não deve iniciar a CLI upstream"),
    )
    with pytest.raises(MPT_AGENT.SkillError, match="não produziu áudio segmentado"):
        MPT_AGENT.generate_video(
            root,
            "Tema prioritário",
            [
                "--video-script",
                "Roteiro preparado",
                "--voice-name",
                "en-US-BrianMultilingualNeural-V2-Male",
            ],
        )


def test_run_checked_surfaces_uv_failure_detail_without_secret(tmp_path, monkeypatch):
    secret = "uv-secret-api-key"

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout=f"error: resolver failed for package; token={secret}\n",
        )

    monkeypatch.setenv("MPT_LLM_API_KEY", secret)
    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    with pytest.raises(MPT_AGENT.SkillError) as raised:
        MPT_AGENT.run_checked(["uv", "sync", "--frozen"], cwd=tmp_path)
    message = str(raised.value)
    assert "resolver failed" in message
    assert secret not in message
