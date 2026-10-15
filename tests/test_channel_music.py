"""Tests do uploader partilhado de música de fundo com rodízio (0.9.99).

Cobrem as três camadas da funcionalidade:
- persistência pura (hermes_ui.channel_music): gravação na pasta do canal,
  dedupe por checksum, sanitização, remoção física+manifest, rodízio circular;
- componente de UI (render_music_upload_section) com streamlit gravado;
- pipeline (_with_uploaded_background_music + _moneyprinter_cli_args): o
  rodízio avança e persiste o índice ANTES do render e a faixa é copiada para
  storage/bgm do MoneyPrinterTurbo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_ui import channel_music, pipeline_worker

APP_MAIN = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")


def _isolate_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Root de storage isolado por teste (mesmo padrão do test_domain.py)."""
    from hermes_ui import storage

    root = tmp_path / "storage"
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(root))
    storage.STORAGE = root
    storage.STATE = root / "state"
    storage.BLUEPRINTS = root / "blueprints"
    storage.ensure_storage()
    return root


class _FakeUpload:
    def __init__(self, name: str, content: bytes):
        self.name = name
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


class _FakeColumn:
    def __init__(self, recorder: "_RecordingStreamlit"):
        self._recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def button(self, label: str, **kwargs):
        return self._recorder.button(label, **kwargs)

    def caption(self, text: str):
        return self._recorder.caption(text)


class _RecordingStreamlit:
    """Streamlit mínimo que grava as chamadas de widget do componente."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.session_state: dict[str, object] = {}
        self.uploads: list[_FakeUpload] = []
        self.button_results: dict[str, bool] = {}
        self.checkbox_value = False
        self.rerun_count = 0

    def file_uploader(self, label: str, **kwargs):
        self.calls.append(("file_uploader", label, kwargs))
        return list(self.uploads)

    def markdown(self, text: str, **kwargs):
        self.calls.append(("markdown", text))

    def caption(self, text: str, **kwargs):
        self.calls.append(("caption", text))

    def columns(self, spec, **kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [_FakeColumn(self) for _ in range(count)]

    def button(self, label: str, **kwargs):
        self.calls.append(("button", label, kwargs))
        return bool(self.button_results.get(label, False))

    def checkbox(self, label: str, **kwargs):
        self.calls.append(("checkbox", label, kwargs))
        return bool(self.checkbox_value)

    def warning(self, text: str, **kwargs):
        self.calls.append(("warning", text))

    def success(self, text: str, **kwargs):
        self.calls.append(("success", text))

    def error(self, text: str, **kwargs):
        self.calls.append(("error", text))

    def rerun(self):
        self.rerun_count += 1

    def uploader_calls(self) -> list[tuple]:
        return [call for call in self.calls if call[0] == "file_uploader"]

    def checkbox_calls(self) -> list[tuple]:
        return [call for call in self.calls if call[0] == "checkbox"]


def _save_track(scope: str, name: str, content: bytes) -> dict:
    return channel_music.save_channel_music(scope, name, content)


# ── Componente de UI ──────────────────────────────────────────────────────────


def test_music_uploader_appears_when_source_is_carregar_ficheiro(tmp_path, monkeypatch):
    root = _isolate_storage(tmp_path, monkeypatch)
    fake = _RecordingStreamlit()
    monkeypatch.setattr(channel_music, "st", fake)

    state = channel_music.render_music_upload_section("channel_channel-abc123")

    assert state["source"] == "Carregar ficheiro"
    assert len(fake.uploader_calls()) == 1
    _, label, kwargs = fake.uploader_calls()[0]
    assert label == "Carregar música de fundo"
    assert kwargs["accept_multiple_files"] is True
    assert kwargs["key"] == "music_upload_channel_channel-abc123"
    assert sorted(kwargs["type"]) == ["flac", "m4a", "mp3", "ogg", "wav"]
    # A UI condicionada existe nos dois locais (Local A e Local B) do app.
    assert 'if selected_music_source == "Carregar ficheiro":' in APP_MAIN
    assert 'if settings["background_music_source"] == "Carregar ficheiro":' in APP_MAIN
    assert root.joinpath("blueprints", "canais").is_dir()


def test_music_list_shows_all_attached_musics(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    scope = "channel_channel-list"
    _save_track(scope, "trilha1.mp3", b"a" * 4200000)
    _save_track(scope, "trilha2.mp3", b"b" * 5100000)
    _save_track(scope, "trilha3.mp3", b"c" * 3800000)

    fake = _RecordingStreamlit()
    monkeypatch.setattr(channel_music, "st", fake)
    state = channel_music.render_music_upload_section(scope)

    captions = [call[1] for call in fake.calls if call[0] == "caption"]
    markdowns = [call[1] for call in fake.calls if call[0] == "markdown"]
    assert any("Músicas anexadas (3)" in text for text in markdowns)
    assert any(text.startswith("1. **trilha1.mp3**") for text in captions)
    assert any(text.startswith("2. **trilha2.mp3**") for text in captions)
    assert any(text.startswith("3. **trilha3.mp3**") for text in captions)
    assert any("4.0 MB" in text for text in captions)
    assert len(state["musics"]) == 3


def test_music_list_empty_shows_no_music_attached(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    fake = _RecordingStreamlit()
    monkeypatch.setattr(channel_music, "st", fake)
    channel_music.render_music_upload_section("channel_channel-empty")
    captions = [call[1] for call in fake.calls if call[0] == "caption"]
    assert any("Nenhuma música anexada." in text for text in captions)


def test_rotation_checkbox_only_visible_with_2_or_more_musics(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    scope = "channel_channel-rotation-ui"
    _save_track(scope, "unica.mp3", b"audio-1")

    fake = _RecordingStreamlit()
    monkeypatch.setattr(channel_music, "st", fake)
    channel_music.render_music_upload_section(scope)
    assert fake.checkbox_calls() == []

    _save_track(scope, "segunda.mp3", b"audio-2")
    fake = _RecordingStreamlit()
    monkeypatch.setattr(channel_music, "st", fake)
    channel_music.render_music_upload_section(scope)
    checkbox_calls = fake.checkbox_calls()
    assert len(checkbox_calls) == 1
    _, label, kwargs = checkbox_calls[0]
    assert label == "Fazer rodízio entre as músicas a cada vídeo gerado"
    assert kwargs["key"] == f"rotation_{scope}"


# ── Persistência ──────────────────────────────────────────────────────────────


def test_music_upload_persists_file_to_channel_folder(tmp_path, monkeypatch):
    root = _isolate_storage(tmp_path, monkeypatch)
    scope = channel_music.music_scope_for_channel("channel-abc123")
    assert scope == "channel_channel-abc123"

    entry = _save_track(scope, "trilha1.mp3", b"conteudo-audio-1")

    music_dir = root / "blueprints" / "canais" / "channel-abc123" / "music"
    assert (music_dir / "trilha1.mp3").read_bytes() == b"conteudo-audio-1"
    assert entry["filename"] == "trilha1.mp3"
    assert entry["size"] == len(b"conteudo-audio-1")
    assert entry["checksum"]
    assert entry["uploaded_at"]
    manifest = channel_music.read_music_manifest(scope)
    assert [item["filename"] for item in manifest["musics"]] == ["trilha1.mp3"]
    assert manifest["rotation_enabled"] is False
    assert manifest["last_used_index"] == 0


def test_music_upload_persists_to_video_creation_scope_without_channel(tmp_path, monkeypatch):
    root = _isolate_storage(tmp_path, monkeypatch)
    assert channel_music.music_scope_for_channel("") == channel_music.VIDEO_CREATION_SCOPE
    entry = _save_track(channel_music.VIDEO_CREATION_SCOPE, "global.mp3", b"audio-global")
    assert (root / "blueprints" / "video_creation" / "music" / "global.mp3").is_file()
    assert entry["path"].endswith("global.mp3")


def test_music_upload_handles_duplicates_by_checksum(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    scope = "channel_channel-dup"
    first = _save_track(scope, "trilha1.mp3", b"mesmo-conteudo")
    second = _save_track(scope, "renomeada.mp3", b"mesmo-conteudo")

    assert second["id"] == first["id"]
    assert second["filename"] == "trilha1.mp3"
    manifest = channel_music.read_music_manifest(scope)
    assert len(manifest["musics"]) == 1
    files = list(channel_music.music_directory(scope).glob("*.mp3"))
    assert len(files) == 1

    # Conteúdo diferente com o mesmo nome não sobrescreve: trilha1_2.mp3.
    third = _save_track(scope, "trilha1.mp3", b"outro-conteudo")
    assert third["filename"] == "trilha1_2.mp3"
    assert len(channel_music.read_music_manifest(scope)["musics"]) == 2


def test_music_upload_sanitizes_filename(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    scope = "channel_channel-sanitize"

    traversal = _save_track(scope, "..\\..\\tent<ativa>.mp3", b"x")
    assert traversal["filename"] == "tent_ativa.mp3"
    saved_path = Path(traversal["path"])
    assert saved_path.parent == channel_music.music_directory(scope)

    reserved = _save_track(scope, "con.mp3", b"y")
    assert reserved["filename"].startswith("musica_")
    assert Path(reserved["path"]).parent == channel_music.music_directory(scope)

    no_extension = _save_track(scope, "gravação sem extensão", b"z")
    assert no_extension["filename"].endswith(".mp3")

    with pytest.raises(ValueError):
        _save_track(scope, "vazio.mp3", b"")
    with pytest.raises(ValueError):
        _save_track(scope, "grande.mp3", b"0" * (channel_music.MAX_UPLOAD_BYTES + 1))


def test_music_remove_deletes_file_and_manifest_entry(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    scope = "channel_channel-remove"
    first = _save_track(scope, "trilha1.mp3", b"audio-1")
    second = _save_track(scope, "trilha2.mp3", b"audio-2")

    assert channel_music.remove_channel_music(scope, first["id"]) is True

    assert not Path(first["path"]).is_file()
    assert Path(second["path"]).is_file()
    manifest = channel_music.read_music_manifest(scope)
    assert [item["filename"] for item in manifest["musics"]] == ["trilha2.mp3"]
    assert channel_music.remove_channel_music(scope, "id-inexistente") is False


def test_music_remove_requires_confirmation_in_ui(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    scope = "channel_channel-confirm"
    entry = _save_track(scope, "trilha1.mp3", b"audio-1")

    fake = _RecordingStreamlit()
    fake.button_results["🗑️ Remover"] = True
    monkeypatch.setattr(channel_music, "st", fake)
    channel_music.render_music_upload_section(scope)

    assert fake.session_state[f"music_remove_confirm_{scope}_{entry['id']}"] is True
    warnings = [call[1] for call in fake.calls if call[0] == "warning"]
    assert any("trilha1.mp3" in text for text in warnings)
    # O primeiro clique só pede confirmação — o ficheiro continua em disco.
    assert Path(entry["path"]).is_file()


# ── Rodízio ───────────────────────────────────────────────────────────────────


def _manifest_with_three_tracks(tmp_path, monkeypatch) -> str:
    _isolate_storage(tmp_path, monkeypatch)
    scope = "channel_channel-rotation"
    for index in range(1, 4):
        channel_music.save_channel_music(scope, f"trilha{index}.mp3", f"audio-{index}".encode())
    channel_music.set_rotation_enabled(scope, True)
    return scope


def test_rotation_selects_next_music_in_circular_order(tmp_path, monkeypatch):
    scope = _manifest_with_three_tracks(tmp_path, monkeypatch)

    first = channel_music.select_music_for_render(scope)
    second = channel_music.select_music_for_render(scope)
    third = channel_music.select_music_for_render(scope)
    fourth = channel_music.select_music_for_render(scope)

    assert [first["filename"], second["filename"], third["filename"]] == ["trilha2.mp3", "trilha3.mp3", "trilha1.mp3"]
    assert fourth["filename"] == "trilha2.mp3"


def test_rotation_persists_last_used_index_before_render(tmp_path, monkeypatch):
    scope = _manifest_with_three_tracks(tmp_path, monkeypatch)

    selected = channel_music.select_music_for_render(scope)

    # O índice já está persistido no momento em que a selecção é devolvida ao
    # pipeline — antes de qualquer renderização do MPT começar.
    manifest = channel_music.read_music_manifest(scope)
    assert manifest["last_used_index"] == 1
    assert selected["filename"] == manifest["musics"][1]["filename"]

    channel_music.select_music_for_render(scope)
    assert channel_music.read_music_manifest(scope)["last_used_index"] == 2
    channel_music.select_music_for_render(scope)
    assert channel_music.read_music_manifest(scope)["last_used_index"] == 0


def test_rotation_disabled_uses_first_music(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    scope = "channel_channel-no-rotation"
    for index in range(1, 4):
        channel_music.save_channel_music(scope, f"trilha{index}.mp3", f"audio-{index}".encode())

    for _ in range(3):
        assert channel_music.select_music_for_render(scope)["filename"] == "trilha1.mp3"
    assert channel_music.read_music_manifest(scope)["last_used_index"] == 0


# ── Pipeline ──────────────────────────────────────────────────────────────────


def _fake_moneyprinter_root(tmp_path: Path) -> Path:
    root = tmp_path / "moneyprinter"
    root.mkdir(parents=True, exist_ok=True)
    (root / "cli.py").write_text("# fake cli", encoding="utf-8")
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    return root


def _uploaded_bgm_task(scope: str) -> dict:
    return {
        "id": "video-1",
        "channel_id": scope.removeprefix("channel_"),
        "generation_settings": {
            "background_music_source": "Carregar ficheiro",
            "background_music_volume": "20%",
            "background_music_scope": scope,
        },
    }


def test_pipeline_stages_rotation_music_into_moneyprinter_bgm_folder(tmp_path, monkeypatch):
    root = _isolate_storage(tmp_path, monkeypatch)
    scope = _manifest_with_three_tracks(tmp_path, monkeypatch)
    mpt_root = _fake_moneyprinter_root(tmp_path)
    task = _uploaded_bgm_task(scope)

    resolved = pipeline_worker._with_uploaded_background_music(task, {"moneyprinter_path": str(mpt_root)})

    staged = str(resolved["generation_settings"].get("background_music_file") or "")
    assert staged.startswith("thunderbolt-") and staged.endswith(".mp3")
    staged_path = mpt_root / "storage" / "bgm" / staged
    assert staged_path.is_file()
    # O rodízio avançou e persistiu antes do render.
    assert channel_music.read_music_manifest(scope)["last_used_index"] == 1
    assert Path(resolved["generation_settings"]["background_music_file"]).name == staged_path.name
    # A tarefa original não foi mutada.
    assert "background_music_file" not in task["generation_settings"]


def test_pipeline_without_uploads_keeps_legacy_bgm_args(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    task = _uploaded_bgm_task("channel_channel-sem-musicas")
    resolved = pipeline_worker._with_uploaded_background_music(task, {"moneyprinter_path": ""})
    assert resolved is task
    args = pipeline_worker._moneyprinter_cli_args(task, "pexels")
    assert "--bgm-type" not in args
    assert "--bgm-file" not in args


def test_moneyprinter_cli_args_send_custom_bgm_file_only_with_staged_track(tmp_path, monkeypatch):
    task_staged = {
        "generation_settings": {
            "background_music_source": "Carregar ficheiro",
            "background_music_volume": "20%",
            "background_music_file": "thunderbolt-abc.mp3",
        },
    }
    args = pipeline_worker._moneyprinter_cli_args(task_staged, "pexels")
    assert args[args.index("--bgm-type") + 1] == "custom"
    assert args[args.index("--bgm-file") + 1] == "thunderbolt-abc.mp3"
    assert args[args.index("--bgm-volume") + 1] == "0.2"

    # Fontes legadas mantêm o contrato anterior, byte a byte.
    legacy_none = pipeline_worker._moneyprinter_cli_args({"generation_settings": {"background_music_source": "Sem música"}}, "pexels")
    assert legacy_none[legacy_none.index("--bgm-type") + 1] == "none"
    legacy_random = pipeline_worker._moneyprinter_cli_args({"generation_settings": {"background_music_source": "Random Background Music"}}, "pexels")
    assert legacy_random[legacy_random.index("--bgm-type") + 1] == "random"
    legacy_existing = pipeline_worker._moneyprinter_cli_args({"generation_settings": {"background_music_source": "Ficheiro existente"}}, "pexels")
    assert legacy_existing[legacy_existing.index("--bgm-type") + 1] == "custom"
    assert "--bgm-file" not in legacy_existing


def test_same_component_used_in_channel_card_and_video_creation():
    # Local A — card do canal (Configurações de Audio).
    channel_card = APP_MAIN[APP_MAIN.index("def render_channel_audio_subtitle_defaults("):]
    assert 'with st.expander("Configurações de Audio", expanded=False):' in channel_card
    assert "render_music_upload_section(music_scope_for_channel(channel_id))" in channel_card
    # Local B — criação de vídeo (Configurações de áudio).
    video_creation = APP_MAIN[APP_MAIN.index("def render_video_generation_settings("):APP_MAIN.index("def channel_default_options(")]
    assert 'with st.expander("Configurações de áudio", expanded=False):' in video_creation
    assert 'if settings["background_music_source"] == "Carregar ficheiro":' in video_creation
    assert "music_scope = music_scope_for_channel(" in video_creation
    assert "render_music_upload_section(music_scope)" in video_creation
    # O componente é importado uma única vez e partilhado por ambos.
    assert "from hermes_ui.channel_music import" in APP_MAIN
    assert APP_MAIN.count("render_music_upload_section(") == 2  # exactamente as 2 chamadas partilhadas
