# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Locate the BYON runtime pieces the launcher needs.

Searches env vars and known repo locations. Returns what was found and a list of
human-readable problems (with the exact env var / path to set) when something is missing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass
class Discovery:
    repo_root: Path
    gateway_module: str = "gateway.server"          # always in-repo
    memory_service_server: Optional[Path] = None
    orchestrator_dir: Optional[Path] = None
    fcem_root: Optional[str] = None
    problems: List[str] = field(default_factory=list)


def _first_existing(paths: List[Path]) -> Optional[Path]:
    for p in paths:
        if p.exists():
            return p
    return None


def discover() -> Discovery:
    root = repo_root()
    d = Discovery(repo_root=root)

    # memory-service server.py (external official orchestrator checkout)
    env_ms = os.environ.get("BYON_MEMORY_SERVICE_ROOT", "").strip()
    d.memory_service_server = _first_existing([
        *( [Path(env_ms) / "server.py"] if env_ms else [] ),
        root / "external/byon_optimus/byon-orchestrator/memory-service/server.py",
        root / "byon-orchestrator/memory-service/server.py",
        root / "memory-service/server.py",
    ])

    # orchestrator dir (optional; the local backend does not require it)
    env_orch = os.environ.get("BYON_ORCHESTRATOR_ROOT", "").strip()
    d.orchestrator_dir = _first_existing([
        *( [Path(env_orch)] if env_orch else [] ),
        root / "external/byon_optimus/byon-orchestrator",
        root / "byon-orchestrator",
    ])

    # real FCE-M v15.7a engine
    try:
        from dcortex.v10_milestone import resolve_fcem_engine_root
        d.fcem_root = resolve_fcem_engine_root() or None
    except Exception:
        d.fcem_root = os.environ.get("FCEM_MEMORY_ENGINE_ROOT", "").strip() or None

    if not d.fcem_root:
        d.problems.append(
            "Real FCE-M engine not found. Provide FCEM_MEMORY_ENGINE_ROOT "
            "(path to the v15.7a 'd_cortex' package) or run setup.")
    return d
