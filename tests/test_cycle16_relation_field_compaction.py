# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 16 - relation-field ledger compaction.

The relation field is an append-only JSONL replayed in full on every request; every
add_entity/add_relation appends a full copy, so the file grows without bound while distinct
state stays small, making per-request status/gaps reads O(history) (observed: a 225K-line
ledger -> 57s status reads -> harness mget timeouts -> false-failed invariant gates). compact()
rewrites one line per current key. Because _load() is already last-record-wins, compaction is
state-preserving: a freshly loaded field is identical, only the file is small.
"""
from __future__ import annotations

from gateway.relation_field import RelationField


def _lines(path) -> int:
    return sum(1 for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())


def test_compaction_shrinks_file_and_preserves_state(tmp_path):
    f = RelationField(str(tmp_path / "rf"))
    # Bloat: reinforce the SAME few entities/relations many times -> many superseded lines.
    for _ in range(200):
        f.add_relation("BYON", "has_component", "D_Cortex", source_id="k1",
                       source_class="SYSTEM_CANONICAL", origin="canonical_schema")
        f.add_relation("D_Cortex", "has_component", "FAISS", source_id="k2",
                       source_class="VERIFIED_PROJECT_FACT")
    before_status = RelationField(str(tmp_path / "rf")).status()
    edges_before = _lines(f.edges_path)
    ents_before = _lines(f.entities_path)
    assert edges_before > 50 and ents_before > 50            # genuinely bloated history

    stats = f.compact()
    assert stats[f.edges_path.name]["after"] < edges_before   # file shrank
    assert _lines(f.edges_path) == stats[f.edges_path.name]["after"]

    # A freshly loaded field after compaction is identical in distinct state.
    reloaded = RelationField(str(tmp_path / "rf"))
    after_status = reloaded.status()
    for k in ("is_truth_authority", "total_entities", "total_relations",
              "committed_relations", "by_relation_type"):
        assert after_status[k] == before_status[k]
    # one line per current record now
    assert _lines(reloaded.edges_path) == after_status["total_relations"]
    assert _lines(reloaded.entities_path) == after_status["total_entities"]


def test_compaction_folds_in_concurrent_appends(tmp_path):
    # A line appended by another writer AFTER this field loaded must survive compaction
    # (compact() re-reads + merges the on-disk file before rewriting).
    f = RelationField(str(tmp_path / "rf"))
    f.add_relation("A", "depends_on", "B", source_id="s1", source_class="VERIFIED_PROJECT_FACT")
    other = RelationField(str(tmp_path / "rf"))
    other.add_relation("C", "depends_on", "D", source_id="s2", source_class="VERIFIED_PROJECT_FACT")
    # f has not seen C->D in memory; compaction must not drop it.
    f.compact()
    reloaded = RelationField(str(tmp_path / "rf"))
    pairs = {(r["subject"], r["object"]) for r in reloaded._rel.values()}
    assert ("A", "B") in pairs and ("C", "D") in pairs
