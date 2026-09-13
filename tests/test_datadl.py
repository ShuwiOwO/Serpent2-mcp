"""Nuclear data catalog and resumable downloader."""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

from serpent2_mcp.runner import datadl


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    """Minimal static file server with HEAD and Range support."""

    root: Path

    def log_message(self, *args):  # noqa: D102
        pass

    def _resolve(self) -> Path | None:
        candidate = (self.root / self.path.lstrip("/")).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _send_file(self, path: Path, body: bool) -> None:
        data = path.read_bytes()
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            spec = range_header[len("bytes="):]
            start_text, _, end_text = spec.partition("-")
            start = int(start_text) if start_text else 0
            end = int(end_text) if end_text else len(data) - 1
            end = min(end, len(data) - 1)
            chunk = data[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            if body:
                self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        if body:
            self.wfile.write(data)

    def do_HEAD(self):  # noqa: N802
        path = self._resolve()
        if path is None:
            self.send_error(404)
            return
        self._send_file(path, body=False)

    def do_GET(self):  # noqa: N802
        path = self._resolve()
        if path is None:
            self.send_error(404)
            return
        self._send_file(path, body=True)


@pytest.fixture()
def http_server(tmp_path: Path):
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "lib.bin").write_bytes(b"0123456789" * 10000)

    class Handler(_RangeHandler):
        root = payload

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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
        if entry.manual:
            assert entry.homepage.startswith("https://")
            continue
        assert entry.url.startswith("https://serpent.vtt.fi/repository/")
        assert entry.size_bytes is None or entry.size_bytes > 0


def test_catalog_aliases():
    assert datadl.find_entry("JEFF").key == "jeff32"
    assert datadl.find_entry("jeff-3.2").key == "jeff32"
    assert datadl.find_entry("ENDF/B-VII.1").key == "endfb71"
    assert datadl.find_entry("jendl").key == "jendl40"
    assert datadl.find_entry("fendl").key == "fendl30"
    assert datadl.find_entry("unknown-library") is None


def test_repo_mirror_rewrites_vtt_urls(monkeypatch):
    monkeypatch.setenv("SERPENT_DATA_REPO_URL", "https://mirror.example/serpent")
    url = "https://serpent.vtt.fi/repository/Serpent_2_xsdata/s2v0_endfb71.tar.gz"
    assert datadl._apply_repo_mirror(url) == "https://mirror.example/serpent/Serpent_2_xsdata/s2v0_endfb71.tar.gz"
    monkeypatch.delenv("SERPENT_DATA_REPO_URL")
    assert datadl._apply_repo_mirror(url) == url


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


def test_download_resume_continues_part(tmp_path: Path, http_server: str):
    dest = tmp_path / "out"
    dest.mkdir()
    payload = (tmp_path / "payload" / "lib.bin").read_bytes()
    (dest / "lib.bin.part").write_bytes(payload[:50000])  # genuine interrupted prefix
    path = datadl.download(f"{http_server}/lib.bin", dest, log=lambda _m: None)
    assert path.read_bytes() == payload


def test_download_stream_restarts_without_range_support(tmp_path: Path):
    payload_dir = tmp_path / "basic"
    payload_dir.mkdir()
    data = b"0123456789" * 10000
    (payload_dir / "lib.bin").write_bytes(data)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D102
            pass

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(payload_dir), **kwargs)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        dest = tmp_path / "out"
        dest.mkdir()
        (dest / "lib.bin.part").write_bytes(b"x" * 50000)  # stale file, no Range support
        path = datadl.download(f"{base}/lib.bin", dest, log=lambda _m: None)
        assert path.read_bytes() == data
    finally:
        server.shutdown()


def test_download_threads_env(monkeypatch):
    monkeypatch.delenv("SERPENT_DOWNLOAD_THREADS", raising=False)
    assert datadl.download_threads() == datadl.DEFAULT_DOWNLOAD_THREADS
    monkeypatch.setenv("SERPENT_DOWNLOAD_THREADS", "3")
    assert datadl.download_threads() == 3
    monkeypatch.setenv("SERPENT_DOWNLOAD_THREADS", "99")
    assert datadl.download_threads() == 16
    monkeypatch.setenv("SERPENT_DOWNLOAD_THREADS", "nonsense")
    assert datadl.download_threads() == datadl.DEFAULT_DOWNLOAD_THREADS


def test_parallel_download(tmp_path: Path, http_server: str, monkeypatch):
    monkeypatch.setenv("SERPENT_DOWNLOAD_THREADS", "3")
    monkeypatch.setattr(datadl, "PARALLEL_MIN_SIZE", 100_000)
    monkeypatch.setattr(datadl, "DOWNLOAD_CHUNK_SIZE", 100_000)
    payload = (tmp_path / "payload" / "lib.bin").read_bytes()
    dest = tmp_path / "out"
    path = datadl.download(f"{http_server}/lib.bin", dest, log=lambda _m: None)
    assert path.read_bytes() == payload
    assert not (dest / "lib.bin.chunks").exists()
    assert not list(dest.glob("*.part"))


def test_parallel_download_resumes_completed_chunks(tmp_path: Path, http_server: str, monkeypatch):
    monkeypatch.setenv("SERPENT_DOWNLOAD_THREADS", "3")
    monkeypatch.setattr(datadl, "PARALLEL_MIN_SIZE", 100_000)
    monkeypatch.setattr(datadl, "DOWNLOAD_CHUNK_SIZE", 100_000)
    payload = (tmp_path / "payload" / "lib.bin").read_bytes()
    dest = tmp_path / "out"
    chunk_dir = dest / "lib.bin.chunks"
    chunk_dir.mkdir(parents=True)
    (chunk_dir / f"chunk_{0:012d}").write_bytes(payload[:100_000])  # already complete
    path = datadl.download(f"{http_server}/lib.bin", dest, log=lambda _m: None)
    assert path.read_bytes() == payload
    assert not chunk_dir.exists()


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


# ---------------------------------------------------------------------------
# Photon data (mcplib.xsdata + photon_data + optional local mcplib84)
# ---------------------------------------------------------------------------


def test_photon_catalog_and_aliases():
    assert datadl.find_entry("photon data").key == "photon_data"
    assert datadl.find_entry("photon-data").key == "photon_data"
    assert datadl.find_entry("photon libraries").key == "photon_data"
    assert datadl.find_entry("mcplib.xsdata").key == "photon_xsdata"
    manual = datadl.find_entry("mcplib84")
    assert manual is not None and manual.manual is True
    assert manual.url == ""
    assert manual.homepage.startswith("https://nucleardata.lanl.gov")
    assert datadl.find_entry("mcplib63").key == "mcplib84"


def _make_photon_payload(payload_dir: Path) -> None:
    import io
    import tarfile

    photo = payload_dir / "photon_data"
    photo.mkdir(exist_ok=True)
    (photo / "mcplib.xsdata").write_text(
        "  1000.84p   1000.84p 5   1000 0    1.007900 0.000000 0 /xs/data/mcplib84\n"
        "  2000.84p   2000.84p 5   2000 0    4.002604 0.000000 0 /xs/data/mcplib84\n",
        encoding="utf-8",
    )
    with tarfile.open(photo / "photon_data.tar.gz", "w:gz") as tar:
        content = b"photon physics data\n"
        info = tarfile.TarInfo("photon_data/README.txt")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))


def test_find_ace_file_ignores_small_directory_file(tmp_path: Path):
    directory = tmp_path / "lib"
    directory.mkdir()
    (directory / "mcplib84").write_bytes(b"x" * 1000)  # directory file, too small
    assert datadl.find_ace_file(directory) is None
    (directory / "mcplib84").write_bytes(b"x" * 1_100_000)  # looks like ACE data
    assert datadl.find_ace_file(directory) is not None


def test_find_ace_file_recursive_in_acedata(tmp_path: Path):
    nested = tmp_path / "data" / "acedata"
    nested.mkdir(parents=True)
    (nested / "mcplib84").write_bytes(b"x" * 1_100_000)
    found = datadl.find_ace_file(tmp_path / "data")
    assert found is not None
    assert found.name == "mcplib84"
    assert found.parent.name == "acedata"


def test_install_photon_uses_ace_from_acedata(tmp_path: Path, http_server: str):
    _make_photon_payload(tmp_path / "payload")
    dest = tmp_path / "xsdata"
    (dest / "acedata").mkdir(parents=True)
    (dest / "acedata" / "mcplib84").write_bytes(b"C" * 1_300_000)
    empty = tmp_path / "empty"
    empty.mkdir()

    result = datadl.install_photon(
        dest, ace_source=empty, base_url=http_server, rel_root=tmp_path, log=lambda _m: None
    )

    assert result["ace_installed"] is True
    assert result["ace_file"].endswith("xsdata/acedata/mcplib84")
    assert not (dest / "mcplib84").exists()  # used in place, not duplicated
    assert result["ace_path_in_directory_file"] == "xsdata/acedata/mcplib84"


def test_setup_data_with_local_server(tmp_path: Path, http_server: str):
    import io
    import tarfile

    payload = tmp_path / "payload"

    def make_tar(name: str, members: dict[str, bytes]) -> None:
        with tarfile.open(payload / name, "w:gz") as tar:
            for member, data in members.items():
                info = tarfile.TarInfo(member)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

    make_tar(
        "s2v0_endfb71.tar.gz",
        {
            "data.xsdata": (
                b"  1001.03c 1001.03c 1 1001 0 1.0 300 0 /xs/data/acedata/1001ENDF7.ace\n"
                b"   lwtr.20t   lwtr.20t  3      0  0    1.0  293 0 /xs/data/data/sssth1\n"
            ),
            "acedata/1001ENDF7.ace": b"ace",
            "sss_endfb7.dec": b"dec",
        },
    )
    make_tar("sss_thxs.tar.gz", {"data/sssth1": b"thermal"})
    _make_photon_payload(payload)

    dest = tmp_path / "xsdata"
    result = datadl.setup_data(dest, neutron="endfb71", base_url=http_server, rel_root=tmp_path, log=lambda _m: None)

    assert (dest / "data.xsdata").is_file()
    patched = (dest / "data.xsdata").read_text(encoding="utf-8")
    assert " xsdata/acedata/1001ENDF7.ace" in patched
    assert " xsdata/data/sssth1" in patched
    assert "/xs/data/" not in patched
    assert (dest / "data" / "sssth1").is_file()
    assert (dest / "photon_data" / "README.txt").is_file()
    assert (dest / "mcplib.xsdata").is_file()
    assert result["thermal_scattering"] == "sss_thxs.tar.gz"
    lines = result["use_in_input"]
    assert 'set acelib "xsdata/data.xsdata" "xsdata/mcplib.xsdata"' in lines
    assert 'set declib "xsdata/sss_endfb7.dec"' in lines
    assert 'set pdatadir "xsdata/photon_data"' in lines
    # The fake payload has no mcplib84, so the result is partial and gives exact instructions.
    assert result["state"] == "partial"
    assert "mcplib84" in result["warning"]
    manual = result["manual_download"]
    assert manual["save_as"] == "xsdata/mcplib84"
    assert manual["url"].startswith("https://nucleardata.lanl.gov")
    assert manual["absolute_path"] == str(dest / "mcplib84")


def test_patch_xsdata_files_outside_workspace_uses_absolute(tmp_path: Path):
    dest = tmp_path / "elsewhere" / "xsdata"
    (dest / "acedata").mkdir(parents=True)
    (dest / "acedata" / "1001ENDF7.ace").write_bytes(b"ace")
    xsdata = dest / "data.xsdata"
    xsdata.write_text("  1001.03c 1001.03c 1 1001 0 1.0 300 0 /xs/data/acedata/1001ENDF7.ace\n", encoding="utf-8")
    other_root = tmp_path / "workspace"
    other_root.mkdir()
    datadl.patch_xsdata_files(dest, rel_root=other_root, log=lambda _m: None)
    text = xsdata.read_text(encoding="utf-8")
    assert ".." not in text
    assert str(dest / "acedata" / "1001ENDF7.ace") in text


def test_patch_xsdata_files(tmp_path: Path):
    dest = tmp_path / "xsdata"
    (dest / "acedata").mkdir(parents=True)
    (dest / "acedata" / "1001ENDF7.ace").write_bytes(b"ace")
    xsdata = dest / "data.xsdata"
    xsdata.write_text(
        "  1001.03c 1001.03c 1 1001 0 1.0 300 0 /xs/data/acedata/1001ENDF7.ace\n"
        "  9999.03c 9999.03c 1 9999 0 1.0 300 0 /xs/data/acedata/9999ENDF7.ace\n",
        encoding="utf-8",
    )
    dry = datadl.patch_xsdata_files(dest, rel_root=tmp_path, apply=False, log=lambda _m: None)
    assert dry["patched"] == 1
    assert dry["missing"] == ["9999ENDF7.ace"]
    assert "/xs/data/" in xsdata.read_text(encoding="utf-8")  # dry run wrote nothing

    stats = datadl.patch_xsdata_files(dest, rel_root=tmp_path, log=lambda _m: None)
    assert stats["patched"] == 1
    text = xsdata.read_text(encoding="utf-8")
    assert " xsdata/acedata/1001ENDF7.ace" in text
    assert "/xs/data/acedata/1001ENDF7.ace" not in text
    assert "/xs/data/acedata/9999ENDF7.ace" in text  # missing entry stays untouched


def test_install_photon_with_local_ace(tmp_path: Path, http_server: str):
    _make_photon_payload(tmp_path / "payload")
    ace_source = tmp_path / "photon_libraries"
    ace_source.mkdir()
    (ace_source / "mcplib84").write_bytes(b"A" * 1_200_000)
    dest = tmp_path / "out"

    result = datadl.install_photon(dest, ace_source=ace_source, base_url=http_server, log=lambda _m: None)

    assert (dest / "mcplib.xsdata").is_file()
    assert (dest / "photon_data" / "README.txt").is_file()
    assert (dest / "mcplib84").stat().st_size == 1_200_000
    assert result["state"] == "done"
    assert result["directory_entries_patched"] == 2
    assert result["ace_installed"] is True
    assert result["ace_file"] == str(dest / "mcplib84")
    patched = (dest / "mcplib.xsdata").read_text(encoding="utf-8")
    assert str(dest / "mcplib84") in patched
    assert "/xs/data/mcplib84" not in patched


def test_install_photon_relative_paths(tmp_path: Path, http_server: str):
    _make_photon_payload(tmp_path / "payload")
    ace_source = tmp_path / "photon_libraries"
    ace_source.mkdir()
    (ace_source / "mcplib84").write_bytes(b"A" * 1_200_000)
    dest = tmp_path / "xsdata"

    result = datadl.install_photon(
        dest,
        ace_source=ace_source,
        base_url=http_server,
        rel_root=tmp_path,
        log=lambda _m: None,
    )

    assert result["ace_path_in_directory_file"] == "xsdata/mcplib84"
    patched = (dest / "mcplib.xsdata").read_text(encoding="utf-8")
    assert " xsdata/mcplib84" in patched
    assert str(tmp_path) not in patched
    assert result["use_in_input"] == [
        'set acelib "xsdata/mcplib.xsdata"',
        'set pdatadir "xsdata/photon_data"',
    ]


def test_install_photon_ace_url(tmp_path: Path, http_server: str):
    _make_photon_payload(tmp_path / "payload")
    (tmp_path / "payload" / "mcplib84").write_bytes(b"B" * 1_100_000)
    empty = tmp_path / "empty"
    empty.mkdir()
    dest = tmp_path / "out"

    result = datadl.install_photon(
        dest,
        ace_source=empty,
        ace_url=f"{http_server}/mcplib84",
        base_url=http_server,
        log=lambda _m: None,
    )

    assert result["ace_installed"] is True
    assert (dest / "mcplib84").stat().st_size == 1_100_000


def test_install_photon_without_ace(tmp_path: Path, http_server: str):
    _make_photon_payload(tmp_path / "payload")
    empty = tmp_path / "empty"
    empty.mkdir()
    dest = tmp_path / "out"

    result = datadl.install_photon(dest, ace_source=empty, base_url=http_server, log=lambda _m: None)

    assert (dest / "mcplib.xsdata").is_file()
    assert result["state"] == "partial"
    assert result["ace_file"] is None
    assert result["directory_entries_patched"] == 2
    assert "message" in result
    # Paths are written even without the ACE file, pointing at the expected location.
    assert result["ace_path_in_directory_file"] == str(dest / "mcplib84")
    assert "mcplib84" in (dest / "mcplib.xsdata").read_text(encoding="utf-8")
