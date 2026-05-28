# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""ServiceSupervisor - start/track/stop child services for the one-command launcher.

Starts subprocesses, captures their logs, waits for HTTP health, and guarantees the
children are terminated on exit / Ctrl+C / exception. The user never manages terminals.

Cycle 14 hardening (S5): child stdout/stderr are ALWAYS redirected to OPEN FILE HANDLES, never to
an unread subprocess.PIPE (an unread PIPE fills the ~64KB OS buffer under sustained logging and
blocks the child on write while the parent stays up - the exact "memory-service dies mid-run while
Gateway stays alive" symptom). The supervisor also records child PID + command + redacted env +
exit code as diagnostics, and supports a bounded, opt-in autorestart that marks the run unstable.
"""
from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# env-var name fragments whose VALUES must never be written to diagnostics
_SECRET_FRAGMENTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PWD", "CRED", "AUTH")


def is_port_free(host: str, port: int) -> bool:
    """True if a server could bind here. Uses bind (not connect) so a listening socket's
    backlog is never consumed - connect-based probing is flaky on Windows."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_free_port(host: str, start: int, tries: int = 20) -> int:
    for p in range(start, start + tries):
        if is_port_free(host, p):
            return p
    return start


def redact_env(env: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Return env with secret-looking VALUES replaced by <redacted>. Never writes secrets to disk."""
    out: Dict[str, str] = {}
    for k, v in (env or {}).items():
        upper = k.upper()
        out[k] = "<redacted>" if any(frag in upper for frag in _SECRET_FRAGMENTS) else v
    return out


@dataclass
class Service:
    name: str
    proc: subprocess.Popen
    log_path: Path
    log_file: object
    command: List[str] = field(default_factory=list)
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    stdout_path: Optional[Path] = None
    stderr_path: Optional[Path] = None
    stderr_file: object = None
    restart_count: int = 0
    exit_code: Optional[int] = None


@dataclass
class ServiceSupervisor:
    log_dir: str = "runtime/alpha_app/services"
    diagnostics_dir: str = "runtime/diagnostics"
    services: Dict[str, Service] = field(default_factory=dict)
    unstable: bool = False
    _atexit_registered: bool = False

    def __post_init__(self) -> None:
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        if not self._atexit_registered:
            atexit.register(self.stop_all)
            self._atexit_registered = True

    def start(self, name: str, command: List[str], cwd: Optional[str] = None,
              env: Optional[Dict[str, str]] = None, *, stdout_path: Optional[str] = None,
              stderr_path: Optional[str] = None, record_diagnostics: bool = False) -> Service:
        """Launch a child. Output is redirected to FILE HANDLES (pipe-safe). If both stdout_path and
        stderr_path are given they are used as separate logs; otherwise a single combined log is
        used (stderr merged into stdout). NEVER uses subprocess.PIPE."""
        out_path = Path(stdout_path) if stdout_path else (Path(self.log_dir) / f"{name}.log")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(out_path, "w", encoding="utf-8")
        err_file = None
        if stderr_path:
            err_p = Path(stderr_path)
            err_p.parent.mkdir(parents=True, exist_ok=True)
            err_file = open(err_p, "w", encoding="utf-8")
            proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=log_file,
                                    stderr=err_file, text=True)
        else:
            proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=log_file,
                                    stderr=subprocess.STDOUT, text=True)
        svc = Service(name=name, proc=proc, log_path=out_path, log_file=log_file,
                      command=list(command), cwd=cwd, env=env, stdout_path=out_path,
                      stderr_path=Path(stderr_path) if stderr_path else None, stderr_file=err_file)
        self.services[name] = svc
        if record_diagnostics:
            self.write_process_diagnostics(name)
        return svc

    def write_process_diagnostics(self, name: str) -> Optional[Path]:
        """Record PID + command + redacted env (NO secret values) + start time to
        runtime/diagnostics/{name}_process.json."""
        svc = self.services.get(name)
        if not svc:
            return None
        diag = Path(self.diagnostics_dir)
        diag.mkdir(parents=True, exist_ok=True)
        path = diag / f"{name.replace('-', '_')}_process.json"
        payload = {
            "name": svc.name,
            "pid": svc.proc.pid,
            "command": svc.command,
            "cwd": svc.cwd,
            "stdout_log": str(svc.stdout_path) if svc.stdout_path else None,
            "stderr_log": str(svc.stderr_path) if svc.stderr_path else None,
            "env_redacted": redact_env(svc.env),
            "start_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def is_alive(self, name: str) -> bool:
        svc = self.services.get(name)
        return bool(svc and svc.proc.poll() is None)

    def record_exit(self, name: str) -> Optional[int]:
        """If the child has exited, capture its return code into the Service + diagnostics json."""
        svc = self.services.get(name)
        if not svc:
            return None
        rc = svc.proc.poll()
        if rc is not None:
            svc.exit_code = rc
            diag = Path(self.diagnostics_dir)
            diag.mkdir(parents=True, exist_ok=True)
            path = diag / f"{name.replace('-', '_')}_process.json"
            data: Dict[str, Any] = {}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    data = {}
            data["exit_code"] = rc
            data["exit_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return svc.exit_code

    def restart_if_dead(self, name: str, *, autorestart: Optional[bool] = None,
                        max_restarts: Optional[int] = None, backoff_seconds: Optional[float] = None,
                        sleep: Optional[Any] = None) -> Dict[str, Any]:
        """Bounded, opt-in autorestart. Disabled by default (BYON_MEMORY_SERVICE_AUTORESTART=false).
        If the child is dead AND autorestart is enabled AND under the restart cap, relaunch it,
        mark the run unstable (a run with ANY restart is NOT clean), and log it. Never silent."""
        svc = self.services.get(name)
        if not svc:
            return {"restarted": False, "reason": "unknown service"}
        if svc.proc.poll() is None:
            return {"restarted": False, "reason": "still alive"}
        self.record_exit(name)
        if autorestart is None:
            autorestart = os.environ.get("BYON_MEMORY_SERVICE_AUTORESTART", "false").strip().lower() \
                in ("1", "true", "yes", "on")
        if max_restarts is None:
            max_restarts = int(os.environ.get("BYON_MEMORY_SERVICE_AUTORESTART_MAX", "1"))
        if backoff_seconds is None:
            backoff_seconds = float(os.environ.get("BYON_MEMORY_SERVICE_AUTORESTART_BACKOFF_SECONDS", "3"))
        if not autorestart:
            print(f"[supervisor] {name} died (exit={svc.exit_code}); autorestart disabled - "
                  f"NOT restarting (run is a failure, not a clean pass).", flush=True)
            return {"restarted": False, "autorestart_enabled": False, "exit_code": svc.exit_code}
        if svc.restart_count >= max_restarts:
            print(f"[supervisor] {name} died (exit={svc.exit_code}); restart cap {max_restarts} "
                  f"reached - NOT restarting.", flush=True)
            return {"restarted": False, "autorestart_enabled": True, "cap_reached": True,
                    "exit_code": svc.exit_code}
        (sleep or time.sleep)(backoff_seconds)
        prev = svc.restart_count + 1
        print(f"[supervisor] {name} died (exit={svc.exit_code}); AUTORESTART {prev}/{max_restarts}; "
              f"run marked recovered_but_unstable.", flush=True)
        new = self.start(name, svc.command, cwd=svc.cwd, env=svc.env,
                         stdout_path=str(svc.stdout_path) if svc.stdout_path else None,
                         stderr_path=str(svc.stderr_path) if svc.stderr_path else None,
                         record_diagnostics=True)
        new.restart_count = prev
        self.unstable = True
        return {"restarted": True, "restart_count": prev, "unstable": True,
                "recovered_but_unstable": True, "previous_exit_code": svc.exit_code}

    def is_clean_run(self) -> bool:
        """A run with ANY autorestart is NOT clean."""
        return not self.unstable

    def wait_http(self, name: str, url: str, timeout: float = 60.0,
                  interval: float = 1.0) -> bool:
        import httpx
        deadline = time.time() + timeout
        while time.time() < deadline:
            if name in self.services and self.services[name].proc.poll() is not None:
                return False  # process already exited -> fail fast
            try:
                r = httpx.get(url, timeout=2.0)
                if r.status_code < 500:
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    def tail_log(self, name: str, lines: int = 25) -> str:
        svc = self.services.get(name)
        if not svc or not svc.log_path.exists():
            return ""
        try:
            return "\n".join(svc.log_path.read_text(encoding="utf-8").splitlines()[-lines:])
        except OSError:
            return ""

    def stop(self, name: str) -> None:
        svc = self.services.get(name)
        if not svc:
            return
        if svc.proc.poll() is None:
            try:
                svc.proc.terminate()
                try:
                    svc.proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    svc.proc.kill()
            except Exception:
                pass
        for handle in (svc.log_file, svc.stderr_file):
            try:
                if handle is not None:
                    handle.close()
            except Exception:
                pass

    def stop_all(self) -> None:
        for name in list(self.services.keys()):
            self.stop(name)
