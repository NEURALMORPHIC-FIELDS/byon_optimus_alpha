# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 16 TASK 1 - scoped audit flag require_independent_source.

For verify_with_project_source / resolve_dispute gap-repair, the acquisition phase does NOT
short-circuit on existing memory grounding; it runs the project_files/external pass to seek a
source independent of the cached (vault) grounding. Normal retrieval keeps memory-wins precedence.
"""
from __future__ import annotations

import importlib

es = importlib.import_module("gateway.epistemic_search")
cl = importlib.import_module("gateway.continuous_learning")
from gateway.relation_field import RelationField
from gateway.relation_task_results import ingest_relation_task_result


class GroundedMem:
    read_consistency_mode = "direct"

    def __init__(self, hit):
        self._hit = hit

    def health(self):
        return {"_reachable": True}

    def search_facts(self, q, **kw):
        return [dict(self._hit)]

    def store_fact(self, *a, **k):
        return {"success": True}

    def stats(self):
        return {}

    def fce_consolidate(self):
        return {"fce_status": "consolidated"}


def _project_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "ARCHITECTURE.md").write_text(
        "# Architecture\n\nBYON architecture overview: BYON is the orchestrator and epistemic "
        "auditor; Helios is a depends_on component in the architecture.\n", encoding="utf-8")
    return str(root)


def _run(tmp_path, mem, question, acq_ctx=None):
    learning = cl.ContinuousLearning(tmp_path, mem, thread_id="lifeloop")
    return es.EpistemicSearch().run(
        question=question, user_id="lifeloop", session_id="s", namespace_dir=tmp_path,
        mem_client=mem, learning=learning, allow_web=False, allow_claude=False, action="start",
        acquisition_context=acq_ctx)


_VAULT_HIT = {"content": "BYON depends_on Helios", "score": 0.9, "similarity": 0.9,
              "metadata": {"trust": "VERIFIED_PROJECT_FACT", "source": "relation:BYON->depends_on->Helios"}}


def test_verify_task_with_grounded_vault_relation_still_runs_project_pass(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mem = GroundedMem(_VAULT_HIT)
    repo = _project_repo(tmp_path)
    q = "find a verified/project source for: BYON depends_on Helios architecture"
    base = _run(tmp_path, mem, q)                      # no flag -> grounded, short-circuits
    assert base["epistemic_status"] == "KNOWN"
    out = _run(tmp_path, mem, q, acq_ctx={"require_independent_source": True, "repo_root": repo})
    assert out["acquisition"]["ran"] is True
    types = {p["source"]["type"] for p in out["acquisition"]["packets"]}
    assert "project_file" in types                     # project pass fires DESPITE committed grounding


def test_verify_task_returns_independent_source_or_honest_none(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = _run(tmp_path, GroundedMem(_VAULT_HIT),
               "find a verified/project source for: BYON architecture orchestrator role",
               acq_ctx={"require_independent_source": True, "repo_root": _project_repo(tmp_path)})
    types = {p["source"]["type"] for p in out["acquisition"]["packets"]}
    if "project_file" in types:
        assert out["answer"]                           # an independent source was returned
    else:
        assert out["epistemic_status"] in ("UNKNOWN", "ASK_USER_FOR_SOURCE",
                                           "PROVISIONAL_UNVERIFIED")   # honest none, not fabricated


def test_disputed_task_seeks_beyond_current_grounding(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mem = GroundedMem({"content": "BYON depends_on Helios", "score": 0.8, "similarity": 0.8,
                       "metadata": {"trust": "EXTRACTED_USER_CLAIM", "source": "vault:note"}})
    out = _run(tmp_path, mem, "resolve dispute: BYON depends_on Helios architecture",
               acq_ctx={"require_independent_source": True, "repo_root": _project_repo(tmp_path)})
    assert out["acquisition"]["ran"] is True
    assert "project_files" in out["acquisition"]["tiers_run"]   # sought beyond current grounding


def test_normal_query_unchanged_memory_still_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    hit = {"content": "Paris is the capital of France", "score": 0.9, "similarity": 0.9,
           "metadata": {"trust": "DOMAIN_VERIFIED", "source": "domain:geo"}}
    out = _run(tmp_path, GroundedMem(hit), "what is the capital of France?",
               acq_ctx={"repo_root": _project_repo(tmp_path)})   # NO require_independent_source
    assert out["epistemic_status"] == "KNOWN"          # memory wins, fast path
    assert out.get("acquisition") is None              # acquisition never reached (precedence intact)


def test_contradiction_from_independent_source_creates_disputed_challenger(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mem = GroundedMem({"content": "BYON depends_on Helios", "score": 0.9, "similarity": 0.9,
                       "metadata": {"trust": "EXTRACTED_USER_CLAIM", "source": "vault:note"}})
    out = _run(tmp_path, mem, "find a verified/project source for: BYON depends_on Helios architecture",
               acq_ctx={"require_independent_source": True, "repo_root": _project_repo(tmp_path),
                        "external_models": ["openai"],
                        "external_model_caller": lambda m, q: "BYON depends on Zephyr instead, not Helios"})
    assert out["epistemic_status"] == "DISPUTED"       # independent sources disagree
    f = RelationField(str(tmp_path / "rf"))
    ingest_relation_task_result(
        gap={"relation_id": "r1", "subject": "BYON", "object": "Helios",
             "gap_type": "verify_with_project_source", "predicate": "depends_on"},
        result={"epistemic_status": out["epistemic_status"], "answer_summary": out.get("answer", ""),
                "task_id": "t1"}, field=f)
    challengers = [r for r in f._rel.values() if r["subject"] == "BYON" and r["object"] == "Helios"
                   and (r.get("contradiction_count", 0) > 0 or r.get("status") == "disputed")]
    assert challengers
