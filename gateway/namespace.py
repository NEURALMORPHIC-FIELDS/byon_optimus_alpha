"""Per-user memory namespace.

Every user gets an isolated directory tree. user_id is sanitised so it can never
escape the users root (no path traversal), and one user's namespace can never
resolve into another's. There is no shared/global namespace by default — that is
the cross-user isolation guarantee the v10 milestone proved at the cortex level,
carried up to the connector layer.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import List

_SUBDIRS = ("faiss", "dcortex", "fcem", "conversations", "audit", "feedback")
_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


class NamespaceIsolationError(RuntimeError):
    """Raised when an access would cross a user-namespace boundary."""


def sanitize_user_id(user_id: str) -> str:
    """Map an arbitrary user_id to a filesystem-safe, collision-resistant slug.

    A short hash suffix keeps two different raw ids from colliding after
    sanitisation (e.g. 'a/b' and 'a.b')."""
    raw = str(user_id).strip()
    if not raw:
        raise ValueError("user_id must be non-empty")
    slug = _SAFE.sub("_", raw).strip("._-") or "user"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"{slug[:40]}-{digest}"


class UserNamespace:
    def __init__(self, users_root: str | Path, user_id: str) -> None:
        self.users_root = Path(users_root).resolve()
        self.user_id = user_id
        self.slug = sanitize_user_id(user_id)
        self.root = (self.users_root / self.slug).resolve()
        # Defence in depth: the resolved root MUST stay under users_root.
        if self.users_root not in self.root.parents and self.root != self.users_root / self.slug:
            raise NamespaceIsolationError(
                f"resolved namespace {self.root} escapes users root {self.users_root}")

    def ensure(self) -> "UserNamespace":
        for sub in _SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        return self

    def path(self, *parts: str) -> Path:
        """Resolve a path inside this user's namespace, refusing any traversal
        that would land outside it."""
        p = (self.root / Path(*parts)).resolve()
        if p != self.root and self.root not in p.parents:
            raise NamespaceIsolationError(
                f"path {p} escapes user namespace {self.root}")
        return p

    def subdirs(self) -> List[str]:
        return list(_SUBDIRS)


def assert_no_cross_access(owner: UserNamespace, other: UserNamespace) -> None:
    """Hard check used by tests and the isolation audit: two distinct users must
    have disjoint namespace roots and neither may resolve into the other's."""
    if owner.slug == other.slug:
        return
    if owner.root == other.root:
        raise NamespaceIsolationError("distinct users share a namespace root")
    if owner.root in other.root.parents or other.root in owner.root.parents:
        raise NamespaceIsolationError("one user namespace nests inside another")
