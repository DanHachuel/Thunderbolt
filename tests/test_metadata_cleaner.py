import subprocess
from pathlib import Path


def _isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()
    return storage


def test_description_and_tags_follow_workflow_shape():
    from hermes_ui.metadata_cleaner import build_description, normalize_tags

    description = build_description(
        "Uma prévia interessante sobre o tema.",
        "Website: https://example.com",
        "00:00 Introdução\n01:00 Conclusão",
    )
    assert description == (
        "Uma prévia interessante sobre o tema.\n\n"
        "Links:\nWebsite: https://example.com\n\n"
        "00:00 Introdução\n01:00 Conclusão"
    )
    assert normalize_tags("#ia, youtube, IA; produtividade") == ["ia", "youtube", "produtividade"]


def test_external_video_is_copied_and_clean_output_is_recorded(tmp_path, monkeypatch):
    storage = _isolate_storage(tmp_path, monkeypatch)
    from hermes_ui import metadata_cleaner

    source, digest = metadata_cleaner.store_external_video("vídeo terceiro.mp4", b"original-video")
    assert source.exists()
    assert len(digest) == 64
    assert source.read_bytes() == b"original-video"

    def fake_run(command, capture_output, text, check, creationflags=0, **kwargs):
        Path(command[-1]).write_bytes(b"clean-video")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(metadata_cleaner.subprocess, "run", fake_run)
    output, run_info = metadata_cleaner.clean_video_metadata(
        source,
        {"title": "Vídeo limpo", "description": "Descrição", "tags": ["um", "dois"]},
        ffmpeg_path="/fake/ffmpeg",
    )
    assert output.exists()
    assert output.read_bytes() == b"clean-video"
    assert "-map_metadata" in run_info["command"]
    assert "title=Vídeo limpo" in run_info["command"]

    record = metadata_cleaner.save_edit_record(source, output, {"title": "Vídeo limpo", "tags": "um, dois"}, run_info)
    assert record["source_type"] == "third_party_video"
    assert record["metadata"]["tags"] == ["um", "dois"]
    assert storage.read_json("metadata_edits.json")[0]["output_name"] == output.name
    assert metadata_cleaner.metadata_manifest(record).startswith(b"{")
