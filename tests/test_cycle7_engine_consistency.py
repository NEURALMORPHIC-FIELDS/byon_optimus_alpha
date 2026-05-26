"""Cycle 7 target 1 — engine-level read/write consistency coordination."""
from __future__ import annotations

import importlib
import threading
import time

import pytest

pytest.importorskip("httpx")

ec = importlib.import_module("gateway.engine_consistency")
cc = importlib.import_module("gateway.consistent_client")
tomb_mod = importlib.import_module("gateway.tombstones")


class EngineAwareBase:
    """A reader that would return a partial (empty) result WHILE a write batch is in progress —
    the engine coordination must make the reader wait for commit before reading."""
    def __init__(self, engine, data):
        self.engine = engine
        self.data = data

    def search_facts(self, q, **k):
        return [] if self.engine.status()["writing"] else [dict(h) for h in self.data]


class FakeLock:
    def status(self):
        return {"indexing_in_progress": False}


def _engine(tmp_path):
    return ec.EngineConsistency(state_path=tmp_path / "memory_engine.json")


def test_status_reports_in_engine_consistency(tmp_path):
    e = _engine(tmp_path)
    st = e.status()
    assert st["read_consistency_mode"] == "in_engine_rw_lock"
    assert "snapshot_version" in st and "last_consistent_read_ts" in st


def test_begin_commit_updates_signal(tmp_path):
    e = _engine(tmp_path)
    bid = e.begin_write()
    assert e.status()["writing"] is True and e.status()["snapshot_version"] == bid
    e.commit_write(bid)
    assert e.status()["writing"] is False and e.status()["last_write_batch_id"] == bid


def test_in_engine_read_during_write_consistent(tmp_path):
    e = _engine(tmp_path)
    base = EngineAwareBase(e, [{"ctx_id": 1, "content": "alpha"}])
    w = cc.ConsistentMemoryClient(base, lock=FakeLock(), engine=e,
                                  tombstones=tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"),
                                                                     audit_path=str(tmp_path / "a.jsonl")))
    bid = e.begin_write()                                   # a write batch starts

    def _commit():
        time.sleep(0.15)
        e.commit_write(bid)
    threading.Thread(target=_commit, daemon=True).start()
    hits = w.search_facts("alpha", top_k=5, threshold=0.0, thread_id="u", scope="thread")
    assert len(hits) == 1 and hits[0]["content"] == "alpha"  # waited for commit -> consistent read


def test_no_false_zero_inside_memory_service(tmp_path):
    e = _engine(tmp_path)
    base = EngineAwareBase(e, [{"ctx_id": 1, "content": "x"}, {"ctx_id": 2, "content": "y"}])
    w = cc.ConsistentMemoryClient(base, lock=FakeLock(), engine=e,
                                  tombstones=tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"),
                                                                     audit_path=str(tmp_path / "a.jsonl")))
    bid = e.begin_write()
    threading.Thread(target=lambda: (time.sleep(0.1), e.commit_write(bid)), daemon=True).start()
    assert len(w.search_facts("q", top_k=5, threshold=0.0, thread_id="u", scope="thread")) == 2


def test_wait_consistent_explicit_timeout(tmp_path):
    e = _engine(tmp_path)
    e.begin_write()                                        # never commit
    t0 = time.time()
    consistent = e.wait_consistent(timeout=0.2)
    assert consistent is False and (time.time() - t0) >= 0.2  # explicit, bounded timeout


def test_stale_writer_not_considered_active(tmp_path):
    e = _engine(tmp_path)
    e._write({"writing": True, "writer_pid": 999999999, "write_batch_id": 5,
              "write_started_ts": time.time()})
    assert e.status()["writing"] is False                  # dead writer pid -> not active


def test_status_reports_in_engine_consistency_via_client(tmp_path):
    e = _engine(tmp_path)
    w = cc.ConsistentMemoryClient(EngineAwareBase(e, []), lock=FakeLock(), engine=e,
                                  tombstones=tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"),
                                                                     audit_path=str(tmp_path / "a.jsonl")))
    assert w.read_consistency_mode == "in_engine_rw_lock"
    st = w.engine_consistency_status()
    assert st["read_consistency_mode"] == "in_engine_rw_lock"
    assert st["fallback_mode"] == cc.READ_CONSISTENCY_MODE   # boundary wrapper remains as fallback


def test_boundary_wrapper_still_works_as_fallback(tmp_path):
    # engine idle; base flickers empty while the (boundary) lock says indexing -> snapshot fallback
    class FlickerBase:
        def __init__(self):
            self.flue = False
            self.data = [{"ctx_id": 1, "content": "z"}]

        def search_facts(self, q, **k):
            return [] if self.flue else [dict(h) for h in self.data]

    class IndexingLock:
        def __init__(self, b):
            self.b = b

        def status(self):
            return {"indexing_in_progress": self.b.flue}

    base = FlickerBase()
    w = cc.ConsistentMemoryClient(base, lock=IndexingLock(base), engine=_engine(tmp_path),
                                  retries=2, retry_wait=0.01,
                                  tombstones=tomb_mod.TombstoneStore(path=str(tmp_path / "t.jsonl"),
                                                                     audit_path=str(tmp_path / "a.jsonl")))
    w.search_facts("q", top_k=5, threshold=0.0, thread_id="u", scope="thread")  # warm snapshot
    base.flue = True                                       # boundary lock active + base empty
    hits = w.search_facts("q", top_k=5, threshold=0.0, thread_id="u", scope="thread")
    assert len(hits) == 1 and w.last_read_timed_out is True  # served from snapshot fallback
