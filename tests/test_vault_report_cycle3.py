"""Cycle 3 Pillar 1 — vault report coherence (stale detection vs memory-service, resume).

A fake memory-service records stored vault facts and returns them on search, so the report's
"agreement" check (stale=false only when report and memory-service agree) is exercised for real.
"""
from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("httpx")

vt = importlib.import_module("gateway.vault_training")
oi = importlib.import_module("gateway.operational_intents")


class FakeMem:
    def __init__(self):
        self.stored = []
        self.consolidated = 0

    def store_fact(self, content, *, source=None, tags=None, thread_id=None, trust=None):
        self.stored.append({"content": content, "source": source, "tags": tags or [],
                            "thread_id": thread_id, "trust": trust})
        return {"success": True}

    def search_facts(self, q, *, top_k=5, threshold=0.35, thread_id=None, scope="thread"):
        return [{"content": s["content"], "metadata": {"source": s["source"]}}
                for s in self.stored if s["thread_id"] == thread_id][:top_k]

    def fce_consolidate(self):
        self.consolidated += 1
        return {"fce_status": "consolidated"}

    def fce_advisory(self):
        return {"advisory": []}

    def stats(self):
        return {"success": True, "by_type": {"fact": len(self.stored)}}


_N = {"a.md": "# A\nFirst note about memory.\n", "b.md": "# B\nSecond note links [[A]].\n",
      "c.md": "# C\nThird note content.\n"}


def _vault(tmp_path, notes):
    v = tmp_path / "vault"
    v.mkdir(parents=True, exist_ok=True)
    for n, b in notes.items():
        (v / n).write_text(b, encoding="utf-8")
    return str(v)


def _run(tmp_path, mem, notes=_N, **kw):
    rd = str(tmp_path / "training")
    rep = vt.train_vault("http://x", vault_path=_vault(tmp_path, notes), mem_client=mem,
                         owner="lucian", report_dir=rd,
                         vaults_base=str(tmp_path / "vaults"), use_lock=False, **kw)
    return rep, rd


def test_full_vault_report_not_stale_after_complete_run(tmp_path):
    mem = FakeMem()
    rep, _ = _run(tmp_path, mem)
    assert rep["complete"] is True and rep["partial"] is False
    assert rep["stale"] is False                       # report agrees with memory-service
    assert rep["vault_facts_in_memory"] >= rep["manifest_active_chunks"] > 0
    # required field surface
    for f in ("vault_path", "vault_hash", "files_scanned", "files_indexed", "files_skipped",
              "chunks_stored", "facts_stored", "trust_tier_distribution", "errors",
              "duration_seconds", "last_completed_file"):
        assert f in rep, f"missing report field {f}"


def test_partial_report_explicit_when_interrupted(tmp_path):
    mem = FakeMem()
    rep, _ = _run(tmp_path, mem, max_files=1)
    assert rep["files_indexed"] == 1
    assert rep["partial"] is True and rep["complete"] is False
    assert rep["stale"] is True                        # incomplete -> never claims agreement


def test_vault_report_matches_memory_service_vault_count(tmp_path):
    mem = FakeMem()
    rep, _ = _run(tmp_path, mem)
    vault_facts = [s for s in mem.stored if s["source"].startswith("vault:")]
    assert rep["vault_facts_in_memory"] == len(vault_facts)
    assert rep["vault_facts_in_memory"] == rep["chunks_stored"]


def test_resume_skips_unchanged_files(tmp_path):
    mem = FakeMem()
    _run(tmp_path, mem)
    n_after_first = len(mem.stored)
    rep2, _ = _run(tmp_path, mem)                      # identical content
    assert rep2["files_skipped"] == 3 and rep2["chunks_stored"] == 0
    assert len(mem.stored) == n_after_first            # nothing re-stored
    assert rep2["complete"] is True and rep2["stale"] is False


def test_resume_continues_after_last_completed_file(tmp_path):
    mem = FakeMem()
    _run(tmp_path, mem)
    changed = dict(_N, **{"c.md": "# C\nThird note CHANGED with new content.\n",
                          "d.md": "# D\nA brand new note added later.\n"})
    rep2, _ = _run(tmp_path, mem, notes=changed)
    # a,b unchanged -> skipped; c changed + d new -> (re)indexed
    assert rep2["files_skipped"] == 2 and rep2["files_indexed"] == 2
    assert rep2["chunks_stored"] > 0 and rep2["complete"] is True


def test_status_handler_reports_complete_when_agreeing(tmp_path):
    mem = FakeMem()
    _, rd = _run(tmp_path, mem)
    o = oi.OperationalIntents(mem, str(tmp_path / "ns"), "s1", report_dir=rd,
                              lifeloop_events=str(tmp_path / "ll.jsonl"))
    _, text, _ = o.handle_vault_training_status()
    assert "completa" in text.lower() and "stale" not in text.lower()
