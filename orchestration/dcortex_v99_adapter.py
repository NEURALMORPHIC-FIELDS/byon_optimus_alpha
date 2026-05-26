
import os
import sys
import json
import time
import traceback
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

class DCortexV99Adapter:
    """Additive D_Cortex v9.9 memory organ for BYON memory-service.

    Non-dilution rule:
    - FAISS, FCE-M, verified/domain facts and BYON trust hierarchy remain canonical.
    - D_Cortex v9.9 is added as a semantic grounded-QA / anti-memorization memory organ.
    - All failures are returned as JSON, never as raw HTTP 500, so Colab can continue with full provenance.
    """

    def __init__(self, memory_storage_path: str, repo_root: str):
        self.memory_storage_path = Path(memory_storage_path)
        root = Path(repo_root).resolve()
        # Accept either official repo root (.../byon_optimus) or orchestrator root.
        # v9.9 passed the orchestrator root but then appended byon-orchestrator
        # a second time; the source path did not exist, so audit returned
        # success=false before subprocess execution.
        if (root / "memory-service" / "server.py").exists():
            self.repo_root = root.parent
            self.orchestrator_root = root
            self.service_dir = root / "memory-service"
        elif (root / "byon-orchestrator" / "memory-service" / "server.py").exists():
            self.repo_root = root
            self.orchestrator_root = root / "byon-orchestrator"
            self.service_dir = self.orchestrator_root / "memory-service"
        else:
            self.repo_root = root
            self.orchestrator_root = root / "byon-orchestrator"
            self.service_dir = self.orchestrator_root / "memory-service"
        self.source_path = self.service_dir / "dcortex_v99_source.py"
        self.output_dir = Path(os.environ.get(
            "DCORTEX_V99_OUTPUT_DIR",
            "/content/drive/MyDrive/v9_9_chronodynamic_semantic_grounded_cortex_results",
        ))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.last_run = None

    def status(self) -> Dict[str, Any]:
        try:
            results = self.output_dir / "v9_9_results.json"
            report = self.output_dir / "v9_9_report.md"
            snapshot = self.output_dir / "v9_9_snapshot.pt"
            return {
                "enabled": True,
                "source_path": str(self.source_path),
                "source_exists": self.source_path.exists(),
                "source_size_bytes": self.source_path.stat().st_size if self.source_path.exists() else 0,
                "source_lines": sum(1 for _ in self.source_path.open("r", encoding="utf-8")) if self.source_path.exists() else 0,
                "output_dir": str(self.output_dir),
                "results_exists": results.exists(),
                "report_exists": report.exists(),
                "snapshot_exists": snapshot.exists(),
                "snapshot_size_mb": round(snapshot.stat().st_size / (1024*1024), 3) if snapshot.exists() else 0.0,
                "last_run": self.last_run,
            }
        except Exception as exc:
            return {"enabled": False, "status_error": repr(exc), "traceback": traceback.format_exc()[-4000:]}

    def run_audit(self, fast_run: bool = False, timeout_sec: int = 14400) -> Dict[str, Any]:
        try:
            if not self.source_path.exists():
                return {"success": False, "error": f"missing source {self.source_path}", "status": self.status()}
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["D_CORTEX_EMBEDDED_IN_BYON"] = "true"
            env.setdefault("DCORTEX_V99_OUTPUT_DIR", str(self.output_dir))
            if fast_run:
                env["D_CORTEX_FAST_RUN_REQUESTED"] = "true"
            t0 = time.time()
            proc = subprocess.run(
                [sys.executable, "-u", str(self.source_path)],
                cwd=str(self.service_dir),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_sec,
            )
            dt = time.time() - t0
            stdout_tail = proc.stdout[-20000:]
            stderr_tail = proc.stderr[-20000:]
            log_path = self.output_dir / "byon_embedded_v99_run.log"
            log_path.write_text(proc.stdout + "\n\nSTDERR:\n" + proc.stderr, encoding="utf-8")
            self.last_run = {
                "returncode": proc.returncode,
                "duration_sec": dt,
                "log_path": str(log_path),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            return {
                "success": proc.returncode == 0,
                "returncode": proc.returncode,
                "duration_sec": dt,
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
                "log_path": str(log_path),
                "status": self.status(),
            }
        except subprocess.TimeoutExpired as exc:
            self.last_run = {
                "returncode": -124,
                "duration_sec": timeout_sec,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "timeout": True,
            }
            return {
                "success": False,
                "error": "D_Cortex v9.9 audit timed out",
                "timeout_sec": timeout_sec,
                "stdout_tail": (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else str(exc.stdout)[-12000:],
                "stderr_tail": (exc.stderr or "")[-12000:] if isinstance(exc.stderr, str) else str(exc.stderr)[-12000:],
                "status": self.status(),
            }
        except Exception as exc:
            self.last_run = {
                "returncode": -1,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "exception": repr(exc),
            }
            return {
                "success": False,
                "error": repr(exc),
                "traceback": traceback.format_exc()[-12000:],
                "status": self.status(),
            }

    def _load_results(self) -> Dict[str, Any]:
        p = self.output_dir / "v9_9_results.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"_load_error": repr(exc), "_load_traceback": traceback.format_exc()[-4000:]}

    def grounding_packet(self, query: Optional[str] = None) -> Dict[str, Any]:
        try:
            r = self._load_results()
            rt = r.get("real_text_assimilation_audit", {}) or {}
            # Schema-robust: semantic QA may live nested under the v9.8 audit.
            qa = (r.get("semantic_grounded_qa_audit")
                  or rt.get("v9_8_semantic_grounded_qa_audit")
                  or rt or {})
            # v9.9 `verdict` is a string; older schemas used a dict. Handle both.
            verdict = r.get("verdict", {})
            if isinstance(verdict, str):
                verdict_line = verdict
            else:
                verdict = verdict or {}
                verdict_line = verdict.get("verdict") or verdict.get("final_verdict_line") or r.get("final_verdict_line")

            def _q(*keys):
                for k in keys:
                    if qa.get(k) is not None:
                        return qa.get(k)
                return None

            packet = {
                "enabled": True,
                "organ": "D_Cortex_v9_9_semantic_grounded_QA_memory",
                "query": query,
                "verdict_line": verdict_line,
                "passes": bool(qa.get("passes", False)),
                "semantic_qa": _q("semantic_grounded_qa_accuracy", "semantic_qa_accuracy"),
                "paraphrase_qa": _q("paraphrase_accuracy", "paraphrase_qa_accuracy"),
                "source_qa": _q("source_grounded_accuracy", "source_qa_accuracy"),
                "relation_qa": _q("relation_grounded_accuracy", "relation_qa_accuracy"),
                "no_answer": _q("no_answer_accuracy"),
                "contradiction_boundary": _q("contradiction_source_boundary_accuracy", "contradiction_boundary_accuracy"),
                "memory_damage": _q("memory_damage", "persistent_memory_damage"),
                "key_damage": _q("key_damage", "real_text_key_damage"),
                "target_permutation_damage": _q("target_permutation_damage"),
                "reader_only_accuracy_proxy": _q("reader_only_accuracy_proxy"),
                "skipped": bool(rt.get("skipped", False)),
                "status": self.status(),
            }
            no_answer = packet.get("no_answer")
            if no_answer is not None and no_answer < 0.75:
                packet["byon_required_gate"] = "route unknown/insufficient-info through BYON Auditor/trust hierarchy; do not rely on local cortex-only abstention"
            else:
                packet["byon_required_gate"] = "local cortex abstention acceptable; still enforce BYON trust hierarchy"
            return packet
        except Exception as exc:
            return {"enabled": False, "query": query, "error": repr(exc), "traceback": traceback.format_exc()[-8000:], "status": self.status()}

    def semantic_probe(self, query: str) -> Dict[str, Any]:
        packet = self.grounding_packet(query=query)
        return {
            "success": True,
            "query": query,
            "dcortex_grounding_packet": packet,
            "answer_mode": "BYON_AGENT_REQUIRED",
        }
