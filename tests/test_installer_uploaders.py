"""1.0.90 — instalação dos uploaders diagnosticável (fim do aborto cego).

Relato do utilizador: `pacotes obrigatórios ainda sem importar após a
reparação: uploader, sau_cli. A instalação foi ABORTADA.` — sem maneira de
saber PORQUÊ. Investigação no código-fonte do social-auto-upload (commit
0012d2c): `sau_cli` importa OS DEZ uploadadores (douyin, kuaishou,
xiaohongshu, bilibili, tencent, alipay, weibo, hupu, youtube, baijiahao) —
qualquer um deles com dependência em falta derruba o import inteiro; e
`uploader/__init__.py` cria diretórios no import.

Contratos: diagnóstico real da excepção no aborto, reparação em dois passos
(spec + dependências declaradas) e `--no-cache-dir` (ZIP corrompido no cache
do pip reaproveitado em cada tentativa).
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL_SOURCE = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")


def test_import_diagnostics_report_the_real_exception():
    """O aborto deixa de dizer apenas «não importa» — mostra a excepção."""
    assert "function moduleImportDiagnostics(modules)" in INSTALL_SOURCE
    assert 'spawnSync(pythonBin, ["-c", `import ${moduleName}`]' in INSTALL_SOURCE
    assert "causa —" in INSTALL_SOURCE  # a linha de causa impressa por pacote
    assert 'split(/\\r?\\n/).filter(Boolean).pop()' in INSTALL_SOURCE


def test_failed_repair_reports_causes_before_aborting():
    assert "function reportMissingModules(label, modules, extraHint" in INSTALL_SOURCE
    assert "reportMissingModules(label, stillMissing);" in INSTALL_SOURCE
    assert 'reportMissingModules(label, unmatched,' in INSTALL_SOURCE
    assert "installLogPath" in INSTALL_SOURCE  # caminho do registo no aborto


def test_repair_never_reuses_a_corrupt_github_zip():
    """--no-cache-dir: o cache do pip reaproveitava um ZIP do social-auto-upload
    corrompido em cada tentativa de reparação."""
    first_repair = INSTALL_SOURCE.split('"a instalar APENAS os pacotes em falta', 1)[0]
    assert '"--no-cache-dir"' in first_repair
    assert '"--force-reinstall"' in first_repair


def test_uploaders_get_a_second_repair_step_with_declared_dependencies():
    """O `import sau_cli` falha por qualquer um dos 10 uploadadores — as
    dependências declaradas do pacote (loguru, opencv-python, qrcode, segno)
    são reinstaladas explicitamente antes do aborto."""
    assert "const SOCIAL_AUTO_UPLOAD_DEPS =" in INSTALL_SOURCE
    for dependency in ("loguru", "opencv-python", "qrcode", "segno", "patchright==1.58.2"):
        assert dependency in INSTALL_SOURCE
    step2 = INSTALL_SOURCE.split("a reparar as dependências declaradas dos uploaders", 1)[1]
    assert "SOCIAL_AUTO_UPLOAD_DEPS" in step2
    assert "stillMissing = missingModules(modules);" in step2
    # o gatilho é o alias social-auto-upload (uploader/sau_cli)
    assert 'moduleRequirementAliases[moduleName] === "social-auto-upload"' in INSTALL_SOURCE


def test_uploaders_remain_mandatory_no_opt_in_skip():
    """Regra do AGENTS.md: dependências obrigatórias nunca ficam atrás de flag
    — o que mudou foi o diagnóstico e a reparação, não a obrigatoriedade."""
    assert "uploader" in INSTALL_SOURCE
    assert "sau_cli" in INSTALL_SOURCE
    assert "A instalação foi ABORTADA" in INSTALL_SOURCE
    # nenhuma FLAG de exclusão (a menção em comentário histórico não conta)
    assert 'args.includes("--with-uploaders")' not in INSTALL_SOURCE
    assert 'args.includes("--skip-uploaders")' not in INSTALL_SOURCE
    assert "process.env.SKIP_UPLOADERS" not in INSTALL_SOURCE
