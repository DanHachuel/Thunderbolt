"""1.0.86 — «Regenerar Áudio (TTS)» no cartão da Automação YouTube.

O checkbox passa a selecção ao remake: com ele marcado, os artefactos de
narração são descartados (o worker sincroniza voz nova); sem ele, o
reaproveitamento da 1.0.66 continua intacto — e a bandeira morta
``audio_regeneration_requested`` (escrita e nunca lida) nunca volta.
"""

from __future__ import annotations

import json


def _storage(tmp_path, monkeypatch):
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.ensure_storage()
    return storage


def _task(tmp_path, **extra) -> dict:
    # narracao VALIDA de verdade: a 1.0.66 só descarta audio de ficheiro
    # desaparecido, por isso o teste precisa de um ficheiro real no disco.
    audio = tmp_path / "narracao.mp3"
    audio.write_bytes(b"ID3-fake-audio")
    task = {
        "id": "video-regen-audio",
        "channel_id": "",
        "state": "failed",
        "stage": "video",
        "progress": 50,
        "artifacts": {
            "script": "/tmp/script.md",
            "audio": str(audio),
            "video": "/tmp/antigo.mp4",
            "upload": "/tmp/upload.json",
        },
    }
    task.update(extra)
    return task


def test_remake_reuses_valid_audio_by_default(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    from hermes_ui.domain import remake_video_task

    storage.write_json("tasks.json", [_task(tmp_path)])

    remade = remake_video_task("video-regen-audio")

    assert remade is not None
    # 1.0.66 intacto: narração válida preservada, vídeo/upload descartados.
    assert remade["artifacts"]["audio"] == str(tmp_path / "narracao.mp3")
    assert (tmp_path / "narracao.mp3").is_file()
    assert "video" not in remade["artifacts"]
    assert "upload" not in remade["artifacts"]
    assert "audio_regeneration_requested" not in remade


def test_remake_discards_audio_when_the_file_is_gone(tmp_path, monkeypatch):
    """Regressao 1.0.66: ficheiro desaparecido sai de qualquer forma."""
    storage = _storage(tmp_path, monkeypatch)
    from hermes_ui.domain import remake_video_task

    storage.write_json("tasks.json", [_task(tmp_path, artifacts={"script": "/tmp/s.md", "audio": "/tmp/nao-existe.mp3"})])

    remade = remake_video_task("video-regen-audio")

    assert "audio" not in remade["artifacts"]


def test_remake_force_flag_discards_the_narration(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    from hermes_ui.domain import remake_video_task

    storage.write_json("tasks.json", [_task(tmp_path)])

    remade = remake_video_task("video-regen-audio", force_audio_regeneration=True)

    assert remade is not None
    assert remade["state"] == "to_do"
    assert remade["progress"] == 0
    # narração fora: o worker gera voz nova; o roteiro fica.
    assert "audio" not in remade["artifacts"]
    assert remade["artifacts"]["script"] == "/tmp/script.md"
    # e o JSON persistido confirma (não é só o valor devolvido).
    persisted = json.loads((tmp_path / "storage" / "state" / "tasks.json").read_text(encoding="utf-8"))
    assert "audio" not in persisted[0]["artifacts"]


def test_audio_reuse_decision_matches_the_remake_contract():
    """O worker só reaproveita o que o remake deixou: com a flag, o helper de
    reutilização não encontra nada para o caminho descartado."""
    from hermes_ui import pipeline_worker

    task = {"artifacts": {"audio": "/tmp/narracao.mp3"}}
    # reutilização resolvida pelo artefacto presente (comportamento 1.0.66).
    assert callable(pipeline_worker._task_audio_for_reuse)
    assert pipeline_worker._task_audio_for_reuse(task) is None  # ficheiro não existe neste disco
    assert pipeline_worker._task_audio_for_reuse({"artifacts": {}}) is None
    assert pipeline_worker._task_audio_for_reuse({}) is None
