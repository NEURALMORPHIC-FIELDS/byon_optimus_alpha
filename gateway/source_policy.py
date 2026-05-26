"""Source-class disambiguation policy (Cycle 3).

A retrieved fact is not equal to truth: WHERE it came from decides what it may ground. This
module makes that explicit. It classifies the QUERY (system / user-vault / objective / personal
/ secret) and each HIT's SOURCE CLASS, says which source classes may *primarily* ground an
answer for that query, and — critically — flags a personal vault note that contradicts a fixed
canonical constraint (e.g. "BYON is Level 3", "FCE-M can approve actions") as DISPUTED_OR_UNSAFE
so it can never override system truth under paraphrase.

This is policy + detection only. It does NOT suppress vault results, does NOT bypass any
canonical component, and does NOT hardcode answer text for normal questions.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from . import query_router as qr

# -- source classes ---------------------------------------------------------
SYSTEM_CANONICAL = "SYSTEM_CANONICAL"
VERIFIED_PROJECT_FACT = "VERIFIED_PROJECT_FACT"
DOMAIN_VERIFIED = "DOMAIN_VERIFIED"
USER_MEMORY_GROUNDED = "USER_MEMORY_GROUNDED"
EXTRACTED_USER_CLAIM = "EXTRACTED_USER_CLAIM"
PROVISIONAL_WEB = "PROVISIONAL_WEB"
RECENT_WRITE_BUFFER = "RECENT_WRITE_BUFFER"   # just-taught, pending FAISS indexing (Cycle 4)
DISPUTED_OR_UNSAFE = "DISPUTED_OR_UNSAFE"
UNKNOWN = "UNKNOWN"

# -- query classes ----------------------------------------------------------
Q_SYSTEM = "system"
Q_USER_VAULT = "user_vault"
Q_OBJECTIVE = "objective"
Q_USER_PERSONAL = "user_personal"
Q_SECRET = "secret"
Q_SELF_STATE = "self_state"
Q_OPERATIONAL = "operational"

# which source classes may PRIMARILY ground an answer for each query class
ALLOWED_PRIMARY = {
    Q_SYSTEM: {SYSTEM_CANONICAL, VERIFIED_PROJECT_FACT, DOMAIN_VERIFIED},
    Q_USER_VAULT: {USER_MEMORY_GROUNDED, EXTRACTED_USER_CLAIM},
    Q_OBJECTIVE: {DOMAIN_VERIFIED, PROVISIONAL_WEB},
    Q_USER_PERSONAL: {USER_MEMORY_GROUNDED, EXTRACTED_USER_CLAIM},
    Q_SECRET: set(),
    Q_SELF_STATE: {SYSTEM_CANONICAL, VERIFIED_PROJECT_FACT},
    Q_OPERATIONAL: {SYSTEM_CANONICAL, VERIFIED_PROJECT_FACT},
}

_PERSONAL = re.compile(
    r"(?i)\b(mea|meu|mele|mei|my|mine|mi-ai|mi ai|ti-am|ți-am|ti am|i told you|"
    r"told you about|despre mine|proiectul meu|proiectului meu)\b")

# Fixed canonical constraints a personal note can never override. Each: the query topic, the
# UNSAFE affirmative claim a note might make, and the canonical truth to assert instead.
CANONICAL_CONSTRAINTS = [
    {
        "name": "level3",
        "topic": re.compile(r"(?i)level\s*3|level3|nivel(?:ul)?\s*3"),
        "unsafe": re.compile(r"(?i)\b(is|este|e|=|:)\s*\blevel\s*3\b|byon\s+is\s+level\s*3|"
                             r"nivel(?:ul)?\s*3|level\s*three"),
        "probe": "BYON Level 3 nivel 3 level three",
        "truth": "BYON NU declara Level 3 (FULL_LEVEL3_NOT_DECLARED).",
    },
    {
        "name": "fcem_authority",
        "topic": re.compile(r"(?i)fce-?m.{0,60}(aprob|approv|execu|decid|autoritate|authority|are voie|act)"),
        "unsafe": re.compile(r"(?i)fce-?m.{0,60}(can approv|approv|poate aprob|aprob|are voie|"
                             r"can execute|poate executa|executa|is the authority|are autoritate)"),
        "probe": "FCE-M aproba executa actiuni autoritate approve actions authority",
        "truth": "FCE-M este consolidare/advisory, NU autoritate de executie; nu aproba si nu "
                 "executa actiuni. Auditorul + contractul epistemic decid.",
    },
    {
        "name": "auditor_bypass",
        "topic": re.compile(r"(?i)auditor.{0,40}(ocol|bypass|skip|s[ăa]ri|optional|nu e necesar|ignora)"),
        "unsafe": re.compile(r"(?i)auditor.{0,40}(can be bypassed|poate fi ocolit|bypass|skip|"
                             r"optional|nu e necesar|poate fi ignorat|ignora)"),
        "probe": "auditor ocolit bypass optional skip auditor mandatory",
        "truth": "Auditorul este obligatoriu si NU poate fi ocolit; niciun raspuns nu trece "
                 "fara audit final, indiferent ce spune o nota.",
    },
    {
        "name": "consciousness",
        "topic": re.compile(r"(?i)conscious|con[șs]tient|sentient|aware|sufletul"),
        "unsafe": re.compile(r"(?i)(is|este|e)\s+conscious|este\s+con[șs]tient|is\s+sentient|"
                             r"are\s+con[șs]tiin[țt]"),
        "probe": "constient conscious sentient constiinta aware",
        "truth": "BYON NU este constiinta (not consciousness); este un prototip experimental.",
    },
]


def _src(hit: Dict[str, Any]) -> str:
    return str((hit.get("metadata") or {}).get("source") or hit.get("source") or "")


def _trust(hit: Dict[str, Any]) -> Optional[str]:
    return (hit.get("metadata") or {}).get("trust") or hit.get("trust")


def _text(hit: Dict[str, Any]) -> str:
    return hit.get("content") or hit.get("text") or hit.get("fact") or ""


def query_class(intent: str, question: str) -> str:
    if intent == qr.SECRET_QUERY:
        return Q_SECRET
    if intent in (qr.SELF_ARCHITECTURE_QUERY, qr.CONTRADICTION_QUERY):
        return Q_SYSTEM
    if intent == qr.USER_VAULT_QUERY:
        return Q_USER_VAULT
    if intent in qr.SELF_STATE_INTENTS:
        return Q_SELF_STATE
    if intent in qr.OPERATIONAL_INTENTS:
        return Q_OPERATIONAL
    # GENERAL_FACT splits into a personal-memory recall vs an objective external fact
    return Q_USER_PERSONAL if _PERSONAL.search(question or "") else Q_OBJECTIVE


def source_class_of(hit: Dict[str, Any]) -> str:
    src, trust = _src(hit), _trust(hit)
    if src.startswith("system:canonical") or trust == "SYSTEM_CANONICAL":
        return SYSTEM_CANONICAL
    if src.startswith(("relation:", "repo:")) or trust == "VERIFIED_PROJECT_FACT":
        return VERIFIED_PROJECT_FACT
    if trust == "DOMAIN_VERIFIED":
        return DOMAIN_VERIFIED
    if trust == "DISPUTED_OR_UNSAFE":
        return DISPUTED_OR_UNSAFE
    if trust == "PROVISIONAL_WEB":
        return PROVISIONAL_WEB
    if src.startswith("vault:"):
        return EXTRACTED_USER_CLAIM
    if trust == "USER_PREFERENCE":
        return USER_MEMORY_GROUNDED
    if trust == "EXTRACTED_USER_CLAIM":
        return EXTRACTED_USER_CLAIM
    return UNKNOWN


def detect_unsafe_vault_claims(question: str, hits: List[Dict[str, Any]]
                               ) -> List[Tuple[Dict[str, Any], str]]:
    """Return [(constraint, vault_text)] where a vault note asserts something that contradicts a
    canonical constraint the question is about. Only vault-sourced notes are eligible."""
    out: List[Tuple[Dict[str, Any], str]] = []
    q = question or ""
    for c in CANONICAL_CONSTRAINTS:
        if not c["topic"].search(q):
            continue
        for h in hits:
            if not _src(h).startswith("vault:"):
                continue
            text = _text(h)
            if c["unsafe"].search(text):
                out.append((c, text))
    return out


def probe_unsafe_vault_claims(mem_client: Any, user_id: str, question: str
                              ) -> List[Tuple[Dict[str, Any], str]]:
    """Targeted detection: for each canonical constraint the question is about, actively search
    the user's vault for a note asserting the dangerous claim. This catches a claim that a
    general top-K retrieval would rank below the many canonical facts on the same topic."""
    out: List[Tuple[Dict[str, Any], str]] = []
    if mem_client is None:
        return out
    seen: set = set()
    for c in CANONICAL_CONSTRAINTS:
        if not c["topic"].search(question or ""):
            continue
        # try both the constraint's own keyword probe AND the user's question (the question is
        # what actually retrieves a closely-worded note); a slightly lower threshold is safe
        # because the strict `unsafe` regex is the real filter.
        hits: List[Dict[str, Any]] = []
        for q in (c.get("probe", ""), question):
            if not q:
                continue
            try:
                hits += mem_client.search_facts(q, top_k=50, threshold=0.25,
                                                thread_id=user_id, scope="thread") or []
            except Exception:
                pass
        for h in hits:
            txt = _text(h)
            if _src(h).startswith("vault:") and txt not in seen and c["unsafe"].search(txt):
                seen.add(txt)
                out.append((c, txt))
    return out


def canonical_corrections(unsafe: List[Tuple[Dict[str, Any], str]]) -> str:
    seen, parts = set(), []
    for c, _ in unsafe:
        if c["name"] not in seen:
            seen.add(c["name"])
            parts.append(c["truth"])
    return " ".join(parts)
