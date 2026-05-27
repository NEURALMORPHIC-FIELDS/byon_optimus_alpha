"""Relational memory field (Cycle 10, v1).

A navigation/structure layer OVER the memory BYON already has — committed facts, candidates,
disputes, vault chunks, session events, LifeLoop task results and semantic evidence. It lets BYON
answer not only "what do I know?" but "how are these related?", "what depends on what?", "where
are the contradictions?", "which themes recur?", "what changed over time?".

It is explicitly NOT a truth authority and NOT another vector store:
  * it stores entities + typed relations with PROVENANCE and a trust/source class — never raw text
    re-embedded into a parallel index;
  * canonical/system relations outrank vault/user relations;
  * disputed relations stay visible AS disputed (never silently dropped or merged into truth);
  * answers built from it still pass source policy + the Auditor — the field never commits a
    relation as objective truth on its own and never overrides source policy.

The store is two append-only JSONL ledgers (entities, edges) with last-record-wins per id, kept in
the same namespace as the candidate lifecycle so the relation field is a sibling of, not a
replacement for, the canonical memory-service.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# the relation field NAVIGATES; BYON + source policy + Auditor remain the only truth authority.
IS_TRUTH_AUTHORITY = False
ANSWERS_USER_DIRECTLY = False

# allowed relation types (predicate is normalised into one of these)
HAS_COMPONENT = "has_component"
ROLE_OF = "role_of"
DEPENDS_ON = "depends_on"
SUPPORTS = "supports"
CONTRADICTS = "contradicts"
REFINES = "refines"
BROADER_THAN = "broader_than"
NARROWER_THAN = "narrower_than"
CAUSED_BY = "caused_by"
DERIVED_FROM = "derived_from"
MENTIONED_IN = "mentioned_in"
BELONGS_TO_PROJECT = "belongs_to_project"
USER_PREFERS = "user_prefers"
USER_CORRECTED = "user_corrected"
SOURCE_CONFIRMS = "source_confirms"
SOURCE_DISPUTES = "source_disputes"
CONSOLIDATION_PROMOTED = "consolidation_promoted"
CANDIDATE_CHALLENGER_OF = "candidate_challenger_of"
RELATION_TYPES = {HAS_COMPONENT, ROLE_OF, DEPENDS_ON, SUPPORTS, CONTRADICTS, REFINES, BROADER_THAN,
                  NARROWER_THAN, CAUSED_BY, DERIVED_FROM, MENTIONED_IN, BELONGS_TO_PROJECT,
                  USER_PREFERS, USER_CORRECTED, SOURCE_CONFIRMS, SOURCE_DISPUTES,
                  CONSOLIDATION_PROMOTED, CANDIDATE_CHALLENGER_OF}

# relation status
CANDIDATE = "candidate"
REINFORCED = "reinforced"
COMMITTED = "committed"
DISPUTED = "disputed"
ARCHIVED = "archived"

# directed semantics (Cycle 12): how a stored (subject -> object) edge may be traversed/rendered.
FORWARD = "forward"                  # traverse subject -> object only
BIDIRECTIONAL = "bidirectional"      # traverse both ways (e.g. contradicts)
INVERSE_RENDERABLE = "inverse_renderable"  # forward stored; the inverse may be RENDERED (not stored) on request
_DIRECTIONALITY = {
    HAS_COMPONENT: FORWARD, DEPENDS_ON: FORWARD, CAUSED_BY: FORWARD, DERIVED_FROM: FORWARD,
    SUPPORTS: FORWARD, MENTIONED_IN: FORWARD, ROLE_OF: FORWARD, BELONGS_TO_PROJECT: FORWARD,
    CONSOLIDATION_PROMOTED: FORWARD, CANDIDATE_CHALLENGER_OF: FORWARD, REFINES: FORWARD,
    SOURCE_CONFIRMS: FORWARD, SOURCE_DISPUTES: FORWARD, USER_PREFERS: FORWARD, USER_CORRECTED: FORWARD,
    CONTRADICTS: BIDIRECTIONAL,
    BROADER_THAN: INVERSE_RENDERABLE, NARROWER_THAN: INVERSE_RENDERABLE,
}
_INVERSE_TYPE = {BROADER_THAN: NARROWER_THAN, NARROWER_THAN: BROADER_THAN}


def directionality(relation_type: str) -> str:
    return _DIRECTIONALITY.get(relation_type, FORWARD)


_STATUS_W = {COMMITTED: 0.40, REINFORCED: 0.25, CANDIDATE: 0.05, DISPUTED: -0.30, ARCHIVED: -0.20}
_OBJECTIVE_TYPES_W = {HAS_COMPONENT, DEPENDS_ON, ROLE_OF, CAUSED_BY, DERIVED_FROM, BROADER_THAN,
                      NARROWER_THAN, REFINES, BELONGS_TO_PROJECT}
_USER_CLASSES_W = {"USER_PREFERENCE", "USER_MEMORY_GROUNDED", "EXTRACTED_USER_CLAIM"}


def relation_weight_score(r: Dict[str, Any], *, now_ts: Optional[float] = None,
                          tombstoned: bool = False) -> float:
    """Evidence/source-weighted score in [0,1] used to rank relations everywhere (neighborhoods,
    dependency/contradiction maps, multi-hop paths, normal-answer context). Rewards committed/
    reinforced status, source-class rank, independent evidence, quality, recency, canonical origin;
    penalises disputed/candidate-only, vault-only OBJECTIVE relations, staleness, tombstoned source,
    low confidence and weak (Claude-advisory) inference."""
    now_ts = now_ts if now_ts is not None else time.time()
    classes = set(r.get("source_classes", []))
    ev = len(set(r.get("source_ids", [])))
    rank = max((_SRC_RANK.get(sc, 1) for sc in classes), default=1)
    canonical = r.get("origin") == "canonical_schema" or "SYSTEM_CANONICAL" in classes
    w = 0.30
    w += _STATUS_W.get(r.get("status"), 0.0)
    w += 0.05 * rank                                       # source-class rank
    w += 0.05 * min(ev, 4)                                 # independent evidence
    w += 0.15 * float(r.get("confidence", 0.5))
    w += 0.15 if canonical else 0.0
    w += 0.05 if ev >= 2 else 0.0                          # multiple independent sources
    try:
        age_days = (now_ts - time.mktime(time.strptime(
            r.get("last_seen") or r.get("updated_at") or "", "%Y-%m-%dT%H:%M:%SZ"))) / 86400.0
    except (ValueError, TypeError):
        age_days = 0.0
    w += 0.08 if age_days < 7 else (0.0 if age_days < 30 else -0.10)
    # negatives
    if r.get("relation_type") in _OBJECTIVE_TYPES_W and classes and classes <= _USER_CLASSES_W:
        w -= 0.20                                          # vault-only objective relation
    if tombstoned:
        w -= 0.50
    if r.get("method") == "claude_advisory":
        w -= 0.10                                          # weak inference method
    if float(r.get("confidence", 0.5)) < 0.5:
        w -= 0.05
    return round(max(0.0, min(1.0, w)), 4)


def _decay_cfg() -> Dict[str, Any]:
    g = os.environ.get
    return {
        "enabled": g("BYON_RELATION_DECAY_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on"),
        "half_life": float(g("BYON_RELATION_DECAY_HALF_LIFE_DAYS", "30") or 30),
        "min_weight": float(g("BYON_RELATION_DECAY_MIN_WEIGHT", "0.15") or 0.15),
        "mult_canonical": float(g("BYON_CANONICAL_DECAY_MULTIPLIER", "0.0") or 0.0),
        "mult_committed": float(g("BYON_COMMITTED_DECAY_MULTIPLIER", "0.35") or 0.35),
        "mult_candidate": float(g("BYON_CANDIDATE_DECAY_MULTIPLIER", "1.0") or 1.0),
        "mult_disputed": float(g("BYON_DISPUTED_DECAY_MULTIPLIER", "1.5") or 1.5),
    }


def _age_days(r: Dict[str, Any], now_ts: float) -> float:
    ref = r.get("last_reinforced_at") or r.get("last_seen") or r.get("updated_at") or ""
    try:
        return max(0.0, (now_ts - time.mktime(time.strptime(ref, "%Y-%m-%dT%H:%M:%SZ"))) / 86400.0)
    except (ValueError, TypeError):
        return 0.0


def relation_decay(r: Dict[str, Any], *, now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Temporal trust decay (Cycle 13). Returns {decay_factor, decayed_weight, decay_status,
    decay_reason, age_days, base_weight}. Old/weak/unreinforced/disputed relations LOSE ranking
    weight; canonical resists (multiplier 0); committed decays slower than candidate; reinforcement
    recovers weight. Decay NEVER deletes or archives — it only lowers influence and stays auditable."""
    now_ts = now_ts if now_ts is not None else time.time()
    cfg = _decay_cfg()
    tomb = bool(r.get("tombstoned"))
    base = relation_weight_score(r, now_ts=now_ts, tombstoned=tomb)
    if not cfg["enabled"]:
        return {"decay_factor": 1.0, "decayed_weight": base, "decay_status": "disabled",
                "decay_reason": "decay disabled", "age_days": 0.0, "base_weight": base}
    classes = set(r.get("source_classes", []))
    canonical = r.get("origin") == "canonical_schema" or "SYSTEM_CANONICAL" in classes
    status = r.get("status")
    if canonical:
        mult, why = cfg["mult_canonical"], "canonical (resists decay)"
    elif status == DISPUTED:
        mult, why = cfg["mult_disputed"], "disputed (decays faster)"
    elif status == COMMITTED:
        mult, why = cfg["mult_committed"], "committed (decays slower)"
    else:
        mult, why = cfg["mult_candidate"], "candidate-only"
    if "VERIFIED_PROJECT_FACT" in classes:
        mult *= 0.4
    elif "DOMAIN_VERIFIED" in classes:
        mult *= 0.7
    if len(set(r.get("source_ids", []))) >= 2:
        mult *= 0.7                                        # multiple independent sources resist
    if r.get("method") == "claude_advisory":
        mult *= 1.3                                        # weak method decays faster
    age = _age_days(r, now_ts)
    if tomb:
        factor = 0.2                                       # tombstoned source decays hard
        why = "tombstoned source"
    elif mult <= 0 or cfg["half_life"] <= 0:
        factor = 1.0
    else:
        factor = 0.5 ** (age * mult / cfg["half_life"])
    decayed = round(max(cfg["min_weight"], base * factor), 4)
    decay_status = "fresh" if factor >= 0.8 else ("decaying" if factor >= 0.4 else "stale")
    return {"decay_factor": round(factor, 4), "decayed_weight": decayed, "decay_status": decay_status,
            "decay_reason": f"{why}; age {age:.0f}d, half-life {cfg['half_life']:.0f}d", "age_days": round(age, 1),
            "base_weight": base}

# raw predicate -> normalised relation type
_PRED_MAP = {
    "has_component": HAS_COMPONENT, "component_of": HAS_COMPONENT, "has component": HAS_COMPONENT,
    "role": ROLE_OF, "not_role": ROLE_OF, "function": ROLE_OF, "operational_level": ROLE_OF,
    "epistemic_contract": ROLE_OF, "role_of": ROLE_OF,
    "depends_on": DEPENDS_ON, "depends": DEPENDS_ON,
    "supports": SUPPORTS, "support": SUPPORTS, "same_claim": SUPPORTS,
    "contradicts": CONTRADICTS, "canonical_conflict": CONTRADICTS,
    "refines": REFINES, "narrows": NARROWER_THAN, "broadens": BROADER_THAN,
    "broader_than": BROADER_THAN, "narrower_than": NARROWER_THAN,
    "caused_by": CAUSED_BY, "derived_from": DERIVED_FROM, "mentioned_in": MENTIONED_IN,
    "belongs_to_project": BELONGS_TO_PROJECT, "user_prefers": USER_PREFERS,
    "user_corrected": USER_CORRECTED, "source_confirms": SOURCE_CONFIRMS,
    "source_disputes": SOURCE_DISPUTES, "consolidation_promoted": CONSOLIDATION_PROMOTED,
    "candidate_challenger_of": CANDIDATE_CHALLENGER_OF,
}

# trust rank per source class — canonical/system relations outrank vault/user relations.
_SRC_RANK = {"SYSTEM_CANONICAL": 6, "VERIFIED_PROJECT_FACT": 5, "DOMAIN_VERIFIED": 4,
             "USER_PREFERENCE": 3, "USER_MEMORY_GROUNDED": 3, "EXTRACTED_USER_CLAIM": 2,
             "PROVISIONAL_WEB": 1, "RECENT_WRITE_BUFFER": 1, "UNKNOWN": 1, None: 1, "": 1,
             "DISPUTED_OR_UNSAFE": 0}
CANONICAL_SOURCE_CLASSES = {"SYSTEM_CANONICAL", "VERIFIED_PROJECT_FACT"}

# light entity typing for the well-known project components (else "concept")
_ENTITY_TYPES = {
    "byon": "system", "d_cortex": "component", "fce-m": "component", "fce-m v15.7a": "component",
    "claude": "faculty", "memory-service": "component", "faiss semantic memory-service": "component",
    "auditor": "component", "web search": "source",
}
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_\-\.]*")
_STOP = {"the", "a", "an", "is", "are", "of", "to", "in", "on", "and", "or", "for", "that", "este",
         "si", "și", "la", "de", "ce", "un", "o"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _eid(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _norm(name)).strip("_")[:48] or "x"
    return "ent_" + slug


def _rid(subject: str, predicate: str, obj: str) -> str:
    h = hashlib.sha1(f"{_norm(subject)}|{predicate}|{_norm(obj)}".encode("utf-8")).hexdigest()
    return "rel_" + h[:12]


def _rtype(predicate: str) -> str:
    return _PRED_MAP.get((predicate or "").strip().lower(), MENTIONED_IN)


def _tokens(s: str) -> set:
    return {t for t in _TOKEN.findall((s or "").lower()) if t not in _STOP and len(t) > 1}


def parse_relation_source(src: str) -> Optional[tuple]:
    """A canonical relation fact stores its triple in the source: 'relation:SUBJ->PRED->OBJ'."""
    if not src or not src.startswith("relation:"):
        return None
    body = src[len("relation:"):]
    parts = body.split("->")
    if len(parts) != 3:
        return None
    return parts[0].strip(), parts[1].strip(), parts[2].strip()


class RelationField:
    def __init__(self, namespace_dir: str | Path) -> None:
        self.dir = Path(namespace_dir)
        self.entities_path = self.dir / "relation_entities.jsonl"
        self.edges_path = self.dir / "relation_edges.jsonl"
        self.contradictions_path = self.dir / "relation_contradictions.jsonl"   # Cycle 13 ledger
        self._ent: Dict[str, Dict[str, Any]] = {}
        self._rel: Dict[str, Dict[str, Any]] = {}
        self._contra: Dict[str, Dict[str, Any]] = {}
        self._alias: Dict[str, str] = {}     # normalised alias/name -> entity_id
        self._load()

    # -- ledger -------------------------------------------------------------
    def _load(self) -> None:
        for path, sink in ((self.entities_path, self._ent), (self.edges_path, self._rel)):
            if not path.exists():
                continue
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        r = json.loads(line)
                        key = r.get("entity_id") or r.get("relation_id")
                        if key:
                            sink[key] = r
            except (OSError, json.JSONDecodeError):
                pass
        if self.contradictions_path.exists():
            try:
                for line in self.contradictions_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        c = json.loads(line)
                        self._contra[c["contradiction_id"]] = c   # last record wins
            except (OSError, json.JSONDecodeError):
                pass
        for e in self._ent.values():
            self._alias[_norm(e["canonical_name"])] = e["entity_id"]
            for a in e.get("aliases", []):
                self._alias[_norm(a)] = e["entity_id"]

    def _append(self, path: Path, rec: Dict[str, Any]) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def is_empty(self) -> bool:
        return not self._rel and not self._ent

    # -- entities -----------------------------------------------------------
    def resolve(self, name: str) -> Optional[str]:
        return self._alias.get(_norm(name))

    def add_entity(self, name: str, *, entity_type: Optional[str] = None,
                   source_class: Optional[str] = None, ts: Optional[str] = None) -> Dict[str, Any]:
        name = (name or "").strip()[:120] or "(unnamed)"
        now = ts or _now()
        eid = self.resolve(name) or _eid(name)
        etype = entity_type or _ENTITY_TYPES.get(_norm(name), "concept")
        e = self._ent.get(eid)
        if e is None:
            e = {"entity_id": eid, "canonical_name": name, "aliases": [], "entity_type": etype,
                 "source_classes": [source_class] if source_class else [], "first_seen": now,
                 "last_seen": now, "mentions": 1, "confidence": 0.5}
        else:
            e["mentions"] = e.get("mentions", 0) + 1
            e["last_seen"] = now
            if source_class and source_class not in e["source_classes"]:
                e["source_classes"].append(source_class)
            if e.get("entity_type", "concept") == "concept" and etype != "concept":
                e["entity_type"] = etype
            e["confidence"] = round(min(0.95, 0.5 + 0.05 * e["mentions"]), 3)
        self._ent[eid] = e
        self._alias[_norm(name)] = eid
        self._append(self.entities_path, e)
        return e

    def register_alias(self, canonical_name: str, alias: str) -> Optional[Dict[str, Any]]:
        """Merge `alias` into the entity for `canonical_name` (e.g. 'D-Cortex' -> 'D_Cortex')."""
        eid = self.resolve(canonical_name)
        if eid is None:
            return None
        e = self._ent[eid]
        if _norm(alias) != _norm(canonical_name) and alias not in e["aliases"]:
            e["aliases"].append(alias)
        self._alias[_norm(alias)] = eid
        self._ent[eid] = e
        self._append(self.entities_path, e)
        return e

    # -- relations ----------------------------------------------------------
    def _status_for(self, rel: Dict[str, Any], explicit: Optional[str]) -> str:
        if rel.get("contradiction_count", 0) > 0:
            return DISPUTED
        if explicit in (ARCHIVED, COMMITTED, REINFORCED, CANDIDATE, DISPUTED):
            return explicit
        # canonical schema / SYSTEM_CANONICAL commit directly (the declared project structure);
        # INFERRED relations (Cycle 11) start as candidates and only commit via consolidate().
        if rel.get("origin") == "canonical_schema" or "SYSTEM_CANONICAL" in rel.get("source_classes", []):
            return COMMITTED
        return REINFORCED if rel.get("evidence_count", 0) >= 2 else CANDIDATE

    def add_relation(self, subject: str, predicate: str, obj: str, *,
                     relation_type: Optional[str] = None, source_id: Optional[str] = None,
                     source_class: Optional[str] = None, status: Optional[str] = None,
                     is_contradiction: bool = False, ts: Optional[str] = None,
                     origin: str = "inferred", evidence_quote: Optional[str] = None,
                     method: Optional[str] = None, confidence: Optional[float] = None) -> Dict[str, Any]:
        now = ts or _now()
        subject, obj = (subject or "").strip()[:160], (obj or "").strip()[:200]
        rtype = relation_type if relation_type in RELATION_TYPES else _rtype(predicate)
        if rtype == CONTRADICTS:
            is_contradiction = True
        self.add_entity(subject, source_class=source_class, ts=now)
        self.add_entity(obj, source_class=source_class, ts=now)
        rid = _rid(subject, predicate, obj)
        r = self._rel.get(rid)
        if r is None:
            r = {"relation_id": rid, "subject": subject, "predicate": predicate, "object": obj,
                 "relation_type": rtype, "source_ids": [], "source_classes": [],
                 "evidence_count": 0, "contradiction_count": 0, "confidence": 0.5,
                 "status": CANDIDATE, "created_at": now, "updated_at": now,
                 # Cycle 11: provenance + inference origin
                 "origin": origin, "evidence_quote": evidence_quote, "method": method,
                 # temporal tracking
                 "first_seen": now, "last_seen": now, "last_reinforced_at": now,
                 "reinforcement_count": 0, "tombstoned": False,
                 "contradicted_at": None, "committed_at": None, "archived_at": None,
                 "source_history": []}
            action = "created"
        else:
            action = "reinforced" if (source_id not in r.get("source_ids", [])) else "seen"
            if evidence_quote and not r.get("evidence_quote"):
                r["evidence_quote"] = evidence_quote
            if method and not r.get("method"):
                r["method"] = method
            if origin == "canonical_schema":              # an inferred edge later confirmed canonical
                r["origin"] = "canonical_schema"
        if source_id and source_id not in r["source_ids"]:
            r["source_ids"].append(source_id)
            r["evidence_count"] = r.get("evidence_count", 0) + 1
            r["last_reinforced_at"] = now                  # Cycle 13: reinforcement recovers from decay
            if action == "reinforced":
                r["reinforcement_count"] = r.get("reinforcement_count", 0) + 1
        if source_class and source_class not in r["source_classes"]:
            r["source_classes"].append(source_class)
        if is_contradiction:
            r["contradiction_count"] = r.get("contradiction_count", 0) + 1
            r["contradicted_at"] = now
            action = "contradicted"
        r["last_seen"] = now
        r["updated_at"] = now
        r["confidence"] = round(min(0.95, 0.4 + 0.15 * r["evidence_count"]), 3)
        if confidence is not None:
            r["confidence"] = round(max(r["confidence"], min(0.95, float(confidence))), 3)
        r["status"] = self._status_for(r, status)
        if r["status"] == COMMITTED and not r.get("committed_at"):
            r["committed_at"] = now
        if r["status"] == ARCHIVED and not r.get("archived_at"):
            r["archived_at"] = now
        r["source_history"].append({"ts": now, "source_id": source_id,
                                    "source_class": source_class, "action": action})
        self._rel[rid] = r
        self._append(self.edges_path, r)
        return r

    # -- queries ------------------------------------------------------------
    def get_entity(self, name: str) -> Optional[Dict[str, Any]]:
        eid = self.resolve(name)
        return self._ent.get(eid) if eid else None

    def relations_for(self, name: str) -> List[Dict[str, Any]]:
        eid = self.resolve(name)
        if not eid:
            return []
        out = [r for r in self._rel.values()
               if self.resolve(r["subject"]) == eid or self.resolve(r["object"]) == eid]
        return sorted(out, key=self._priority, reverse=True)

    def neighborhood(self, name: str) -> Dict[str, Any]:
        e = self.get_entity(name)
        rels = self.relations_for(name)
        eid = self.resolve(name)
        related = []
        seen = set()
        for r in rels:
            other = r["object"] if self.resolve(r["subject"]) == eid else r["subject"]
            if _norm(other) not in seen:
                seen.add(_norm(other))
                related.append(other)
        return {"entity": e, "query": name, "found": e is not None,
                "relations": rels, "related_entities": related}

    def contradictions(self) -> List[Dict[str, Any]]:
        out = [r for r in self._rel.values()
               if r.get("status") == DISPUTED or r.get("contradiction_count", 0) > 0]
        return sorted(out, key=lambda r: r.get("contradicted_at") or r.get("updated_at") or "",
                      reverse=True)

    def dependencies(self) -> List[Dict[str, Any]]:
        out = [r for r in self._rel.values()
               if r.get("relation_type") in (DEPENDS_ON, HAS_COMPONENT, BELONGS_TO_PROJECT)]
        return sorted(out, key=self._priority, reverse=True)

    def recent_changes(self, limit: int = 15) -> List[Dict[str, Any]]:
        return sorted(self._rel.values(), key=lambda r: r.get("updated_at", ""), reverse=True)[:limit]

    def search(self, query: str, *, limit: int = 12) -> Dict[str, Any]:
        qt = _tokens(query)
        ent_hits = [e for e in self._ent.values()
                    if _tokens(e["canonical_name"]) & qt or any(_tokens(a) & qt for a in e.get("aliases", []))]
        rel_hits = [r for r in self._rel.values()
                    if (_tokens(r["subject"]) | _tokens(r["object"]) | _tokens(r["predicate"])) & qt]
        ent_hits.sort(key=lambda e: e.get("mentions", 0), reverse=True)
        rel_hits.sort(key=self._priority, reverse=True)
        return {"entities": ent_hits[:limit], "relations": rel_hits[:limit]}

    def _priority(self, r: Dict[str, Any]):
        # Cycle 12/13: rank by DECAYED evidence/source weight (committed/canonical/quality up;
        # disputed/candidate-only/vault-objective/stale/decayed down) — disputed & decayed relations
        # stay VISIBLE, just lower influence.
        return (relation_decay(r)["decayed_weight"], r.get("updated_at", ""))

    def weight(self, r: Dict[str, Any]) -> float:
        return relation_weight_score(r)

    def decayed_weight(self, r: Dict[str, Any]) -> float:
        return relation_decay(r)["decayed_weight"]

    def source_class_breakdown(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for r in self._rel.values():
            for sc in r.get("source_classes", []) or ["UNKNOWN"]:
                out[sc] = out.get(sc, 0) + 1
        return out

    def counts(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for r in self._rel.values():
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            by_type[r["relation_type"]] = by_type.get(r["relation_type"], 0) + 1
        return {"entities": len(self._ent), "relations": len(self._rel),
                "by_status": by_status, "by_relation_type": by_type}

    def status(self) -> Dict[str, Any]:
        c = self.counts()
        top_ent = sorted(self._ent.values(), key=lambda e: e.get("mentions", 0), reverse=True)[:10]
        contras = self.contradictions()
        return {
            "is_truth_authority": IS_TRUTH_AUTHORITY,
            "answers_user_directly": ANSWERS_USER_DIRECTLY,
            "total_entities": c["entities"], "total_relations": c["relations"],
            "committed_relations": c["by_status"].get(COMMITTED, 0),
            "disputed_relations": c["by_status"].get(DISPUTED, 0),
            "candidate_relations": c["by_status"].get(CANDIDATE, 0) + c["by_status"].get(REINFORCED, 0),
            "by_relation_type": c["by_relation_type"],
            "top_entities": [{"name": e["canonical_name"], "type": e["entity_type"],
                              "mentions": e["mentions"]} for e in top_ent],
            "top_contradictions": [{"subject": r["subject"], "object": r["object"],
                                    "contradicted_at": r.get("contradicted_at")} for r in contras[:10]],
            "recent_changes": [{"subject": r["subject"], "relation_type": r["relation_type"],
                                "object": r["object"], "status": r["status"],
                                "updated_at": r["updated_at"]} for r in self.recent_changes(10)],
            "source_class_breakdown": self.source_class_breakdown(),
            # Cycle 12: relation-aware self-state metrics
            "central_concepts": self.central_concepts(10),
            "disputed_areas": self.disputed_areas(10),
            # Cycle 13: decay + stability + gaps + contradiction history
            "decay_enabled": _decay_cfg()["enabled"],
            "decayed_relations": self.decayed_relations(limit=10),
            "stable_relations": self.stable_relations(limit=10),
            "weak_central_nodes": self.weak_central_nodes(top_n=10),
            "active_contradictions": [c for c in self.contradiction_history()
                                      if c.get("current_status") not in ("resolved", "superseded")][:10],
        }

    # -- relation metrics + conflict classification (Cycle 12) --------------
    def central_concepts(self, top_n: int = 10) -> List[Dict[str, Any]]:
        deg: Dict[str, int] = {}
        wdeg: Dict[str, float] = {}
        for r in self._rel.values():
            w = relation_weight_score(r)
            for end in (self.resolve(r["subject"]), self.resolve(r["object"])):
                if end:
                    deg[end] = deg.get(end, 0) + 1
                    wdeg[end] = wdeg.get(end, 0.0) + w
        rows = []
        for eid, d in deg.items():
            e = self._ent.get(eid)
            if e:
                rows.append({"name": e["canonical_name"], "type": e["entity_type"], "degree": d,
                             "weighted_centrality": round(wdeg[eid], 3)})
        rows.sort(key=lambda x: (x["weighted_centrality"], x["degree"]), reverse=True)
        return rows[:top_n]

    def disputed_areas(self, top_n: int = 10) -> List[Dict[str, Any]]:
        cnt: Dict[str, int] = {}
        for r in self.contradictions():
            for end in (self.resolve(r["subject"]), self.resolve(r["object"])):
                if end:
                    cnt[end] = cnt.get(end, 0) + 1
        rows = [{"name": self._ent[eid]["canonical_name"], "disputed_relations": c}
                for eid, c in cnt.items() if eid in self._ent]
        rows.sort(key=lambda x: x["disputed_relations"], reverse=True)
        return rows[:top_n]

    def recently_reinforced(self, limit: int = 10) -> List[Dict[str, Any]]:
        rows = [r for r in self._rel.values() if r.get("reinforcement_count", 0) > 0]
        return sorted(rows, key=lambda r: r.get("last_seen", ""), reverse=True)[:limit]

    def candidate_relations(self, limit: int = 25) -> List[Dict[str, Any]]:
        rows = [r for r in self._rel.values() if r.get("status") in (CANDIDATE, REINFORCED)]
        return sorted(rows, key=self._priority, reverse=True)[:limit]

    def decayed_relations(self, *, limit: int = 12, threshold: float = 0.45) -> List[Dict[str, Any]]:
        """Relations whose decay factor has fallen (weakened over time) — auditable, not deleted."""
        rows = []
        for r in self._rel.values():
            d = relation_decay(r)
            if d["decay_factor"] < 0.8 and d["decay_status"] != "disabled":
                rows.append({"subject": r["subject"], "relation_type": r["relation_type"],
                             "object": r["object"], "status": r["status"],
                             "decay_status": d["decay_status"], "decayed_weight": d["decayed_weight"],
                             "decay_reason": d["decay_reason"], "age_days": d["age_days"]})
        rows.sort(key=lambda x: x["decayed_weight"])
        return rows[:limit]

    def stable_relations(self, *, limit: int = 12) -> List[Dict[str, Any]]:
        rows = []
        for r in self._rel.values():
            d = relation_decay(r)
            if d["decay_factor"] >= 0.8 and r.get("status") in (COMMITTED, REINFORCED):
                rows.append({"subject": r["subject"], "relation_type": r["relation_type"],
                             "object": r["object"], "status": r["status"],
                             "decayed_weight": d["decayed_weight"]})
        rows.sort(key=lambda x: x["decayed_weight"], reverse=True)
        return rows[:limit]

    def weak_central_nodes(self, *, top_n: int = 10) -> List[Dict[str, Any]]:
        """Central concepts whose supporting relations are weak/candidate/decayed — need sources."""
        deg: Dict[str, int] = {}
        weak: Dict[str, int] = {}
        for r in self._rel.values():
            d = relation_decay(r)
            is_weak = r.get("status") in (CANDIDATE, DISPUTED) or d["decay_status"] == "stale"
            for end in (self.resolve(r["subject"]), self.resolve(r["object"])):
                if end:
                    deg[end] = deg.get(end, 0) + 1
                    if is_weak:
                        weak[end] = weak.get(end, 0) + 1
        rows = []
        for eid, d in deg.items():
            e = self._ent.get(eid)
            if e and weak.get(eid, 0) > 0 and d >= 2:
                rows.append({"name": e["canonical_name"], "degree": d,
                             "weak_relations": weak.get(eid, 0),
                             "weak_ratio": round(weak.get(eid, 0) / d, 2)})
        rows.sort(key=lambda x: (x["weak_ratio"], x["degree"]), reverse=True)
        return rows[:top_n]

    def relation_metrics(self) -> Dict[str, Any]:
        c = self.counts()
        return {"central_concepts": self.central_concepts(8), "disputed_areas": self.disputed_areas(8),
                "decayed_relations": self.decayed_relations(limit=8),
                "stable_relations": self.stable_relations(limit=8),
                "weak_central_nodes": self.weak_central_nodes(top_n=8),
                "recently_reinforced": [{"subject": r["subject"], "relation_type": r["relation_type"],
                                         "object": r["object"], "reinforcement_count": r.get("reinforcement_count", 0),
                                         "last_seen": r.get("last_seen")} for r in self.recently_reinforced(8)],
                "active_candidate_relations": c["by_status"].get(CANDIDATE, 0) + c["by_status"].get(REINFORCED, 0),
                "committed_relations": c["by_status"].get(COMMITTED, 0),
                "disputed_relations": c["by_status"].get(DISPUTED, 0),
                "source_class_mix": self.source_class_breakdown()}

    def classify_conflict(self, r: Dict[str, Any]) -> str:
        """Classify a disputed relation: canonical_conflict | source_scope_conflict |
        temporal_conflict | direct_contradiction."""
        text = f"{r.get('subject','')} {r.get('predicate','')} {r.get('object','')}"
        try:
            from .source_policy import CANONICAL_CONSTRAINTS
            for c in CANONICAL_CONSTRAINTS:
                if c["topic"].search(text) and c["unsafe"].search(text):
                    return "canonical_conflict"
        except Exception:
            pass
        classes = set(r.get("source_classes", []))
        user = classes & {"EXTRACTED_USER_CLAIM", "USER_MEMORY_GROUNDED", "USER_PREFERENCE"}
        objective = classes & {"SYSTEM_CANONICAL", "VERIFIED_PROJECT_FACT", "DOMAIN_VERIFIED"}
        if user and objective:
            return "source_scope_conflict"                 # user-memory vs objective
        ca, fs = r.get("contradicted_at"), r.get("first_seen")
        if ca and fs:
            try:
                days = (time.mktime(time.strptime(ca, "%Y-%m-%dT%H:%M:%SZ")) -
                        time.mktime(time.strptime(fs, "%Y-%m-%dT%H:%M:%SZ"))) / 86400.0
                if days >= 1.0:
                    return "temporal_conflict"
            except (ValueError, TypeError):
                pass
        return "direct_contradiction"

    # -- contradiction evolution / history (Cycle 13) -----------------------
    _NEXT_ACTION = {"canonical_conflict": "canonical_overrides",
                    "temporal_conflict": "reinforce_current_relation",
                    "source_scope_conflict": "ask_user_for_source",
                    "direct_contradiction": "keep_disputed"}

    def _record_contradiction(self, *, incumbent: Optional[Dict[str, Any]],
                              challenger: Dict[str, Any], source_id: Optional[str]) -> None:
        cid = "contra_" + hashlib.sha1(
            f"{(incumbent or {}).get('relation_id','')}|{challenger.get('relation_id','')}".encode()
        ).hexdigest()[:12]
        conflict_type = self.classify_conflict(challenger if challenger.get("contradiction_count")
                                               else (incumbent or challenger))
        status = "canonical_overrides" if conflict_type == "canonical_conflict" else "active"
        now = _now()
        rec = self._contra.get(cid)
        if rec is None:
            rec = {"contradiction_id": cid, "first_seen": now,
                   "source_that_introduced_conflict": source_id,
                   "incumbent_relation": (incumbent or {}).get("relation_id"),
                   "challenger_relation": challenger.get("relation_id"),
                   "incumbent": f"{(incumbent or {}).get('subject','')} {(incumbent or {}).get('relation_type','')} {(incumbent or {}).get('object','')}".strip(),
                   "challenger": f"{challenger.get('subject','')} {challenger.get('relation_type','')} {challenger.get('object','')}".strip(),
                   "resolution_source": None}
        rec["last_seen"] = now
        rec["conflict_type"] = conflict_type
        rec["current_status"] = rec.get("current_status") if rec.get("current_status") in (
            "resolved", "superseded") else status
        rec["recommended_next_action"] = self._NEXT_ACTION.get(conflict_type, "keep_disputed")
        self._contra[cid] = rec
        self._append(self.contradictions_path, rec)

    def contradiction_history(self) -> List[Dict[str, Any]]:
        return sorted(self._contra.values(), key=lambda c: c.get("last_seen", ""), reverse=True)

    def resolve_contradiction(self, contradiction_id: str, *, resolution_source: str,
                              status: str = "resolved") -> Optional[Dict[str, Any]]:
        rec = self._contra.get(contradiction_id)
        if not rec:
            return None
        rec["current_status"] = status
        rec["resolution_source"] = resolution_source
        rec["last_seen"] = _now()
        self._contra[contradiction_id] = rec
        self._append(self.contradictions_path, rec)
        return rec

    # -- relation-candidate lifecycle (Cycle 11) ----------------------------
    def ingest_candidate_relation(self, rc: Dict[str, Any]) -> Dict[str, Any]:
        """Add one inferred RelationCandidate. A contradiction edge ALSO disputes any existing
        relation between the same two entities (so a negated claim makes the prior relation
        visibly disputed). Inferred relations start as candidates — they never commit on ingest."""
        subj, obj = rc.get("subject", ""), rc.get("object", "")
        if rc.get("is_contradiction") or rc.get("relation_type") == CONTRADICTS:
            r = self.add_relation(subj, rc.get("predicate") or "contradicts", obj,
                                  relation_type=CONTRADICTS, source_id=rc.get("source_id"),
                                  source_class=rc.get("source_class"), is_contradiction=True,
                                  status=DISPUTED, origin="inferred",
                                  evidence_quote=rc.get("evidence_quote"), method=rc.get("method"),
                                  confidence=rc.get("confidence"))
            incumbents = self._dispute_between(subj, obj, rc.get("source_id"))
            self._record_contradiction(incumbent=(incumbents[0] if incumbents else None),
                                       challenger=r, source_id=rc.get("source_id"))
            return r
        return self.add_relation(subj, rc.get("predicate") or "", obj,
                                 relation_type=rc.get("relation_type"), source_id=rc.get("source_id"),
                                 source_class=rc.get("source_class"), origin="inferred",
                                 evidence_quote=rc.get("evidence_quote"), method=rc.get("method"),
                                 confidence=rc.get("confidence"))

    def _dispute_between(self, subject: str, obj: str, source_id: Optional[str]) -> List[Dict[str, Any]]:
        sid, oid = self.resolve(subject), self.resolve(obj)
        disputed = []
        for r in self._rel.values():
            if r.get("relation_type") == CONTRADICTS:
                continue
            ends = {self.resolve(r["subject"]), self.resolve(r["object"])}
            if sid in ends and oid in ends:
                r["contradiction_count"] = r.get("contradiction_count", 0) + 1
                r["contradicted_at"] = _now()
                r["status"] = DISPUTED
                r["updated_at"] = _now()
                self._rel[r["relation_id"]] = r
                self._append(self.edges_path, r)
                disputed.append(r)
        return disputed

    def relation_quality(self, r: Dict[str, Any]) -> float:
        ev = len(set(r.get("source_ids", [])))
        classes = set(r.get("source_classes", []))
        verified = bool(classes & CANONICAL_SOURCE_CLASSES) or "DOMAIN_VERIFIED" in classes
        q = 0.5 + 0.15 * min(ev, 3) + 0.1 * (1 if len(classes) >= 2 else 0)
        q += 0.2 * (1 if verified else 0) - 0.3 * (1 if r.get("contradiction_count", 0) > 0 else 0)
        return round(max(0.0, min(1.0, q)), 3)

    def _policy_allows_commit(self, r: Dict[str, Any]) -> bool:
        from . import relation_policy as rp
        ok, _ = rp.commit_allowed(r.get("relation_type"), r.get("source_classes", []),
                                  subject=r.get("subject"), obj=r.get("object"),
                                  evidence_count=len(set(r.get("source_ids", []))))
        return ok

    def evaluate_relation(self, r: Dict[str, Any], *, commit_quality: float = 0.70,
                          stale_days: int = 30) -> Dict[str, Any]:
        ev = len(set(r.get("source_ids", [])))
        contra = r.get("contradiction_count", 0)
        canonical = r.get("origin") == "canonical_schema" or "SYSTEM_CANONICAL" in r.get("source_classes", [])
        q = self.relation_quality(r)
        try:
            age_days = (time.time() - time.mktime(time.strptime(
                r.get("first_seen", _now()), "%Y-%m-%dT%H:%M:%SZ"))) / 86400.0
        except (ValueError, TypeError):
            age_days = 0.0
        if contra > 0:
            return {"action": DISPUTED, "quality": q, "reason": "active contradiction"}
        # Cycle 12: relation-type source policy decides whether this edge may commit as structure.
        if (canonical or ev >= 2) and q >= commit_quality and self._policy_allows_commit(r):
            return {"action": COMMITTED, "quality": q,
                    "reason": f"{'canonical' if canonical else f'{ev} independent sources'}, quality {q}"}
        if age_days >= stale_days and ev < 2 and q < 0.70:
            return {"action": ARCHIVED, "quality": q, "reason": f"stale ({age_days:.0f}d) and weak"}
        if ev >= 2:
            return {"action": REINFORCED, "quality": q, "reason": "independent evidence"}
        return {"action": CANDIDATE, "quality": q, "reason": "needs more independent evidence"}

    def consolidate(self, *, commit_quality: float = 0.70, stale_days: int = 30) -> List[Dict[str, Any]]:
        """The ONLY path that promotes an inferred candidate relation to committed/disputed/archived.
        Canonical/system relations may commit directly; everything else needs >=2 independent
        sources + quality + no contradiction. Never commits a DISPUTED_OR_UNSAFE relation."""
        decisions = []
        for r in list(self._rel.values()):
            if r.get("status") not in (CANDIDATE, REINFORCED):
                continue
            d = self.evaluate_relation(r, commit_quality=commit_quality, stale_days=stale_days)
            act = d["action"]
            if act != r["status"]:
                r["status"] = act
                r["updated_at"] = _now()
                if act == COMMITTED and not r.get("committed_at"):
                    r["committed_at"] = _now()
                if act == ARCHIVED and not r.get("archived_at"):
                    r["archived_at"] = _now()
                self._rel[r["relation_id"]] = r
                self._append(self.edges_path, r)
            decisions.append({"relation_id": r["relation_id"], **d})
        return decisions

    # -- bounded, DIRECTED multi-hop reasoning (Cycle 12) -------------------
    def multi_hop_path(self, start: str, target: Optional[str] = None, *, max_depth: int = 2,
                       limit: int = 12, include_inverse: bool = False) -> Dict[str, Any]:
        """Bounded DIRECTED traversal (default depth 2). Each stored edge is traversed per its
        directionality: forward edges subject→object only; bidirectional (contradicts) both ways;
        inverse_renderable (broader/narrower_than) forward by default and BACKWARD only when
        include_inverse=True — and such a backward hop is RENDERED, never stored, and flagged
        inverse_rendered. A disputed hop marks the path disputed; an all-committed canonical path
        is ranked first (then by edge weight)."""
        max_depth = max(1, min(int(max_depth or 2), 4))
        start_eid = self.resolve(start)
        tgt_eid = self.resolve(target) if target else None
        if not start_eid or (target and not tgt_eid):
            return {"start": start, "target": target, "max_depth": max_depth,
                    "include_inverse": include_inverse, "paths": []}

        def steps(eid):
            out = []
            for r in self._rel.values():
                s, o = self.resolve(r["subject"]), self.resolve(r["object"])
                d = directionality(r["relation_type"])
                if s == eid:                               # stored direction: subject -> object
                    out.append((r, o, "forward", False))
                if o == eid:                               # reverse of stored direction
                    if d == BIDIRECTIONAL:
                        out.append((r, s, "backward", False))
                    elif d == INVERSE_RENDERABLE and include_inverse:
                        out.append((r, s, "inverse", True))
            return out

        paths: List[List[Dict[str, Any]]] = []
        stack = [(start_eid, [], {start_eid})]
        while stack and len(paths) < limit:
            cur, hops, visited = stack.pop()
            if hops and (tgt_eid is None or cur == tgt_eid):
                paths.append(hops)
                if tgt_eid is not None:
                    continue
            if len(hops) >= max_depth:
                continue
            for r, nxt, direction, inverse in steps(cur):
                if nxt in visited:
                    continue
                stack.append((nxt, hops + [(r, direction, inverse)], visited | {nxt}))

        out = [self._path_obj(h) for h in paths]
        out.sort(key=lambda p: (0 if p["canonical"] else 1, 0 if p["path_status"] != DISPUTED else 1,
                                -p["weight"], len(p["hops"])))
        return {"start": start, "target": target, "max_depth": max_depth,
                "include_inverse": include_inverse, "paths": out[:limit]}

    def _path_obj(self, steps: List[tuple]) -> Dict[str, Any]:
        rels = [r for r, _d, _inv in steps]
        statuses = [r.get("status") for r in rels]
        disputed = any(s == DISPUTED for s in statuses) or any(r.get("contradiction_count", 0) > 0
                                                               for r in rels)
        all_committed = all(s == COMMITTED for s in statuses)
        canonical = all(r.get("origin") == "canonical_schema" or
                        "SYSTEM_CANONICAL" in r.get("source_classes", []) for r in rels)
        path_status = DISPUTED if disputed else (COMMITTED if all_committed else "provisional")
        inverse_rendered = any(inv for _r, _d, inv in steps)
        weight = round(min((relation_weight_score(r) for r in rels), default=0.0), 4)
        hops = []
        for r, direction, inv in steps:
            rtype = r["relation_type"]
            shown_type = _INVERSE_TYPE.get(rtype, rtype) if inv else rtype
            dec = relation_decay(r)
            hops.append({"subject": r["subject"], "relation_type": shown_type,
                         "stored_relation_type": rtype, "object": r["object"], "status": r["status"],
                         "direction": direction, "inverse_rendered": inv,
                         "source_classes": r.get("source_classes", []),
                         "source_ids": r.get("source_ids", [])[:3], "weight": relation_weight_score(r),
                         "decayed_weight": dec["decayed_weight"], "decay_status": dec["decay_status"],
                         "confidence": round(min(0.99, dec["decayed_weight"]), 3),
                         "evidence_quote": r.get("evidence_quote")})
        return {"length": len(hops), "path_status": path_status, "canonical": canonical,
                "weight": weight, "inverse_rendered": inverse_rendered,
                "note": ("contains an inverse-rendered hop (rendered, not stored as truth)"
                         if inverse_rendered else None),
                "source_classes": sorted({sc for r in rels for sc in r.get("source_classes", [])}),
                "hops": hops}


def lifeloop_field(users_root: str | Path) -> RelationField:
    """The system-level relation field lives in the lifeloop namespace, beside the candidate
    lifecycle (same root the consolidator/endpoints use)."""
    from .namespace import UserNamespace
    return RelationField(UserNamespace(str(users_root), "lifeloop").root)


class RelationFieldBuilder:
    """Builds the relation field FROM existing memory — never re-embeds, never creates a parallel
    truth store. Reuses the canonical relation seed, the candidate lifecycle, dispute records,
    vault manifest, LifeLoop task results and session events, attaching provenance + source class
    to every edge and de-duplicating by stable relation id."""

    def __init__(self, field: RelationField, *, mem_client: Optional[Any] = None,
                 lifecycle: Optional[Any] = None, vault_manifest: Optional[Any] = None,
                 lifeloop_dir: str | Path = "runtime/lifeloop",
                 owners: Optional[List[str]] = None) -> None:
        self.f = field
        self.mem = mem_client
        self.lc = lifecycle
        self.vm = vault_manifest
        self.lifeloop_dir = Path(lifeloop_dir)
        self.owners = owners or []                         # vault owners whose chunk CONTENT to mine

    # -- per-source ingestion ----------------------------------------------
    def _seed_canonical(self) -> int:
        """The canonical project relations (same seed self-training stores) — VERIFIED_PROJECT_FACT,
        committed. Deterministic so the field always knows BYON's components/roles."""
        from .self_training import _RELATIONS
        n = 0
        for subj, pred, tgt in _RELATIONS:
            self.f.add_relation(subj, pred, tgt, source_id=f"relation:{subj}->{pred}->{tgt}",
                                source_class="VERIFIED_PROJECT_FACT", status=COMMITTED,
                                origin="canonical_schema",
                                evidence_quote=f"{subj} {pred.replace('_', ' ')} {tgt}")
            n += 1
        return n

    def _from_memory_relations(self) -> int:
        """Parse any 'relation:SUBJ->PRED->OBJ' facts already committed in memory-service."""
        if self.mem is None:
            return 0
        n = 0
        seen = set()
        for q in ("BYON D_Cortex FCE-M architecture components", "Claude role truth authority",
                  "memory-service function relations", "BYON epistemic contract level"):
            try:
                hits = self.mem.search_facts(q, top_k=20, threshold=0.0, thread_id=None, scope="thread")
            except Exception:
                hits = []
            for h in hits:
                src = str((h.get("metadata") or {}).get("source") or h.get("source") or "")
                triple = parse_relation_source(src)
                if triple and src not in seen:
                    seen.add(src)
                    subj, pred, tgt = triple
                    self.f.add_relation(subj, pred, tgt, source_id=src,
                                        source_class="VERIFIED_PROJECT_FACT", status=COMMITTED,
                                        origin="canonical_schema",
                                        evidence_quote=str(h.get("content") or "")[:200])
                    n += 1
        return n

    def infer_from_memory(self, queries: Optional[List[str]] = None, *, cap: int = 80) -> int:
        """Cycle 11: infer relation candidates from stored fact/chunk CONTENT (not filenames). Reuses
        memory-service retrieval — no new vector store, no re-embedding. System scope + each owner's
        vault thread so vault CHUNK CONTENT is mined too. Secret content yields nothing."""
        if self.mem is None:
            return 0
        from . import relation_inference as ri
        from .source_policy import source_class_of
        queries = queries or [
            "depends on requires component contains supports contradicts role function",
            "BYON D_Cortex FCE-M memory-service Claude architecture components",
            "consolidation auditor epistemic contract derived from based on"]
        # owner vault threads FIRST (each with its own budget) so a single planted note is never
        # starved by the thousands of system facts; then the system/self-training scope.
        n, seen = 0, set()
        for owner in self.owners:
            n += self._infer_scope(ri, source_class_of, queries, owner, "thread", seen, cap=40)
        n += self._infer_scope(ri, source_class_of, queries, None, "thread", seen, cap=cap)
        return n

    def _infer_scope(self, ri, source_class_of, queries, owner, scope, seen, *, cap) -> int:
        n = 0
        for q in queries:
            try:                                          # high recall so a single owner vault note
                hits = self.mem.search_facts(q, top_k=200, threshold=0.0, thread_id=owner, scope=scope)
            except Exception:                              # is not drowned by system facts in-thread
                hits = []
            for h in hits:
                content = h.get("content") or ""
                src = str((h.get("metadata") or {}).get("source") or h.get("source") or "")
                key = src or content[:40]
                if not content or key in seen:
                    continue
                seen.add(key)
                sc = source_class_of(h)
                for rc in ri.infer_relations_from_text(content, src or f"fact:{h.get('ctx_id')}",
                                                       sc, {"ctx_id": h.get("ctx_id")}):
                    self.f.ingest_candidate_relation(rc)
                    n += 1
                if n >= cap:
                    return n
        return n

    def ingest_candidate(self, c: Dict[str, Any]) -> int:
        topic = (c.get("topic") or "").strip()
        if not topic:
            return 0
        sc = c.get("source_class")
        self.f.add_entity(topic, entity_type="topic", source_class=sc)
        from . import relation_inference as ri          # mine relations from the claim CONTENT
        for rc in ri.infer_from_candidate(c):
            self.f.ingest_candidate_relation(rc)
        n = 0
        cid = c.get("candidate_id", "")
        if c.get("status") == "committed":
            self.f.add_relation(topic, "consolidation_promoted", (c.get("claim") or topic)[:80],
                                relation_type=CONSOLIDATION_PROMOTED, source_id=f"candidate:{cid}",
                                source_class=sc, status=COMMITTED)
            n += 1
        if c.get("challenger_of"):
            self.f.add_relation(topic, "candidate_challenger_of", str(c.get("challenger_of")),
                                relation_type=CANDIDATE_CHALLENGER_OF, source_id=f"candidate:{cid}",
                                source_class=sc, is_contradiction=True)
            n += 1
        if not n:                                        # a plain candidate is still navigable
            self.f.add_relation(topic, "derived_from", "candidate lifecycle",
                                relation_type=DERIVED_FROM, source_id=f"candidate:{cid}",
                                source_class=sc)
            n += 1
        return n

    def ingest_dispute(self, d: Dict[str, Any]) -> int:
        cid = d.get("candidate_id", "")
        subj = None
        if self.lc is not None:
            inc = self.lc.get(cid) if hasattr(self.lc, "get") else None
            subj = (inc or {}).get("topic")
        subj = subj or (d.get("evidence_a") or "claim")[:60]
        obj = "challenger: " + (d.get("evidence_b") or "")[:80]
        self.f.add_relation(subj, "contradicts", obj, relation_type=CONTRADICTS,
                            source_id=f"dispute:{cid}:{d.get('challenger_id','')}",
                            source_class=d.get("source_class_a"), is_contradiction=True,
                            status=DISPUTED, ts=d.get("ts"))
        return 1

    def ingest_task_result(self, t: Dict[str, Any]) -> int:
        topic = (t.get("topic") or t.get("question") or "").strip()
        if not topic:
            return 0
        self.f.add_relation(topic, "derived_from", "lifeloop task",
                            relation_type=DERIVED_FROM, source_id=f"task:{t.get('task_id','')}",
                            source_class=t.get("source_class"))
        n = 1
        summary = t.get("answer_summary") or ""           # Cycle 11: mine the result CONTENT too
        if summary:
            from . import relation_inference as ri
            for rc in ri.infer_relations_from_text(summary, f"task:{t.get('task_id','')}",
                                                   t.get("source_class"), {"task_id": t.get("task_id")}):
                self.f.ingest_candidate_relation(rc)
                n += 1
        return n

    def _from_vault(self, cap: int = 400) -> int:
        if self.vm is None:
            return 0
        n = 0
        try:
            recs = [r for r in self.vm._by_chunk.values()] if hasattr(self.vm, "_by_chunk") else []
        except Exception:
            recs = []
        for rec in recs:
            if n >= cap:
                break
            if rec.get("status") != "active":
                continue
            rel = rec.get("file_path") or ""
            stem = Path(rel).stem.replace("_", " ").replace("-", " ").strip() or rel
            if not stem:
                continue
            self.f.add_relation(stem, "mentioned_in", "vault", relation_type=MENTIONED_IN,
                                source_id=rec.get("chunk_id"), source_class="EXTRACTED_USER_CLAIM")
            n += 1
        return n

    def _read_jsonl(self, name: str) -> List[Dict[str, Any]]:
        p = self.lifeloop_dir / name
        if not p.exists():
            return []
        out = []
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
        return out

    # -- orchestration ------------------------------------------------------
    def rebuild(self) -> Dict[str, Any]:
        stats = {"canonical_seed": 0, "memory_relations": 0, "candidates": 0, "disputes": 0,
                 "vault": 0, "task_results": 0}
        stats["canonical_seed"] = self._seed_canonical()
        stats["memory_relations"] = self._from_memory_relations()
        if self.lc is not None:
            for c in (self.lc.list() if hasattr(self.lc, "list") else []):
                stats["candidates"] += self.ingest_candidate(c)
            for d in (self.lc.list_disputes() if hasattr(self.lc, "list_disputes") else []):
                stats["disputes"] += self.ingest_dispute(d)
        stats["vault"] = self._from_vault()
        for t in self._read_jsonl("task_results.jsonl"):
            stats["task_results"] += self.ingest_task_result(t)
        stats["inferred"] = self.infer_from_memory()       # Cycle 11: content-based inference
        stats["entities"] = self.f.counts()["entities"]
        stats["relations"] = self.f.counts()["relations"]
        return stats

    def infer_text(self, text: str, *, source: str, source_class: Optional[str],
                   provenance: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Run the grounded extractor on one bounded text and ingest the candidates (never commits).
        Used by the operator/infer endpoint and incremental updates. Secret text yields nothing."""
        from . import relation_inference as ri
        cands = ri.infer_relations_from_text(text, source, source_class, provenance or {})
        for rc in cands:
            self.f.ingest_candidate_relation(rc)
        return cands

    def incremental_update(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a single source event without a full rebuild. Dedup by stable relation id means a
        repeated event never creates a duplicate relation (it reinforces / no-ops)."""
        etype = (event or {}).get("type")
        before = self.f.counts()["relations"]
        if etype == "candidate":
            self.ingest_candidate(event.get("candidate") or event)
        elif etype == "dispute":
            self.ingest_dispute(event.get("dispute") or event)
        elif etype == "task_result":
            self.ingest_task_result(event.get("task") or event)
        elif etype == "relation_fact":
            triple = parse_relation_source(event.get("source", ""))
            if triple:
                self.f.add_relation(*triple, source_id=event.get("source"),
                                    source_class=event.get("source_class", "VERIFIED_PROJECT_FACT"),
                                    status=COMMITTED)
        elif etype == "relation":
            self.f.add_relation(event["subject"], event["predicate"], event["object"],
                                relation_type=event.get("relation_type"),
                                source_id=event.get("source_id"),
                                source_class=event.get("source_class"),
                                is_contradiction=bool(event.get("is_contradiction")))
        elif etype == "text":
            self.infer_text(event.get("text", ""), source=event.get("source", "text"),
                            source_class=event.get("source_class"),
                            provenance=event.get("provenance"))
        after = self.f.counts()["relations"]
        return {"type": etype, "relations_before": before, "relations_after": after,
                "new_relation": after > before}


# -- Relation proposals back to the candidate lifecycle (Cycle 11) ----------
PROPOSAL_MISSING = "missing_candidate"
PROPOSAL_CONTRADICTION = "contradiction"
PROPOSAL_DEPENDENCY = "dependency"
PROPOSAL_CONSOLIDATION = "consolidation"


def make_proposal(field: "RelationField", r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Turn a relation into a RelationProposal for the candidate lifecycle. The relation field can
    PROPOSE (missing fact / contradiction / dependency / consolidation) but never commit."""
    rid = r["relation_id"]
    canonical = r.get("origin") == "canonical_schema" or "SYSTEM_CANONICAL" in r.get("source_classes", [])
    base = {"proposal_id": "prop_" + rid[4:], "relation_id": rid,
            "evidence": r.get("evidence_quote") or "", "source_class": (r.get("source_classes") or [None])[0]}
    if r.get("status") == DISPUTED or r.get("contradiction_count", 0) > 0:
        return {**base, "proposal_type": PROPOSAL_CONTRADICTION,
                "suggested_claim": f"{r['subject']} {r['relation_type']} {r['object']} (contested)",
                "status": DISPUTED}
    if r.get("status") == REINFORCED and r.get("relation_type") in (DEPENDS_ON, HAS_COMPONENT):
        return {**base, "proposal_type": PROPOSAL_DEPENDENCY,
                "suggested_claim": f"{r['subject']} {r['relation_type']} {r['object']}",
                "status": CANDIDATE}
    if r.get("status") == REINFORCED:
        return {**base, "proposal_type": PROPOSAL_CONSOLIDATION,
                "suggested_claim": f"{r['subject']} {r['relation_type']} {r['object']}",
                "status": CANDIDATE}
    return None


class RelationProposer:
    """Scans the relation field and proposes candidates BACK to the candidate lifecycle. Suggestions
    become candidates (never committed by the field); a canonical-conflict proposal is marked
    disputed. The field cannot commit and cannot override source policy."""

    def __init__(self, field: "RelationField", *, lifecycle: Optional[Any] = None,
                 proposals_path: Optional[str | Path] = None) -> None:
        self.f = field
        self.lc = lifecycle
        self.path = Path(proposals_path) if proposals_path else (field.dir / "relation_proposals.jsonl")

    def run(self, *, cap: int = 25) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in list(self.f._rel.values()):
            if len(out) >= cap:
                break
            p = make_proposal(self.f, r)
            if not p:
                continue
            if self.lc is not None:                        # propose -> CANDIDATE (never committed here)
                try:
                    epi = "DISPUTED" if p["status"] == DISPUTED else "PROVISIONAL"
                    self.lc.ingest_task_result(
                        task_id="relprop_" + r["relation_id"][4:], topic=r["subject"],
                        claim=p["suggested_claim"], sources_used=r.get("source_ids", [])[:3],
                        epistemic_status=epi, source_class=p["source_class"],
                        source_event_ids=[r["relation_id"]])
                    p["routed_to_candidate_lifecycle"] = True
                except Exception:
                    p["routed_to_candidate_lifecycle"] = False
            self._write(p)
            out.append(p)
        return out

    def _write(self, p: Dict[str, Any]) -> None:
        try:
            self.f.dir.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def list(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]
        except (OSError, json.JSONDecodeError):
            return []


# -- relation-gap task generation (Cycle 13) --------------------------------
_SECRET_RX = re.compile(r"(?i)\b(password|parol[ăa]|secret|api[ _-]?key|token|pin|iban|cnp|"
                        r"credit\s*card|cont\s+bancar)\b")
_OBJECTIVE_GAP_TYPES = {HAS_COMPONENT, DEPENDS_ON, ROLE_OF, CAUSED_BY, DERIVED_FROM}


class RelationGapScanner:
    """LifeLoop-side: turn weak / disputed / vault-only-objective / decayed-central relation GAPS
    into controlled internal research tasks. Memory-only tasks may run automatically; web tasks need
    permission; secret-derived gaps produce no task; task results become candidates, never truth.
    The relation field PROPOSES — it never commits."""

    def __init__(self, field: "RelationField", *, tasks: Optional[Any] = None) -> None:
        self.f = field
        self.tasks = tasks

    def _file(self, *, gap_type: str, subject: str, obj: str, question: str, allowed, rid: str):
        if _SECRET_RX.search(f"{subject} {obj}"):
            return {"gap_type": gap_type, "relation_id": rid, "task_id": None, "skipped": "secret"}
        task_id = None
        if self.tasks is not None:
            try:
                t = self.tasks.create(topic=f"relgap:{rid}", question=question,
                                      allowed_sources=allowed, trigger_event_ids=[rid])
                task_id = (t or {}).get("task_id")
            except Exception:
                task_id = None
        return {"gap_type": gap_type, "relation_id": rid, "subject": subject, "object": obj,
                "task_id": task_id, "allowed_sources": allowed,
                "requires_permission": "web" in allowed}

    def scan(self, *, cap: int = 20) -> List[Dict[str, Any]]:
        from . import relation_policy as rp
        out: List[Dict[str, Any]] = []
        weak_central = {r["name"] for r in self.f.weak_central_nodes(top_n=8)}
        for r in list(self.f._rel.values()):
            if len(out) >= cap:
                break
            rid, subj, obj = r["relation_id"], r["subject"], r["object"]
            status, rtype = r.get("status"), r.get("relation_type")
            classes = r.get("source_classes", [])
            ev = len(set(r.get("source_ids", [])))
            d = relation_decay(r)
            gap = None
            if status == DISPUTED:
                gap = self._file(gap_type="resolve_dispute", subject=subj, obj=obj, rid=rid,
                                 question=f"resolve dispute: {subj} {rtype} {obj}",
                                 allowed=["memory", "vault", "self_state"])
            elif rtype in _OBJECTIVE_GAP_TYPES and rp.is_vault_only(classes):
                # objective relation blocked because source is vault-only → seek a verified source
                gap = self._file(gap_type="verify_with_project_source", subject=subj, obj=obj, rid=rid,
                                 question=f"find a verified/project source for: {subj} {rtype} {obj}",
                                 allowed=["memory", "vault", "self_state"])
            elif "PROVISIONAL_WEB" in classes and ev < 2:
                gap = self._file(gap_type="request_web_permission", subject=subj, obj=obj, rid=rid,
                                 question=f"verify with independent web sources: {subj} {rtype} {obj}",
                                 allowed=["memory", "web"])
            elif status == CANDIDATE and ev < 2:
                gap = self._file(gap_type="find_internal_evidence", subject=subj, obj=obj, rid=rid,
                                 question=f"find internal evidence for: {subj} {rtype} {obj}",
                                 allowed=["memory", "vault", "self_state"])
            elif d["decay_status"] == "stale" and (subj in weak_central or obj in weak_central):
                gap = self._file(gap_type="inspect_relation_gap", subject=subj, obj=obj, rid=rid,
                                 question=f"central but decayed relation needs review: {subj} {rtype} {obj}",
                                 allowed=["memory", "vault", "self_state"])
            if gap:
                out.append(gap)
        return out

    def scan_path_gap(self, start: str, target: str) -> Optional[Dict[str, Any]]:
        """A failed path query (no directed path within depth) creates a missing-relation task."""
        if not self.f.multi_hop_path(start, target, max_depth=2)["paths"]:
            return self._file(gap_type="inspect_relation_gap", subject=start, obj=target,
                              rid=_rid(start, "missing_path", target),
                              question=f"missing relation between {start} and {target}",
                              allowed=["memory", "vault", "self_state"])
        return None
