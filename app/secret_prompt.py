"""Secure secret handling for the launcher.

Prompts for ANTHROPIC_API_KEY with getpass (never echoed). Prints only a masked prefix.
Does not write the key to disk unless the user explicitly passes --save-key, in which case
it is written to .env.local (gitignored) with a warning.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Optional


def mask(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return "(none)"
    return key[:10] + "…" if len(key) > 10 else "sk-ant-…"


def ensure_api_key(*, interactive: bool = True, save: bool = False) -> Optional[str]:
    """Return the ANTHROPIC_API_KEY, prompting if missing (Claude is optional; an empty
    answer means 'continue without Claude language enrichment')."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    if not interactive:
        return None
    try:
        entered = getpass.getpass(
            "ANTHROPIC_API_KEY (optional — press Enter to run without Claude language): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not entered:
        return None
    os.environ["ANTHROPIC_API_KEY"] = entered
    print(f"  key accepted ({mask(entered)}); kept in process env only.")
    if save:
        save_key_to_env_local(entered)
    return entered


def save_key_to_env_local(key: str, path: str = ".env.local") -> Path:
    p = Path(path)
    lines = []
    if p.exists():
        lines = [l for l in p.read_text(encoding="utf-8").splitlines()
                 if not l.startswith("ANTHROPIC_API_KEY=")]
    lines.append(f"ANTHROPIC_API_KEY={key}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  WARNING: API key written to {p} (gitignored). Delete it to stop persisting.")
    return p
