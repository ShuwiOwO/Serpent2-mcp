"""Small shared utilities (network, files, subprocess)."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "serpent2-mcp/0.1 (+https://serpent.vtt.fi)"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def http_get(
    url: str,
    timeout: float = 60.0,
    retries: int = 3,
    headers: dict[str, str] | None = None,
) -> bytes:
    """Fetch a URL and return raw bytes. Retries transient failures."""
    req_headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if headers:
        req_headers.update(headers)
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    data = gzip.decompress(data)
                return data
        except Exception as exc:  # noqa: BLE001 - retry all network errors
            last_error = exc
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
    assert last_error is not None
    raise last_error


def http_get_text(url: str, timeout: float = 60.0, retries: int = 3) -> str:
    data = http_get(url, timeout=timeout, retries=retries)
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def atomic_write(path: Path, data: bytes | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(data, str):
        tmp.write_text(data, encoding="utf-8")
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, obj: Any) -> None:
    atomic_write(path, json.dumps(obj, indent=2, ensure_ascii=False))


def run_capture(
    argv: list[str],
    timeout: float = 10.0,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> tuple[int, str, str]:
    """Run a command, capturing output. Never raises on non-zero exit."""
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        return 124, out, err + f"\n[timeout after {timeout:.0f}s]"
    except OSError as exc:
        return 127, "", str(exc)


def truncate(text: str, limit: int = 12000, note: str = "... [truncated]") -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n{note}"


def human_size(num: float | int | None) -> str:
    if num is None:
        return "?"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.2f} TB"


def stderr_log(message: str) -> None:
    """Log to stderr (stdout is reserved for the MCP stdio protocol)."""
    print(f"[serpent2-mcp] {message}", file=sys.stderr, flush=True)
