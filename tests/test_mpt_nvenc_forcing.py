"""NVENC forçado no runtime MPT + fallback seguro para CPU (1.0.23).

Investigação nesta máquina: o fork do MPT resolve o FFmpeg por ENV → PATH →
wheel do imageio (IGNORA o ``ffmpeg_path`` do config.toml) e o spawn principal
do ``mpt_agent.py`` corria **sem ``env=``** — o probe de codec usava o binário
do PATH (FFmpeg 9.0 que anuncia ``h264_nvenc`` nos ``-encoders`` mas falha a
abrir o encoder com error -40) e o MoviePy o wheel antigo do imageio; o
render caía silenciosamente para libx264 na CPU e 3 vídeos em paralelo
travavam a barra nos 79% (encode final de ~4 min por vídeo). Correcções:

1. o subprocesso de render recebe ``IMAGEIO_FFMPEG_EXE``/``FFMPEG_BINARY``
   do binário EFECTIVO (o 7.1 do pacote) — helper no mpt_agent + env_values
   no pipeline_worker;
2. o config.toml do MPT nunca fica no comando nu "ffmpeg" quando existe um
   binário instalado (resolver em moneyprinter_config);
3. o probe REAL de NVENC (encode de 1 s com o binário efectivo) determina o
   banner ``[MPT-CODEC]`` — a listagem ``-encoders`` mente num build partido;
4. NVENC indisponível ⇒ gate do runtime cai a 1 (CPU não aguenta 3 renders)
   + AVISO em código;
5. o log do MOTOR é varrido pelos marcadores de fallback para CPU.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hermes_ui import pipeline_worker
from integrations.moneyprinter_config import (
    NVENC_VIDEO_CODEC,
    build_moneyprinter_config,
    resolve_effective_ffmpeg_path,
)


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
AGENT_SOURCE = (ROOT / "seed" / "skills" / "mpt_agent.py").read_text(encoding="utf-8")

_SPEC = importlib.util.spec_from_file_location("test_mpt_agent_nvenc", ROOT / "seed" / "skills" / "mpt_agent.py")
mpt_agent = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mpt_agent)


@pytest.fixture(autouse=True)
def _reset_nvenc_state(monkeypatch):
    """O probe/cache/flag são estado de processo — cada teste parte limpo."""
    monkeypatch.setattr(pipeline_worker, "_nvenc_probe_state", {"path": "", "available": None})
    pipeline_worker._mpt_cpu_fallback.clear()
    yield
    pipeline_worker._mpt_cpu_fallback.clear()


@pytest.fixture()
def isolated_storage(tmp_path, monkeypatch):
    """STORAGE apontado a tmp; LOCALAPPDATA a um home vazio (sem binários)."""
    from hermes_ui import storage

    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(pipeline_worker, "STORAGE", root)
    empty_home = tmp_path / "home"
    empty_home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(empty_home))
    return tmp_path


def _fake_ffmpeg(parent: Path, name: str = "ffmpeg.exe") -> Path:
    binary = parent / name
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"fake")
    return binary


# ---------------------------------------------------------------------------
# 1+2. Resolver: o binário EFECTIVO nunca é o comando nu "ffmpeg" por engano
# ---------------------------------------------------------------------------


def test_resolver_prefers_the_explicitly_seeded_binary(isolated_storage, tmp_path):
    seeded = _fake_ffmpeg(tmp_path / "seeded")
    assert resolve_effective_ffmpeg_path({"ffmpeg_seed_path": str(seeded)}) == str(seeded)


def test_resolver_discovers_the_bundled_binary_next_to_storage(isolated_storage, tmp_path):
    installed = _fake_ffmpeg(tmp_path / "ffmpeg" / "7.1-20240930" / "bin")
    assert resolve_effective_ffmpeg_path({"ffmpeg_path": "ffmpeg"}) == str(installed)


def test_resolver_falls_back_to_the_windows_thunderbolt_home(isolated_storage, tmp_path, monkeypatch):
    # O branch do home default do Windows só corre com os.name == "nt" — no CI
    # Linux o teste simula a plataforma para exercitar a descoberta
    # LOCALAPPDATA/THUNDERBOLT (é o caminho das instalações reais do pacote).
    monkeypatch.setattr("os.name", "nt")
    home = tmp_path / "home" / "THUNDERBOLT"
    installed = _fake_ffmpeg(home / "ffmpeg" / "7.1-20240930" / "inner" / "bin")
    assert resolve_effective_ffmpeg_path({}) == str(installed)


def test_resolver_keeps_the_configured_path_when_nothing_is_installed(isolated_storage):
    assert resolve_effective_ffmpeg_path({"ffmpeg_path": "C:/tools/ffmpeg.exe"}) == "C:/tools/ffmpeg.exe"
    assert resolve_effective_ffmpeg_path({}) == "ffmpeg"


def test_sync_writes_the_resolved_ffmpeg_and_nvenc_into_the_mpt_config(isolated_storage, tmp_path):
    installed = _fake_ffmpeg(tmp_path / "ffmpeg" / "7.1-20240930" / "bin")
    config = build_moneyprinter_config({"ffmpeg_path": "ffmpeg"})
    # nunca o comando nu: o config alimenta a injecção de env do mpt_agent
    assert config["app"]["ffmpeg_path"] == str(installed)
    assert config["app"]["video_codec"] == NVENC_VIDEO_CODEC


# ---------------------------------------------------------------------------
# 3+4. Probe real de NVENC → banner + gate a 1 runtime
# ---------------------------------------------------------------------------


def test_probe_skips_bare_commands_and_unknown_binaries():
    assert pipeline_worker._probe_nvenc_availability("ffmpeg") is None
    assert pipeline_worker._probe_nvenc_availability("") is None
    assert not pipeline_worker._mpt_cpu_fallback.is_set()


def test_probe_runs_a_real_encode_and_caches_per_binary(tmp_path, monkeypatch):
    binary = _fake_ffmpeg(tmp_path / "ff")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(pipeline_worker.subprocess, "run", fake_run)
    assert pipeline_worker._probe_nvenc_availability(str(binary)) is True
    assert pipeline_worker._probe_nvenc_availability(str(binary)) is True
    # cache por binário: um único encode por processo
    assert len(calls) == 1
    assert calls[0][0] == str(binary)
    assert "-c:v" in calls[0] and "h264_nvenc" in calls[0]
    assert not pipeline_worker._mpt_cpu_fallback.is_set()


def test_probe_failure_sets_the_cpu_fallback_and_logs_the_warning(tmp_path, monkeypatch):
    binary = _fake_ffmpeg(tmp_path / "broken-ff")
    warnings: list[str] = []
    monkeypatch.setattr(pipeline_worker.subprocess, "run", lambda command, **kwargs: type("Completed", (), {"returncode": 1})())
    monkeypatch.setattr(pipeline_worker, "_mpt_runtime_log", warnings.append)

    assert pipeline_worker._probe_nvenc_availability(str(binary)) is False
    assert pipeline_worker._mpt_cpu_fallback.is_set()
    assert any("NVENC indisponível" in message for message in warnings)


def test_gate_falls_to_one_runtime_when_nvenc_is_unavailable():
    assert pipeline_worker._max_parallel_mpt_runtimes({"motor": {"max_parallel_mpt_runtimes": 4}}) == 4
    pipeline_worker._mpt_cpu_fallback.set()
    assert pipeline_worker._max_parallel_mpt_runtimes({"motor": {"max_parallel_mpt_runtimes": 4}}) == 1
    assert pipeline_worker._max_parallel_mpt_runtimes({}) == 1


# ---------------------------------------------------------------------------
# 5. Detecção pós-render: marcadores de fallback no output e no log do motor
# ---------------------------------------------------------------------------


def test_detect_mpt_cpu_fallback_scans_output_and_engine_log(tmp_path):
    engine_log = tmp_path / "run-video.log"
    engine_log.write_text(
        "INFO something\n"
        "WARNING video codec h264_nvenc was disabled after a runtime failure, fallback to libx264\n",
        encoding="utf-8",
    )
    assert pipeline_worker._detect_mpt_cpu_fallback("tudo normal") is False
    assert not pipeline_worker._mpt_cpu_fallback.is_set()
    assert pipeline_worker._detect_mpt_cpu_fallback("", engine_log) is True
    assert pipeline_worker._mpt_cpu_fallback.is_set()
    assert pipeline_worker._detect_mpt_cpu_fallback("…fallback to libx264…", None) is True


# ---------------------------------------------------------------------------
# 1. mpt_agent: env injectado no subprocesso de RENDER (não só no TTS)
# ---------------------------------------------------------------------------


def test_mpt_agent_ffmpeg_environment_injects_both_variables(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[app]\nffmpeg_path = "C:\\\\ffmpeg71\\\\bin\\\\ffmpeg.exe"\n', encoding="utf-8")
    environment = mpt_agent._ffmpeg_environment(config)
    assert environment["IMAGEIO_FFMPEG_EXE"] == "C:\\ffmpeg71\\bin\\ffmpeg.exe"
    assert environment["FFMPEG_BINARY"] == "C:\\ffmpeg71\\bin\\ffmpeg.exe"


def test_mpt_agent_ffmpeg_environment_without_configured_path(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("[app]\n", encoding="utf-8")
    environment = mpt_agent._ffmpeg_environment(config, {"OTHER": "1"})
    assert "IMAGEIO_FFMPEG_EXE" not in environment
    assert environment["OTHER"] == "1"


def test_mpt_agent_main_render_spawn_carries_the_ffmpeg_environment():
    block = AGENT_SOURCE.split("def generate_video(", 1)[1].split("def missing_config(", 1)[0]
    # o spawn principal deixa de herdar o ambiente nu do launcher
    assert "environment = _ffmpeg_environment(config_path)" in block
    assert "using ffmpeg:" in block
    spawn = block.split("result = subprocess.run(", 1)[1][:700]
    assert "env=environment" in spawn
    # a via do TTS Azure continua a usar o MESMO helper
    azure = AGENT_SOURCE.split("def _prepare_azure_v2_chunked_audio(", 1)[1].split("def generate_video(", 1)[0]
    assert "environment = _ffmpeg_environment(config_path, os.environ.copy())" in azure


def test_pipeline_worker_injects_the_effective_ffmpeg_in_the_helper_env():
    block = PIPELINE_SOURCE.split("def _run_video_helper_once(", 1)[1].split("def _run_video_helper(", 1)[0]
    assert '"IMAGEIO_FFMPEG_EXE": effective_ffmpeg' in block
    assert '"FFMPEG_BINARY": effective_ffmpeg' in block
    # o binário efectivo é resolvido e o NVENC sondado ANTES do estágio
    assert "effective_ffmpeg = resolve_effective_ffmpeg_path(settings)" in block
    assert "_probe_nvenc_availability(effective_ffmpeg)" in block
    # banner de codec junto ao banner de spawn
    assert "[MPT-CODEC] ffmpeg={effective_ffmpeg} codec=h264_nvenc" in block
    # detecção pós-render no finally (log do motor + stdout do helper)
    assert "_detect_mpt_cpu_fallback(_output_text(), helper_log_path)" in block
