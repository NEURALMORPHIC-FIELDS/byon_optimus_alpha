# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 15 TRACK I - relation maintenance UI/API endpoints (Gateway-only surface)."""
from __future__ import annotations

import dataclasses

import pytest

pytest.importorskip("fastapi")


def _app(tmp_path):
    from gateway.app import create_app
    from gateway.config import GatewayConfig
    from gateway.alpha_validation import StubBYONBackend
    cfg = dataclasses.replace(GatewayConfig.from_env(), users_root=str(tmp_path / "users"),
                              audit_root=str(tmp_path / "audit"))
    return create_app(cfg, backend=StubBYONBackend())


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    return TestClient(_app(tmp_path))


def test_maintenance_status_endpoint(client):
    r = client.get("/v1/lifeloop/relation-field/maintenance/status")
    assert r.status_code == 200 and "last_maintenance" in r.json()


def test_maintenance_run_endpoint(client):
    client.post("/v1/lifeloop/relation-field/rebuild")
    r = client.post("/v1/lifeloop/relation-field/maintenance/run")
    assert r.status_code == 200
    assert r.json()["report"]["relations_scanned"] >= 1


def test_gaps_endpoint(client):
    client.post("/v1/lifeloop/relation-field/rebuild")
    r = client.get("/v1/lifeloop/relation-field/gaps")
    assert r.status_code == 200 and "gaps" in r.json()


def test_path_score_endpoint(client):
    client.post("/v1/lifeloop/relation-field/rebuild")
    r = client.get("/v1/lifeloop/relation-field/path-score", params={"source": "BYON"})
    assert r.status_code == 200
    j = r.json()
    assert j["found"] is True and j["score"] is not None and "path_weight" in j["score"]
    assert "bottleneck_edge" in j["score"]


def test_relation_task_results_endpoint(client):
    r = client.get("/v1/lifeloop/relation-field/task-results")
    assert r.status_code == 200 and "results" in r.json()


def test_ui_calls_gateway_only_for_maintenance(tmp_path):
    # the UI's only allowed surface is the Gateway: every maintenance op is a registered Gateway
    # route (so the UI never has to touch the memory-service directly for maintenance).
    app = _app(tmp_path)
    paths = {getattr(r, "path", "") for r in app.routes}
    for p in ("/v1/lifeloop/relation-field/maintenance/status",
              "/v1/lifeloop/relation-field/maintenance/run",
              "/v1/lifeloop/relation-field/gaps",
              "/v1/lifeloop/relation-field/gaps/scan",
              "/v1/lifeloop/relation-field/path-score",
              "/v1/lifeloop/relation-field/task-results"):
        assert p in paths, f"missing Gateway route {p}"
