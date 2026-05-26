"""Auth context (alpha scope).

In alpha, access is by a small allowlist of private user_ids and an optional shared
bearer token. The point of this module is not strong auth yet — it is to make
`user_id` a first-class, mandatory, isolating identity. Production would swap this
for real per-user credentials without changing the Gateway contract.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Set


@dataclass
class AuthContext:
    user_id: str
    authenticated: bool
    reason: str = ""


def _allowlist() -> Optional[Set[str]]:
    raw = os.environ.get("BYON_ALPHA_USER_ALLOWLIST", "").strip()
    if not raw:
        return None  # no allowlist configured → any non-empty user_id is accepted (alpha)
    return {u.strip() for u in raw.split(",") if u.strip()}


def authenticate(user_id: str, auth_token: Optional[str]) -> AuthContext:
    if not user_id or not str(user_id).strip():
        return AuthContext(user_id="", authenticated=False, reason="missing user_id")
    expected = os.environ.get("BYON_ALPHA_SHARED_TOKEN", "").strip()
    if expected and (auth_token or "").strip() != expected:
        return AuthContext(user_id=user_id, authenticated=False, reason="bad auth_token")
    allow = _allowlist()
    if allow is not None and user_id not in allow:
        return AuthContext(user_id=user_id, authenticated=False, reason="user not in alpha allowlist")
    return AuthContext(user_id=user_id, authenticated=True)
