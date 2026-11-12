"""1.0.96 — Etapa 3 da auditoria global (médios e baixos).

Cobre as seis correcções pedidas depois da Etapa 2:

1. **M5** — `st.rerun()` sem escopo dentro de fragments (recarregava a página
   inteira a cada clique num cartão);
2. **M3** — a aba TikTok lia o catálogo de tarefas (e os canais) DUAS vezes no
   mesmo ciclo de render, uma por sub-aba;
3. **M4** — thumbnails servidas em resolução de produção para cartões de 300 px;
4. **`st.video(caminho)` directo** nos 6 pontos das abas Cortes/Editor Python
   (o MP4 inteiro para a RAM a cada render);
5. **`read_bytes()` nos downloads** — os ficheiros grandes passam a ser servidos
   pelo mini-servidor HTTP local, sem tocar no processo do Streamlit;
6. **M8** — lixo de testes (`storage/_temp_test`) e ficheiros de debug na raiz.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CLI = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")

TREE = ast.parse(MAIN)
FUNCS = {node.name: node for node in TREE.body if isinstance(node, ast.FunctionDef)}


# ---------------------------------------------------------------------------
# 1. M5 - rerun com scope dentro de fragments
# ---------------------------------------------------------------------------


def _chamadores() -> dict[str, set[str]]:
    calls: dict[str, set[str]] = {}
    for name, node in FUNCS.items():
        found: set[str] = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    found.add(f.id)
                elif isinstance(f, ast.Attribute):
                    found.add(f.attr)
        calls[name] = found
    return calls


def _fragmentos() -> list[str]:
    nomes = []
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                is_frag = (
                    (isinstance(dec, ast.Call) and getattr(dec.func, "attr", None) == "fragment")
                    or (isinstance(dec, ast.Attribute) and dec.attr == "fragment")
                )
                if is_frag:
                    nomes.append(node.name)
    return nomes


def _alcancaveis(inicio: str) -> set[str]:
    calls = _chamadores()
    vistos, pilha = set(), [inicio]
    while pilha:
        for chamado in calls.get(pilha.pop(), ()):
            if chamado in FUNCS and chamado not in vistos:
                vistos.add(chamado)
                pilha.append(chamado)
    return vistos


def _envolvente(lineno: int) -> str:
    melhor = None
    for name, node in FUNCS.items():
        if node.lineno <= lineno <= (node.end_lineno or node.lineno):
            if melhor is None or node.lineno > FUNCS[melhor].lineno:
                melhor = name
    return melhor or ""


def test_no_unscoped_rerun_inside_fragments():
    """M5: nenhum st.rerun() sem scope pode ser alcancável de um fragmento."""
    alcance = {f: _alcancaveis(f) | {f} for f in _fragmentos()}
    offenders = []
    for n in ast.walk(TREE):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "rerun":
            if any(kw.arg == "scope" for kw in n.keywords):
                continue
            fn = _envolvente(n.lineno)
            if any(fn in alc for alc in alcance.values()):
                offenders.append((n.lineno, fn))
    assert not offenders, f"st.rerun() sem scope dentro de fragment: {offenders}"


def test_fragment_reruns_are_scoped():
    """Os cartões passaram a usar scope='fragment' de facto."""
    for card in ("_video_backlog_card_body", "_render_tiktok_automation_task_list", "_youtube_task_card_body"):
        fonte = ast.get_source_segment(MAIN, FUNCS[card]) or ""
        assert fonte, card
        assert 'st.rerun(scope="fragment")' in fonte, f"{card} não usa scope"
    helper = ast.get_source_segment(MAIN, FUNCS["_render_video_download_control"]) or ""
    assert 'st.rerun(scope="fragment")' in helper


# ---------------------------------------------------------------------------
# 2. M3 - catálogo TikTok lido uma vez
# ---------------------------------------------------------------------------


def test_tiktok_cards_share_one_catalog_read():
    """M3: as duas sub-abas partilham o catálogo (antes each uma relia tudo)."""
    cards = ast.get_source_segment(MAIN, FUNCS["_render_tiktok_automation_cards"]) or ""
    assert 'tiktok_tasks = load_automation_tasks_for_platform("tiktok")' in cards
    assert "_render_tiktok_automation_task_list(tiktok_tasks, posted_only=False)" in cards
    assert "_render_tiktok_automation_task_list(tiktok_tasks, posted_only=True)" in cards
    assert cards.count("load_automation_tasks_for_platform") == 1
    assert 'read_json("channels.json"' not in cards

    # a lista continua a poder ser chamada sem o catálogo (chamadas antigas)
    lista = ast.get_source_segment(MAIN, FUNCS["_render_tiktok_automation_task_list"]) or ""
    assert "tasks: list[dict[str, Any]] | None = None" in lista
    assert "else load_automation_tasks_for_platform(\"tiktok\")" in lista


# ---------------------------------------------------------------------------
# 3. M4 - miniaturas reduzidas em cache
# ---------------------------------------------------------------------------


def test_thumbnail_display_path_exists_and_reduces():
    helper = ast.get_source_segment(MAIN, FUNCS["_thumbnail_display_path"]) or ""
    assert "def _thumbnail_display_path(" in MAIN
    assert "Image.LANCZOS" in helper
    assert "_THUMBNAIL_DISPLAY_WIDTH" in MAIN
    assert 'thumbnail_path.stat().st_size' not in helper  # usa stat() único
    # falha devolve o original (nunca quebra o card)
    assert "return thumbnail_path" in helper


def test_cards_render_the_reduced_thumbnail(tmp_path, monkeypatch):
    """Prova funcional: uma thumbnail de 1280x720 sai a 360 px e em cache."""
    pytest.importorskip("PIL")
    from PIL import Image

    monkeypatch.setattr(
        __import__("app.main", fromlist=["_THUMBNAIL_CACHE_DIR"]),
        "_THUMBNAIL_CACHE_DIR",
        tmp_path / "cache",
    )
    import app.main as main_module

    original = tmp_path / "thumb.png"
    Image.effect_noise((1280, 720), 90).convert("RGB").save(original, format="PNG")

    miniatura = main_module._thumbnail_display_path(original)
    assert miniatura != original and miniatura.is_file()
    with Image.open(miniatura) as imagem:
        assert imagem.width == 360
        assert imagem.height == 202
    # segunda chamada reutiliza a miniatura (nenhuma re-codificação)
    assert main_module._thumbnail_display_path(original) == miniatura


def test_thumbnail_display_path_degrades_to_the_original(tmp_path, monkeypatch):
    """Ficheiro corrompido/pasta impossível: devolve o ORIGINAL, sem excepção."""
    monkeypatch.setattr(
        __import__("app.main", fromlist=["_THUMBNAIL_CACHE_DIR"]),
        "_THUMBNAIL_CACHE_DIR",
        tmp_path / "cache",
    )
    import app.main as main_module

    corrompido = tmp_path / "corrompido.png"
    corrompido.write_bytes(b"nao e imagem")
    assert main_module._thumbnail_display_path(corrompido) == corrompido


def test_cards_use_the_display_path_not_the_raw_one():
    for card in ("_render_task_thumbnail",):
        fonte = ast.get_source_segment(MAIN, FUNCS[card]) or ""
        assert "st.image(str(_thumbnail_display_path(thumbnail_path))" in fonte


# ---------------------------------------------------------------------------
# 4. st.video directo substituído pelo player unificado
# ---------------------------------------------------------------------------


def test_no_direct_st_video_outside_the_unified_player():
    """Só o `_render_local_video_player` pode chamar st.video (com caminho)."""
    permitidos = {"_render_local_video_player"}
    offenders = []
    for n in ast.walk(TREE):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "video":
            fn = _envolvente(n.lineno)
            if fn not in permitidos:
                offenders.append((n.lineno, fn, ast.get_source_segment(MAIN, n)))
    assert not offenders, f"st.video fora do player unificado: {offenders}"


def test_cuts_and_python_editor_use_the_local_player():
    cortes = ast.get_source_segment(MAIN, FUNCS["render_cuts"]) or ""
    editor = ast.get_source_segment(MAIN, FUNCS["render_python_editor"]) or ""
    assert "_render_local_video_player(clip_path)" in cortes
    assert "_render_local_video_player(source_path)" in cortes or "_render_local_video_player(generated_path)" in cortes
    assert "_render_local_video_player(source_path)" in editor
    assert "_render_local_video_player(output)" in editor


def test_local_player_serves_every_video_root():
    """As pastas de Cortes/Editor Python/Media/Metadados são raízes servidas."""
    helper = ast.get_source_segment(MAIN, FUNCS["_tb_media_roots"]) or ""
    for root in ("videos", "artifacts", "cuts", "python_editor", "downloads", "metadata_cleaner", "music"):
        assert f'"{root}"' in helper, root
    # storage/state e storage/data NUNCA podem ser servidos (credenciais)
    for proibido in ("state", "data", "logs"):
        assert f'"{proibido}"' not in helper, proibido


# ---------------------------------------------------------------------------
# 5. Downloads sem ler o ficheiro para a RAM
# ---------------------------------------------------------------------------


def test_download_controls_use_the_local_http_server():
    node = FUNCS["_render_download_control"]
    # só o CÓDIGO (a docstring menciona read_bytes() para explicar o passado)
    corpo = "\n".join(
        ast.get_source_segment(MAIN, statement) or ""
        for statement in node.body
        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
    )
    assert "_tb_media_local_url(path)" in corpo
    assert 'download="{safe_name}"' in corpo
    # último recurso (ficheiro fora das raízes): stream, nunca read_bytes()
    assert "path.open(\"rb\")" in corpo
    assert "read_bytes" not in corpo


def test_no_card_reads_a_big_file_for_a_download_button():
    offenders = []
    for n in ast.walk(TREE):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "download_button":
            segmento = ast.get_source_segment(MAIN, n) or ""
            if ".read_bytes()" in segmento:
                offenders.append((n.lineno, _envolvente(n.lineno)))
    assert not offenders, f"st.download_button com read_bytes(): {offenders}"


def test_media_and_metadata_downloads_go_through_the_helper():
    for card in ("render_media_download", "render_metadata_cleaner", "render_cuts", "render_python_editor"):
        if card not in FUNCS:
            continue
        fonte = ast.get_source_segment(MAIN, FUNCS[card]) or ""
        if card in ("render_media_download", "render_metadata_cleaner"):
            assert "_render_download_control(" in fonte, card
    musica = ast.get_source_segment(MAIN, FUNCS["_render_music_file_card"]) or ""
    assert "_render_download_control(" in musica


# ---------------------------------------------------------------------------
# 6. M8 - lixo de testes e ficheiros de debug
# ---------------------------------------------------------------------------


def test_installer_test_no_longer_writes_inside_the_repo_storage():
    """O teste de TEMP passou a usar um directório temporário do pytest."""
    teste = (ROOT / "tests" / "test_winerror32_temp_isolation.py").read_text(encoding="utf-8")
    assert 'LOCALAPPDATA", str(ROOT / "storage" / "_temp_test")' not in teste
    assert 'LOCALAPPDATA", str(tmp_path / "localappdata")' in teste
    assert "tmp_path" in teste


def test_generated_files_are_ignored():
    ignorados = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "storage/_temp_test/" in ignorados
    assert "storage/thumbnails/cache/" in ignorados


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
