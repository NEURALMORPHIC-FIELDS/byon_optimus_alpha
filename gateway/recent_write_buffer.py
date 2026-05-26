"""Recent-write buffer (Cycle 4, target 6).

A fact stored in the memory-service takes ~8–11s to become searchable in FAISS. Rather than
fake immediate retrieval, BYON keeps a small per-user buffer of just-written facts so they can be
recalled right away — but the answer is honestly marked as coming from the RECENT_WRITE_BUFFER
(not yet stable indexed FAISS). An entry expires after a TTL or once FAISS confirms it is
searchable, after which the normal memory-service source is used.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "is", "are", "what", "my", "me", "of", "to", "in", "on", "and",
         "ce", "este", "e", "mea", "meu", "mele", "care", "ai", "am", "in", "la", "un", "o"}


def _tokens(text: str) -> set:
    return {t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP and len(t) > 1}


class RecentWriteBuffer:
    def __init__(self, ttl_seconds: float = 90.0, max_per_user: int = 50) -> None:
        self.ttl = ttl_seconds
        self.max_per_user = max_per_user
        self._by_user: Dict[str, List[Dict[str, Any]]] = {}

    def _prune(self, user_id: Optional[str] = None) -> None:
        now = time.time()
        users = [user_id] if user_id else list(self._by_user.keys())
        for u in users:
            entries = self._by_user.get(u)
            if entries is None:
                continue
            kept = [e for e in entries if now - e["ts"] <= self.ttl]
            if kept:
                self._by_user[u] = kept[-self.max_per_user:]
            else:
                self._by_user.pop(u, None)

    def add(self, user_id: str, content: str, *, source_id: Optional[str] = None,
            ctx_id: Any = None) -> None:
        if not user_id or not (content or "").strip():
            return
        self._prune(user_id)
        self._by_user.setdefault(user_id, []).append({
            "content": content.strip(), "source_id": source_id, "ctx_id": ctx_id,
            "ts": time.time(), "tokens": _tokens(content)})

    def recall(self, user_id: str, query: str, *, min_overlap: int = 1) -> List[Dict[str, Any]]:
        """Buffered writes for this user relevant to the query (most recent first). Honest:
        these are pending FAISS indexing, not stable retrieval."""
        self._prune(user_id)
        q = _tokens(query)
        if not q:
            return []
        out = []
        for e in reversed(self._by_user.get(user_id, [])):
            if len(q & e["tokens"]) >= min_overlap:
                out.append({"content": e["content"], "source_id": e["source_id"],
                            "ctx_id": e["ctx_id"], "age_s": round(time.time() - e["ts"], 1)})
        return out

    def confirm_indexed(self, user_id: str, content: str, *, overlap: float = 0.6) -> None:
        """Drop a buffered entry once FAISS has it — matched by token overlap (the stored fact may
        be re-phrased, e.g. 'my favorite editor is vim' → 'user favorite editor is vim')."""
        entries = self._by_user.get(user_id)
        if not entries:
            return
        faiss_tok = _tokens(content)
        if not faiss_tok:
            return
        kept = []
        for e in entries:
            et = e["tokens"]
            ratio = (len(et & faiss_tok) / len(et)) if et else 0.0
            if ratio < overlap:
                kept.append(e)
        if kept:
            self._by_user[user_id] = kept
        else:
            self._by_user.pop(user_id, None)

    def count(self) -> int:
        self._prune()
        return sum(len(v) for v in self._by_user.values())

    def count_for(self, user_id: str) -> int:
        self._prune(user_id)
        return len(self._by_user.get(user_id, []))

    def clear(self) -> None:
        self._by_user.clear()
