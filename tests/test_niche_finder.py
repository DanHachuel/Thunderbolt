from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

from app.modules.niche_finder.core import run_niche_analysis
from app.modules.niche_finder.data_loader import DatasetError, load_dataframe


pytestmark = pytest.mark.filterwarnings("ignore::FutureWarning")


def test_niche_finder_requires_explicit_analysis_submit():
    source_path = Path(__file__).parents[1] / "app" / "main.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "render_niche_finder")
    function_source = ast.get_source_segment(source_path.read_text(encoding="utf-8"), function)

    assert function_source is not None
    assert "with st.sidebar" not in function_source
    assert 'st.form_submit_button("Analisar Nichos"' in function_source
    assert "if analyse:" in function_source
    assert "load_analysis_data(" in function_source
    assert "use_remote=True" in function_source
    assert "A kernel é publicada e executada remotamente" in function_source



@pytest.fixture
def niche_csv(tmp_path):
    rows = []
    tag_groups = [
        "history|facts|war",
        "history|facts|ancient",
        "history|war|documentary",
        "gaming|review|games",
        "gaming|games|console",
        "gaming|review|pc",
        "cooking|recipes|food",
        "cooking|recipes|easy",
        "cooking|food|dinner",
        "history|facts|war",
        "gaming|games|console",
        "cooking|recipes|food",
    ]
    for index, tags in enumerate(tag_groups):
        rows.append(
            {
                "title": f"Video {index}",
                "publish_date": f"2025-01-{index + 1:02d}",
                "country": "US" if index < 9 else "BR",
                "view_count": 1000 + index * 100,
                "like_count": 100 + index * 10,
                "comment_count": 10 + index,
                "video_tags": tags,
                "channel_name": f"Channel {index % 3}",
            }
        )
    path = tmp_path / "niche.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_loader_requires_core_columns(tmp_path):
    path = tmp_path / "invalid.csv"
    pd.DataFrame([{"title": "Only title"}]).to_csv(path, index=False)
    with pytest.raises(DatasetError, match="colunas necessárias"):
        load_dataframe(path)


def test_run_niche_analysis_returns_dataframes_and_filters(niche_csv):
    pytest.importorskip("sklearn")
    pytest.importorskip("mlxtend")
    result = run_niche_analysis(
        str(niche_csv),
        n_clusters=3,
        min_support=0.1,
        start_date="2025-01-01",
        end_date="2025-01-09",
        country="US",
        engagement="Todos",
    )
    assert set(["clusters", "frequent_items", "association_rules", "raw_data", "cluster_points", "summary"]).issubset(result)
    assert isinstance(result["clusters"], pd.DataFrame)
    assert isinstance(result["frequent_items"], pd.DataFrame)
    assert isinstance(result["association_rules"], pd.DataFrame)
    assert isinstance(result["raw_data"], pd.DataFrame)
    assert len(result["raw_data"]) == 9
    assert 1 <= len(result["clusters"]) <= 3
    assert result["summary"]["rows_filtered"] == 9


def _write_minimal_cached_dataset(path):
    pd.DataFrame(
        [
            {
                "title": "Cached video",
                "publish_date": "2025-01-01",
                "country": "US",
                "view_count": 100,
                "like_count": 10,
                "comment_count": 1,
                "video_tags": "cache|test",
            }
        ]
    ).to_csv(path, index=False)


def test_automatic_loader_reuses_valid_existing_cache(tmp_path, monkeypatch):
    from app.modules.niche_finder import data_loader

    data_dir = tmp_path / "storage" / "data" / "niches"
    data_dir.mkdir(parents=True)
    cached_path = data_dir / data_loader.DEFAULT_DATASET_FILENAME
    _write_minimal_cached_dataset(cached_path)
    monkeypatch.setattr(data_loader, "DATA_DIR", data_dir)
    monkeypatch.setattr(data_loader, "DEFAULT_DATASET_PATH", cached_path)

    class UnexpectedKaggleHub:
        def dataset_download(self, *args, **kwargs):
            raise AssertionError("KaggleHub não deveria ser chamado para uma cache válida")

    monkeypatch.setattr(data_loader, "kagglehub", UnexpectedKaggleHub())
    assert data_loader.download_kaggle_dataset() == cached_path


def test_automatic_loader_downloads_into_empty_temporary_directory(tmp_path, monkeypatch):
    from app.modules.niche_finder import data_loader

    data_dir = tmp_path / "storage" / "data" / "niches"
    data_dir.mkdir(parents=True)
    cached_path = data_dir / data_loader.DEFAULT_DATASET_FILENAME
    monkeypatch.setattr(data_loader, "DATA_DIR", data_dir)
    monkeypatch.setattr(data_loader, "DEFAULT_DATASET_PATH", cached_path)
    calls = []

    class FakeKaggleHub:
        def dataset_download(self, slug, *, output_dir, force_download):
            output = Path(output_dir)
            calls.append((slug, output, force_download))
            assert output.exists()
            assert list(output.iterdir()) == []
            assert force_download is True
            source = output / data_loader.DEFAULT_DATASET_FILENAME
            _write_minimal_cached_dataset(source)
            return str(output)

    from pathlib import Path

    monkeypatch.setattr(data_loader, "kagglehub", FakeKaggleHub())
    result = data_loader.download_kaggle_dataset()
    assert result == cached_path
    assert cached_path.exists()
    assert calls[0][0] == data_loader.DEFAULT_DATASET_SLUG
    assert not list(data_dir.parent.glob(".niche-kaggle-*"))


def test_niche_finder_navigation_has_kaggle_and_apify_pages():
    source_path = Path(__file__).parents[1] / "app" / "main.py"
    source = source_path.read_text(encoding="utf-8")

    assert 'niche_finder_items = [' in source
    assert '("Niche Finder Kaggle", ":material/search:", "Niche Finder Kaggle")' in source
    assert '("Niche Finder Apify", ":material/api:", "Niche Finder Apify")' in source
    assert '"Niche Finder Kaggle": render_niche_finder' in source
    assert '"Niche Finder Apify": render_niche_finder_apify' in source
    assert source.index('("Niche Finder Kaggle"') < source.index('("Niche Finder Apify"')
    assert 'st.title("Niche Finder Apify")' in source
    assert 'st.form_submit_button("Pesquisar no Apify"' in source
    assert 'Ainda não existe uma pesquisa nesta sessão' in source


def test_edition_navigation_has_cleaner_cuts_and_python_editor():
    source_path = Path(__file__).parents[1] / "app" / "main.py"
    source = source_path.read_text(encoding="utf-8")

    assert 'edition_items = [' in source
    assert '("Limpador de Metadados", ":material/edit_note:", "Limpador de Metadados")' in source
    assert '("Cortes", ":material/content_cut:", "Cortes")' in source
    assert '("Editor Python", ":material/code:", "Editor Python")' in source
    assert source.index('("Limpador de Metadados", ":material/edit_note:') < source.index('("Cortes", ":material/content_cut:') < source.index('("Editor Python", ":material/code:')
    assert '"Edição": lambda: render_edit_placeholder("Edição"' in source
    assert '"Cortes": render_cuts' in source
    assert 'def render_cuts()' in source
    assert 'Gerar Clips' in source
    assert '"Editor Python": render_python_editor' in source


def test_ai_influencers_navigation_has_characters_and_social_pages():
    source_path = Path(__file__).parents[1] / "app" / "main.py"
    source = source_path.read_text(encoding="utf-8")

    assert 'models_ai_items = [' in source
    assert '("Personagens", ":material/person:", "Personagens")' in source
    assert '("Contas Instagram", ":material/share:", "Contas Instagram")' in source
    channel_start = source.index("channel_profile_items = [")
    channel_end = source.index("    ]", channel_start)
    assert channel_start < source.index('("Contas Instagram", ":material/share:') < channel_end
    assert '("AI Influencers", ":material/smart_toy:", "AI Influencers")' in source
    assert '"Models AI": "AI Influencers"' in source
    assert '"AI Influencers": lambda: render_edit_placeholder("AI Influencers"' in source
    assert '"Personagens": lambda: render_ai_influencer_characters' in source
    assert '"Geração de Conteúdo IA": lambda: render_ai_influencer_content' in source
    assert '"Contas Instagram": lambda: render_social_networks' in source


def test_niche_finder_menu_precedes_pipeline_in_top_navigation():
    source_path = Path(__file__).parents[1] / "app" / "main.py"
    source = source_path.read_text(encoding="utf-8")
    top_pages_start = source.index("    top_pages = [")
    top_pages_end = source.index("    aliases = {", top_pages_start)
    top_pages = source[top_pages_start:top_pages_end]

    assert top_pages.index('(\"Niche Finder\", ":material/search:", \"Niche Finder\")') < top_pages.index('(\"Pipeline Vídeos\", ":material/account_tree:", \"Pipeline Vídeos\")')
