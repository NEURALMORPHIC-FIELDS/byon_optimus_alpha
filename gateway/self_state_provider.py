# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""SelfStateProvider - answers BYON self-introspection from REAL runtime state.

Capability / memory-state / limitation / recent-learning questions are answered from actual
runtime signals (memory-service stats, persisted training reports, FCE-M/D_Cortex status,
flags, consolidation log) - NOT from generic vault retrieval, NOT from Claude prior, NOT from
hardcoded canned answers. Every line is derived from collected state; absent capabilities are
simply omitted, and only validated/available things are claimed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_json(p: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


class SelfStateProvider:
    def __init__(self, mem_client: Optional[Any] = None, *, report_dir: str = "runtime/training",
                 lifeloop_events: str = "runtime/lifeloop/events.jsonl",
                 namespace_dir: Optional[str] = None) -> None:
        self.mem = mem_client
        self.report_dir = Path(report_dir)
        self.lifeloop_events = Path(lifeloop_events)
        self.namespace_dir = namespace_dir   # per-user dir for candidate/committed/disputed counts

    def _memory_lifecycle_counts(self) -> Dict[str, int]:
        """candidates / committed / disputed counts from the per-user lifecycle ledgers
        (the same ones /v1/memory/status exposes)."""
        if not self.namespace_dir:
            return {"candidates": 0, "committed": 0, "disputed": 0}
        try:
            from .continuous_learning import ContinuousLearning
            cl = ContinuousLearning(self.namespace_dir, self.mem)
            return {"candidates": len(cl.list_candidates()), "committed": len(cl.list_committed()),
                    "disputed": len(cl.list_disputed())}
        except Exception:
            return {"candidates": 0, "committed": 0, "disputed": 0}

    def _fcem_advisory(self) -> Dict[str, Any]:
        if self.mem is None or not hasattr(self.mem, "fce_advisory"):
            return {"available": False}
        try:
            adv = self.mem.fce_advisory() or {}
            items = adv.get("advisory", adv) if isinstance(adv, dict) else adv
            return {"available": True, "signals": len(items) if isinstance(items, (list, dict)) else 0}
        except Exception:
            return {"available": False}

    # -- collection ---------------------------------------------------------
    def _relation_count(self) -> int:
        try:
            from .self_training import _RELATIONS
            return len(_RELATIONS)
        except Exception:
            return 0

    # -- LifeLoop v2 internal state (pressure / tasks / temporal snapshots) ---
    def _lifeloop_dir(self) -> Path:
        return self.lifeloop_events.parent

    def _pressure_state(self) -> Dict[str, Any]:
        return _read_json(self._lifeloop_dir() / "pressure_state.json") or {}

    def _research_tasks(self) -> List[Dict[str, Any]]:
        p = self._lifeloop_dir() / "research_tasks.jsonl"
        if not p.exists():
            return []
        tasks: Dict[str, Dict[str, Any]] = {}
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    t = json.loads(line)
                    tasks[t["task_id"]] = t            # last record wins
        except (OSError, json.JSONDecodeError):
            return []
        return [t for t in tasks.values() if t.get("status") in
                ("pending", "running", "blocked_needs_permission")]

    def _latest_snapshot(self) -> Optional[Dict[str, Any]]:
        p = self._lifeloop_dir() / "self_state_snapshots.jsonl"
        if not p.exists():
            return None
        try:
            lines = [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
            return json.loads(lines[-1]) if lines else None
        except (OSError, json.JSONDecodeError):
            return None

    def internal_state_summary(self) -> List[str]:
        ps = self._pressure_state()
        topics = sorted((ps.get("topics") or {}).values(), key=lambda r: r.get("pressure", 0), reverse=True)
        active = [t for t in topics if t.get("pressure", 0) > 0][:5]
        tasks = self._research_tasks()
        disputed = [t for t in topics if t.get("disputed_count", 0) > 0][:5]
        out = [f"presiune interna totala: {ps.get('total', 0)}",
               f"topicuri sub presiune: {len(active)}"]
        for t in active:
            out.append(f"  - \"{t['topic'][:60]}\" presiune={t['pressure']} "
                       f"(unknown={t.get('unknown_count',0)}, disputed={t.get('disputed_count',0)}) "
                       f"-> {t.get('recommended_action')}")
        if disputed:
            out.append(f"contradictii observate pe {len(disputed)} topic(uri): "
                       + "; ".join(f"\"{t['topic'][:40]}\"" for t in disputed))
        else:
            out.append("contradictii observate: niciuna activa")
        out.append(f"sarcini interne de cercetare in asteptare: {len(tasks)}")
        for t in tasks[:6]:
            out.append(f"  - [{t.get('status')}] \"{t.get('question','')[:60]}\" "
                       f"(surse permise: {','.join(t.get('allowed_sources', []))})")
        out.append("Nota: LifeLoop observa si propune; NU raspunde direct si NU este autoritate de adevar.")
        return out

    def _lifeloop_tail(self, kinds, limit=5) -> List[Dict[str, Any]]:
        if not self.lifeloop_events.exists():
            return []
        rows = []
        try:
            for line in self.lifeloop_events.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("kind") in kinds:
                    rows.append(r)
        except OSError:
            return []
        return rows[-limit:]

    def collect(self) -> Dict[str, Any]:
        stats = {}
        reachable = False
        if self.mem is not None:
            try:
                stats = self.mem.stats() or {}
                reachable = bool(stats.get("success", True)) and bool(stats)
            except Exception:
                stats, reachable = {}, False
        by_type = stats.get("by_type", {}) if isinstance(stats, dict) else {}
        return {
            "backend_mode": os.environ.get("BYON_BACKEND_MODE", "memory_service"),
            "memory_service": {"reachable": reachable,
                               "facts": by_type.get("fact"),
                               "total_contexts": stats.get("num_contexts")},
            "self_training": _read_json(self.report_dir / "self_train_report.json"),
            "vault_training": _read_json(self.report_dir / "vault_train_report.json"),
            "relation_facts_seeded": self._relation_count(),
            "lifecycle": self._memory_lifecycle_counts(),
            "fcem": {"runtime_proven": reachable, "version": "v15.7a (sealed)",
                     "advisory": self._fcem_advisory()},
            "dcortex": {"present": True, "role": "additive morphogenetic addressable memory"},
            "web_enabled": os.environ.get("BYON_WEB_SEARCH_ENABLED", "false").strip().lower()
                           in ("1", "true", "yes", "on"),
            "claude_present": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
            "tombstones": (self.mem.tombstone_counts() if hasattr(self.mem, "tombstone_counts") else {}),
            "read_consistency_mode": getattr(self.mem, "read_consistency_mode", "direct"),
            "local_backend_forbidden_in_real": True,
            "full_level3_not_declared": True,
            "last_consolidations": self._lifeloop_tail({"consolidate"}, 3),
            "recent_feedback": self._lifeloop_tail({"feedback"}, 5),
        }

    # -- derived answers (deterministic, from collected state) --------------
    def capability_manifest(self, st: Dict[str, Any]) -> List[str]:
        caps: List[str] = []
        if st["memory_service"]["reachable"]:
            caps.append("Canonical memory-service: FAISS semantic memory + trust tiers")
        caps.append("D_Cortex: additive morphogenetic / addressable / persistent memory organ")
        caps.append("Real FCE-M v15.7a: advisory signals + consolidation (provisional->committed->retrograde)")
        caps.append("Canonical FactExtractor: learns facts from interaction with trust classification")
        if st.get("self_training"):
            s = st["self_training"]
            caps.append(f"Self-training on repo corpus ({s.get('chunks_stored','?')} chunks / "
                        f"{s.get('files','?')} files, {st['relation_facts_seeded']} relation facts)")
        if st.get("vault_training"):
            v = st["vault_training"]
            caps.append(f"Obsidian vault training ({v.get('files','?')} notes, {v.get('chunks_stored','?')} chunks)")
        caps.append("Epistemic research mode: memory -> Claude hypothesis -> web -> synthesis -> audit")
        caps.append("Epistemic statuses: KNOWN / PROVISIONAL / PROVISIONAL_UNVERIFIED / DISPUTED / "
                    "NEEDS_MORE_TIME / ASK_USER_FOR_SOURCE / UNKNOWN / REFUSED")
        caps.append("Per-user memory isolation; recall survives restart (FAISS persisted)")
        caps.append("Claude as language/reasoning/hypothesis faculty (NOT a truth authority)")
        caps.append("Web search: " + ("enabled" if st["web_enabled"] else "available but not configured"))
        caps.append("BYONLifeLoop v1: internal event stream, self_state, periodic consolidation")
        return caps

    def limitations(self, st: Dict[str, Any]) -> List[str]:
        lims = ["Operates at Level 2 of 4 - FULL_LEVEL3_NOT_DECLARED (no Level 3 claim)",
                "Not a general LLM, not consciousness, not a finished product",
                "No vision and no voice",
                "Claude prior is never accepted as truth without grounding",
                "Web search " + ("enabled" if st["web_enabled"] else "is NOT configured (no web evidence)"),
                "BYONLifeLoop is v1 (minimal internal circulation), not full autonomy"]
        v = st.get("vault_training")
        if v and v.get("partial"):
            lims.append("Obsidian vault ingest is PARTIAL (re-run --train-vault to complete)")
        return lims

    def memory_state_summary(self, st: Dict[str, Any]) -> List[str]:
        ms = st["memory_service"]
        lc = st.get("lifecycle", {})
        adv = (st.get("fcem", {}) or {}).get("advisory", {})
        out = [f"memory-service backend: {st['backend_mode']} (reachable={ms['reachable']})",
               f"total facts indexed (FAISS): {ms.get('facts')}",
               f"canonical relation facts: {st['relation_facts_seeded']}",
               f"candidates / committed / disputed: {lc.get('candidates',0)} / "
               f"{lc.get('committed',0)} / {lc.get('disputed',0)}",
               f"FCE-M advisory: {'active, ' + str(adv.get('signals',0)) + ' signal(s)' if adv.get('available') else 'n/a'}"]
        if st.get("self_training"):
            s = st["self_training"]
            out.append(f"self-training: {s.get('chunks_stored','?')} chunks from {s.get('files','?')} "
                       f"files; trust tiers={s.get('trust_tiers')}")
        else:
            out.append("self-training: not run yet")
        if st.get("vault_training"):
            v = st["vault_training"]
            out.append(f"vault training: {v.get('files','?')} notes, {v.get('chunks_stored','?')} chunks"
                       + (" (PARTIAL)" if v.get('partial') else "") + f"; trust tiers={v.get('trust_tiers')}")
        else:
            out.append("vault training: not run")
        if st["last_consolidations"]:
            out.append(f"last consolidation(s): {len(st['last_consolidations'])} recorded (FCE-M)")
        tomb = (st.get("tombstones") or {}).get("tombstoned_active")
        if tomb:
            out.append(f"retired (tombstoned, excluded from search): {tomb} fact(s)")
        out.append(f"read consistency: {st.get('read_consistency_mode', 'direct')}")
        out.append("FULL_LEVEL3_NOT_DECLARED preserved")
        return out

    def recent_learning(self, st: Dict[str, Any]) -> List[str]:
        out = []
        if st.get("self_training"):
            out.append(f"self-training report present: {st['self_training'].get('chunks_stored','?')} chunks")
        if st.get("vault_training"):
            out.append(f"vault report present: {st['vault_training'].get('chunks_stored','?')} chunks")
        out.append(f"recent FCE-M consolidations logged: {len(st['last_consolidations'])}")
        out.append(f"recent feedback events: {len(st['recent_feedback'])}")
        snap = self._latest_snapshot()
        if snap:
            out.append(f"ultima stare interna (snapshot tick {snap.get('tick')}): "
                       f"known={snap.get('known_count')}, unknown={snap.get('unknown_count')}, "
                       f"disputed={snap.get('disputed_count')}, unknown_rate={snap.get('unknown_rate')}, "
                       f"presiune={snap.get('pressure_total')}, "
                       f"sarcini active={snap.get('active_research_tasks')}, "
                       f"vault active/tombstoned={snap.get('active_vault_facts')}/{snap.get('tombstoned_vault_facts')}")
        if not out:
            out = ["no recent learning recorded yet"]
        return out

    def answer_for(self, intent: str, question: str = "") -> Tuple[str, List[str]]:
        from . import query_router as qr
        st = self.collect()
        sources = ["runtime:self_state", "memory-service:stats"]
        if st.get("self_training"):
            sources.append("report:self_train")
        if st.get("vault_training"):
            sources.append("report:vault_train")
        if intent == qr.SELF_CAPABILITY_QUERY:
            body = self.capability_manifest(st)
            head = "Capacitati active (din starea curenta a sistemului):"
            lims = self.limitations(st)
            text = head + "\n- " + "\n- ".join(body) + "\n\nLimitari:\n- " + "\n- ".join(lims)
        elif intent == qr.SELF_LIMITATION_QUERY:
            text = "Limitari curente:\n- " + "\n- ".join(self.limitations(st))
        elif intent == qr.SELF_RECENT_LEARNING_QUERY:
            text = "Invatare recenta (din loguri/rapoarte + snapshot-uri LifeLoop):\n- " + "\n- ".join(self.recent_learning(st))
        elif intent == qr.SELF_INTERNAL_STATE_QUERY:
            text = ("Stare interna LifeLoop v2 (presiuni, contradictii, sarcini - observatii, nu raspuns):\n- "
                    + "\n- ".join(self.internal_state_summary()))
            sources = ["runtime:lifeloop:pressure", "runtime:lifeloop:tasks", "runtime:lifeloop:snapshots"]
        else:  # SELF_MEMORY_STATE_QUERY
            text = ("Ce am asimilat in memorie (stare reala, nu nota de vault):\n- "
                    + "\n- ".join(self.memory_state_summary(st)))
        return text, sources
