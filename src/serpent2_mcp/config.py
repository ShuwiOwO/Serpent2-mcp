"""Configuration and zero-config discovery of the Serpent installation.

Resolution order (later wins):

1. Built-in defaults.
2. TOML config file (``serpent2-mcp.toml`` / ``.serpent2-mcp.toml`` in the
   workspace, or ``~/.config/serpent2-mcp/config.toml``).
3. Environment variables (``SERPENT_*``).

Every path parameter is optional: if ``sss2`` and the data libraries are simply
sitting in (or under) the directory where the MCP client was started, they are
found automatically.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # Python >= 3.11
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10
    tomllib = None  # type: ignore[assignment]

APP_NAME = "serpent2-mcp"

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _xdg(env_var: str, fallback: str) -> Path:
    base = os.environ.get(env_var)
    return Path(base) if base else Path.home() / fallback


def default_state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / APP_NAME


def default_cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / APP_NAME


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _split_paths(value: str) -> list[Path]:
    return [Path(p).expanduser() for p in value.split(os.pathsep) if p.strip()]


@dataclass
class SshConfig:
    host: str
    workdir: str | None = None
    jobdir: str = "~/.serpent2-mcp/jobs"
    options: list[str] = field(default_factory=list)


@dataclass
class Settings:
    workspace: Path
    exe: str | None = None
    exe_source: str | None = None
    data_dirs: list[Path] = field(default_factory=list)
    acelib: Path | None = None
    declib: Path | None = None
    nfylib: Path | None = None
    backend: str = "local"
    ssh: SshConfig | None = None
    omp: int | None = None
    mpi_launcher: str | None = None
    job_timeout: int = 0
    jobs_dir: Path = field(default_factory=lambda: default_state_dir() / "jobs")
    cache_dir: Path = field(default_factory=default_cache_dir)
    docs_url: str = "https://serpent.vtt.fi/docs"
    docs_auto_sync: bool = True
    docs_max_age_days: int = 30
    lang: str = "ru"
    allow_outside: bool = False
    extra_allowed_roots: list[Path] = field(default_factory=list)
    config_file: Path | None = None

    @property
    def allowed_roots(self) -> list[Path]:
        roots = [self.workspace, self.jobs_dir, self.cache_dir]
        roots.extend(self.data_dirs)
        roots.extend(self.extra_allowed_roots)
        seen: list[Path] = []
        for root in roots:
            try:
                resolved = root.expanduser().resolve()
            except OSError:
                continue
            if resolved not in seen:
                seen.append(resolved)
        return seen

    def resolve(self, path: str | Path) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.workspace / p
        return p

    def is_allowed(self, path: str | Path) -> bool:
        if self.allow_outside:
            return True
        try:
            target = self.resolve(path).resolve()
        except OSError:
            return False
        for root in self.allowed_roots:
            try:
                target.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "exe": self.exe,
            "exe_source": self.exe_source,
            "data_dirs": [str(p) for p in self.data_dirs],
            "acelib": str(self.acelib) if self.acelib else None,
            "declib": str(self.declib) if self.declib else None,
            "nfylib": str(self.nfylib) if self.nfylib else None,
            "backend": self.backend,
            "ssh_host": self.ssh.host if self.ssh else None,
            "ssh_workdir": self.ssh.workdir if self.ssh else None,
            "omp": self.omp,
            "mpi_launcher": self.mpi_launcher,
            "job_timeout": self.job_timeout,
            "jobs_dir": str(self.jobs_dir),
            "cache_dir": str(self.cache_dir),
            "docs_url": self.docs_url,
            "lang": self.lang,
            "config_file": str(self.config_file) if self.config_file else None,
        }


# ---------------------------------------------------------------------------
# TOML
# ---------------------------------------------------------------------------


def _find_config_file(workspace: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    candidates = [
        workspace / "serpent2-mcp.toml",
        workspace / ".serpent2-mcp.toml",
        Path.home() / ".config" / APP_NAME / "config.toml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_toml(path: Path | None) -> dict[str, Any]:
    if path is None or tomllib is None:
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# Filesystem discovery
# ---------------------------------------------------------------------------


def _find_files(
    roots: list[Path],
    patterns: tuple[str, ...],
    max_depth: int = 3,
) -> list[Path]:
    """Find files matching glob patterns under roots, breadth-limited."""
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        root = root.expanduser()
        if not root.is_dir():
            continue
        queue: list[tuple[Path, int]] = [(root, 0)]
        while queue:
            directory, depth = queue.pop(0)
            try:
                entries = sorted(directory.iterdir())
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir():
                        if depth < max_depth and entry.name not in _SKIP_DIRS:
                            queue.append((entry, depth + 1))
                        continue
                    if any(entry.match(pat) for pat in patterns):
                        resolved = entry.resolve()
                        if resolved not in seen:
                            seen.add(resolved)
                            found.append(resolved)
                except OSError:
                    continue
    return found


def _find_executable(workspace: Path) -> tuple[str | None, str | None]:
    direct = workspace / "sss2"
    if direct.is_file():
        return str(direct), f"found in workspace: {direct}"
    candidates = _find_files([workspace], ("sss2",), max_depth=3)
    if candidates:
        return str(candidates[0]), f"found under workspace: {candidates[0]}"
    from .util import which

    on_path = which("sss2")
    if on_path:
        return on_path, "found in PATH"
    return None, None


def _resolve_explicit_path(value: str | None, workspace: Path) -> Path | None:
    if not value:
        return None
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = workspace / p
    return p


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_settings(workspace: str | Path | None = None) -> Settings:
    ws_env = os.environ.get("SERPENT_MCP_WORKSPACE")
    if workspace is not None:
        ws = Path(workspace)
    elif ws_env:
        ws = Path(ws_env)
    else:
        ws = Path.cwd()
    ws = ws.expanduser().resolve()

    config_file = _find_config_file(ws, os.environ.get("SERPENT_TOML"))
    toml = _load_toml(config_file)
    sec = toml.get("serpent", {}) if isinstance(toml, dict) else {}
    backend_sec = toml.get("backend", {}) if isinstance(toml, dict) else {}
    run_sec = toml.get("run", {}) if isinstance(toml, dict) else {}
    docs_sec = toml.get("docs", {}) if isinstance(toml, dict) else {}
    ui_sec = toml.get("ui", {}) if isinstance(toml, dict) else {}

    # --- executable -------------------------------------------------------
    explicit_exe = os.environ.get("SERPENT_EXE") or sec.get("exe")
    exe: str | None = None
    exe_source: str | None = None
    if explicit_exe:
        resolved = _resolve_explicit_path(str(explicit_exe), ws)
        if resolved and resolved.is_file():
            exe, exe_source = str(resolved), "configured"
        elif "/" not in str(explicit_exe):
            from .util import which

            on_path = which(str(explicit_exe))
            if on_path:
                exe, exe_source = on_path, "configured (from PATH)"
            else:
                exe, exe_source = str(explicit_exe), "configured (not found)"
        else:
            exe, exe_source = str(explicit_exe), "configured (not found)"
    else:
        exe, exe_source = _find_executable(ws)

    # --- data -------------------------------------------------------------
    env_data_dirs = os.environ.get("SERPENT_DATA_DIR")
    configured_dirs: list[Path] = []
    if env_data_dirs:
        configured_dirs.extend(_split_paths(env_data_dirs))
    elif sec.get("data_dirs"):
        configured_dirs.extend(_resolve_explicit_path(str(d), ws) for d in sec["data_dirs"])
    data_dirs = [d for d in configured_dirs if d is not None]

    search_roots = list(data_dirs) + [ws]
    xsdata_files = _find_files(search_roots, ("*.xsdata",), max_depth=3)
    dec_files = _find_files(search_roots, ("*.dec",), max_depth=3)
    nfy_files = _find_files(search_roots, ("*.nfy",), max_depth=3)

    for path in (xsdata_files + dec_files + nfy_files):
        parent = path.parent
        if parent not in data_dirs:
            data_dirs.append(parent)

    def _pick(explicit_env: str, explicit_cfg: Any, files: list[Path], preferred: str | None) -> Path | None:
        raw = os.environ.get(explicit_env) or explicit_cfg
        if raw:
            resolved = _resolve_explicit_path(str(raw), ws)
            if resolved:
                return resolved
        if preferred:
            for candidate in files:
                if candidate.name == preferred:
                    return candidate
        return files[0] if files else None

    acelib = _pick("SERPENT_ACELIB", sec.get("acelib"), xsdata_files, "data.xsdata")
    declib = _pick("SERPENT_DECLIB", sec.get("declib"), dec_files, "sss_endfb7.dec")
    nfylib = _pick("SERPENT_NFYLIB", sec.get("nfylib"), nfy_files, "sss_endfb7.nfy")

    # --- backend ----------------------------------------------------------
    ssh_sec = backend_sec.get("ssh", {}) if isinstance(backend_sec, dict) else {}
    ssh_host = os.environ.get("SERPENT_SSH_HOST") or ssh_sec.get("host")
    ssh: SshConfig | None = None
    if ssh_host:
        raw_opts = os.environ.get("SERPENT_SSH_OPTS")
        options = raw_opts.split() if raw_opts else list(ssh_sec.get("options", []))
        ssh = SshConfig(
            host=str(ssh_host),
            workdir=os.environ.get("SERPENT_SSH_WORKDIR") or ssh_sec.get("workdir"),
            jobdir=os.environ.get("SERPENT_SSH_JOBDIR") or ssh_sec.get("jobdir", "~/.serpent2-mcp/jobs"),
            options=options,
        )

    backend = os.environ.get("SERPENT_BACKEND") or backend_sec.get("type") or ("ssh" if ssh else "local")
    if backend not in {"local", "ssh"}:
        backend = "local"

    # --- run options ------------------------------------------------------
    omp_raw = os.environ.get("SERPENT_OMP") or run_sec.get("omp")
    omp = int(omp_raw) if omp_raw not in (None, "") else None

    timeout_raw = os.environ.get("SERPENT_JOB_TIMEOUT") or run_sec.get("timeout_seconds")
    try:
        job_timeout = int(timeout_raw) if timeout_raw not in (None, "") else 0
    except (TypeError, ValueError):
        job_timeout = 0

    jobs_dir_raw = os.environ.get("SERPENT_JOBS_DIR")
    jobs_dir = Path(jobs_dir_raw).expanduser() if jobs_dir_raw else default_state_dir() / "jobs"

    extra_roots = [Path(p).expanduser() for p in os.environ.get("SERPENT_EXTRA_ROOTS", "").split(os.pathsep) if p.strip()]

    settings = Settings(
        workspace=ws,
        exe=exe,
        exe_source=exe_source,
        data_dirs=data_dirs,
        acelib=acelib,
        declib=declib,
        nfylib=nfylib,
        backend=backend,
        ssh=ssh,
        omp=omp,
        mpi_launcher=os.environ.get("SERPENT_MPI_LAUNCHER") or run_sec.get("mpi_launcher"),
        job_timeout=job_timeout,
        jobs_dir=jobs_dir,
        docs_url=os.environ.get("SERPENT_DOCS_URL") or docs_sec.get("base_url", "https://serpent.vtt.fi/docs"),
        docs_auto_sync=_bool(os.environ.get("SERPENT_DOCS_AUTO_SYNC"), _bool(docs_sec.get("auto_sync"), True)),
        docs_max_age_days=int(docs_sec.get("max_age_days", 30)),
        lang=(os.environ.get("SERPENT_LANG") or ui_sec.get("lang", "ru")).lower()[:2],
        allow_outside=_bool(os.environ.get("SERPENT_ALLOW_OUTSIDE"), False),
        extra_allowed_roots=extra_roots,
        config_file=config_file,
    )
    return settings
