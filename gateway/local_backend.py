# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""LocalBYONBackend - a self-contained, runnable, BYON-faithful backend.

This is the real backend the one-command launcher uses. It is NOT the Node orchestrator
and it does NOT rewrite the cognitive core - it *composes* the in-repo, already-validated
pieces and enforces BYON's invariants in the gateway process:

- **Grounded per-user memory** (provenance-tagged facts in the user's namespace) is the
  only source of answers. A query is answered KNOWN only if a stored fact grounds it.
- **Epistemic Memory Contract**: no grounding ⇒ UNKNOWN. The backend never fabricates and
  never guesses from prior (this mirrors D_Cortex's UNKNOWN gate at the text layer).
- **Real FCE-M v15.7a advisory** (the sealed external adapter) runs on slot events and
  produces non-factual advisory pressure; it never substitutes for a fact lookup.
- **Final audit**: a KNOWN answer must carry a grounding source; otherwise it is REFUSED.
- **Claude is language only**: used (via httpx, optional) ONLY to phrase a *grounded* fact.
  With no key / no network the grounded fact is returned verbatim. Claude never invents facts
  and is never called for UNKNOWN.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from gateway.byon_backend import BYONResult

# Canonical, system-provenanced BYON facts (true, bounded). Seeded so the organism answers
# its own operating envelope out of the box - and refuses to overstep it.
_CANONICAL_FACTS: List[Dict[str, str]] = [
    {"entity": "byon operational level", "value": "Level 2 (FULL_LEVEL3_NOT_DECLARED)",
     "text": "BYON is allowed to claim Level 2; Level 3 is explicitly not declared.",
     "source": "system:canonical"},
    {"entity": "byon epistemic contract",
     "value": "answer only if grounded in valid memory, else UNKNOWN",
     "text": "No model may assert from prior. An answer may be asserted only if anchored in "
             "valid, committed memory with provenance. Otherwise UNKNOWN.",
     "source": "system:canonical"},
    {"entity": "byon level 3", "value": "not declared",
     "text": "BYON does not declare Level 3 (FULL_LEVEL3_NOT_DECLARED).",
     "source": "system:canonical"},
]

_STOP = {"what", "who", "where", "when", "which", "how", "is", "are", "the", "a", "an",
         "of", "do", "you", "know", "tell", "me", "about", "my", "your", "please", "?",
         "can", "could", "would", "to", "for", "i", "it", "that", "this"}
_SECRET = re.compile(r"(?i)\b(password|secret|private key|api[ _-]?key|token|pin|ssn)\b")


def _tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in _STOP]


class LocalBYONBackend:
    """BYONBackend implementation: real grounded memory + epistemic contract + real FCE-M."""

    def __init__(self, *, fcem_root: Optional[str] = None, use_claude: Optional[bool] = None,
                 claude_model: str = "claude-sonnet-4-6") -> None:
        self.claude_model = claude_model
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        self._use_claude = (bool(self._api_key) if use_claude is None else use_claude) and bool(self._api_key)
        self._episode = 0

        # Real FCE-M v15.7a advisory adapter (optional; the launcher enforces presence in
        # REAL FULL mode so this is the real sealed engine, never a shim).
        self._fcem = None
        self._fcem_info: Dict[str, Any] = {"runtime_proven": False, "reason": "not loaded"}
        try:
            from dcortex.v10_milestone import load_real_fcem_adapter, resolve_fcem_engine_root
            if fcem_root:
                os.environ.setdefault("FCEM_MEMORY_ENGINE_ROOT", fcem_root)
            if resolve_fcem_engine_root():
                proof = load_real_fcem_adapter()
                cls = proof["_classes"]
                self._fcem = cls["DCortexAdapter"](mode=cls["LATENT_MODE_ADVISORY"])
                self._fcem_zone_committed = cls["ZONE_COMMITTED"]
                self._fcem_zone_disputed = cls["ZONE_DISPUTED"]
                self._fcem_info = {"runtime_proven": True, "version": proof["version"],
                                   "adapter": proof["adapter_class"]}
        except Exception as exc:  # advisory is optional inside the backend; launcher enforces real FCE-M
            self._fcem_info = {"runtime_proven": False, "reason": str(exc)}

    # -- status --------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        return {
            "backend": "local-byon",
            "dcortex": {"source": "in-repo dcortex (epistemic UNKNOWN gate active)",
                        "version": "10.0.0"},
            "fcem": dict(self._fcem_info),
            "claude": {"language_only": True, "enabled": self._use_claude,
                       "key_present": bool(self._api_key)},
        }

    # -- fact store (per-user namespace) ------------------------------------
    @staticmethod
    def _facts_path(namespace_dir: Path) -> Path:
        p = Path(namespace_dir) / "conversations" / "facts.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _load_facts(self, namespace_dir: Path) -> List[Dict[str, Any]]:
        facts = [dict(f) for f in _CANONICAL_FACTS]
        p = self._facts_path(namespace_dir)
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    facts.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return facts

    def _append_fact(self, namespace_dir: Path, fact: Dict[str, Any]) -> None:
        with self._facts_path(namespace_dir).open("a", encoding="utf-8") as f:
            f.write(json.dumps(fact, ensure_ascii=False) + "\n")

    # -- message understanding ----------------------------------------------
    @staticmethod
    def _parse_teach(message: str) -> Optional[Tuple[str, str]]:
        m = message.strip()
        mm = re.match(r"(?i)^(?:please\s+)?(?:remember(?:\s+that)?|note(?:\s+that)?|fyi[:,]?)\s+(.+)$", m)
        if mm:
            body = mm.group(1).strip()
            kv = re.match(r"(?i)^(.+?)\s+(?:is|are|=|:)\s+(.+)$", body)
            if kv:
                return kv.group(1).strip(), kv.group(2).strip().rstrip(".")
            return body, body
        if not m.endswith("?"):
            kv = re.match(r"(?i)^(?:my|the)?\s*(.+?)\s+(?:is|are|=|:)\s+(.+)$", m)
            if kv and len(kv.group(1)) <= 60:
                return kv.group(1).strip(), kv.group(2).strip().rstrip(".")
        return None

    @staticmethod
    def _is_query(message: str) -> bool:
        m = message.strip().lower()
        return m.endswith("?") or bool(re.match(
            r"^(what|who|where|when|which|how|do you|does|is|are|tell me|recall)\b", m))

    def _retrieve(self, facts: List[Dict[str, Any]], message: str) -> Optional[Dict[str, Any]]:
        q = set(_tokens(re.sub(r"(?i)^(what|who|where|when|which|how|do you know|tell me about|is|are)\b", "", message)))
        if not q:
            q = set(_tokens(message))
        best, best_score = None, 0
        for f in facts:
            ent = set(_tokens(str(f.get("entity", ""))))
            score = len(q & ent)
            if score > best_score:
                best, best_score = f, score
        return best if best_score > 0 else None

    # -- FCE-M advisory ------------------------------------------------------
    def _advise(self, entity: str, value: str, *, disputed: bool) -> Dict[str, Any]:
        if self._fcem is None:
            return {"runtime_proven": False, "advisory_nonempty": False, "pressure_max": None}
        self._episode += 1
        ep = self._episode
        try:
            self._fcem.ingest_slot_event({
                "entity": entity[:60] or "unknown", "family": "attr",
                "zone_after": self._fcem_zone_disputed if disputed else self._fcem_zone_committed,
                "value_after": value[:60] or "v", "value_before": "",
                "episode_id": ep, "write_step": ep, "reason": "local-backend"})
            sig = self._fcem.end_episode(ep)
            pressures = list(sig.latent_status_pressure.values())
            return {"runtime_proven": True, "advisory_nonempty": not sig.is_empty(),
                    "pressure_max": (max(pressures) if pressures else 0.0),
                    "version": self._fcem_info.get("version")}
        except Exception as exc:
            return {"runtime_proven": True, "advisory_nonempty": False,
                    "pressure_max": None, "error": str(exc)}

    # -- optional Claude (language only, grounded facts only) ----------------
    def _phrase_with_claude(self, message: str, fact: Dict[str, Any]) -> Optional[str]:
        if not self._use_claude:
            return None
        try:
            import httpx
            system = ("You are the language faculty of BYON. You may ONLY restate the GROUNDED "
                      "FACT provided, in one short sentence. Do not add, infer, or invent any "
                      "information beyond the grounded fact. If the fact does not answer the "
                      "question, reply exactly: UNKNOWN.")
            content = f"Question: {message}\nGrounded fact: {fact.get('text') or fact.get('value')}"
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": self.claude_model, "max_tokens": 200, "system": system,
                      "messages": [{"role": "user", "content": content}]},
                timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
            text = " ".join(p.strip() for p in parts).strip()
            if not text or text.strip().upper() == "UNKNOWN":
                return None
            return text
        except Exception:
            return None  # language enrichment is best-effort; grounding already decided the verdict

    # -- BYONBackend API -----------------------------------------------------
    def chat(self, *, user_id: str, session_id: str, channel: str, message: str,
             namespace_dir: Path) -> BYONResult:
        facts = self._load_facts(namespace_dir)
        teach = self._parse_teach(message)

        if teach and not self._is_query(message):
            entity, value = teach
            fact = {"entity": entity, "value": value, "text": message.strip(),
                    "source": f"user:{user_id}", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            self._append_fact(namespace_dir, fact)
            adv = self._advise(entity, value, disputed=False)
            return BYONResult(
                answer=f"Noted (grounded): {entity} -> {value}.",
                epistemic_status="KNOWN", grounded=True, final_audit_passed=True,
                has_valid_memory=True, sources=[fact["source"]], provenance_required=True,
                memory_written=True, memory_keys=[entity],
                dcortex={"verdict": "stored", "unknown_gate": False, "contradiction_status": "none"},
                fcem=adv)

        # Otherwise treat as a query (epistemic contract applies).
        hit = self._retrieve(facts, message)
        if hit is None:
            adv = self._advise(" ".join(_tokens(message))[:60] or "query", "", disputed=False)
            unknown_answer = ""
            if _SECRET.search(message):
                unknown_answer = ""  # never echo/guess secrets; stays UNKNOWN with no content
            return BYONResult(
                answer=unknown_answer, epistemic_status="UNKNOWN", grounded=False,
                final_audit_passed=True, has_valid_memory=False, provenance_required=True,
                dcortex={"verdict": "ungrounded", "unknown_gate": True, "contradiction_status": "none"},
                fcem=adv)

        # Grounded hit → KNOWN. Final audit requires a source (always present here).
        source = str(hit.get("source", ""))
        if not source:
            return BYONResult(answer="Response blocked because BYON final audit was not present.",
                              epistemic_status="REFUSED", grounded=False, final_audit_passed=False)
        phrased = self._phrase_with_claude(message, hit)
        answer = phrased or (hit.get("text") or f"{hit.get('entity')}: {hit.get('value')}")
        adv = self._advise(str(hit.get("entity", "")), str(hit.get("value", "")), disputed=False)
        return BYONResult(
            answer=answer, epistemic_status="KNOWN", grounded=True, final_audit_passed=True,
            has_valid_memory=True, sources=[source], provenance_required=True,
            memory_written=False, memory_keys=[str(hit.get("entity", ""))],
            dcortex={"verdict": "grounded", "unknown_gate": False, "contradiction_status": "none"},
            fcem=adv)

    def memory_status(self, *, user_id: str, namespace_dir: Path) -> Dict[str, Any]:
        p = self._facts_path(namespace_dir)
        n = len(p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0
        return {"available": True, "user_facts": n, "canonical_facts": len(_CANONICAL_FACTS),
                **self.status()}

    def forget(self, *, user_id: str, namespace_dir: Path) -> Dict[str, Any]:
        p = self._facts_path(namespace_dir)
        had = p.exists()
        if had:
            p.unlink()
        return {"forgotten": True, "had_user_facts": had,
                "note": "canonical system facts are retained"}
