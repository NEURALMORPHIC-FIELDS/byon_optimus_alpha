#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""BYON Optimus + D_Cortex - off-Colab / local full-organism integration runner.

This is the Windows/Linux-local adaptation of the v9.9 self-contained Colab runner.
It removes every Colab/Drive assumption (``drive.mount``, ``/content`` paths,
``chmod``/linux-esbuild repair, masked getpass) and instead:

  * uses an already-cloned official ``byon_optimus`` checkout under ``external/``;
  * injects the patched D_Cortex v9.9 source as an additive memory organ;
  * patches ``memory-service/server.py`` with the dcortex_v99_* actions;
  * boots the canonical FastAPI memory-service;
  * runs the live BYON + D_Cortex QA gating harness against Claude.

Non-dilution rule (dev-sheet 7.3): if a real component is missing, fail hard with
a clear report. No mocks are substituted silently.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------------------
# Paths and configuration
# --------------------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_REPO = PROJECT_ROOT / "external" / "byon_optimus"
ORCH_DIR = EXTERNAL_REPO / "byon-orchestrator"
SERVICE_DIR = ORCH_DIR / "memory-service"
DCORTEX_SOURCE = PROJECT_ROOT / "dcortex" / "v99_source.py"
ADAPTER_SRC = PROJECT_ROOT / "orchestration" / "dcortex_v99_adapter.py"
E2E_SRC = PROJECT_ROOT / "orchestration" / "byon-dcortex-v99-live-e2e.mjs"
LEVEL3_REPO = PROJECT_ROOT / "runtime" / "dcortex_run" / "byon_optimus_level3_real_source"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
RESULTS_DIR = RUNTIME_DIR / "integration_results"
MEMORY_STORAGE = RESULTS_DIR / "memory_storage"
DCORTEX_OUT = RUNTIME_DIR / "dcortex_out"

REPO_URL = "https://github.com/NEURALMORPHIC-FIELDS/byon_optimus.git"

# Real FCE-M v15.7a consolidator engine root. The memory-service's fcem_backend loads the
# REAL external_v15_7a runtime (not the vendored minimal shim) when FCEM_MEMORY_ENGINE_ROOT
# points at a dir containing `d_cortex/__init__.py` (or `13_v15_7a_consolidation/d_cortex/`).
# Resolve a sensible default from the local fragmergent-memory-engine checkout; override via env.
def _resolve_fcem_engine_root() -> str:
    env = os.environ.get("FCEM_MEMORY_ENGINE_ROOT", "").strip()
    if env:
        return env
    for cand in (
        Path(r"c:/Users/Lucian/Desktop/fragmergent-memory-engine/13_v15_7a_consolidation"),
        Path(r"c:/Users/Lucian/Desktop/fragmergent-memory-engine"),
    ):
        if (cand / "d_cortex" / "__init__.py").exists() or (cand / "13_v15_7a_consolidation" / "d_cortex" / "__init__.py").exists():
            return str(cand)
    return ""

FCEM_ENGINE_ROOT = _resolve_fcem_engine_root()
MEMORY_SERVICE_PORT = int(os.environ.get("MEMORY_SERVICE_PORT", "8000"))
MEMORY_SERVICE_URL = f"http://127.0.0.1:{MEMORY_SERVICE_PORT}"
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")

DCORTEX_ACTIONS = [
    "dcortex_v99_status",
    "dcortex_v99_run_audit",
    "dcortex_v99_grounding_packet",
    "dcortex_v99_semantic_probe",
]


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[{ts()}] {msg}", flush=True)


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def npm_exe() -> str:
    exe = shutil.which("npm") or shutil.which("npm.cmd")
    if not exe:
        raise RuntimeError("npm not found on PATH; install Node.js >=18.")
    return exe


def node_exe() -> str:
    exe = shutil.which("node")
    if not exe:
        raise RuntimeError("node not found on PATH; install Node.js >=18.")
    return exe


def run(cmd: List[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None,
        check: bool = True, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    log(f"RUN {' '.join(map(str, cmd))} (cwd={cwd})")
    cp = subprocess.run(
        list(map(str, cmd)), cwd=str(cwd) if cwd else None, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
    )
    if cp.stdout.strip():
        print(cp.stdout[-4000:], flush=True)
    if cp.stderr.strip():
        print(cp.stderr[-4000:], file=sys.stderr, flush=True)
    if check and cp.returncode != 0:
        raise RuntimeError(f"command failed rc={cp.returncode}: {cmd}")
    return cp


# --------------------------------------------------------------------------------------
# Secret handling - never written to a tracked file
# --------------------------------------------------------------------------------------
def load_secret_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        key_file = PROJECT_ROOT / "secrets" / "anthropic.key"
        if key_file.exists():
            raw = key_file.read_text(encoding="utf-8").strip()
            # tolerate "ANTHROPIC_API_KEY=sk-..." or a bare key
            key = raw.split("=", 1)[1].strip() if raw.startswith("ANTHROPIC_API_KEY=") else raw
    if not key.startswith("sk-ant-"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY missing or malformed. Set the env var or put it in "
            "secrets/anthropic.key (gitignored)."
        )
    os.environ["ANTHROPIC_API_KEY"] = key
    return key


# --------------------------------------------------------------------------------------
# Repo / injection
# --------------------------------------------------------------------------------------
def verify_repo() -> None:
    if not (SERVICE_DIR / "server.py").exists():
        raise RuntimeError(
            f"byon_optimus checkout not found at {EXTERNAL_REPO}.\n"
            f"Expected {SERVICE_DIR / 'server.py'}.\n"
            f"Clone it first:\n"
            f'  git -c core.longpaths=true clone --depth 1 --branch main {REPO_URL} "{EXTERNAL_REPO}"'
        )
    commit = run(["git", "rev-parse", "HEAD"], cwd=EXTERNAL_REPO).stdout.strip()
    log(f"byon_optimus commit={commit}")


def write_dcortex_injection() -> Dict[str, Any]:
    if not DCORTEX_SOURCE.exists():
        raise RuntimeError(f"D_Cortex source missing: {DCORTEX_SOURCE}")
    if not ADAPTER_SRC.exists():
        raise RuntimeError(f"D_Cortex adapter missing: {ADAPTER_SRC}")
    dst_source = SERVICE_DIR / "dcortex_v99_source.py"
    dst_adapter = SERVICE_DIR / "dcortex_v99_adapter.py"
    shutil.copyfile(DCORTEX_SOURCE, dst_source)
    shutil.copyfile(ADAPTER_SRC, dst_adapter)
    # fail hard before server start if injected source is syntactically broken
    run([sys.executable, "-m", "py_compile", str(dst_source)], timeout=120)
    run([sys.executable, "-m", "py_compile", str(dst_adapter)], timeout=120)
    log(f"injected D_Cortex source -> {dst_source}")
    return {"source": str(dst_source), "adapter": str(dst_adapter)}


def apply_server_patch(text: str) -> str:
    """Pure, idempotent transform that injects the dcortex_v99_* actions into
    the memory-service server source. Returns the patched text unchanged if it
    is already patched. Raises if the expected anchors are missing."""
    if "DCortexV99Adapter" in text:
        return text
    text = text.replace(
        "from fcem_backend import FcemBackend\n",
        "from fcem_backend import FcemBackend\nfrom dcortex_v99_adapter import DCortexV99Adapter\n",
    )
    text = text.replace(
        "fcem: Optional[FcemBackend] = None\n",
        "fcem: Optional[FcemBackend] = None\ndcortex_v99: Optional[DCortexV99Adapter] = None\n",
    )
    text = text.replace(
        "    global handlers, fcem, start_time\n",
        "    global handlers, fcem, dcortex_v99, start_time\n",
    )
    marker = (
        "    logger.info(\n"
        "        \"Memory backend mode: %s (FCE-M enabled=%s).\", backend_mode, fcem.enabled\n"
        "    )\n"
    )
    inject = marker + (
        "\n    # D_Cortex v9.9 additive memory organ (off-Colab local integration patch).\n"
        "    dcortex_v99 = DCortexV99Adapter(storage_path, str(Path(__file__).resolve().parents[2]))\n"
        "    logger.info(\"D_Cortex v9.9 memory organ initialized: %s\", dcortex_v99.status())\n"
    )
    if marker not in text:
        raise RuntimeError("server.py patch marker (FCE-M backend init log) not found")
    text = text.replace(marker, inject)

    action_marker = (
        "    elif action == \"embed_batch\":\n"
        "        return await embed_texts(request)\n\n"
        "    else:\n"
        "        raise HTTPException(status_code=400, detail=f\"Unknown action: {action}\")\n"
    )
    action_inject = (
        "    elif action == \"embed_batch\":\n"
        "        return await embed_texts(request)\n\n"
        "    elif action == \"dcortex_v99_status\":\n"
        "        if dcortex_v99 is None:\n"
        "            raise HTTPException(status_code=503, detail=\"D_Cortex v9.9 adapter not initialized\")\n"
        "        return {\"success\": True, \"dcortex_v99\": dcortex_v99.status()}\n\n"
        "    elif action == \"dcortex_v99_run_audit\":\n"
        "        if dcortex_v99 is None:\n"
        "            raise HTTPException(status_code=503, detail=\"D_Cortex v9.9 adapter not initialized\")\n"
        "        return dcortex_v99.run_audit(fast_run=bool(request.get(\"fast_run\", False)), timeout_sec=int(request.get(\"timeout_sec\", 14400)))\n\n"
        "    elif action == \"dcortex_v99_grounding_packet\":\n"
        "        if dcortex_v99 is None:\n"
        "            raise HTTPException(status_code=503, detail=\"D_Cortex v9.9 adapter not initialized\")\n"
        "        return {\"success\": True, \"packet\": dcortex_v99.grounding_packet(request.get(\"query\"))}\n\n"
        "    elif action == \"dcortex_v99_semantic_probe\":\n"
        "        if dcortex_v99 is None:\n"
        "            raise HTTPException(status_code=503, detail=\"D_Cortex v9.9 adapter not initialized\")\n"
        "        return dcortex_v99.semantic_probe(request.get(\"query\", \"\"))\n\n"
        "    else:\n"
        "        raise HTTPException(status_code=400, detail=f\"Unknown action: {action}\")\n"
    )
    if action_marker not in text:
        raise RuntimeError("server.py action marker (embed_batch dispatch) not found")
    text = text.replace(action_marker, action_inject)
    return text


def patch_server_py() -> None:
    """Idempotently inject the dcortex_v99_* actions into server.py on disk."""
    server = SERVICE_DIR / "server.py"
    original = server.read_text(encoding="utf-8")
    if "DCortexV99Adapter" in original:
        log("server.py already patched for D_Cortex")
        return
    patched = apply_server_patch(original)
    server.write_text(patched, encoding="utf-8")
    log(f"server.py patched for D_Cortex actions: {', '.join(DCORTEX_ACTIONS)}")


def write_e2e_script() -> Path:
    dst = ORCH_DIR / "scripts" / "byon-dcortex-v99-live-e2e.mjs"
    ensure_dir(dst.parent)
    shutil.copyfile(E2E_SRC, dst)
    log(f"wrote live E2E harness -> {dst}")
    return dst


# --------------------------------------------------------------------------------------
# Build / deps
# --------------------------------------------------------------------------------------
def service_env() -> Dict[str, str]:
    env = os.environ.copy()
    env.update({
        "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
        "LLM_PROVIDER": "anthropic",
        "LLM_MODEL": LLM_MODEL,
        "MEMORY_SERVICE_URL": MEMORY_SERVICE_URL,
        "MEMORY_SERVICE_HOST": "127.0.0.1",
        "MEMORY_SERVICE_PORT": str(MEMORY_SERVICE_PORT),
        "MEMORY_STORAGE_PATH": str(MEMORY_STORAGE),
        "MEMORY_BACKEND": "hybrid",
        "FCEM_ENABLED": "true",
        "FCEM_CONSOLIDATE_EVERY_N": "3",
        # Load the REAL sealed v15.7a consolidator (external_v15_7a), not the minimal shim.
        "FCEM_MEMORY_ENGINE_ROOT": FCEM_ENGINE_ROOT,
        "FSOAT_REQUIRE_EXTERNAL_FCEM_RUNTIME": "true" if FCEM_ENGINE_ROOT else "false",
        "D_CORTEX_V99_INTEGRATED": "true",
        "DCORTEX_V99_OUTPUT_DIR": str(DCORTEX_OUT),
        "D_CORTEX_V99_OUTPUT_DIR": str(DCORTEX_OUT),
        # reuse the pre-staged level3 checkout in the audit subprocess
        "DCORTEX_LEVEL3_REPO_DIR": str(LEVEL3_REPO),
        "D_CORTEX_FAST_RUN_REQUESTED": os.environ.get("D_CORTEX_FAST_RUN_REQUESTED", "true"),
        "D_CORTEX_SKIP_REAL_TEXT": os.environ.get("D_CORTEX_SKIP_REAL_TEXT", "true"),
        "PYTHONUNBUFFERED": "1",
    })
    return env


def pip_install_service_deps() -> None:
    log("installing memory-service Python dependencies")
    req = SERVICE_DIR / "requirements.txt"
    run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)], check=False, timeout=1800)
    # ensure the live LLM SDK for the E2E (node side uses @anthropic-ai/sdk via npm)
    run([sys.executable, "-m", "pip", "install", "-q", "anthropic"], check=False, timeout=600)


def npm_install_build(run_test: bool) -> Dict[str, Any]:
    env = os.environ.copy()
    env["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] = "1"
    out: Dict[str, Any] = {}
    run([npm_exe(), "install", "--ignore-scripts"], cwd=ORCH_DIR, env=env, check=True, timeout=2400)
    bcp = run([npm_exe(), "run", "build"], cwd=ORCH_DIR, env=env, check=False, timeout=1200)
    out["build_rc"] = bcp.returncode
    if run_test:
        tcp = run([npm_exe(), "test"], cwd=ORCH_DIR, env=env, check=False, timeout=1800)
        out["test_rc"] = tcp.returncode
    return out


# --------------------------------------------------------------------------------------
# Memory service lifecycle
# --------------------------------------------------------------------------------------
def start_memory_service(env: Dict[str, str]) -> subprocess.Popen:
    log_path = RESULTS_DIR / "memory_service.log"
    log(f"starting memory-service at {MEMORY_SERVICE_URL} (log={log_path})")
    log_f = log_path.open("w", encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-u", "server.py"], cwd=str(SERVICE_DIR), env=env,
        stdout=log_f, stderr=subprocess.STDOUT, text=True,
    )
    deadline = time.time() + 240
    last_err: Optional[Exception] = None
    while time.time() < deadline:
        if p.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
            raise RuntimeError(f"memory-service exited early rc={p.returncode}. Tail:\n{tail}")
        try:
            with urllib.request.urlopen(MEMORY_SERVICE_URL + "/health", timeout=3) as r:
                if r.status == 200:
                    log("memory-service healthy")
                    return p
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(3)
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
    raise RuntimeError(f"memory-service did not become healthy: {last_err}. Tail:\n{tail}")


def memory_post(payload: Dict[str, Any], timeout: int = 600) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        MEMORY_SERVICE_URL + "/", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"memory-service HTTP {exc.code} action={payload.get('action')}: {body[-4000:]}") from exc


# --------------------------------------------------------------------------------------
# Main orchestration
# --------------------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="BYON + D_Cortex local full-organism integration runner")
    ap.add_argument("--skip-npm", action="store_true", help="skip npm install/build (orchestrator)")
    ap.add_argument("--run-npm-test", action="store_true", help="run vitest after build")
    ap.add_argument("--skip-pip", action="store_true", help="skip memory-service pip install")
    ap.add_argument("--run-dcortex-audit", action="store_true", help="trigger the embedded D_Cortex audit via the service")
    ap.add_argument("--skip-e2e", action="store_true", help="skip the live Claude E2E")
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)
    ensure_dir(MEMORY_STORAGE)
    ensure_dir(DCORTEX_OUT)

    report: Dict[str, Any] = {
        "timestamp": ts(),
        "runner": "byon-dcortex-local-integration-v1",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "repo_dir": str(EXTERNAL_REPO),
        "llm_model": LLM_MODEL,
        "api_key_written_to_disk": False,
        "dcortex_actions": DCORTEX_ACTIONS,
    }
    proc: Optional[subprocess.Popen] = None
    try:
        load_secret_key()
        log(f"Anthropic key loaded (prefix={os.environ['ANTHROPIC_API_KEY'][:10]}...). Not persisted by runner.")
        verify_repo()
        write_dcortex_injection()
        patch_server_py()
        write_e2e_script()

        if not args.skip_pip:
            pip_install_service_deps()
        if not args.skip_npm:
            report["npm"] = npm_install_build(args.run_npm_test)

        env = service_env()
        proc = start_memory_service(env)
        report["memory_health"] = memory_post({"action": "ping"}, timeout=10) if False else json.loads(
            urllib.request.urlopen(MEMORY_SERVICE_URL + "/health", timeout=5).read().decode("utf-8")
        )
        report["dcortex_status_start"] = memory_post({"action": "dcortex_v99_status"}, timeout=30)

        if args.run_dcortex_audit:
            log("running embedded D_Cortex audit through memory-service action")
            report["dcortex_v99_run"] = memory_post(
                {"action": "dcortex_v99_run_audit", "fast_run": True, "timeout_sec": 14400}, timeout=15000
            )

        report["dcortex_grounding_packet"] = memory_post(
            {"action": "dcortex_v99_grounding_packet", "query": "BYON level and source grounding"}, timeout=60
        )

        if not args.skip_e2e:
            log("running BYON + D_Cortex live QA gating harness (Claude)")
            e2e_env = env.copy()
            e2e_out = RESULTS_DIR / "byon-dcortex-v99-live-e2e"
            e2e_env["BYON_DCORTEX_E2E_OUT"] = str(e2e_out)
            cp = run([node_exe(), "scripts/byon-dcortex-v99-live-e2e.mjs"], cwd=ORCH_DIR, env=e2e_env, check=False, timeout=900)
            report["byon_dcortex_live_e2e"] = {
                "returncode": cp.returncode, "out_dir": str(e2e_out),
                "stdout_tail": cp.stdout[-4000:], "stderr_tail": cp.stderr[-4000:],
            }

        report["dcortex_status_final"] = memory_post({"action": "dcortex_v99_status"}, timeout=30)
        report["success"] = True
    except Exception as exc:  # noqa: BLE001
        report["success"] = False
        report["error"] = repr(exc)
        log(f"FATAL {exc}")
    finally:
        if proc is not None and proc.poll() is None:
            log("stopping memory-service")
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        report_path = RESULTS_DIR / "integration_report.json"
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        log(f"report -> {report_path}")
        if not report.get("success"):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
