"""1.0.93 — player HTML5 customizado + servidor de média local (fim do spinner).

O relato: na 1.0.91/92 o player ficava preso num spinner de carregamento
infinito com o vídeo em «done». CAUSA PROVADA no código do Streamlit 1.65
(`streamlit/runtime/memory_media_file_storage.py`): o único storage existente
é o `MemoryMediaFileStorage`, cujo ``load_and_get_id`` faz
``open(filename).read()`` — **lê o MP4 INTEIRO para a RAM** — e
``_calculate_file_id`` faz o hash do conteúdo, **a cada render**. Com vídeos
de dezenas de MB e vários cards na página, cada rerun bloqueia o servidor
nessa leitura/hash e o browser fica à espera do delta (spinner infinito).
A correcção serve o ficheiro DIRECTAMENTE do disco, com Range requests, por
um endpoint HTTP no próprio processo da app (SaaS local) e toca num <video>
HTML5 puro: zero RAM, zero hash, scrubbing funcional.

Estes testes correm o código REAL de `app/main.py` (extraído por `ast`, sem
Streamlit) e provam o servidor com pedidos HTTP de verdade.
"""

from __future__ import annotations

import ast
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _build_namespace(storage: Path):
    """Namespace com as peças do player/servidor, prontas a correr."""
    tree = ast.parse(MAIN_SOURCE)
    namespace: dict = {
        "__name__": "tb_media_test",
        "os": __import__("os"),
        "re": re,
        "threading": threading,
        "mimetypes": __import__("mimetypes"),
        "Path": Path,
        "Any": object,
        "uuid": __import__("uuid"),
        "quote": __import__("urllib.parse", fromlist=["quote"]).quote,
        "read_json": lambda name, fallback=None: fallback if fallback is not None else {},
        "BaseHTTPRequestHandler": __import__(
            "http.server", fromlist=["BaseHTTPRequestHandler"]
        ).BaseHTTPRequestHandler,
        "ThreadingHTTPServer": __import__(
            "http.server", fromlist=["ThreadingHTTPServer"]
        ).ThreadingHTTPServer,
        "socket": __import__("socket"),
        "STORAGE": storage,
        "st": SimpleNamespace(markdown=lambda html, **kw: namespace.setdefault("html", html)),
    }
    for node in tree.body:
        wanted = isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {
            "_tb_media_roots",
            "_TbMediaRequestHandler",
            "_tb_media_server",
            "_tb_media_local_url",
            "_custom_video_player",
        }
        assigned = isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
            isinstance(target, ast.Name) and "TB_MEDIA" in target.id
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
        if wanted or assigned:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<main.py>", "exec"), namespace)
    return namespace


@pytest.fixture()
def media(tmp_path: Path):
    """Servidor de média real + ficheiro de teste de 16 KB."""
    storage = tmp_path / "storage"
    videos = storage / "videos"
    videos.mkdir(parents=True)
    payload = bytes(range(256)) * 64
    video = videos / "final-1.mp4"
    video.write_bytes(payload)
    namespace = _build_namespace(storage)
    namespace["_payload"] = payload
    namespace["_video"] = video
    return namespace


# ---------------------------------------------------------------------------
# Servidor: GET/Range/HEAD do disco (nunca RAM)
# ---------------------------------------------------------------------------


def test_server_streams_the_file_from_disk_with_200(media):
    url = media["_tb_media_local_url"](media["_video"])
    assert url.startswith("http://127.0.0.1:") and url.endswith("/tb-media/videos/final-1.mp4")
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        assert response.read() == media["_payload"]
        assert response.headers.get("Accept-Ranges") == "bytes"
        assert response.headers.get("Content-Type") == "video/mp4"


def test_server_answers_range_requests_with_206(media):
    url = media["_tb_media_local_url"](media["_video"])
    request = urllib.request.Request(url, headers={"Range": "bytes=100-199"})
    with urllib.request.urlopen(request) as response:
        assert response.status == 206
        assert response.read() == media["_payload"][100:200]
        assert response.headers.get("Content-Range") == f"bytes 100-199/{len(media['_payload'])}"


def test_server_answers_suffix_ranges(media):
    url = media["_tb_media_local_url"](media["_video"])
    request = urllib.request.Request(url, headers={"Range": "bytes=-16"})
    with urllib.request.urlopen(request) as response:
        assert response.status == 206
        assert response.read() == media["_payload"][-16:]


def test_server_answers_head_without_body(media):
    url = media["_tb_media_local_url"](media["_video"])
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request) as response:
        assert response.status == 200
        assert response.read() == b""


def test_server_blocks_path_traversal(media):
    server = media["_tb_media_server"]()
    port = server.server_address[1]
    for hostile in (
        f"http://127.0.0.1:{port}/tb-media/videos/../../etc/passwd",
        f"http://127.0.0.1:{port}/tb-media/videos/..%2f..%2fetc/passwd",
        f"http://127.0.0.1:{port}/tb-media/desconhecido/final-1.mp4",
        f"http://127.0.0.1:{port}/outra-coisa",
    ):
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(hostile)
        assert raised.value.code == 404


def test_server_is_a_singleton_and_streams_in_chunks(media):
    first = media["_tb_media_server"]()
    second = media["_tb_media_server"]()
    assert first is second  # um servidor só, vários renders
    assert media["TB_MEDIA_STREAM_CHUNK"] == 256 * 1024  # blocos, nunca o ficheiro inteiro


def test_files_outside_the_served_roots_have_no_url(media, tmp_path: Path):
    outside = tmp_path / "fora.mp4"
    outside.write_bytes(b"x")
    assert media["_tb_media_local_url"](outside) is None


# ---------------------------------------------------------------------------
# Player HTML5: <video> local + dica de download em 3 s
# ---------------------------------------------------------------------------


def test_custom_player_renders_video_tag_with_the_local_url(media):
    media["_custom_video_player"](media["_video"])
    html = media["html"]
    url = media["_tb_media_local_url"](media["_video"])
    assert "<video" in html and url in html
    assert "controls" in html and 'preload="metadata"' in html
    assert "st.video" not in html  # o gestor nativo (leitura em RAM) ficou de fora


def test_custom_player_swaps_to_the_download_hint_after_three_seconds(media):
    media["_custom_video_player"](media["_video"])
    html = media["html"]
    assert "O player demorou a carregar. Clique em 'Baixar Vídeo' para assistir localmente." in html
    assert "3000" in html and "readyState===0" in html
    assert "display:none" in html  # a dica começa escondida e aparece só na falha


def test_custom_player_raises_when_the_file_is_outside_the_roots(media, tmp_path: Path):
    outside = tmp_path / "fora.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        media["_custom_video_player"](outside)


# ---------------------------------------------------------------------------
# Contratos do `_render_local_video_player` (a hierarquia de reprodução)
# ---------------------------------------------------------------------------


def test_player_hierarchy_contract():
    player = MAIN_SOURCE.split("def _render_local_video_player", 1)[1].split("def _load_local_env", 1)[0]
    # 1.0.91: em modo destacado não há URL do launcher…
    assert 'os.environ.get("THUNDERBOLT_LAUNCHER_MODE") == "detached"' in MAIN_SOURCE.split(
        "def _tb_media_video_url", 1
    )[1].split("def _tb_media_server", 1)[0]
    # 1.0.93: …e o caminho resolvido toca pelo servidor local (zero RAM),
    # com o media_file_mgr como última rede.
    assert "_custom_video_player(path, width=width)" in player
    assert "except Exception:" in player  # fallback preservado
    assert "st.video(str(resolved), **video_kwargs)" in player


def test_custom_player_contracts_the_real_streamlit_behaviour():
    """O código do Streamlit que provocava o spinner fica documentado no teste."""
    sp = Path(__file__).resolve().parents[1] / ".venv" / "Lib" / "site-packages" / "streamlit"
    if not sp.is_dir():
        pytest.skip("streamlit não instalado neste ambiente")
    storage_source = (sp / "runtime" / "memory_media_file_storage.py").read_text(encoding="utf-8")
    # só existe storage em MEMÓRIA: `st.video(caminho)` lê o MP4 inteiro + hash
    assert "def load_and_get_id" in storage_source
    assert "with open(filename, \"rb\") as f:" in storage_source
    assert "return f.read()" in storage_source
    assert not (sp / "runtime" / "file_media_file_storage.py").exists()
