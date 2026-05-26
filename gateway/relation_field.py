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
        self._ent: Dict[str, Dict[str, Any]] = {}
        self._rel: Dict[str, Dict[str, Any]] = {}
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
        if any(sc in CANONICAL_SOURCE_CLASSES for sc in rel.get("source_classes", [])):
            return COMMITTED
        return REINFORCED if rel.get("evidence_count", 0) >= 2 else CANDIDATE

    def add_relation(self, subject: str, predicate: str, obj: str, *,
                     relation_type: Optional[str] = None, source_id: Optional[str] = None,
                     source_class: Optional[str] = None, status: Optional[str] = None,
                     is_contradiction: bool = False, ts: Optional[str] = None) -> Dict[str, Any]:
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
                 # temporal tracking
                 "first_seen": now, "last_seen": now, "reinforcement_count": 0,
                 "contradicted_at": None, "committed_at": None, "archived_at": None,
                 "source_history": []}
            action = "created"
        else:
            action = "reinforced" if (source_id not in r.get("source_ids", [])) else "seen"
        if source_id and source_id not in r["source_ids"]:
            r["source_ids"].append(source_id)
            r["evidence_count"] = r.get("evidence_count", 0) + 1
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
        committed = 1 if r.get("status") == COMMITTED else 0
        rank = max((_SRC_RANK.get(sc, 1) for sc in r.get("source_classes", [])), default=1)
        return (committed, rank, r.get("evidence_count", 0), r.get("updated_at", ""))

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
        }


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
                 lifeloop_dir: str | Path = "runtime/lifeloop") -> None:
        self.f = field
        self.mem = mem_client
        self.lc = lifecycle
        self.vm = vault_manifest
        self.lifeloop_dir = Path(lifeloop_dir)

    # -- per-source ingestion ----------------------------------------------
    def _seed_canonical(self) -> int:
        """The canonical project relations (same seed self-training stores) — VERIFIED_PROJECT_FACT,
        committed. Deterministic so the field always knows BYON's components/roles."""
        from .self_training import _RELATIONS
        n = 0
        for subj, pred, tgt in _RELATIONS:
            self.f.add_relation(subj, pred, tgt, source_id=f"relation:{subj}->{pred}->{tgt}",
                                source_class="VERIFIED_PROJECT_FACT", status=COMMITTED)
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
                                        source_class="VERIFIED_PROJECT_FACT", status=COMMITTED)
                    n += 1
        return n

    def ingest_candidate(self, c: Dict[str, Any]) -> int:
        topic = (c.get("topic") or "").strip()
        if not topic:
            return 0
        sc = c.get("source_class")
        self.f.add_entity(topic, entity_type="topic", source_class=sc)
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
        return 1

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
        stats["entities"] = self.f.counts()["entities"]
        stats["relations"] = self.f.counts()["relations"]
        return stats

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
        after = self.f.counts()["relations"]
        return {"type": etype, "relations_before": before, "relations_after": after,
                "new_relation": after > before}
