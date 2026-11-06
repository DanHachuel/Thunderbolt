"""1.0.66 - reaproveitamento de audio no "Refazer Video" + retry WinError 32.

Contexto do relato: o utilizador clicou em "Refazer Video" e levou um WinError 32
na pasta azure-v2-chunks. A investigacao provou que o remake DESCARTAVA todos os
artefos de audio (`domain.remake_video_task`), pelo que o worker nao tinha nada
para passar como audio customizado e o mpt_agent ressintetizava o roteiro inteiro
no Azure a cada clique - tempo, dinheiro e ficheiros temporarios retidos no
Windows. Estes testes prendem o contrato novo.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_ui import domain, pipeline_worker, storage


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_SOURCE = (ROOT / "hermes_ui" / "domain.py").read_text(encoding="utf-8")
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
MPT_AGENT_SOURCE = (ROOT / "seed" / "skills" / "mpt_agent.py").read_text(encoding="utf-8")
CHUNKED_SOURCE = (ROOT / "seed" / "skills" / "azure_tts_chunked.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. domain: o remake mantem o audio valido
# ---------------------------------------------------------------------------


def _isolate(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(storage, "TIKTOK_PROMPT_MASTERS", root / "tiktok" / "prompts_master")
    monkeypatch.setattr(storage, "MEDIA_DOWNLOADS", root / "downloads")
    monkeypatch.setattr(domain.storage_module, "STORAGE", root)
    storage.ensure_storage()
    return root


def test_remake_keeps_valid_audio_and_drops_only_the_video(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    audio = tmp_path / "narracao-valida.mp3"
    audio.write_bytes(b"ID3-audio-valido")
    storage.write_json("channels.json", [{"id": "channel-1", "name": "Canal", "platform": "youtube"}])
    storage.write_json("tasks.json", [{
        "id": "video-1",
        "state": "done",
        "stage": "edit",
        "script": "roteiro preservado",
        "channel_id": "channel-1",
        "audio_path": str(audio),
        "artifacts": {
            "video": str(tmp_path / "final-1.mp4"),
            "audio": str(audio),
            "narration": str(audio),
            "script": str(tmp_path / "roteiro.md"),
            "thumbnail": str(tmp_path / "thumb.png"),
        },
    }])

    remade = domain.remake_video_task("video-1")

    assert remade is not None
    artifacts = remade["artifacts"]
    # Regra de ouro: so o video (e o upload) saem.
    assert artifacts.get("video") is None
    assert artifacts.get("upload") is None
    # O audio VALIDO fica - nenhuma chamada ao Azure no clique.
    assert artifacts["audio"] == str(audio)
    assert artifacts["narration"] == str(audio)
    assert artifacts["script"], "o roteiro preservado continua"
    assert artifacts["thumbnail"], "a thumbnail preservada continua"
    # A flag morta (escrita e nunca lida) foi removida.
    assert "audio_regeneration_requested" not in remade
    # A tarefa volta a fila para remontar.
    assert remade["state"] == "to_do" and remade["stage"] == "video"


def test_remake_drops_audio_whose_file_disappeared(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.write_json("channels.json", [{"id": "channel-1", "name": "Canal", "platform": "youtube"}])
    storage.write_json("tasks.json", [{
        "id": "video-2",
        "state": "done",
        "stage": "edit",
        "script": "roteiro",
        "channel_id": "channel-1",
        "artifacts": {"audio": str(tmp_path / "audio-que-nao-existe.mp3"), "script": "x"},
    }])

    remade = domain.remake_video_task("video-2")

    assert remade["artifacts"].get("audio") is None, "audio inexistente sai - o worker gera de novo"


# ---------------------------------------------------------------------------
# 2. worker: deteccao do audio reaproveitavel + --custom-audio-file
# ---------------------------------------------------------------------------


def test_worker_reuses_valid_audio_artifact():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "azure-v2-audio.mp3"
        audio.write_bytes(b"audio")
        task = {"artifacts": {"audio": str(audio)}}
        assert pipeline_worker._task_audio_for_reuse(task) == audio.resolve()


def test_worker_ignores_missing_or_invalid_audio():
    assert pipeline_worker._task_audio_for_reuse({"artifacts": {"audio": ""}}) is None
    assert pipeline_worker._task_audio_for_reuse({"artifacts": {}}) is None
    assert pipeline_worker._task_audio_for_reuse({}) is None
    # ficheiro inexistente em disco
    assert pipeline_worker._task_audio_for_reuse({"artifacts": {"audio": "Z:/nao/existe.mp3"}}) is None


def test_worker_passes_custom_audio_when_reusing():
    wiring = WORKER_SOURCE.split('elif generated_elevenlabs_audio is not None:', 1)[1]
    block = wiring.split('command.extend(["--custom-audio-file", str(reusable_audio.resolve())])', 1)[0]
    assert "_task_audio_for_reuse(task)" in block
    assert "[MPT-AUDIO] audio existente reaproveitado" in WORKER_SOURCE
    # o caminho volta do protocolo do helper e fica nos artefactos
    assert 're.search(r"(?m)^AUDIO_FILE=(.+)$", output)' in WORKER_SOURCE
    assert 'task_artifacts["audio"] = str(helper_audio_path)' in WORKER_SOURCE


# ---------------------------------------------------------------------------
# 3. mpt_agent: verificacao de integridade (voz) e reaproveitamento
# ---------------------------------------------------------------------------


def test_mpt_agent_reuses_azure_audio_when_voice_matches(tmp_path):
    from seed.skills import mpt_agent  # noqa: PLC0415

    task_dir = tmp_path / "task"
    task_dir.mkdir()
    audio = task_dir / "azure-v2-audio.mp3"
    audio.write_bytes(b"audio-azure-valido")
    (task_dir / "azure-v2-audio.json").write_text(
        json.dumps({"status": "completed", "voice": "pt-BR-FranciscaNeural-Female", "rate": 1.0}),
        encoding="utf-8",
    )

    reused = mpt_agent._reusable_azure_v2_audio(task_dir, "pt-BR-FranciscaNeural-Female", 1.0)
    assert reused == audio.resolve()


def test_mpt_agent_does_not_reuse_audio_with_a_different_voice(tmp_path):
    from seed.skills import mpt_agent  # noqa: PLC0415

    task_dir = tmp_path / "task"
    task_dir.mkdir()
    audio = task_dir / "azure-v2-audio.mp3"
    audio.write_bytes(b"audio")
    (task_dir / "azure-v2-audio.json").write_text(
        json.dumps({"status": "completed", "voice": "en-US-JennyNeural", "rate": 1.0}),
        encoding="utf-8",
    )

    assert mpt_agent._reusable_azure_v2_audio(task_dir, "pt-BR-FranciscaNeural-Female", 1.0) is None


def test_mpt_agent_does_not_reuse_empty_audio_or_missing_metadata(tmp_path):
    from seed.skills import mpt_agent  # noqa: PLC0415

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    (empty_dir / "azure-v2-audio.mp3").write_bytes(b"")
    (empty_dir / "azure-v2-audio.json").write_text(json.dumps({"status": "completed", "voice": "v", "rate": 1.0}), encoding="utf-8")
    assert mpt_agent._reusable_azure_v2_audio(empty_dir, "v", 1.0) is None, "audio vazio nao se reaproveita"

    no_meta = tmp_path / "no-meta"
    no_meta.mkdir()
    audio = no_meta / "azure-v2-audio.mp3"
    audio.write_bytes(b"audio")
    assert mpt_agent._reusable_azure_v2_audio(no_meta, "v", 1.0) is None, "sem metadados nao ha como provar a voz"


def test_mpt_agent_writes_voice_and_rate_metadata():
    assert '"voice": voice,' in MPT_AGENT_SOURCE
    assert '"rate": float(_voice_rate(cli_args)),' in MPT_AGENT_SOURCE


def test_mpt_agent_publishes_audio_file_on_the_protocol():
    assert "def _protocol_audio_file(" in MPT_AGENT_SOURCE
    assert 'print(f"AUDIO_FILE={audio_file}")' in MPT_AGENT_SOURCE


# ---------------------------------------------------------------------------
# 4. azure_tts_chunked: retry nas operacoes de ficheiro
# ---------------------------------------------------------------------------


def test_chunked_synthesis_retries_file_operations():
    assert "FILE_RETRY_COUNT = 4" in CHUNKED_SOURCE
    assert "def _retry_file_operation(" in CHUNKED_SOURCE
    assert "def _remove_with_retry(" in CHUNKED_SOURCE
    assert "_remove_with_retry(segment_path)" in CHUNKED_SOURCE
    # exportacao por temporario + mover com retry (nunca deixa o output travado)
    assert "staged_output" in CHUNKED_SOURCE
    assert 'os.replace(staged_output, output)' in CHUNKED_SOURCE
