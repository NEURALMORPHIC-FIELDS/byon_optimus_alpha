# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""ServiceSupervisor - start/track/stop child services for the one-command launcher.

Starts subprocesses, captures their logs, waits for HTTP health, and guarantees the
children are terminated on exit / Ctrl+C / exception. The user never manages terminals.
"""
from __future__ import annotations

import atexit
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


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


@dataclass
class Service:
    name: str
    proc: subprocess.Popen
    log_path: Path
    log_file: object


@dataclass
class ServiceSupervisor:
    log_dir: str = "runtime/alpha_app/services"
    services: Dict[str, Service] = field(default_factory=dict)
    _atexit_registered: bool = False

    def __post_init__(self) -> None:
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        if not self._atexit_registered:
            atexit.register(self.stop_all)
            self._atexit_registered = True

    def start(self, name: str, command: List[str], cwd: Optional[str] = None,
              env: Optional[Dict[str, str]] = None) -> Service:
        log_path = Path(self.log_dir) / f"{name}.log"
        log_file = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=log_file,
                                stderr=subprocess.STDOUT, text=True)
        svc = Service(name=name, proc=proc, log_path=log_path, log_file=log_file)
        self.services[name] = svc
        return svc

    def is_alive(self, name: str) -> bool:
        svc = self.services.get(name)
        return bool(svc and svc.proc.poll() is None)

    def wait_http(self, name: str, url: str, timeout: float = 60.0,
                  interval: float = 1.0) -> bool:
        import httpx
        deadline = time.time() + timeout
        while time.time() < deadline:
            if name in self.services and self.services[name].proc.poll() is not None:
                return False  # process already exited → fail fast
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
        try:
            svc.log_file.close()
        except Exception:
            pass

    def stop_all(self) -> None:
        for name in list(self.services.keys()):
            self.stop(name)
