# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
#!/usr/bin/env python
"""Project style-contract checker (Cycle 13.1, release hygiene).

Flags, across the owned source + docs (sealed/external/vendored trees excluded):
  * em-dash characters (project style uses commas / colon / parentheses / ASCII hyphen);
  * missing copyright header on owned Python files;
  * a raw, NON-negated "Level 3" claim in prose (a positive assertion that the system IS Level 3);
  * a missing FULL_LEVEL3_NOT_DECLARED marker at repo level.

The em-dash and Level-3 strings are built from char codes so this checker contains neither a literal
em-dash nor a raw Level-3 claim, and it never scans itself or verify_integration.py.

Exit 0 when clean; 1 when any violation is found.

Cycle 13.2 (A5): the em-dash + copyright-header scan now ALSO covers the sealed / adapter trees
dcortex/, orchestration/, integrations/ (no type-hint requirement is imposed on those trees; only
the header presence and em-dash absence are enforced there). The owned source dirs continue to be
scanned exactly as before, and the positive-Level-3-claim and FULL_LEVEL3_NOT_DECLARED-marker checks
remain repo-wide. Any em-dash, any missing header, any positive Level-3 claim, or a missing marker
still causes a non-zero exit.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

EMDASH = chr(0x2014)
HEADER_MARK = "Copyright (c) 2024-2026 Vasile Lucian Borbeleac"
LEVEL3_MARKER = "FULL_LEVEL3_NOT_DECLARED"

SOURCE_DIRS = ["gateway", "app", "byon_mcp", "scripts"]
# Cycle 13.2 (A5): sealed / adapter trees - em-dash + header enforced, no type-hint demand.
WIDE_DIRS = ["dcortex", "orchestration", "integrations"]
ROOT_PY = ["run_byon.py", "run_alpha_app.py"]
DOC_GLOBS = ["*.md", "docs/*.md"]
TOOLING = {"scripts/check_style_contract.py", "scripts\\check_style_contract.py",
           "verify_integration.py"}
EXCLUDE = {".venv", ".venv_gpu", "external", "node_modules", "__pycache__", "runtime", "dcortex",
           ".git", "tests"}
# like EXCLUDE but keeps the sealed/adapter trees in scope (they are the point of the widened scan).
WIDE_EXCLUDE = {".venv", ".venv_gpu", "external", "node_modules", "__pycache__", "runtime",
                ".git", "tests"}

# a positive "is Level 3" claim (prose), with negation handled by the caller per line
_RAW_L3 = re.compile(r"(?i)\b(is|are|am|achieved|reached|declares?)\s+level\s*3\b")
# negation OR safety/example context (a quoted "is Level 3" inside a rejection/constraint sentence
# is the forbidden PATTERN being guarded against, not a claim that the system is Level 3).
_NEG = re.compile(r"(?i)(\b(not|never|nu|no|n't|reject|without|denies?|forbidden|disputed|unsafe|"
                  r"constraint|canonical|contradict|vs|auditor|approve)\b|bypass|e\.g|"
                  + re.escape(LEVEL3_MARKER) + r")")


def _owned_py(root: Path) -> List[Path]:
    out = []
    for d in SOURCE_DIRS:
        p = root / d
        if p.is_dir():
            out += [f for f in p.rglob("*.py") if not any(x in EXCLUDE for x in f.parts)]
    for f in ROOT_PY:
        if (root / f).exists():
            out.append(root / f)
    return sorted(set(out))


def _widened_py(root: Path) -> List[Path]:
    """Sealed / adapter Python files (dcortex, orchestration, integrations) for em-dash + header."""
    out = []
    for d in WIDE_DIRS:
        p = root / d
        if p.is_dir():
            out += [f for f in p.rglob("*.py") if not any(x in WIDE_EXCLUDE for x in f.parts)]
    return sorted(set(out))


def _owned_docs(root: Path) -> List[Path]:
    out = []
    for g in DOC_GLOBS:
        out += [f for f in root.glob(g) if not any(x in EXCLUDE for x in f.parts)]
    return sorted(set(out))


def check_file(path: Path) -> List[Dict[str, Any]]:
    """Check a single file. Python files require the header; all files are em-dash/Level-3 checked."""
    rel = path.name
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return _check_text(text, rel, is_py=path.suffix == ".py")


def _check_text(text: str, name: str, *, is_py: bool) -> List[Dict[str, Any]]:
    v: List[Dict[str, Any]] = []
    if EMDASH in text:
        v.append({"kind": "em_dash", "file": name, "count": text.count(EMDASH)})
    if is_py and HEADER_MARK not in text:
        v.append({"kind": "missing_copyright_header", "file": name})
    for i, line in enumerate(text.splitlines(), 1):
        if _RAW_L3.search(line) and not _NEG.search(line):
            v.append({"kind": "raw_level3_claim", "file": name, "line": i, "text": line.strip()[:120]})
    return v


def check_repo(root: Path) -> Dict[str, Any]:
    violations: List[Dict[str, Any]] = []
    for f in _owned_py(root):
        if str(f.relative_to(root)).replace("\\", "/") in {t.replace("\\", "/") for t in TOOLING}:
            continue
        violations += _add_rel(check_file(f), f, root)
    for f in _widened_py(root):  # sealed/adapter trees: em-dash + header (+ Level-3) only
        violations += _add_rel(check_file(f), f, root)
    for f in _owned_docs(root):
        # docs are not Python: em-dash + raw-claim only (no header requirement)
        text = f.read_text(encoding="utf-8", errors="ignore")
        violations += _add_rel(_check_text(text, f.name, is_py=False), f, root)
    # repo-level marker presence (README or NOTICE must carry it)
    marker_present = any(LEVEL3_MARKER in (root / n).read_text(encoding="utf-8", errors="ignore")
                         for n in ("README.md", "NOTICE") if (root / n).exists())
    if not marker_present:
        violations.append({"kind": "missing_level3_marker", "file": "(repo)",
                           "detail": f"{LEVEL3_MARKER} not found in README.md / NOTICE"})
    return {"ok": not violations, "violation_count": len(violations), "violations": violations,
            "level3_marker_present": marker_present}


def _add_rel(vs: List[Dict[str, Any]], path: Path, root: Path) -> List[Dict[str, Any]]:
    rel = str(path.relative_to(root))
    for x in vs:
        x["file"] = rel
    return vs


def main(argv: Optional[Any]=None) -> Any:
    root = Path(__file__).resolve().parents[1]
    rep = check_repo(root)
    if rep["ok"]:
        print(f"[check_style_contract] PASS - no style violations; {LEVEL3_MARKER} marker present.")
        return 0
    print(f"[check_style_contract] FAIL - {rep['violation_count']} violation(s):")
    for v in rep["violations"][:50]:
        print(f"  - {v['kind']} in {v.get('file')}" + (f":{v['line']}" if v.get("line") else ""))
    return 1


if __name__ == "__main__":
    sys.exit(main())
