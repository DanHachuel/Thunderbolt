"""1.0.91 — player de vídeo no modo DESTACADO (fim da tela preta pós-1.0.89).

O relato: depois da arquitectura destacada (1.0.89) os players da aba
Automação YouTube voltaram a ficar PRETOS com o vídeo em «done». Estes
testes correm o código REAL de `app/main.py` (extraído por `ast` e executado
num namespace isolado, sem Streamlit) e provam:

- `_tb_media_video_url` NÃO devolve a URL do launcher em modo destacado (o
  proxy morreu com o launcher; a URL era um 404 do Streamlit);
- em modo launcher/foreground a URL continua a ser construída (contrato 1.0.34);
- o player toca pelo **caminho absoluto resolvido** quando não há URL, e uma
  falha de carregamento vira **aviso vermelho** em vez de silêncio;
- `_task_artifact_path` resolve caminhos contra as raízes reais do
  `THUNDERBOLT_HOME` (o `.runtime` não tem storage copiado).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _extract_function(name: str) -> str:
    tree = ast.parse(MAIN_SOURCE)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"função {name} não encontrada em app/main.py")


class _FakeSt:
    """Streamlit mínimo: grava as chamadas de video/error/warning."""

    def __init__(self, *, video_raises: bool = False):
        self.calls: list[tuple] = []
        self._video_raises = video_raises

    def video(self, data, **kwargs):
        self.calls.append(("video", data, kwargs))
        if self._video_raises:
            raise OSError("[WinError 32] bloqueado pelo Windows")

    def error(self, message):
        self.calls.append(("error", message))

    def warning(self, message):
        self.calls.append(("warning", message))


def _namespace(env: dict[str, str], storage: Path, *, video_url: str | None = None, video_raises: bool = False):
    st = _FakeSt(video_raises=video_raises)
    namespace: dict = {
        "os": SimpleNamespace(environ=dict(env)),
        "Path": Path,
        "Any": object,
        "STORAGE": storage,
        "st": st,
        "mimetypes": SimpleNamespace(guess_type=lambda name: "video/mp4"),
        "inspect": SimpleNamespace(signature=lambda func: SimpleNamespace(parameters={})),
        "quote": __import__("urllib.parse", fromlist=["quote"]).quote,
        "read_json": lambda name, fallback=None: fallback or {},
        "_tb_media_video_url": (lambda path, settings=None: video_url),
    }
    exec(compile(_extract_function("_render_local_video_player"), "<main.py:player>", "exec"), namespace)
    return namespace["_render_local_video_player"], st


# ---------------------------------------------------------------------------
# _tb_media_video_url: sem URL em modo destacado, com URL em modo launcher
# ---------------------------------------------------------------------------


def _url_namespace(env: dict[str, str], storage: Path, video: Path):
    from urllib.parse import quote as _quote

    namespace: dict = {
        "os": SimpleNamespace(environ=dict(env)),
        "Path": Path,
        "Any": object,
        "STORAGE": storage,
        "quote": _quote,
        "read_json": lambda name, fallback=None: {"port": 3030, "moneyprinter_path": ""},
    }
    exec(compile(_extract_function("_tb_media_video_url"), "<main.py:url>", "exec"), namespace)
    return namespace["_tb_media_video_url"]


def test_media_url_is_none_in_detached_mode(tmp_path: Path):
    """A regressão: no modo destacado a URL do launcher era um 404."""
    storage = tmp_path / "storage"
    (storage / "videos").mkdir(parents=True)
    video = storage / "videos" / "video_x.mp4"
    video.write_bytes(b"mp4")
    builder = _url_namespace(
        {"THUNDERBOLT_STORAGE_DIR": str(storage), "THUNDERBOLT_LAUNCHER_MODE": "detached"}, storage, video
    )
    assert builder(video) is None


def test_media_url_is_built_in_launcher_mode(tmp_path: Path):
    """Em modo launcher (foreground) a URL de streaming continua a sair."""
    storage = tmp_path / "storage"
    (storage / "videos").mkdir(parents=True)
    video = storage / "videos" / "video_x.mp4"
    video.write_bytes(b"mp4")
    builder = _url_namespace(
        {"THUNDERBOLT_STORAGE_DIR": str(storage)}, storage, video
    )
    url = builder(video)
    assert url == "http://127.0.0.1:3030/tb-media/videos/video_x.mp4"


def test_media_url_is_none_without_storage_dir(tmp_path: Path):
    """Sem launcher (dev puro) continua a cair para o caminho resolvido."""
    storage = tmp_path / "storage"
    (storage / "videos").mkdir(parents=True)
    video = storage / "videos" / "video_x.mp4"
    video.write_bytes(b"mp4")
    builder = _url_namespace({}, storage, video)
    assert builder(video) is None


# ---------------------------------------------------------------------------
# Player: caminho absoluto resolvido + aviso vermelho em falha
# ---------------------------------------------------------------------------


def _video_call(st: _FakeSt) -> str:
    for kind, data, *_rest in st.calls:
        if kind == "video":
            return str(data)
    raise AssertionError("st.video não foi chamado")
    storage = tmp_path / "storage" / "videos"
    storage.mkdir(parents=True)
    video = storage / "final-1.mp4"
    video.write_bytes(b"mp4")
    player, st = _namespace(
        {"THUNDERBOLT_STORAGE_DIR": str(storage.parent)}, storage.parent, video_url=None
    )
    player(video)
    kinds = [call[0] for call in st.calls]
    assert "video" in kinds
    assert "error" not in kinds
    data = _video_call(st)
    # o caminho entregue ao st.video é ABSOLUTO e resolvido (nunca relativo
    # ao .runtime)
    assert Path(data).is_absolute()
    assert Path(data) == video.resolve()


def test_player_warns_in_red_when_the_file_is_missing(tmp_path: Path):
    video = tmp_path / "nao-existe.mp4"
    player, st = _namespace({}, tmp_path, video_url=None)
    player(video)
    assert [call[0] for call in st.calls] == ["warning"]
    assert "não encontrado" in st.calls[0][1].lower()


def test_player_shows_red_error_instead_of_staying_mute(tmp_path: Path):
    """Falha de carregamento = aviso vermelho, nunca silêncio (tela preta)."""
    video = tmp_path / "bloqueado.mp4"
    video.write_bytes(b"mp4")
    player, st = _namespace(
        {"THUNDERBOLT_STORAGE_DIR": str(tmp_path / "storage")}, tmp_path, video_url=None, video_raises=True
    )
    player(video)
    errors = [call[1] for call in st.calls if call[0] == "error"]
    assert errors, "a falha tem de virar aviso vermelho"
    assert "Não foi possível carregar o player" in errors[0]
    assert "bloqueado" in errors[0]


def test_player_prefers_the_launcher_url_when_available(tmp_path: Path):
    video = tmp_path / "final-1.mp4"
    video.write_bytes(b"mp4")
    player, st = _namespace({}, tmp_path, video_url="http://127.0.0.1:3030/tb-media/videos/final-1.mp4")
    player(video)
    data = _video_call(st)
    assert data.startswith("http://127.0.0.1:3030/tb-media/")


# ---------------------------------------------------------------------------
# _task_artifact_path: raízes reais do THUNDERBOLT_HOME (o .runtime não tem
# storage copiado)
# ---------------------------------------------------------------------------


def test_artifact_path_falls_back_to_the_thunderbolt_home_roots(tmp_path: Path):
    home = tmp_path / "home"
    (home / "storage" / "videos").mkdir(parents=True)
    video = home / "storage" / "videos" / "video_relativo.mp4"
    video.write_bytes(b"mp4")
    namespace: dict = {
        "os": SimpleNamespace(environ={"THUNDERBOLT_HOME": str(home)}),
        "Path": Path,
        "Any": object,
        "STORAGE": tmp_path / "runtime" / "storage",  # o storage "errado" do runtime
    }
    exec(compile(_extract_function("_task_artifact_path"), "<main.py:artifact>", "exec"), namespace)
    resolved = namespace["_task_artifact_path"]({"artifacts": {"video": "videos/video_relativo.mp4"}}, "video")
    assert resolved == video


def test_artifact_path_still_prefers_the_absolute_stored_path(tmp_path: Path):
    video = tmp_path / "final-absoluto.mp4"
    video.write_bytes(b"mp4")
    namespace: dict = {
        "os": SimpleNamespace(environ={"THUNDERBOLT_HOME": str(tmp_path / "home")}),
        "Path": Path,
        "Any": object,
        "STORAGE": tmp_path / "storage",
    }
    exec(compile(_extract_function("_task_artifact_path"), "<main.py:artifact>", "exec"), namespace)
    resolved = namespace["_task_artifact_path"]({"artifacts": {"video": str(video)}}, "video")
    assert resolved == video
    assert namespace["_task_artifact_path"]({"artifacts": {}}, "video") is None
