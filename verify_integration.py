# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
#!/usr/bin/env python
"""Integration verifier (Cycle 13.1, release hygiene).

Static, dependency-free audit of the repository's wiring and safety boundary. It parses every
project Python file, builds the internal import graph (including lazy imports inside functions),
classifies each module (WIRED / NOT_WIRED / DUPLICATE / EXTERNAL / TEST_ONLY), marks the critical
modules, and scans for boundary VIOLATIONS:

  * memory-service bypass (raw faiss import outside the sealed engine);
  * Auditor bypass (final-audit requirement disabled at the source);
  * LocalBYONBackend used in REAL mode without a mode guard;
  * relation field acting as a truth authority (IS_TRUTH_AUTHORITY = True);
  * LifeLoop answering the user directly (answers_user_directly = True);
  * duplicate canonical modules;
  * dead (NOT_WIRED) critical modules;
  * raw FAISS / D_Cortex / FCE-M endpoint exposure on the public Gateway surface.

Outputs runtime/integration_report.{json,md}. Exit code: 0 = all critical WIRED and no critical
violation; 1 = a critical module is NOT_WIRED or an unsafe bypass was found; 2 = parsing / import
graph failed.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# directories that hold project Python we own/verify; sealed/external/vendored trees are excluded.
SCAN_DIRS = ["gateway", "app", "byon_mcp", "scripts"]
ROOT_FILES = ["run_byon.py", "verify_integration.py"]
EXCLUDE_DIRS = {".venv", ".venv_gpu", "external", "node_modules", "__pycache__", "runtime",
                "dcortex", ".git", "tests"}

CRITICAL_MODULES = [
    "run_byon", "gateway.app", "gateway.epistemic_search", "gateway.source_policy",
    "gateway.memory_service_backend", "gateway.lifeloop", "gateway.candidate_lifecycle",
    "gateway.relation_field", "gateway.relation_policy", "gateway.relation_inference",
    "gateway.relation_reports", "gateway.vault_training", "gateway.tombstones",
    "gateway.consistent_client", "scripts.live_byon_eval",
]

# status
WIRED, NOT_WIRED, DUPLICATE, EXTERNAL, TEST_ONLY = "WIRED", "NOT_WIRED", "DUPLICATE", "EXTERNAL", "TEST_ONLY"


def _module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join(parts) if parts else rel.parts[0]


def _iter_py(root: Path) -> List[Path]:
    out = []
    for d in SCAN_DIRS:
        p = root / d
        if p.is_dir():
            out += [f for f in p.rglob("*.py")
                    if not any(part in EXCLUDE_DIRS for part in f.parts)]
    for f in ROOT_FILES:
        if (root / f).exists():
            out.append(root / f)
    return sorted(set(out))


def _imports(tree: ast.AST, pkg: str) -> Set[str]:
    """All internal modules imported anywhere in the tree (top-level AND lazy/in-function)."""
    found: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:                # relative import
                base = pkg
                mod = (base + "." + node.module) if node.module else base
                found.add(mod)
                for a in node.names:                         # `from . import X` -> pkg.X
                    found.add(mod + "." + a.name)
            elif node.module:
                found.add(node.module)
                for a in node.names:
                    found.add(node.module + "." + a.name)
    return found


def build_graph(root: Path) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Set[str]]]:
    """Returns (modules, edges). Raises on a parse failure (caller maps to exit 2)."""
    files = _iter_py(root)
    modules: Dict[str, Dict[str, Any]] = {}
    name_by_file: Dict[Path, str] = {}
    import hashlib
    for f in files:
        name = _module_name(f, root)
        name_by_file[f] = name
        body = f.read_text(encoding="utf-8", errors="ignore")
        # content hash ignores the (identical) copyright header so true copies still match
        core = "\n".join(ln for ln in body.splitlines()
                         if not ln.startswith("# Copyright (c) 2024-2026") and ln.strip() != "# Licensed under Apache-2.0.")
        modules[name] = {"name": name, "path": str(f.relative_to(root)), "raw_imports": set(),
                         "sha": hashlib.sha1(core.strip().encode("utf-8")).hexdigest()}
    known = set(modules)
    edges: Dict[str, Set[str]] = {m: set() for m in modules}
    for f in files:
        name = name_by_file[f]
        pkg = name.rsplit(".", 1)[0] if "." in name else ""
        # package of a file under gateway/ is "gateway" even for gateway/app.py
        pkg = f.relative_to(root).parts[0] if len(f.relative_to(root).parts) > 1 else ""
        tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"), filename=str(f))
        raw = _imports(tree, pkg)
        modules[name]["raw_imports"] = sorted(raw)
        for imp in raw:
            # resolve to a known internal module: exact, or parent (drop trailing symbol)
            target = imp if imp in known else (imp.rsplit(".", 1)[0] if imp.rsplit(".", 1)[0] in known else None)
            if target and target != name:
                edges[name].add(target)
    return modules, edges


def _reachable(roots: Set[str], edges: Dict[str, Set[str]]) -> Set[str]:
    seen, stack = set(), [r for r in roots if r in edges]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(edges.get(cur, ()))
    return seen


def classify(modules: Dict[str, Dict[str, Any]], edges: Dict[str, Set[str]],
             *, roots: Optional[Set[str]] = None) -> Dict[str, str]:
    # entrypoints: root .py files, every script, the gateway app factory
    auto_roots = {m for m in modules if "." not in m}                 # run_byon, verify_integration
    auto_roots |= {m for m in modules if m.startswith("scripts.")}
    auto_roots |= {m for m in modules if m == "gateway.app"}
    auto_roots |= {m for m in modules if m.endswith(".__init__")}
    roots = (roots or set()) | auto_roots
    reach = _reachable(roots, edges)
    # DUPLICATE = a true content copy of another module (byte-identical core), not merely a shared
    # basename across packages (gateway.server vs byon_mcp.server are legitimately distinct).
    by_sha: Dict[str, List[str]] = {}
    for m, info in modules.items():
        if not m.endswith(".__init__") and info.get("sha"):
            by_sha.setdefault(info["sha"], []).append(m)
    dups = {m for ms in by_sha.values() if len(ms) > 1 for m in ms}
    out: Dict[str, str] = {}
    for m in modules:
        if m in dups:
            out[m] = DUPLICATE
        elif m in reach:
            out[m] = WIRED
        else:
            out[m] = NOT_WIRED
    return out


# ---- boundary violation scanners (conservative: only flag CLEAR signals) ----
def scan_violations(root: Path) -> List[Dict[str, Any]]:
    # the audit tooling itself legitimately CONTAINS the forbidden patterns (as detection strings),
    # so it is never scanned for violations.
    TOOLING = {"verify_integration.py", "scripts/check_style_contract.py",
               "scripts\\check_style_contract.py"}
    violations: List[Dict[str, Any]] = []
    for f in _iter_py(root):
        rel = str(f.relative_to(root))
        if rel in TOOLING:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        low = text.lower()
        # relation field / report claiming truth authority
        if "is_truth_authority = true" in low or '"is_truth_authority": true' in low:
            violations.append({"kind": "relation_truth_authority", "module": rel, "critical": True,
                               "detail": "relation field/report sets is_truth_authority True"})
        # LifeLoop answering the user directly
        if "answers_user_directly = true" in low or '"answers_user_directly": true' in low:
            violations.append({"kind": "lifeloop_answers_directly", "module": rel, "critical": True,
                               "detail": "LifeLoop sets answers_user_directly True"})
        # LocalBYONBackend constructed in REAL without a mode guard in the same file
        if "localbyonbackend(" in low and "real" in low and \
                "byon_backend_mode" not in low and "backend_mode" not in low and "demo" not in low:
            violations.append({"kind": "local_backend_real_mode", "module": rel, "critical": True,
                               "detail": "LocalBYONBackend constructed in REAL context without a mode guard"})
        # memory-service bypass: raw faiss import outside the sealed engine
        if ("import faiss" in low or "from faiss" in low) and "dcortex" not in rel and "external" not in rel:
            violations.append({"kind": "memory_service_bypass", "module": rel, "critical": True,
                               "detail": "raw faiss import outside the sealed memory-service"})
        # Auditor bypass: final-audit requirement disabled at the source
        if "require_final_audit = false" in low or "require_final_audit: false" in low:
            violations.append({"kind": "auditor_bypass", "module": rel, "critical": True,
                               "detail": "final-audit requirement disabled in source"})
        # raw FAISS / D_Cortex / FCE-M endpoint exposure on the public surface
        if "@app." in text:
            for bad in ('"/v1/faiss', "'/v1/faiss", '"/faiss', '"/v1/fcem', '"/v1/dcortex',
                        '"/v1/memory/raw'):
                if bad in text:
                    violations.append({"kind": "raw_engine_endpoint", "module": rel, "critical": True,
                                       "detail": f"raw engine endpoint exposed: {bad}"})
    return violations


def run(root: Path, *, roots: Optional[Set[str]] = None,
        critical: Optional[List[str]] = None) -> Dict[str, Any]:
    critical = critical if critical is not None else CRITICAL_MODULES
    modules, edges = build_graph(root)
    status = classify(modules, edges, roots=roots)
    violations = scan_violations(root)
    present_critical = [c for c in critical if c in modules]
    unwired_critical = [c for c in present_critical if status.get(c) != WIRED]
    missing_critical = [c for c in critical if c not in modules]
    critical_violations = [v for v in violations if v.get("critical")]
    ok = not unwired_critical and not critical_violations and not missing_critical
    return {
        "ok": ok,
        "module_count": len(modules),
        "status_counts": {s: sum(1 for v in status.values() if v == s)
                          for s in (WIRED, NOT_WIRED, DUPLICATE, TEST_ONLY)},
        "critical_modules": {c: status.get(c, "MISSING") for c in critical},
        "unwired_critical": unwired_critical,
        "missing_critical": missing_critical,
        "violations": violations,
        "critical_violations": critical_violations,
        "not_wired_modules": sorted(m for m, s in status.items() if s == NOT_WIRED),
        "duplicate_modules": sorted(m for m, s in status.items() if s == DUPLICATE),
        "modules": {m: {"status": status[m], "path": modules[m]["path"]} for m in sorted(modules)},
    }


def _render_md(rep: Dict[str, Any]) -> str:
    lines = ["# Integration report", "",
             f"- result: **{'PASS' if rep['ok'] else 'FAIL'}**",
             f"- modules scanned: {rep['module_count']}",
             f"- status counts: {rep['status_counts']}",
             f"- critical violations: {len(rep['critical_violations'])}", "",
             "## Critical modules", ""]
    for m, s in rep["critical_modules"].items():
        mark = "OK" if s == WIRED else "PROBLEM"
        lines.append(f"- [{mark}] `{m}`: {s}")
    lines += ["", "## Violations", ""]
    if not rep["violations"]:
        lines.append("- none")
    for v in rep["violations"]:
        lines.append(f"- {'CRITICAL ' if v.get('critical') else ''}{v['kind']} in `{v['module']}`: {v['detail']}")
    if rep["not_wired_modules"]:
        lines += ["", "## Not-wired (dead) modules", ""] + [f"- `{m}`" for m in rep["not_wired_modules"]]
    return "\n".join(lines) + "\n"


def write_reports(rep: Dict[str, Any], outdir: Path) -> Tuple[Path, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    jp, mp = outdir / "integration_report.json", outdir / "integration_report.md"
    jp.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    mp.write_text(_render_md(rep), encoding="utf-8")
    return jp, mp


def main(argv: Optional[List[str]] = None) -> int:
    root = Path(__file__).resolve().parent
    try:
        rep = run(root)
    except SyntaxError as exc:
        print(f"[verify_integration] PARSE FAILURE: {exc}")
        return 2
    jp, mp = write_reports(rep, root / "runtime")
    print(f"[verify_integration] {'PASS' if rep['ok'] else 'FAIL'} - "
          f"{rep['module_count']} modules, {len(rep['critical_violations'])} critical violations, "
          f"unwired critical: {rep['unwired_critical'] or 'none'} -> {jp}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
