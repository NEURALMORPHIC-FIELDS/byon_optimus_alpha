# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Bridge to the CANONICAL BYON FactExtractor (Node, LLM-driven).

Learning from interaction goes through the real `fact-extractor.mjs` (extract → classify
trust → store via memory-service), invoked through `scripts/byon_fact_extract.mjs`. The old
Python `_parse_teach` heuristic is NOT the canonical authority - it is only an emergency
fallback and anything it stores is tagged `non_canonical_fallback`.

`available()` is true only when Node + the canonical extractor + an API key are all present.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

_REPO = Path(__file__).resolve().parents[1]
_WRAPPER = _REPO / "scripts" / "byon_fact_extract.mjs"
_CANONICAL_EXTRACTOR = (_REPO / "external/byon_optimus/byon-orchestrator/scripts/lib/fact-extractor.mjs")


def node_bin() -> Optional[str]:
    return shutil.which("node")


def available() -> bool:
    return bool(node_bin()) and _WRAPPER.exists() and _CANONICAL_EXTRACTOR.exists() \
        and bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def extract_and_store(text: str, *, thread_id: str, channel: str = "web",
                      memory_url: str = "http://127.0.0.1:8000",
                      role: str = "user", timeout_s: float = 45.0) -> Dict[str, Any]:
    """Run the canonical FactExtractor on a user message. Returns the wrapper's JSON
    ({ok, canonical, facts, ctx_ids, trust_report, trust_tiers}) or a non-canonical marker."""
    nb = node_bin()
    if not nb or not _WRAPPER.exists() or not _CANONICAL_EXTRACTOR.exists():
        return {"ok": False, "canonical": False, "reason": "node/extractor unavailable"}
    env = dict(os.environ)
    env["BYON_MEMORY_SERVICE_URL"] = memory_url
    payload = json.dumps({"text": text, "role": role, "threadId": thread_id, "channel": channel})
    try:
        proc = subprocess.run([nb, str(_WRAPPER)], input=payload, env=env, cwd=str(_REPO),
                              text=True, capture_output=True, timeout=timeout_s)
    except Exception as exc:
        return {"ok": False, "canonical": False, "reason": f"node invocation failed: {exc}"}
    out = (proc.stdout or "").strip().splitlines()
    for line in reversed(out):  # last JSON line is the result
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"ok": False, "canonical": False, "reason": (proc.stderr or "no output")[:300]}
