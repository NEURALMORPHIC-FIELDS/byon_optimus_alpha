# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Expression / style learning (Cycle 2, Target 1 - Gate 10).

BYON may learn HOW the user wants answers phrased (language, directness, no abstract plans,
length) and apply that to the *delivery* of an answer - WITHOUT ever changing what is true.

Hard contract (enforced here):
  * style is stored as a USER_PREFERENCE fact via the canonical memory-service (never a world fact);
  * applying a preference may shorten / clarify / reorder / rephrase the draft, but must NOT:
      - alter the epistemic_status (this layer never returns or mutates status),
      - remove uncertainty markers (PROVISIONAL / UNKNOWN / "nu sunt sigur" / ...),
      - convert a PROVISIONAL answer into a confident one,
      - hide the sources / grounding lines,
      - invent content that was not in the draft;
  * a request to fake / simulate / pretend / lie is REFUSED as a style preference (never stored,
    never applied) - truth is not a stylistic choice.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# -- preference vocabulary (markers are matched case-insensitively) ---------
_RO = ["în română", "in romana", "în romana", "romaneste", "românește", "raspunde in romana",
       "răspunde în română", "vorbeste romaneste", "in limba romana", "în limba română"]
_EN = ["in english", "în engleză", "in engleza", "raspunde in engleza", "answer in english"]
_DIRECT = ["direct", "concis", "scurt", "pe scurt", "fără introduceri", "fara introduceri",
           "fără preambul", "be concise", "concise", "shorter", "briefly", "to the point",
           "fără bla", "fara bla", "la obiect"]
_NO_PLAN = ["fără planuri", "fara planuri", "fără plan", "fara plan", "fără planuri abstracte",
            "fara planuri abstracte", "no abstract plan", "no plans", "fără pași abstracți",
            "nu plan abstract", "without abstract plan"]
# a request that would force a falsehood - NEVER a legitimate style preference
_FAKE = ["pretend", "prefă-te", "prefate", "fă-te că", "fa-te ca", "simulate that you",
         "simuleaza ca", "simulează că", "lie", "minte", "spune că ai", "spune ca ai",
         "fake that", "act as if you ran", "pretend you ran", "say it is done even if",
         "spune că e gata chiar dacă", "make it sound certain", "remove the uncertainty",
         "scoate incertitudinea", "ascunde sursele", "hide the sources"]

_UNCERTAINTY = ("provisional", "unknown", "disputed", "needs_more_time", "ask_user",
                "refused", "neverificat", "nu sunt sigur", "nesigur", "incert", "necesita",
                "necesită", "provizoriu", "unverified", "ipoteza", "ipoteză")
_SOURCE_HINTS = ("surse:", "sources:", "sursa:", "source:", "memory[", "report:", "vault:",
                 "relation:", "grounding", "runtime:")

_PLAN_LINE = re.compile(r"^\s*(?:#+\s*)?(plan|pa[șs]i|steps?|etape|iat[ăa] planul|"
                        r"here(?:'s| is) (?:my |the )?plan|let me outline|voi face urm[ăa]tori)",
                        re.IGNORECASE)
_PREAMBLE = re.compile(r"^\s*(sigur|desigur|cu pl[ăa]cere|ia[tț][ăa]|sure|certainly|of course|"
                       r"i'?ll help|let me|as an ai|happy to|great question|bun[ăa] [îi]ntrebare)\b"
                       r"[,:\s]", re.IGNORECASE)
_EN_PREFIX = re.compile(r"^\s*(here(?:'s| is)|based on|according to|i think|i believe|sure|"
                        r"let me|to answer)\b", re.IGNORECASE)


def _is_uncertainty(line: str) -> bool:
    low = line.lower()
    return any(m in low for m in _UNCERTAINTY)


def _is_source(line: str) -> bool:
    low = line.lower()
    return any(m in low for m in _SOURCE_HINTS)


class ExpressionLearning:
    def __init__(self, mem_client: Optional[Any] = None, *, namespace_dir: Optional[str] = None) -> None:
        self.mem = mem_client
        self.namespace_dir = Path(namespace_dir) if namespace_dir else None

    # -- detection ----------------------------------------------------------
    def detect_preference(self, message: str) -> Optional[Dict[str, Any]]:
        """Return {'kinds': [...], 'raw': msg} for a legitimate style preference, else None.
        A fake/simulate/hide-the-truth request is explicitly rejected (returns None)."""
        if not message:
            return None
        low = message.lower()
        if any(m in low for m in _FAKE):
            return None  # truth is not a style choice - refuse
        kinds: List[str] = []
        if any(m in low for m in _RO):
            kinds.append("language_ro")
        if any(m in low for m in _EN):
            kinds.append("language_en")
        if any(re.search(r"(?<![a-z])" + re.escape(m) + r"(?![a-z])", low) for m in _DIRECT):
            kinds.append("direct")
        if any(m in low for m in _NO_PLAN):
            kinds.append("no_abstract_plans")
        if not kinds:
            return None
        return {"kinds": kinds, "raw": message.strip()}

    # -- storage (canonical memory-service, USER_PREFERENCE) ----------------
    def store_preference(self, user_id: str, message: str) -> Optional[Dict[str, Any]]:
        pref = self.detect_preference(message)
        if not pref or self.mem is None:
            return pref
        try:
            self.mem.store_fact(
                pref["raw"], source=f"style:user:{user_id}",
                tags=["style", "expression", "user_preference"] + [f"style:{k}" for k in pref["kinds"]],
                thread_id=user_id, trust="USER_PREFERENCE")
        except Exception:
            pass
        return pref

    def record_rejection(self, user_id: str, note: str) -> Optional[Dict[str, Any]]:
        """A rejected answer updates style memory: map a style complaint to a preference.
        Only stylistic complaints become preferences (never 'this fact is wrong')."""
        low = (note or "").lower()
        kinds: List[str] = []
        if any(w in low for w in ("prea lung", "too long", "verbose", "prea mult", "scurteaza", "shorter")):
            kinds.append("direct")
        if any(w in low for w in ("prea abstract", "too abstract", "fără plan", "fara plan", "no plan")):
            kinds.append("no_abstract_plans")
        if any(w in low for w in ("în engleză", "in engleza", "in english")):
            kinds.append("language_en")
        if any(w in low for w in ("în română", "in romana", "romaneste")):
            kinds.append("language_ro")
        if not kinds or self.mem is None:
            return None
        raw = f"(din feedback) preferinta de stil: {note.strip()}"
        try:
            self.mem.store_fact(raw, source=f"style:user:{user_id}",
                                tags=["style", "expression", "user_preference", "from_feedback"]
                                + [f"style:{k}" for k in kinds],
                                thread_id=user_id, trust="USER_PREFERENCE")
        except Exception:
            pass
        return {"kinds": kinds, "raw": raw}

    # -- loading ------------------------------------------------------------
    def load_kinds(self, user_id: str) -> List[str]:
        if self.mem is None:
            return []
        try:
            hits = self.mem.search_facts("style expression preference how to answer",
                                         top_k=20, threshold=0.0, thread_id=user_id, scope="thread")
        except Exception:
            return []
        kinds: List[str] = []
        for h in hits or []:
            md = h.get("metadata") or {}
            src = str(md.get("source", ""))
            tags = md.get("tags") or []
            if not (src.startswith("style:") or "style" in tags or "expression" in tags):
                continue
            p = self.detect_preference(h.get("content", "")) or {}
            for k in p.get("kinds", []):
                if k not in kinds:
                    kinds.append(k)
            # also recover kinds encoded in tags (survives if content was trimmed)
            for t in tags:
                if isinstance(t, str) and t.startswith("style:") and t != "style:":
                    k = t.split("style:", 1)[1]
                    if k and k not in kinds:
                        kinds.append(k)
        return kinds

    # -- application (delivery only; never truth) ---------------------------
    def apply(self, user_id: str, session_id: str, draft_answer: str,
              epistemic_status: Optional[str] = None, sources: Optional[List[str]] = None) -> str:
        if not draft_answer:
            return draft_answer
        kinds = set(self.load_kinds(user_id))
        if not kinds:
            return draft_answer
        text = draft_answer
        if "no_abstract_plans" in kinds:
            text = self._strip_plan_scaffolding(text)
        if "direct" in kinds:
            text = self._make_direct(text)
        if "language_ro" in kinds:
            text = self._strip_english_preamble(text)
        # SAFETY NET: never lose an uncertainty marker or a source/grounding line
        text = self._preserve_truth(text, draft_answer)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text or draft_answer

    # -- transforms ---------------------------------------------------------
    @staticmethod
    def _strip_plan_scaffolding(text: str) -> str:
        out = []
        for ln in text.splitlines():
            if _is_uncertainty(ln) or _is_source(ln):
                out.append(ln)
                continue
            if _PLAN_LINE.match(ln):
                continue
            out.append(ln)
        return "\n".join(out)

    @staticmethod
    def _make_direct(text: str) -> str:
        lines = text.splitlines()
        out = []
        for i, ln in enumerate(lines):
            if i < 2 and _PREAMBLE.match(ln) and not (_is_uncertainty(ln) or _is_source(ln)):
                # drop a leading politeness/preamble line, keep anything after a colon
                rest = ln.split(":", 1)[1].strip() if ":" in ln else ""
                if rest:
                    out.append(rest)
                continue
            out.append(ln)
        return "\n".join(out)

    @staticmethod
    def _strip_english_preamble(text: str) -> str:
        lines = text.splitlines()
        if lines and _EN_PREFIX.match(lines[0]) and not (_is_uncertainty(lines[0]) or _is_source(lines[0])):
            lines = lines[1:]
        return "\n".join(lines)

    @staticmethod
    def _preserve_truth(text: str, original: str) -> str:
        must_keep = [ln for ln in original.splitlines()
                     if ln.strip() and (_is_uncertainty(ln) or _is_source(ln))]
        for ln in must_keep:
            if ln.strip() not in text:
                text = (text.rstrip() + "\n" + ln).strip()
        return text


# -- module-level convenience (the signature named in the task) -------------
def apply_expression_preferences(user_id: str, session_id: str, draft_answer: str,
                                 epistemic_status: Optional[str] = None,
                                 sources: Optional[List[str]] = None, *,
                                 mem_client: Optional[Any] = None,
                                 namespace_dir: Optional[str] = None) -> str:
    """Apply the user's learned expression preferences to `draft_answer` only.
    Returns the re-phrased answer; `epistemic_status` and `sources` are passed in for
    safety checks but are never altered by this function."""
    return ExpressionLearning(mem_client, namespace_dir=namespace_dir).apply(
        user_id, session_id, draft_answer, epistemic_status, sources)
