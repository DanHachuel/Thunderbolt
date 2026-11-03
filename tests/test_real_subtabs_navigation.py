"""Testes de navegação real — roteamento resolvido, never presença de strings.

1.0.54 — regressão da v0.8.21 (commit 79a9f30): o mapa de aliases colapsava
todas as sub-abas de Growth no pai e o pai apontava para um placeholder; os
testes antigos só verificavam a PRESENÇA de strings no fonte e nunca apanharam
a quebra (os mapeamentos existiam, mas eram inalcançáveis). Estes testes
passaram a processar por AST os mapas reais de `app/main.py` e a simular a
resolução efectuada em runtime (`aliases.get(página, página)` → renderers).
"""

import ast
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

# As 5 sub-abas reais do grupo «Analise Growth» (rótulo → target de clique).
GROWTH_SIDEBAR_ITEMS = {
    "Growth Youtube": "Growth Youtube",
    "Growth Tiktok": "Growth Tiktok",
    "Growth Instagram": "Growth Instagram",
    "Facebook Pages": "Growth Facebook Pages",
    "Growth Bilibili": "Growth Bilibili",
}


def _dict_assignment(name: str) -> ast.Dict:
    """Devolve o nó AST do dict atribuído a ``name`` em qualquer escopo."""
    for node in ast.walk(ast.parse(MAIN_SOURCE)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node.value
    raise AssertionError(f"mapa «{name}» não encontrado em app/main.py")


def _aliases_map() -> dict[str, str]:
    return ast.literal_eval(_dict_assignment("aliases"))


def _renderers_map() -> dict[str, dict[str, str]]:
    """Chave do renderers -> {'function': nome} ou {'placeholder': texto}."""
    resolved: dict[str, dict[str, str]] = {}
    for key_node, value_node in zip(_dict_assignment("renderers").keys, _dict_assignment("renderers").values):
        if not isinstance(key_node, ast.Constant):
            continue
        if isinstance(value_node, ast.Name):
            resolved[str(key_node.value)] = {"function": value_node.id}
        elif isinstance(value_node, ast.Call):
            placeholder = ""
            for arg in value_node.args:
                if isinstance(arg, ast.Constant):
                    placeholder = str(arg.value)
            resolved[str(key_node.value)] = {"placeholder": placeholder}
        else:
            resolved[str(key_node.value)] = {"lambda": ast.dump(value_node)[:80]}
    return resolved


def _resolve_page(stored_page: str, aliases: dict[str, str]) -> str:
    """Simulação EXACTA da resolução de main(): aliases.get(stored, stored)."""
    return aliases.get(stored_page, stored_page)


# ---------------------------------------------------------------------------
# Growth: roteamento real (nunca mais validação de presença de string)
# ---------------------------------------------------------------------------


def test_growth_subtabs_never_collapse_through_aliases():
    aliases = _aliases_map()
    for target in GROWTH_SIDEBAR_ITEMS.values():
        resolved = _resolve_page(target, aliases)
        assert resolved == target, (
            f"a sub-aba «{target}» colapsa para «{resolved}» pelo mapa de "
            "aliases — regressão da v0.8.21 (commit 79a9f30)"
        )
    # Nenhum alias pode apontar uma sub-aba de Growth para o pai.
    for source, destination in aliases.items():
        if source in GROWTH_SIDEBAR_ITEMS.values():
            assert destination != "Growth", f"alias «{source}» colapsa no pai"


def test_growth_parent_renders_the_real_page_not_a_placeholder():
    renderers = _renderers_map()
    assert renderers["Growth"] == {"function": "render_growth_pages"}
    # O placeholder de Growth não pode existir em nenhum mapeamento.
    assert '"Seleccione uma subaba de Growth."' not in MAIN_SOURCE


def test_growth_subtab_renderers_are_real_functions():
    renderers = _renderers_map()
    for target in GROWTH_SIDEBAR_ITEMS.values():
        assert target in renderers, f"«{target}» não tem renderizador no mapa"
        assert renderers[target].get("function"), (
            f"«{target}» não aponta para uma função real: {renderers[target]}"
        )
    assert renderers["Growth Youtube"]["function"] == "render_growth_youtube"
    assert renderers["Growth Tiktok"]["function"] == "render_growth_tiktok"
    assert renderers["Growth Instagram"]["function"] == "render_growth_instagram"
    assert renderers["Growth Facebook Pages"]["function"] == "render_growth_facebook_pages"
    assert renderers["Growth Bilibili"]["function"] == "render_growth_bilibili"


def test_facebook_pages_key_is_disambiguated_across_sections():
    """A chave «Facebook Pages» existe em Canais/Perfis e em Growth.

    Com a mesma chave nos dois, a última ocorrência do dict literal escondia
    a outra (1.0.54): o alvo do Growth passa a ser distinto e o de Canais
    volta a renderizar a sua própria página.
    """
    renderers = _renderers_map()
    assert renderers["Facebook Pages"] == {"function": "render_facebook_pages"}
    assert renderers["Growth Facebook Pages"] == {"function": "render_growth_facebook_pages"}


def test_renderers_map_has_no_duplicate_keys():
    keys = [str(key.value) for key in _dict_assignment("renderers").keys if isinstance(key, ast.Constant)]
    duplicates = {key: count for key, count in Counter(keys).items() if count > 1}
    assert not duplicates, f"chaves duplicadas no mapa de renderers: {duplicates}"


def test_growth_sidebar_click_resolves_to_a_real_renderer():
    """Percurso completo do clique: rótulo → target → aliases → renderers."""
    aliases = _aliases_map()
    renderers = _renderers_map()
    for _label, target in GROWTH_SIDEBAR_ITEMS.items():
        page = _resolve_page(target, aliases)
        assert page in renderers, f"«{page}» não existe no mapa de renderers"
        assert renderers[page].get("function"), f"«{page}» cai num placeholder: {renderers[page]}"
    # O pai continua a ser uma página real (com as 5 sub-abas internas).
    page = _resolve_page("Growth", aliases)
    assert renderers[page] == {"function": "render_growth_pages"}


def test_growth_legacy_aliases_still_resolve_to_real_pages():
    aliases = _aliases_map()
    renderers = _renderers_map()
    for legacy in ("Analista Growth Youtube", "Analista Facebook Pages"):
        page = _resolve_page(legacy, aliases)
        assert renderers[page].get("function"), f"legado «{legacy}» cai em placeholder: {renderers[page]}"


# ---------------------------------------------------------------------------
# Testes de Documentação (1.0.52 — sessão paralela) preservados
# ---------------------------------------------------------------------------


def test_growth_is_a_page_with_real_content_tabs():
    assert '"Growth": growth_items' in MAIN_SOURCE
    assert 'growth_items = growth_analysis_items' in MAIN_SOURCE
    assert "render_growth_pages" in MAIN_SOURCE


def test_documentation_is_a_page_with_real_content_tabs():
    # 1.0.52 — «Documentação» deixou de ser página do menu lateral: os
    # tutoriais passaram a aba INTERNA da página Configurações (render_settings),
    # com as sub-tabs reais (Meta, Supabase, Kaggle, ...) intactas.
    assert "with documentation_tab:" in MAIN_SOURCE
    assert "render_documentation_pages" not in MAIN_SOURCE
    assert '"Documentação": documentation_items' not in MAIN_SOURCE
    assert "documentation_items" not in MAIN_SOURCE
    assert "tutorial_items" not in MAIN_SOURCE
    assert '"Meta", "Supabase", "Kaggle", "Apify", "YouTube Video-Upload Frontend",' in MAIN_SOURCE.replace("\n", " ")
    assert "render_models_ai_tutorial," in MAIN_SOURCE
    assert "render_supabase_tutorial," in MAIN_SOURCE


def test_growth_and_documentation_do_not_use_expandable_submenus():
    assert 'growth_items = []' not in MAIN_SOURCE
    assert 'documentation_items = []' not in MAIN_SOURCE
    assert 'Seleccione um tutorial no menu expansível' not in MAIN_SOURCE
    assert 'Seleccione uma das abas de Growth no menu expansível' not in MAIN_SOURCE
    assert 'Seleccione uma subaba de Growth.' not in MAIN_SOURCE


def test_existing_upload_music_reference_remains_tab_based():
    assert 'render_localized_tabs(["JewelMusic", "Pushtunes", "ytmusicapi", "DistroKid"])' in MAIN_SOURCE
