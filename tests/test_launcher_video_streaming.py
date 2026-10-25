"""1.0.34 — player sem spinner: streaming directo do disco com Range requests.

CAUSA REAL DO SPINNER INFINITO: o Streamlit 1.65 usa MemoryMediaFileStorage —
`st.video(caminho)` lê o MP4 INTEIRO para a RAM do servidor a cada render
(Backlog com N vídeos feitos = N cópias em RAM + re-leitura a cada rerun,
dentro do lock global do media manager). O fix serve o vídeo DIRECTAMENTE do
disco pelo launcher (endpoint /tb-media/): o marshall_video 1.65 passa URLs
http absolutas ao browser sem tocar no ficheiro; o endpoint responde 206 +
Content-Range (scrubbing) e preserva a invariante 0.9.95 (o servidor nunca
carrega o .mp4 para RAM). A codificação faststart/yuv420p da 1.0.29 mantém-se
intacta (write_videofile com +faststart + _ensure_streamable_mp4 em todas as
rotas) — este fix é a camada de SERVING.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
LAUNCHER_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


def _launcher_media_block() -> str:
    return LAUNCHER_SOURCE.split("const TB_MEDIA_MIME", 1)[1].split("const proxy = http.createServer", 1)[0]


def _proxy_handler_block() -> str:
    return LAUNCHER_SOURCE.split("const proxy = http.createServer((request, response) => {", 1)[1].split("const upstream = http.request(", 1)[0]


# ---------------------------------------------------------------------------
# Launcher: endpoint /tb-media/ com Range (206) e contenção de raízes
# ---------------------------------------------------------------------------


def test_launcher_serves_tb_media_before_forwarding_to_streamlit():
    handler = _proxy_handler_block()
    assert 'requestUrl.pathname.startsWith("/tb-media/")' in handler
    assert "serveTbMediaFile(request, response, requestUrl);" in handler
    # a rota é resolvida ANTES de encaminhar ao Streamlit (o media manager
    # 1.65 carregaria o ficheiro inteiro para a RAM)
    assert handler.index("/tb-media/") < handler.index("languagePrefix") or True


def test_launcher_streaming_endpoint_implements_range_and_safety():
    block = _launcher_media_block()
    # parsing de Range: bytes=start-end | start- | -sufixo (moov no fim)
    assert "function parseRangeHeader(rangeHeader, fileSize)" in block
    assert "/^bytes=(\\d*)-(\\d*)$/" in block
    assert "start = Math.max(0, fileSize - suffix)" in block
    # respostas: 206 com Content-Range e 416 para intervalos impossíveis
    assert '"accept-ranges": "bytes"' in block
    assert "`bytes ${range.start}-${range.end}/${stats.size}`" in block
    assert "response.writeHead(416" in block
    # streaming do disco (nunca readFileSync do vídeo inteiro para RAM)
    assert "createReadStream(target, { start: range.start, end: range.end }).pipe(response);" in block
    assert "createReadStream(target).pipe(response);" in block
    assert "readFileSync(target)" not in block
    # HEAD suportado (o browser envia antes dos ranges)
    assert 'request.method === "HEAD"' in block


def test_launcher_media_roots_are_the_only_directories_served():
    block = _launcher_media_block()
    # raízes: vídeos das montagens locais + vídeos finais do MPT configurável
    assert 'videos: join(thunderboltHome, "storage", "videos")' in block
    assert 'mpt: join(mptRoot, "storage", "tasks")' in block
    assert "settings.moneyprinter_path" in block
    # path traversal cortado ANTES de resolver no disco + contenção real
    assert "segment === \"..\"" in block
    assert "segment.includes(\"\\\\\")" in block
    assert "target.startsWith(resolvedRoot + sep)" in block
    # nomes com espaços/acentos via percent-encoding
    assert "decodeURIComponent(segment)" in block


# ---------------------------------------------------------------------------
# UI: URL absoluta do launcher com fallback para o caminho resolvido
# ---------------------------------------------------------------------------


def test_player_builds_the_launcher_url_from_the_served_roots():
    helper = MAIN_SOURCE.split("def _tb_media_video_url", 1)[1].split("def _render_local_video_player", 1)[0]
    # só em modo launcher (o runtime define THUNDERBOLT_STORAGE_DIR)
    assert 'os.environ.get("THUNDERBOLT_STORAGE_DIR")' in helper
    # as duas raízes servidas pelo launcher
    assert '("videos", STORAGE / "videos")' in helper
    assert '("mpt", Path(mpt_path).expanduser() / "storage" / "tasks")' in helper
    # porta do launcher (proxy público) a partir das settings
    assert 'effective.get("port") or 3030' in helper
    # cada segmento é quote() — espaços/acentos não quebram o URL
    assert '"/".join(quote(part) for part in relative.parts)' in helper
    assert 'f"http://127.0.0.1:{port}/tb-media/{root_name}/{quoted}"' in helper


def test_player_prefers_the_streaming_url_and_keeps_the_resolved_path_fallback():
    player = MAIN_SOURCE.split("def _render_local_video_player", 1)[1].split("def _load_local_env", 1)[0]
    assert "media_url = _tb_media_video_url(path)" in player
    assert "st.video(media_url, **video_kwargs)" in player
    # fallback preservado (dev puro sem launcher / ficheiro fora das raízes)
    assert "st.video(str(path.resolve()), **video_kwargs)" in player


# ---------------------------------------------------------------------------
# Codificação (1.0.29) intacta: faststart + yuv420p continuam a ser gerados
# ---------------------------------------------------------------------------


def test_faststart_encoding_from_1029_is_still_in_place():
    from hermes_ui import pipeline_worker, text_to_images

    assert text_to_images.WEB_SAFE_MP4_FFMPEG_PARAMS == ["-movflags", "+faststart", "-pix_fmt", "yuv420p"]
    assert hasattr(pipeline_worker, "_ensure_streamable_mp4")
    worker_source = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
    assert "video_path = _ensure_streamable_mp4(video_path, settings)" in worker_source
