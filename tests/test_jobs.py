"""Background job manager: local and (fake) SSH backends."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

from serpent2_mcp.config import Settings, SshConfig
from serpent2_mcp.runner.jobs import Jobs


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _wait(jobs: Jobs, job, timeout: float = 15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobs.refresh(job)
        if job.state in {"finished", "failed", "lost", "killed"}:
            return job
        time.sleep(0.2)
    return job


def test_local_job_success(tmp_path):
    jobs = Jobs(tmp_path / "jobs")
    script = tmp_path / "fake_sss2"
    _write_executable(
        script,
        "#!/bin/sh\necho \"fake serpent args: $@\"\nexit 0\n",
    )
    job = jobs.start_local("run", [str(script), "input.inp"], tmp_path)
    job = _wait(jobs, job)
    assert job.state == "finished"
    assert job.exit_code == 0
    output = jobs.output(job)
    assert "fake serpent args: input.inp" in output


def test_local_job_failure(tmp_path):
    jobs = Jobs(tmp_path / "jobs")
    script = tmp_path / "fake_sss2"
    _write_executable(script, "#!/bin/sh\necho 'boom' >&2\nexit 3\n")
    job = jobs.start_local("run", [str(script), "input.inp"], tmp_path)
    job = _wait(jobs, job)
    assert job.state == "failed"
    assert job.exit_code == 3
    assert "boom" in jobs.output(job)


def test_local_job_kill(tmp_path):
    jobs = Jobs(tmp_path / "jobs")
    script = tmp_path / "sleeper"
    _write_executable(script, "#!/bin/sh\nsleep 30\n")
    job = jobs.start_local("run", [str(script)], tmp_path)
    time.sleep(0.5)
    job = jobs.kill(job)
    assert job.state == "killed"


def _fake_ssh(tmp_path: Path, monkeypatch) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    ssh = bindir / "ssh"
    _write_executable(
        ssh,
        """#!/bin/sh
seen_host=0
cmd=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o|-p) shift 2 ;;
    -*) shift ;;
    *)
      if [ $seen_host -eq 1 ]; then cmd="$1"; fi
      seen_host=1
      shift
      ;;
  esac
done
exec sh -c "$cmd"
""",
    )
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH','')}")
    return bindir


def test_ssh_job_with_fake_ssh(tmp_path, monkeypatch):
    _fake_ssh(tmp_path, monkeypatch)
    jobs = Jobs(tmp_path / "jobs")
    script = tmp_path / "sss2"
    _write_executable(script, "#!/bin/sh\necho \"remote serpent: $@\"\nexit 0\n")

    settings = Settings(
        workspace=tmp_path,
        exe=str(script),
        backend="ssh",
        ssh=SshConfig(host="fakehost", workdir=str(tmp_path), jobdir=str(tmp_path / "remote-jobs")),
        jobs_dir=tmp_path / "jobs",
    )
    job = jobs.start_ssh("run", settings, [str(script), "input.inp"], str(tmp_path))
    job = _wait(jobs, job)
    assert job.state == "finished", (job.state, job.error)
    assert "remote serpent: input.inp" in jobs.output(job)


def test_ssh_job_failure_state(tmp_path, monkeypatch):
    _fake_ssh(tmp_path, monkeypatch)
    jobs = Jobs(tmp_path / "jobs")
    settings = Settings(
        workspace=tmp_path,
        exe="does-not-exist",
        backend="ssh",
        ssh=SshConfig(host="fakehost", workdir=str(tmp_path), jobdir=str(tmp_path / "remote-jobs")),
        jobs_dir=tmp_path / "jobs",
    )
    job = jobs.start_ssh("run", settings, ["does-not-exist", "input.inp"], str(tmp_path))
    job = _wait(jobs, job)
    assert job.state == "failed"
    assert job.exit_code not in (0, None)
