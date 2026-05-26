"""Tests for runtime discovery."""
from __future__ import annotations

import importlib
from pathlib import Path

rd = importlib.import_module("app.runtime_discovery")


def test_discover_returns_repo_root_and_gateway_module():
    d = rd.discover()
    assert (d.repo_root / "gateway" / "server.py").exists()
    assert d.gateway_module == "gateway.server"


def test_discover_reports_fcem_or_problem():
    d = rd.discover()
    if d.fcem_root:
        assert (Path(d.fcem_root) / "d_cortex" / "__init__.py").exists()
    else:
        assert any("FCE-M" in p for p in d.problems)


def test_memory_service_discovery_optional():
    d = rd.discover()
    # memory-service is optional; if found it must be a real server.py path
    if d.memory_service_server is not None:
        assert d.memory_service_server.name == "server.py"
