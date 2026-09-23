from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from hermes_ui.storage import STORAGE

try:
    import kagglehub
except ImportError:  # pragma: no cover - exercised in installations before the extra dependency is installed
    kagglehub = None


DATA_DIR = STORAGE / "data" / "niches"
DEFAULT_DATASET_SLUG = "asaniczka/trending-youtube-videos-113-countries"
DEFAULT_DATASET_FILENAME = "trending_yt_videos_113_countries.csv"
DEFAULT_DATASET_PATH = DATA_DIR / DEFAULT_DATASET_FILENAME

REQUIRED_COLUMNS = (
    "title",
    "publish_date",
    "country",
    "view_count",
    "like_count",
    "comment_count",
)
OPTIONAL_COLUMNS = (
    "video_tags",
    "channel_name",
    "thumbnail_url",
    "video_id",
    "channel_id",
)


class DatasetError(RuntimeError):
    """Raised when the automatic Niche Finder dataset cannot be read or validated."""


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def _find_csv(root: Path) -> Path | None:
    candidates = sorted(root.rglob("*.csv"))
    if not candidates:
        return None
    for candidate in candidates:
        if candidate.name.lower() == DEFAULT_DATASET_FILENAME.lower():
            return candidate
    return candidates[0]


def _copy_csv(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return destination


def _has_usable_cached_dataset() -> bool:
    """Check only the header so a valid multi-gigabyte cache is not read twice."""
    if not DEFAULT_DATASET_PATH.exists() or DEFAULT_DATASET_PATH.stat().st_size <= 0:
        return False
    try:
        columns = set(pd.read_csv(DEFAULT_DATASET_PATH, nrows=0).columns)
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return False
    return set(REQUIRED_COLUMNS).issubset(columns)


def _download_with_kagglehub() -> Path | None:
    if kagglehub is None:
        return None
    ensure_data_dir()
    # KaggleHub rejects a non-empty output_dir on Windows. Use a new temporary
    # directory for every download, then copy only the validated CSV into the
    # persistent Thunderbolt cache. This also isolates partial downloads.
    with tempfile.TemporaryDirectory(prefix=".niche-kaggle-", dir=str(DATA_DIR.parent)) as temporary_root:
        temporary_path = Path(temporary_root)
        try:
            try:
                downloaded = kagglehub.dataset_download(
                    DEFAULT_DATASET_SLUG,
                    output_dir=str(temporary_path),
                    force_download=True,
                )
            except TypeError:  # compatibility with older KaggleHub releases
                downloaded = kagglehub.dataset_download(
                    DEFAULT_DATASET_SLUG,
                    output_dir=str(temporary_path),
                )
        except Exception as exc:  # pragma: no cover - depends on network/provider state
            raise DatasetError(f"O Thunderbolt não conseguiu preparar os dados automáticos: {exc}") from exc
        source = _find_csv(Path(downloaded))
        if source is None:
            raise DatasetError("A preparação automática terminou sem encontrar dados compatíveis.")
        return _copy_csv(source, DEFAULT_DATASET_PATH)


def download_kaggle_dataset() -> Path:
    """Prepare and cache the public Niche-Finder dataset after an explicit user action."""
    ensure_data_dir()
    if _has_usable_cached_dataset():
        return DEFAULT_DATASET_PATH
    if kagglehub is None:
        raise DatasetError("O componente automático de dados não está disponível nesta instalação.")
    downloaded = _download_with_kagglehub()
    if downloaded is None:
        raise DatasetError("O componente automático de dados não devolveu um caminho válido.")
    return downloaded


def validate_dataset(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the internal dataset schema and return a normalised copy."""
    if frame is None or frame.empty:
        raise DatasetError("A fonte automática de dados não contém registos.")
    cleaned = frame.copy()
    cleaned.columns = [str(column).strip() for column in cleaned.columns]
    missing = [column for column in REQUIRED_COLUMNS if column not in cleaned.columns]
    if missing:
        raise DatasetError("A fonte automática não contém as colunas necessárias: " + ", ".join(missing) + ".")
    if "video_tags" not in cleaned.columns:
        cleaned["video_tags"] = ""
    for column in ("view_count", "like_count", "comment_count"):
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
    cleaned["publish_date"] = pd.to_datetime(cleaned["publish_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    cleaned["country"] = cleaned["country"].astype("string").str.strip()
    cleaned["title"] = cleaned["title"].astype("string").fillna("").str.strip()
    cleaned = cleaned.dropna(subset=["publish_date", "view_count", "like_count", "comment_count"])
    cleaned = cleaned[cleaned["title"] != ""].copy()
    if cleaned.empty:
        raise DatasetError("A fonte automática não contém registos válidos depois da normalização.")
    return cleaned.reset_index(drop=True)


def load_dataframe(path: str | Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path)
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise DatasetError(f"Não foi possível ler a fonte automática de dados: {exc}") from exc
    return validate_dataset(frame)


def load_analysis_data(
    use_remote: bool = True,
    username: str | None = None,
    api_key: str | None = None,
    kernel_slug: str | None = None,
    force_rerun: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Load Niche Finder results from Kaggle by default or from the local path."""
    if use_remote:
        from .kaggle_runner import run_niche_analysis_remotely

        return run_niche_analysis_remotely(
            username=username or "",
            api_key=api_key or "",
            kernel_slug=kernel_slug or "",
            output_dir=STORAGE / "data" / "niches" / "kaggle_results",
            force_rerun=force_rerun,
            n_clusters=int(kwargs.get("n_clusters", 5)),
            min_support=float(kwargs.get("min_support", 0.05)),
        )
    dataset_path = kwargs.pop("dataset_path", None)
    if not dataset_path:
        raise DatasetError("Indique um dataset_path para a análise local.")
    from .core import run_niche_analysis

    return run_niche_analysis(dataset_path, **kwargs)
