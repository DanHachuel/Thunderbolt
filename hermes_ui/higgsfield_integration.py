"""Higgsfield AI via CLI (a autenticacao nao e uma chave de API).

O Higgsfield expoe a geracao por um CLI (`@higgsfield/cli`, binarios `higgsfield`
e `higgs`) que guarda a autenticacao do utilizador (`higgsfield auth login`) e
por skills de agente (`higgsfield-ai/skills`). Como a credencial vive no CLI e
nao e uma chave por cartao, o provedor nao encaixa no catalogo de "cards" com
chave (`hermes_ui/media_providers.py`); daqui este modulo proprio, que embrulha
o CLI para a UI do Thunderbolt.

Comandos usados (verificados na documentacao oficial do CLI e das skills):

    higgsfield account status                      estado da autenticacao
    higgsfield auth login                          login interactivo (terminal)
    higgsfield generate create <jst> ... --json    cria um job (sem --wait)
    higgsfield generate get <id> --json            le um job
    higgsfield generate wait <id> --json           espera por um job
    higgsfield generate list --json
    higgsfield product-photoshoot create --mode <mode> [--count N] [prompt]
    higgsfield soul-id create --name X --soul-2 --image <p> ...
    higgsfield soul-id wait <id>

O CLI aceita `--wait`/`--wait-timeout`/`--wait-interval` e saida `--json`. Uma
flag de media aceita caminho local (o CLI faz o upload) ou um UUID. A UI cria o
job SEM `--wait` (resposta imediata) e acompanha com `generate get` num
`st.fragment`, para nao bloquear a thread do Streamlit.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

# Binarios do pacote @higgsfield/cli (npm), por ordem de preferencia.
HIGGSFIELD_EXECUTABLES: tuple[str, ...] = ("higgsfield", "higgs")

# Tempo limite de UMA chamada ao CLI. A criacao de job e a leitura sao curtas; a
# espera (`generate wait`) e a que pode demorar, e por isso tem o seu proprio.
COMMAND_TIMEOUT_SECONDS = 120
WAIT_TIMEOUT_SECONDS = 600

# Estados terminais de um job (a documentacao do CLI usa "completed").
HIGGSFIELD_TERMINAL_STATUSES = frozenset({"completed", "complete", "succeeded", "failed", "error", "cancelled", "canceled"})
HIGGSFIELD_DONE_STATUSES = frozenset({"completed", "complete", "succeeded"})

HIGGSFIELD_INSTALL_INSTRUCTIONS = (
    "Instale o CLI do Higgsfield com um destes comandos no terminal:\n"
    "  npm install -g @higgsfield/cli          (Windows, macOS e Linux)\n"
    "  curl -fsSL https://raw.githubusercontent.com/higgsfield-ai/cli/main/install.sh | sh\n"
    "  brew install higgsfield-ai/tap/higgsfield\n"
    "Depois feche e volte a abrir o Thunderbolt para o PATH ser actualizado."
)

HIGGSFIELD_LOGIN_INSTRUCTIONS = (
    "Corra no terminal, fora do Thunderbolt:\n"
    "  higgsfield auth login\n"
    "O login e interactivo (abre o browser para autorizar a conta). O agente nao "
    "o faz automaticamente por seguranca."
)

# Chaves que o CLI pode usar para identificar um job. Nenhuma e garantida pela
# documentacao, por isso procuro em varias e nao invento uma so.
_JOB_ID_KEYS = ("id", "job_id", "job_set_id", "request_id", "task_id")


class HiggsfieldError(RuntimeError):
    """Falha de uma operacao do Higgsfield (CLI ausente, sem auth, job falhado)."""


def higgsfield_executable() -> str | None:
    """Caminho do binario do CLI, ou None se nao estiver instalado."""
    for name in HIGGSFIELD_EXECUTABLES:
        found = shutil.which(name)
        if found:
            return found
    return None


def higgsfield_installed() -> bool:
    return higgsfield_executable() is not None


def _creationflags() -> int:
    """Flags de criacao do subprocesso (regra do AGENTS.md / windows-processos).

    `CREATE_NEW_PROCESS_GROUP` isola o CLI dos sinais da consola (um Ctrl+C no
    MobaXterm/PowerShell nao pode matar a geracao a meio) e `CREATE_NO_WINDOW`
    garante que nao aparece nenhuma janela de consola ao utilizador. Nada de
    `detached`, nada de `stdio: "inherit"`: a saida vai por pipe para o log.
    """
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def _environment() -> dict[str, str]:
    """Ambiente do filho: UTF-8 forcado (regra 3 do AGENTS.md, sem mojibake)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["NO_COLOR"] = "1"
    return env


def _run(args: Sequence[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    """Corre o CLI sem consola, com tempo limite e saida capturada.

    Uma excepcao de tempo limite ou de arranque do processo torna-se
    `HiggsfieldError` (mensagem legivel), para a UI nunca mostrar um traceback.
    """
    executable = higgsfield_executable()
    if executable is None:
        raise HiggsfieldError("CLI do Higgsfield não encontrado no PATH.")
    try:
        return subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=_environment(),
            creationflags=_creationflags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise HiggsfieldError(
            f"O comando do Higgsfield não respondeu em {timeout}s: {' '.join(args)}"
        ) from exc
    except OSError as exc:
        raise HiggsfieldError(f"Não foi possível executar o CLI do Higgsfield: {exc}") from exc


def _output(completed: subprocess.CompletedProcess[str]) -> str:
    return f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()


def _parse_json(text: str) -> Any:
    """Le a saida `--json` do CLI; devolve None se nao for JSON."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # O CLI pode imprimir linhas de aviso antes do JSON: procuro o primeiro
        # objecto/array completo.
        start = min(
            (index for index in (raw.find("{"), raw.find("[")) if index >= 0),
            default=-1,
        )
        if start < 0:
            return None
        try:
            return json.loads(raw[start:])
        except json.JSONDecodeError:
            return None


def _first(payload: Any, *keys: str) -> Any:
    """Primeiro valor presente num dicionario (as chaves variam por comando)."""
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _looks_unauthenticated(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in ("not authenticated", "session expired", "auth login", "unauthorized"))


def _normalize_job(payload: Any, *, fallback_id: str = "") -> dict[str, Any]:
    """Forma comum de um job para a UI, sem depender de um nome de campo único."""
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    job_id = _first(payload, *_JOB_ID_KEYS) or fallback_id
    status = str(_first(payload, "status", "state") or "").lower()
    url = _first(payload, "result_url", "url", "output_url", "video_url", "image_url")
    return {
        "id": str(job_id or ""),
        "status": status,
        "url": str(url or ""),
        "done": status in HIGGSFIELD_DONE_STATUSES,
        "terminal": status in HIGGSFIELD_TERMINAL_STATUSES,
        "raw": payload,
    }


def auth_status() -> dict[str, Any]:
    """Estado do CLI e da autenticacao (nunca lanca: a UI mostra o resultado)."""
    executable = higgsfield_executable()
    if executable is None:
        return {
            "installed": False,
            "authenticated": False,
            "command": "higgsfield account status",
            "detail": "CLI do Higgsfield não encontrado no PATH.",
            "instructions": HIGGSFIELD_INSTALL_INSTRUCTIONS,
        }
    try:
        completed = _run(["account", "status", "--json"])
    except HiggsfieldError as exc:
        return {
            "installed": True,
            "authenticated": False,
            "command": "higgsfield account status",
            "detail": str(exc),
            "instructions": HIGGSFIELD_LOGIN_INSTRUCTIONS,
        }
    payload = _parse_json(completed.stdout)
    detail = _output(completed)[:400]
    authenticated = completed.returncode == 0 and not _looks_unauthenticated(detail)
    if isinstance(payload, Mapping):
        authenticated = authenticated and bool(payload.get("authenticated", True))
        detail = str(_first(payload, "message", "detail", "email", "workspace") or detail)
    return {
        "installed": True,
        "authenticated": authenticated,
        "command": "higgsfield account status",
        "detail": detail,
        "instructions": HIGGSFIELD_LOGIN_INSTRUCTIONS if not authenticated else "",
    }


def _require_ready() -> dict[str, Any]:
    """Garante CLI instalado e sessao autenticada antes de gerar."""
    status = auth_status()
    if not status["installed"]:
        raise HiggsfieldError(status["detail"] + "\n\n" + HIGGSFIELD_INSTALL_INSTRUCTIONS)
    if not status["authenticated"]:
        raise HiggsfieldError(
            "Sessão do Higgsfield não autenticada.\n\n" + HIGGSFIELD_LOGIN_INSTRUCTIONS
        )
    return status


def _media_flags(values: Any, flag: str) -> list[str]:
    """`--image/--video/--audio` repetidos, de caminhos ou UUIDs já enviados.

    Uma flag de media aceita caminho local (o CLI faz o upload) ou um UUID
    (`higgsfield upload create`, ou o id de um job anterior).
    """
    flags: list[str] = []
    if values in (None, ""):
        return flags
    items = values if isinstance(values, (list, tuple)) else [values]
    name = f"--{str(flag).lstrip('-')}"
    for item in items:
        text = str(item or "").strip()
        if text:
            flags.extend([name, text])
    return flags


def _extra_flags(params: Mapping[str, Any] | None) -> list[str]:
    """Parametros livres do modelo (`--aspect_ratio 16:9`, `--duration 5`, ...)."""
    flags: list[str] = []
    for key, value in (params or {}).items():
        if value in (None, ""):
            continue
        flags.extend([f"--{str(key).lstrip('-')}", str(value)])
    return flags


def submit_generation(
    job_set_type: str,
    *,
    prompt: str = "",
    image: Any = None,
    video: Any = None,
    audio: Any = None,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Cria um job de geracao e devolve-o SEM esperar (a UI faz o polling).

    Levanta `HiggsfieldError` se o CLI faltar, a sessao nao estiver autenticada
    ou o CLI recusar o pedido.
    """
    _require_ready()
    model = str(job_set_type or "").strip()
    if not model:
        raise HiggsfieldError("Indique o modelo do Higgsfield (job set type).")
    args = ["generate", "create", model, "--json"]
    if str(prompt or "").strip():
        args.extend(["--prompt", str(prompt).strip()])
    args.extend(_media_flags(image, "image"))
    args.extend(_media_flags(video, "video"))
    args.extend(_media_flags(audio, "audio"))
    args.extend(_extra_flags(params))
    completed = _run(args)
    if completed.returncode != 0:
        raise HiggsfieldError(_output(completed) or "O CLI do Higgsfield recusou o pedido.")
    payload = _parse_json(completed.stdout)
    if payload is None:
        raise HiggsfieldError("O CLI não devolveu JSON. Saída: " + _output(completed)[:300])
    return _normalize_job(payload)


def get_generation(job_id: str) -> dict[str, Any]:
    """Le um job (usado pelo polling da UI)."""
    identifier = str(job_id or "").strip()
    if not identifier:
        raise HiggsfieldError("Job do Higgsfield sem identificador.")
    completed = _run(["generate", "get", identifier, "--json"])
    if completed.returncode != 0:
        raise HiggsfieldError(_output(completed) or "Não foi possível ler o job.")
    payload = _parse_json(completed.stdout)
    if payload is None:
        raise HiggsfieldError("O CLI não devolveu JSON. Saída: " + _output(completed)[:300])
    return _normalize_job(payload, fallback_id=identifier)


def wait_generation(job_id: str, *, timeout_seconds: int = WAIT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Espera por um job com o proprio `--wait` do CLI (boundado)."""
    identifier = str(job_id or "").strip()
    if not identifier:
        raise HiggsfieldError("Job do Higgsfield sem identificador.")
    completed = _run(
        ["generate", "wait", identifier, "--json", "--wait-timeout", f"{max(1, int(timeout_seconds))}s"],
        timeout=timeout_seconds + COMMAND_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise HiggsfieldError(_output(completed) or "A espera do job falhou.")
    payload = _parse_json(completed.stdout)
    if payload is None:
        raise HiggsfieldError("O CLI não devolveu JSON. Saída: " + _output(completed)[:300])
    return _normalize_job(payload, fallback_id=identifier)


def list_generations() -> list[dict[str, Any]]:
    """Jobs recentes (para a UI mostrar o histórico)."""
    completed = _run(["generate", "list", "--json"])
    if completed.returncode != 0:
        raise HiggsfieldError(_output(completed) or "Não foi possível listar os jobs.")
    payload = _parse_json(completed.stdout)
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        payload = _first(payload, "items", "jobs", "results", "data") or []
    if not isinstance(payload, list):
        return []
    return [_normalize_job(item) for item in payload if isinstance(item, Mapping)]


def submit_product_photoshoot(
    *,
    mode: str,
    prompt: str = "",
    image: Any = None,
    count: int | None = None,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Skill `product-photoshoot`: imagens de produto com realce por modo.

    Modos verificados na skill: `product_shot`, `lifestyle_scene`,
    `closeup_product_with_person`, `moodboard_pin`, `hero_banner`,
    `social_carousel`, `ad_creative_pack`, `virtual_model_tryout`,
    `conceptual_product`, `restyle`.
    """
    _require_ready()
    selected = str(mode or "").strip() or "product_shot"
    args = ["product-photoshoot", "create", "--mode", selected, "--json"]
    if str(prompt or "").strip():
        args.append(str(prompt).strip())
    media = _media_flags(image, "image")
    if media:
        args.extend(media)
    if count:
        args.extend(["--count", str(int(count))])
    args.extend(_extra_flags(params))
    completed = _run(args)
    if completed.returncode != 0:
        raise HiggsfieldError(_output(completed) or "O photoshoot de produto falhou.")
    payload = _parse_json(completed.stdout)
    if payload is None:
        raise HiggsfieldError("O CLI não devolveu JSON. Saída: " + _output(completed)[:300])
    return _normalize_job(payload)


def train_soul(
    *,
    name: str,
    images: Sequence[Any],
    variant: str = "soul-2",
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Skill `soul-id`: treina um personagem com 5-20 fotos do rosto.

    `variant` pode ser `soul-2` (imagem, por omissão) ou `soul-cinematic`
    (video), conforme a skill.
    """
    _require_ready()
    character = str(name or "").strip()
    if not character:
        raise HiggsfieldError("Dê um nome ao personagem.")
    media = _media_flags(list(images or []), "image")
    if not media:
        raise HiggsfieldError("Envie entre 5 e 20 fotos do rosto para treinar o personagem.")
    selected = str(variant or "").strip() or "soul-2"
    args = ["soul-id", "create", "--name", character, f"--{selected}", "--json"]
    args.extend(media)
    args.extend(_extra_flags(params))
    completed = _run(args)
    if completed.returncode != 0:
        raise HiggsfieldError(_output(completed) or "O treino do personagem falhou.")
    payload = _parse_json(completed.stdout)
    if payload is None:
        raise HiggsfieldError("O CLI não devolveu JSON. Saída: " + _output(completed)[:300])
    return _normalize_job(payload)


def wait_soul(reference_id: str, *, timeout_seconds: int = WAIT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Espera pelo treino de um personagem (a skill usa timeout de 30 min)."""
    identifier = str(reference_id or "").strip()
    if not identifier:
        raise HiggsfieldError("Personagem sem identificador.")
    completed = _run(
        ["soul-id", "wait", identifier, "--wait-timeout", f"{max(1, int(timeout_seconds))}s"],
        timeout=timeout_seconds + COMMAND_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise HiggsfieldError(_output(completed) or "A espera do personagem falhou.")
    payload = _parse_json(completed.stdout)
    if payload is None:
        raise HiggsfieldError("O CLI não devolveu JSON. Saída: " + _output(completed)[:300])
    return _normalize_job(payload, fallback_id=identifier)


def list_souls() -> list[dict[str, Any]]:
    """Personagens treinados (`higgsfield soul-id list`)."""
    completed = _run(["soul-id", "list", "--json"])
    if completed.returncode != 0:
        raise HiggsfieldError(_output(completed) or "Não foi possível listar os personagens.")
    payload = _parse_json(completed.stdout)
    if isinstance(payload, Mapping):
        payload = _first(payload, "items", "souls", "references", "results", "data") or []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, Mapping)]


def submit_media_upload(path: str | Path) -> dict[str, Any]:
    """Envia um ficheiro e devolve o identificador (o CLI tambem auto-upload)."""
    target = Path(path)
    if not target.is_file():
        raise HiggsfieldError(f"Ficheiro não encontrado: {target}")
    completed = _run(["upload", "create", str(target), "--json"], timeout=COMMAND_TIMEOUT_SECONDS * 3)
    if completed.returncode != 0:
        raise HiggsfieldError(_output(completed) or "O upload falhou.")
    payload = _parse_json(completed.stdout)
    if payload is None:
        raise HiggsfieldError("O CLI não devolveu JSON. Saída: " + _output(completed)[:300])
    return {"id": str(_first(payload, *_JOB_ID_KEYS) or ""), "url": str(_first(payload, "url") or ""), "raw": payload}