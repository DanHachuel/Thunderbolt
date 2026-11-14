"""1.0.99 — o gate das Skills locais (.opencode/skills) no CI.

As skills de auditoria vivem no repo (`.opencode/skills/<skill>/scripts/`) e são
 executadas pelo workflow de publish como passo bloqueante. Este ficheiro prende
esse contrato: se alguém apagar uma skill, mover um script ou remover o passo do
workflow, o gate do CI falha aqui — não na publicação.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".opencode" / "skills"
WORKFLOW = ROOT / ".github" / "workflows" / "publish-npm.yml"

SCRIPTS = (
    "evitar-regressoes/scripts/verificar-atomic.py",
    "escopo-cirurgico/scripts/verificar-escopo.py",
    "streamlit-estado/scripts/verificar-streamlit.py",
    "windows-processos/scripts/verificar-spawn.py",
    "testes-contrato/scripts/verificar-testes.py",
)


@pytest.mark.parametrize("relativo", SCRIPTS)
def test_every_audit_script_is_versioned(relativo: str):
    """O script existe no repo e é um ficheiro Python executável."""
    caminho = SKILLS / relativo
    assert caminho.is_file(), f"skill ausente: .opencode/skills/{relativo}"
    assert caminho.read_text(encoding="utf-8").lstrip().startswith(("#!", "'''", '"""'))


def test_every_skill_has_a_discoverable_skill_md():
    """OpenCode só descobre skills com SKILL.md e frontmatter (name/description)."""
    for pasta in sorted(p.name for p in SKILLS.iterdir() if p.is_dir()):
        skill = SKILLS / pasta / "SKILL.md"
        assert skill.is_file(), f"{pasta} não tem SKILL.md"
        cabecalho = skill.read_text(encoding="utf-8").split("---")[1]
        assert "name:" in cabecalho, f"{pasta}/SKILL.md sem name"
        assert "description:" in cabecalho, f"{pasta}/SKILL.md sem description"


def test_the_publish_workflow_runs_every_audit_as_a_gate():
    """O passo bloqueante existe e corre os 5 scripts, sem continue-on-error."""
    conteudo = WORKFLOW.read_text(encoding="utf-8")
    passo = conteudo.split("Rodar Auditorias das Skills (Gate)", 1)[1].split("\n      - name:", 1)[0]
    for relativo in SCRIPTS:
        assert f"python .opencode/skills/{relativo}" in passo, f"o gate não corre {relativo}"
    # a chave YAML (com dois pontos) e' a unica forma de um passo ignorar falhas
    assert "continue-on-error:" not in passo
    # fetch-depth 0: o auditor de escopo precisa do histórico para o git diff
    assert "fetch-depth: 0" in conteudo


@pytest.mark.parametrize("relativo", SCRIPTS)
def test_the_audit_scripts_run_clean_on_the_repo(relativo: str):
    """Prova real: cada auditor corre norepo e devolve 0 (verde)."""
    resultado = subprocess.run(
        [sys.executable, str(SKILLS / relativo)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PATH": "", "SYSTEMROOT": ""},
        timeout=120,
    )
    assert resultado.returncode == 0, f"{relativo} falhou:\n{resultado.stdout}"


def test_the_scripts_do_not_depend_on_a_windows_console_encoding():
    """AGENTS.md (regra 3): zero mojibake — os scripts reconfiguram o stdout."""
    for relativo in ("escopo-cirurgico/scripts/verificar-escopo.py", "testes-contrato/scripts/verificar-testes.py"):
        texto = (SKILLS / relativo).read_text(encoding="utf-8")
        assert "reconfigure" in texto, f"{relativo} depende do encoding da consola"