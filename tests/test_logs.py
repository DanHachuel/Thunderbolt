from pathlib import Path


def _isolated_storage(tmp_path):
    from hermes_ui import storage

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.TIKTOK_PROMPT_MASTERS = storage.STORAGE / "tiktok" / "prompts_master"
    storage.ensure_storage()
    return storage


def test_logs_download_uses_moneyprinter_agent_logs_directory():
    source = Path(__file__).resolve().parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'root / ".agent-logs" / "moneyprinterturbo-video"' in source
    assert 'path.is_dir()' in source
    assert '"# Logs do MoneyPrinterTurbo"' in source
    assert '"text/markdown"' in source
    assert 'f"{files[0].stem}.md"' in source
    assert 'mime=log_download[2]' in source
    assert 'disabled=log_download is None' in source


def test_list_logs_projects_tasks_and_notifications_with_required_fields(tmp_path):
    storage = _isolated_storage(tmp_path / "projection")
    from hermes_ui.logs import list_logs, logs_to_rows
    from hermes_ui.notifications import record_notification

    storage.write_json("tasks.json", [
        {
            "id": "video-pending",
            "state": "to_do",
            "stage": "script",
            "title": "Vídeo pendente",
            "channel_name": "Canal de teste",
            "progress": 0,
            "created_at": "2026-08-26T10:00:00+00:00",
            "updated_at": "2026-08-26T10:01:00+00:00",
        },
        {
            "id": "video-running",
            "state": "doing",
            "stage": "video",
            "title": "Vídeo em execução",
            "channel_name": "Canal de teste",
            "video_log": r"C:\Users\USUARIO\AppData\Local\THUNDERBOLT\MoneyPrinterTurbo\.agent-logs\moneyprinterturbo-video\run-00bbe89c-6b6c-48a3-a6b1-70aaed70ceef.log",
            "progress": 72,
            "created_at": "2026-08-26T10:00:00+00:00",
            "updated_at": "2026-08-26T10:02:00+00:00",
        },
        {
            "id": "video-failed",
            "state": "failed",
            "stage": "video",
            "title": "Vídeo com falha",
            "channel_name": "Canal de teste",
            "error": "Timeout do Motor",
            "failure_api": "Pexels API",
            "failure_provider": "pexels",
            "failure_service": "MoneyPrinterTurbo",
            "failure_config_fields": "pexels_api_keys",
            "created_at": "2026-08-26T10:00:00+00:00",
            "updated_at": "2026-08-26T10:03:00+00:00",
        },
        {
            "id": "video-legacy-failed",
            "state": "failed",
            "stage": "video",
            "style_wide": "pixabay",
            "title": "Vídeo antigo com falha",
            "updated_at": "2026-08-26T10:04:00+00:00",
        },
    ])
    record_notification("music_completed", "Música guardada", "Faixa pronta", dedupe_key="music:one")

    records = list_logs(limit=50)
    assert {"operation", "status", "date", "time"} <= set(records[0])
    assert {item["status"] for item in records} >= {"Pendente", "Em execução", "Falha", "Concluído"}
    running = next(item for item in records if item["task_id"] == "video-running")
    assert running["operation"] == "Vídeo concluído"
    assert running["progress"] == 72
    assert running["filename"] == "run-00bbe89c-6b6c-48a3-a6b1-70aaed70ceef.log"
    assert "Canal de teste" in running["details"]
    failed = next(item for item in records if item["task_id"] == "video-failed")
    assert "Timeout do Motor" in failed["details"]
    assert failed["api_provider"] == "Pexels API"
    assert "API/provider: Pexels API" in failed["details"]
    assert "Configuração: pexels_api_keys" in failed["details"]
    legacy_failed = next(item for item in records if item["task_id"] == "video-legacy-failed")
    assert legacy_failed["api_provider"] == "Pixabay API"
    assert "API/provider: Pixabay API" in legacy_failed["details"]

    rows = logs_to_rows(records)
    assert {"Operação", "Estado", "Data", "Hora", "Ficheiro", "API/Provider"} <= set(rows[0])
    assert all(row["Data"] != "—" and row["Hora"] != "—" for row in rows)


def test_log_filters_match_operation_status_and_free_text(tmp_path):
    storage = _isolated_storage(tmp_path / "filters")
    from hermes_ui.logs import list_logs

    storage.write_json("tasks.json", [
        {
            "id": "music-running",
            "state": "doing",
            "style_wide": "music",
            "title": "Faixa em execução",
            "channel_name": "Canal musical",
            "updated_at": "2026-08-26T10:00:00+00:00",
        },
        {
            "id": "video-done",
            "state": "done",
            "title": "Vídeo pronto",
            "channel_name": "Canal de vídeo",
            "updated_at": "2026-08-26T10:01:00+00:00",
        },
    ])

    assert [item["task_id"] for item in list_logs(operation="Música concluída")] == ["music-running"]
    assert [item["task_id"] for item in list_logs(status="Em execução")] == ["music-running"]
    assert [item["task_id"] for item in list_logs(query="Canal de vídeo")] == ["video-done"]
def test_log_filename_is_searchable_when_persisted(tmp_path):
    storage = _isolated_storage(tmp_path / "filename")
    from hermes_ui.logs import list_logs
    filename = "run-00bbe89c-6b6c-48a3-a6b1-70aaed70ceef.log"
    storage.write_json("tasks.json", [{"id": "video-run", "state": "failed", "video_log": filename, "updated_at": "2026-08-26T10:00:00+00:00"}])
    assert [item["task_id"] for item in list_logs(query=filename)] == ["video-run"]


def test_latest_result_resolves_to_the_real_run_filename(tmp_path):
    from hermes_ui.logs import _real_log_filename
    log_dir = tmp_path / "moneyprinterturbo-video"
    log_dir.mkdir()
    (log_dir / "latest-result.json").write_text("{}", encoding="utf-8")
    real_log = log_dir / "run-00bbe89c-6b6c-48a3-a6b1-70aaed70ceef.log"
    real_log.write_text("log", encoding="utf-8")
    assert _real_log_filename(str(log_dir / "latest-result.json")) == real_log.name
    assert _real_log_filename("run-00bbe89c-6b6c-48a3-a6b1-70aaed70ceef.log") == "run-00bbe89c-6b6c-48a3-a6b1-70aaed70ceef.log"


def test_logs_page_is_between_notifications_and_api_configuration():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "main.py").read_text(encoding="utf-8")
    settings_start = source.index("settings_items = [")
    settings_end = source.index("]", settings_start)
    settings_block = source[settings_start:settings_end]
    assert settings_block.index('("Notificações"') < settings_block.index('("Logs"') < settings_block.index('("Configuração API"')
    assert '"Logs": render_logs' in source
    for label in ("Filtrar operações", "Operação", "Estado", "Data", "Hora", "Registo", "Ficheiro", "Origem", "API/Provider", "Detalhes"):
        assert label in source
    assert "list_logs(operation=operation_filter, query=query, status=status_filter, limit=500)" in source
    assert "height=520" in source
    assert "with st.container(height=520, horizontal=True):" in source
    assert 'log_columns = ["Download", "Operação", "Estado", "Data", "Hora", "Registo", "Ficheiro", "Origem", "Progresso", "API/Provider", "Detalhes"]' in source
    assert 'for cell, column in zip(cells[1:], log_columns[1:])' in source
    assert 'path.name != "latest-result.json"' in source
    assert 'run-[0-9a-f]{8}-[0-9a-f]{4}' in source
    assert "barra de rolagem horizontal na parte inferior" in source
