# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Relation-field reports + the RELATION_FIELD_QUERY answer builder (Cycle 10).

Turns the structural relation field into the operator-facing reports (entity neighborhood,
contradiction map, dependency map, recurrent themes, source-class breakdown, recent changes) and
into a grounded natural answer for relation queries. Every answer carries PROVENANCE (the relation
source ids) and a source class, so it still passes source policy + the Auditor - the relation field
describes structure, it never asserts objective truth and never overrides source policy.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from gateway import relation_field as rf

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
    out = []
    for r in contras:
        b = _brief(r)
        ct = field.classify_conflict(r)                    # Cycle 12: explain the conflict TYPE
        b["conflict_type"] = ct
        b["recommended_next_action"] = field._NEXT_ACTION.get(ct, "keep_disputed")  # Cycle 13
        b["current_status"] = "canonical_overrides" if ct == "canonical_conflict" else "active"
        out.append(b)
    return {"focus": focus, "count": len(out), "contradictions": out,
            "history": field.contradiction_history()[:20]}


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


def central_concepts(field: rf.RelationField, *, top_n: int = 10) -> Dict[str, Any]:
    return {"central_concepts": field.central_concepts(top_n)}


def top_disputed_areas(field: rf.RelationField, *, top_n: int = 10) -> Dict[str, Any]:
    return {"disputed_areas": field.disputed_areas(top_n)}


def relation_metrics(field: rf.RelationField) -> Dict[str, Any]:
    return field.relation_metrics()


def relation_context_for(field: rf.RelationField, question: str, *,
                         is_secret: bool = False, limit: int = 8) -> Dict[str, Any]:
    """Cycle 12: committed/reinforced relations the relation field can contribute as CONTEXT to a
    normal answer. Never for secrets; source-policy gated (a vault-only OBJECTIVE relation is
    blocked from being presented as objective structure); ordered by evidence weight. This is
    CONTEXT only - it never overrides a memory fact and cannot answer alone."""
    from gateway import relation_policy as rp
    if is_secret:
        return {"focus": None, "relations": [], "sources": [], "blocked": True, "reason": "secret"}
    focus = _focal_entity(field, question)
    if not focus:
        return {"focus": None, "relations": [], "sources": [], "blocked": False}
    allowed, blocked = [], []
    for r in field.relations_for(focus):
        if r.get("status") not in (rf.COMMITTED, rf.REINFORCED):
            continue
        if rp.context_allowed(r.get("relation_type"), r.get("source_classes", []),
                              subject=r.get("subject")):
            allowed.append(r)
        else:
            blocked.append(r)
    allowed = allowed[:limit]
    return {"focus": focus, "relations": [_brief(r) for r in allowed],
            "sources": _sources_of(allowed), "blocked_count": len(blocked),
            "blocked": False}


_OBJ_RELATION_CUES = ("depinde", "depind", "depends", "influen", "risc", "risk", "sustine", "susține",
                      "supports", "support", "contrazice", "contradic", "consecin", "consequence",
                      "important", "de ce", "why does", "why is", "matter", "leaga", "leagă", "rol",
                      "componente", "what depends", "what supports", "what contradicts")


def relation_context_bundle(field: rf.RelationField, question: str, *, is_secret: bool = False,
                            limit: int = 6) -> Dict[str, Any]:
    """Cycle 13: bundle of policy-gated committed relation CONTEXT for a normal answer, with the
    safety metadata the answer must carry. Empty for secrets. Never primary unless it is the only
    grounding and the source class allows it (the search still ranks memory facts first)."""
    if is_secret:
        return {"used": False, "blocked": True, "reason": "secret query - relation field skipped",
                "hits": [], "relation_ids": [], "source_classes": [], "any_disputed": False,
                "any_candidate": False, "any_decayed": False, "primary": False}
    q = (question or "").lower()
    relevant = any(c in q for c in _OBJ_RELATION_CUES)
    ctx = relation_context_for(field, question, is_secret=False, limit=limit)
    rels = ctx.get("relations", [])
    if not relevant or not rels:
        return {"used": False, "blocked": False, "reason": "no relevant committed relation context",
                "hits": [], "relation_ids": [], "source_classes": [], "any_disputed": False,
                "any_candidate": False, "any_decayed": False, "primary": False,
                "blocked_count": ctx.get("blocked_count", 0)}
    hits = relation_context_hits(field, question, is_secret=False, limit=limit)
    scs = sorted({sc for b in rels for sc in b.get("source_classes", [])})
    return {"used": True, "blocked": False,
            "reason": "policy-allowed committed/reinforced relations (secondary context)",
            "hits": hits, "relation_ids": [b.get("relation_id") for b in rels if b.get("relation_id")],
            "source_classes": scs, "focus": ctx.get("focus"),
            "any_disputed": any(b.get("status") == rf.DISPUTED for b in rels),
            "any_candidate": any(b.get("status") == rf.CANDIDATE for b in rels),
            "any_decayed": any(b.get("decay_status") == "stale" for b in rels),
            "blocked_count": ctx.get("blocked_count", 0), "primary": False}


def relation_context_hits(field: rf.RelationField, question: str, *,
                          is_secret: bool = False, limit: int = 6) -> list:
    """The same committed relation context as memory-service-style hits (source 'relation:...',
    trust per relation_policy) so the normal epistemic search can rerank them WITH memory facts and
    source policy - they never outrank a real committed memory fact."""
    from gateway import relation_policy as rp
    ctx = relation_context_for(field, question, is_secret=is_secret, limit=limit)
    hits = []
    for b in ctx["relations"]:
        trust = rp.commit_trust_for(b["relation_type"], b.get("source_classes", []))
        hits.append({"content": f"{b['subject']} {b['relation_type'].replace('_',' ')} {b['object']}",
                     "metadata": {"source": f"relation:{b['subject']}->{b['relation_type']}->{b['object']}",
                                  "trust": trust}})
    return hits


def render_path_explanation(field: rf.RelationField, start: str, target: Optional[str] = None, *,
                            include_inverse: bool = False, max_depth: int = 2) -> Dict[str, Any]:
    """Cycle 13: a grounded, readable WHY/HOW explanation of the best path. Each hop carries source
    class + evidence quote + confidence + weight + decayed_weight + status + disputed/inverse flags.
    Epistemic status: DISPUTED if any disputed hop; PROVISIONAL if any candidate-only or unsourced
    hop or any inverse-rendered hop; KNOWN only if every hop is committed/canonical AND sourced."""
    res = field.multi_hop_path(start, target, max_depth=max_depth, include_inverse=include_inverse)
    if not res["paths"]:
        return {"found": False, "epistemic_status": "UNKNOWN", "start": start, "target": target,
                "answer": f"Nu exista un drum dirijat (≤{max_depth} hopuri) de la {start}"
                          + (f" la {target}" if target else "") + ".", "hops": [], "sources": ["relation:field"]}
    best = res["paths"][0]
    hops, sources, any_disputed, any_candidate, any_unsourced, any_inverse = [], ["relation:field"], False, False, False, False
    for h in best["hops"]:
        rid_src = h.get("source_ids") or []
        sourced = bool(rid_src)
        status = h.get("status")
        disputed = status == rf.DISPUTED
        candidate_only = status in (rf.CANDIDATE,)
        any_disputed = any_disputed or disputed
        any_candidate = any_candidate or candidate_only
        any_unsourced = any_unsourced or not sourced
        any_inverse = any_inverse or bool(h.get("inverse_rendered"))
        hops.append({"subject": h["subject"], "relation_type": h["relation_type"],
                     "direction": h.get("direction"), "inverse_rendered": bool(h.get("inverse_rendered")),
                     "object": h["object"], "source_classes": h.get("source_classes", []),
                     "source_ids": rid_src[:3], "evidence_quote": h.get("evidence_quote"),
                     "weight": h.get("weight"), "decayed_weight": h.get("decayed_weight"),
                     "confidence": h.get("confidence"), "status": status, "disputed": disputed,
                     "sourced": sourced})
        for sid in rid_src[:2]:
            if sid and sid not in sources:
                sources.append(sid)
    if any_disputed:
        epi, why = "DISPUTED", "a hop on this path is DISPUTED → the whole chain is disputed"
    elif any_unsourced:
        epi, why = "PROVISIONAL", "a hop lacks a source → cannot be asserted as known"
    elif any_candidate:
        epi, why = "PROVISIONAL", "a hop is candidate-only (insufficient independent evidence)"
    elif any_inverse:
        epi, why = "PROVISIONAL", "an inverse hop was RENDERED (not stored as truth)"
    elif best["canonical"] or all(h["status"] == rf.COMMITTED for h in best["hops"]):
        epi, why = "KNOWN", "every hop is committed/canonical and sourced"
    else:
        epi, why = "PROVISIONAL", "mixed-strength chain"
    lines = [f"Drum {start}" + (f" → {target}" if target else "") + f" [{epi}]: {why}."]
    for h in hops:
        tag = "DISPUTED" if h["disputed"] else h["status"]
        inv = " [INVERS RANDAT, nu stocat ca adevăr]" if h["inverse_rendered"] else ""
        qt = (h["evidence_quote"] or "")[:80]
        lines.append(f"  • {h['subject']} {h['relation_type']} {h['object']} "
                     f"[{tag}, {','.join(h['source_classes']) or 'necunoscut'}, w={h['weight']}, "
                     f"dir={h['direction']}]{inv}" + (f" - \"{qt}\"" if qt else ""))
    return {"found": True, "epistemic_status": epi, "why": why, "start": start, "target": target,
            "path_status": best["path_status"], "canonical": best["canonical"],
            "inverse_rendered": any_inverse, "hops": hops, "sources": sources[:12],
            "answer": "\n".join(lines)}


def render_path_explanation_v2(field: rf.RelationField, start: str, target: Optional[str] = None, *,
                               include_inverse: bool = False, max_depth: int = 2) -> Dict[str, Any]:
    """Cycle 15 TRACK G: grounded path explanation v2, built on the per-hop path score (TRACK F).

    Adds, over v1: a path summary; a per-hop explanation; a bottleneck explanation; the final path
    status with WHY it is KNOWN / PROVISIONAL / DISPUTED; relation weights and decayed weights;
    confidence propagation; the source per hop; and a NEXT RECOMMENDED ACTION when the path is weak.
    The relation field is never a truth authority; this only explains, it commits nothing."""
    res = field.multi_hop_path(start, target, max_depth=max_depth, include_inverse=include_inverse)
    if not res["paths"]:
        return {"found": False, "epistemic_status": "UNKNOWN", "start": start, "target": target,
                "path_summary": f"No directed path (<= {max_depth} hops) from {start}"
                                + (f" to {target}" if target else "") + ".",
                "hops": [], "bottleneck": None, "next_recommended_action": None,
                "sources": ["relation:field"]}
    best = res["paths"][0]
    score = best.get("score") or {}
    pstatus = best.get("path_status")
    if pstatus == rf.DISPUTED:
        epi, why = "DISPUTED", "a hop on this path is DISPUTED, so the whole chain is disputed"
    elif pstatus == rf.COMMITTED:
        epi, why = "KNOWN", ("every hop is committed/canonical and sourced"
                             if best.get("canonical") else "every hop is committed and sourced")
    else:
        epi, why = "PROVISIONAL", ("the chain contains a candidate, unsourced, decayed, or "
                                   "inverse-rendered hop, so it cannot be asserted as known")
    per_hop: List[Dict[str, Any]] = []
    sources = ["relation:field"]
    for i, h in enumerate(best["hops"]):
        src_ids = (h.get("source_ids") or [])[:3]
        for sid in src_ids:
            if sid and sid not in sources:
                sources.append(sid)
        per_hop.append({
            "index": i, "subject": h["subject"], "relation_type": h["relation_type"],
            "object": h["object"], "status": h.get("status"), "direction": h.get("direction"),
            "inverse_rendered": bool(h.get("inverse_rendered")), "weight": h.get("weight"),
            "decayed_weight": h.get("decayed_weight"), "confidence": h.get("confidence"),
            "source_classes": h.get("source_classes", []), "source_ids": src_ids,
            "source": (src_ids[0] if src_ids else "unsourced"),
            "evidence_quote": h.get("evidence_quote"),
            "explanation": (f"hop {i}: {h['subject']} {h['relation_type']} {h['object']} "
                            f"[{h.get('status')}, w={h.get('weight')}, "
                            f"decayed={h.get('decayed_weight')}, "
                            f"src={','.join(h.get('source_classes', [])) or 'unknown'}]"
                            + (" (inverse-rendered, not stored as truth)"
                               if h.get("inverse_rendered") else ""))})
    bn = score.get("bottleneck_edge")
    bottleneck = None
    if bn is not None:
        bottleneck = dict(bn)
        bottleneck["explanation"] = (f"the weakest hop is #{bn.get('index')} "
                                     f"({bn.get('subject')} {bn.get('relation_type')} "
                                     f"{bn.get('object')}, weight {bn.get('weight')}); the chain is "
                                     f"only as strong as this hop")
    next_action = None
    if epi != "KNOWN" or float(score.get("path_weight", 0) or 0) < 0.5:
        if epi == "DISPUTED":
            next_action = ("resolve the disputed hop: gather an independent verified source or "
                           "request operator review")
        elif bn is not None:
            next_action = (f"strengthen the bottleneck hop #{bn.get('index')} "
                           f"({bn.get('subject')} {bn.get('relation_type')} {bn.get('object')}): "
                           f"find a verified/project source to reinforce or commit it")
        else:
            next_action = "find a verified source to strengthen the weakest hop"
    path_summary = (f"{start}" + (f" -> {target}" if target else "")
                    + f" [{epi}] path_weight={score.get('path_weight')} status={pstatus}; "
                    + (score.get("explanation") or ""))
    return {"found": True, "epistemic_status": epi, "why": why, "start": start, "target": target,
            "path_status": pstatus, "canonical": best.get("canonical"),
            "path_summary": path_summary, "path_weight": score.get("path_weight"), "score": score,
            "hops": per_hop, "bottleneck": bottleneck,
            "confidence_propagation": {"confidence_product": score.get("confidence_product"),
                                       "per_hop_confidence": [h["confidence"] for h in per_hop]},
            "relation_weights": [h["weight"] for h in per_hop],
            "decayed_weights": [h["decayed_weight"] for h in per_hop],
            "next_recommended_action": next_action, "sources": sources[:12]}


def decayed_relations_report(field: rf.RelationField, *, limit: int = 12) -> Dict[str, Any]:
    return {"decayed_relations": field.decayed_relations(limit=limit)}


def stable_relations_report(field: rf.RelationField, *, limit: int = 12) -> Dict[str, Any]:
    return {"stable_relations": field.stable_relations(limit=limit)}


def weak_central_nodes_report(field: rf.RelationField, *, top_n: int = 10) -> Dict[str, Any]:
    return {"weak_central_nodes": field.weak_central_nodes(top_n=top_n)}


def unresolved_contradictions_report(field: rf.RelationField) -> Dict[str, Any]:
    rows = [c for c in field.contradiction_history()
            if c.get("current_status") not in ("resolved", "superseded")]
    return {"unresolved_contradictions": rows}


def _brief(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"relation_id": r.get("relation_id"), "subject": r["subject"], "predicate": r.get("predicate"),
            "relation_type": r["relation_type"], "object": r["object"], "status": r["status"],
            "source_classes": r.get("source_classes", []), "source_ids": r.get("source_ids", [])[:4],
            "evidence_quote": r.get("evidence_quote"), "method": r.get("method"),
            "origin": r.get("origin"), "weight": rf.relation_weight_score(r),
            "decayed_weight": rf.relation_decay(r)["decayed_weight"],
            "decay_status": rf.relation_decay(r)["decay_status"],
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


def _two_entities(field: rf.RelationField, question: str) -> Any:
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
    quote = f" - citat: \"{q[:120]}\"" if q else ""
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
        inc_inv = any(w in q for w in ("invers", "inverse", "ambele sensuri", "both directions"))
        res = field.multi_hop_path(start, target, max_depth=2, include_inverse=inc_inv)
        if not res["paths"]:
            return _ans("KNOWN", f"Nu exista un drum dirijat (≤2 hopuri) de la {start}"
                        + (f" la {target}" if target else "") + " in campul relational.",
                        ["relation:field"], "VERIFIED_PROJECT_FACT", "path")
        best = res["paths"][0]
        lines = [f"Drum {start}" + (f" → {target}" if target else "") +
                 f" ({best['path_status']}, {'canonic' if best['canonical'] else 'mixt'}, "
                 f"{best['length']} hop, weight {best['weight']}):"]
        srcs = ["relation:field"]
        for h in best["hops"]:
            scs = ",".join(h.get("source_classes") or []) or "necunoscut"
            tag = "DISPUTED" if h.get("status") == rf.DISPUTED else h.get("status")
            qt = (h.get("evidence_quote") or "")[:90]
            inv = " [INVERS RANDAT, nu stocat ca adevăr]" if h.get("inverse_rendered") else ""
            lines.append(f"  • {h['subject']} {h['relation_type']} {h['object']} "
                         f"[{tag}, {scs}, dir={h.get('direction')}]{inv}" + (f" - \"{qt}\"" if qt else ""))
            for sid in (h.get("source_ids") or [])[:2]:
                if sid and sid not in srcs:
                    srcs.append(sid)
        if best.get("inverse_rendered"):
            lines.append("NOTA: " + best.get("note", "contine un hop invers randat (randat, nu stocat ca adevar)."))
        if best["path_status"] == rf.DISPUTED:
            lines.append("ATENTIE: drumul contine un hop DISPUTAT -> intregul lant e provizoriu/disputat.")
        status = "DISPUTED" if best["path_status"] == rf.DISPUTED else "KNOWN"
        return _ans(status, "\n".join(lines), srcs[:12], "VERIFIED_PROJECT_FACT", "path")

    # 0a2) relation-health self-state (Cycle 13): weakened / stable / need-sources / active conflicts
    if any(w in q for w in ("slabit", "slăbit", "decayed", "weakened", "au slabit")):
        rows = field.decayed_relations(limit=10)
        if not rows:
            return _ans("KNOWN", "Nicio relatie nu s-a slabit semnificativ (toate proaspete/stabile).",
                        ["relation:field"], "VERIFIED_PROJECT_FACT", "decayed_relations")
        lines = ["Relatii care s-au slabit in timp (decayed, inca auditabile):"]
        lines += [f"- {r['subject']} {r['relation_type']} {r['object']} [{r['decay_status']}, "
                  f"w={r['decayed_weight']}, {r['decay_reason']}]" for r in rows]
        return _ans("KNOWN", "\n".join(lines), ["relation:field"], "VERIFIED_PROJECT_FACT", "decayed_relations")
    if any(w in q for w in ("cele mai stabile", "stable relations", "relatii stabile", "relații stabile")):
        rows = field.stable_relations(limit=10)
        lines = ["Cele mai stabile relatii (committed/canonical, neafectate de decay):"]
        lines += [f"- {r['subject']} {r['relation_type']} {r['object']} [w={r['decayed_weight']}]" for r in rows]
        return _ans("KNOWN", "\n".join(lines) if rows else "Nu exista inca relatii stabile.",
                    ["relation:field"], "VERIFIED_PROJECT_FACT", "stable_relations")
    if any(w in q for w in ("nevoie de surse", "need sources", "slab sustinute", "slab susținute",
                            "weakly supported", "nevoie de verificare", "need verification")):
        rows = field.weak_central_nodes(top_n=10)
        lines = ["Concepte centrale dar slab sustinute (au nevoie de surse/verificare):"]
        lines += [f"- {r['name']}: grad {r['degree']}, {r['weak_relations']} relatii slabe "
                  f"(ratie {r['weak_ratio']})" for r in rows]
        return _ans("KNOWN", "\n".join(lines) if rows else "Niciun nod central slab sustinut.",
                    ["relation:field"], "VERIFIED_PROJECT_FACT", "weak_central_nodes")
    if any(w in q for w in ("contradictii raman active", "contradicții rămân active", "active contradictions",
                            "contradictii active", "contradicții active")):
        rows = unresolved_contradictions_report(field)["unresolved_contradictions"]
        lines = ["Contradictii inca active (cu actiune recomandata):"]
        lines += [f"- {c.get('incumbent')} ⟂ {c.get('challenger')} [tip: {c.get('conflict_type')}, "
                  f"status: {c.get('current_status')} → {c.get('recommended_next_action')}]" for c in rows[:10]]
        return _ans("KNOWN", "\n".join(lines) if rows else "Nicio contradictie activa.",
                    ["relation:field"], "VERIFIED_PROJECT_FACT", "active_contradictions")

    # 0b) relation-aware self-state metrics: central concepts / disputed areas / candidate relations
    if any(w in q for w in ("centrale", "central", "organizeaza memoria", "organizează memoria",
                            "noduri", "centralitate", "centrality")):
        rows = field.central_concepts(10)
        if not rows:
            return _ans("KNOWN", "Inca nu exista concepte centrale in campul relational.",
                        ["relation:field"], "VERIFIED_PROJECT_FACT", "central_concepts")
        lines = ["Cele mai centrale concepte (grad + centralitate ponderată):"]
        lines += [f"- {r['name']} ({r['type']}): grad {r['degree']}, weight {r['weighted_centrality']}"
                  for r in rows]
        return _ans("KNOWN", "\n".join(lines), ["relation:field"], "VERIFIED_PROJECT_FACT",
                    "central_concepts")
    if any(w in q for w in ("zone", "cele mai multe contradic", "most contradictions", "disputed areas",
                            "zone disputate")):
        rows = field.disputed_areas(10)
        if not rows:
            return _ans("KNOWN", "Nu exista zone cu contradictii in campul relational.",
                        ["relation:field"], "VERIFIED_PROJECT_FACT", "disputed_areas")
        lines = ["Zone cu cele mai multe contradictii:"]
        lines += [f"- {r['name']}: {r['disputed_relations']} relatii disputate" for r in rows]
        return _ans("KNOWN", "\n".join(lines), ["relation:field"], "VERIFIED_PROJECT_FACT",
                    "disputed_areas")
    if any(w in q for w in ("relatii sunt candidate", "relații sunt candidate", "candidate relations",
                            "relatii candidate", "relații candidate")):
        rows = field.candidate_relations(15)
        if not rows:
            return _ans("KNOWN", "Nu exista relatii candidate active.", ["relation:field"],
                        "VERIFIED_PROJECT_FACT", "candidate_relations")
        lines = ["Relatii candidate (neconfirmate, in asteptarea dovezilor):"]
        lines += [_frame(r) for r in rows[:10]]
        return _ans("KNOWN", "\n".join(lines), _sources_of(rows), "VERIFIED_PROJECT_FACT",
                    "candidate_relations")

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
            lines.append(f"- {r['subject']} ⟂ {r['object']} [tip conflict: {r.get('conflict_type')}, "
                         f"{r['status']}, surse {r['source_classes']}]")
        lines.append("(tipuri: canonical_conflict domina; source_scope_conflict = memorie utilizator "
                     "vs obiectiv; temporal_conflict = nota veche vs fapt nou; o nota veche nu inlocuieste "
                     "un fapt canonic mai nou.)")
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
