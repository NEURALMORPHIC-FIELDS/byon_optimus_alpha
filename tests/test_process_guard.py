"""Cycle 4 target 4 — orphan / single-writer process guard (pure detection, no real kills)."""
from __future__ import annotations

import importlib

import pytest

pytest.importorskip("httpx")

_spec = importlib.util.spec_from_file_location(
    "byon_process_guard",
    str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts" / "byon_process_guard.py"))
pg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pg)


def test_detects_python313_training_process():
    procs = [
        {"pid": 100, "name": "python3.13.exe",
         "cmdline": "C:\\...\\python3.13.exe -c from gateway.vault_training import train_vault"},
        {"pid": 101, "name": "python.exe", "cmdline": "python run_byon.py --train-vault --vault D:/x"},
        {"pid": 102, "name": "py.exe", "cmdline": "py scripts\\foo.py train_vault"},
    ]
    found = pg.find_vault_trainers(procs, self_pid=1)
    assert {t["pid"] for t in found} == {100, 101, 102}


def test_does_not_kill_unrelated_python():
    procs = [
        {"pid": 200, "name": "python.exe", "cmdline": "python -m pytest tests/"},
        {"pid": 201, "name": "python3.13.exe", "cmdline": "python3.13 -m gateway.server"},
        {"pid": 202, "name": "python.exe", "cmdline": "python run_byon.py --no-prompt"},
        {"pid": 203, "name": "code.exe", "cmdline": "VS Code helper"},
    ]
    found = pg.find_vault_trainers(procs, self_pid=1)
    assert found == []                                  # none match the vault-trainer signature


def test_excludes_self_pid():
    procs = [{"pid": 7, "name": "python3.13.exe", "cmdline": "python3.13 train_vault"}]
    assert pg.find_vault_trainers(procs, self_pid=7) == []


def test_is_vault_trainer_signature():
    assert pg.is_vault_trainer("python3.13.exe", "x train_vault y") is True
    assert pg.is_vault_trainer("python.exe", "run_byon.py --train-vault") is True
    assert pg.is_vault_trainer("python.exe", "python -m pytest") is False
    assert pg.is_vault_trainer("notepad.exe", "notepad train_vault.txt") is False  # not python


def test_active_writer_status_reported(tmp_path, monkeypatch):
    import gateway.write_lock as wl
    monkeypatch.setattr(wl, "DEFAULT_LOCK", tmp_path / "vault_training.lock")
    monkeypatch.setattr(pg, "VaultTrainingLock", lambda *a, **k: wl.VaultTrainingLock(tmp_path / "vault_training.lock"))
    monkeypatch.setattr(wl, "pid_alive", lambda pid: True)
    # a live, fresh lock holder + a matching process → reported as the active writer, no orphan
    lk = wl.VaultTrainingLock(tmp_path / "vault_training.lock")
    lk.acquire(vault_path="/v", command="train_vault")
    holder = lk.read()["pid"]
    monkeypatch.setattr(pg, "list_processes",
                        lambda: [{"pid": holder, "name": "python3.13.exe", "cmdline": "python3.13 train_vault"}])
    st = pg.status()
    assert st["lock"]["indexing_in_progress"] is True
    assert st["active_writer_pid"] == holder
    assert st["orphan_writers"] == [] and st["orphan_writer_warning"] is False


def test_stale_writer_detected_as_orphan(tmp_path, monkeypatch):
    import gateway.write_lock as wl
    monkeypatch.setattr(pg, "VaultTrainingLock", lambda *a, **k: wl.VaultTrainingLock(tmp_path / "none.lock"))
    # no fresh lock, but a vault-trainer process is running -> orphan warning
    monkeypatch.setattr(pg, "list_processes",
                        lambda: [{"pid": 555, "name": "python3.13.exe", "cmdline": "python3.13 train_vault"}])
    st = pg.status()
    assert st["active_writer_pid"] is None
    assert [o["pid"] for o in st["orphan_writers"]] == [555]
    assert st["orphan_writer_warning"] is True
