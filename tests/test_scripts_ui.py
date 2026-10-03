from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
STORAGE_SOURCE = (ROOT / "hermes_ui" / "storage.py").read_text(encoding="utf-8")


def test_scripts_is_between_music_and_upload_in_pipeline():
    music_item = '("Criação de Músicas", ":material/music_note:", "Criação de Músicas")'
    scripts_item = '("Roteiros", ":material/article:", "Roteiros")'
    upload_item = '("Upload", ":material/cloud_upload:", "Upload")'
    assert music_item in MAIN_SOURCE
    assert scripts_item in MAIN_SOURCE
    assert upload_item in MAIN_SOURCE
    # A reorganização por caminhos (commit 7eda7c5, "reorganize UI navigation")
    # moveu "Criação de Músicas" para o grupo Pipeline Música e manteve
    # "Roteiros" no grupo Pipeline Vídeos, imediatamente antes de "Upload" — a
    # ordem anterior na fonte (Músicas < Roteiros < Upload) foi substituída por
    # deliberação nesse commit.
    pipeline_block = MAIN_SOURCE.split("    pipeline_video_items = [", 1)[1].split("    ]", 1)[0]
    assert pipeline_block.index(scripts_item) < pipeline_block.index(upload_item)
    assert '"Roteiros": render_scripts' in MAIN_SOURCE
    assert '"Roteiros": "/pipeline-videos/roteiros"' in MAIN_SOURCE


def test_scripts_ui_exposes_storage_paths_and_blueprint_generation():
    assert 'st.info(f"**Ficheiros guardados em:** `{script_dir}`' in MAIN_SOURCE
    assert 'st.caption(f"Os vídeos são guardados em `{STORAGE / \'videos\'}`.")' in MAIN_SOURCE
    assert "Gerar com IA a partir do Blueprint" in MAIN_SOURCE
    assert "Histórico guardado" in MAIN_SOURCE
    assert "Blueprint: {record.get('blueprint_name', '—')} · ID: {record.get('blueprint_id', '—')}" in MAIN_SOURCE


def test_saved_script_blueprint_backfill_keeps_documents_without_channel():
    assert '"Attach every saved video script to its channel or stored Blueprint."' in MAIN_SOURCE
    assert "if not channel:\n            continue" not in MAIN_SOURCE[MAIN_SOURCE.index("def _backfill_saved_script_blueprints"):MAIN_SOURCE.index("def channel_video_language")]


def test_storage_has_script_history_default():
    assert '"scripts.json": []' in STORAGE_SOURCE
