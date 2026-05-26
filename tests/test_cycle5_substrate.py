"""Cycle 5 — read consistency, batch writes, tombstones, compaction (unit-portable)."""
from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("httpx")

tomb_mod = importlib.import_module("gateway.tombstones")
cc = importlib.import_module("gateway.consistent_client")
compact_spec = importlib.util.spec_from_file_location(
    "compact_vault_memory",
    str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts" / "compact_vault_memory.py"))
compact_mod = importlib.util.module_from_spec(compact_spec)
compact_spec.loader.exec_module(compact_mod)


def _hit(ctx_id, content, source="vault:n.md#h", trust="EXTRACTED_USER_CLAIM", tags=None, ts=0):
    return {"ctx_id": ctx_id, "content": content, "similarity": 0.7,
            "metadata": {"source": source, "trust": trust, "tags": tags or [], "timestamp": ts}}


class FakeBase:
    def __init__(self, facts=None):
        self.facts = facts or []
        self.stored = []
        self.write_flag = False
        self.fail_sids = set()

    def search_facts(self, query, *, top_k=5, threshold=0.35, thread_id=None, scope="thread", **k):
        if self.write_flag:
            return []                       # FAISS churn during a write burst returns empty
        return [dict(h) for h in self.facts]

    def store_fact(self, fact, *, source="", tags=None, thread_id=None, trust=None):
        sid = next((t.split("source_id:", 1)[1] for t in (tags or []) if str(t).startswith("source_id:")), None)
        if sid in self.fail_sids:
            raise RuntimeError("store boom")
        self.stored.append({"fact": fact, "source": source, "tags": tags, "thread_id": thread_id,
                            "trust": trust})
        return {"success": True, "ctx_id": len(self.stored)}

    def stats(self):
        return {"success": True, "by_type": {"fact": len(self.facts)}}

    def health(self):
        return {"_reachable": True}


class FakeLock:
    def __init__(self, base):
        self.base = base

    def status(self):
        return {"indexing_in_progress": self.base.write_flag}

    def heartbeat(self):
        pass


def _wrap(base, tmp_path, **kw):
    ts = tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"), audit_path=str(tmp_path / "a.jsonl"))
    return cc.ConsistentMemoryClient(base, tombstones=ts, lock=FakeLock(base),
                                     retries=2, retry_wait=0.01, **kw), ts


# ---------------- T1 read consistency ----------------
def test_status_reports_read_consistency_mode(tmp_path):
    w, _ = _wrap(FakeBase(), tmp_path)
    # Cycle 7: primary mode is the in-engine RW lock; the Cycle-5 snapshot+retry is the fallback
    assert w.read_consistency_mode == "in_engine_rw_lock"
    assert w.fallback_consistency_mode == cc.READ_CONSISTENCY_MODE


def test_concurrent_read_during_write_returns_consistent_result(tmp_path):
    base = FakeBase([_hit(1, "alpha fact")])
    w, _ = _wrap(base, tmp_path)
    assert len(w.search_facts("alpha", top_k=5, threshold=0.0, thread_id="u", scope="thread")) == 1
    base.write_flag = True                  # write burst -> base flickers to empty
    hits = w.search_facts("alpha", top_k=5, threshold=0.0, thread_id="u", scope="thread")
    assert len(hits) == 1 and hits[0]["content"] == "alpha fact"   # served from stable snapshot


def test_no_false_zero_vault_count_during_write(tmp_path):
    base = FakeBase([_hit(1, "v1"), _hit(2, "v2")])
    w, _ = _wrap(base, tmp_path)
    assert w.vault_fact_count("u")["active"] == 2     # warm the snapshot
    base.write_flag = True
    assert w.vault_fact_count("u")["active"] == 2     # never a false zero during the write burst


def test_read_timeout_reported_explicitly(tmp_path):
    base = FakeBase([_hit(1, "x")])
    w, _ = _wrap(base, tmp_path)
    w.search_facts("x", top_k=5, threshold=0.0, thread_id="u", scope="thread")
    base.write_flag = True
    w.search_facts("x", top_k=5, threshold=0.0, thread_id="u", scope="thread")
    assert w.last_read_timed_out is True              # explicitly flagged it served a snapshot


def test_read_does_not_crash_during_vault_training(tmp_path):
    base = FakeBase()                                 # no stable snapshot, write active
    base.write_flag = True
    w, _ = _wrap(base, tmp_path)
    assert w.search_facts("anything", top_k=5, threshold=0.0, thread_id="u", scope="thread") == []


# ---------------- T2 batch writes ----------------
def test_batch_store_preserves_source_id_and_provenance(tmp_path):
    base = FakeBase()
    w, _ = _wrap(base, tmp_path)
    items = [{"fact": "f1", "source": "vault:a.md#h", "tags": ["vault", "source_id:obsidian:a#0:ab"],
              "thread_id": "u", "trust": "EXTRACTED_USER_CLAIM", "source_id": "obsidian:a#0:ab"}]
    res = w.store_facts_batch(items, batch_size=10)
    assert res["stored"] == 1 and res["ids"][0]["source_id"] == "obsidian:a#0:ab"
    assert base.stored[0]["source"] == "vault:a.md#h" and base.stored[0]["trust"] == "EXTRACTED_USER_CLAIM"


def test_batch_store_partial_failure_reports_failed_items(tmp_path):
    base = FakeBase()
    base.fail_sids = {"obsidian:bad#0:zz"}
    w, _ = _wrap(base, tmp_path)
    items = [{"fact": "ok", "tags": ["source_id:obsidian:ok#0:aa"], "source_id": "obsidian:ok#0:aa"},
             {"fact": "bad", "tags": ["source_id:obsidian:bad#0:zz"], "source_id": "obsidian:bad#0:zz"}]
    res = w.store_facts_batch(items, batch_size=10)
    assert res["stored"] == 1 and res["failed"] == 1
    assert res["failed_items"][0]["source_id"] == "obsidian:bad#0:zz"


def test_batch_size_configurable(monkeypatch, tmp_path):
    monkeypatch.setenv("BYON_VAULT_WRITE_BATCH_SIZE", "7")
    base = FakeBase()
    w, _ = _wrap(base, tmp_path)
    res = w.store_facts_batch([{"fact": "x", "source_id": "s"}])
    assert res["batch_size"] == 7


def test_vault_training_uses_batch_store(tmp_path, monkeypatch):
    vt = importlib.import_module("gateway.vault_training")
    called = {"n": 0}

    class SpyMem(FakeBase):
        def store_facts_batch(self, items):
            called["n"] += 1
            for it in items:
                self.store_fact(it["fact"], source=it.get("source", ""), tags=it.get("tags"),
                                thread_id=it.get("thread_id"), trust=it.get("trust"))
            return {"success": True, "ids": [{"source_id": it.get("source_id"), "ctx_id": i}
                                             for i, it in enumerate(items)], "failed_items": []}

        def search_facts(self, q, **k):
            return []

        def fce_consolidate(self):
            return {"fce_status": "c"}

    v = tmp_path / "vault"
    v.mkdir()
    (v / "a.md").write_text("# A\nalpha content.\n", encoding="utf-8")
    mem = SpyMem()
    vt.train_vault("http://x", vault_path=str(v), mem_client=mem, owner="u",
                   report_dir=str(tmp_path / "tr"), vaults_base=str(tmp_path / "vaults"), use_lock=False)
    assert called["n"] >= 1 and len(mem.stored) >= 1


# ---------------- T3 tombstone ----------------
def test_tombstone_requires_reason(tmp_path):
    ts = tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"), audit_path=str(tmp_path / "a.jsonl"))
    assert ts.tombstone(ctx_id=1, reason="").get("ok") is False


def test_tombstoned_fact_not_returned_by_default(tmp_path):
    base = FakeBase([_hit(1, "keep"), _hit(2, "retire")])
    w, ts = _wrap(base, tmp_path)
    ts.tombstone(ctx_id=2, reason="dup")
    hits = w.search_facts("q", top_k=5, threshold=0.0, thread_id="u", scope="thread")
    assert [h["ctx_id"] for h in hits] == [1]


def test_tombstoned_fact_returned_with_include_tombstoned(tmp_path):
    base = FakeBase([_hit(1, "keep"), _hit(2, "retire")])
    w, ts = _wrap(base, tmp_path)
    ts.tombstone(ctx_id=2, reason="dup")
    hits = w.search_facts("q", include_tombstoned=True, top_k=5, threshold=0.0, thread_id="u", scope="thread")
    assert {h["ctx_id"] for h in hits} == {1, 2}


def test_cannot_tombstone_canonical_without_operator_flag(tmp_path):
    ts = tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"), audit_path=str(tmp_path / "a.jsonl"))
    r = ts.tombstone(ctx_id=9, reason="x", trust="SYSTEM_CANONICAL")
    assert r.get("ok") is False and r.get("canonical") is True
    r2 = ts.tombstone(ctx_id=9, reason="x", trust="SYSTEM_CANONICAL", operator=True)
    assert r2.get("ok") is True


def test_tombstone_audit_written(tmp_path):
    apath = tmp_path / "a.jsonl"
    ts = tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"), audit_path=str(apath))
    ts.tombstone(ctx_id=5, reason="dup compaction")
    assert apath.exists()
    rec = json.loads(apath.read_text(encoding="utf-8").splitlines()[0])
    assert rec["action"] == "tombstone" and rec["ctx_id"] == 5 and rec["reason"] == "dup compaction"


def test_tombstone_idempotent(tmp_path):
    ts = tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"), audit_path=str(tmp_path / "a.jsonl"))
    ts.tombstone(ctx_id=3, reason="dup")
    r = ts.tombstone(ctx_id=3, reason="dup")
    assert r.get("idempotent") is True and ts.active_count() == 1


# ---------------- T4 compaction ----------------
def _dup_mem():
    # two identical-content facts (ctx 1 older, 2 newer) + one unique + one canonical dup
    base = FakeBase([
        _hit(1, "same content", ts=100),
        _hit(2, "same content", ts=200),
        _hit(3, "unique content"),
        _hit(10, "verified dup", trust="VERIFIED_PROJECT_FACT", source="vault:verified/x.md#h", ts=1),
        _hit(11, "verified dup", trust="VERIFIED_PROJECT_FACT", source="vault:verified/x.md#h", ts=2),
    ])
    return base


def test_compaction_dry_run_does_not_mutate(tmp_path):
    ts = tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"), audit_path=str(tmp_path / "a.jsonl"))
    rep = compact_mod.compact(_dup_mem(), ts, owner="u", apply=False)
    assert rep["dry_run"] is True and rep["duplicates_found"] >= 1
    assert ts.active_count() == 0                      # nothing actually tombstoned


def test_compaction_apply_tombstones_duplicates(tmp_path):
    ts = tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"), audit_path=str(tmp_path / "a.jsonl"))
    rep = compact_mod.compact(_dup_mem(), ts, owner="u", apply=True)
    assert rep["tombstoned"] >= 1 and ts.active_count() == rep["tombstoned"]
    assert rep["active_after"] == rep["active_before"] - rep["tombstoned"]


def test_compaction_never_tombstones_canonical(tmp_path):
    ts = tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"), audit_path=str(tmp_path / "a.jsonl"))
    rep = compact_mod.compact(_dup_mem(), ts, owner="u", apply=True)        # no --allow-verified
    # the VERIFIED_PROJECT_FACT duplicate (ctx 10/11) must be skipped, only the plain dup retired
    assert rep["tombstoned"] == 1 and rep["skipped"] >= 1


def test_compaction_keeps_newest_active(tmp_path):
    ts = tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"), audit_path=str(tmp_path / "a.jsonl"))
    compact_mod.compact(_dup_mem(), ts, owner="u", apply=True)
    # the older copy (ctx 1) is tombstoned; the newest (ctx 2) is kept
    assert ts.is_tombstoned(_hit(1, "same content")) is True
    assert ts.is_tombstoned(_hit(2, "same content")) is False


def test_compaction_idempotent(tmp_path):
    ts = tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"), audit_path=str(tmp_path / "a.jsonl"))
    base = _dup_mem()
    compact_mod.compact(base, ts, owner="u", apply=True)
    n1 = ts.active_count()
    rep2 = compact_mod.compact(base, ts, owner="u", apply=True)             # second pass
    assert rep2["tombstoned"] == 0 and ts.active_count() == n1              # nothing new retired


# ---------------- T5 self-state / vault-status reporting ----------------
def test_self_state_reports_tombstoned_count(tmp_path):
    from gateway.self_state_provider import SelfStateProvider

    class TombMem(FakeBase):
        def tombstone_counts(self):
            return {"tombstoned_active": 4}
        read_consistency_mode = cc.READ_CONSISTENCY_MODE
    st = SelfStateProvider(TombMem(), report_dir=str(tmp_path)).collect()
    assert st["tombstones"]["tombstoned_active"] == 4
    assert st["read_consistency_mode"] == cc.READ_CONSISTENCY_MODE
