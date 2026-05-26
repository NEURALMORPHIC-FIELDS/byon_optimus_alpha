"""Tests for the BYON Active Memory Core (Phases 1-4, 7-9).

All mocked: no live memory-service, no live Claude, no live Node. The canonical FactExtractor
bridge is exercised at the contract level (availability + non-canonical fallback path)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

_REPO = Path(__file__).resolve().parents[1]


class FakeMem:
    def __init__(self):
        self.stored = []
        self.consolidated = 0
        self.receipts = []

    def store_fact(self, fact, **kw):
        self.stored.append({"fact": fact, **kw})
        return {"success": True, "ctx_id": len(self.stored)}

    def fce_consolidate(self):
        self.consolidated += 1
        return {"fce_status": "consolidated"}

    def fce_assimilate_receipt(self, order_id, status, summary=None):
        self.receipts.append({"order_id": order_id, "status": status})
        return {"ok": True}

    def health(self):
        return {"_reachable": True, "version": "4.0.0-faiss"}

    def stats(self):
        return {"num_contexts": len(self.stored)}

    def search_facts(self, *a, **k):
        return []


# ---------------- Phase 1: REAL mode forbids LocalBYONBackend ----------------

def test_real_mode_forbids_local_when_memory_service_missing(monkeypatch, capsys):
    run_byon = importlib.import_module("run_byon")
    import app.runtime_discovery as rdmod
    import app.service_supervisor as ssmod
    import app.secret_prompt as spmod
    monkeypatch.setattr(sys, "argv", ["run_byon.py", "--no-prompt"])
    # main() sets these on os.environ directly; register them with monkeypatch so they are
    # restored after the test and do not leak into other tests.
    monkeypatch.setenv("FCEM_MEMORY_ENGINE_ROOT", "X")
    monkeypatch.setenv("FSOAT_REQUIRE_EXTERNAL_FCEM_RUNTIME", "true")

    class _D:
        repo_root = _REPO
        fcem_root = "X"
        memory_service_server = None
        orchestrator_dir = None
        problems = []
    monkeypatch.setattr(rdmod, "discover", lambda: _D())
    monkeypatch.setattr(ssmod, "is_port_free", lambda h, p: True)
    monkeypatch.setattr(spmod, "ensure_api_key", lambda **k: None)
    rc = run_byon.main()
    out = capsys.readouterr().out.lower()
    assert rc == 2
    assert "memory-service" in out and "local" in out  # requires memory-service; local only via --local-dev


def test_backend_selection_is_memory_service_not_local(monkeypatch):
    from gateway.app import _resolve_backend
    from gateway.config import GatewayConfig
    import gateway.memory_service_backend as msb
    monkeypatch.setenv("BYON_BACKEND_MODE", "memory_service")
    monkeypatch.setattr(msb.MemoryServiceBackend, "_seed_canonical", lambda self: None)
    b = _resolve_backend(GatewayConfig.from_env())
    assert b.__class__.__name__ == "MemoryServiceBackend"


# ---------------- Phase 2: canonical FactExtractor bridge ----------------

def test_fact_extractor_bridge_availability_requires_node_and_key(monkeypatch):
    feb = importlib.import_module("gateway.fact_extractor_bridge")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert feb.available() is False  # no key → not available (no silent fake)


def test_learn_falls_back_non_canonical_when_extractor_unavailable(tmp_path, monkeypatch):
    import gateway.memory_service_backend as msb
    monkeypatch.setattr(msb.MemoryServiceBackend, "_seed_canonical", lambda self: None)
    monkeypatch.setattr(msb.feb, "available", lambda: False)
    mem = FakeMem()
    backend = msb.MemoryServiceBackend(mem_client=mem)
    learning = backend._learning(tmp_path, "u")
    out = backend._learn_from_message("my favorite color is blue", "u", learning)
    assert out["canonical"] is False
    assert any("non_canonical_fallback" in (s.get("source", "") + "".join(s.get("tags", [])))
               for s in mem.stored)


def test_secret_message_is_not_learned(tmp_path, monkeypatch):
    import gateway.memory_service_backend as msb
    monkeypatch.setattr(msb.MemoryServiceBackend, "_seed_canonical", lambda self: None)
    monkeypatch.setattr(msb.feb, "available", lambda: True)
    called = {"n": 0}
    monkeypatch.setattr(msb.feb, "extract_and_store", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {})
    mem = FakeMem()
    backend = msb.MemoryServiceBackend(mem_client=mem)
    learning = backend._learning(tmp_path, "u")
    out = backend._learn_from_message("what is my bank password?", "u", learning)
    assert out.get("skipped") == "secret" and called["n"] == 0


# ---------------- Phase 3: self-training ----------------

def test_self_training_stores_chunks_relations_and_consolidates():
    st = importlib.import_module("gateway.self_training")
    mem = FakeMem()
    rep = st.train_self("http://x", repo_root=_REPO, mem_client=mem)
    assert rep["chunks_stored"] > 0 and rep["relations_stored"] == len(st._RELATIONS)
    assert rep["consolidated"] == "consolidated" and mem.consolidated == 1
    # project self-knowledge is system-scope, committed trust
    assert all(s.get("thread_id") is None for s in mem.stored)
    assert all(s.get("trust") == "VERIFIED_PROJECT_FACT" for s in mem.stored)
    # a relation fact is present
    assert any("D_Cortex" in s["fact"] and "has component" in s["fact"] for s in mem.stored)


# ---------------- Phase 4: vault training ----------------

def _make_vault(tmp_path):
    v = tmp_path / "vault"
    (v / ".obsidian").mkdir(parents=True)
    (v / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")  # must be ignored
    (v / "FCE-M notes.md").write_text(
        "---\ntags: research, memory\n---\n# FCE-M\nFCE-M is the consolidation engine.\n"
        "See [[Architecture]].\n#fcem\n", encoding="utf-8")
    (v / "Architecture.md").write_text("# Architecture\nThe organism has D_Cortex.\n", encoding="utf-8")
    return v


def test_vault_training_stores_chunks_backlinks_and_ignores_obsidian(tmp_path):
    vt = importlib.import_module("gateway.vault_training")
    mem = FakeMem()
    v = _make_vault(tmp_path)
    rep = vt.train_vault("http://x", vault_path=str(v), mem_client=mem, owner="lucian",
                         report_dir=str(tmp_path / "training"),
                         vaults_base=str(tmp_path / "vaults"), use_lock=False)  # isolated
    assert rep["files"] == 2 and rep["chunks_stored"] > 0  # .obsidian/app.json not counted
    assert rep["backlinks"] >= 1  # FCE-M notes -> [[Architecture]]
    assert rep["consolidated"] == "consolidated"
    # vault notes are USER memory (not objective truth), stored under the owner thread
    assert all(s.get("trust") == "EXTRACTED_USER_CLAIM" for s in mem.stored)
    assert all(s.get("thread_id") == "lucian" for s in mem.stored)
    assert not any(".obsidian" in s.get("source", "") for s in mem.stored)
    # tags + backlink provenance captured
    assert any(any(t.startswith("tag:") for t in s.get("tags", [])) for s in mem.stored)
    assert any(any(t.startswith("backlink:") for t in s.get("tags", [])) for s in mem.stored)


# ---------------- Phase 9: feedback as learning signal ----------------

def _backend(monkeypatch, mem):
    import gateway.memory_service_backend as msb
    monkeypatch.setattr(msb.MemoryServiceBackend, "_seed_canonical", lambda self: None)
    return msb.MemoryServiceBackend(mem_client=mem)


def test_feedback_wrong_disputes(tmp_path, monkeypatch):
    mem = FakeMem()
    backend = _backend(monkeypatch, mem)
    out = backend.apply_feedback(user_id="u", namespace_dir=tmp_path, rating="wrong",
                                 value="France won the 1998 World Cup")
    assert out["action"] == "disputed"
    assert any(r["status"] == "failed" for r in mem.receipts)


def test_feedback_important_reinforces(tmp_path, monkeypatch):
    mem = FakeMem()
    backend = _backend(monkeypatch, mem)
    out = backend.apply_feedback(user_id="u", namespace_dir=tmp_path, rating="important",
                                 value="my project codename is Orion")
    assert out["action"] == "reinforced"
    assert any(r["status"] == "success" for r in mem.receipts)
