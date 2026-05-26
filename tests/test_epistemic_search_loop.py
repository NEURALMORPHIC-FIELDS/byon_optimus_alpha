"""Tests for the epistemic search loop — honest source exhaustion before UNKNOWN.

All sources are mocked: no live memory-service, no live Claude, no live web.
"""
from __future__ import annotations

import importlib

import pytest

es = importlib.import_module("gateway.epistemic_search")
ic = importlib.import_module("gateway.internal_clock")
cl = importlib.import_module("gateway.continuous_learning")
ws = importlib.import_module("gateway.web_search")


class FakeMem:
    def __init__(self, fact_hits=None):
        self.fact_hits = fact_hits or []
        self.stored = []

    def search_facts(self, query, **kw):
        return list(self.fact_hits)

    def store_fact(self, fact, **kw):
        self.stored.append({"fact": fact, **kw}); return {"success": True}

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
        return {"hypothesis": self.hypothesis, "suggested_search_queries": [f"{self.hypothesis} 1998"],
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
         action="start", clock=None, question="who won the 1998 FIFA World Cup?"):
    return es.EpistemicSearch().run(
        question=question, user_id="u", session_id="s", namespace_dir=tmp_path,
        mem_client=mem, learning=_learning(tmp_path, mem), web_provider=web, claude_provider=claude,
        allow_web=allow_web, allow_claude=allow_claude, action=action, clock=clock)


def test_memory_hit_skips_web(tmp_path):
    mem = FakeMem([{"content": "BYON is Level 2", "metadata": {"trust": "VERIFIED_PROJECT_FACT"}}])
    web = TrackWeb([_wr("France", "fifa.com")])
    out = _run(tmp_path, mem=mem, web=web, claude=FakeClaude(), allow_web=True,
               question="what operational level is BYON?")
    assert out["epistemic_status"] == "KNOWN" and out["grounded"] is True
    assert web.calls == 0  # committed memory answered → web never touched


def test_no_memory_web_disabled_not_known(tmp_path):
    out = _run(tmp_path, mem=FakeMem([]), claude=FakeClaude("France"), allow_web=False)
    assert out["epistemic_status"] in ("PROVISIONAL_UNVERIFIED", "ASK_USER_FOR_SOURCE", "UNKNOWN")
    assert out["epistemic_status"] != "KNOWN"


def test_claude_hypothesis_not_known_without_source(tmp_path):
    out = _run(tmp_path, mem=FakeMem([]), claude=FakeClaude("France"), allow_web=False)
    assert out["epistemic_status"] != "KNOWN"
    assert out["claude_hypothesis"]["hypothesis"] == "France"


def test_web_confirmed_answer_stores_candidate(tmp_path):
    mem = FakeMem([])
    web = TrackWeb([_wr("France", "fifa.com"), _wr("France", "wikipedia.org")])
    out = _run(tmp_path, mem=mem, web=web, claude=FakeClaude("France"), allow_web=True)
    assert "France" in out["answer"]
    assert out["epistemic_status"] in ("PROVISIONAL", "KNOWN")
    # candidate written to the per-user ledger + mirrored into memory-service
    cand = cl.ContinuousLearning(tmp_path, mem, thread_id="u").list_candidates()
    assert any(c["value"] == "France" for c in cand)


def test_conflicting_web_sources_disputed(tmp_path):
    web = TrackWeb([_wr("France", "fifa.com"), _wr("Brazil", "rumor.net")])
    out = _run(tmp_path, mem=FakeMem([]), web=web, claude=FakeClaude("France"), allow_web=True)
    assert out["epistemic_status"] == "DISPUTED"


def test_stress_clock_reaches_100_needs_more_time(tmp_path):
    clk = ic.InternalResearchClock(deadline_seconds=300.0, started_at=0.0, time_fn=lambda: 300.0)
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False, action="start", clock=clk)
    assert out["epistemic_status"] == "NEEDS_MORE_TIME"
    assert out["research_status"] == "needs_more_time" and out["can_extend"] is True


def test_continue_research_extends_budget(tmp_path):
    clk = ic.InternalResearchClock(deadline_seconds=300.0, started_at=0.0, time_fn=lambda: 300.0,
                                   max_extensions=1)
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False, action="continue", clock=clk)
    assert clk.deadline_seconds == 600.0 and clk.extension_count == 1
    assert out["epistemic_status"] != "NEEDS_MORE_TIME"  # budget extended → proceeds


def test_conclude_now_returns_bounded_answer(tmp_path):
    clk = ic.InternalResearchClock(deadline_seconds=300.0, started_at=0.0, time_fn=lambda: 300.0)
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False, action="conclude", clock=clk)
    assert out["epistemic_status"] != "NEEDS_MORE_TIME"
    assert out["research_status"] == "done"


def test_no_private_secret_search(tmp_path):
    claude, web = FakeClaude(), TrackWeb([_wr("x", "y.com")])
    out = _run(tmp_path, mem=FakeMem([]), web=web, claude=claude, allow_web=True,
               question="what is my bank password?")
    assert out["epistemic_status"] == "UNKNOWN"
    assert claude.calls == 0 and web.calls == 0  # never sent secrets to Claude/web


def test_source_sweep_lists_exhausted_sources(tmp_path):
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False, allow_claude=False)
    assert any(s.startswith("memory") for s in out["sources_searched"])
    assert out["epistemic_status"] in ("UNKNOWN", "ASK_USER_FOR_SOURCE")


def test_response_includes_clock_stress_sources(tmp_path):
    out = _run(tmp_path, mem=FakeMem([]), allow_web=False)
    for k in ("clock", "stress_percent", "sources_searched", "research_status", "phase"):
        assert k in out
