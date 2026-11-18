"""1.1.00 — skills externas integradas ao catálogo Remotion do Thunderbolt.

As skills «claude-animated-shorts» e «line-art-animation» (ambas MIT) foram
vendidas de repositórios externos. Estes contratos travam o que a integração
promete:

  · as pastas existem em `seed/remotion_skills/` e são autocontidas (SKILL.md);
  · o `index.json` lista as duas novas skills com `folder` correcto;
  · o catálogo NÃO foi reordenado — as packs novas entram alfabeticamente e as
    18 existentes ficam na mesma posição relativa;
  · as composições `Cartoon3DShort` e `LineArtAnimation` existem e estão
    registadas no `Root.tsx` do pacote Remotion;
  · a lista da UI (`REMOTION_STYLE_OPTIONS`) espelha o índice — sem ela a skill
    nova nunca apareceria no selector de estilos do canal;
  · os caminhos de instalação global da skill original (`~/.claude/skills/`)
    não vazam para o SKILL.md adaptado.

Não é teste de ficheiro-a-ficheiro: as contagens e os conteúdos vêm do disco.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "seed" / "remotion_skills"
REMOTION_SRC = ROOT / "packages" / "remotion" / "src"

PACKS_NOVOS = ("cartoon-3d-skills", "line-art-animation-skills")
SKILLS_NOVAS = ("cartoon-3d-short", "line-art-animation")
# nomes como aparecem no selector da UI (campo `name` do index)
NOMES_UI = ("Cartoon 3D Short", "Line Art Animation")
COMPOSICOES_NOVAS = ("Cartoon3DShort", "LineArtAnimation")


def _index() -> dict:
    return json.loads((SKILLS_ROOT / "index.json").read_text(encoding="utf-8"))


def _skill(index: dict, skill_id: str) -> dict:
    for pack in index["packs"]:
        for skill in pack["skills"]:
            if skill.get("id") == skill_id:
                return skill
    raise AssertionError(f"skill {skill_id} não está no index.json")


# ---------------------------------------------------------------------------
# 1. as pastas existem e são autocontidas
# ---------------------------------------------------------------------------


PARES = list(zip(PACKS_NOVOS, SKILLS_NOVAS, strict=True))


@pytest.mark.parametrize("pack,skill", PARES)
def test_new_skill_folders_exist_with_skill_md(pack: str, skill: str) -> None:
    raiz = SKILLS_ROOT / pack / skill
    assert raiz.is_dir(), f"pasta em falta: {raiz}"
    assert (raiz / "SKILL.md").is_file(), f"SKILL.md em falta em {raiz}"
    # licença MIT do repo de origem tem de ser preservada
    assert (raiz / "LICENSE").is_file(), f"LICENSE em falta em {raiz}"


def test_new_skills_are_self_contained() -> None:
    """Cada skill nova tem o conteúdo que a sua SKILL.md promete."""
    cartoon = SKILLS_ROOT / "cartoon-3d-skills" / "cartoon-3d-short"
    lineart = SKILLS_ROOT / "line-art-animation-skills" / "line-art-animation"

    # cartoon: templates + referências (SÓ markdown)
    assert (cartoon / "templates" / "bridge" / "story.ts").is_file()
    assert (cartoon / "templates" / "bridge" / "Bridge.tsx").is_file()
    assert (cartoon / "references" / "STYLE_BIBLE.md").is_file()
    assert (cartoon / "references" / "reports").is_dir()

    # line-art: a biblioteca de 4 ficheiros `.ts` sem dependências
    for modulo in ("ink.ts", "gait.ts", "motion.ts", "daynight.ts"):
        assert (lineart / "lib" / modulo).is_file(), f"lib/{modulo} em falta"
    assert (lineart / "references" / "style.md").is_file()


def test_private_study_frames_are_not_published() -> None:
    """O SKILL.md original proíbe publicar o material de estudo do canal.

    `references/frames/` e `references/sheets/` são ~17 MB de fotogramas
    extraídos de vídeos de um canal privado; este repo é público (GitHub +
    tarball npm), por isso só os textos de análise entraram.
    """
    cartoon = SKILLS_ROOT / "cartoon-3d-skills" / "cartoon-3d-short"
    for proibido in ("references/frames", "references/sheets"):
        assert not (cartoon / proibido).exists(), f"{proibido} não devia ser publicado"
    # e nenhum ficheiro de imagem foi copiado para a skill
    imagens = list(cartoon.rglob("*.jpg")) + list(cartoon.rglob("*.png"))
    assert not imagens, f"imagens de estudo não deviam estar aqui: {imagens[:3]}"


# ---------------------------------------------------------------------------
# 2. o index.json lista as skills novas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_id", SKILLS_NOVAS)
def test_index_registers_the_new_skills(skill_id: str) -> None:
    skill = _skill(_index(), skill_id)
    assert skill["name"], "a skill nova precisa de nome"
    assert skill.get("description"), "a skill nova precisa de descrição"
    assert skill.get("folder"), "a skill nova precisa de folder"
    # a pasta anunciada no índice é a que existe no disco
    assert (SKILLS_ROOT / skill["folder"]).is_dir(), f"folder não existe: {skill['folder']}"


def test_index_counts_grew_by_two() -> None:
    index = _index()
    assert len(index["packs"]) == 20
    assert sum(len(p["skills"]) for p in index["packs"]) == 57


# ---------------------------------------------------------------------------
# 3. o catálogo existente NÃO foi reordenado
# ---------------------------------------------------------------------------


def test_existing_packs_keep_their_relative_order() -> None:
    """As packs novas entram alfabeticamente; as 18 existentes não se mexem."""
    index = _index()
    nomes = [pack["name"] for pack in index["packs"]]
    assert nomes == sorted(nomes), "o catálogo tem de ficar alfabético por pack"
    # as duas novas estão logo nas posições alfabéticas certas
    assert nomes.index("cartoon-3d-skills") == nomes.index("b-roll-skills") + 1
    assert nomes.index("line-art-animation-skills") == nomes.index("kinetic-typography-skills") + 1
    # e a ordem relativa das antigas está intacta
    antigas = [n for n in nomes if n not in PACKS_NOVOS]
    assert antigas == [
        "ad-video-skills", "b-roll-skills", "data-animation-skills", "ecommerce-video-skills",
        "explainer-video-skills", "freelance-motion-skills", "generative-illustration-skills",
        "javascript-animation-skills", "kinetic-typography-skills", "lower-thirds-skills",
        "manim-skills", "map-animation-skills", "motion-design-skills",
        "text-message-video-skills", "tiktok-video-skills", "web-animation-skills",
        "webgl-animation-skills", "youtube-video-skills",
    ]


# ---------------------------------------------------------------------------
# 4. as composições existem e estão registadas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("composition", COMPOSICOES_NOVAS)
def test_new_compositions_exist_and_are_registered(composition: str) -> None:
    ficheiro = REMOTION_SRC / "compositions" / f"{composition}.tsx"
    assert ficheiro.is_file(), f"composição em falta: {ficheiro}"

    root = (REMOTION_SRC / "Root.tsx").read_text(encoding="utf-8")
    assert f'id="{composition}"' in root, f"{composition} não está registada no Root.tsx"
    assert f"from \"./compositions/{composition}\"" in root, f"{composition} não é importada no Root.tsx"


def test_new_compositions_have_default_props() -> None:
    """Sem defaultProps o `npx remotion render` não arranca."""
    root = (REMOTION_SRC / "Root.tsx").read_text(encoding="utf-8")
    for composition in COMPOSICOES_NOVAS:
        bloco = root.split(f'id="{composition}"', 1)[1].split("/>", 1)[0]
        assert "defaultProps={" in bloco, f"{composition} sem defaultProps"
        assert "durationInFrames={" in bloco, f"{composition} sem durationInFrames"


def test_lineart_composition_uses_the_vendored_library() -> None:
    """A composição tem de consumir a `lib/` vendida — não senos livres."""
    fonte = (REMOTION_SRC / "compositions" / "LineArtAnimation.tsx").read_text(encoding="utf-8")
    for modulo in ("gait", "motion", "daynight"):
        assert modulo in fonte, f"LineArtAnimation não usa {modulo}"
    assert "walk.pose(" in fonte or "walkerPose(" in fonte, "a marcha tem de vir de gait()"


def test_cartoon_composition_uses_the_vendored_timeline() -> None:
    """A timeline do template dita os shots — não uma reimplementação."""
    fonte = (REMOTION_SRC / "compositions" / "Cartoon3DShort.tsx").read_text(encoding="utf-8")
    timeline = REMOTION_SRC / "videos" / "cartoon-3d" / "story.ts"
    assert timeline.is_file(), "timeline do template não foi vendorizada"
    for exported in ("SHOTS", "camAt", "dofAt", "bridgeState", "layersAt"):
        assert exported in fonte, f"Cartoon3DShort não usa {exported} da timeline"


def test_cartoon_composition_documents_the_scope_decision() -> None:
    """A decisão de NÃO adicionar three.js tem de estar escrita no código.

    Motivo: `scripts/install.mjs` corre `npm install` simples e o conjunto
    R3F 9/react-three-postprocessing não resolve contra o React 18 do pacote —
    a instalação abortaria para todos os utilizadores.
    """
    fonte = (REMOTION_SRC / "compositions" / "Cartoon3DShort.tsx").read_text(encoding="utf-8")
    assert "install.mjs" in fonte
    assert "npm install" in fonte


# ---------------------------------------------------------------------------
# 5. a lista da UI espelha o índice
# ---------------------------------------------------------------------------


def test_remotion_style_options_mirror_the_index() -> None:
    main_source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    bloco = main_source.split("REMOTION_STYLE_OPTIONS = [", 1)[1].split("\n]", 1)[0]
    opcoes = [linha.strip().strip('",') for linha in bloco.splitlines() if linha.strip().startswith('"')]

    index = _index()
    extraidas = [s["name"] for pack in index["packs"] for s in pack["skills"]]
    assert opcoes[:3] == ["Sem Estilo/Livre", "Vox-style Motion", "Hand-drawn Canvas Animation"]
    assert set(opcoes[3:]) == set(extraidas)
    assert len(opcoes) == 3 + len(extraidas)
    for nome in NOMES_UI:
        assert nome in opcoes, f"{nome} não aparece no selector da UI"


def test_new_style_options_are_in_the_alphabetical_slot() -> None:
    """Entram alfabeticamente, como o resto da lista."""
    main_source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    bloco = main_source.split("REMOTION_STYLE_OPTIONS = [", 1)[1].split("\n]", 1)[0]
    opcoes = [linha.strip().strip('",') for linha in bloco.splitlines() if linha.strip().startswith('"')]
    assert opcoes.index("Cartoon 3D Short") == opcoes.index("Talking-head B-roll") + 1
    assert opcoes.index("Line Art Animation") == opcoes.index("Kinetic Typography") + 1


# ---------------------------------------------------------------------------
# 6. os caminhos de instalação global da origem não vazam
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack,skill", PARES)
def test_skill_md_has_no_global_install_paths(pack: str, skill: str) -> None:
    texto = (SKILLS_ROOT / pack / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "~/.claude/skills" not in texto
    assert "/.claude/" not in texto
    # e passa a apontar para a estrutura do Thunderbolt
    assert "packages/remotion" in texto


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))