"""Relation-field reports + the RELATION_FIELD_QUERY answer builder (Cycle 10).

Turns the structural relation field into the operator-facing reports (entity neighborhood,
contradiction map, dependency map, recurrent themes, source-class breakdown, recent changes) and
into a grounded natural answer for relation queries. Every answer carries PROVENANCE (the relation
source ids) and a source class, so it still passes source policy + the Auditor — the relation field
describes structure, it never asserts objective truth and never overrides source policy.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import relation_field as rf

_HOP_WORDS = ("cum ajung", "de la", "pana la", "până la", "path from", "leaga", "leagă", "legătur",
              "depinde de ce depinde", "lant", "lanț", "chain", "via", "prin ce", "drumul")
_VAULT_CLASSES = ("EXTRACTED_USER_CLAIM", "USER_MEMORY_GROUNDED", "USER_PREFERENCE")
_DEP_WORDS = ("depinde", "depind", "depends", "depend on", "ce contine", "ce conține", "componente")
_CONTRA_WORDS = ("contrazice", "contradic", "contradicț", "contradicti", "conflict", "disput", "în jurul",
                 "in jurul")
_THEME_WORDS = ("teme recurente", "recurrent themes", "teme", "themes", "recurring")
_TEMPORAL_WORDS = ("schimbat", "changed", "consolidat recent", "devenit disputate", "recent",
                   "evoluat", "evolved", "istoric")
_SOURCE_WORDS = ("surse", "source class", "source breakdown", "pe clase de sursa", "clase de sursă")
_SUPPORT_WORDS = ("sustine", "susține", "supports", "support")


def entity_neighborhood(field: rf.RelationField, entity: str) -> Dict[str, Any]:
    nb = field.neighborhood(entity)
    return {"entity": entity, "found": nb["found"],
            "related_entities": nb["related_entities"],
            "relations": [_brief(r) for r in nb["relations"]]}


def contradiction_map(field: rf.RelationField, *, focus: Optional[str] = None) -> Dict[str, Any]:
    contras = field.contradictions()
    if focus:
        eid = field.resolve(focus)
        contras = [r for r in contras
                   if field.resolve(r["subject"]) == eid or field.resolve(r["object"]) == eid]
    return {"focus": focus, "count": len(contras), "contradictions": [_brief(r) for r in contras]}


def dependency_map(field: rf.RelationField, *, focus: Optional[str] = None) -> Dict[str, Any]:
    deps = field.dependencies()
    if focus:
        eid = field.resolve(focus)
        deps = [r for r in deps
                if field.resolve(r["subject"]) == eid or field.resolve(r["object"]) == eid]
    return {"focus": focus, "count": len(deps), "dependencies": [_brief(r) for r in deps]}


def recurrent_themes(field: rf.RelationField, *, top_n: int = 10) -> Dict[str, Any]:
    ents = sorted(field._ent.values(), key=lambda e: e.get("mentions", 0), reverse=True)
    themes = [{"name": e["canonical_name"], "type": e["entity_type"], "mentions": e["mentions"]}
              for e in ents if e.get("mentions", 0) >= 1][:top_n]
    return {"themes": themes, "total_entities": len(ents)}


def source_breakdown(field: rf.RelationField) -> Dict[str, Any]:
    return {"by_source_class": field.source_class_breakdown(),
            "by_status": field.counts()["by_status"]}


def recent_relation_changes(field: rf.RelationField, *, limit: int = 15) -> Dict[str, Any]:
    return {"changes": [dict(_brief(r), updated_at=r.get("updated_at"),
                             reinforcement_count=r.get("reinforcement_count", 0),
                             contradicted_at=r.get("contradicted_at"),
                             committed_at=r.get("committed_at")) for r in field.recent_changes(limit)]}


def _brief(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"subject": r["subject"], "predicate": r.get("predicate"),
            "relation_type": r["relation_type"], "object": r["object"], "status": r["status"],
            "source_classes": r.get("source_classes", []), "source_ids": r.get("source_ids", [])[:4],
            "evidence_quote": r.get("evidence_quote"), "method": r.get("method"),
            "origin": r.get("origin"),
            "evidence_count": r.get("evidence_count", 0), "reinforcement_count": r.get("reinforcement_count", 0),
            "contradiction_count": r.get("contradiction_count", 0),
            "first_seen": r.get("first_seen"), "last_seen": r.get("last_seen"),
            "contradicted_at": r.get("contradicted_at")}


def _focal_entity(field: rf.RelationField, question: str) -> Optional[str]:
    """Pick the entity the question is about. Prefer an entity whose FULL canonical name appears as
    a phrase in the question (so 'legate de BYON' picks BYON, not a longer 'BYON gateway' that the
    question never named); among those, the longest. Else fall back to the longest token match."""
    q = (question or "").lower()
    found = field.search(question)["entities"]
    if not found:
        return None
    named = [e for e in found if e["canonical_name"].lower() in q
             or any(a.lower() in q for a in e.get("aliases", []))]
    pool = named or found
    pool.sort(key=lambda e: len(e["canonical_name"]), reverse=True)
    return pool[0]["canonical_name"]


def _two_entities(field: rf.RelationField, question: str):
    """Find the two entities a path question mentions, ordered by position in the question."""
    q = (question or "").lower()
    found = field.search(question)["entities"]
    pos = []
    for e in found:
        i = q.find(e["canonical_name"].lower())
        if i < 0:
            i = min((q.find(a.lower()) for a in e.get("aliases", []) if a.lower() in q), default=-1)
        if i >= 0:
            pos.append((i, e["canonical_name"]))
    pos.sort()
    names = [n for _, n in pos]
    return (names[0] if names else None, names[1] if len(names) > 1 else None)


def _frame(r: Dict[str, Any]) -> str:
    """One human line for a relation: status + source class + (vault framing) + quote."""
    scs = r.get("source_classes") or []
    vault = any(sc in _VAULT_CLASSES for sc in scs) and not (set(scs) & set(rf.CANONICAL_SOURCE_CLASSES))
    frame = "in memoria ta (vault, nu adevăr obiectiv)" if vault else (",".join(scs) or "necunoscut")
    q = (r.get("evidence_quote") or "").strip()
    quote = f" — citat: \"{q[:120]}\"" if q else ""
    return (f"- {r['subject']} {r['relation_type']} {r['object']} "
            f"[{r.get('status')}, sursă: {frame}]{quote}")


def _sources_of(rels: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = ["relation:field"]
    for r in rels:
        for sid in (r.get("source_ids") or [])[:3]:
            if sid and sid not in out:
                out.append(sid)
    return out[:12]


def _best_source_class(rels: List[Dict[str, Any]]) -> str:
    best, best_rank = "UNKNOWN", -1
    for r in rels:
        for sc in r.get("source_classes", []):
            rank = rf._SRC_RANK.get(sc, 1)
            if rank > best_rank:
                best, best_rank = sc, rank
    return best


def render_answer(field: rf.RelationField, question: str) -> Dict[str, Any]:
    """Build a grounded relation answer. Returns {status, answer, sources, source_class, kind}.
    DISPUTED relations are surfaced AS disputed; nothing is asserted as objective truth here."""
    q = (question or "").lower()
    focus = _focal_entity(field, question)

    # 0) multi-hop path: "cum ajung de la X la Y", "ce depinde de ce depinde de X", "ce leagă X de Y"
    if any(w in q for w in _HOP_WORDS):
        start, target = _two_entities(field, question)
        start = start or focus
        if not start:
            return _ans("ASK_USER_FOR_SOURCE", "De la ce entitate pornesc? (ex. BYON, D_Cortex)",
                        ["relation:field"], "VERIFIED_PROJECT_FACT", "path")
        res = field.multi_hop_path(start, target, max_depth=2)
        if not res["paths"]:
            return _ans("KNOWN", f"Nu exista un drum (≤2 hopuri) de la {start}"
                        + (f" la {target}" if target else "") + " in campul relational.",
                        ["relation:field"], "VERIFIED_PROJECT_FACT", "path")
        best = res["paths"][0]
        lines = [f"Drum {start}" + (f" → {target}" if target else "") +
                 f" ({best['path_status']}, {'canonic' if best['canonical'] else 'mixt'}, "
                 f"{best['length']} hop):"]
        srcs = ["relation:field"]
        for h in best["hops"]:
            scs = ",".join(h.get("source_classes") or []) or "necunoscut"
            tag = "DISPUTED" if h.get("status") == rf.DISPUTED else h.get("status")
            qt = (h.get("evidence_quote") or "")[:90]
            lines.append(f"  • {h['subject']} {h['relation_type']} {h['object']} "
                         f"[{tag}, {scs}]" + (f" — \"{qt}\"" if qt else ""))
            for sid in (h.get("source_ids") or [])[:2]:
                if sid and sid not in srcs:
                    srcs.append(sid)
        if best["path_status"] == rf.DISPUTED:
            lines.append("ATENTIE: drumul contine un hop DISPUTAT -> intregul lant e provizoriu/disputat.")
        status = "DISPUTED" if best["path_status"] == rf.DISPUTED else "KNOWN"
        return _ans(status, "\n".join(lines), srcs[:12], "VERIFIED_PROJECT_FACT", "path")

    # 1) contradictions around X / global contradiction map
    if any(w in q for w in _CONTRA_WORDS):
        rep = contradiction_map(field, focus=focus)
        rels = field.contradictions()
        if focus:
            eid = field.resolve(focus)
            rels = [r for r in rels if field.resolve(r["subject"]) == eid or field.resolve(r["object"]) == eid]
        if not rep["contradictions"]:
            return _ans("KNOWN", f"Nu exista contradictii inregistrate in campul relational"
                        + (f" in jurul lui {focus}" if focus else "") + ".", ["relation:field"],
                        "VERIFIED_PROJECT_FACT", "contradiction_map")
        lines = [f"Contradictii (relatii DISPUTED){' in jurul lui ' + focus if focus else ''}:"]
        for r in rep["contradictions"][:8]:
            lines.append(f"- {r['subject']} ⟂ {r['object']} [{r['status']}, surse {r['source_classes']}]")
        return _ans("KNOWN", "\n".join(lines), _sources_of(rels), "VERIFIED_PROJECT_FACT",
                    "contradiction_map")

    # 2) dependencies / components of X
    if any(w in q for w in _DEP_WORDS):
        rep = dependency_map(field, focus=focus)
        rels = [r for r in field.dependencies()
                if not focus or field.resolve(r["subject"]) == field.resolve(focus)
                or field.resolve(r["object"]) == field.resolve(focus)]
        if not rep["dependencies"]:
            return _ans("KNOWN", "Nu exista dependente/componente inregistrate"
                        + (f" pentru {focus}" if focus else "") + ".", ["relation:field"],
                        "VERIFIED_PROJECT_FACT", "dependency_map")
        lines = [f"Dependente / componente{' ale lui ' + focus if focus else ''}:"]
        for r in rep["dependencies"][:10]:
            lines.append(f"- {r['subject']} {r['relation_type']} {r['object']} [{r['status']}]")
        return _ans("KNOWN", "\n".join(lines), _sources_of(rels),
                    _best_source_class(rels), "dependency_map")

    # 3) recurrent themes
    if any(w in q for w in _THEME_WORDS) and "byon" not in q and not focus:
        rep = recurrent_themes(field)
        if not rep["themes"]:
            return _ans("KNOWN", "Inca nu exista teme recurente in campul relational.",
                        ["relation:field"], "VERIFIED_PROJECT_FACT", "recurrent_themes")
        lines = ["Teme recurente (entitati cele mai mentionate):"]
        for t in rep["themes"]:
            lines.append(f"- {t['name']} ({t['type']}, {t['mentions']} mentiuni)")
        return _ans("KNOWN", "\n".join(lines), ["relation:field"], "VERIFIED_PROJECT_FACT",
                    "recurrent_themes")

    # 4) temporal: what changed recently
    if any(w in q for w in _TEMPORAL_WORDS):
        rep = recent_relation_changes(field, limit=10)
        if focus:
            eid = field.resolve(focus)
            rep["changes"] = [c for c in rep["changes"]
                              if field.resolve(c["subject"]) == eid or field.resolve(c["object"]) == eid]
        if not rep["changes"]:
            return _ans("KNOWN", "Nu exista schimbari recente inregistrate in campul relational.",
                        ["relation:field"], "VERIFIED_PROJECT_FACT", "recent_changes")
        lines = [f"Schimbari recente in memoria relationala{' despre ' + focus if focus else ''}:"]
        for c in rep["changes"][:8]:
            tag = "DISPUTED" if c.get("contradicted_at") else c["status"]
            lines.append(f"- {c['subject']} {c['relation_type']} {c['object']} "
                         f"[{tag}, reinforced×{c['reinforcement_count']}, {c['updated_at']}]")
        rels = field.recent_changes(10)
        return _ans("KNOWN", "\n".join(lines), _sources_of(rels), "VERIFIED_PROJECT_FACT",
                    "recent_changes")

    # 5) source-class breakdown
    if any(w in q for w in _SOURCE_WORDS):
        rep = source_breakdown(field)
        lines = ["Distributia relatiilor pe clase de sursa:"]
        for sc, n in sorted(rep["by_source_class"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {sc}: {n}")
        return _ans("KNOWN", "\n".join(lines), ["relation:field"], "VERIFIED_PROJECT_FACT",
                    "source_breakdown")

    # 6) default: entity neighborhood (concepts related to X / relation map of X)
    if focus:
        nb = field.neighborhood(focus)
        if not nb["relations"]:
            return _ans("ASK_USER_FOR_SOURCE",
                        f"Nu am relatii inregistrate pentru '{focus}' in campul relational. "
                        "Pot reconstrui campul (rebuild) sau pot cauta in memorie.",
                        ["relation:field"], "VERIFIED_PROJECT_FACT", "neighborhood")
        rels = nb["relations"]
        committed_or_canon = [r for r in rels if r.get("status") in (rf.COMMITTED, rf.DISPUTED)
                              or set(r.get("source_classes", [])) & set(rf.CANONICAL_SOURCE_CLASSES)]
        # weak: only low-evidence candidate relations -> do not overstate
        if not committed_or_canon and all(r.get("status") == rf.CANDIDATE for r in rels):
            lines = [f"Pentru {nb['entity']['canonical_name']} am doar relatii CANDIDAT "
                     "(dovezi insuficiente, neconfirmate):"]
            lines += [_frame(r) for r in rels[:8]]
            lines.append("Nu sunt suficiente dovezi independente pentru a confirma aceste relatii.")
            return _ans("ASK_USER_FOR_SOURCE", "\n".join(lines), _sources_of(rels),
                        _best_source_class(rels), "neighborhood_weak")
        lines = [f"Camp relational pentru {nb['entity']['canonical_name']} "
                 f"({nb['entity']['entity_type']}):"]
        lines += [_frame(r) for r in rels[:10]]
        lines.append(f"Concepte legate: {', '.join(nb['related_entities'][:8])}")
        return _ans("KNOWN", "\n".join(lines), _sources_of(rels),
                    _best_source_class(rels), "neighborhood")

    return _ans("ASK_USER_FOR_SOURCE",
                "Despre ce entitate? Pot arata campul relational pentru BYON, D_Cortex, FCE-M etc.",
                ["relation:field"], "VERIFIED_PROJECT_FACT", "none")


def _ans(status: str, answer: str, sources: List[str], source_class: str, kind: str) -> Dict[str, Any]:
    return {"status": status, "answer": answer, "sources": sources,
            "source_class": source_class, "kind": kind}
