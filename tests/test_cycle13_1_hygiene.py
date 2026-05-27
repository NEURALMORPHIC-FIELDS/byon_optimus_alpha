# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Cycle 13.1 - release hygiene: ownership attribution, integration verification, .claude project
memory, em-dash style contract, and the FCE-M runtime dependency doc. No cognitive behavior here."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(modpath: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, modpath)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


VI = _load(ROOT / "verify_integration.py", "verify_integration")
CS = _load(ROOT / "scripts" / "check_style_contract.py", "check_style_contract")
EMDASH = chr(0x2014)


# ============================================================ 1. ownership
def test_all_py_files_have_copyright_header():
    rep = CS.check_repo(ROOT)
    missing = [v for v in rep["violations"] if v["kind"] == "missing_copyright_header"]
    assert missing == [], f"py files missing copyright header: {missing}"


def test_citation_mentions_borbeleac():
    t = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "Borbeleac" in t and "FRAGMERGENT" in t


def test_notice_mentions_fragmergent():
    t = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "FRAGMERGENT TECHNOLOGY S.R.L." in t and "Borbeleac" in t


def test_readme_has_ownership_section():
    t = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Ownership and attribution" in t and "Borbeleac" in t and "FRAGMERGENT" in t


# ============================================================ 2. verify_integration
def test_verify_integration_detects_wired_critical_modules():
    rep = VI.run(ROOT)
    assert rep["unwired_critical"] == [] and rep["missing_critical"] == []
    assert all(s == "WIRED" for s in rep["critical_modules"].values())


def _mini_tree(tmp_path):
    (tmp_path / "gateway").mkdir()
    (tmp_path / "gateway" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "gateway" / "app.py").write_text("from . import wired\n", encoding="utf-8")
    (tmp_path / "gateway" / "wired.py").write_text("X = 1\n", encoding="utf-8")
    return tmp_path


def test_verify_integration_flags_unwired_dummy_module(tmp_path):
    _mini_tree(tmp_path)
    (tmp_path / "gateway" / "dummy_unwired.py").write_text("Y = 2\n", encoding="utf-8")
    rep = VI.run(tmp_path, critical=["gateway.app"])
    assert "gateway.dummy_unwired" in rep["not_wired_modules"]
    assert rep["critical_modules"]["gateway.app"] == "WIRED"


def test_verify_integration_flags_local_backend_real_mode(tmp_path):
    _mini_tree(tmp_path)
    (tmp_path / "gateway" / "bad_backend.py").write_text(
        "# REAL mode wiring\nbackend = LocalBYONBackend()\n", encoding="utf-8")
    vs = VI.scan_violations(tmp_path)
    assert any(v["kind"] == "local_backend_real_mode" for v in vs)


def test_verify_integration_flags_truth_authority_violation(tmp_path):
    _mini_tree(tmp_path)
    (tmp_path / "gateway" / "bad_rel.py").write_text("IS_TRUTH_AUTHORITY = True\n", encoding="utf-8")
    vs = VI.scan_violations(tmp_path)
    assert any(v["kind"] == "relation_truth_authority" for v in vs)


def test_verify_integration_outputs_json_and_md(tmp_path):
    rep = VI.run(ROOT)
    jp, mp = VI.write_reports(rep, tmp_path)
    assert jp.exists() and mp.exists()
    assert "Integration report" in mp.read_text(encoding="utf-8")
    assert isinstance(json.loads(jp.read_text(encoding="utf-8"))["critical_modules"], dict)


# ============================================================ 3. .claude project memory
def test_claude_project_files_exist():
    for n in ("project_concept.json", "project_structure.json", "project_log.json"):
        p = ROOT / ".claude" / n
        assert p.exists(), f"missing {n}"
        json.loads(p.read_text(encoding="utf-8"))          # valid JSON


def test_project_concept_preserves_level3_not_declared():
    c = json.loads((ROOT / ".claude" / "project_concept.json").read_text(encoding="utf-8"))
    assert c["FULL_LEVEL3_NOT_DECLARED"] is True
    assert "not Level 3 (FULL_LEVEL3_NOT_DECLARED)" in c["what_byon_is_not"]
    assert "NOT a truth authority" in c["truth_authority_rules"]["claude_role"] or \
        "not a truth authority" in c["truth_authority_rules"]["claude_role"].lower()


def test_project_structure_lists_critical_modules():
    s = json.loads((ROOT / ".claude" / "project_structure.json").read_text(encoding="utf-8"))
    canon = s["canonical_modules"]
    for m in ("gateway/app.py", "gateway/epistemic_search.py", "gateway/source_policy.py",
              "gateway/relation_field.py", "gateway/relation_policy.py"):
        assert m in canon


def test_project_log_mentions_cycle13():
    lg = json.loads((ROOT / ".claude" / "project_log.json").read_text(encoding="utf-8"))
    cycles = {str(c["cycle"]) for c in lg["cycles"]}
    assert "13" in cycles and "13.1" in cycles
    assert "14" in lg["next_cycle"]


# ============================================================ 4. style contract
def test_style_contract_flags_em_dash(tmp_path):
    f = tmp_path / "dirty.py"
    f.write_text("# Copyright (c) 2024-2026 Vasile Lucian Borbeleac\nx = 1  " + EMDASH + " note\n",
                 encoding="utf-8")
    vs = CS.check_file(f)
    assert any(v["kind"] == "em_dash" for v in vs)


def test_style_contract_passes_clean_file(tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.\n"
                 "# Licensed under Apache-2.0.\n\"\"\"A clean module.\"\"\"\nx = 1\n", encoding="utf-8")
    assert CS.check_file(f) == []


def test_style_contract_repo_clean():
    assert CS.check_repo(ROOT)["ok"], CS.check_repo(ROOT)["violations"][:10]


# ============================================================ 5. runtime dependencies doc
def test_runtime_dependencies_doc_exists():
    assert (ROOT / "docs" / "RUNTIME_DEPENDENCIES.md").exists()


def test_runtime_dependencies_mentions_fcem_root():
    t = (ROOT / "docs" / "RUNTIME_DEPENDENCIES.md").read_text(encoding="utf-8")
    assert "FCEM_MEMORY_ENGINE_ROOT" in t and "v15.7a" in t


def test_runtime_dependencies_mentions_fail_hard():
    t = (ROOT / "docs" / "RUNTIME_DEPENDENCIES.md").read_text(encoding="utf-8").lower()
    assert "fail hard" in t and "no diluted fallback" in t
