"""Query intent router + trust-tier retrieval re-ranking.

Fixes ranking: a memory hit's final rank is its semantic similarity PLUS a trust-tier boost
PLUS an intent boost, so a canonical VERIFIED_PROJECT_FACT / relation fact can no longer be
out-ranked by a higher-cosine vault EXTRACTED_USER_CLAIM for an architecture question — while
vault notes still dominate for "what did I write…" questions.

Trust order (high→low):
  SYSTEM_CANONICAL > VERIFIED_PROJECT_FACT > DOMAIN_VERIFIED > USER_PREFERENCE >
  EXTRACTED_USER_CLAIM > PROVISIONAL_WEB > DISPUTED_OR_UNSAFE
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

TRUST_RANK = {
    "SYSTEM_CANONICAL": 6, "VERIFIED_PROJECT_FACT": 5, "DOMAIN_VERIFIED": 4,
    "USER_PREFERENCE": 3, "EXTRACTED_USER_CLAIM": 2, "PROVISIONAL_WEB": 1,
    None: 1, "": 1, "DISPUTED_OR_UNSAFE": 0,
}
COMMITTED_TIERS = {"SYSTEM_CANONICAL", "VERIFIED_PROJECT_FACT", "DOMAIN_VERIFIED", "USER_PREFERENCE"}

SELF_TERMS = ["byon", "d_cortex", "d-cortex", "dcortex", "fce-m", "fcem", "auditor",
              "memory-service", "memory service", "orchestrator", "worker", "executor",
              "claude role", "level 2", "level 3", "epistemic contract", "level3", "level2"]
VAULT_TRIGGERS = ["ce am scris", "ce-am scris", "in notele mele", "în notele mele", "notele mele",
                  "unde am mentionat", "unde am menționat", "rezuma vault", "rezumă vault",
                  "vault-ul meu", "vault meu", "my notes", "what did i write", "in my vault",
                  "din notele"]
CONTRADICTION_TRIGGERS = ["contradic", "conflicting", "in conflict", "în conflict", "disput",
                          "gresit", "greșit", "wrong fact", "contradiction"]
# self-introspection — answered from RUNTIME STATE, not vault retrieval
CAPABILITY_TRIGGERS = ["ce capacitati ai", "ce capacități ai", "ce poti face", "ce poți face",
                       "ce poti sa faci", "ce poți să faci", "what can you do",
                       "what are your capabilities", "your capabilities", "ce module ai",
                       "ce stii sa faci", "ce știi să faci", "ce functii ai", "ce funcții ai",
                       "capabilities"]
LIMITATION_TRIGGERS = ["ce nu poti face", "ce nu poți face", "ce limitari ai", "ce limitări ai",
                       "what are your limitations", "your limitations", "ce nu stii", "ce nu știi",
                       "limitarile tale", "limitările tale"]
RECENT_LEARNING_TRIGGERS = ["ce ai invatat recent", "ce ai învățat recent", "ce ai consolidat recent",
                            "ce s-a schimbat in memoria ta", "ce s-a schimbat în memoria ta",
                            "recent learning", "what did you learn recently", "ce ai invatat ultima"]
# LifeLoop v2 internal state — pressures, contradictions noticed, pending internal tasks
INTERNAL_STATE_TRIGGERS = ["ce te preocupa", "ce te preocupă", "ce presiuni ai", "ce presiuni active",
                           "presiuni interne", "ce contradictii ai observat", "ce contradicții ai observat",
                           "ce sarcini interne", "sarcini in asteptare", "sarcini în așteptare",
                           "what concerns you internally", "internal pressure", "internal pressures",
                           "pending internal tasks", "ce te framanta", "ce te frământă",
                           "dinamica ta interna actuala", "starea ta interna"]
MEMORY_STATE_TRIGGERS = ["ce ai asimilat", "ce ai in memorie", "ce ai în memorie", "ce ai invatat",
                         "ce ai învățat", "ce ai indexat", "ce ai memorat", "ce ai stocat",
                         "what have you learned", "what is in your memory", "what's in your memory",
                         "ce contine memoria ta", "ce conține memoria ta", "starea memoriei tale",
                         "ce este in memoria ta", "ce este în memoria ta", "ce ai salvat in memorie",
                         "ce ai salvat în memorie", "ce s-a pastrat in memorie", "ce s-a păstrat în memorie",
                         "memoria ta salvata", "memoria ta salvată"]
# operational / self-referential intents
DYNAMICS_TRIGGERS = ["analiza reala a dinamicii tale", "dinamicii tale interne", "analiza dinamica interna",
                     "analiză dinamică internă", "raport dinamic intern", "internal dynamics report",
                     "analyze your internal dynamics", "dinamica ta interna", "dinamica ta internă"]
PROOF_TRIGGERS = ["dovedeste ca esti altfel", "dovedește că ești altfel", "demonstreaza ca functionezi",
                  "demonstrează că funcționezi", "prove you are different", "show proof",
                  "dovedeste ca esti", "dovedește că ești"]
CHAT_SUMMARY_TRIGGERS = ["ce am discutat in acest chat", "ce am discutat în acest chat",
                         "fa o lista cu ce am discutat", "fă o listă cu ce am discutat",
                         "rezuma acest chat", "rezumă acest chat", "summarize this chat",
                         "what did we discuss", "rezuma conversatia", "rezumă conversația",
                         "ce am discutat"]
MEMORY_ACTION_TRIGGERS = ["imbunatateste-ti memoria", "îmbunătățește-ți memoria", "imbunatateste memoria",
                          "antreneaza-te pe", "antrenează-te pe", "consolideaza memoria",
                          "consolidează memoria", "consolideaza-ti memoria", "reindexeaza vault",
                          "reindexează vault", "train vault", "consolidate memory", "antreneaza-te pe vault"]
# relation-field navigation (Cycle 10) — "how are things related / what depends on what /
# where are the contradictions / which themes recur / what changed". Specific phrases so a plain
# "cine este BYON" stays SELF_ARCHITECTURE and "ce contradictii ai observat" stays internal-state.
RELATION_FIELD_TRIGGERS = ["relatie intre", "relatie între", "relatia intre", "relatia dintre",
                           "relația dintre", "relație între", "relatie dintre", "relation between",
                           "relationship between", "ce depinde de", "ce depind de", "what depends on",
                           "ce contrazice", "contradictii in jurul", "contradicții în jurul",
                           "contradictii exista", "contradicții există", "ce sustine ideea",
                           "ce susține ideea", "unde apare", "concepte legate", "concepte sunt legate",
                           "concepts related", "related concepts", "harta memoriei", "memory map",
                           "camp relational", "câmp relațional", "campul relational", "câmpul relațional",
                           "relation field", "relational field", "campul relational",
                           "schimbat in memoria despre", "schimbat în memoria despre", "what changed about",
                           "invatat recent despre", "învățat recent despre", "ce relatii s-au consolidat",
                           "ce relații s-au consolidat", "relatii au devenit disputate",
                           "relații au devenit disputate", "relatii s-au consolidat recent",
                           "teme recurente", "recurrent themes", "recurring themes",
                           # Cycle 12: relation-aware self-state metrics
                           "concepte iti organizeaza", "concepte îți organizează", "concepte organizeaza memoria",
                           "cele mai centrale", "noduri centrale", "concepte centrale",
                           "zone au cele mai multe contradic", "zone cu cele mai multe contradic",
                           "ce relatii sunt candidate", "ce relații sunt candidate",
                           "relatii s-au intarit recent", "relații s-au întărit recent"]
VAULT_STATUS_TRIGGERS = ["cat din vault ai indexat", "cât din vault ai indexat", "statusul vaultului",
                         "care este statusul vaultului", "vault training status",
                         "ce ai indexat din obsidian", "status vault", "cat ai indexat din vault"]
FOLLOWUP_TRIGGERS = ["de ce conteaza", "de ce contează", "ce inseamna asta", "ce înseamnă asta",
                     "ce urmeaza", "ce urmează", "and so", "why does it matter",
                     "si apoi", "și apoi", "si dupa", "și după", "dupa aceea", "după aceea",
                     "and then", "what next", "continua", "continuă"]
FOLLOWUP_EXACT = {"asa si", "asa si?", "așa și", "așa și?", "si", "si?", "și", "și?", "ok si", "ok si?",
                  "apoi", "apoi?", "si apoi", "si apoi?", "și apoi", "și apoi?", "si dupa?", "și după?"}
# old/historical limitation phrasings that must NOT be reported as current truth
_STALE_LIMITATION = re.compile(
    r"(?i)(never promoted|nu (sunt|au fost) promova|provisional.*never|pas\s*6|"
    r"never consolidat|nu se consolid|last-write-wins|provizoriile nu)")
_SECRET = re.compile(
    r"(?i)\b(password|parol[ăa]|secret|secret[ăa]|private\s+key|cheie\s+(?:privat[ăa]|secret[ăa])|"
    r"api[ _-]?key|token|pin|cod\s+pin|cod\s+de\s+acces|ssn|cnp|iban|credit\s*card|"
    r"card\s+(?:bancar|de\s+credit)|cont\s+bancar)\b")

SELF_ARCHITECTURE_QUERY = "SELF_ARCHITECTURE_QUERY"
SELF_CAPABILITY_QUERY = "SELF_CAPABILITY_QUERY"
SELF_MEMORY_STATE_QUERY = "SELF_MEMORY_STATE_QUERY"
SELF_LIMITATION_QUERY = "SELF_LIMITATION_QUERY"
SELF_RECENT_LEARNING_QUERY = "SELF_RECENT_LEARNING_QUERY"
SELF_INTERNAL_STATE_QUERY = "SELF_INTERNAL_STATE_QUERY"
SELF_DYNAMICS_REPORT_QUERY = "SELF_DYNAMICS_REPORT_QUERY"
SELF_PROOF_QUERY = "SELF_PROOF_QUERY"
CHAT_HISTORY_SUMMARY_QUERY = "CHAT_HISTORY_SUMMARY_QUERY"
MEMORY_ACTION_QUERY = "MEMORY_ACTION_QUERY"
FOLLOWUP_QUERY = "FOLLOWUP_QUERY"
VAULT_TRAINING_STATUS_QUERY = "VAULT_TRAINING_STATUS_QUERY"
USER_VAULT_QUERY = "USER_VAULT_QUERY"
GENERAL_FACT_QUERY = "GENERAL_FACT_QUERY"
SECRET_QUERY = "SECRET_QUERY"
CONTRADICTION_QUERY = "CONTRADICTION_QUERY"
RELATION_FIELD_QUERY = "RELATION_FIELD_QUERY"

# intents answered from the SelfStateProvider (runtime state), never from generic vault
SELF_STATE_INTENTS = {SELF_CAPABILITY_QUERY, SELF_MEMORY_STATE_QUERY,
                      SELF_LIMITATION_QUERY, SELF_RECENT_LEARNING_QUERY, SELF_INTERNAL_STATE_QUERY}
# operational/self-referential intents handled by operational_intents (also never vault)
OPERATIONAL_INTENTS = {SELF_DYNAMICS_REPORT_QUERY, SELF_PROOF_QUERY, CHAT_HISTORY_SUMMARY_QUERY,
                       MEMORY_ACTION_QUERY, FOLLOWUP_QUERY, VAULT_TRAINING_STATUS_QUERY,
                       RELATION_FIELD_QUERY}


def classify_intent(question: str) -> str:
    q = (question or "").lower()
    qn = q.strip().rstrip("?.! ").strip()
    if _SECRET.search(q):
        return SECRET_QUERY
    # vault wins for "what did *I* write / in my notes" (am scris / notele mele)
    if any(t in q for t in VAULT_TRIGGERS):
        return USER_VAULT_QUERY
    # relation-field navigation (Cycle 10) — before contradiction/self-architecture so
    # "ce contradictii exista in jurul FCE-M" / "concepte legate de BYON" reach the relation field.
    if any(t in q for t in RELATION_FIELD_TRIGGERS):
        return RELATION_FIELD_QUERY
    # operational / self-referential commands (runtime state / actions), most specific first
    if any(t in q for t in VAULT_STATUS_TRIGGERS):
        return VAULT_TRAINING_STATUS_QUERY
    if any(t in q for t in MEMORY_ACTION_TRIGGERS):
        return MEMORY_ACTION_QUERY
    if any(t in q for t in DYNAMICS_TRIGGERS):
        return SELF_DYNAMICS_REPORT_QUERY
    if any(t in q for t in PROOF_TRIGGERS):
        return SELF_PROOF_QUERY
    if any(t in q for t in CHAT_SUMMARY_TRIGGERS):
        return CHAT_HISTORY_SUMMARY_QUERY
    # self-introspection about *you* (BYON) — runtime state
    if any(t in q for t in CAPABILITY_TRIGGERS):
        return SELF_CAPABILITY_QUERY
    if any(t in q for t in LIMITATION_TRIGGERS):
        return SELF_LIMITATION_QUERY
    if any(t in q for t in RECENT_LEARNING_TRIGGERS):
        return SELF_RECENT_LEARNING_QUERY
    if any(t in q for t in INTERNAL_STATE_TRIGGERS):
        return SELF_INTERNAL_STATE_QUERY
    if any(t in q for t in MEMORY_STATE_TRIGGERS):
        return SELF_MEMORY_STATE_QUERY
    # short follow-ups (exact or specific phrases) — late so specific intents win
    if qn in FOLLOWUP_EXACT or any(t in q for t in FOLLOWUP_TRIGGERS):
        return FOLLOWUP_QUERY
    if any(t in q for t in CONTRADICTION_TRIGGERS):
        return CONTRADICTION_QUERY
    if any(t in q for t in SELF_TERMS):
        return SELF_ARCHITECTURE_QUERY
    return GENERAL_FACT_QUERY


def is_stale_limitation(text: str) -> bool:
    """True if a retrieved note states an OLD limitation that the current version contradicts
    (e.g. 'provisional entries never promoted' — superseded by v9.9.1 arbitration + v10.3)."""
    return bool(_STALE_LIMITATION.search(text or ""))


def _src(h: Dict[str, Any]) -> str:
    return ((h.get("metadata") or {}).get("source") or h.get("source") or "")


def _trust(h: Dict[str, Any]) -> str:
    return (h.get("metadata") or {}).get("trust") or h.get("trust")


def _sim(h: Dict[str, Any]) -> float:
    v = h.get("similarity", h.get("score"))
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def rerank(hits: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
    """Return hits sorted by combined score (similarity + trust boost + intent boost)."""
    scored = []
    for h in hits:
        src = _src(h)
        tier = TRUST_RANK.get(_trust(h), 1)
        base = _sim(h)
        boost = 0.0
        if intent in (SELF_ARCHITECTURE_QUERY, CONTRADICTION_QUERY):
            boost += 0.18 * tier                       # strongly prefer trusted tiers
            if src.startswith("relation:"):
                boost += 1.0                           # canonical relations first
            elif src.startswith("repo:"):
                boost += 0.6                           # repo/docs next
            elif src.startswith("vault:"):
                boost -= 0.6                            # vault is lower priority here
        elif intent == RELATION_FIELD_QUERY:
            boost += 0.15 * tier                       # prefer trusted relation/repo facts
            if src.startswith("relation:"):
                boost += 1.0
            elif src.startswith("repo:"):
                boost += 0.5
            elif src.startswith("vault:"):
                boost -= 0.4
        elif intent == USER_VAULT_QUERY:
            if src.startswith("vault:"):
                boost += 0.8                            # vault dominates
            elif src.startswith(("relation:", "repo:")):
                boost -= 0.4
            boost += 0.04 * tier
        else:  # GENERAL_FACT_QUERY
            boost += 0.10 * tier
        h = dict(h)
        h["_combined"] = base + boost
        h["_tier"] = tier
        scored.append(h)
    scored.sort(key=lambda x: x["_combined"], reverse=True)
    return scored


def committed(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [h for h in hits if _trust(h) in COMMITTED_TIERS]
