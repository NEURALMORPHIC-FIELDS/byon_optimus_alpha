"""Vault read/chunk error classification (Cycle 4, target 5).

One bad note must never crash a full training run, and errors must be classified and logged with
file path + reason, not silently swallowed. Encoding is handled with a safe fallback ladder
(utf-8 → utf-8-sig → cp1252 as a last resort); binary / oversized files are skipped explicitly.

Errors are written to runtime/vaults/{vault_hash}/errors.jsonl:
  {file_path, error_type, message, phase, recoverable}
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# error types
ENCODING = "encoding"
PERMISSION = "permission"
FRONTMATTER = "frontmatter"
UNSUPPORTED = "unsupported_markdown"
EMPTY_OR_BINARY_OR_LARGE = "empty_or_binary_or_large"
PATH = "path"
STORE = "store"
UNKNOWN = "unknown"

MAX_BYTES = 2_000_000   # 2 MB: a markdown note beyond this is treated as not-a-note


def classify_exception(exc: Exception, phase: str) -> Tuple[str, bool]:
    """(error_type, recoverable) for an exception raised during a given phase."""
    if isinstance(exc, PermissionError):
        return PERMISSION, False
    if isinstance(exc, UnicodeDecodeError):
        return ENCODING, True
    if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        return PATH, False
    if phase == "frontmatter":
        return FRONTMATTER, True
    if phase == "store":
        return STORE, True
    if phase == "chunk":
        return UNSUPPORTED, True
    return UNKNOWN, False


def read_markdown(path: Path) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Read a note with an encoding fallback ladder. Returns (text, None) on success or
    (None, error_dict) when the file should be skipped/errored. Never raises."""
    try:
        raw = path.read_bytes()
    except PermissionError as exc:
        return None, {"error_type": PERMISSION, "message": str(exc), "phase": "read",
                      "recoverable": False}
    except OSError as exc:
        return None, {"error_type": PATH, "message": str(exc), "phase": "read",
                      "recoverable": False}
    if not raw:
        return None, {"error_type": EMPTY_OR_BINARY_OR_LARGE, "message": "empty file",
                      "phase": "read", "recoverable": False}
    if len(raw) > MAX_BYTES:
        return None, {"error_type": EMPTY_OR_BINARY_OR_LARGE,
                      "message": f"file too large ({len(raw)} bytes > {MAX_BYTES})",
                      "phase": "read", "recoverable": False}
    if b"\x00" in raw[:4096]:
        return None, {"error_type": EMPTY_OR_BINARY_OR_LARGE, "message": "binary content (NUL byte)",
                      "phase": "read", "recoverable": False}
    for enc in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc), None
        except UnicodeDecodeError:
            continue
    # last resort: lossy utf-8 (recorded as an encoding error but still usable)
    return raw.decode("utf-8", errors="replace"), {"error_type": ENCODING,
            "message": "decoded with utf-8 replacement (no clean encoding matched)",
            "phase": "read", "recoverable": True}


class VaultErrorLog:
    def __init__(self, vault_hash: str, *, base: str = "runtime/vaults") -> None:
        self.path = Path(base) / vault_hash / "errors.jsonl"
        self.records: list = []

    def log(self, file_path: str, error_type: str, message: str, phase: str,
            recoverable: bool) -> Dict[str, Any]:
        rec = {"file_path": file_path, "error_type": error_type, "message": str(message)[:300],
               "phase": phase, "recoverable": bool(recoverable),
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self.records.append(rec)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return rec

    def counts_by_type(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for r in self.records:
            out[r["error_type"]] = out.get(r["error_type"], 0) + 1
        return out

    def reset_file(self) -> None:
        """Start a fresh error log for a full (non-resume) run."""
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass
        self.records = []
