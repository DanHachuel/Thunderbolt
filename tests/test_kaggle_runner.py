import json
import os
import subprocess
import sys
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
        assert metadata["is_private"] is False
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


def test_username_and_kernel_slug_use_kaggle_identifier_format():
    valid = kaggle_runner._required_credentials("danhachuel", "key", "thunderbolt")
    assert valid == ("danhachuel", "key", "thunderbolt")
    assert kaggle_runner._required_credentials("", "KGAT_example-token", "thunderbolt") == ("", "KGAT_example-token", "thunderbolt")
    for username, slug in (("bad_name", "thunderbolt"), ("-user", "thunderbolt"), ("user", "bad/slug"), ("user", "bad-"), ("x" * 51, "thunderbolt")):
        try:
            kaggle_runner._required_credentials(username, "key", slug)
        except kaggle_runner.KaggleNicheError as exc:
            assert "minúsculas" in str(exc)
        else:
            raise AssertionError(f"Invalid Kaggle identifiers were accepted: {username!r}/{slug!r}")


def test_runner_sets_legacy_credentials_before_loading_sdk(tmp_path, monkeypatch):
    seen = []

    class FakeApi:
        def __init__(self):
            seen.append((os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY"), os.environ.get("KAGGLE_API_TOKEN")))

        def authenticate(self):
            seen.append("authenticated")

    for name in ("KAGGLE_CONFIG_DIR", "KAGGLE_USERNAME", "KAGGLE_KEY", "KAGGLE_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KAGGLE_API_TOKEN", "stale-modern-token")
    monkeypatch.setattr(kaggle_runner, "_load_kaggle_api", lambda: FakeApi)
    monkeypatch.setattr(kaggle_runner.tempfile, "mkdtemp", lambda **_kwargs: str(tmp_path / "config"))
    kaggle_runner.KaggleNicheRunner("danhachuel", "legacy-key", "thunderbolt")
    assert seen == [("danhachuel", "legacy-key", None), "authenticated"]


def test_runner_uses_modern_token_without_mixing_legacy_key_environment(tmp_path, monkeypatch):
    seen = []

    class FakeApi:
        def __init__(self):
            seen.append((os.environ.get("KAGGLE_API_TOKEN"), os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")))

        def authenticate(self):
            seen.append("authenticated")

    for name in ("KAGGLE_CONFIG_DIR", "KAGGLE_USERNAME", "KAGGLE_KEY", "KAGGLE_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KAGGLE_USERNAME", "stale-user")
    monkeypatch.setenv("KAGGLE_KEY", "stale-legacy-key")
    monkeypatch.setattr(kaggle_runner, "_load_kaggle_api", lambda: FakeApi)
    monkeypatch.setattr(kaggle_runner.tempfile, "mkdtemp", lambda **_kwargs: str(tmp_path / "config"))
    kaggle_runner.KaggleNicheRunner("danhachuel", "KGAT_example-token", "thunderbolt")
    assert seen == [("KGAT_example-token", None, None), "authenticated"]


def test_runner_derives_username_from_modern_access_token(tmp_path, monkeypatch):
    class FakeApi:
        CONFIG_NAME_USER = "username"

        def __init__(self):
            self.config_values = {}

        def authenticate(self):
            self.config_values[self.CONFIG_NAME_USER] = "danhachuel"

    for name in ("KAGGLE_CONFIG_DIR", "KAGGLE_USERNAME", "KAGGLE_KEY", "KAGGLE_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(kaggle_runner, "_load_kaggle_api", lambda: FakeApi)
    monkeypatch.setattr(kaggle_runner.tempfile, "mkdtemp", lambda **_kwargs: str(tmp_path / "config"))
    runner = kaggle_runner.KaggleNicheRunner("", "KGAT_example-token", "thunderbolt")
    assert runner.username == "danhachuel"
    assert runner.kernel_ref == "danhachuel/thunderbolt"


def test_runner_converts_sdk_system_exit_to_actionable_error(tmp_path, monkeypatch):
    class FakeApi:
        def __init__(self):
            pass

        def authenticate(self):
            raise SystemExit(1)

    for name in ("KAGGLE_CONFIG_DIR", "KAGGLE_USERNAME", "KAGGLE_KEY", "KAGGLE_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(kaggle_runner, "_load_kaggle_api", lambda: FakeApi)
    monkeypatch.setattr(kaggle_runner.tempfile, "mkdtemp", lambda **_kwargs: str(tmp_path / "config"))
    try:
        kaggle_runner.KaggleNicheRunner("danhachuel", "KGAT_invalid-token", "thunderbolt")
    except kaggle_runner.KaggleNicheError as exc:
        assert "autenticação Kaggle falhou" in str(exc)
    else:
        raise AssertionError("SDK SystemExit must not escape the diagnostic action")


def test_wait_propagates_kernel_not_found_instead_of_timing_out(caplog):
    runner = object.__new__(kaggle_runner.KaggleNicheRunner)
    runner.kernel_ref = "danhachuel/missing-kernel"

    class FakeResponse:
        status_code = 404

    class NotFoundError(RuntimeError):
        response = FakeResponse()

    class FakeApi:
        def kernels_status(self, _kernel_ref):
            raise NotFoundError("kernel not found")

    runner.api = FakeApi()
    try:
        runner.wait(timeout_minutes=1)
    except kaggle_runner.KaggleNicheError as exc:
        assert "não foi encontrada" in str(exc)
    else:
        raise AssertionError("A missing kernel should fail immediately instead of timing out")
    assert "Kernel Kaggle" in caplog.text


def test_importing_niche_finder_does_not_load_kaggle_sdk():
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import app.modules.niche_finder; print('kaggle' in sys.modules)"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(root)},
    )
    assert result.stdout.strip() == "False"


def test_importing_app_does_not_print_kaggle_authentication_help(tmp_path):
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "import app.main; import sys; print('kaggle' in sys.modules)"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(root), "THUNDERBOLT_STORAGE_DIR": str(tmp_path / "storage")},
    )
    output = result.stdout + result.stderr
    assert "Authentication required to call the Kaggle API." not in output
    assert result.stdout.strip().endswith("False")


def test_kaggle_sdk_import_is_lazy_until_runner_action():
    source = (Path(__file__).parents[1] / "app/modules/niche_finder/kaggle_runner.py").read_text(encoding="utf-8")
    assert "from kaggle.api.kaggle_api_extended import KaggleApi" in source
    assert "def _load_kaggle_api()" in source
    assert "KaggleApi = _load_kaggle_api()" in source
    assert "_load_kaggle_api()" in source[source.index("class KaggleNicheRunner"):]
    assert "KAGGLE_CONFIG_DIR" in source
    assert "tempfile.mkdtemp" in source
