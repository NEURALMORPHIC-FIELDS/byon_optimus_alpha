"""Tests for Cycle 2 Target 2 — Obsidian vault training report (atomic, resume, stale).

Uses a fake memory-service client so no FAISS / model / network is needed. Verifies the
persisted report is atomic and accurate, that resume skips unchanged notes and re-indexes
changed ones, and that the vault-status handler flags a stale report against live memory counts.
"""
from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("httpx")

vt = importlib.import_module("gateway.vault_training")
oi = importlib.import_module("gateway.operational_intents")


class FakeMem:
    """Records stored facts; counts as a stand-in for the canonical memory-service."""

    def __init__(self, facts=0):
        self.stored = []
        self.consolidated = 0
        self._extra_facts = facts

    def store_fact(self, content, *, source=None, tags=None, thread_id=None, trust=None):
        self.stored.append({"content": content, "source": source, "tags": tags or [],
                            "thread_id": thread_id, "trust": trust})
        return {"success": True}

    def search_facts(self, q, **k):
        return [{"content": s["content"], "metadata": {"source": s["source"]}}
                for s in self.stored[:k.get("top_k", 1)]]

    def fce_consolidate(self):
        self.consolidated += 1
        return {"fce_status": "consolidated"}

    def fce_advisory(self):
        return {"advisory": []}

    def stats(self):
        n = len(self.stored) + self._extra_facts
        return {"success": True, "num_contexts": n, "by_type": {"fact": n}}


def _vault(tmp_path, notes):
    v = tmp_path / "vault"
    v.mkdir(parents=True, exist_ok=True)
    for name, body in notes.items():
        (v / name).write_text(body, encoding="utf-8")
    return str(v)


_N1 = "# Alpha\nThis is the first note about morphogenetic memory.\n\n## Detail\nMore text here.\n"
_N2 = "# Beta\nSecond note linking [[Alpha]] with tags #project #byon.\n"
_N3 = "# Gamma\nThird note, standalone content.\n"


def _run(tmp_path, mem, notes, **kw):
    report_dir = str(tmp_path / "training")
    return vt.train_vault("http://unused", vault_path=_vault(tmp_path, notes),
                          mem_client=mem, owner="lucian", report_dir=report_dir, **kw), report_dir


def test_vault_report_atomic_write(tmp_path):
    mem = FakeMem()
    rep, report_dir = _run(tmp_path, mem, {"a.md": _N1, "b.md": _N2})
    p = tmp_path / "training" / "vault_train_report.json"
    assert p.exists()
    on_disk = json.loads(p.read_text(encoding="utf-8"))  # must be complete valid JSON (atomic)
    assert on_disk["files_indexed"] == 2 and on_disk["files_scanned"] == 2
    assert on_disk["chunks_stored"] > 0 and on_disk["vault_hash"]
    assert on_disk["complete"] is True and on_disk["partial"] is False
    # no leftover temp file
    assert not (tmp_path / "training" / "vault_train_report.json.tmp").exists()
    assert mem.consolidated == 1


def test_vault_report_detects_partial(tmp_path):
    mem = FakeMem()
    rep, report_dir = _run(tmp_path, mem, {"a.md": _N1, "b.md": _N2, "c.md": _N3}, max_files=1)
    on_disk = json.loads((tmp_path / "training" / "vault_train_report.json").read_text(encoding="utf-8"))
    assert on_disk["files_indexed"] == 1
    assert on_disk["partial"] is True and on_disk["complete"] is False
    assert on_disk["notes_total"] == 3


def test_vault_training_resume_skips_unchanged(tmp_path):
    mem = FakeMem()
    _run(tmp_path, mem, {"a.md": _N1, "b.md": _N2})
    first_chunks = len(mem.stored)
    # second run, identical content -> everything skipped, nothing re-stored
    rep2, _ = _run(tmp_path, mem, {"a.md": _N1, "b.md": _N2})
    assert rep2["skipped"] == 2 and rep2["chunks_stored"] == 0
    assert len(mem.stored) == first_chunks  # no duplicate stores


def test_vault_training_resume_continues_changed(tmp_path):
    mem = FakeMem()
    _run(tmp_path, mem, {"a.md": _N1, "b.md": _N2})
    # change only b.md -> a is skipped, b is re-indexed
    changed = _N2 + "\n## New section\nAdded content after first run.\n"
    rep2, _ = _run(tmp_path, mem, {"a.md": _N1, "b.md": changed})
    assert rep2["skipped"] == 1 and rep2["files_indexed"] == 1
    assert rep2["chunks_stored"] > 0


# -- stale detection via the operational status handler --------------------
def _write_report(tmp_path, **fields):
    d = tmp_path / "training"
    d.mkdir(parents=True, exist_ok=True)
    base = {"files": 2, "notes_total": 69, "chunks_stored": 3, "partial": False}
    base.update(fields)
    (d / "vault_train_report.json").write_text(json.dumps(base), encoding="utf-8")
    return str(d)


def _status(tmp_path, mem, report_fields):
    ns = tmp_path / "ns"
    (ns).mkdir(parents=True, exist_ok=True)
    o = oi.OperationalIntents(mem, str(ns), "s1", report_dir=_write_report(tmp_path, **report_fields),
                              lifeloop_events=str(tmp_path / "ll.jsonl"))
    return o.handle_vault_training_status()


def test_vault_report_detects_stale_memory_mismatch(tmp_path):
    # report claims 2 notes / 3 chunks, but memory-service holds thousands of facts -> stale
    mem = FakeMem(facts=3810)
    _, text, _ = _status(tmp_path, mem, {"files": 2, "notes_total": 69, "chunks_stored": 3})
    assert "stale" in text.lower() or "partial" in text.lower()
    assert "--train-vault" in text


def test_vault_status_uses_report_plus_memory_counts(tmp_path):
    mem = FakeMem(facts=3810)
    _, text, srcs = _status(tmp_path, mem, {"files": 2, "notes_total": 69, "chunks_stored": 3})
    assert "2" in text and "3810" in text  # both report notes and live memory facts
    assert "memory-service:stats" in srcs and "runtime:training_report" in srcs
