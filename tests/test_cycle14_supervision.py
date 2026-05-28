# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 14 S5 - pipe-safe supervision tests (real trivial child processes)."""
from __future__ import annotations

import importlib
import json
import sys
import time

ss = importlib.import_module("app.service_supervisor")


def _sup(tmp_path):
    return ss.ServiceSupervisor(log_dir=str(tmp_path / "svc"),
                                diagnostics_dir=str(tmp_path / "diag"))


def test_run_byon_records_memory_service_pid(tmp_path):
    sup = _sup(tmp_path)
    svc = sup.start("memory-service", [sys.executable, "-c", "import time; time.sleep(5)"],
                    stdout_path=str(tmp_path / "out.log"), stderr_path=str(tmp_path / "err.log"),
                    record_diagnostics=True)
    diag = json.loads((tmp_path / "diag" / "memory_service_process.json").read_text(encoding="utf-8"))
    assert diag["pid"] == svc.proc.pid
    assert diag["command"][0] == sys.executable
    sup.stop_all()


def test_run_byon_captures_memory_service_logs(tmp_path):
    sup = _sup(tmp_path)
    sup.start("memory-service", [sys.executable, "-c", "print('HELLO_FROM_CHILD')"],
              stdout_path=str(tmp_path / "out.log"), stderr_path=str(tmp_path / "err.log"))
    sup.services["memory-service"].proc.wait(timeout=10)
    time.sleep(0.2)
    assert "HELLO_FROM_CHILD" in (tmp_path / "out.log").read_text(encoding="utf-8")
    sup.stop_all()


def test_run_byon_redirects_child_output_to_files_not_unread_pipe(tmp_path):
    sup = _sup(tmp_path)
    svc = sup.start("memory-service", [sys.executable, "-c", "import time; time.sleep(5)"],
                    stdout_path=str(tmp_path / "out.log"), stderr_path=str(tmp_path / "err.log"))
    # file-handle redirection => Popen creates NO pipe objects (subprocess.PIPE would set these)
    assert svc.proc.stdout is None
    assert svc.proc.stderr is None
    sup.stop_all()


def test_autorestart_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BYON_MEMORY_SERVICE_AUTORESTART", raising=False)
    sup = _sup(tmp_path)
    sup.start("memory-service", [sys.executable, "-c", "pass"], stdout_path=str(tmp_path / "o.log"))
    sup.services["memory-service"].proc.wait(timeout=10)
    r = sup.restart_if_dead("memory-service")
    assert r["restarted"] is False
    assert r["autorestart_enabled"] is False
    assert sup.unstable is False and sup.is_clean_run() is True
    sup.stop_all()


def test_autorestart_logs_restart_if_enabled(tmp_path, capsys):
    sup = _sup(tmp_path)
    sup.start("memory-service", [sys.executable, "-c", "pass"], stdout_path=str(tmp_path / "o.log"))
    sup.services["memory-service"].proc.wait(timeout=10)
    r = sup.restart_if_dead("memory-service", autorestart=True, max_restarts=1,
                            backoff_seconds=0, sleep=lambda s: None)
    assert r["restarted"] is True and r["restart_count"] == 1
    out = capsys.readouterr().out
    assert "AUTORESTART" in out
    sup.stop_all()


def test_autorestart_run_marked_unstable(tmp_path):
    sup = _sup(tmp_path)
    sup.start("memory-service", [sys.executable, "-c", "pass"], stdout_path=str(tmp_path / "o.log"))
    sup.services["memory-service"].proc.wait(timeout=10)
    sup.restart_if_dead("memory-service", autorestart=True, max_restarts=1,
                        backoff_seconds=0, sleep=lambda s: None)
    assert sup.unstable is True
    assert sup.is_clean_run() is False           # a run with any restart is NOT clean
    sup.stop_all()


def test_unread_pipe_blocks_heavy_logger_but_file_handle_does_not(tmp_path):
    """Positive proof of the pipe-buffer deadlock mechanism (S7 prime suspect):

    a child that writes far more than the ~64KB OS pipe buffer BLOCKS on write when its stdout is
    an UNREAD subprocess.PIPE (the parent never reads), but COMPLETES when stdout is a file handle
    (the supervisor's redirection). This is exactly why file-handle redirection is the cure."""
    import subprocess
    heavy = "import sys\nsys.stdout.write('x' * (1024*1024))\nsys.stdout.flush()\n"

    # UNREAD PIPE: parent does not read -> child blocks once the buffer fills
    p_pipe = subprocess.Popen([sys.executable, "-c", heavy], stdout=subprocess.PIPE)
    blocked = False
    try:
        p_pipe.wait(timeout=4)
    except subprocess.TimeoutExpired:
        blocked = True
    finally:
        p_pipe.kill()
        try:
            p_pipe.communicate(timeout=5)
        except Exception:
            pass
    assert blocked is True, "unread PIPE should block the heavy-logging child (deadlock)"

    # FILE HANDLE (supervisor's redirection): child completes, no deadlock
    out = tmp_path / "heavy.out"
    with open(out, "w", encoding="utf-8") as fh:
        p_file = subprocess.Popen([sys.executable, "-c", heavy], stdout=fh)
        rc = p_file.wait(timeout=15)
    assert rc == 0, "file-handle redirection must let the heavy-logging child complete"
    assert out.stat().st_size >= 1024 * 1024


def test_records_exit_code_when_child_dies(tmp_path):
    sup = _sup(tmp_path)
    sup.start("memory-service", [sys.executable, "-c", "import sys; sys.exit(7)"],
              stdout_path=str(tmp_path / "o.log"), record_diagnostics=True)
    sup.services["memory-service"].proc.wait(timeout=10)
    rc = sup.record_exit("memory-service")
    assert rc == 7
    diag = json.loads((tmp_path / "diag" / "memory_service_process.json").read_text(encoding="utf-8"))
    assert diag["exit_code"] == 7
    sup.stop_all()
