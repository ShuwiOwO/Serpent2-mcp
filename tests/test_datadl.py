"""Nuclear data catalog and resumable downloader."""

from __future__ import annotations

import functools
import http.server
import json
import threading
from pathlib import Path

import pytest

from serpent2_mcp.runner import datadl


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D102
        pass


@pytest.fixture()
def http_server(tmp_path: Path):
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "lib.bin").write_bytes(b"0123456789" * 10000)
    handler = functools.partial(_QuietHandler, directory=str(payload))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


@pytest.fixture(autouse=True)
def _progress_file(tmp_path: Path, monkeypatch):
    """Keep downloader progress out of the repository working directory."""
    monkeypatch.setenv("SERPENT_PROGRESS_FILE", str(tmp_path / "progress.json"))


def test_catalog_has_main_libraries():
    keys = {entry.key for entry in datadl.CATALOG}
    assert {"endfb71", "jeff32", "jendl40", "fendl30", "thxs"} <= keys
    for entry in datadl.CATALOG:
        assert entry.url.startswith("https://serpent.vtt.fi/repository/")
        assert entry.size_bytes is None or entry.size_bytes > 0


def test_catalog_aliases():
    assert datadl.find_entry("JEFF").key == "jeff32"
    assert datadl.find_entry("jeff-3.2").key == "jeff32"
    assert datadl.find_entry("ENDF/B-VII.1").key == "endfb71"
    assert datadl.find_entry("jendl").key == "jendl40"
    assert datadl.find_entry("fendl").key == "fendl30"
    assert datadl.find_entry("unknown-library") is None


def test_download_writes_progress(tmp_path: Path, http_server: str, monkeypatch):
    progress_file = tmp_path / "progress.json"
    monkeypatch.setenv("SERPENT_PROGRESS_FILE", str(progress_file))
    dest = tmp_path / "out"
    logs: list[str] = []
    path = datadl.download(f"{http_server}/lib.bin", dest, log=logs.append)
    assert path == dest / "lib.bin"
    assert path.read_bytes() == b"0123456789" * 10000
    payload = json.loads(progress_file.read_text(encoding="utf-8"))
    assert payload["state"] == "done"
    assert payload["downloaded"] == 100000
    assert not list(dest.glob("*.part"))


def test_download_resume_overwrites_stale_part(tmp_path: Path, http_server: str):
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "lib.bin.part").write_bytes(b"x" * 50000)  # server ignores Range -> restart
    path = datadl.download(f"{http_server}/lib.bin", dest, log=lambda _m: None)
    assert path.read_bytes() == b"0123456789" * 10000


def test_download_extracts_tarball_into_dest(tmp_path: Path, http_server: str):
    import io
    import tarfile

    # Build a small tar.gz that mimics a Serpent data package.
    archive = tmp_path / "payload" / "pack.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        content = b"# serpent xsdata directory\n"
        info = tarfile.TarInfo("data.xsdata")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))

    dest = tmp_path / "out"
    datadl.download(f"{http_server}/pack.tar.gz", dest, extract=True, log=lambda _m: None)
    assert (dest / "pack.tar.gz").is_file()
    assert (dest / "data.xsdata").read_bytes().startswith(b"# serpent xsdata")


def test_cli_download_and_force(tmp_path: Path, http_server: str, monkeypatch, capsys):
    monkeypatch.setenv("SERPENT_PROGRESS_FILE", str(tmp_path / "progress.json"))
    dest = tmp_path / "out"
    rc = datadl.main(["download", "--url", f"{http_server}/lib.bin", "--dest", str(dest)])
    assert rc is None
    target = dest / "lib.bin"
    assert target.is_file()
    before = target.stat().st_mtime_ns
    # --force with an existing file must be accepted and must not fail.
    datadl.main(["download", "--url", f"{http_server}/lib.bin", "--dest", str(dest), "--force", "--no-extract"])
    assert target.stat().st_mtime_ns == before
