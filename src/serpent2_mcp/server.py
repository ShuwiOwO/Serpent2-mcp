"""MCP server entry point: tools, instructions and lifecycle.

Tool names are intentionally short; MCP clients that namespace tools by server
(e.g. OpenCode) expose them as ``serpent_<tool>``.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import __version__
from .compat import Server
from .config import Settings, load_settings
from .knowledge import reference
from .knowledge.store import Store, normalize_card_name
from .knowledge.sync import (
    db_path,
    ensure_sync_async,
    load_static_cards,
    seed_reference,
    seed_store_cards,
    sync,
    sync_status,
)
from .lint import Index, lint_path, lint_text
from .lint.model import Issue
from .results import outputs as results_outputs
from .results import plots
from .runner import datadl
from .runner.jobs import Job, Jobs
from .runner.probe import convert_option_style, probe_cached, resolve_executable
from .util import human_size, now_iso, run_capture, stderr_log, truncate

INSTRUCTIONS = """\
Serpent 2 is a continuous-energy 3-D Monte Carlo particle transport code (VTT).
Input files are input cards; a card is delimited by the NEXT CARD NAME, not by
lines, so one card may span many lines. Comments: `%` and `/* */`. Card names
are case-insensitive.

Working rules:
1. Read the user's task literally. If they provide a reference/previous-task
   file or an exact method (geometry, source, response, normalisation), open
   those files and follow them exactly — do not substitute another method.
2. Never guess syntax: call get_card for every card/parameter you are not
   certain about (e.g. sg, sb, srad, de, dr, ene), and search_docs when the
   meaning is unclear. get_reference has the curated summary.
3. Validate before running (validate_input; level 3 runs `sss2 --norun`) and
   smoke-test small inputs before long runs. Long runs are background jobs:
   run -> job_status/job_output -> job_kill; never wait synchronously.
4. Verify every run: get_results for _res.m (TOT_SRCRATE, NORM_COEF, k-eff),
   _det*.m detectors and _gsrc.m/_nsrc.m for decay sources (their `tot` is the
   emission rate for set srcrate). If a detector is empty or the source rate
   is zero, fix the input instead of changing the method.
5. Respect the installed version: get_environment reports it; old versions use
   single-dash CLI flags (handled automatically) and some syntax differs.

Minimal external-source input: set title; surf; cell; mat; src ...; set nps N;
set acelib "data.xsdata". Criticality replaces src/set nps with set pop
NPG NGEN NSKIP. Decay source: `src NAME p sg DMAT MODE` plus set declib (and
set nfylib for spontaneous-fission neutrons); emitting nuclides carry decay
data (ZAI or element form without library suffix). Pre-defined energy grids:
`ene NAME 4 scale44`; special detector responses: negative dr numbers, -100
NAME needs a fun card. Library data lives under xsdata/ with the stable names
data.xsdata / data.dec / data.nfy.
"""

class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.index = self._build_index(settings)
        self.jobs = Jobs(settings.jobs_dir)

    @staticmethod
    def _build_index(settings: Settings) -> Index:
        try:
            store = Store(db_path(settings))
            seed_store_cards(store)
            seed_reference(store)
            index = Index.from_store(store)
            store.close()
            return index
        except Exception as exc:  # noqa: BLE001
            stderr_log(f"using bundled card index ({exc})")
            return Index.from_static()

    def open_store(self) -> Store:
        store = Store(db_path(self.settings))
        seed_store_cards(store)
        seed_reference(store)
        return store


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _severity_badge(severity: str) -> str:
    return {"error": "ERROR", "warning": "WARN", "info": "INFO"}.get(severity, severity.upper())


def format_issues(issues: list[Issue], file_hint: str = "") -> str:
    if not issues:
        return "No issues found by the static checks."
    lines: list[str] = []
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    lines.append(
        f"Static check: {counts.get('error', 0)} error(s), {counts.get('warning', 0)} warning(s), {counts.get('info', 0)} info"
    )
    for issue in issues:
        location = f"{issue.file}:{issue.line}"
        lines.append(f"- [{_severity_badge(issue.severity)}] {location}: {issue.message}" + (f" — {issue.hint}" if issue.hint else ""))
    if file_hint:
        lines.append(file_hint)
    return "\n".join(lines)


def _job_summary(job: Job, jobs: Jobs) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "job_id": job.id,
        "kind": job.kind,
        "state": job.state,
        "backend": job.backend,
        "command": job.display_command,
        "cwd": job.cwd,
        "log_file": job.log_file,
        "pid": job.pid,
        "started": job.started,
        "finished": job.finished,
        "exit_code": job.exit_code,
        "meta": job.meta or {},
    }
    progress = jobs.progress(job)
    if progress:
        summary["progress"] = progress
    if job.error:
        summary["error"] = job.error
    return summary


def _load_static_card(name: str) -> dict[str, Any] | None:
    payload = load_static_cards()
    normalized, kind = normalize_card_name(name)
    for card in payload.get("cards", []):
        if card["name"] == normalized and (kind is None or card["kind"] == kind):
            return card
    return None


def _all_card_names() -> list[str]:
    payload = load_static_cards()
    names = []
    for card in payload.get("cards", []):
        names.append(f"set {card['name']}" if card["kind"] == "set" else card["name"])
    return names


def _primer_path(filename: str) -> Path:
    return Path(__file__).with_name("knowledge") / filename


def _primer() -> str:
    try:
        return _primer_path("primer.md").read_text(encoding="utf-8")
    except OSError:
        return "Primer not found in the installation."


def _section_from_markdown(text: str, topic: str) -> str | None:
    pattern = re.compile(r"^##+\s*(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    topic_lower = topic.lower()
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        if topic_lower in title.lower():
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            return text[match.start():end].strip()
    for index, match in enumerate(matches):
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():body_end]
        if topic_lower in body.lower():
            return text[match.start():body_end].strip()
    return None


def _require_allowed(settings: Settings, path: Path) -> None:
    if not settings.is_allowed(path):
        raise ValueError(
            f"path '{path}' is outside the allowed roots. Set SERPENT_ALLOW_OUTSIDE=1 or SERPENT_EXTRA_ROOTS to allow it."
        )


def _rel_to(settings: Settings, path: str | Path) -> str:
    """Path relative to the workspace root (where sss2 is usually run from).

    Falls back to the absolute path when it is outside the workspace.
    """
    try:
        target = Path(path).resolve()
        relative = os.path.relpath(str(target), str(settings.workspace.resolve()))
        if not relative.startswith(".."):
            return relative
        return str(target)
    except (OSError, ValueError):
        return str(path)


def _data_role(path: Path) -> str:
    name = path.name.lower()
    if name == "mcplib.xsdata":
        return "photon directory file"
    if name.endswith(".xsdata"):
        if "+" in name:
            return "variant directory file (special cases)"
        if name == "data.xsdata":
            return "main directory file (stable alias)"
        return "neutron/mixed directory file"
    if name.endswith(".dec"):
        return "radioactive decay data"
    if name.endswith(".nfy"):
        return "neutron-induced fission yields"
    if name.endswith(".bra"):
        return "isomeric branching ratios"
    return "data"


def _parse_serpent_errors(text: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    pattern = re.compile(
        r'Input error in parameter "([^"]*)" on line (\d+) in file "([^"]*)":\s*\n?\s*([^\n]*)',
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        errors.append(
            {
                "type": "input-error",
                "parameter": match.group(1),
                "line": int(match.group(2)),
                "file": match.group(3),
                "message": match.group(4).strip(),
            }
        )
    fatal = re.compile(r"Fatal error in function ([A-Za-z0-9_]+):\s*\n?\s*([^\n]*)")
    for match in fatal.finditer(text):
        errors.append(
            {"type": "fatal-error", "function": match.group(1), "message": match.group(2).strip()}
        )
    return errors


# ---------------------------------------------------------------------------
# Server construction
# ---------------------------------------------------------------------------


def create_server(settings: Settings) -> Server:
    app = App(settings)
    server = Server(
        name="serpent2-mcp",
        instructions=INSTRUCTIONS,
        version=__version__,
    )

    # -- environment -------------------------------------------------------

    @server.tool(
        description=(
            "Show detected Serpent executable, version, CLI flag style, data libraries, "
            "server configuration and documentation cache status. Call this first on a new machine "
            "or when a run fails with 'sss2 not found'."
        )
    )
    def get_environment(refresh: bool = False) -> str:
        s = app.settings
        probe = probe_cached(s, refresh)
        docs = sync_status(s)
        data_files: list[dict[str, Any]] = []
        input_hints: list[str] = []

        def _add_hint(hint: str) -> None:
            if hint not in input_hints:
                input_hints.append(hint)

        for directory in s.data_dirs:
            for pattern in ("*.xsdata", "*.dec", "*.nfy", "*.bra"):
                for path in sorted(directory.glob(pattern)):
                    try:
                        size = path.stat().st_size
                    except OSError:
                        size = 0
                    relative = _rel_to(s, path)
                    data_files.append(
                        {
                            "path": str(path),
                            "relative": relative,
                            "size": human_size(size),
                            "role": _data_role(path),
                        }
                    )
            for hint in datadl.input_lines(directory, rel_root=s.workspace):
                _add_hint(hint)
            photon_dir_candidate = directory / "photon_data"
            if photon_dir_candidate.is_dir():
                _add_hint(f'set pdatadir "{_rel_to(s, photon_dir_candidate)}"')
        warnings: list[str] = []
        if not probe.get("found"):
            warnings.append(
                "sss2 executable not found. Put ./sss2 in the workspace, add it to PATH, or set SERPENT_EXE."
            )
        version = str(probe.get("version") or "")
        if probe.get("is_beta") or version.startswith(("1.", "2.0", "2.1")):
            warnings.append(
                f"Legacy Serpent detected ({version or 'unknown version'}): the online docs describe 2.2.5. "
                "Card syntax is taken from the matching documentation where possible; verify uncommon "
                "cards with get_card and validate with sss2 -norun."
            )

        photon_dir = s.workspace / "photon_libraries"
        photon_ace: list[dict[str, Any]] = []
        if photon_dir.is_dir():
            for path in sorted(photon_dir.iterdir()):
                try:
                    if path.is_file() and path.name.lower().startswith(("mcplib", "mcp")):
                        photon_ace.append({"path": str(path), "size": human_size(path.stat().st_size)})
                except OSError:
                    continue
        photon_installed: list[str] = []
        for directory in s.data_dirs:
            for name in ("mcplib.xsdata", "mcplib84"):
                for candidate in sorted(directory.rglob(name)):
                    if candidate.is_file():
                        photon_installed.append(str(candidate))
            photon_data_dir = directory / "photon_data"
            if photon_data_dir.is_dir():
                photon_installed.append(str(photon_data_dir))
        has_mcplib_ace = any(Path(path).name == "mcplib84" for path in photon_installed)
        if photon_ace and not has_mcplib_ace:
            warnings.append(
                "Local mcplib84 ACE file found in photon_libraries but not installed; "
                "call install_photon_data to copy it and patch mcplib.xsdata."
            )

        payload = {
            "server_version": __version__,
            "workspace": str(s.workspace),
            "config": s.to_public_dict(),
            "executable": probe,
            "docs": docs,
            "data_files": data_files[:80],
            "paths_relative_to": str(s.workspace),
            "input_hints": input_hints[:20],
            "photon": {
                "source_dir": str(photon_dir),
                "ace_candidates": photon_ace,
                "installed": photon_installed,
            },
            "warnings": warnings,
            "time": now_iso(),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    # -- knowledge ---------------------------------------------------------

    @server.tool(
        description=(
            "Return the curated Serpent 2 quick reference (modes, geometry, materials, sources, "
            "detectors, burnup, group constants, CLI options, output files, pitfalls). Optionally "
            "request one topic (e.g. 'geometry', 'burnup', 'source', 'versions')."
        )
    )
    def get_reference(topic: str | None = None) -> str:
        text = _primer()
        if topic:
            topic_lower = topic.lower()
            if "energy" in topic_lower and "structure" in topic_lower:
                return (
                    "Pre-defined energy group structures for ene type 4.\n"
                    "Usage: ene NAME 4 <structure> (or <structure>_ext for full energy range).\n"
                    "They cannot be used directly in detectors; redefine them with an ene card.\n\n"
                    + reference.structures_text(limit=200)
                )
            if "version" in topic_lower or "отличи" in topic_lower:
                diffs = _primer_path("version_diffs.md").read_text(encoding="utf-8")
                section = _section_from_markdown(diffs, topic) if topic_lower not in {"versions", "version"} else diffs
                return truncate(section or diffs, 20000)
            section = _section_from_markdown(text, topic)
            if section:
                return truncate(section, 20000)
            return (
                f"No section matching '{topic}'. Available topics:\n"
                + "\n".join(re.findall(r"^##+\s*(.+)$", text, re.MULTILINE))
            )
        return truncate(text, 30000)

    @server.tool(
        description=(
            "Full-text search across the indexed official Serpent documentation (syntax manual, "
            "user guide, appendices, wiki). kind: all|card|guide|extra|wiki. Returns matching "
            "sections with source links."
        )
    )
    def search_docs(query: str, kind: str = "all", limit: int = 8) -> str:
        store = app.open_store()
        try:
            if not store.is_ready():
                card = _load_static_card(query)
                names = difflib.get_close_matches(query.lower(), [n.lower() for n in _all_card_names()], n=5)
                extra = (
                    f"\nClosest card names: {', '.join(names)}" if names else ""
                )
                if card:
                    return json.dumps({"note": "docs cache not ready; static card index used", "card": card}, indent=2, ensure_ascii=False)
                return (
                    "The documentation cache is not ready yet (first sync may be running). "
                    "Use get_card for syntax; retry search_docs in a moment." + extra
                )
            results = store.search(query, kind=kind, limit=max(1, min(limit, 25)))
            if not results:
                names = difflib.get_close_matches(query.lower(), [n.lower() for n in _all_card_names()], n=5)
                return json.dumps(
                    {"query": query, "results": [], "closest_cards": names}, indent=2, ensure_ascii=False
                )
            payload = [
                {
                    "title": item["title"] or item["section"],
                    "doc": item["doc"],
                    "url": item["url"],
                    "snippet": item["snippet"],
                }
                for item in results
            ]
            return json.dumps({"query": query, "results": payload}, indent=2, ensure_ascii=False)
        finally:
            store.close()

    @server.tool(
        description=(
            "Get the exact syntax, parameter list, notes and documentation link for a Serpent input "
            "card or set option. Examples: 'surf', 'mat', 'src', 'set acelib', 'acelib', 'sb'."
        )
    )
    def get_card(name: str) -> str:
        card = None
        try:
            store = app.open_store()
            try:
                card = store.get_card(name)
            finally:
                store.close()
        except Exception:  # noqa: BLE001
            card = None
        if card is None:
            card = _load_static_card(name)
        if card is None:
            # Parameter lookup: e.g. get_card("sg") -> the src card that uses it.
            target = normalize_card_name(name)[0]
            for key, params in app.index.params.items():
                if target in params:
                    kind, _, card_name = key.partition(":")
                    parent = {"name": card_name or key, "kind": kind or "card"}
                    return json.dumps(
                        {
                            "requested": name,
                            "resolved_as": "parameter",
                            "card": parent["name"],
                            "kind": parent["kind"],
                            "note": f"'{name}' is a parameter of the {parent['kind']} '{parent['name']}'. "
                            f"Call get_card('{parent['name']}') for the full syntax.",
                            "legacy_note": reference.legacy_note(target),
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
            names = difflib.get_close_matches(
                target, [n.lower() for n in _all_card_names()], n=6
            )
            hint = f" Did you mean: {', '.join(names)}?" if names else ""
            return f"Card '{name}' was not found.{hint}"
        if card.get("syntax") is None and card.get("params"):
            card["syntax"] = ""
        note = reference.legacy_note(card.get("name", ""))
        if note:
            card["legacy_note"] = note
        if card.get("kind") == "card" and card.get("name") == "ene":
            card["predefined_structures"] = reference.structures_text(limit=200)
        return json.dumps(card, indent=2, ensure_ascii=False)

    @server.tool(
        description=(
            "List the pre-defined energy group structures available for the ene card "
            "(name, number of groups, description; '_ext' variants span all energies)."
        )
    )
    def list_energy_structures() -> str:
        return json.dumps(
            {"structures": reference.structures(), "usage": "ene NAME 4 <structure>"},
            indent=2,
            ensure_ascii=False,
        )

    @server.tool(
        description=(
            "List all known Serpent input cards and set options, optionally filtered by kind "
            "(card|set|all). Useful for discovery when the exact name is unknown."
        )
    )
    def list_cards(kind: str = "all") -> str:
        store = app.open_store()
        try:
            cards = store.cards(kind if kind in {"card", "set"} else None)
        finally:
            store.close()
        payload = [
            {
                "name": card["name"],
                "kind": card["kind"],
                "description": re.sub(r"\s+", " ", card["notes"] or "").strip()[:120],
            }
            for card in cards
        ]
        return json.dumps({"count": len(payload), "cards": payload}, indent=2, ensure_ascii=False)

    @server.tool(
        description=(
            "List bundled Serpent input examples (pin cell, shielding, burnup, group constants, "
            "minimal sphere). With topic, return the best matching example content."
        )
    )
    def get_examples(topic: str | None = None) -> str:
        example_dir = _primer_path("examples")
        files = sorted(example_dir.glob("*.inp")) if example_dir.is_dir() else []
        if not files:
            return "No bundled examples found."
        if not topic:
            listing = []
            for path in files:
                first_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:2]
                title = next((line for line in first_lines if "set title" in line), "")
                listing.append({"file": path.name, "title": title.strip()})
            return json.dumps({"examples": listing}, indent=2, ensure_ascii=False)
        topic_lower = topic.lower()
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            if topic_lower in path.name.lower() or topic_lower in text.lower():
                return text
        return json.dumps(
            {"error": f"no example matches '{topic}'", "available": [p.name for p in files]},
            indent=2,
            ensure_ascii=False,
        )

    @server.tool(
        description=(
            "Trigger or refresh the download/index of the official Serpent documentation cache "
            "(runs in the background). Returns current sync status."
        )
    )
    def sync_docs(force: bool = False) -> str:
        ensure_sync_async(app.settings, force=force)
        return json.dumps(sync_status(app.settings), indent=2, ensure_ascii=False)

    # -- validation --------------------------------------------------------

    @server.tool(
        description=(
            "Statically validate a Serpent input file (and its includes): known cards/options, "
            "duplicate names, undefined surface/material/cell/universe references, material unit "
            "mixing, source/neutron-mode consistency and more. level=3 (or run_norun=true) also runs "
            "`sss2 -noplot -norun` when the executable is available and parses its exact input errors."
        )
    )
    def validate_input(
        input: str | None = None,
        text: str | None = None,
        level: int = 2,
        run_norun: bool = False,
    ) -> str:
        if not input and not text:
            return "Provide either 'input' (path) or 'text' (input file content)."
        level = max(1, min(int(level or 2), 3))
        issues: list[Issue] = []
        files: list[str] = []
        path: Path | None = None
        if input:
            path = app.settings.resolve(input)
            if not path.is_file():
                return f"Input file not found: {path}"
            try:
                _require_allowed(app.settings, path)
            except ValueError as exc:
                return str(exc)
            issues, files = lint_path(path, app.index, app.settings.workspace)
        else:
            issues = lint_text(text or "", filename="<text>", index=app.index)
            files = ["<text>"]

        result: dict[str, Any] = {
            "files": files,
            "counts": {
                "error": sum(1 for i in issues if i.severity == "error"),
                "warning": sum(1 for i in issues if i.severity == "warning"),
                "info": sum(1 for i in issues if i.severity == "info"),
            },
            "issues": [issue.to_dict() for issue in issues],
        }

        wants_run = run_norun or level >= 3
        if wants_run:
            if text is not None and path is None:
                tmp_dir = app.settings.jobs_dir / f"validate-{uuid.uuid4().hex[:8]}"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                path = tmp_dir / "validate.inp"
                path.write_text(text, encoding="utf-8")
            assert path is not None
            run_result = _run_norun(app.settings, path)
            result["serpent_check"] = run_result

        summary = format_issues(issues)
        return summary + "\n\n```json\n" + json.dumps(result, indent=2, ensure_ascii=False) + "\n```"

    # -- runs --------------------------------------------------------------

    @server.tool(
        description=(
            "Start a Serpent calculation as a background job and return its job id (long runs must "
            "not block). By default the input is statically validated first; pass force=true to skip. "
            "options: extra CLI flags, e.g. ['--noplot']. omp/mpi_tasks are convenience shortcuts."
        )
    )
    def run(
        input: str,
        workdir: str | None = None,
        options: list[str] | None = None,
        omp: int | None = None,
        mpi_tasks: int | None = None,
        backend: str | None = None,
        validate_first: bool = True,
        force: bool = False,
    ) -> str:
        s = app.settings
        path = s.resolve(input)
        if not path.is_file():
            return f"Input file not found: {path}"
        try:
            _require_allowed(s, path)
        except ValueError as exc:
            return str(exc)
        wd = s.resolve(workdir) if workdir else path.parent
        if not wd.is_dir():
            return f"Working directory not found: {wd}"
        try:
            _require_allowed(s, wd)
        except ValueError as exc:
            return str(exc)

        if validate_first:
            issues, _files = lint_path(path, app.index, s.workspace)
            errors = [i for i in issues if i.severity == "error"]
            if errors and not force:
                return (
                    "Refusing to run: static validation found errors. Fix them, or pass force=true.\n\n"
                    + format_issues(errors)
                )

        use_backend = (backend or s.backend or "local").lower()
        input_arg = path.name if wd.resolve() == path.parent.resolve() else str(path)
        exe = resolve_executable(s.exe)

        if use_backend == "ssh":
            if s.ssh is None:
                return "SSH backend selected but SERPENT_SSH_HOST is not configured."
            # On the remote host only the command name/path is meaningful.
            exe_name = Path(str(s.exe)).name if s.exe else "sss2"
            if not workdir and s.ssh.workdir:
                remote_wd = s.ssh.workdir
                input_arg = path.name
            else:
                remote_wd = str(wd)
            argv = _build_argv(s, [str(exe_name)], input_arg, options, omp, mpi_tasks)
            job = app.jobs.start_ssh("run", s, argv, remote_wd, meta={"input": str(path)})
        else:
            if exe is None:
                return (
                    "Serpent executable not found. Put ./sss2 in the workspace, add it to PATH, "
                    "or set SERPENT_EXE. See get_environment."
                )
            argv = _build_argv(s, [str(exe)], input_arg, options, omp, mpi_tasks)
            job = app.jobs.start_local("run", argv, wd, meta={"input": str(path)})

        if s.job_timeout and s.job_timeout > 0 and job.state == "running":
            threading.Thread(
                target=_watchdog,
                args=(app.jobs, job.id, s.job_timeout),
                daemon=True,
                name=f"watchdog-{job.id}",
            ).start()
        return json.dumps(_job_summary(job, app.jobs), indent=2, ensure_ascii=False)

    @server.tool(
        description=(
            "Check background job state (running/finished/failed/lost), exit code, progress and "
            "recent log output. Without job_id, list the most recent jobs."
        )
    )
    def job_status(job_id: str | None = None, tail: int = 2500) -> str:
        if not job_id:
            jobs = [app.jobs.refresh(job) for job in app.jobs.list(20)]
            payload = [_job_summary(job, app.jobs) for job in jobs]
            return json.dumps({"jobs": payload}, indent=2, ensure_ascii=False)
        job = app.jobs.get(job_id)
        if job is None:
            return f"Unknown job id: {job_id}"
        job = app.jobs.refresh(job)
        payload = _job_summary(job, app.jobs)
        output = app.jobs.output(job, tail_chars=max(0, tail))
        payload["log_tail"] = output
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @server.tool(description="Read more log output from a background job (tail of the run log).")
    def job_output(job_id: str, tail_chars: int = 8000) -> str:
        job = app.jobs.get(job_id)
        if job is None:
            return f"Unknown job id: {job_id}"
        job = app.jobs.refresh(job)
        return app.jobs.output(job, tail_chars=max(100, min(int(tail_chars or 8000), 200000)))

    @server.tool(description="Terminate a running background job (SIGTERM, then SIGKILL for local jobs).")
    def job_kill(job_id: str) -> str:
        job = app.jobs.get(job_id)
        if job is None:
            return f"Unknown job id: {job_id}"
        job = app.jobs.refresh(job)
        if job.state in {"finished", "failed"}:
            return f"Job {job_id} already {job.state} (exit code {job.exit_code})."
        job = app.jobs.kill(job)
        return json.dumps(_job_summary(job, app.jobs), indent=2, ensure_ascii=False)

    # -- results -----------------------------------------------------------

    @server.tool(
        description=(
            "Read and summarise Serpent output files. Defaults to the newest _res.m in the workdir; "
            "returns k-eff estimates, run parameters, integral rates and optionally detector/depletion "
            "summaries. Use variables=[...] to extract specific _res.m variables."
        )
    )
    def get_results(
        workdir: str | None = None,
        input: str | None = None,
        file: str | None = None,
        variables: list[str] | None = None,
        sections: list[str] | None = None,
        max_rows: int = 60,
    ) -> str:
        s = app.settings
        wd = s.resolve(workdir) if workdir else s.workspace
        try:
            _require_allowed(s, wd)
        except ValueError as exc:
            return str(exc)
        wanted = set(sections) if sections else {"res", "det", "dep", "source"}

        res_path: Path | None = None
        det_path: Path | None = None
        dep_path: Path | None = None
        source_paths: list[Path] = []
        if file:
            candidate = s.resolve(file)
            if not candidate.is_file():
                return f"File not found: {candidate}"
            if candidate.name.endswith("_det.m") or re.search(r"_det\d+.*\.m$", candidate.name):
                det_path = candidate
            elif candidate.name.endswith("_dep.m"):
                dep_path = candidate
            else:
                res_path = candidate
        else:
            if not input:
                candidates = sorted(wd.glob("*_res.m"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not candidates:
                    return f"No *_res.m files found in {wd}. Pass input= or file= explicitly."
                res_path = candidates[0]
                input = res_path.name[: -len("_res.m")]
            found = results_outputs.find_outputs(wd, input or "")
            if not res_path and found["res"]:
                res_path = found["res"][0]
            if found["det"]:
                det_path = found["det"][0]
            if found["dep"]:
                dep_path = found["dep"][0]
            source_paths = found.get("source", [])

        result: dict[str, Any] = {"workdir": str(wd)}
        if "res" in wanted and res_path is not None:
            res = results_outputs.read_res(res_path)
            result["res_file"] = str(res_path)
            result["summary"] = results_outputs.summarize_res(res)
            if variables:
                extracted: dict[str, Any] = {}
                for name in variables:
                    value = res.get(name)
                    if value is None:
                        continue
                    rows = value.rows()
                    if value.kind == "string":
                        extracted[name] = value.value
                    elif rows and len(rows) == 1 and len(rows[0]) == 1:
                        extracted[name] = rows[0][0]
                    else:
                        extracted[name] = rows[: max(1, min(int(max_rows or 60), 500))]
                result["variables"] = extracted
        if "det" in wanted and det_path is not None:
            info: dict[str, Any] = {}
            det = results_outputs.read_det(det_path, info=info)
            summary = results_outputs.summarize_det(det)
            result["det_file"] = str(det_path)
            result["detectors"] = summary["detectors"]
            if info.get("streamed"):
                result["detector_parse"] = {
                    "streamed": True,
                    "file_size": info.get("file_size"),
                    "truncated_variables": info.get("truncated", []),
                    "max_rows": 500,
                    "note": "large detector file: values are capped; use plot_results for spectra",
                }
        if "dep" in wanted and dep_path is not None:
            dep = results_outputs.read_dep(dep_path)
            result["dep_file"] = str(dep_path)
            result["depletion"] = results_outputs.summarize_dep(dep)
        if "source" in wanted and source_paths:
            result["source_file"] = str(source_paths[0])
            result["source_emission"] = results_outputs.summarize_source_files(source_paths)
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)

    @server.tool(
        description=(
            "Draw a PNG plot from Serpent output. kind: detector (needs name), keff (k-eff per step), "
            "burnup (BU vs DAYS from _dep.m), variables (needs x and y variable names). "
            "Returns the path of the written image."
        )
    )
    def plot_results(
        kind: str,
        workdir: str | None = None,
        input: str | None = None,
        file: str | None = None,
        name: str | None = None,
        x: str | None = None,
        y: str | None = None,
        output: str | None = None,
        lang: str | None = None,
    ) -> str:
        if not plots.available():
            return "matplotlib is not installed. Run ./setup.sh (or pip install 'serpent2-mcp[plots]')."
        s = app.settings
        wd = s.resolve(workdir) if workdir else s.workspace
        language = lang or s.lang
        kind = (kind or "").lower()

        def resolve_source() -> Path:
            if file:
                candidate = s.resolve(file)
                if not candidate.is_file():
                    raise FileNotFoundError(f"file not found: {candidate}")
                return candidate
            if kind == "detector":
                candidates = sorted(wd.glob("*_det*.m"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not candidates:
                    raise FileNotFoundError(f"no *_det*.m files in {wd}")
                return candidates[0]
            if kind == "burnup":
                candidates = sorted(wd.glob("*_dep.m"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not candidates:
                    raise FileNotFoundError(f"no *_dep.m files in {wd}")
                return candidates[0]
            candidates = sorted(wd.glob("*_res.m"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                raise FileNotFoundError(f"no *_res.m files in {wd}")
            return candidates[0]

        try:
            source = resolve_source()
            stem = source.name.split("_")[0]
            if kind == "detector":
                if not name:
                    return "kind='detector' requires name=<detector identifier>."
                out = Path(output) if output else wd / f"{stem}_det_{name}.png"
                path = plots.plot_detector(source, name, out, lang=language)
            elif kind == "keff":
                out = Path(output) if output else wd / f"{stem}_keff.png"
                path = plots.plot_keff(source, out, lang=language)
            elif kind == "burnup":
                out = Path(output) if output else wd / f"{stem}_burnup.png"
                path = plots.plot_dep_burnup(source, out, lang=language)
            elif kind == "variables":
                if not x or not y:
                    return "kind='variables' requires x=<var> and y=<var>."
                out = Path(output) if output else wd / f"{stem}_{y}_vs_{x}.png"
                path = plots.plot_variables(source, x, y, out, lang=language)
            else:
                return "kind must be one of: detector, keff, burnup, variables."
        except Exception as exc:  # noqa: BLE001
            return f"Plot failed: {exc}"
        size = path.stat().st_size if path.is_file() else 0
        return json.dumps({"plot": str(path), "size": human_size(size), "kind": kind}, indent=2)

    # -- data libraries ----------------------------------------------------

    @server.tool(
        description=(
            "List the official VTT Serpent nuclear data libraries that can be downloaded "
            "(ENDF/B-VII.1, JEFF-3.2, JENDL-4.0, FENDL-3.0, decay/fission-yield/photon data). "
            "Each entry has key, title, size, URL and file name."
        )
    )
    def list_data_libraries() -> str:
        return json.dumps({"libraries": datadl.catalog()}, indent=2, ensure_ascii=False)

    @server.tool(
        description=(
            "Start a background download of a Serpent data library into a local directory "
            "(resumable, extracts tar.gz; multi-GB transfers report progress via job_status). "
            "The download runs on THIS machine (the one hosting the MCP server). Use name from "
            "list_data_libraries, or an explicit url."
        )
    )
    def download_data_library(
        name: str | None = None,
        url: str | None = None,
        dest: str | None = None,
        filename: str | None = None,
        extract: bool | None = None,
        force_reextract: bool = False,
    ) -> str:
        s = app.settings
        if not name and not url:
            return "Provide name (catalog key) or url."
        entry = datadl.find_entry(name) if name else None
        if name and entry is None:
            return f"Unknown library '{name}'. Use list_data_libraries to see valid keys."
        if entry is not None and entry.manual:
            payload = {
                "manual": True,
                "library": entry.to_dict(),
                "message": entry.note,
                "next_steps": [
                    f"1. Download the mcplib84 ACE data file from {entry.homepage}",
                    "2. Put it into <workspace>/photon_libraries/ (or pass ace_source to install_photon_data)",
                    "3. Call install_photon_data: it downloads mcplib.xsdata and photon_data.tar.gz "
                    "from https://serpent.vtt.fi/repository/photon_data/, copies the ACE file and fixes "
                    "the paths inside mcplib.xsdata",
                    '4. In the input: set acelib "data.xsdata" "mcplib.xsdata" and '
                    'set pdatadir "<data_dir>/photon_data"',
                    "Do not commit LANL/RSICC data to a public repository.",
                ],
            }
            return json.dumps(payload, indent=2, ensure_ascii=False)
        if dest:
            dest_path = s.resolve(dest)
        elif s.data_dirs:
            dest_path = s.data_dirs[0]
        else:
            dest_path = s.workspace / "xsdata"
        try:
            _require_allowed(s, dest_path)
        except ValueError as exc:
            return str(exc)
        dest_path.mkdir(parents=True, exist_ok=True)
        argv = [
            sys.executable,
            "-m",
            "serpent2_mcp.runner.datadl",
            "download",
            "--dest",
            str(dest_path),
        ]
        if entry is not None:
            argv += ["--name", entry.key]
            do_extract = entry.extract if extract is None else extract
            if not do_extract:
                argv.append("--no-extract")
            elif entry.kind == "xsdata":
                # Patch '/xs/data/' paths inside the extracted directory files.
                argv += ["--patch", "--rel-root", str(s.workspace)]
        else:
            argv += ["--url", str(url)]
            if filename:
                argv += ["--filename", filename]
            if extract is False:
                argv.append("--no-extract")
        if force_reextract:
            argv.append("--force")
        job = app.jobs.start_local(
            "download",
            argv,
            dest_path,
            meta={"library": name or url, "dest": str(dest_path)},
        )
        summary = _job_summary(job, app.jobs)
        summary["note"] = (
            "Data is downloaded on the machine running the MCP server. "
            "For remote runs, copy/extract the data on the target host or use a shared mount."
        )
        summary["dest_relative"] = _rel_to(s, dest_path)
        summary["paths_relative_to"] = str(s.workspace)
        if entry is not None:
            rel_dir = _rel_to(s, dest_path)
            if entry.kind == "xsdata" and entry.extract:
                summary["use_in_input_hint"] = f'set acelib "{rel_dir}/data.xsdata"'
            elif entry.kind == "decay":
                setter = "set declib" if entry.filename.endswith(".dec") else "set nfylib"
                summary["use_in_input_hint"] = f'{setter} "{rel_dir}/{entry.filename}"'
            elif entry.kind == "photon" and entry.extract:
                summary["use_in_input_hint"] = f'set pdatadir "{rel_dir}/photon_data"'
        return json.dumps(summary, indent=2, ensure_ascii=False)

    @server.tool(
        description=(
            "Install photon transport data: downloads mcplib.xsdata and photon_data.tar.gz from "
            "https://serpent.vtt.fi/repository/photon_data/ (background, resumable) and rewrites the "
            "ACE path inside mcplib.xsdata relative to the workspace root. mcplib84 is usually "
            "already present in the extracted xsdata tree (acedata/mcplib84) and is used in place; "
            "it can also be provided via ace_file, ace_source (default <workspace>/photon_libraries) "
            "or ace_url. Missing mcplib84 is reported explicitly."
        )
    )
    def install_photon_data(
        dest: str | None = None,
        ace_source: str | None = None,
        ace_file: str | None = None,
        ace_url: str | None = None,
    ) -> str:
        s = app.settings
        if dest:
            dest_path = s.resolve(dest)
        elif s.data_dirs:
            dest_path = s.data_dirs[0]
        else:
            dest_path = s.workspace / "xsdata"
        try:
            _require_allowed(s, dest_path)
        except ValueError as exc:
            return str(exc)
        dest_path.mkdir(parents=True, exist_ok=True)
        source = s.resolve(ace_source) if ace_source else (s.workspace / "photon_libraries")
        argv = [
            sys.executable,
            "-m",
            "serpent2_mcp.runner.datadl",
            "photon",
            "--dest",
            str(dest_path),
            "--ace-source",
            str(source),
            "--rel-root",
            str(s.workspace),
            "--base-url",
            s.data_repo,
        ]
        if ace_file:
            candidate = s.resolve(ace_file)
            if not candidate.is_file():
                return f"ace_file not found: {candidate}"
            argv += ["--ace-file", str(candidate)]
        if ace_url:
            argv += ["--ace-url", str(ace_url)]
        job = app.jobs.start_local(
            "download",
            argv,
            dest_path,
            meta={
                "library": "photon",
                "dest": str(dest_path),
                "dest_relative": _rel_to(s, dest_path),
                "ace_source": str(source),
            },
        )
        summary = _job_summary(job, app.jobs)
        summary["paths_relative_to"] = str(s.workspace)
        summary["note"] = (
            "VTT files are downloaded automatically. mcplib84 is normally shipped inside the Serpent "
            "xsdata packages as acedata/mcplib84 and is used in place; only if it is missing you need "
            f"{datadl.CATALOG_BY_KEY['mcplib84'].homepage} or ace_file=/ace_url=. "
            "Paths inside mcplib.xsdata are written relative to the workspace root (or set SERPENT_DATA). "
            "Never publish LANL/RSICC data in a public repository."
        )
        return json.dumps(summary, indent=2, ensure_ascii=False)

    @server.tool(
        description=(
            "Check (and by default repair) the data file paths inside *.xsdata directory files of a "
            "data directory. VTT directory files reference data files under '/xs/data/'; this tool "
            "finds each referenced file by name inside the directory (for example "
            "xsdata/acedata/mcplib84), rewrites the entry and returns statistics. Paths are written "
            "relative to the workspace root when possible. Use apply=false for a dry run. Reports "
            "missing files so that incomplete data sets are visible immediately."
        )
    )
    def check_data_paths(directory: str | None = None, apply: bool = True, relative: bool = False) -> str:
        s = app.settings
        target = s.resolve(directory) if directory else (s.data_dirs[0] if s.data_dirs else s.workspace / "xsdata")
        try:
            _require_allowed(s, target)
        except ValueError as exc:
            return str(exc)
        if not target.is_dir():
            return f"Directory not found: {target}"
        stats = datadl.patch_xsdata_files(
            target, rel_root=str(s.workspace), apply=apply, relative=relative, log=stderr_log
        )
        stats["paths_relative_to"] = str(s.workspace)
        return json.dumps(stats, indent=2, ensure_ascii=False)

    @server.tool(
        description=(
            "One-call data setup for a fresh machine: downloads and extracts a neutron data package "
            "(neutron: endfb71|jeff32|jendl40|fendl30; ACE + decay + fission yields), the thermal "
            "scattering library (sss_thxs), the ENDF/B-VII decay/yield files used by older decks "
            "(sss_endfb7.dec/nfy) and the photon data. Rewrites every '/xs/data/' path inside the "
            "extracted *.xsdata files to absolute local paths, adds stable aliases "
            "(data.xsdata/data.dec/data.nfy) and natural-element aliases, and returns ready-to-paste "
            "set lines. Runs as a background job (6-8 GB): follow with job_status. mcplib84 photon "
            "ACE data is LANL/RSICC licensed and cannot be downloaded automatically: on a partial "
            "result see manual_download or call mcplib84_instructions."
        )
    )
    def setup_data(
        neutron: str = "endfb71",
        dest: str | None = None,
        with_photon: bool = True,
        with_thxs: bool = True,
        with_other_data: bool = True,
        ace_file: str | None = None,
        ace_url: str | None = None,
    ) -> str:
        s = app.settings
        if dest:
            dest_path = s.resolve(dest)
        elif s.data_dirs:
            dest_path = s.data_dirs[0]
        else:
            dest_path = s.workspace / "xsdata"
        try:
            _require_allowed(s, dest_path)
        except ValueError as exc:
            return str(exc)
        if datadl.find_entry(neutron) is None:
            return f"Unknown neutron library '{neutron}'. Use endfb71, jeff32, jendl40 or fendl30."
        dest_path.mkdir(parents=True, exist_ok=True)
        argv = [
            sys.executable,
            "-m",
            "serpent2_mcp.runner.datadl",
            "setup",
            "--neutron",
            neutron,
            "--dest",
            str(dest_path),
            "--rel-root",
            str(s.workspace),
            "--base-url",
            s.data_repo,
        ]
        if not with_photon:
            argv.append("--no-photon")
        if not with_thxs:
            argv.append("--no-thxs")
        if not with_other_data:
            argv.append("--no-other-data")
        if ace_file:
            candidate = s.resolve(ace_file)
            if not candidate.is_file():
                return f"ace_file not found: {candidate}"
            argv += ["--ace-file", str(candidate)]
        if ace_url:
            argv += ["--ace-url", str(ace_url)]
        job = app.jobs.start_local(
            "download",
            argv,
            dest_path,
            meta={"neutron": neutron, "dest": str(dest_path), "dest_relative": _rel_to(s, dest_path), "with_photon": with_photon},
        )
        summary = _job_summary(job, app.jobs)
        summary["paths_relative_to"] = str(s.workspace)
        summary["note"] = (
            "Large download (6-8 GB); poll job_status. When finished, use the 'use_in_input' lines "
            "from the job progress/output, or call get_environment. Directory files reference "
            "absolute paths; input hints are relative to the workspace root."
        )
        return json.dumps(summary, indent=2, ensure_ascii=False)

    @server.tool(
        description=(
            "Explain which data file still has to be downloaded manually and exactly where to put "
            "it. Currently the only such file is mcplib84 (MCPLIB84 photon ACE data, LANL/RSICC "
            "licensed, not redistributable). The tool checks whether the file is already present in "
            "the data directory and returns the download URL, the exact target path, how to verify "
            "the file and what to run next."
        )
    )
    def mcplib84_instructions(dest: str | None = None) -> str:
        s = app.settings
        if dest:
            dest_path = s.resolve(dest)
        elif s.data_dirs:
            dest_path = s.data_dirs[0]
        else:
            dest_path = s.workspace / "xsdata"
        target = dest_path / "mcplib84"
        alternative_dir = s.workspace / "photon_libraries"
        found = datadl.find_ace_file(dest_path, extra_dirs=[alternative_dir])
        alternative_dir = s.workspace / "photon_libraries"
        payload: dict[str, Any] = {
            "file": "mcplib84",
            "description": "MCPLIB84 photon ACE cross sections (.84p), needed for photon transport only",
            "why_manual": (
                "It is LANL/RSICC data under US export-control/licensing terms and is not "
                "redistributed with this server or by VTT."
            ),
            "download_url": datadl.CATALOG_BY_KEY["mcplib84"].homepage,
            "place_file_at": _rel_to(s, target),
            "absolute_path": str(target),
            "alternative": {
                "directory": _rel_to(s, alternative_dir),
                "then": "re-run install_photon_data or setup_data",
            },
            "verify": "file starts with '  1000.84p' and is about 15 MB",
            "then": "run check_data_paths (or install_photon_data) to wire it into the directory files",
        }
        if found is not None:
            payload["status"] = "already present"
            payload["found_at"] = str(found)
            payload["message"] = (
                "mcplib84 is already available; no manual download is needed. "
                "Run check_data_paths to make sure the directory files point to it."
            )
        else:
            payload["status"] = "missing"
            payload["message"] = (
                f"Download the file from {payload['download_url']} and save it as "
                f"'{payload['place_file_at']}' (absolute: {target}). Then run "
                "install_photon_data or check_data_paths again."
            )
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @server.tool(
        description=(
            "Validate the installed Serpent executable and data: repairs stale relative paths in "
            "*.xsdata, builds a minimal -norun input from the installed directory/decay/yield files, "
            "runs `sss2 -noplot -norun` and reports the version, the exact set lines used, any input "
            "errors and missing referenced data files. Fast (seconds), safe (no transport)."
        )
    )
    def selfcheck(directory: str | None = None) -> str:
        s = app.settings
        target = s.resolve(directory) if directory else (s.data_dirs[0] if s.data_dirs else s.workspace / "xsdata")
        try:
            _require_allowed(s, target)
        except ValueError as exc:
            return str(exc)
        report = datadl.selfcheck(s.exe, target, log=stderr_log)
        return json.dumps(report, indent=2, ensure_ascii=False)

    # -- MCP resources (best effort; clients differ in support) ------------

    try:

        @server.resource(
            "serpent://card/{name}",
            description="Serpent input card or set option syntax",
        )
        def card_resource(name: str) -> str:
            return get_card(name)

    except Exception:  # noqa: BLE001 - resource API differs across SDK versions
        pass

    return server


def _watchdog(jobs: Jobs, job_id: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        job = jobs.get(job_id)
        if job is None or jobs.refresh(job).state != "running":
            return
        time.sleep(5)
    job = jobs.get(job_id)
    if job is not None and jobs.refresh(job).state == "running":
        jobs.kill(job)
        stderr_log(f"job {job_id} killed after timeout ({timeout_seconds}s)")


def _build_argv(
    settings: Settings,
    exe_argv: list[str],
    input_arg: str,
    options: list[str] | None,
    omp: int | None,
    mpi_tasks: int | None,
) -> list[str]:
    probe = probe_cached(settings)
    style = probe.get("flag_style", "double")
    argv: list[str] = []
    if mpi_tasks and mpi_tasks > 1:
        launcher = settings.mpi_launcher or "mpirun -np {n}"
        argv += [part.replace("{n}", str(int(mpi_tasks))) for part in shlex.split(launcher)]
    argv += list(exe_argv)
    argv.append(input_arg)
    if omp:
        argv.append(convert_option_style("--omp", style))
        argv.append(str(int(omp)))
    for option in options or []:
        for part in shlex.split(str(option)):
            argv.append(convert_option_style(part, style))
    return argv


def _run_norun(settings: Settings, path: Path) -> dict[str, Any]:
    if settings.backend == "ssh":
        return {
            "ran": False,
            "reason": "level-3 check is not available over the SSH backend; run validate on the remote host",
        }
    exe = resolve_executable(settings.exe)
    if exe is None:
        return {
            "ran": False,
            "reason": "sss2 not found; static checks only. See get_environment.",
        }
    probe = probe_cached(settings)
    style = probe.get("flag_style", "double")
    flags = [
        convert_option_style("--noplot", style),
        convert_option_style("--norun", style),
    ]
    argv = [str(exe), path.name, *flags]
    started = time.time()
    rc, out, err = run_capture(argv, timeout=240, cwd=path.parent)
    text = f"{out}\n{err}"
    parsed = _parse_serpent_errors(text)
    tail = text[-6000:]
    return {
        "ran": True,
        "command": " ".join(shlex.quote(part) for part in argv),
        "exit_code": rc,
        "elapsed_seconds": round(time.time() - started, 2),
        "errors": parsed,
        "log_tail": tail if (parsed or rc != 0) else tail[-1500:],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serpent 2 MCP server")
    parser.add_argument("--workspace", default=None, help="workspace directory (default: cwd)")
    parser.add_argument("--sync-docs", action="store_true", help="sync the documentation cache and exit")
    parser.add_argument("--status", action="store_true", help="print environment/status and exit")
    parser.add_argument("--version", action="version", version=f"serpent2-mcp {__version__}")
    args, _unknown = parser.parse_known_args(argv)

    settings = load_settings(args.workspace)

    if args.sync_docs:
        result = sync(settings, force=True)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    if args.status:
        payload = {
            "server_version": __version__,
            "config": settings.to_public_dict(),
            "probe": probe_cached(settings),
            "docs": sync_status(settings),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return

    stderr_log(
        f"start version={__version__} workspace={settings.workspace} "
        f"exe={settings.exe or '(not found)'} backend={settings.backend}"
    )
    if settings.docs_auto_sync:
        ensure_sync_async(settings)
    server = create_server(settings)
    server.run(transport="stdio")


if __name__ == "__main__":
    main(sys.argv[1:])
