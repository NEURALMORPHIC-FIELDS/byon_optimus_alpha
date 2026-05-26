"""Cycle 4 — substrate hardening: write-lock, content dedup, error classification.

Unit-portable (fake memory-service, isolated dirs). The live behaviours (indexing_in_progress in
the status endpoint, restart recall during indexing) are exercised by the live harness.
"""
from __future__ import annotations

import importlib
import json
import os

import pytest

pytest.importorskip("httpx")

wl = importlib.import_module("gateway.write_lock")
vm = importlib.import_module("gateway.vault_manifest")
ve = importlib.import_module("gateway.vault_errors")
vt = importlib.import_module("gateway.vault_training")


class FakeMem:
    def __init__(self):
        self.stored = []
        self.consolidated = 0

    def store_fact(self, content, *, source=None, tags=None, thread_id=None, trust=None):
        self.stored.append({"content": content, "source": source, "tags": tags or [],
                            "thread_id": thread_id, "trust": trust})
        return {"success": True, "ctx_id": len(self.stored)}

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


# ---------------- write lock (target 3) ----------------
def test_second_writer_refused_when_lock_active(tmp_path, monkeypatch):
    lock_path = tmp_path / "vault_training.lock"
    monkeypatch.setattr(wl, "pid_alive", lambda pid: True)   # holder is alive
    import time
    lock_path.write_text(json.dumps({"pid": 999999, "vault_path": "/x", "command": "train_vault",
                                     "heartbeat_at": time.time()}), encoding="utf-8")
    lk = wl.VaultTrainingLock(lock_path)
    res = lk.acquire(vault_path="/x", command="train_vault")
    assert res["acquired"] is False and "active writer" in res["reason"]
    assert lk.status()["indexing_in_progress"] is True


def test_stale_lock_reclaimed(tmp_path, monkeypatch):
    lock_path = tmp_path / "vault_training.lock"
    monkeypatch.setattr(wl, "pid_alive", lambda pid: False)  # holder is dead
    lock_path.write_text(json.dumps({"pid": 999999, "vault_path": "/x", "command": "train_vault",
                                     "heartbeat_at": 0}), encoding="utf-8")
    lk = wl.VaultTrainingLock(lock_path)
    res = lk.acquire(vault_path="/x", command="train_vault")
    assert res["acquired"] is True and res["reclaimed"] is True
    assert json.loads(lock_path.read_text())["pid"] == os.getpid()
    lk.release()
    assert not lock_path.exists()


def test_status_reports_indexing_in_progress_when_held(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "pid_alive", lambda pid: True)
    lk = wl.VaultTrainingLock(tmp_path / "l.lock")
    lk.acquire(vault_path="/v", command="train_vault")
    st = lk.status()
    assert st["locked"] and st["indexing_in_progress"] and st["pid"] == os.getpid()
    lk.release()
    assert lk.status()["indexing_in_progress"] is False


# ---------------- content dedup (target 2) ----------------
def test_unchanged_chunk_not_rewritten(tmp_path):
    man = vm.VaultManifest("vhash", base=str(tmp_path / "vaults"))
    sha = vm.chunk_sha256("hello world")
    man.record_chunk(rel_path="a.md", file_sha="f1", index=0, chunk_sha=sha, memory_ctx_id=1)
    assert man.has_active_chunk_sha(sha) is True            # second store would be skipped
    assert man.counts()["active"] == 1


def test_manifest_records_superseded_chunks(tmp_path):
    man = vm.VaultManifest("vhash", base=str(tmp_path / "vaults"))
    sha = vm.chunk_sha256("v1 content")
    man.record_chunk(rel_path="a.md", file_sha="f1", index=0, chunk_sha=sha)
    n = man.supersede_file("a.md")
    assert n == 1 and man.counts()["superseded"] == 1
    assert man.has_active_chunk_sha(sha) is False           # no longer active after supersede
    # reload from disk preserves lifecycle
    man2 = vm.VaultManifest("vhash", base=str(tmp_path / "vaults"))
    assert man2.counts()["superseded"] == 1


def test_duplicate_run_does_not_increase_chunk_count(tmp_path):
    mem = FakeMem()
    notes = {"a.md": "# A\nalpha content here.\n", "b.md": "# B\nbeta content here.\n"}
    v = tmp_path / "vault"
    v.mkdir()
    for n, b in notes.items():
        (v / n).write_text(b, encoding="utf-8")
    kw = dict(mem_client=mem, owner="u", report_dir=str(tmp_path / "tr"),
              vaults_base=str(tmp_path / "vaults"), use_lock=False)
    r1 = vt.train_vault("http://x", vault_path=str(v), **kw)
    n_after_first = len(mem.stored)
    r2 = vt.train_vault("http://x", vault_path=str(v), **kw)
    assert r2["chunks_stored"] == 0 and r2["files_skipped"] == 2
    assert len(mem.stored) == n_after_first                 # duplicate run stored nothing


# ---------------- error classification (target 5) ----------------
def test_encoding_error_classified():
    exc = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")
    assert ve.classify_exception(exc, "read")[0] == ve.ENCODING


def test_frontmatter_error_classified():
    assert ve.classify_exception(ValueError("bad yaml"), "frontmatter")[0] == ve.FRONTMATTER


def test_binary_file_skipped(tmp_path):
    p = tmp_path / "bin.md"
    p.write_bytes(b"PK\x03\x04\x00\x00binary\x00data")
    text, err = ve.read_markdown(p)
    assert text is None and err["error_type"] == ve.EMPTY_OR_BINARY_OR_LARGE


def test_encoding_fallback_cp1252(tmp_path):
    p = tmp_path / "n.md"
    p.write_bytes("# Café résumé\nnaïve\n".encode("cp1252"))   # not valid utf-8
    text, err = ve.read_markdown(p)
    assert text is not None and "Caf" in text                 # decoded via fallback ladder


def test_error_report_written(tmp_path):
    log = ve.VaultErrorLog("vhash", base=str(tmp_path / "vaults"))
    log.log("bad.md", ve.ENCODING, "could not decode", "read", True)
    assert log.path.exists()
    rec = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["file_path"] == "bad.md" and rec["error_type"] == ve.ENCODING and rec["phase"] == "read"
    assert log.counts_by_type()[ve.ENCODING] == 1


def test_training_continues_after_bad_file(tmp_path):
    mem = FakeMem()
    v = tmp_path / "vault"
    v.mkdir()
    (v / "good1.md").write_text("# Good1\nfirst good note.\n", encoding="utf-8")
    (v / "bad.md").write_bytes(b"\x00\x01binary garbage\x00")          # binary -> skipped+logged
    (v / "good2.md").write_text("# Good2\nsecond good note.\n", encoding="utf-8")
    rep = vt.train_vault("http://x", vault_path=str(v), mem_client=mem, owner="u",
                         report_dir=str(tmp_path / "tr"), vaults_base=str(tmp_path / "vaults"),
                         use_lock=False)
    assert rep["complete"] is True                       # one bad note did not abort the run
    assert rep["files_indexed"] == 2 and rep["errors"] >= 1
    assert ve.EMPTY_OR_BINARY_OR_LARGE in rep["errors_by_type"]
    # error report exists with file + reason
    errp = tmp_path / "vaults" / rep["vault_hash"] / "errors.jsonl"
    assert errp.exists() and "bad.md" in errp.read_text(encoding="utf-8")


# ---------------- report coherence (target 1) ----------------
def test_full_vault_completion_sets_complete_true(tmp_path):
    mem = FakeMem()
    v = tmp_path / "vault"
    v.mkdir()
    (v / "a.md").write_text("# A\ncontent a.\n", encoding="utf-8")
    rep = vt.train_vault("http://x", vault_path=str(v), mem_client=mem, owner="u",
                         report_dir=str(tmp_path / "tr"), vaults_base=str(tmp_path / "vaults"),
                         use_lock=False)
    assert rep["complete"] is True and rep["partial"] is False
    assert rep["files_scanned"] == rep["eligible_files"] == 1


def test_partial_run_sets_partial_true(tmp_path):
    mem = FakeMem()
    v = tmp_path / "vault"
    v.mkdir()
    for i in range(3):
        (v / f"n{i}.md").write_text(f"# N{i}\nbody {i}.\n", encoding="utf-8")
    rep = vt.train_vault("http://x", vault_path=str(v), mem_client=mem, owner="u",
                         report_dir=str(tmp_path / "tr"), vaults_base=str(tmp_path / "vaults"),
                         use_lock=False, max_files=1)
    assert rep["partial"] is True and rep["complete"] is False and rep["stale"] is True


def test_stale_false_only_when_report_matches_memory(tmp_path):
    mem = FakeMem()
    v = tmp_path / "vault"
    v.mkdir()
    (v / "a.md").write_text("# A\nbody.\n", encoding="utf-8")
    rep = vt.train_vault("http://x", vault_path=str(v), mem_client=mem, owner="u",
                         report_dir=str(tmp_path / "tr"), vaults_base=str(tmp_path / "vaults"),
                         use_lock=False)
    # complete + memory holds every active chunk -> not stale
    assert rep["complete"] is True and rep["stale"] is False
    assert rep["vault_facts_in_memory"] >= rep["manifest_active_chunks"] > 0


# ---------------- health / status reporting (target 7) ----------------
class _HealthMem(FakeMem):
    def health(self):
        return {"_reachable": True, "version": "test"}


def _backend(mem):
    from gateway.memory_service_backend import MemoryServiceBackend
    return MemoryServiceBackend(memory_url="http://x", mem_client=mem, web_provider=False,
                                claude_provider=type("C", (), {"available": False})())


def _write_report(tmp_path, **fields):
    d = tmp_path / "training"
    d.mkdir(parents=True, exist_ok=True)
    base = {"complete": False, "partial": True, "stale": True, "files_scanned": 50,
            "files_indexed": 48, "eligible_files": 843, "errors": 24,
            "errors_by_type": {"encoding": 20, "empty_or_binary_or_large": 4},
            "vault_facts_in_memory": 1200, "manifest_active_chunks": 1180}
    base.update(fields)
    (d / "vault_train_report.json").write_text(json.dumps(base), encoding="utf-8")
    return str(d)


def test_status_reports_vault_partial(tmp_path):
    rd = _write_report(tmp_path)
    ss = _backend(_HealthMem()).substrate_status(report_dir=rd)
    assert ss["vault_report"]["partial"] is True and ss["vault_report"]["complete"] is False
    assert ss["vault_report"]["files_scanned"] == 50


def test_status_reports_error_count(tmp_path):
    rd = _write_report(tmp_path, errors=24)
    ss = _backend(_HealthMem()).substrate_status(report_dir=rd)
    assert ss["vault_report"]["errors"] == 24
    assert ss["vault_report"]["errors_by_type"]["encoding"] == 20


def test_status_reports_recent_buffer_count(tmp_path):
    b = _backend(_HealthMem())
    b.recent_buffer.add("u", "my favorite mountain is Retezat")
    b.recent_buffer.add("u", "my project codename is Helios")
    ss = b.substrate_status(report_dir=_write_report(tmp_path))
    assert ss["recent_write_buffer_count"] == 2


def test_status_reports_lock_active(tmp_path, monkeypatch):
    import gateway.write_lock as wl
    lock_path = tmp_path / "vault_training.lock"
    monkeypatch.setattr(wl, "DEFAULT_LOCK", lock_path)
    monkeypatch.setattr(wl, "pid_alive", lambda pid: True)
    wl.VaultTrainingLock(lock_path).acquire(vault_path="/v", command="train_vault")
    ss = _backend(_HealthMem()).substrate_status(report_dir=_write_report(tmp_path))
    assert ss["indexing_in_progress"] is True and ss["active_writer_pid"] is not None
