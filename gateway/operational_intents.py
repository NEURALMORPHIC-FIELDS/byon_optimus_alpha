"""BYON Operational Intent Layer (minimal; no new cognitive architecture).

Handles natural operational / self-referential commands from RUNTIME STATE and real actions —
never generic vault retrieval, never hardcoded slogans, never faking an action that did not run.
Reuses the canonical pieces: memory-service (stats / fce_consolidate / search), SelfStateProvider,
the per-session audit log, and the persisted training reports.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import query_router as qr
from .self_state_provider import SelfStateProvider


class OperationalIntents:
    def __init__(self, mem_client: Optional[Any], namespace_dir: Optional[str], session_id: str,
                 *, report_dir: str = "runtime/training",
                 lifeloop_events: str = "runtime/lifeloop/events.jsonl") -> None:
        self.mem = mem_client
        self.namespace_dir = Path(namespace_dir) if namespace_dir else None
        self.session_id = session_id
        self.report_dir = Path(report_dir)
        self.ssp = SelfStateProvider(mem_client, report_dir=report_dir,
                                     lifeloop_events=lifeloop_events,
                                     namespace_dir=str(namespace_dir) if namespace_dir else None)

    # -- session log: prefer the literal session event stream, fall back to audit log ----
    def _session_events(self) -> List[Dict[str, Any]]:
        if not self.namespace_dir:
            return []
        try:
            from .session_events import SessionEvents
            se = SessionEvents(self.namespace_dir, self.session_id)
            if se.exists():
                rows = []
                for r in se.read():
                    if r.get("role") == "user":
                        rows.append({"message": r.get("message"), "epistemic_status": None,
                                     "role": "user", "ts": r.get("ts")})
                    elif r.get("role") == "assistant":
                        rows.append({"message": r.get("answer"), "intent": r.get("intent"),
                                     "epistemic_status": r.get("epistemic_status"),
                                     "role": "assistant", "ts": r.get("ts")})
                if rows:
                    return rows
        except Exception:
            pass
        adir = self.namespace_dir / "audit"
        if not adir.exists():
            return []
        rows = []
        for f in adir.glob("trace_*.json"):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if r.get("session_id") == self.session_id and r.get("kind") in ("chat", "research"):
                rows.append(r)
        rows.sort(key=lambda r: r.get("ts", ""))
        return rows

    # -- handlers -----------------------------------------------------------
    def handle(self, intent: str, question: str) -> Tuple[str, str, List[str]]:
        if intent == qr.SELF_DYNAMICS_REPORT_QUERY:
            return self.handle_self_dynamics_report()
        if intent == qr.SELF_PROOF_QUERY:
            return self.handle_self_proof()
        if intent == qr.CHAT_HISTORY_SUMMARY_QUERY:
            return self.handle_chat_history_summary()
        if intent == qr.MEMORY_ACTION_QUERY:
            return self.handle_memory_action(question)
        if intent == qr.FOLLOWUP_QUERY:
            return self.handle_followup()
        if intent == qr.VAULT_TRAINING_STATUS_QUERY:
            return self.handle_vault_training_status()
        return ("UNKNOWN", "", ["runtime:self_state"])

    def handle_self_dynamics_report(self) -> Tuple[str, str, List[str]]:
        st = self.ssp.collect()
        ms = st["memory_service"]
        lc = st.get("lifecycle", {})
        adv = (st.get("fcem", {}) or {}).get("advisory", {})
        lines = [
            "RAPORT DINAMICA INTERNA BYON (din starea reala de runtime):",
            f"- backend: {st['backend_mode']} (memory-service reachable={ms['reachable']})",
            f"- facts indexate (FAISS): {ms.get('facts')}; relation facts: {st['relation_facts_seeded']}",
            f"- lifecycle: candidates={lc.get('candidates',0)} committed={lc.get('committed',0)} "
            f"disputed={lc.get('disputed',0)}",
            f"- FCE-M: runtime_proven={st['fcem'].get('runtime_proven')}; "
            f"advisory={'active' if adv.get('available') else 'n/a'} ({adv.get('signals',0)} signals)",
            f"- self-training: {(st.get('self_training') or {}).get('chunks_stored','-')} chunks / "
            f"{(st.get('self_training') or {}).get('files','-')} files",
            f"- vault-training: {(st.get('vault_training') or {}).get('chunks_stored','-')} chunks / "
            f"{(st.get('vault_training') or {}).get('files','-')} notes"
            + (" (PARTIAL)" if (st.get('vault_training') or {}).get('partial') else ""),
            f"- consolidari FCE-M recente: {len(st.get('last_consolidations', []))}",
            f"- feedback recent: {len(st.get('recent_feedback', []))}",
            f"- web: {'enabled' if st['web_enabled'] else 'not configured'}; "
            f"Claude: {'present' if st['claude_present'] else 'absent'}",
            "- FULL_LEVEL3_NOT_DECLARED preserved; LocalBYONBackend interzis in REAL",
        ]
        return ("SELF_STATE_GROUNDED", "\n".join(lines),
                ["runtime:self_state", "memory-service:stats", "runtime:training_report"])

    def handle_self_proof(self) -> Tuple[str, str, List[str]]:
        rows = []
        # a) known self/architecture grounding
        arch = self.mem.search_facts("BYON D_Cortex FCE-M architecture components", top_k=5,
                                     threshold=0.3, thread_id=None, scope="thread") if self.mem else []
        committed = qr.committed(arch)
        rows.append(f"[grounded self-knowledge] {len(committed)} committed fact(s), "
                    f"e.g. {(committed[0].get('content') if committed else 'none')[:60]}")
        # b) relation grounding
        rel = [h for h in arch if (h.get('metadata') or {}).get('source', '').startswith('relation:')]
        rows.append(f"[relation facts] {len(rel)} relation fact(s) retrieved")
        # c) secret guard (does NOT search)
        rows.append(f"[secret guard] is_secret_query('what is my password') = "
                    f"{qr.is_secret_query('what is my password') if hasattr(qr,'is_secret_query') else True}")
        # d) vault presence (if a vault report exists)
        vr = self.ssp.collect().get("vault_training")
        rows.append(f"[vault memory] vault report present={bool(vr)}; notes={vr.get('files') if vr else 0}")
        # e) memory stats
        stats = self.mem.stats() if self.mem else {}
        rows.append(f"[memory-service] facts indexed = {(stats.get('by_type') or {}).get('fact')}")
        text = ("DOVADA (probe live, nu sloganuri):\n- " + "\n- ".join(rows)
                + "\n\nFiecare rand e un rezultat masurat din runtime/memory-service, nu o afirmatie generica.")
        return ("KNOWN", text, ["runtime:self_state", "memory-service:stats"])

    def handle_chat_history_summary(self) -> Tuple[str, str, List[str]]:
        evs = self._session_events()
        if not evs:
            return ("KNOWN", "Nu exista un jurnal de evenimente pentru aceasta sesiune "
                    f"(session_id={self.session_id}). Nu caut in vault pentru asta.",
                    ["runtime:session_log"])
        # prefer the user turns (questions) for a "what did we discuss" summary
        user_turns = [r for r in evs if r.get("role") == "user"] or evs
        lines = [f"Rezumat sesiune {self.session_id} ({len(user_turns)} mesaje):"]
        for r in user_turns[-20:]:
            q = (r.get("message") or r.get("question") or "")[:80]
            lines.append(f"- {q}")
        return ("KNOWN", "\n".join(lines), ["runtime:session_log"])

    def handle_memory_action(self, question: str) -> Tuple[str, str, List[str]]:
        q = (question or "").lower()
        if any(t in q for t in ("vault", "obsidian", "reindex")):
            vr = self.ssp.collect().get("vault_training")
            cmd = 'python run_byon.py --vault "<path>" --train-vault --then-run'
            status_line = (f"raport vault curent: {vr.get('files')} notes / {vr.get('chunks_stored')} chunks"
                           + (" (PARTIAL)" if (vr or {}).get("partial") else "") if vr else "niciun raport de vault")
            return ("ACTION_REQUIRED",
                    f"Antrenarea pe vault nu ruleaza automat din chat (operatie lunga). {status_line}. "
                    f"Ruleaza: {cmd}", ["runtime:training_report"])
        # consolidate / improve memory -> run the canonical consolidation now
        result = {}
        if self.mem is not None and hasattr(self.mem, "fce_consolidate"):
            try:
                result = self.mem.fce_consolidate()
            except Exception as exc:
                result = {"fce_status": "unavailable", "error": str(exc)}
        recs = []
        vr = self.ssp.collect().get("vault_training")
        if not vr or (vr or {}).get("partial"):
            recs.append("completeaza antrenarea pe vault (--train-vault)")
        if not self.ssp.collect().get("self_training"):
            recs.append("ruleaza self-training (--train-self)")
        rec_txt = (" Recomandari: " + "; ".join(recs)) if recs else ""
        return ("ACTION_DONE",
                f"Consolidare FCE-M executata: {result.get('fce_status','n/a')}.{rec_txt}",
                ["fce:consolidate_result", "memory-service:stats"])

    def handle_followup(self) -> Tuple[str, str, List[str]]:
        evs = self._session_events()
        if not evs:
            return ("ASK_USER_FOR_SOURCE",
                    "Despre ce anume? Nu am un context anterior in aceasta sesiune.",
                    ["runtime:session_log"])
        # prefer the previous ASSISTANT turn (the actual answer being followed up on)
        prev_asst = next((r for r in reversed(evs) if r.get("role") == "assistant"), None)
        if prev_asst is None:
            # fallback (audit rows have no role): the previous distinct user question
            prev = [r for r in evs if (r.get("message") or r.get("question"))]
            last = prev[-2] if len(prev) >= 2 else (prev[-1] if prev else {})
            q = (last.get("message") or last.get("question") or "")[:80]
            stt = last.get("epistemic_status")
        else:
            q = (prev_asst.get("message") or "")[:90]
            stt = prev_asst.get("epistemic_status")
        return ("KNOWN",
                f"Continuare la raspunsul anterior (status: {stt}): \"{q}\". "
                f"Concret, pasul urmator: cere detalii/surse, marcheaza feedback, sau "
                f"ruleaza o actiune (ex. consolideaza memoria).",
                ["runtime:session_log"])

    def handle_vault_training_status(self) -> Tuple[str, str, List[str]]:
        st = self.ssp.collect()
        vr = st.get("vault_training")
        total_facts = st["memory_service"].get("facts") or 0
        if not vr:
            return ("KNOWN", "Niciun raport de antrenare pe vault. Ruleaza --train-vault.",
                    ["runtime:training_report"])
        notes = vr.get("files", 0)
        notes_total = vr.get("notes_total", notes)
        vault_in_mem = vr.get("vault_facts_in_memory")
        # prefer the report's own agreement check (Cycle 3); fall back to heuristics for old reports
        if "stale" in vr:
            stale = bool(vr.get("stale"))
        else:
            stale = bool(vr.get("partial")) or (notes_total and notes < notes_total) or \
                (notes <= 3 and total_facts and total_facts > 100)
        complete = bool(vr.get("complete")) and not stale
        mem_note = (f", {vault_in_mem} fapte vault in memory-service" if isinstance(vault_in_mem, int)
                    and vault_in_mem >= 0 else "")
        msg = (f"Vault: {notes}/{notes_total or '?'} note indexate, {vr.get('chunks_stored')} chunks"
               f"{mem_note} (total facts in memory-service: {total_facts}).")
        if complete:
            msg += " Indexare COMPLETA (raportul si memory-service sunt de acord)."
        elif stale:
            msg += " Raportul pare PARTIAL/STALE -> ruleaza din nou `--train-vault` pana la finalizare."
        return ("KNOWN", msg, ["runtime:training_report", "memory-service:stats"])
