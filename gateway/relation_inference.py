"""Grounded relation inference (Cycle 11).

Turns committed facts / candidate claims / dispute explanations / vault-chunk CONTENT / self-training
docs / task summaries into RELATION CANDIDATES — never truth. Every candidate carries the evidence
quote it came from, its source id and source class, and the inference method. Candidates enter the
relation-candidate lifecycle (they do not become committed relations on inference).

Methods, in order of authority:
  * deterministic pattern rules over the text (primary, testable);
  * canonical schema rules (a recognised project triple → VERIFIED_PROJECT_FACT);
  * candidate-lifecycle records (a committed/disputed candidate → relation candidate);
  * OPTIONAL Claude extraction as a language faculty only (opt-in BYON_RELATION_INFERENCE_CLAUDE),
    bounded snippet in, proposed candidates out — advisory, never truth, never source-policy override.

Hard rules: secret content is never inferred from and never sent to Claude; a vault/user relation
stays user-memory-grounded (never silently promoted to objective truth); source policy + the Auditor
remain dominant downstream.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from . import relation_field as rf

# methods
M_DETERMINISTIC = "deterministic"
M_CANONICAL = "canonical_schema"
M_LIFECYCLE = "candidate_lifecycle"
M_CLAUDE = "claude_advisory"

_SECRET = re.compile(
    r"(?i)\b(password|parol[ăa]|secret|secret[ăa]|private\s+key|cheie\s+(?:privat[ăa]|secret[ăa])|"
    r"api[ _-]?key|token|codeword|pin|cod\s+pin|cod\s+de\s+acces|ssn|cnp|iban|credit\s*card|"
    r"card\s+(?:bancar|de\s+credit)|cont\s+bancar)\b")

# verb-phrase → relation type. Order matters (longest/most-specific first).
_PATTERNS = [
    (re.compile(r"(?i)\bis a component of\b|\bis part of\b|\bcomponent of\b|\bpart of\b|"
                r"\bface parte din\b|\bparte (?:din|a)\b"), rf.HAS_COMPONENT, True),   # reversed
    (re.compile(r"(?i)\bhas components?\b|\bhas component\b|\bcontains\b|\bis composed of\b|"
                r"\bcomprises\b|\bcuprinde\b|\bcon[țt]ine\b|\bare componenta\b|\bhas a\b"),
     rf.HAS_COMPONENT, False),
    (re.compile(r"(?i)\bdepends? on\b|\bdepend on\b|\bdepinde de\b|\bdepind de\b|\brequires\b|"
                r"\bnecesit[ăa]\b|\brelies on\b|\bse bazeaz[ăa] pe\b"), rf.DEPENDS_ON, False),
    (re.compile(r"(?i)\bderived from\b|\bderivat din\b|\bbased on\b|\bbazat pe\b"), rf.DERIVED_FROM, False),
    (re.compile(r"(?i)\bcaused by\b|\bcauzat de\b|\bdatorit[ăa]\b|\bbecause of\b"), rf.CAUSED_BY, False),
    (re.compile(r"(?i)\bcontradicts\b|\bcontrazice\b|\bconflicts with\b|\bin conflict cu\b|"
                r"\bîn conflict cu\b"), rf.CONTRADICTS, False),
    (re.compile(r"(?i)\bsupports\b|\bsus[țt]ine\b|\bconfirms\b|\bconfirm[ăa]\b|\bcorroborates\b"),
     rf.SUPPORTS, False),
    (re.compile(r"(?i)\brefines\b|\brafineaz[ăa]\b|\bnarrows\b"), rf.REFINES, False),
    (re.compile(r"(?i)\bis the role of\b|\brole of\b|\bfunctions as\b|\bacts as\b|\bserves as\b|"
                r"\beste rolul\b|\bare rolul (?:de|să)\b|\bare rol de\b|\bfunc[țt]ioneaz[ăa] ca\b"),
     rf.ROLE_OF, False),
]
_NEG = re.compile(r"(?i)\b(not|never|nu|n't|isn't|doesn't|does not|nu este|nu depinde|fără|fara)\b")
_EDGE_STOP = {"the", "a", "an", "this", "that", "these", "those", "is", "are", "was", "were", "be",
              "it", "its", "and", "or", "of", "to", "in", "on", "as", "by", "with", "also", "now",
              # auxiliaries / negation so "X does not" trims back to "X" (the real subject)
              "does", "do", "did", "not", "never", "no", "nor", "cannot", "doesn", "isn", "don",
              "este", "e", "un", "o", "si", "și", "la", "de", "ce", "iar", "acest", "aceasta",
              "această", "care", "deci", "nu", "niciodata", "niciodată", "fara", "fără"}
_CANON_ENTITIES = {"byon", "d_cortex", "d-cortex", "dcortex", "fce-m", "fcem", "fce-m v15.7a",
                   "memory-service", "memory service", "claude", "faiss", "auditor", "d cortex"}


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+|;\s+", (text or "").strip())
    return [p.strip() for p in parts if p and len(p.strip()) > 3][:40]


def _clean_np(s: str, *, take_last: bool) -> str:
    """Trim a side of the sentence to a short noun phrase next to the verb."""
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-\.]*", s or "")
    toks = toks[-7:] if take_last else toks[:7]
    while toks and toks[0].lower() in _EDGE_STOP:
        toks.pop(0)
    while toks and toks[-1].lower() in _EDGE_STOP:
        toks.pop()
    return " ".join(toks).strip().strip(".,;:!?").strip()[:80]


def _is_secret(text: str) -> bool:
    return bool(_SECRET.search(text or ""))


def _candidate(subject, predicate, obj, rtype, conf, quote, source, source_class, method,
               provenance, *, is_contradiction=False) -> Dict[str, Any]:
    return {"subject": subject, "predicate": predicate, "object": obj, "relation_type": rtype,
            "confidence": round(conf, 3), "evidence_quote": (quote or "")[:240], "source_id": source,
            "source_class": source_class, "method": method, "provenance": provenance or {},
            "is_contradiction": bool(is_contradiction or rtype == rf.CONTRADICTS),
            "status": rf.CANDIDATE}


def _is_canon(name: str) -> bool:
    return (name or "").strip().lower() in _CANON_ENTITIES


def infer_relations_from_text(text: str, source: str, source_class: Optional[str],
                              provenance: Optional[Dict[str, Any]] = None, *,
                              context: Optional[Dict[str, Any]] = None,
                              claude_advisor: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Return RelationCandidate dicts inferred from `text`. Deterministic-first; Claude is advisory
    and opt-in. Secret text yields nothing and is never sent to Claude."""
    ctx = context or {}
    if ctx.get("is_secret") or _is_secret(text):
        return []
    out: List[Dict[str, Any]] = []
    for sent in _sentences(text):
        for rx, rtype, reverse in _PATTERNS:
            m = rx.search(sent)
            if not m:
                continue
            left = _clean_np(sent[:m.start()], take_last=True)
            right = _clean_np(sent[m.end():], take_last=False)
            if not left or not right:
                break
            subj, obj = (right, left) if reverse else (left, right)
            neg = bool(_NEG.search(sent[:m.start()]) or _NEG.search(" " + m.group(0)))
            rt = rf.CONTRADICTS if (neg and rtype != rf.CONTRADICTS) else rtype
            # canonical schema rule: a recognised project triple is a VERIFIED_PROJECT_FACT
            method, conf, sc = M_DETERMINISTIC, 0.7, source_class
            if _is_canon(subj) and _is_canon(obj) and source_class in (
                    "SYSTEM_CANONICAL", "VERIFIED_PROJECT_FACT"):
                method, conf = M_CANONICAL, 0.9
            out.append(_candidate(subj, m.group(0).strip(), obj, rt, conf, sent.strip(), source,
                                  sc, method, provenance, is_contradiction=(rt == rf.CONTRADICTS)))
            break                                          # one relation per sentence (first match)
    adv = _claude_relations(text, source, source_class, provenance, claude_advisor)
    return out + adv


def _claude_relations(text, source, source_class, provenance, advisor) -> List[Dict[str, Any]]:
    """Advisory Claude extraction — opt-in, bounded snippet, proposed candidates only, never truth."""
    if advisor is None or os.environ.get("BYON_RELATION_INFERENCE_CLAUDE", "false").strip().lower() \
            not in ("1", "true", "yes", "on"):
        return []
    if _is_secret(text):                                   # never send secret content to Claude
        return []
    try:
        proposed = advisor(text[:600]) or []               # bounded snippet only
    except Exception:
        return []
    out = []
    for p in proposed:
        rt = p.get("relation_type") if p.get("relation_type") in rf.RELATION_TYPES else \
            rf._rtype(p.get("predicate", ""))
        if p.get("subject") and p.get("object"):
            out.append(_candidate(p["subject"], p.get("predicate", rt), p["object"], rt, 0.55,
                                  p.get("evidence_quote") or text[:160], source, source_class,
                                  M_CLAUDE, provenance))
    return out


def infer_from_candidate(c: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A committed/disputed candidate is also a relation source (method candidate_lifecycle)."""
    claim = c.get("claim") or ""
    sc = c.get("source_class")
    prov = {"candidate_id": c.get("candidate_id"), "topic": c.get("topic")}
    cands = infer_relations_from_text(claim, f"candidate:{c.get('candidate_id','')}", sc, prov)
    for rc in cands:
        rc["method"] = M_LIFECYCLE
    return cands
