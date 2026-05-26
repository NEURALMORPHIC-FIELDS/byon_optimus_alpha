"""Tests for the run_byon launcher and the real LocalBYONBackend.

No live Claude, no live external BYON. The LocalBYONBackend is exercised directly
(it is real, in-repo) and the launcher's mode logic is exercised without launching a UI.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")

run_byon = importlib.import_module("run_byon")
lb = importlib.import_module("gateway.local_backend")
brc = importlib.import_module("app.byon_runtime_client")
hc = importlib.import_module("app.health_checks")


def test_run_byon_exists_and_has_main():
    assert hasattr(run_byon, "main")


def test_connect_mode_fails_cleanly_when_gateway_unreachable(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_byon.py", "--connect"])
    monkeypatch.setenv("BYON_GATEWAY_URL", "http://127.0.0.1:59997")
    rc = run_byon.main()
    assert rc == 2  # exits cleanly, does not launch UI


def test_real_mode_fcem_missing_fails_with_clear_message(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["run_byon.py", "--no-prompt"])
    import app.runtime_discovery as rdmod

    class _D:
        repo_root = Path(".").resolve()
        fcem_root = None
        memory_service_server = None
        problems = ["Real FCE-M engine not found. Provide FCEM_MEMORY_ENGINE_ROOT or run setup."]
    monkeypatch.setattr(rdmod, "discover", lambda: _D())
    rc = run_byon.main()
    out = capsys.readouterr().out
    assert rc == 2
    assert "FCE-M" in out and "FCEM_MEMORY_ENGINE_ROOT" in out
    assert "shim" in out.lower()


def test_local_backend_grounded_known(tmp_path):
    backend = lb.LocalBYONBackend()
    r = backend.chat(user_id="u", session_id="s", channel="web",
                     message="What operational level is BYON allowed to claim?",
                     namespace_dir=tmp_path)
    assert r.epistemic_status == "KNOWN" and r.grounded is True
    assert "level 2" in r.answer.lower() and "level 3" in r.answer.lower()
    assert r.final_audit_passed is True and r.sources


def test_local_backend_unknown_when_ungrounded(tmp_path):
    backend = lb.LocalBYONBackend()
    r = backend.chat(user_id="u", session_id="s", channel="web",
                     message="What is my private bank password?", namespace_dir=tmp_path)
    assert r.epistemic_status == "UNKNOWN" and r.grounded is False and r.answer == ""


def test_local_backend_teach_then_recall_and_isolation(tmp_path):
    backend = lb.LocalBYONBackend()
    a = tmp_path / "userA"
    b = tmp_path / "userB"
    backend.chat(user_id="A", session_id="s", channel="web",
                 message="remember that my project codename is orion", namespace_dir=a)
    rec = backend.chat(user_id="A", session_id="s", channel="web",
                       message="what is my project codename?", namespace_dir=a)
    assert rec.epistemic_status == "KNOWN" and "orion" in rec.answer.lower()
    # user B has a separate namespace → must not see A's fact
    iso = backend.chat(user_id="B", session_id="s", channel="web",
                       message="what is my project codename?", namespace_dir=b)
    assert iso.epistemic_status == "UNKNOWN" and iso.grounded is False


def test_local_backend_never_calls_claude_without_grounding(tmp_path, monkeypatch):
    # Even with a key set, an ungrounded query must NOT call Claude and must be UNKNOWN.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    backend = lb.LocalBYONBackend(use_claude=True)
    called = {"claude": False}
    monkeypatch.setattr(backend, "_phrase_with_claude",
                        lambda *a, **k: called.__setitem__("claude", True) or "leak")
    r = backend.chat(user_id="u", session_id="s", channel="web",
                     message="who secretly won an unrecorded match?", namespace_dir=tmp_path)
    assert r.epistemic_status == "UNKNOWN" and called["claude"] is False


def test_ui_client_preserves_unknown_and_refused():
    class _Resp:
        def __init__(self, payload): self._p = payload; self.status_code = 200
        def raise_for_status(self): pass
        def json(self): return self._p

    class _HTTP:
        def __init__(self, payload): self._p = payload
        def request(self, *a, **k): return _Resp(self._p)

    unk = brc.BYONRuntimeClient("http://t", http_client=_HTTP(
        {"epistemic_status": "UNKNOWN", "grounded": False, "final_audit_passed": True,
         "answer": "", "audit_trace_id": "t"})).chat("u", "s", "x")
    assert unk.epistemic_status == "UNKNOWN" and unk.answer == ""
    ref = brc.BYONRuntimeClient("http://t", http_client=_HTTP(
        {"epistemic_status": "REFUSED", "grounded": False, "final_audit_passed": True,
         "answer": "no", "audit_trace_id": "t"})).chat("u", "s", "x")
    assert ref.epistemic_status == "REFUSED" and ref.grounded is False


def test_no_direct_claude_or_memory_service_in_ui_layer():
    ui_src = (Path(__file__).resolve().parents[1] / "app" / "alpha_ui.py").read_text(encoding="utf-8")
    cli_src = (Path(__file__).resolve().parents[1] / "app" / "byon_runtime_client.py").read_text(encoding="utf-8")
    assert "anthropic" not in ui_src.lower() and "anthropic" not in cli_src.lower()
    # UI client talks only to the gateway /v1 surface
    assert "/v1/chat" in cli_src and "8000" not in cli_src


def test_health_summary_fail_when_unreachable():
    s = hc.summarize("http://127.0.0.1:59996")
    assert s["Gateway"] == "FAIL"
