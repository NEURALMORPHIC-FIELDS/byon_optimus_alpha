"""Tests for the ServiceSupervisor: starts/stops children, cleans up, handles ports."""
from __future__ import annotations

import importlib
import socket
import sys

import pytest

pytest.importorskip("httpx")

ss = importlib.import_module("app.service_supervisor")


def test_supervisor_starts_and_stops_dummy_process(tmp_path):
    sup = ss.ServiceSupervisor(log_dir=str(tmp_path / "svc"))
    sup.start("dummy", [sys.executable, "-c", "import time; time.sleep(30)"])
    assert sup.is_alive("dummy") is True
    sup.stop("dummy")
    assert sup.is_alive("dummy") is False


def test_supervisor_stop_all_cleans_up_on_exit(tmp_path):
    sup = ss.ServiceSupervisor(log_dir=str(tmp_path / "svc"))
    sup.start("a", [sys.executable, "-c", "import time; time.sleep(30)"])
    sup.start("b", [sys.executable, "-c", "import time; time.sleep(30)"])
    assert sup.is_alive("a") and sup.is_alive("b")
    sup.stop_all()
    assert not sup.is_alive("a") and not sup.is_alive("b")


def test_wait_http_fails_fast_if_process_exits(tmp_path):
    sup = ss.ServiceSupervisor(log_dir=str(tmp_path / "svc"))
    # process exits immediately → wait_http must return False, not hang
    sup.start("quick", [sys.executable, "-c", "pass"])
    ok = sup.wait_http("quick", "http://127.0.0.1:59998/none", timeout=5)
    assert ok is False
    sup.stop_all()


def test_port_conflict_detection(tmp_path):
    # No SO_REUSEADDR: on Windows that flag lets a fresh connect succeed against the
    # bound port, which would defeat occupancy detection. Plain bind+listen is reliable.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert ss.is_port_free("127.0.0.1", port) is False
        alt = ss.find_free_port("127.0.0.1", port)
        assert alt != port and ss.is_port_free("127.0.0.1", alt) is True
    finally:
        s.close()
