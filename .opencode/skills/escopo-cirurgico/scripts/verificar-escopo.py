#!/usr/bin/env python3
"""
Auditoria de Escopo: verifica o git status e alerta se arquivos restritos
foram modificados numa tarefa de UI/dependências.

Uso: python scripts/verificar-escopo.py

1.1.00 — PRECISÃO, NÃO SILÊNCIO. A versão anterior proibia `pipeline_worker.py`
por nome: qualquer tarefa que tocasse `app/main.py` E o worker falhava, mesmo
quando a tarefa era *justamente* sobre o worker (ex.: silenciar a telemetria
`[SCRIPT]`/`[PEXELS]`, que vive lá). O resultado era um gate que só passava
quando se ignorava o passo — o pior dos dois mundos.

Agora a proibão é sobre o TIPO de mudança:
  · install.mjs, requirements.txt e as DEPENDÊNCIAS do package.json ficam
    sempre proibidos em tarefas de UI (é a regra 1 do AGENTS.md);
  · pipeline_worker.py passa a ser permitido quando a alteração está confinada
    a LOGGING (print/logger/handler/nível/comentário) — é o conteúdo da tarefa,
    não uma mexida no motor de render;
  · o bump de versão em package.json (MAJOR.MINOR.PATCH) é sempre permitido:
    faz parte de toda a entrega e não é uma alteração de dependências.

Qualquer outra coisa nesses ficheiros continua a ser violação.
"""
import ast
import re
import subprocess
import sys
from pathlib import Path

# AGENTS.md (regra 3): zero mojibake. A consola do Windows (cp1252) nao imprime
# os emojis dos relatorios - reconfiguramos a saida antes de qualquer print.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

# Proibidos SEMPRE em tarefa de UI (instalador e dependências - regra 1).
PROIBIDOS_INSTALADOR = ["install.mjs", "requirements.txt"]
# Proibidos SÓ quando a mudança não é de logging/versão.
PROIBIDOS_CONDICIONAIS = ["pipeline_worker.py"]

# Tokens que, em qualquer ponto da linha, fazem dela uma linha de LOGGING.
_TOKENS_LOGGING = re.compile(
    r"(logging\.(getLogger|FileHandler|StreamHandler|Formatter|INFO|WARNING|DEBUG|ERROR|CRITICAL)"
    r"|_logger|logger\.|print\s*\(|handler|_mpt_runtime_|telemetria|YT-AUTOM|MPT-|PEXELS|SCRIPT"
    r"|stderr|stdout|THUNDERBOLT_DEBUG|create_stream_handler|ensure_.*logger"
    r"|makedirs|automation\.log|mpt_runtime\.log|/ \"logs\")",
    re.IGNORECASE,
)
# Linhas estruturais de Python que, sozinhas, não carregam lógica de negócio.
# Um `if task.get("state") == "doing":` NÃO casa aqui (tem expressão).
# As palavras-chave ficam SEM expressão própria: quem trata o resto da linha
# (espaços + comentário) é o grupo final — assim `pass  # explicação` passa,
# mas `return video_path, False` e `pass 1` não.
_ESTRUTURAL = re.compile(
    r"^\s*(#.*|\"\"\"|'''|import\b.*|from\b.*|try\s*:|except[^:]*:|finally\s*:|else\s*:|elif[^:]*:|"
    r"return|pass|break|continue|@.*|)\s*(#.*)?$",
)
# Assinatura de CÓDIGO de verdade (atribuição, chamada, palavra-chave de fluxo).
# Uma linha suspeita sem token de logging é uma alteração fora do escopo.
_SUSPEITA = re.compile(r"(=[^=]|\(|\b(if|for|while|def|class|with|raise|assert|del|yield|await)\b)")
# O bump de versão (duplo) faz parte de toda a entrega. `_changed_lines` já
# entrega a linha SEM o prefixo `+`/`-` do diff, por isso não o exigimos aqui.
_VERSION_LINE = re.compile(r'^\s*"?version"?\s*[:=]\s*"?\d+\.\d+\.\d+"?', re.IGNORECASE)


def _git(*args: str) -> str:
    """Saída de um comando git, sempre como `str` (nunca None).

    `subprocess.run(text=True)` sem encoding explícito decodida com
    `locale.getpreferredencoding()` — cp1252 no Windows. O diff de ficheiros
    com comentários em português tem bytes indefinidos nessa tabela (ex.: 0x8D),
    o que faz a thread de leitura do subprocess rebentar e devolve `stdout=None`
    — e a auditoria morria com `AttributeError` em qualquer repositório com
    acentos. Encoding explícito + `errors="replace"` resolve as duas coisas.
    """
    try:
        resultado = subprocess.run(
            ["git", *args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        return resultado.stdout or ""
    except Exception as exc:  # noqa: BLE001 - a auditoria nunca rebenta
        print(f"Erro ao rodar git {' '.join(args)}: {exc}", file=sys.stderr)
        return ""


def get_modified_files() -> list[str]:
    return [f for f in _git("diff", "--name-only", "HEAD").split("\n") if f]


def _changed_lines(path: str) -> list[str]:
    """Conteúdo (+ e -) do diff de um ficheiro, sem o prefixo do diff.

    O prefixo `+`/`-` tem de sair antes de qualquer comparação: com ele, um
    `re.match` ancorado no início nunca casava — e diff "não identificado"
    significava violação para tudo (ou permissão para tudo, no caminho
    inverso da lógica).
    """
    diff = _git("diff", "HEAD", "--", path) or ""
    linhas = []
    for linha in diff.splitlines():
        if linha.startswith(("+++", "---", "@@", "diff ", "index ")):
            continue
        if linha.startswith(("+", "-")):
            linhas.append(linha[1:])
    return linhas


def _linhas_de_docstring(path: str) -> set[int]:
    """Linhas (no ficheiro NOVO) cobertas por docstrings.

    Prosa de docstring tem parênteses, `=` e palavras como `if` — a heurística
    de código erra sempre nela. Com o AST a coisa é exacta: o que está dentro
    de uma docstring nunca é código.
    """
    try:
        codigo = Path(path).read_text(encoding="utf-8")
        arvore = ast.parse(codigo)
    except (OSError, SyntaxError, ValueError):
        return set()
    linhas: set[int] = set()
    for node in ast.walk(arvore):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        corpo = getattr(node, "body", None)
        if not corpo:
            continue
        primeira = corpo[0]
        if isinstance(primeira, ast.Expr) and isinstance(primeira.value, ast.Constant) and isinstance(
            primeira.value.value, str
        ):
            linhas.update(range(primeira.lineno, (primeira.end_lineno or primeira.lineno) + 1))
    return linhas


def _mudancas_numeradas(path: str) -> list[tuple[int, str]]:
    """(linha no ficheiro NOVO, conteúdo) de cada linha alterada."""
    diff = _git("diff", "HEAD", "--", path)
    linhas_novo = 0
    saida: list[tuple[int, str]] = []
    for linha in diff.splitlines():
        if linha.startswith("@@"):
            encontro = re.search(r"\+(\d+)(?:,(\d+))?", linha)
            if not encontro:
                continue
            linhas_novo = int(encontro.group(1))
            if linhas_novo == 0:  # ficheiro apagado: nada a numerar
                linhas_novo = -1
            continue
        if linha.startswith(("+++", "---", "diff ", "index ")):
            continue
        if linha.startswith("+"):
            if linhas_novo > 0:
                saida.append((linhas_novo, linha[1:]))
            linhas_novo += 1
        elif linha.startswith("-"):
            continue  # linha removida: só existe no ficheiro antigo
        elif linha.startswith("\\"):
            continue
        else:
            linhas_novo += 1  # contexto
    return saida


def _eh_linha_de_logging(linha: str) -> bool:
    """Uma linha conta como logging se tem um token de logging OU é estrutural.

    O comentário é retirado ANTES de procurar tokens: um `# ... logging ...` a
    explicar uma linha de código arbitrário não pode fazer essa linha passar
    por ser de logging.
    """
    sem_comentario = re.sub(r"#.*$", "", linha).rstrip()
    if not sem_comentario.strip():
        return True  # comentário puro
    if _TOKENS_LOGGING.search(sem_comentario):
        return True
    return bool(_ESTRUTURAL.match(linha))


def _eh_mudanca_de_logging(path: str) -> bool:
    """True quando TODA a mudança no ficheiro é de logging/telemetria."""
    mudancas = _mudancas_numeradas(path)
    if not mudancas:
        return True
    docstrings = _linhas_de_docstring(path)
    for numero, conteudo in mudancas:
        if numero in docstrings:
            continue  # prosa de docstring: nunca é código
        if not _eh_linha_de_logging(conteudo):
            return False
    return True


def _eh_so_bump_de_versao(path: str) -> bool:
    linhas = _changed_lines(path)
    if not linhas:
        return True
    return all(_VERSION_LINE.match(linha) for linha in linhas)


def main() -> int:
    modified = get_modified_files()
    if not modified:
        print("✅ Nenhum arquivo modificado.")
        return 0

    print(f"🔍 Analisando {len(modified)} arquivo(s) modificado(s)...")

    tarefa_de_ui = any("app/main.py" in f or "pages/" in f for f in modified)
    alertas: list[str] = []
    permitidos: list[str] = []

    # Itera sobre os ficheiros REALMENTE modificados (com o caminho completo) e
    # compara com os padrões proibidos. Passar o padrão ao git em vez do
    # caminho real devolvia um diff vazio — e diff vazio significava
    # "alteração confinada a logging", deixando passar qualquer coisa.
    def _proibidos(padroes: list[str]) -> list[tuple[str, str]]:
        return [
            (ficheiro, padrao)
            for padrao in padroes
            for ficheiro in modified
            if padrao in ficheiro
        ]

    for ficheiro, padrao in _proibidos(PROIBIDOS_INSTALADOR):
        if tarefa_de_ui:
            alertas.append(
                f"⚠️  Tarefa de UI detectada, mas o INSTALADOR/DEPENDÊNCIAS '{ficheiro}' foi alterado."
            )
        else:
            permitidos.append(f"{ficheiro} (tarefa de instalador: permitido)")

    for ficheiro, _padrao in _proibidos(PROIBIDOS_CONDICIONAIS):
        if _eh_so_bump_de_versao(ficheiro):
            permitidos.append(f"{ficheiro} (apenas bump de versão)")
        elif _eh_mudanca_de_logging(ficheiro):
            permitidos.append(f"{ficheiro} (alteração confinada a logging/telemetria)")
        elif tarefa_de_ui:
            alertas.append(
                f"⚠️  Tarefa de UI detectada e '{ficheiro}' foi alterado FORA de logging "
                f"(mexer no motor de render/pipeline exige tarefa própria)."
            )
        else:
            permitidos.append(f"{ficheiro} (tarefa de backend: permitido)")

    if "package.json" in modified and not _eh_so_bump_de_versao("package.json"):
        alertas.append("⚠️  package.json alterado fora de um bump de versão (dependências).")

    if alertas:
        print("\n🚨 VIOLAÇÕES DE ESCOPO DETECTADAS:")
        for alerta in alertas:
            print(alerta)
        print("\nReverta essas alterações antes do commit ou justifique.")
        return 1

    for permitido in permitidos:
        print(f"✅ {permitido}")
    print("\n✅ SUCESSO: nenhuma violação de escopo detectada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())