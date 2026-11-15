"""Contratos da recuperação de estado protegido (incidente 13/11/2026).

O relato: os 117 vídeos da aba Automação passaram a aparecer como 4 na
interface, sem nada ter sido apagado. A causa foi a recuperação de desastres
do `hermes_ui/storage.py`: uma leitura TRANSITÓRIA do `tasks.json` falhou, o
sistema preservou correctamente o ficheiro (117 itens, válido) como
`tasks.json.corrupt-20261113234519534382` e — ignorando a cópia que acabara
de criar — restaurou por cima um backup de 28 de Agosto com 3 itens.

Estes testes cravam as três regras que impedem a repetição:

1. REGRA DE OURO: a cópia preservada no momento do erro é a fonte mais fresca
   (byte-a-byte do ficheiro que falhou) e é tentada PRIMEIRO — se parsear, é
   ela que é restaurada, nunca um backup antigo.
2. RELEITURA: uma falha de leitura transitória (partilha do Windows,
   antivírus, replace atómico em curso) não deve desencadear restauro nenhum
   quando uma segunda leitura do mesmo ficheiro já funciona.
3. GUARDA DE ENCOLHIMENTO: nenhum restauro pode devolver menos de metade dos
   itens conhecidos — sobrescrever 100+ tarefas por 3 de um backup obsoleto é
   perda de dados; nesse caso o corrompido fica preservado para análise manual.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _isolated_storage(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(storage_root))
    from hermes_ui import storage

    # Atribuição directa vazaria STORAGE/STATE para os testes seguintes.
    monkeypatch.setattr(storage, "STORAGE", storage_root)
    monkeypatch.setattr(storage, "STATE", storage_root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", storage_root / "blueprints")
    storage.ensure_storage()
    return storage


def _tasks(count: int, prefix: str) -> list[dict]:
    return [
        {"id": f"{prefix}-{index:03d}", "state": "to_do", "title": f"tarefa {index}"}
        for index in range(count)
    ]


def _write_corrupt(state_dir: Path, name: str, items: list[dict]) -> Path:
    path = state_dir / name
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _recovery_events(state_dir: Path) -> list[dict]:
    log_path = state_dir / "storage-recovery.log"
    if not log_path.is_file():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_recovery_prefers_the_copy_preserved_in_the_incident_over_an_old_backup(tmp_path, monkeypatch):
    """Incidente 13/11/2026: a cópia fresca (100 itens) tem de vencer o backup
    antigo (3 itens). A falha de leitura é forçada APENAS no ficheiro actual —
    as leituras dos candidatos continuam reais, como no acidente."""
    storage = _isolated_storage(tmp_path, monkeypatch)
    state_dir = storage.STATE
    task_path = state_dir / "tasks.json"

    current = _tasks(100, "video")
    storage.write_json("tasks.json", current)

    # backup obsoleto de Agosto (3 itens) já existia em disco
    obsolete = _write_corrupt(state_dir, "tasks.json.corrupt-20260828155014", _tasks(3, "old"))

    original_loader = storage._load_json_unlocked

    def transient_failure(target: Path):
        if Path(target) == task_path:
            raise json.JSONDecodeError("leitura forçada (falha transitoria)", "<doc>", 0)
        return original_loader(target)

    monkeypatch.setattr(storage, "_load_json_unlocked", transient_failure)

    recovered = storage.read_json("tasks.json")

    # são os 100 actuais, não os 3 de Agosto
    assert [task["id"] for task in recovered] == [task["id"] for task in current]
    assert len(json.loads(task_path.read_text(encoding="utf-8"))) == 100
    assert "old-000" not in {task["id"] for task in recovered}

    # o backup obsoleto continua intacto em disco (nada foi destruído)
    assert json.loads(obsolete.read_text(encoding="utf-8"))[0]["id"] == "old-000"

    events = _recovery_events(state_dir)
    assert any("ficheiro invalido" in event["message"] for event in events)
    # restaurado a partir da cópia recém-criada, NUNCA a partir do backup de Agosto
    assert any("restaurado a partir de tasks.json.corrupt-2026" in event["message"] for event in events)
    assert not any("restaurado a partir de tasks.json.corrupt-20260828155014" in event["message"] for event in events)


def test_recovery_relieves_a_transient_read_failure_without_restoring_anything(tmp_path, monkeypatch):
    """Falha transitória: a segunda leitura do MESMO ficheiro funciona — não
    há restauro, nenhuma escrita, o ficheiro fica como estava (é o cenário do
    acidente: a cópia preservada 35 ms depois já estava completa)."""
    storage = _isolated_storage(tmp_path, monkeypatch)
    state_dir = storage.STATE
    task_path = state_dir / "tasks.json"

    current = _tasks(50, "video")
    storage.write_json("tasks.json", current)
    mtime_before = task_path.stat().st_mtime_ns
    size_before = task_path.stat().st_size

    original_loader = storage._load_json_unlocked
    calls = {"count": 0}

    def fails_once(target: Path):
        if Path(target) == task_path:
            calls["count"] += 1
            if calls["count"] == 1:
                raise json.JSONDecodeError("leitura forçada (falha transitoria)", "<doc>", 0)
        return original_loader(target)

    monkeypatch.setattr(storage, "_load_json_unlocked", fails_once)

    recovered = storage.read_json("tasks.json")

    assert len(recovered) == 50
    assert calls["count"] == 2  # falhou uma vez, a releitura funcionou
    # zero escrita: mesmo conteúdo, mesmo tamanho, mesmo mtime
    assert task_path.stat().st_mtime_ns == mtime_before
    assert task_path.stat().st_size == size_before

    events = _recovery_events(state_dir)
    assert any("ficheiro relido com sucesso" in event["message"] for event in events)
    assert not any("restaurado a partir de" in event["message"] for event in events)


def test_recovery_blocks_an_obsolete_backup_that_would_shrink_the_state(tmp_path, monkeypatch):
    """Guarda de encolhimento: com o ficheiro E a cópia fresca ilegíveis, um
    candidato recente de 3 itens NÃO pode substituir 100 — é abortado e o
    candidato bom (100 itens) é restaurado no seu lugar."""
    storage = _isolated_storage(tmp_path, monkeypatch)
    state_dir = storage.STATE
    task_path = state_dir / "tasks.json"

    # ficheiro actual ilegível (a cópia preservada será ilegível também)
    task_path.write_text("{invalido", encoding="utf-8")

    good = _tasks(100, "video")
    # o candidato OBSULETO (3 itens) é o mais recente; o bom (100) é mais antigo
    _write_corrupt(state_dir, "tasks.json.corrupt-20261113000000000000", _tasks(3, "obsoleto"))
    _write_corrupt(state_dir, "tasks.json.corrupt-20261006000000000000", good)
    os.utime(state_dir / "tasks.json.corrupt-20261113000000000000", (1_800_000_000, 1_800_000_000))
    os.utime(state_dir / "tasks.json.corrupt-20261006000000000000", (1_700_000_000, 1_700_000_000))

    recovered = storage.read_json("tasks.json")

    assert len(recovered) == 100
    assert "obsoleto-000" not in {task["id"] for task in recovered}

    events = _recovery_events(state_dir)
    blocked = [event["message"] for event in events if "abortado" in event["message"]]
    assert blocked, "a guarda de encolhimento tinha de bloquear o backup de 3 itens"
    assert "3 itens" in blocked[0] and "50%" in blocked[0]
    assert any("restaurado a partir de tasks.json.corrupt-20261006000000000000" in event["message"] for event in events)


def test_recovery_uses_atomic_write_leftovers_when_every_backup_is_obsolete(tmp_path, monkeypatch):
    """Leftovers `.tasks.json.*` (snapshots completos de escritas atómicas
    interrompidas) passam a ser candidatos: com o backup mais recente obsoleto
    (3 itens) e um leftover de 100 itens, é o leftover que é restaurado — a
    lógica anterior nunca olhava para estes ficheiros."""
    storage = _isolated_storage(tmp_path, monkeypatch)
    state_dir = storage.STATE
    task_path = state_dir / "tasks.json"

    task_path.write_text("{invalido", encoding="utf-8")

    good = _tasks(100, "video")
    _write_corrupt(state_dir, "tasks.json.corrupt-20260828155014", _tasks(3, "obsoleto"))
    leftover = state_dir / ".tasks.json.rcgmsn63"
    leftover.write_text(json.dumps(good, ensure_ascii=False, indent=2), encoding="utf-8")
    # o backup obsoleto é MAIS RECENTE que o leftover: sem a guarda, venceria
    os.utime(state_dir / "tasks.json.corrupt-20260828155014", (1_800_000_000, 1_800_000_000))
    os.utime(leftover, (1_700_000_000, 1_700_000_000))

    recovered = storage.read_json("tasks.json")

    assert len(recovered) == 100
    assert [task["id"] for task in recovered] == [task["id"] for task in good]

    events = _recovery_events(state_dir)
    assert any("restaurado a partir de .tasks.json.rcgmsn63" in event["message"] for event in events)
    assert not any("restaurado a partir de tasks.json.corrupt-20260828155014" in event["message"] for event in events)


def stamp_epoch(name: str) -> float:
    """Epoch de um sufixo corrupt-AAAAMMDDHHMMSSffffff (UTC)."""
    parsed = datetime.strptime(name, "%Y%m%d%H%M%S%f").replace(tzinfo=timezone.utc)
    return parsed.timestamp()