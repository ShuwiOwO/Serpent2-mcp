"""Nuclear data library catalog and resumable background downloads.

The libraries are distributed publicly by VTT at serpent.vtt.fi/repository.
Downloads run as ordinary background jobs (see jobs.py), so multi-GB transfers
never block the MCP session.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from ..util import USER_AGENT, human_size, now_iso

REPO = "https://serpent.vtt.fi/repository"


@dataclass
class DataLibrary:
    key: str
    title: str
    url: str
    size_bytes: int | None
    kind: str  # xsdata | decay | photon | misc
    extract: bool
    note: str = ""

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]

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
        "mcplib84",
        "Photon cross sections (mcplib84 directory file)",
        f"{REPO}/photon_data/mcplib.xsdata",
        14_800,
        "photon",
        False,
        "ACE data itself must be obtained from LANL; this is the directory file.",
    ),
    DataLibrary(
        "photon_data",
        "Photon physics data (set pdatadir)",
        f"{REPO}/photon_data/photon_data.tar.gz",
        7_750_353,
        "photon",
        True,
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


def download(
    url: str,
    dest: str | Path,
    filename: str | None = None,
    extract: bool = False,
    resume: bool = True,
    force: bool = False,
    log=print,
) -> Path:
    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    filename = filename or url.rsplit("/", 1)[-1]
    target = dest / filename
    if target.is_file() and target.stat().st_size > 0:
        log(f"already present: {target} ({human_size(target.stat().st_size)})")
        _progress(
            {
                "state": "done",
                "file": filename,
                "downloaded": target.stat().st_size,
                "total": target.stat().st_size,
                "path": str(target),
            }
        )
        if extract and force:
            _extract(target, dest, log)
        return target

    part = target.with_name(target.name + ".part")
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
        last_report = 0.0
        with part.open(mode) as handle:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                pos += len(chunk)
                now = time.time()
                if now - last_report > 2.0:
                    last_report = now
                    _progress({"state": "downloading", "file": filename, "downloaded": pos, "total": total})
                    if total:
                        pct = 100.0 * pos / total
                        log(f"{filename}: {human_size(pos)} / {human_size(total)} ({pct:.1f}%)")
                    else:
                        log(f"{filename}: {human_size(pos)}")
    os.replace(part, target)
    log(f"downloaded {target} ({human_size(target.stat().st_size)})")
    _progress(
        {
            "state": "done",
            "file": filename,
            "downloaded": target.stat().st_size,
            "total": target.stat().st_size,
            "path": str(target),
        }
    )
    if extract:
        _extract(target, dest, log)
        _progress(
            {
                "state": "extracted",
                "file": filename,
                "downloaded": target.stat().st_size,
                "total": target.stat().st_size,
                "path": str(target),
                "dest": str(dest),
            }
        )
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

    args = parser.parse_args(argv)
    if args.command == "list":
        print(json.dumps(catalog(), indent=2, ensure_ascii=False))
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
        )
        return
    print("either --name or --url is required", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
