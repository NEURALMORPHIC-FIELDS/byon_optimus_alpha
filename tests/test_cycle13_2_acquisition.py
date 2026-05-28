"""Cycle 13.2 - evidence acquisition extension of the epistemic loop.

The acquisition tiers (project files, corpus, external-LLM advisory, budget) are ADDITIVE: they
escalate only when retrieved memory is insufficient, they never become a parallel engine, and the
existing memory-grounded KNOWN/UNKNOWN/DISPUTED behavior is unchanged. All sources are mocked: no
live memory-service, no live Claude, no live web, no live external LLM.
"""
from __future__ import annotations

import importlib

import pytest

es = importlib.import_module("gateway.epistemic_search")
cl = importlib.import_module("gateway.continuous_learning")
ws = importlib.import_module("gateway.web_search")
ep = importlib.import_module("gateway.acquisition.evidence_packet")
acq = importlib.import_module("gateway.acquisition.acquisition")


class FakeMem:
    def __init__(self, fact_hits=None):
        self.fact_hits = fact_hits or []
        self.stored = []

    def search_facts(self, query, **kw):
        return list(self.fact_hits)

    def store_fact(self, fact, **kw):
        self.stored.append({"fact": fact, **kw})
        return {"success": True}

    def fce_consolidate(self):
        return {"fce_status": "consolidated"}

    def stats(self):
        return {}


class FakeClaude:
    available = True

    def __init__(self, hypothesis="France"):
        self.hypothesis = hypothesis
        self.calls = 0

    def propose(self, question, memory_hits, uncertainty=""):
        self.calls += 1
        return {"hypothesis": self.hypothesis, "suggested_search_queries": [self.hypothesis],
                "possible_entities": [self.hypothesis], "confidence": 0.6, "requires_verification": True}


class TrackWeb(ws.WebSearchProvider):
    name = "track"
    available = True

    def __init__(self, results):
        self.results = results
        self.calls = 0

    def search(self, query, max_results=5):
        self.calls += 1
        return list(self.results)


def _wr(claim, domain):
    return ws.WebResult(title=claim, url=f"https://{domain}/x", snippet=f"{claim} won",
                        source_domain=domain, claim=claim)


def _learning(tmp_path, mem):
    return cl.ContinuousLearning(tmp_path, mem, thread_id="u")


def _run(tmp_path, *, mem, web=None, claude=None, allow_web=False, allow_claude=True,
         action="start", clock=None, question="who won the 1998 FIFA World Cup?", acq_ctx=None):
    return es.EpistemicSearch().run(
        question=question, user_id="u", session_id="s", namespace_dir=tmp_path,
        mem_client=mem, learning=_learning(tmp_path, mem), web_provider=web, claude_provider=claude,
        allow_web=allow_web, allow_claude=allow_claude, action=action, clock=clock,
        acquisition_context=acq_ctx)


def _project_repo(tmp_path, body):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "ARCHITECTURE.md").write_text("# Architecture\n\n" + body + "\n", encoding="utf-8")
    return str(root)


def _packet_types(out):
    return {p["source"]["type"] for p in (out.get("acquisition") or {}).get("packets", [])}


# 1 -------------------------------------------------------------------------
def test_empty_memory_triggers_acquisition_not_immediate_unknown(tmp_path):
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False, allow_claude=False)
    record = out["acquisition"]
    assert record["ran"] is True
    assert record["tiers_run"]                      # at least one acquisition tier was attempted
    assert any(s.startswith("acquisition:") for s in out["sources_searched"])


# 2 -------------------------------------------------------------------------
def test_partial_memory_triggers_missing_slot_acquisition(tmp_path):
    # an uncommitted hit covering only part of the question -> still insufficient -> acquisition
    mem = FakeMem([{"content": "FIFA is a football body", "metadata": {"trust": "PROVISIONAL_WEB"},
                    "score": 0.4}])
    out = _run(tmp_path, mem=mem, allow_web=False, allow_claude=False,
               question="who won the 1998 FIFA World Cup final?")
    suff = out["acquisition"]["sufficiency"]
    assert suff["sufficient"] is False
    assert suff["missing_slots"]                    # some question slots remain uncovered
    assert out["acquisition"]["ran"] is True


# 3 -------------------------------------------------------------------------
def test_project_question_hits_project_files_before_external_llm(tmp_path):
    root = _project_repo(tmp_path, "BYON is the orchestrator and epistemic auditor of the system.")
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False,
               question="what is BYON architecture and orchestrator role?",
               acq_ctx={"repo_root": root})
    assert "project_file" in _packet_types(out)
    srcs = out["sources_searched"]
    assert "acquisition:project_files" in srcs
    if "acquisition:external_llm" in srcs:
        assert srcs.index("acquisition:project_files") < srcs.index("acquisition:external_llm")


# 4 -------------------------------------------------------------------------
def test_current_fact_question_routes_to_web(tmp_path):
    web = TrackWeb([_wr("Paris", "wikipedia.org")])
    out = _run(tmp_path, mem=FakeMem([]), web=web, claude=FakeClaude("Paris"), allow_web=True,
               question="what is the current capital of France today?")
    assert web.calls >= 1
    assert any(s.startswith("web:") for s in out["sources_searched"])


# 5 -------------------------------------------------------------------------
def test_book_question_routes_to_corpus_adapter(tmp_path):
    book = tmp_path / "book.md"
    book.write_text("# Chapter 2\n\nPhotosynthesis converts light into chemical energy in plants.\n",
                    encoding="utf-8")
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False,
               question="what does the book say about photosynthesis in plants?",
               acq_ctx={"corpus_path": str(book)})
    assert "corpus" in _packet_types(out)


# 6 -------------------------------------------------------------------------
def test_paid_only_unavailable_yields_budget_required_not_fabrication(tmp_path):
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False, allow_claude=False,
               question="what is the proprietary licensed figure for X?",
               acq_ctx={"paid_source_required": True,
                        "paid_source_needed": "a licensed market-data API"})
    assert out["epistemic_status"] == "BUDGET_REQUIRED"
    req = out["acquisition"]["budget_request"]
    for k in ("reason", "source_needed", "expected_gain", "estimated_cost", "free_alternatives",
              "post_acquisition_memory_plan"):
        assert k in req
    assert out["answer"] == ""                      # never a fabricated answer


# 7 -------------------------------------------------------------------------
def test_external_llm_authority_advisory_never_known(tmp_path):
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False,
               question="what is the population estimate of Atlantis?",
               acq_ctx={"external_models": ["openai"],
                        "external_model_caller": lambda model, q: "About ten thousand"})
    authorities = [p["trust"]["authority"] for p in out["acquisition"]["packets"]]
    assert ep.EXTERNAL_LLM_ADVISORY in authorities
    assert out["epistemic_status"] != "KNOWN"


# 8 -------------------------------------------------------------------------
def test_model_prior_never_becomes_verified_fact(tmp_path):
    mem = FakeMem([])
    out = _run(tmp_path, mem=mem, claude=FakeClaude("France"), allow_web=False)
    assert out["epistemic_status"] != "KNOWN"
    # the unverified prior is not written to memory as a committed/verified fact
    assert not any(s.get("trust") in ("VERIFIED_PROJECT_FACT", "SYSTEM_CANONICAL", "DOMAIN_VERIFIED")
                   for s in mem.stored)


# 9 -------------------------------------------------------------------------
def test_acquired_item_is_well_formed_packet_with_provenance(tmp_path):
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False,
               question="what is the population estimate of Atlantis?",
               acq_ctx={"external_models": ["openai"],
                        "external_model_caller": lambda model, q: "About ten thousand"})
    packets = out["acquisition"]["packets"]
    assert packets
    p = packets[0]
    assert "packet_id" in p
    for section in ("source", "content", "trust", "memory_write"):
        assert section in p
    assert {"type", "id", "title", "url", "file_path", "model_id", "timestamp"} <= set(p["source"])
    assert {"authority", "confidence", "freshness", "provenance_complete"} <= set(p["trust"])
    assert p["source"]["model_id"] == "openai"      # provenance is concrete, not vague


# 10 ------------------------------------------------------------------------
def test_contradictory_acquired_evidence_disputed(tmp_path):
    def caller(model, q):
        return "France" if model == "openai" else "Brazil"
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False,
               question="who won the contested final?",
               acq_ctx={"external_models": ["openai", "gemini"], "external_model_caller": caller})
    assert out["epistemic_status"] == "DISPUTED"


# 11 ------------------------------------------------------------------------
def test_synthesis_receives_packets_from_all_source_types(tmp_path):
    root = _project_repo(tmp_path, "BYON orchestrator architecture and auditor role description.")
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False,
               question="what is BYON architecture orchestrator role?",
               acq_ctx={"repo_root": root, "external_models": ["openai"],
                        "external_model_caller": lambda model, q: "an external opinion on BYON"})
    types = _packet_types(out)
    assert "project_file" in types and "external_llm" in types
    # the memory and web representations also reduce to packets the loop can reason over uniformly
    mp = ep.memory_hit_to_packet({"content": "x", "metadata": {"trust": "VERIFIED_PROJECT_FACT"}})
    wp = ep.web_result_to_packet(_wr("y", "z.com"))
    assert mp.source.type == "memory" and wp.source.type == "web"
    assert "acquisition" in out["synthesis"]


# 12 ------------------------------------------------------------------------
def test_previously_empty_memory_answers_from_acquired_evidence(tmp_path):
    root = _project_repo(tmp_path, "BYON is the orchestrator and epistemic auditor; the Auditor is "
                                   "mandatory and the Executor is air-gapped.")
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False,
               question="what is the BYON orchestrator and auditor architecture?",
               acq_ctx={"repo_root": root})
    assert "project_file" in _packet_types(out)
    assert out["answer"]                            # an answer exists from acquired evidence
    assert out["epistemic_status"] != "UNKNOWN"


# 13 ------------------------------------------------------------------------
def test_insufficient_evidence_is_uncertainty_not_refusal_by_memory_absence(tmp_path):
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False, allow_claude=False,
               question="what is the exact value of an obscure unknowable constant?")
    assert out["acquisition"]["ran"] is True        # it TRIED to acquire, did not just refuse
    assert out["epistemic_status"] != "REFUSED"
    assert out["epistemic_status"] != "KNOWN"
    assert out["epistemic_status"] in ("ASK_USER_FOR_SOURCE", "UNKNOWN", "PROVISIONAL_UNVERIFIED")


# 14 ------------------------------------------------------------------------
def test_every_acquisition_is_auditable(tmp_path):
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False,
               question="what is the population estimate of Atlantis?",
               acq_ctx={"external_models": ["openai"],
                        "external_model_caller": lambda model, q: "About ten thousand"})
    record = out["acquisition"]
    assert record["tiers_run"]
    assert record["packets"]
    for p in record["packets"]:
        assert p["source"]["type"]                  # every packet records where it came from
    assert any(s.startswith("acquisition:") for s in out["sources_searched"])


# 15 ------------------------------------------------------------------------
def test_existing_memory_grounded_behavior_unchanged(tmp_path):
    # committed memory -> KNOWN, web never touched
    mem = FakeMem([{"content": "BYON is Level 2", "metadata": {"trust": "VERIFIED_PROJECT_FACT"}}])
    web = TrackWeb([_wr("France", "fifa.com")])
    out = _run(tmp_path, mem=mem, web=web, claude=FakeClaude(), allow_web=True,
               question="what operational level is BYON?")
    assert out["epistemic_status"] == "KNOWN" and out["grounded"] is True
    assert web.calls == 0

    # empty memory, web disabled, no claude -> honest non-KNOWN, not fabricated
    out2 = _run(tmp_path, mem=FakeMem([]), allow_web=False, allow_claude=False)
    assert out2["epistemic_status"] in ("UNKNOWN", "ASK_USER_FOR_SOURCE")

    # conflicting web sources -> DISPUTED
    web2 = TrackWeb([_wr("France", "fifa.com"), _wr("Brazil", "rumor.net")])
    out3 = _run(tmp_path, mem=FakeMem([]), web=web2, claude=FakeClaude("France"), allow_web=True)
    assert out3["epistemic_status"] == "DISPUTED"
