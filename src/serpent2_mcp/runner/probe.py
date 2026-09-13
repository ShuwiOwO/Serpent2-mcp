"""Probe the installed Serpent executable (version, CLI flag style)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..config import Settings
from ..util import now_iso, read_json, run_capture, write_json


def resolve_executable(exe: str | None) -> Path | None:
    if not exe:
        return None
    path = Path(exe).expanduser()
    if path.is_file():
        return path
    found = shutil.which(exe)
    return Path(found) if found else None


def probe(exe: str | None) -> dict:
    """Run the executable without arguments and parse version/usage."""
    path = resolve_executable(exe)
    if path is None:
        return {"found": False, "exe": exe, "error": "executable not found"}
    rc, out, err = run_capture([str(path)], timeout=12)
    text = f"{out}\n{err}"
    version = None
    match = re.search(r"[Vv]ersion\s*[:=]?\s*([0-9][0-9A-Za-z._-]*)", text)
    if match:
        version = match.group(1)
    if re.search(r"--[a-z]", text):
        style = "double"
    elif re.search(r"(?<!-)-[a-z][a-z]+", text):
        style = "single"
    else:
        style = "double"
    return {
        "found": True,
        "exe": str(path),
        "version": version,
        "flag_style": style,
        "exit_code": rc,
        "usage_excerpt": text[:3000],
        "probed_at": now_iso(),
    }


def probe_cached(settings: Settings, refresh: bool = False) -> dict:
    cache_file = settings.cache_dir / "exe_probe.json"
    cached = read_json(cache_file, default=None)
    exe = settings.exe
    try:
        stamp = str(Path(exe).expanduser().stat().st_mtime) if exe else None
    except OSError:
        stamp = None
    if (
        not refresh
        and isinstance(cached, dict)
        and cached.get("exe") == exe
        and cached.get("stamp") == stamp
        and cached.get("found")
    ):
        return cached
    result = probe(exe)
    result["stamp"] = stamp
    write_json(cache_file, result)
    return result


def convert_option_style(option: str, style: str) -> str:
    """Normalise a CLI option to single- or double-dash form."""
    if style == "single":
        if option.startswith("--"):
            return "-" + option[2:]
        return option
    if style == "double":
        if option.startswith("--") or len(option) <= 2:
            return option
        return "-" + option
    return option
