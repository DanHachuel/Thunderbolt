from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd

from .models import NicheAnalysisResult
from .errors import KaggleNicheError

logger = logging.getLogger(__name__)
KERNEL_DIR = Path(__file__).parent / "kaggle_kernel"
DEFAULT_TIMEOUT_MIN = 20
POLL_INTERVAL_SEC = 15
OUTPUT_FILENAMES = ("clusters.csv", "frequent_items.csv", "association_rules.csv")
_KAGGLE_IDENTIFIER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$")


def _required_credentials(username: str, api_key: str, kernel_slug: str) -> tuple[str, str, str]:
    values = (str(username or "").strip(), str(api_key or "").strip(), str(kernel_slug or "").strip())
    modern_token = values[1].startswith("KGAT_")
    if not values[1] or not values[2] or (not values[0] and not modern_token):
        raise KaggleNicheError("Preencha a API key/token e o slug da kernel; o username é obrigatório para chave legada e opcional para token KGAT_.")
    if (values[0] and not _KAGGLE_IDENTIFIER_RE.fullmatch(values[0])) or not _KAGGLE_IDENTIFIER_RE.fullmatch(values[2]):
        raise KaggleNicheError("Username e slug devem conter apenas letras minúsculas, números e hífens, com até 50 caracteres e sem hífen inicial/final.")
    return values


def _status_value(status: Any) -> str:
    if isinstance(status, dict):
        return str(status.get("status") or "").strip().lower()
    return str(getattr(status, "status", status) or "").strip().lower()


def _exception_status_code(exc: BaseException) -> int | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None) or getattr(current, "status_code", None)
        try:
            code = int(status)
        except (TypeError, ValueError):
            code = 0
        if 100 <= code <= 599:
            return code
        current = current.__cause__ or current.__context__
    return None


def _load_kaggle_api():
    """Import the SDK only for an explicit action; Kaggle 2.x authenticates on package import."""
    from kaggle.api.kaggle_api_extended import KaggleApi

    return KaggleApi


def _authenticated_username(api: Any) -> str:
    """Return the username established by modern access-token authentication."""
    config_values = getattr(api, "config_values", {})
    if isinstance(config_values, dict):
        config_key = str(getattr(api, "CONFIG_NAME_USER", "username"))
        value = config_values.get(config_key) or config_values.get("username")
    else:
        value = getattr(config_values, "username", "")
    return str(value or "").strip()


class KaggleNicheRunner:
    def __init__(self, username: str, api_key: str, kernel_slug: str):
        username, api_key, kernel_slug = _required_credentials(username, api_key, kernel_slug)
        self.username = username
        self.kernel_slug = kernel_slug
        self.kernel_ref = f"{username}/{kernel_slug}" if username else ""
        config_dir = Path(tempfile.mkdtemp(prefix="thunderbolt-kaggle-config-"))
        self.config_dir = config_dir
        os.environ["KAGGLE_CONFIG_DIR"] = str(config_dir)
        # Kaggle 2.x tries KAGGLE_API_TOKEN before legacy credentials. Keep the
        # two formats distinct; a legacy API key must not be sent as a bearer token.
        if api_key.startswith("KGAT_"):
            os.environ["KAGGLE_API_TOKEN"] = api_key
            os.environ.pop("KAGGLE_USERNAME", None)
            os.environ.pop("KAGGLE_KEY", None)
        else:
            os.environ.pop("KAGGLE_API_TOKEN", None)
            os.environ["KAGGLE_USERNAME"] = username
            os.environ["KAGGLE_KEY"] = api_key
        try:
            KaggleApi = _load_kaggle_api()
        except ImportError as exc:  # pragma: no cover - depends on installation extras
            raise KaggleNicheError("A biblioteca Python kaggle não está instalada nesta instalação.") from exc
        try:
            self.api = KaggleApi()
            self.api.authenticate()
        except SystemExit as exc:
            logger.exception("O SDK Kaggle terminou a autenticação para %s", username)
            raise KaggleNicheError("A autenticação Kaggle falhou. Verifique o username e a API key ou token configurados.") from exc
        except Exception as exc:
            logger.exception("Falha na autenticação Kaggle para %s", username)
            raise KaggleNicheError("A autenticação Kaggle falhou. Verifique o username e a API key ou token configurados.") from exc
        if not self.username:
            self.username = _authenticated_username(self.api)
            if not _KAGGLE_IDENTIFIER_RE.fullmatch(self.username):
                raise KaggleNicheError("O token moderno não forneceu um username Kaggle válido para localizar a kernel.")
            self.kernel_ref = f"{self.username}/{self.kernel_slug}"

    def test_connection(self) -> bool:
        try:
            self.api.kernels_list(user=self.username, page_size=1)
            return True
        except Exception:
            logger.exception("Falha ao testar a ligação Kaggle para %s", self.username)
            return False

    def _staged_kernel(self, n_clusters: int, min_support: float) -> tempfile.TemporaryDirectory:
        temporary = tempfile.TemporaryDirectory(prefix=".thunderbolt-kaggle-")
        destination = Path(temporary.name)
        script = (KERNEL_DIR / "script.py").read_text(encoding="utf-8")
        script = script.replace(
            'N_CLUSTERS = int(os.environ.get("NICHE_N_CLUSTERS", "5"))',
            f"N_CLUSTERS = {int(n_clusters)}",
        ).replace(
            'MIN_SUPPORT = float(os.environ.get("NICHE_MIN_SUPPORT", "0.05"))',
            f"MIN_SUPPORT = {float(min_support)!r}",
        )
        (destination / "script.py").write_text(script, encoding="utf-8")
        metadata = json.loads((KERNEL_DIR / "kernel-metadata.json").read_text(encoding="utf-8"))
        # The checked-in template uses the public default; always overwrite it with the runtime owner/slug.
        metadata["id"] = self.kernel_ref
        (destination / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        return temporary

    def push(self, *, n_clusters: int = 5, min_support: float = 0.05) -> None:
        with self._staged_kernel(n_clusters, min_support) as staged:
            self.api.kernels_push(str(staged))

    def wait(self, timeout_minutes: int = DEFAULT_TIMEOUT_MIN) -> str:
        deadline = time.monotonic() + max(1, int(timeout_minutes)) * 60
        while time.monotonic() < deadline:
            try:
                state = _status_value(self.api.kernels_status(self.kernel_ref))
            except Exception as exc:
                status_code = _exception_status_code(exc)
                detail = str(exc).lower()
                if status_code == 404:
                    logger.warning("Kernel Kaggle %s não encontrada (HTTP 404)", self.kernel_ref, exc_info=True)
                    raise KaggleNicheError(f"A kernel Kaggle '{self.kernel_ref}' não foi encontrada. Confirme o slug.") from exc
                if status_code in {401, 403} or "cannot access kernel" in detail:
                    logger.warning("Kaggle recusou acesso à kernel %s", self.kernel_ref, exc_info=True)
                    raise KaggleNicheError(f"Sem acesso à kernel '{self.kernel_ref}'. Verifique o slug, a visibilidade e a permissão kernels.get.") from exc
                logger.warning("Falha ao consultar o estado da kernel Kaggle %s", self.kernel_ref, exc_info=True)
                state = "unknown"
            logger.info("Kaggle kernel %s: %s", self.kernel_ref, state or "unknown")
            if state in {"complete", "completed"}:
                return "complete"
            if state in {"error", "failed", "cancelled", "canceled"}:
                raise KaggleNicheError(f"A kernel Kaggle terminou com estado: {state}.")
            time.sleep(POLL_INTERVAL_SEC)
        raise KaggleNicheError(f"A análise Kaggle excedeu o limite de {timeout_minutes} minutos.")

    def download_outputs(self, output_dir: Path) -> dict[str, pd.DataFrame]:
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.api.kernels_output(self.kernel_ref, path=str(output_dir), force=True)
        except TypeError:
            self.api.kernels_output(self.kernel_ref, path=str(output_dir))
        missing = [name for name in OUTPUT_FILENAMES if not (output_dir / name).is_file()]
        if missing:
            raise KaggleNicheError("A kernel terminou sem devolver: " + ", ".join(missing) + ".")
        try:
            return {name.removesuffix(".csv"): pd.read_csv(output_dir / name) for name in OUTPUT_FILENAMES}
        except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
            raise KaggleNicheError(f"Não foi possível ler os resultados descarregados: {exc}") from exc


def _cache_metadata_path(output_dir: Path) -> Path:
    return output_dir / "metadata.json"


def _cached_results(output_dir: Path, cache_key: dict[str, Any]) -> dict[str, pd.DataFrame] | None:
    metadata_path = _cache_metadata_path(output_dir)
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if metadata != cache_key or any(not (output_dir / name).is_file() for name in OUTPUT_FILENAMES):
        return None
    try:
        return {name.removesuffix(".csv"): pd.read_csv(output_dir / name) for name in OUTPUT_FILENAMES}
    except (OSError, UnicodeDecodeError, pd.errors.ParserError):
        return None


def _as_result(frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    clusters = frames["clusters"]
    frequent = frames["frequent_items"]
    rules = frames["association_rules"]
    rows_analyzed = int(clusters["tamanho"].sum()) if "tamanho" in clusters.columns else 0
    summary = {
        "rows_input": rows_analyzed,
        "rows_filtered": rows_analyzed,
        "cluster_count": int(len(clusters)),
        "frequent_item_count": int(len(frequent)),
        "association_rule_count": int(len(rules)),
        "top_tags": [str(value) for value in frequent.get("itemsets", pd.Series(dtype=str)).head(10).tolist()],
        "source": "Kaggle remote kernel",
    }
    return NicheAnalysisResult(
        clusters=clusters,
        frequent_items=frequent,
        association_rules=rules,
        raw_data=pd.DataFrame(),
        cluster_points=pd.DataFrame(),
        summary=summary,
    ).as_dict()


def run_niche_analysis_remotely(
    username: str,
    api_key: str,
    kernel_slug: str,
    output_dir: str | Path,
    *,
    n_clusters: int = 5,
    min_support: float = 0.05,
    force_rerun: bool = False,
    timeout_minutes: int = DEFAULT_TIMEOUT_MIN,
) -> dict[str, Any]:
    username, api_key, kernel_slug = _required_credentials(username, api_key, kernel_slug)
    if not 2 <= int(n_clusters) <= 10:
        raise KaggleNicheError("O número de clusters deve estar entre 2 e 10.")
    if not 0.001 <= float(min_support) <= 0.5:
        raise KaggleNicheError("O suporte mínimo deve estar entre 0,001 e 0,5.")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    cache_key = {
        "username": username,
        "kernel_slug": kernel_slug,
        "n_clusters": int(n_clusters),
        "min_support": float(min_support),
    }
    if not force_rerun:
        cached = _cached_results(destination, cache_key)
        if cached is not None:
            return _as_result(cached)
    runner = KaggleNicheRunner(username, api_key, kernel_slug)
    runner.push(n_clusters=n_clusters, min_support=min_support)
    runner.wait(timeout_minutes=timeout_minutes)
    frames = runner.download_outputs(destination)
    _cache_metadata_path(destination).write_text(json.dumps(cache_key, indent=2) + "\n", encoding="utf-8")
    return _as_result(frames)
