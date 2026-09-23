from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd

from .models import NicheAnalysisResult

try:
    from kaggle.api.kaggle_api_extended import KaggleApi
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    KaggleApi = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)
KERNEL_DIR = Path(__file__).parent / "kaggle_kernel"
DEFAULT_TIMEOUT_MIN = 20
POLL_INTERVAL_SEC = 15
OUTPUT_FILENAMES = ("clusters.csv", "frequent_items.csv", "association_rules.csv")


class KaggleNicheError(RuntimeError):
    """Raised when the remote Kaggle Niche Finder cannot complete."""


def _required_credentials(username: str, api_key: str, kernel_slug: str) -> tuple[str, str, str]:
    values = (str(username or "").strip(), str(api_key or "").strip(), str(kernel_slug or "").strip())
    if not all(values):
        raise KaggleNicheError("Preencha Kaggle Username, Kaggle API Key e Slug da kernel para continuar.")
    if any(char in values[0] for char in " /\\") or any(char in values[2] for char in " /\\"):
        raise KaggleNicheError("Username e slug da kernel devem ser identificadores simples, sem URL ou caminho.")
    return values


def _status_value(status: Any) -> str:
    if isinstance(status, dict):
        return str(status.get("status") or "").strip().lower()
    return str(getattr(status, "status", status) or "").strip().lower()


class KaggleNicheRunner:
    def __init__(self, username: str, api_key: str, kernel_slug: str):
        username, api_key, kernel_slug = _required_credentials(username, api_key, kernel_slug)
        if KaggleApi is None:
            raise KaggleNicheError("A biblioteca Python kaggle não está instalada nesta instalação.")
        self.username = username
        self.kernel_slug = kernel_slug
        self.kernel_ref = f"{username}/{kernel_slug}"
        os.environ["KAGGLE_USERNAME"] = username
        os.environ["KAGGLE_KEY"] = api_key
        os.environ["KAGGLE_API_TOKEN"] = api_key
        self.api = KaggleApi()
        try:
            self.api.authenticate()
        except Exception as exc:
            raise KaggleNicheError(f"Falha na autenticação Kaggle: {exc}") from exc

    def test_connection(self) -> bool:
        try:
            self.api.kernels_list(user=self.username, page_size=1)
            return True
        except Exception as exc:
            logger.warning("Falha ao testar a ligação Kaggle: %s", exc)
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
                logger.info("Não foi possível ler o estado da kernel: %s", exc)
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
