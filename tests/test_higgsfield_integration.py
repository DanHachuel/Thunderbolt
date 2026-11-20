"""Integracao Higgsfield AI: wrapper do CLI (`hermes_ui/higgsfield_integration.py`).

Testes de contrato reais: o `subprocess.run` e o `shutil.which` sao substituidos,
por isso o que se prova e o comando montado, o parsing de `--json`, a
normalizacao do job, a degradacao sem CLI/sem auth e as flags de spawn no
Windows. Nada aqui toca na rede nem no CLI do utilizador.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermes_ui import higgsfield_integration as hf  # noqa: E402


class FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class Recorder:
    """Substituto de subprocess.run que registra os argumentos e responde."""

    def __init__(self, responder):
        self.calls = []
        self._responder = responder

    def __call__(self, args, **kwargs):
        self.calls.append({"args": list(args), "kwargs": dict(kwargs)})
        return self._responder(args)


@pytest.fixture
def cli_installed(monkeypatch):
    """Faz o CLI parecer instalado sem depender do PATH da maquina."""
    monkeypatch.setattr(hf.shutil, "which", lambda name: f"C:/bin/{name}.cmd" if name in hf.HIGGSFIELD_EXECUTABLES else None)
    return monkeypatch


def _install(monkeypatch, responder):
    recorder = Recorder(responder)
    monkeypatch.setattr(hf.shutil, "which", lambda name: f"C:/bin/{name}.cmd")
    monkeypatch.setattr(hf.subprocess, "run", recorder)
    return recorder


def _args_of(recorder, index=-1):
    return recorder.calls[index]["args"]


def _is_auth_call(args) -> bool:
    """O primeiro argumento e o executável; o comando vem a seguir."""
    return args[1:3] == ["account", "status"]


# ---------------------------------------------------------------- ausencia do CLI

def test_missing_cli_is_reported_instead_of_crashing(monkeypatch):
    monkeypatch.setattr(hf.shutil, "which", lambda name: None)
    status = hf.auth_status()
    assert status["installed"] is False
    assert status["authenticated"] is False
    assert "npm install -g @higgsfield/cli" in status["instructions"]


def test_generation_without_cli_raises_a_clear_error(monkeypatch):
    monkeypatch.setattr(hf.shutil, "which", lambda name: None)
    with pytest.raises(hf.HiggsfieldError) as excinfo:
        hf.submit_generation("gpt_image_2_6", prompt="um gato")
    assert "Higgsfield" in str(excinfo.value)
    assert "npm install -g @higgsfield/cli" in str(excinfo.value)


# ------------------------------------------------------------------ autenticacao

def test_authenticated_session_is_detected(cli_installed):
    recorder = _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='{"authenticated": true, "email": "conta@exemplo.pt"}', returncode=0),
    )
    status = hf.auth_status()
    assert status["installed"] is True
    assert status["authenticated"] is True
    assert _args_of(recorder) == [f"C:/bin/higgsfield.cmd", "account", "status", "--json"]


def test_unauthenticated_session_is_reported_with_login_instructions(cli_installed):
    recorder = _install(
        cli_installed,
        lambda args: FakeCompleted(stdout="", stderr="Not authenticated. Run higgsfield auth login", returncode=1),
    )
    status = hf.auth_status()
    assert status["authenticated"] is False
    assert "higgsfield auth login" in status["instructions"]
    assert _args_of(recorder) == [f"C:/bin/higgsfield.cmd", "account", "status", "--json"]


def test_generation_blocked_when_session_is_not_authenticated(cli_installed):
    recorder = _install(cli_installed, lambda args: FakeCompleted(returncode=1, stderr="Not authenticated"))
    with pytest.raises(hf.HiggsfieldError) as excinfo:
        hf.submit_product_photoshoot(mode="product_shot", prompt="garrafa de agua")
    assert "auth login" in str(excinfo.value)
    # so a verificacao de auth correu: nunca submeteu o job
    assert len(recorder.calls) == 1
    assert "account" in _args_of(recorder)


# --------------------------------------------------------------------- generate

def test_submit_generation_builds_the_documented_command(cli_installed):
    recorder = _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='{"id": "job_123", "status": "queued"}', returncode=0),
    )
    job = hf.submit_generation(
        "seedance_2_5",
        prompt="drone sobre uma montanha",
        video=["./fonte.mp4"],
        params={"aspect_ratio": "16:9", "duration": 5, "resolution": "1080p"},
    )
    args = _args_of(recorder)
    assert args[1:5] == ["generate", "create", "seedance_2_5", "--json"]
    assert args[5:7] == ["--prompt", "drone sobre uma montanha"]
    assert args[7:9] == ["--video", "./fonte.mp4"]
    assert args[9:] == ["--aspect_ratio", "16:9", "--duration", "5", "--resolution", "1080p"]
    assert job["id"] == "job_123"
    assert job["status"] == "queued"
    assert job["terminal"] is False
    assert job["done"] is False


def test_submit_generation_accepts_multiple_images(cli_installed):
    recorder = _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='{"job_set_id": "abc"}', returncode=0),
    )
    job = hf.submit_generation("text2image_soul_v2", prompt="retrato", image=["a.png", "b.png"])
    assert _args_of(recorder).count("--image") == 2
    # o id pode vir em varias chaves; a normalizacao nao inventa uma so
    assert job["id"] == "abc"


def test_submit_generation_requires_a_model(cli_installed):
    _install(cli_installed, lambda args: FakeCompleted(stdout="{}"))
    with pytest.raises(hf.HiggsfieldError):
        hf.submit_generation("   ", prompt="nada")


def test_cli_refusal_becomes_a_readable_error(cli_installed):
    def responder(args):
        if _is_auth_call(args):
            return FakeCompleted(stdout='{"authenticated": true}', returncode=0)
        return FakeCompleted(returncode=2, stderr="modelo desconhecido")

    _install(cli_installed, responder)
    with pytest.raises(hf.HiggsfieldError) as excinfo:
        hf.submit_generation("modelo_que_nao_existe", prompt="x")
    assert "modelo desconhecido" in str(excinfo.value)


def test_get_generation_normalises_status_and_url(cli_installed):
    recorder = _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='{"id": "job_9", "status": "completed", "result_url": "https://cdn/x.mp4"}', returncode=0),
    )
    job = hf.get_generation("job_9")
    assert _args_of(recorder) == [f"C:/bin/higgsfield.cmd", "generate", "get", "job_9", "--json"]
    assert job["done"] is True
    assert job["terminal"] is True
    assert job["url"] == "https://cdn/x.mp4"


def test_get_generation_accepts_a_list_payload(cli_installed):
    _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='[{"id": "job_1", "status": "failed"}]', returncode=0),
    )
    job = hf.get_generation("job_1")
    assert job["status"] == "failed"
    assert job["terminal"] is True
    assert job["done"] is False


def test_wait_generation_passes_the_timeout_to_the_cli(cli_installed):
    recorder = _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='{"id": "job_5", "status": "completed", "result_url": "u"}', returncode=0),
    )
    hf.wait_generation("job_5", timeout_seconds=90)
    args = _args_of(recorder)
    assert args[1:4] == ["generate", "wait", "job_5"]
    assert "--wait-timeout" in args
    assert args[args.index("--wait-timeout") + 1] == "90s"


def test_list_generations_reads_a_json_array(cli_installed):
    _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='[{"id": "a", "status": "completed"}, {"id": "b", "status": "failed"}]', returncode=0),
    )
    jobs = hf.list_generations()
    assert [job["id"] for job in jobs] == ["a", "b"]
    assert [job["done"] for job in jobs] == [True, False]


# ------------------------------------------------------- product-photoshoot / soul

def test_product_photoshoot_uses_mode_and_positional_prompt(cli_installed):
    recorder = _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='{"id": "pp_1", "status": "queued"}', returncode=0),
    )
    hf.submit_product_photoshoot(mode="lifestyle_scene", prompt="creme num roupeiro", image="./produto.jpg", count=4)
    args = _args_of(recorder)
    assert args[1:5] == ["product-photoshoot", "create", "--mode", "lifestyle_scene"]
    assert "creme num roupeiro" in args
    assert args[args.index("--image") + 1] == "./produto.jpg"
    assert args[args.index("--count") + 1] == "4"
    assert "--json" in args


def test_soul_training_requires_photos(cli_installed):
    _install(cli_installed, lambda args: FakeCompleted(stdout="{}"))
    with pytest.raises(hf.HiggsfieldError) as excinfo:
        hf.train_soul(name="ana", images=[])
    assert "5 e 20 fotos" in str(excinfo.value)


def test_soul_training_builds_the_skill_command(cli_installed):
    recorder = _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='{"id": "soul_1", "status": "training"}', returncode=0),
    )
    job = hf.train_soul(name="ana", images=["./f1.png", "./f2.png"], variant="soul-cinematic")
    args = _args_of(recorder)
    assert args[1] == "soul-id"
    assert args[2] == "create"
    assert args[args.index("--name") + 1] == "ana"
    assert "--soul-cinematic" in args
    # cada foto gera exactamente um par --image <caminho> (sem duplicar a flag)
    assert args.count("--image") == 2
    assert args[args.index("--image") + 1] == "./f1.png"
    assert args[args.index("--image", args.index("--image") + 1) + 1] == "./f2.png"
    assert "--json" in args
    assert {key: job[key] for key in ("id", "status", "url", "done", "terminal")} == {
        "id": "soul_1", "status": "training", "url": "", "done": False, "terminal": False,
    }


def test_soul_wait_passes_the_timeout(cli_installed):
    recorder = _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='{"id": "soul_1", "status": "completed"}', returncode=0),
    )
    hf.wait_soul("soul_1", timeout_seconds=120)
    args = _args_of(recorder)
    assert args[1:4] == ["soul-id", "wait", "soul_1"]
    assert args[args.index("--wait-timeout") + 1] == "120s"


def test_list_souls_reads_a_json_object(cli_installed):
    _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='{"items": [{"id": "s1"}, {"id": "s2"}]}', returncode=0),
    )
    souls = hf.list_souls()
    assert [soul["id"] for soul in souls] == ["s1", "s2"]


def test_upload_requires_an_existing_file(cli_installed, tmp_path):
    _install(cli_installed, lambda args: FakeCompleted(stdout="{}"))
    with pytest.raises(hf.HiggsfieldError):
        hf.submit_media_upload(tmp_path / "nao-existe.png")


# ------------------------------------------------------- spawn / robustez (regras)

def test_spawn_uses_hidden_window_and_process_group_on_windows():
    flags = hf._creationflags()
    if sys.platform != "win32":
        assert flags == 0
        return
    assert flags & subprocess.CREATE_NO_WINDOW
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP


def test_spawn_never_detaches_nor_inherits_the_console(cli_installed):
    recorder = _install(
        cli_installed,
        lambda args: FakeCompleted(stdout='{"id": "j", "status": "queued"}', returncode=0),
    )
    hf.submit_generation("gpt_image_2_6", prompt="x")
    kwargs = recorder.calls[0]["kwargs"]
    assert "detached" not in kwargs  # nenhum spawn destacado (AGENTS.md)
    assert "stdio" not in kwargs or kwargs["stdio"] != "inherit"
    assert kwargs["capture_output"] is True  # a saida vai por pipe, nao para a consola
    assert kwargs["check"] is False
    assert hf._environment()["PYTHONIOENCODING"] == "utf-8"
    assert "NO_COLOR" in hf._environment()


def test_timeout_becomes_a_readable_error(cli_installed):
    def _timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=5)

    monkeypatch_run = Recorder(_timeout)
    cli_installed.setattr(hf.subprocess, "run", monkeypatch_run)
    with pytest.raises(hf.HiggsfieldError):
        hf.wait_generation("job_x", timeout_seconds=5)


def test_auth_status_timeout_is_reported_not_raised(cli_installed):
    def _timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=5)

    cli_installed.setattr(hf.subprocess, "run", Recorder(_timeout))
    status = hf.auth_status()
    assert status["installed"] is True
    assert status["authenticated"] is False
    assert "não respondeu" in status["detail"]


def test_auth_status_os_error_is_reported_not_raised(cli_installed):
    def _boom(args, **kwargs):
        raise OSError("ficheiro bloqueado (EBUSY)")

    cli_installed.setattr(hf.subprocess, "run", Recorder(_boom))
    status = hf.auth_status()
    assert status["authenticated"] is False
    assert "Higgsfield" in status["detail"] or "CLI" in status["detail"]


def test_json_parser_tolerates_cli_chatter(cli_installed):
    assert hf._parse_json('Aviso: a usar workspace X\n{"id": "1"}') == {"id": "1"}
    assert hf._parse_json("sem json") is None
    assert hf._parse_json("") is None