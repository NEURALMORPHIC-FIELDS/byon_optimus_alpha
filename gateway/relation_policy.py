# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Relation-type source policy (Cycle 12).

Per-relation-type commit/source rules so a relation cannot misuse a source class:
  * an architecture `has_component` / `role_of` about a core component (BYON, D_Cortex, FCE-M,
    Claude, memory-service, Auditor) requires a SYSTEM_CANONICAL / VERIFIED_PROJECT_FACT source;
  * an objective relation (depends_on, caused_by, derived_from, broader/narrower_than, refines)
    requires a verified source (SYSTEM_CANONICAL / VERIFIED_PROJECT_FACT / DOMAIN_VERIFIED);
  * `user_prefers` may commit from USER_PREFERENCE; `mentioned_in` from user/vault memory;
  * `supports` / `contradicts` stay candidate/disputed until an evidence threshold (≥2) or canonical;
  * a vault-only objective relation can NEVER become objective truth - it stays user-memory-grounded.

This is the relation analogue of source_policy for facts. It NEVER overrides source_policy or the
Auditor; it only decides whether an inferred relation may be promoted, and as which trust tier.
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from gateway import relation_field as rf

CANONICAL_CLASSES = {"SYSTEM_CANONICAL", "VERIFIED_PROJECT_FACT"}
VERIFIED_CLASSES = {"SYSTEM_CANONICAL", "VERIFIED_PROJECT_FACT", "DOMAIN_VERIFIED"}
USER_CLASSES = {"USER_PREFERENCE", "USER_MEMORY_GROUNDED", "EXTRACTED_USER_CLAIM"}

# relations that assert OBJECTIVE structure (not personal memory)
OBJECTIVE_TYPES = {rf.HAS_COMPONENT, rf.DEPENDS_ON, rf.ROLE_OF, rf.CAUSED_BY, rf.DERIVED_FROM,
                   rf.BROADER_THAN, rf.NARROWER_THAN, rf.REFINES, rf.BELONGS_TO_PROJECT}
ARCHITECTURE_TYPES = {rf.HAS_COMPONENT, rf.ROLE_OF}
ARCHITECTURE_ENTITIES = {"byon", "d_cortex", "d-cortex", "dcortex", "fce-m", "fcem", "fce-m v15.7a",
                         "claude", "memory-service", "memory service", "faiss", "auditor",
                         "faiss semantic memory-service"}


def _classes(source_classes: Iterable[str]) -> set:
    return {c for c in (source_classes or []) if c}


def _is_arch_entity(name: Optional[str]) -> bool:
    return (name or "").strip().lower() in ARCHITECTURE_ENTITIES


def is_vault_only(source_classes: Iterable[str]) -> bool:
    cs = _classes(source_classes)
    return bool(cs) and cs <= USER_CLASSES


def commit_allowed(relation_type: str, source_classes: Iterable[str], *,
                   subject: Optional[str] = None, obj: Optional[str] = None,
                   evidence_count: int = 1) -> Tuple[bool, str]:
    """May a relation of this type, sourced from these classes, COMMIT as objective structure?"""
    cs = _classes(source_classes)
    if "DISPUTED_OR_UNSAFE" in cs:
        return False, "disputed/unsafe source can never commit a relation"
    canonical = bool(cs & CANONICAL_CLASSES)
    verified = bool(cs & VERIFIED_CLASSES)

    if relation_type in ARCHITECTURE_TYPES and (_is_arch_entity(subject) or _is_arch_entity(obj)):
        return canonical, "architecture relation requires SYSTEM_CANONICAL / VERIFIED_PROJECT_FACT"
    if relation_type == rf.USER_PREFERS:
        return ("USER_PREFERENCE" in cs or verified), "user preference commits from USER_PREFERENCE"
    if relation_type == rf.MENTIONED_IN:
        return (bool(cs & USER_CLASSES) or verified), "mentioned_in may commit from user/vault memory"
    if relation_type in OBJECTIVE_TYPES:
        return verified, "objective relation requires a verified source (not vault-only)"
    if relation_type in (rf.SUPPORTS, rf.CONTRADICTS):
        return (evidence_count >= 2 or canonical), "supports/contradicts need >=2 evidence or canonical"
    return verified, "default: requires a verified source"


def commit_trust_for(relation_type: str, source_classes: Iterable[str]) -> str:
    """The trust tier a committed relation carries. A user/vault relation commits AS user memory,
    never as objective truth, even when allowed to commit (e.g. user_prefers / mentioned_in)."""
    cs = _classes(source_classes)
    if cs & {"SYSTEM_CANONICAL"}:
        return "SYSTEM_CANONICAL"
    if cs & {"VERIFIED_PROJECT_FACT"}:
        return "VERIFIED_PROJECT_FACT"
    if "DOMAIN_VERIFIED" in cs:
        return "DOMAIN_VERIFIED"
    if cs & USER_CLASSES:
        return "USER_MEMORY_GROUNDED"           # user/vault relation = user memory, not objective
    return "UNKNOWN"


def context_allowed(relation_type: str, source_classes: Iterable[str], *,
                    subject: Optional[str] = None) -> bool:
    """May a relation be used as CONTEXT in a normal (non-relation) answer as objective structure?
    A vault-only objective relation may be shown but only framed as user memory (handled by the
    renderer); here we block presenting it as objective architecture context."""
    if relation_type in OBJECTIVE_TYPES and is_vault_only(source_classes):
        return False
    return "DISPUTED_OR_UNSAFE" not in _classes(source_classes)
