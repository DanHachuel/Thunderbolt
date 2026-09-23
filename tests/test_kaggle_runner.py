import json
from pathlib import Path

import pandas as pd

from app.modules.niche_finder import kaggle_runner


def _frames():
    return {
        "clusters": pd.DataFrame([{"cluster_id": 0, "palavras": "history", "tamanho": 2}]),
        "frequent_items": pd.DataFrame([{"support": 0.5, "itemsets": "history, facts"}]),
        "association_rules": pd.DataFrame([{"antecedents": "history", "consequents": "facts", "support": 0.5, "confidence": 1.0, "lift": 2.0}]),
    }


def test_staged_kernel_contains_requested_parameters_without_credentials(tmp_path, monkeypatch):
    runner = object.__new__(kaggle_runner.KaggleNicheRunner)
    runner.kernel_ref = "user/kernel"
    monkeypatch.setattr(kaggle_runner, "KERNEL_DIR", Path(__file__).parents[1] / "app/modules/niche_finder/kaggle_kernel")
    with runner._staged_kernel(7, 0.12) as staged:
        script = (Path(staged) / "script.py").read_text(encoding="utf-8")
        metadata = json.loads((Path(staged) / "kernel-metadata.json").read_text(encoding="utf-8"))
        assert "N_CLUSTERS = 7" in script
        assert "MIN_SUPPORT = 0.12" in script
        assert metadata["id"] == "user/kernel"
        assert not (Path(staged) / "kaggle.json").exists()


def test_remote_runner_uses_local_cache_without_republishing(tmp_path, monkeypatch):
    frames = _frames()
    calls = []

    class FakeRunner:
        def __init__(self, *_args):
            calls.append("init")

        def push(self, **_kwargs):
            calls.append("push")

        def wait(self, **_kwargs):
            calls.append("wait")

        def download_outputs(self, output_dir):
            calls.append("download")
            output_dir.mkdir(parents=True, exist_ok=True)
            for name, frame in frames.items():
                frame.to_csv(output_dir / f"{name}.csv", index=False)
            return frames

    monkeypatch.setattr(kaggle_runner, "KaggleNicheRunner", FakeRunner)
    first = kaggle_runner.run_niche_analysis_remotely("user", "secret", "kernel", tmp_path, n_clusters=5, min_support=0.05)
    second = kaggle_runner.run_niche_analysis_remotely("user", "secret", "kernel", tmp_path, n_clusters=5, min_support=0.05)
    assert calls == ["init", "push", "wait", "download"]
    assert first["summary"]["cluster_count"] == second["summary"]["cluster_count"] == 1
    assert (tmp_path / "metadata.json").is_file()


def test_required_credentials_are_checked_only_when_action_is_called(tmp_path):
    try:
        kaggle_runner.run_niche_analysis_remotely("", "", "", tmp_path)
    except kaggle_runner.KaggleNicheError as exc:
        assert "Username" in str(exc) or "username" in str(exc)
    else:
        raise AssertionError("Missing Kaggle credentials should fail at action time")
