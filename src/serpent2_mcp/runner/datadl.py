"""Nuclear data library catalog and resumable background downloads.

The libraries are distributed publicly by VTT at serpent.vtt.fi/repository.
Downloads run as ordinary background jobs (see jobs.py), so multi-GB transfers
never block the MCP session.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from ..util import USER_AGENT, human_size, run_capture

REPO = "https://serpent.vtt.fi/repository"


@dataclass
class DataLibrary:
    key: str
    title: str
    url: str
    size_bytes: int | None
    kind: str  # xsdata | decay | photon | misc | manual
    extract: bool
    note: str = ""
    manual: bool = False
    homepage: str = ""

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1] if self.url else ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["filename"] = self.filename
        data["size_human"] = human_size(self.size_bytes)
        return data


CATALOG: list[DataLibrary] = [
    DataLibrary(
        "endfb71",
        "Serpent 2 xsdata — ENDF/B-VII.1 (0K…1800K; recommended default)",
        f"{REPO}/Serpent_2_xsdata/s2v0_endfb71.tar.gz",
        7_116_693_776,
        "xsdata",
        True,
        "Directory file data.xsdata; includes decay/fission-yield data.",
    ),
    DataLibrary(
        "jeff32",
        "Serpent 2 xsdata — JEFF-3.2",
        f"{REPO}/Serpent_2_xsdata/s2v0_jeff32.tar.gz",
        7_886_497_260,
        "xsdata",
        True,
    ),
    DataLibrary(
        "jendl40",
        "Serpent 2 xsdata — JENDL-4.0",
        f"{REPO}/Serpent_2_xsdata/s2v0_jendl40.tar.gz",
        6_612_916_648,
        "xsdata",
        True,
    ),
    DataLibrary(
        "fendl30",
        "Serpent 2 xsdata — FENDL-3.0 rev.4 (fusion)",
        f"{REPO}/Serpent_2_xsdata/s2v0_fendl30.tar.gz",
        7_727_224_107,
        "xsdata",
        True,
    ),
    DataLibrary(
        "thxs",
        "Thermal scattering libraries (S(alpha,beta))",
        f"{REPO}/Serpent_2_xsdata/sss_thxs.tar.gz",
        95_346_291,
        "xsdata",
        True,
    ),
    DataLibrary(
        "endfb71_edep",
        "ENDF/B-VII.1 special-purpose library for energy deposition",
        f"{REPO}/Serpent_2_xsdata/endfb71_edep.tar.gz",
        4_044_461_674,
        "xsdata",
        True,
    ),
    DataLibrary(
        "sss_endfb7.dec",
        "Radioactive decay data — ENDF/B-VII",
        f"{REPO}/other_data/sss_endfb7.dec",
        36_499_734,
        "decay",
        False,
    ),
    DataLibrary(
        "sss_endfb7.nfy",
        "Neutron-induced fission yields — ENDF/B-VII",
        f"{REPO}/other_data/sss_endfb7.nfy",
        6_921_538,
        "decay",
        False,
    ),
    DataLibrary(
        "s2v0_jeff311.dec",
        "Radioactive decay data — JEFF-3.1.1 (closest VTT-hosted match to the JEFF-3.x decay files used by older decks)",
        f"{REPO}/other_data/s2v0_jeff311.dec",
        41_898_222,
        "decay",
        False,
    ),
    DataLibrary(
        "s2v0_jeff311.nfy",
        "Neutron-induced fission yields — JEFF-3.1.1",
        f"{REPO}/other_data/s2v0_jeff311.nfy",
        4_292_514,
        "decay",
        False,
    ),
    DataLibrary(
        "s2v0_endfb71.dec",
        "Radioactive decay data — ENDF/B-VII.1",
        f"{REPO}/other_data/s2v0_endfb71.dec",
        68_162_391,
        "decay",
        False,
    ),
    DataLibrary(
        "s2v0_endfb71.nfy",
        "Neutron-induced fission yields — ENDF/B-VII.1",
        f"{REPO}/other_data/s2v0_endfb71.nfy",
        7_061_742,
        "decay",
        False,
    ),
    DataLibrary(
        "photon_data",
        "Photon physics data for 'set pdatadir' (VTT photon_data.tar.gz)",
        f"{REPO}/photon_data/photon_data.tar.gz",
        7_750_353,
        "photon",
        True,
        "Extracts into a 'photon_data' directory; use set pdatadir.",
    ),
    DataLibrary(
        "photon_xsdata",
        "mcplib84 directory file in Serpent format (VTT)",
        f"{REPO}/photon_data/mcplib.xsdata",
        14_800,
        "photon",
        False,
        "Directory file only. The ACE data file 'mcplib84' comes from LANL; "
        "place it in photon_libraries/ and run install_photon_data to copy it "
        "and fix the file paths inside this directory file.",
    ),
    DataLibrary(
        "mcplib84",
        "MCPLIB84 photon ACE data — normally already included in the Serpent xsdata packages (acedata/mcplib84)",
        "",
        None,
        "manual",
        False,
        "Used in place when found under the data directory (e.g. acedata/mcplib84). "
        "Only if it is missing: download from the LANL nuclear data site, put the 'mcplib84' "
        "file into photon_libraries/, or pass ace_file=/ace_url= to install_photon_data. "
        "Do not publish LANL/RSICC data.",
        manual=True,
        homepage="https://nucleardata.lanl.gov/ace/mcplib84/",
    ),
    DataLibrary(
        "jeff40.xsdata",
        "Correction/updated directory file for JEFF-4.0",
        f"{REPO}/misc/jeff40.xsdata",
        712_957,
        "misc",
        False,
    ),
    DataLibrary(
        "endfb81.xsdata",
        "Correction/updated directory file for ENDF/B-VIII.1",
        f"{REPO}/misc/endfb81.xsdata",
        721_200,
        "misc",
        False,
    ),
    DataLibrary(
        "jendl5.xsdata",
        "Correction/updated directory file for JENDL-5",
        f"{REPO}/misc/jendl5.xsdata",
        759_321,
        "misc",
        False,
    ),
    DataLibrary(
        "fendl32c.xsdata",
        "Correction/updated directory file for FENDL-3.2c",
        f"{REPO}/misc/fendl32c.xsdata",
        28_122,
        "misc",
        False,
    ),
]

CATALOG_BY_KEY = {entry.key: entry for entry in CATALOG}

# Human-friendly aliases (evaluation names as users say them).
ALIASES = {
    "endf": "endfb71",
    "endfb71": "endfb71",
    "endf/b-vii.1": "endfb71",
    "endf-b-vii.1": "endfb71",
    "endf71": "endfb71",
    "sss_endfb7": "sss_endfb7.dec",
    "jef3": "s2v0_jeff311.dec",
    "jef-3": "s2v0_jeff311.dec",
    "jeff-3.1.1 decay": "s2v0_jeff311.dec",
    "jeff311": "s2v0_jeff311.dec",
    "jeff": "jeff32",
    "jeff-3.2": "jeff32",
    "jeff32": "jeff32",
    "jeff-3.1.1": "jeff32",
    "jendl": "jendl40",
    "jendl-4.0": "jendl40",
    "jendl4": "jendl40",
    "jendl40": "jendl40",
    "fendl": "fendl30",
    "fendl-3.0": "fendl30",
    "fendl30": "fendl30",
    "thermal": "thxs",
    "thxs": "thxs",
    "photon": "photon_data",
    "photon data": "photon_data",
    "photon-data": "photon_data",
    "photon libraries": "photon_data",
    "photon physics": "photon_data",
    "pdatadir": "photon_data",
    "photon xsdata": "photon_xsdata",
    "photon-xsdata": "photon_xsdata",
    "mcplib.xsdata": "photon_xsdata",
    "mcplib-xsdata": "photon_xsdata",
    "mcplib": "mcplib84",
    "mcplib84": "mcplib84",
    "mcplib63": "mcplib84",
    "mcnp photon": "mcplib84",
    "energy-deposition": "endfb71_edep",
    "edep": "endfb71_edep",
}


def catalog() -> list[dict]:
    return [entry.to_dict() for entry in CATALOG]


def find_entry(name: str | None) -> DataLibrary | None:
    """Resolve a catalog key, an alias, or a unique substring/title match."""
    if not name:
        return None
    key = name.strip().lower()
    if key in CATALOG_BY_KEY:
        return CATALOG_BY_KEY[key]
    if key in ALIASES:
        return CATALOG_BY_KEY.get(ALIASES[key])
    matches = [
        entry
        for entry in CATALOG
        if key in entry.key.lower() or key in entry.title.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _progress(payload: dict) -> None:
    path = os.environ.get("SERPENT_PROGRESS_FILE") or "progress.json"
    try:
        Path(path).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Terminal progress bar
# ---------------------------------------------------------------------------

_BAR_FULL = "█"
_BAR_EMPTY = "░"
LOG_LINE_INTERVAL = 10.0  # seconds between log lines when no progress bar is drawn


def _format_eta(seconds: float | None) -> str:
    if seconds is None or seconds != seconds or seconds < 0:
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


class DownloadProgress:
    """Single-line progress bar with speed and ETA.

    Drawn only when the output stream is a TTY (or when explicitly enabled);
    otherwise the caller keeps its compact periodic log lines, which is what
    the MCP background-job logs want.
    """

    def __init__(
        self,
        label: str,
        total: int | None,
        stream=None,
        enabled: bool | None = None,
        width: int = 24,
        min_interval: float = 0.15,
    ):
        self.label = label
        self.total = total or None
        self.stream = stream if stream is not None else sys.stdout
        self.width = width
        self.min_interval = min_interval
        self.start = time.time()
        self._last = 0.0
        self._done = 0
        self._closed = False
        self._lock = threading.Lock()
        try:
            self.enabled = bool(enabled) if enabled is not None else bool(self.stream.isatty())
            _BAR_FULL.encode(self.stream.encoding or "utf-8")
        except (AttributeError, UnicodeEncodeError):
            self.enabled = False

    def _render(self, now: float) -> str:
        elapsed = max(now - self.start, 1e-6)
        rate = self._done / elapsed
        label = self.label if len(self.label) <= 28 else self.label[:27] + "…"
        if self.total:
            fraction = min(max(self._done / self.total, 0.0), 1.0)
            filled = int(fraction * self.width)
            bar = _BAR_FULL * filled + _BAR_EMPTY * (self.width - filled)
            eta = _format_eta((self.total - self._done) / rate if rate > 0 else None)
            return (
                f"{label}: [{bar}] {fraction * 100:5.1f}%  "
                f"{human_size(self._done)}/{human_size(self.total)}  "
                f"{human_size(rate)}/s  ETA {eta}"
            )
        return f"{label}: {human_size(self._done)}  {human_size(rate)}/s"

    def update(self, done: int) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._closed:
                return
            self._done = done
            now = time.time()
            if now - self._last < self.min_interval:
                return
            self._last = now
            try:
                self.stream.write("\r" + self._render(now))
                self.stream.flush()
            except (OSError, ValueError):
                self.enabled = False

    def close(self) -> None:
        if not self.enabled or self._closed:
            return
        with self._lock:
            self._closed = True
            try:
                self.stream.write("\r" + self._render(time.time()) + "\n")
                self.stream.flush()
            except (OSError, ValueError):
                pass


# ---------------------------------------------------------------------------
# Downloading (single stream with resume)
# ---------------------------------------------------------------------------

def _download_stream(
    url: str,
    part: Path,
    resume: bool,
    filename: str,
    log,
    label: str,
    show_progress: bool | None,
) -> None:
    pos = part.stat().st_size if resume and part.exists() else 0
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if pos:
        headers["Range"] = f"bytes={pos}-"
        log(f"resuming {filename} at {human_size(pos)}")
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        status = getattr(response, "status", 200)
        if status != 206:
            pos = 0
        total = pos + int(response.headers.get("Content-Length") or 0)
        mode = "ab" if pos and part.exists() else "wb"
        bar = DownloadProgress(label, total, enabled=show_progress)
        last_progress = 0.0
        last_line = 0.0
        with part.open(mode) as handle:
            while True:
                block = response.read(1 << 22)
                if not block:
                    break
                handle.write(block)
                pos += len(block)
                now = time.time()
                bar.update(pos)
                if now - last_progress > 2.0:
                    last_progress = now
                    _progress({"state": "downloading", "file": filename, "downloaded": pos, "total": total})
                if not bar.enabled and now - last_line > LOG_LINE_INTERVAL:
                    last_line = now
                    if total:
                        log(f"{filename}: {human_size(pos)} / {human_size(total)} ({100.0 * pos / total:.1f}%)")
                    else:
                        log(f"{filename}: {human_size(pos)}")
        bar.close()


def _apply_repo_mirror(url: str) -> str:
    """Rewrite VTT repository URLs to SERPENT_DATA_REPO_URL when configured."""
    mirror = (os.environ.get("SERPENT_DATA_REPO_URL") or "").rstrip("/")
    if mirror and url.startswith(REPO):
        return mirror + url[len(REPO):]
    return url


def download(
    url: str,
    dest: str | Path,
    filename: str | None = None,
    extract: bool = False,
    resume: bool = True,
    force: bool = False,
    patch: bool = False,
    rel_root: str | Path | None = None,
    relative_paths: bool = False,
    label: str | None = None,
    show_progress: bool | None = None,
    log=print,
) -> Path:
    url = _apply_repo_mirror(url)
    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    filename = filename or url.rsplit("/", 1)[-1]
    label = label or filename
    target = dest / filename
    if target.is_file() and target.stat().st_size > 0:
        log(f"already present: {target} ({human_size(target.stat().st_size)})")
        payload = {
            "state": "done",
            "file": filename,
            "downloaded": target.stat().st_size,
            "total": target.stat().st_size,
            "path": str(target),
        }
        _progress(payload)
        if extract and force:
            _extract(target, dest, log)
            payload["state"] = "extracted"
            payload["dest"] = str(dest)
            _progress(payload)
        if extract and patch:
            payload["patch"] = patch_xsdata_files(dest, rel_root=rel_root, relative=relative_paths, log=log)
            _progress(payload)
        return target

    part = target.with_name(target.name + ".part")
    _download_stream(url, part, resume, filename, log, label, show_progress)

    if part.exists():
        os.replace(part, target)
    log(f"downloaded {target} ({human_size(target.stat().st_size)})")
    final: dict = {
        "state": "done",
        "file": filename,
        "downloaded": target.stat().st_size,
        "total": target.stat().st_size,
        "path": str(target),
    }
    _progress(final)
    if extract:
        _extract(target, dest, log)
        final["state"] = "extracted"
        final["dest"] = str(dest)
        if patch:
            final["patch"] = patch_xsdata_files(dest, rel_root=rel_root, relative=relative_paths, log=log)
        _progress(final)
    return target


def _extract(archive: Path, dest: Path, log=print) -> None:
    if not tarfile.is_tarfile(archive):
        return
    log(f"extracting {archive.name} into {dest} ...")
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(dest, filter="data")  # type: ignore[call-arg]
        except TypeError:  # pragma: no cover - Python < 3.12
            tar.extractall(dest)
    log("extraction complete")


# ---------------------------------------------------------------------------
# Photon transport data
# ---------------------------------------------------------------------------

MCPLIB_ACE_PREFIXES = ("mcplib84", "mcp84")
MCPLIB_MIN_ACE_SIZE = 1_000_000  # guard against picking up directory files


def find_ace_file(source: str | Path | None, extra_dirs: list[str | Path] | None = None) -> Path | None:
    """Locate a local mcplib84 ACE file.

    Explicit files are accepted directly; directories are searched recursively
    (so a file inside ``xsdata/acedata/`` is found). Directories and tiny files
    such as the 14 kB ``mcplib.xsdata`` index are ignored.
    """
    dirs: list[Path] = []
    if source:
        path = Path(source).expanduser()
        if path.is_file():
            return path if "mcplib" in path.name.lower() else None
        dirs.append(path)
    for extra in extra_dirs or []:
        dirs.append(Path(extra).expanduser())
    for directory in dirs:
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.rglob("*")):
            try:
                if not candidate.is_file():
                    continue
                if (
                    candidate.name.lower().startswith(MCPLIB_ACE_PREFIXES)
                    and candidate.suffix != ".xsdata"
                    and candidate.stat().st_size > MCPLIB_MIN_ACE_SIZE
                ):
                    return candidate
            except OSError:
                continue
    return None


def patch_directory_file(directory_file: Path, ace_path: str | Path) -> int:
    """Point every entry of a Serpent directory file at the local ACE file."""
    ace_text = str(ace_path)
    lines = directory_file.read_text(encoding="utf-8", errors="replace").splitlines()
    patched = 0
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "%")):
            output.append(line)
            continue
        head = stripped.rsplit(None, 1)[0]
        output.append(f"{head} {ace_text}")
        patched += 1
    directory_file.write_text("\n".join(output) + "\n", encoding="utf-8")
    return patched


def _rel_path(target: Path, rel_root: str | Path | None) -> str:
    """Return a path relative to rel_root (workspace).

    Paths that would have to escape the root (``..``) are returned as absolute
    paths instead of awkward relative ones.
    """
    target_abs = Path(os.path.abspath(str(target)))
    if rel_root:
        try:
            root_abs = Path(os.path.abspath(str(Path(rel_root).expanduser())))
            relative = os.path.relpath(target_abs, root_abs)
            if not relative.startswith(".."):
                return relative
        except (OSError, ValueError):
            pass
    return str(target_abs)


def _build_file_index(directory: Path, skip_suffixes: tuple[str, ...] = (".xsdata",)) -> dict[str, Path]:
    """Map basename -> path for every data file under a directory."""
    index: dict[str, Path] = {}
    for root, _dirs, names in os.walk(directory):
        for name in names:
            if name.endswith(skip_suffixes):
                continue
            index.setdefault(name, Path(root) / name)
    return index


def patch_xsdata_files(
    directory: str | Path,
    rel_root: str | Path | None = None,
    apply: bool = True,
    relative: bool = False,
    log=print,
) -> dict:
    """Rewrite data file paths inside every *.xsdata directory file.

    VTT directory files reference the data files under '/xs/data/'. This
    function finds each referenced file by its base name inside ``directory``
    and rewrites the entry to the local absolute path (or relative to
    ``rel_root`` when ``relative=True``). Entries whose data files are missing
    are left untouched and reported. With ``apply=False`` nothing is written
    (dry run).
    """
    directory = Path(directory).expanduser()
    index = _build_file_index(directory)
    stats: dict = {
        "directory": str(directory),
        "applied": apply,
        "absolute": not relative,
        "files": 0,
        "entries": 0,
        "patched": 0,
        "missing": [],
    }
    for xsdata in sorted(directory.rglob("*.xsdata")):
        lines = xsdata.read_text(encoding="utf-8", errors="replace").splitlines()
        output: list[str] = []
        changed = 0
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "%")):
                output.append(line)
                continue
            stats["entries"] += 1
            head, _sep, old_path = stripped.rpartition(" ")
            if not head:
                output.append(line)
                continue
            base = Path(old_path).name
            target = index.get(base)
            if target is None:
                if base not in stats["missing"]:
                    stats["missing"].append(base)
                output.append(line)
                continue
            new_path = _rel_path(target, rel_root) if relative else str(target.resolve())
            if new_path != old_path:
                changed += 1
            output.append(f"{head} {new_path}")
        if changed:
            stats["files"] += 1
            stats["patched"] += changed
            if apply:
                xsdata.write_text("\n".join(output) + "\n", encoding="utf-8")
                log(f"patched {changed} entries in {xsdata}")
    if stats["missing"]:
        log(f"missing data files referenced by directory files: {len(stats['missing'])}")
    return stats


PHOTON_DATA_EXPECTED = ("ComptonProfiles.dat", "cohff.dat", "deffcor.dat")


# ---------------------------------------------------------------------------
# Directory-file compatibility helpers
# ---------------------------------------------------------------------------

ELEMENT_SYMBOLS: dict[int, str] = {
    1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O", 9: "F", 10: "Ne",
    11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P", 16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca",
    21: "Sc", 22: "Ti", 23: "V", 24: "Cr", 25: "Mn", 26: "Fe", 27: "Co", 28: "Ni", 29: "Cu", 30: "Zn",
    31: "Ga", 32: "Ge", 33: "As", 34: "Se", 35: "Br", 36: "Kr", 37: "Rb", 38: "Sr", 39: "Y", 40: "Zr",
    41: "Nb", 42: "Mo", 43: "Tc", 44: "Ru", 45: "Rh", 46: "Pd", 47: "Ag", 48: "Cd", 49: "In", 50: "Sn",
    51: "Sb", 52: "Te", 53: "I", 54: "Xe", 55: "Cs", 56: "Ba", 57: "La", 58: "Ce", 59: "Pr", 60: "Nd",
    61: "Pm", 62: "Sm", 63: "Eu", 64: "Gd", 65: "Tb", 66: "Dy", 67: "Ho", 68: "Er", 69: "Tm", 70: "Yb",
    71: "Lu", 72: "Hf", 73: "Ta", 74: "W", 75: "Re", 76: "Os", 77: "Ir", 78: "Pt", 79: "Au", 80: "Hg",
    81: "Tl", 82: "Pb", 83: "Bi", 84: "Po", 85: "At", 86: "Rn", 87: "Fr", 88: "Ra", 89: "Ac", 90: "Th",
    91: "Pa", 92: "U", 93: "Np", 94: "Pu", 95: "Am", 96: "Cm", 97: "Bk", 98: "Cf", 99: "Es", 100: "Fm",
}


def add_natural_aliases(directory: str | Path, log=print) -> dict:
    """Add 'Element-nat.<lib>' aliases for natural (ZA = Z000) entries.

    Older user decks (and older Serpent distributions) refer to natural
    compositions as ``H-nat.84p`` or ``C-nat.03c``; some VTT directory files
    only contain the short alias ``H.84p``. The data itself is present either
    way -- this only adds the alternative spelling.
    """
    directory = Path(directory).expanduser()
    stats: dict = {"files": 0, "added": 0, "aliases": []}
    for xsdata in sorted(directory.rglob("*.xsdata")):
        lines = xsdata.read_text(encoding="utf-8", errors="replace").splitlines()
        names = {
            line.split()[0]
            for line in lines
            if line.strip() and not line.strip().startswith(("#", "%")) and len(line.split()) > 1
        }
        additions: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "%")):
                continue
            fields = stripped.split()
            if len(fields) < 3 or "." not in fields[1]:
                continue
            name = fields[0]
            base_za, _, lib = fields[1].partition(".")
            if not base_za.isdigit() or len(base_za) < 4:
                continue
            z, a = int(base_za[:-3]), int(base_za[-3:])
            if a != 0 or z not in ELEMENT_SYMBOLS:
                continue
            alias = f"{ELEMENT_SYMBOLS[z]}-nat.{lib}"
            if alias in names:
                continue
            additions.append(f"{alias}{stripped[len(name):]}")
            names.add(alias)
            stats["aliases"].append(alias)
        if additions:
            with xsdata.open("a", encoding="utf-8") as handle:
                if lines and lines[-1].strip():
                    handle.write("\n")
                handle.write("\n".join(additions) + "\n")
            stats["files"] += 1
            stats["added"] += len(additions)
            log(f"added {len(additions)} natural aliases to {xsdata.name}")
    return stats


def pick_main_xsdata(directory: str | Path) -> Path | None:
    """Best neutron/mixed directory file (never the photon-only mcplib)."""
    directory = Path(directory).expanduser()
    candidates = [
        path
        for path in directory.glob("*.xsdata")
        if "mcplib" not in path.name.lower() and "+" not in path.name
    ]
    if not candidates:
        candidates = [path for path in directory.glob("*.xsdata") if path.name.lower() != "mcplib.xsdata"]
    if not candidates:
        return None
    for path in candidates:
        if path.name == "data.xsdata":
            return path
    return max(candidates, key=lambda path: path.stat().st_size)


def _ensure_stable_names(directory: Path, log=print) -> dict:
    """Create stable aliases (data.xsdata / data.dec / data.nfy) if possible."""
    created: list[str] = []
    main = pick_main_xsdata(directory)
    for target, alias_name in (
        (main, "data.xsdata"),
        (_find_shallowest(directory, "sss_endfb7.dec") or _find_shallowest(directory, "*.dec"), "data.dec"),
        (_find_shallowest(directory, "sss_endfb7.nfy") or _find_shallowest(directory, "*.nfy"), "data.nfy"),
    ):
        if target is None:
            continue
        alias = directory / alias_name
        if alias.exists():
            continue
        try:
            os.symlink(target.name, alias)
            created.append(f"{alias_name} -> {target.name}")
        except OSError:
            shutil.copy2(target, alias)
            created.append(f"{alias_name} (copy of {target.name})")
    if created:
        log("stable names: " + ", ".join(created))
    return {"created": created}


def install_photon(
    dest: str | Path,
    ace_source: str | Path | None = None,
    ace_file: str | Path | None = None,
    ace_url: str | None = None,
    patch: bool = True,
    base_url: str = REPO,
    rel_root: str | Path | None = None,
    relative_paths: bool = False,
    log=print,
) -> dict:
    """Download VTT photon data and wire up a mcplib84 ACE file.

    Always downloads ``mcplib.xsdata`` and ``photon_data.tar.gz`` from the VTT
    repository and rewrites the ACE path inside the directory file. The ACE
    data (``mcplib84``) is frequently already present in the extracted Serpent
    xsdata tree (``<dest>/acedata/mcplib84``); it can also be supplied as a
    local file (``ace_file``), a directory to search (``ace_source``, default
    ``<workspace>/photon_libraries``) or a direct URL (``ace_url``). A file
    found inside ``dest`` is used in place; one found elsewhere is copied to
    ``<dest>/mcplib84``. Without it only the index and physics data are
    installed and the missing file is reported.
    """
    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    base_url = base_url.rstrip("/")
    log(f"downloading photon data from {base_url}/photon_data/ ...")
    xsdata = download(
        f"{base_url}/photon_data/mcplib.xsdata",
        dest,
        filename="mcplib.xsdata",
        extract=False,
        label="mcplib.xsdata directory file",
        log=log,
    )
    download(
        f"{base_url}/photon_data/photon_data.tar.gz",
        dest,
        filename="photon_data.tar.gz",
        extract=True,
        force=True,  # re-extract on repeated installs so a broken extraction self-heals
        label="photon physics data",
        log=log,
    )

    default_target = dest / "mcplib84"

    def _install(source: Path) -> Path:
        try:
            source.resolve().relative_to(dest.resolve())
            installed = source.resolve()  # already inside the data directory: use in place
        except ValueError:
            shutil.copy2(source, default_target)
            installed = default_target
        log(f"using ACE file: {installed} ({human_size(installed.stat().st_size)})")
        return installed

    ace_path: Path | None = None
    if ace_file:
        candidate = Path(ace_file).expanduser()
        if candidate.is_file():
            ace_path = _install(candidate)
        else:
            log(f"ace_file not found: {candidate}")
    if ace_path is None and ace_url:
        try:
            ace_path = _install(download(ace_url, dest, filename="mcplib84", extract=False, log=log))
        except Exception as exc:  # noqa: BLE001
            log(f"ACE download from {ace_url} failed: {exc}")
    if ace_path is None:
        found = find_ace_file(ace_source, extra_dirs=[dest])
        if found is not None:
            ace_path = _install(found)

    ace_installed = ace_path is not None
    # Write the path even if the ACE file is missing, so that placing the file
    # there later is enough (no re-run needed).
    ace_target = ace_path or default_target
    ace_in_file = _rel_path(ace_target, rel_root) if relative_paths else str(ace_target.resolve())
    patched = 0
    if patch:
        patched = patch_directory_file(xsdata, ace_in_file)
        log(f"patched {patched} path entries in {xsdata.name} -> {ace_in_file}")
    aliases = add_natural_aliases(dest, log=log)

    photon_dir = dest / "photon_data"
    extracted = sorted(p.name for p in photon_dir.iterdir()) if photon_dir.is_dir() else []
    missing = [name for name in PHOTON_DATA_EXPECTED if name not in extracted]

    acelib_entries = []
    for name in ("data.xsdata", "mcplib.xsdata"):
        candidate = dest / name
        if candidate.is_file():
            acelib_entries.append(f'"{_rel_path(candidate, rel_root)}"')
    use_in_input = []
    if acelib_entries:
        use_in_input.append("set acelib " + " ".join(acelib_entries))
    use_in_input.append(f'set pdatadir "{_rel_path(photon_dir, rel_root)}"')

    result: dict = {
        "state": "done" if ace_installed else "partial",
        "dest": str(dest),
        "relative_to": str(rel_root) if rel_root else None,
        "directory_file": str(xsdata),
        "directory_entries_patched": patched,
        "ace_path_in_directory_file": ace_in_file,
        "ace_file": str(ace_path) if ace_installed else None,
        "ace_size": ace_path.stat().st_size if ace_installed else 0,
        "ace_installed": ace_installed,
        "photon_data_dir": str(photon_dir),
        "photon_data_files": extracted[:30],
        "photon_data_missing": missing,
        "natural_aliases_added": aliases.get("added", 0),
        "use_in_input": use_in_input,
    }
    if ace_installed:
        result["acelib_hint"] = use_in_input[0] if use_in_input else ""
        result["note"] = (
            "Use paths relative to the directory where sss2 is started (workspace root). "
            "Alternatively set SERPENT_DATA to the absolute data directory."
        )
    else:
        manual_absolute = ace_path or default_target
        alternative = None
        if rel_root:
            alternative = str(Path("photon_libraries") / "mcplib84")
        result["message"] = (
            "Photon physics data and mcplib.xsdata installed, but the mcplib84 ACE file was not "
            "found, so photon transport will not run yet. It is normally shipped with the Serpent "
            "xsdata packages as acedata/mcplib84 (check the extracted data directory); otherwise "
            f"obtain it from {CATALOG_BY_KEY['mcplib84'].homepage} or another LANL/RSICC source and "
            "place it exactly at the path below, then re-run install_photon_data. "
            "Do not publish LANL/RSICC data."
        )
        result["manual_download"] = {
            "file": "mcplib84",
            "url": CATALOG_BY_KEY["mcplib84"].homepage,
            "save_as": ace_in_file,
            "absolute_path": str(manual_absolute),
            "alternative_location": alternative,
            "then": "re-run install_photon_data (or setup_data / check_data_paths) to verify",
            "verify": "the file is ~15 MB and starts with '  1000.84p'",
        }
        log(result["message"])
    _progress(result)
    return result


def _find_shallowest(directory: Path, pattern: str) -> Path | None:
    candidates = sorted(directory.rglob(pattern), key=lambda p: (len(p.parts), str(p)))
    return candidates[0] if candidates else None


def input_lines(dest: str | Path, rel_root: str | Path | None = None) -> list[str]:
    """Ready-to-paste set lines for the data installed in ``dest``.

    Prefers the stable aliases (data.xsdata / data.dec / data.nfy) so that the
    same lines work no matter which evaluation was downloaded.
    """
    dest = Path(dest).expanduser()

    def rel(path: Path) -> str:
        return _rel_path(path, rel_root)

    acelib: list[Path] = []
    for name in ("data.xsdata", "mcplib.xsdata"):
        candidate = dest / name
        if candidate.is_file():
            acelib.append(candidate)
    if not acelib:
        main = pick_main_xsdata(dest)
        if main is not None:
            acelib.append(main)
        photon = dest / "mcplib.xsdata"
        if photon.is_file():
            acelib.append(photon)

    lines: list[str] = []
    if acelib:
        lines.append("set acelib " + " ".join(f'"{rel(path)}"' for path in acelib))
    for name, pattern, option in (
        ("data.dec", "sss_endfb7.dec", "set declib"),
        ("data.nfy", "sss_endfb7.nfy", "set nfylib"),
    ):
        candidate = dest / name
        if not candidate.is_file():
            candidate = _find_shallowest(dest, pattern) or _find_shallowest(dest, f"*{pattern[3:]}")
        if candidate is not None:
            lines.append(f'{option} "{rel(candidate)}"')
    bra = _find_shallowest(dest, "*.bra")
    if bra is not None:
        lines.append(f'set bralib "{rel(bra)}"')
    photon_dir = dest / "photon_data"
    if photon_dir.is_dir():
        lines.append(f'set pdatadir "{rel(photon_dir)}"')
    return lines


def setup_data(
    dest: str | Path,
    neutron: str = "endfb71",
    with_photon: bool = True,
    with_thxs: bool = True,
    with_other_data: bool = True,
    base_url: str = REPO,
    rel_root: str | Path | None = None,
    ace_file: str | Path | None = None,
    ace_url: str | None = None,
    relative_paths: bool = False,
    log=print,
) -> dict:
    """Prepare a fresh data directory in one call.

    Downloads and extracts one neutron data package (ACE + decay + fission
    yields), the thermal scattering library, the ENDF/B-VII decay/yield files
    (the names used by older decks), patches all ``/xs/data/`` paths inside the
    extracted ``*.xsdata`` files to absolute local paths, adds stable aliases
    (``data.xsdata``/``data.dec``/``data.nfy``) and natural-element aliases,
    and optionally installs the photon data. Returns ready-to-paste input
    lines.
    """
    entry = find_entry(neutron)
    if entry is None or entry.manual:
        raise ValueError(f"unknown neutron library '{neutron}'")
    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    base_url = base_url.rstrip("/")

    def _package_url(item: DataLibrary) -> str:
        # A mirror keeps the repository layout below the base URL.
        return item.url if base_url == REPO.rstrip("/") else base_url + item.url[len(REPO):]

    log(f"[1/5] downloading neutron library '{entry.key}' ...")
    _progress({"state": "setup", "step": "neutron", "library": entry.key})
    download(
        _package_url(entry),
        dest,
        filename=entry.filename,
        extract=True,
        patch=True,
        rel_root=rel_root,
        relative_paths=relative_paths,
        label=f"{entry.key} neutron library",
        log=log,
    )

    thxs_entry = CATALOG_BY_KEY.get("thxs")
    if with_thxs and thxs_entry is not None:
        log("[2/5] downloading thermal scattering libraries ...")
        _progress({"state": "setup", "step": "thermal-scattering"})
        download(
            _package_url(thxs_entry),
            dest,
            filename=thxs_entry.filename,
            extract=True,
            patch=False,
            rel_root=rel_root,
            label="thermal scattering (sss_thxs)",
            log=log,
        )
    else:
        log("[2/5] thermal scattering libraries skipped")

    if with_other_data:
        log("[3/5] downloading ENDF/B-VII decay and fission-yield data ...")
        _progress({"state": "setup", "step": "other-data"})
        for key in ("sss_endfb7.dec", "sss_endfb7.nfy"):
            data_entry = CATALOG_BY_KEY.get(key)
            if data_entry is None:
                continue
            download(
                _package_url(data_entry),
                dest,
                filename=data_entry.filename,
                extract=False,
                label=f"{key} (legacy name)",
                log=log,
            )
    else:
        log("[3/5] decay/fission-yield files skipped")

    photon: dict | None = None
    if with_photon:
        log("[4/5] installing photon data ...")
        _progress({"state": "setup", "step": "photon"})
        photon = install_photon(
            dest,
            ace_file=ace_file,
            ace_url=ace_url,
            base_url=base_url,
            rel_root=rel_root,
            relative_paths=relative_paths,
            log=log,
        )
    else:
        log("[4/5] photon data skipped")

    log("[5/5] patching data paths and adding aliases ...")
    _progress({"state": "setup", "step": "patch"})
    patch_stats = patch_xsdata_files(dest, rel_root=rel_root, apply=True, relative=relative_paths, log=log)
    aliases = add_natural_aliases(dest, log=log)
    stable = _ensure_stable_names(dest, log=log)

    lines = input_lines(dest, rel_root=rel_root)
    installed = sorted(p.name for p in dest.iterdir())
    result: dict = {
        "state": "done" if not patch_stats["missing"] else "partial",
        "neutron": entry.key,
        "dest": str(dest),
        "relative_to": str(rel_root) if rel_root else None,
        "use_in_input": lines,
        "patch": patch_stats,
        "natural_aliases_added": aliases.get("added", 0),
        "stable_names": stable.get("created", []),
        "installed_top_level": installed[:50],
    }
    if with_thxs and thxs_entry is not None:
        result["thermal_scattering"] = thxs_entry.filename
    if photon is not None:
        result["photon"] = {
            "ace_installed": photon.get("ace_installed"),
            "ace_file": photon.get("ace_file"),
            "photon_data_missing": photon.get("photon_data_missing"),
            "manual_download": photon.get("manual_download"),
        }
    if patch_stats["missing"]:
        result["warning"] = (
            "Some files referenced by the directory files were not found: "
            + ", ".join(patch_stats["missing"][:10])
        )
        if "mcplib84" in patch_stats["missing"]:
            manual_target = dest / "mcplib84"
            result["warning"] += (
                ". Photon transport needs the mcplib84 ACE file (not shipped by VTT); "
                "download it from the URL below and place it exactly at "
                f"'{_rel_path(manual_target, rel_root)}', then re-run setup_data/install_photon_data."
            )
            result["manual_download"] = {
                "file": "mcplib84",
                "url": CATALOG_BY_KEY["mcplib84"].homepage,
                "save_as": _rel_path(manual_target, rel_root),
                "absolute_path": str(manual_target),
            }
            banner = [
                "",
                "=" * 74,
                "  ACTION REQUIRED for photon transport (neutrons already work)",
                "=" * 74,
                "  1. Download MCPLIB84 from:",
                f"       {CATALOG_BY_KEY['mcplib84'].homepage}",
                "  2. Save the file exactly as:",
                f"       {manual_target}",
                "  3. Verify: ~15 MB, first line starts with '  1000.84p'.",
                "  4. Re-run install_photon_data / setup_data (or check_data_paths).",
                "  Do not publish mcplib84: LANL/RSICC licensed data.",
                "=" * 74,
                "",
            ]
            for line in banner:
                log(line)
    _progress(result)
    log(f"setup complete: {result['state']}")
    return result


def _run_norun(exe: str, input_path: Path, workdir: Path) -> tuple[int, str, list[str]]:
    """Run `sss2 INPUT -noplot -norun`, trying single- and double-dash flags."""
    last: tuple[int, str, list[str]] = (127, "", [])
    for flags in (["-noplot", "-norun"], ["--noplot", "--norun"]):
        rc, out, err = run_capture([exe, input_path.name, *flags], timeout=180, cwd=workdir)
        text = f"{out}\n{err}"
        if "unknown command line option" in text.lower():
            last = (rc, text, flags)
            continue
        return rc, text, flags
    return last


def _missing_referenced(directory: Path, files: list[Path]) -> list[str]:
    """Data files referenced by the given directory files but not present."""
    index = _build_file_index(directory)
    missing: list[str] = []
    for xsdata in files:
        if not xsdata.is_file():
            continue
        for line in xsdata.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "%")):
                continue
            _head, _sep, path = stripped.rpartition(" ")
            base = Path(path).name
            if base and base not in index and base not in missing:
                missing.append(base)
    return missing

def selfcheck(exe: str | Path | None, data_dir: str | Path, workdir: str | Path | None = None, log=print) -> dict:
    """Validate that the executable and the installed data actually work.

    Builds a minimal external-source input referencing the installed directory
    files and runs ``sss2 -noplot -norun`` (input processing only, no
    transport). Returns a machine-readable report.
    """
    from .probe import resolve_executable  # local import to avoid cycles

    exe_path = resolve_executable(str(exe) if exe else None)
    data_dir = Path(data_dir).expanduser()
    if exe_path is None:
        return {"ok": False, "error": "sss2 executable not found"}
    # Repair stale relative paths before validating.
    repair = patch_xsdata_files(data_dir, apply=True)
    main = pick_main_xsdata(data_dir)
    if main is None:
        return {"ok": False, "error": f"no neutron directory file (*.xsdata) in {data_dir}"}
    dec = data_dir / "data.dec"
    if not dec.is_file():
        dec = _find_shallowest(data_dir, "sss_endfb7.dec") or _find_shallowest(data_dir, "*.dec")
    nfy = data_dir / "data.nfy"
    if not nfy.is_file():
        nfy = _find_shallowest(data_dir, "sss_endfb7.nfy") or _find_shallowest(data_dir, "*.nfy")
    photon_dir = data_dir / "photon_data"

    lines = [
        'set title "serpent2-mcp selfcheck"',
        "mat selfcheck_mat -1.0",
        "1001.03c 1.0",
        "surf 1 sph 0.0 0.0 0.0 1.0",
        "cell 1 0 selfcheck_mat -1",
        "cell 2 0 outside 1",
        "src 1 sp 0 0 0 se 1.0",
        "set nps 1000",
        f'set acelib "{main.resolve()}"',
    ]
    if dec is not None and dec.is_file():
        lines.append(f'set declib "{dec.resolve()}"')
    if nfy is not None and nfy.is_file():
        lines.append(f'set nfylib "{nfy.resolve()}"')
    if photon_dir.is_dir():
        lines.append(f'set pdatadir "{photon_dir.resolve()}"')

    tmpdir = Path(tempfile.mkdtemp(prefix="serpent-selfcheck-"))
    try:
        input_path = tmpdir / "selfcheck.inp"
        input_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rc, text, flags = _run_norun(str(exe_path), input_path, tmpdir)
        errors = []
        for match in re.finditer(r'Input error in parameter "([^"]*)" on line (\d+) in file "([^"]*)":\s*\n?\s*([^\n]*)', text):
            errors.append({"parameter": match.group(1), "line": int(match.group(2)), "file": match.group(3), "message": match.group(4).strip()})
        report = {
            "ok": rc == 0 and not errors,
            "exe": str(exe_path),
            "acelib": str(main),
            "declib": str(dec) if dec else None,
            "nfylib": str(nfy) if nfy else None,
            "flags": flags,
            "exit_code": rc,
            "errors": errors,
            "paths_repaired": repair.get("patched", 0),
            "missing_referenced": _missing_referenced(data_dir, [main] + ([data_dir / "mcplib.xsdata"] if (data_dir / "mcplib.xsdata").is_file() else [])),
            "log_tail": text[-2500:],
        }
        log(f"selfcheck: {'OK' if report['ok'] else 'FAILED'} (acelib={main.name})")
        return report
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _print_result(result: dict, stream=None) -> None:
    """Compact human summary on a terminal, full JSON otherwise (job logs)."""
    stream = stream if stream is not None else sys.stdout
    try:
        is_tty = bool(stream.isatty())
    except AttributeError:
        is_tty = False
    if not is_tty:
        print(json.dumps(result, indent=2, ensure_ascii=False), file=stream)
        return
    print(f"state: {result.get('state', 'done')}", file=stream)
    if result.get("dest"):
        print(f"data directory: {result['dest']}", file=stream)
    for line in result.get("use_in_input") or []:
        print(f"  {line}", file=stream)
    manual = result.get("manual_download") or (result.get("photon") or {}).get("manual_download")
    if manual:
        print(f"manual download: {manual.get('url')} -> {manual.get('absolute_path')}", file=stream)
    if result.get("warning"):
        print(f"warning: {result['warning']}", file=stream)
    if result.get("message"):
        print(result["message"], file=stream)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serpent nuclear data library downloader")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list the catalog")

    dl = sub.add_parser("download", help="download a library or URL")
    dl.add_argument("--name", help="catalog key")
    dl.add_argument("--url", help="explicit URL")
    dl.add_argument("--dest", required=True, help="destination directory")
    dl.add_argument("--filename", default=None)
    dl.add_argument("--no-extract", action="store_true")
    dl.add_argument("--no-resume", action="store_true")
    dl.add_argument(
        "--force",
        action="store_true",
        help="if the file already exists, re-extract it (does not re-download)",
    )
    dl.add_argument("--patch", action="store_true", help="rewrite data paths inside extracted *.xsdata files")
    dl.add_argument("--rel-root", default=None, help="workspace root for relative input hints")
    dl.add_argument("--rel-paths", action="store_true", help="write relative instead of absolute paths into *.xsdata")

    px = sub.add_parser("patch-xsdata", help="rewrite data file paths inside *.xsdata directory files")
    px.add_argument("--dir", required=True, help="directory containing the extracted data and *.xsdata files")
    px.add_argument("--rel-root", default=None, help="write paths relative to this directory (workspace root)")
    px.add_argument("--check", action="store_true", help="dry run: report without writing")

    ph = sub.add_parser(
        "photon",
        help="install VTT photon data (mcplib.xsdata + photon_data) and an optional local mcplib84 ACE file",
    )
    ph.add_argument("--dest", required=True, help="destination directory")
    ph.add_argument("--ace-source", default=None, help="directory containing the local mcplib84 ACE file")
    ph.add_argument("--ace-file", default=None, help="explicit path to the mcplib84 ACE file")
    ph.add_argument("--ace-url", default=None, help="direct URL of the mcplib84 ACE file")
    ph.add_argument("--rel-root", default=None, help="write paths relative to this directory (workspace root)")
    ph.add_argument("--no-patch", action="store_true", help="do not rewrite paths in mcplib.xsdata")
    ph.add_argument("--base-url", default=REPO, help=argparse.SUPPRESS)

    st = sub.add_parser(
        "setup",
        help="one-call data setup: neutron package + path patching (+ photon data)",
    )
    st.add_argument("--neutron", default="endfb71", help="catalog key: endfb71 | jeff32 | jendl40 | fendl30")
    st.add_argument("--dest", required=True, help="destination directory")
    st.add_argument("--no-photon", action="store_true", help="skip photon physics data")
    st.add_argument("--no-thxs", action="store_true", help="skip thermal scattering libraries")
    st.add_argument("--no-other-data", action="store_true", help="skip the ENDF/B-VII decay/yield files")
    st.add_argument("--ace-source", default=None, help="directory to search for mcplib84")
    st.add_argument("--ace-file", default=None, help="explicit path to the mcplib84 ACE file")
    st.add_argument("--ace-url", default=None, help="direct URL of the mcplib84 ACE file")
    st.add_argument("--rel-root", default=None, help="write paths relative to this directory (workspace root)")
    st.add_argument("--base-url", default=REPO, help=argparse.SUPPRESS)

    sc = sub.add_parser("selfcheck", help="validate the executable and installed data with a minimal -norun run")
    sc.add_argument("--exe", required=True, help="path to sss2")
    sc.add_argument("--data-dir", required=True, help="directory with the installed data")
    sc.add_argument("--workdir", default=None, help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    if args.command == "list":
        print(json.dumps(catalog(), indent=2, ensure_ascii=False))
        return
    if args.command == "setup":
        result = setup_data(
            args.dest,
            neutron=args.neutron,
            with_photon=not args.no_photon,
            with_thxs=not args.no_thxs,
            with_other_data=not args.no_other_data,
            base_url=args.base_url,
            rel_root=args.rel_root,
            ace_file=args.ace_file,
            ace_url=args.ace_url,
        )
        _print_result(result)
        return
    if args.command == "selfcheck":
        result = selfcheck(args.exe, args.data_dir, workdir=args.workdir)
        _print_result(result)
        return
    if args.command == "patch-xsdata":
        result = patch_xsdata_files(args.dir, rel_root=args.rel_root, apply=not args.check)
        _print_result(result)
        return
    if args.command == "photon":
        result = install_photon(
            args.dest,
            ace_source=args.ace_source,
            ace_file=args.ace_file,
            ace_url=args.ace_url,
            patch=not args.no_patch,
            base_url=args.base_url,
            rel_root=args.rel_root,
        )
        _print_result(result)
        return
    if args.name:
        entry = find_entry(args.name)
        if entry is None:
            print(f"unknown library '{args.name}'; use 'list'", file=sys.stderr)
            raise SystemExit(2)
        download(
            entry.url,
            args.dest,
            filename=entry.filename,
            extract=entry.extract and not args.no_extract,
            resume=not args.no_resume,
            force=args.force,
            patch=args.patch and entry.extract and not args.no_extract,
            rel_root=args.rel_root,
            relative_paths=args.rel_paths,
        )
        return
    if args.url:
        download(
            args.url,
            args.dest,
            filename=args.filename,
            extract=not args.no_extract,
            resume=not args.no_resume,
            force=args.force,
            patch=args.patch and not args.no_extract,
            rel_root=args.rel_root,
            relative_paths=args.rel_paths,
        )
        return
    print("either --name or --url is required", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
