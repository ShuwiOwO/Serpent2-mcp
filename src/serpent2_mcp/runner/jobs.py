"""Background job management for Serpent runs and data downloads."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..config import Settings, SshConfig
from ..util import now_iso, run_capture, write_json


@dataclass
class Job:
    id: str
    kind: str  # "run" | "download"
    backend: str
    argv: list[str]
    cwd: str
    job_dir: str
    log_file: str
    exit_file: str
    pid: int | None = None
    started: str = field(default_factory=now_iso)
    finished: str | None = None
    state: str = "running"  # running | finished | failed | lost | killed
    exit_code: int | None = None
    remote: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def display_command(self) -> str:
        return " ".join(shlex.quote(part) for part in self.argv)


class Jobs:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- helpers -----------------------------------------------------------

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def get(self, job_id: str) -> Job | None:
        path = self.job_dir(job_id) / "job.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return Job(**data)

    def save(self, job: Job) -> None:
        write_json(Path(job.job_dir) / "job.json", job.to_dict())

    def list(self, limit: int = 20) -> list[Job]:
        jobs: list[tuple[float, Job]] = []
        for path in self.root.glob("*/job.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                job = Job(**data)
            except (OSError, ValueError):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            jobs.append((mtime, job))
        jobs.sort(key=lambda item: item[0], reverse=True)
        return [job for _, job in jobs[:limit]]

    # -- local backend ------------------------------------------------------

    def start_local(
        self,
        kind: str,
        argv: list[str],
        cwd: str | Path,
        meta: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
    ) -> Job:
        job_id = self.new_id(kind)
        job_dir = self.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        log_file = job_dir / "app.log"
        exit_file = job_dir / "exit_code"
        script = _script(argv, Path(cwd), log_file, exit_file)
        script_path = job_dir / "run.sh"
        script_path.write_text(script, encoding="utf-8")
        script_path.chmod(0o755)
        job = Job(
            id=job_id,
            kind=kind,
            backend="local",
            argv=argv,
            cwd=str(cwd),
            job_dir=str(job_dir),
            log_file=str(log_file),
            exit_file=str(exit_file),
            meta=meta or {},
        )
        process_env = dict(os.environ)
        process_env.setdefault("SERPENT_PROGRESS_FILE", str(job_dir / "progress.json"))
        if env:
            process_env.update(env)
        try:
            proc = subprocess.Popen(
                ["sh", str(script_path)],
                cwd=str(job_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=process_env,
            )
            job.pid = proc.pid
        except OSError as exc:
            job.state = "failed"
            job.error = str(exc)
            job.finished = now_iso()
        self.save(job)
        return job

    # -- ssh backend --------------------------------------------------------

    def start_ssh(
        self,
        kind: str,
        settings: Settings,
        argv: list[str],
        cwd: str,
        meta: dict[str, Any] | None = None,
    ) -> Job:
        assert settings.ssh is not None
        ssh = settings.ssh
        job_id = self.new_id(kind)
        remote_dir = f"{ssh.jobdir.rstrip('/')}/{job_id}"
        job_dir = self.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        log_file = f"{remote_dir}/app.log"
        exit_file = f"{remote_dir}/exit_code"
        script = _script(argv, Path(cwd), Path(log_file), Path(exit_file))

        job = Job(
            id=job_id,
            kind=kind,
            backend="ssh",
            argv=argv,
            cwd=cwd,
            job_dir=str(job_dir),
            log_file=log_file,
            exit_file=exit_file,
            remote={"host": ssh.host, "dir": remote_dir, "options": ssh.options},
            meta=meta or {},
        )
        try:
            rc, out, err = self._ssh(ssh, f"mkdir -p {_rq(remote_dir)}")
            if rc != 0:
                raise RuntimeError(err.strip() or out.strip() or "ssh mkdir failed")
            rc, out, err = self._ssh(ssh, f"cat > {_rq(remote_dir + '/run.sh')}", input_text=script)
            if rc != 0:
                raise RuntimeError(err.strip() or "failed to upload run script")
            start_cmd = (
                f"cd {_rq(cwd)} && "
                f"nohup sh {_rq(remote_dir + '/run.sh')} >/dev/null 2>&1 < /dev/null & echo $!"
            )
            rc, out, err = self._ssh(ssh, start_cmd)
            if rc != 0:
                raise RuntimeError(err.strip() or "failed to start remote job")
            pid_text = out.strip().splitlines()[-1] if out.strip() else ""
            job.pid = int(pid_text) if pid_text.isdigit() else None
        except Exception as exc:  # noqa: BLE001
            job.state = "failed"
            job.error = str(exc)
            job.finished = now_iso()
        self.save(job)
        return job

    def _ssh(self, ssh: SshConfig, command: str, input_text: str | None = None) -> tuple[int, str, str]:
        argv = ["ssh", *ssh.options, ssh.host, command]
        return run_capture(argv, timeout=60, input_text=input_text)

    # -- status / output / kill ---------------------------------------------

    def refresh(self, job: Job) -> Job:
        if job.state in {"finished", "failed", "killed"} and job.exit_code is not None:
            return job
        if job.backend == "local":
            return self._refresh_local(job)
        return self._refresh_ssh(job)

    def _refresh_local(self, job: Job) -> Job:
        exit_path = Path(job.exit_file)
        if exit_path.is_file():
            return self._apply_exit_code(job, exit_path)
        if job.pid:
            try:
                os.kill(job.pid, 0)
            except ProcessLookupError:
                if job.state == "running":
                    job.state = "lost"
            except PermissionError:
                pass
        return job

    def _refresh_ssh(self, job: Job) -> Job:
        remote = job.remote or {}
        ssh = SshConfig(
            host=remote.get("host", ""),
            options=list(remote.get("options", [])),
        )
        rc, out, err = self._ssh(
            ssh,
            f"if [ -f {_rq(job.exit_file)} ]; then cat {_rq(job.exit_file)}; fi",
        )
        if rc == 0 and out.strip().isdigit():
            exit_path = Path(job.job_dir) / "exit_code"
            exit_path.write_text(out.strip(), encoding="utf-8")
            return self._apply_exit_code(job, exit_path)
        if job.pid:
            rc, _out, _err = self._ssh(ssh, f"kill -0 {job.pid} 2>/dev/null; echo $?")
            if rc == 0 and _out.strip() != "0" and job.state == "running":
                job.state = "lost"
        return job

    def _apply_exit_code(self, job: Job, exit_path: Path) -> Job:
        try:
            code = int(exit_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            code = -1
        job.exit_code = code
        if job.state not in {"killed"}:
            job.state = "finished" if code == 0 else "failed"
        job.finished = job.finished or now_iso()
        self.save(job)
        return job

    def output(self, job: Job, tail_chars: int = 6000) -> str:
        if job.backend == "local":
            path = Path(job.log_file)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
            return text[-tail_chars:] if tail_chars and len(text) > tail_chars else text
        remote = job.remote or {}
        ssh = SshConfig(host=remote.get("host", ""), options=list(remote.get("options", [])))
        tail = f"tail -c {int(tail_chars)}" if tail_chars else "cat"
        rc, out, err = self._ssh(ssh, f"{tail} {_rq(job.log_file)} 2>/dev/null")
        return out if rc == 0 else err

    def kill(self, job: Job) -> Job:
        if job.backend == "local":
            if job.pid:
                try:
                    os.killpg(os.getpgid(job.pid), signal.SIGTERM)
                    for _ in range(20):
                        try:
                            os.kill(job.pid, 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.25)
                    else:
                        os.killpg(os.getpgid(job.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    pass
        else:
            remote = job.remote or {}
            ssh = SshConfig(host=remote.get("host", ""), options=list(remote.get("options", [])))
            if job.pid:
                self._ssh(
                    ssh,
                    f"kill -TERM {job.pid} 2>/dev/null; pkill -TERM -P {job.pid} 2>/dev/null; true",
                )
        job.state = "killed"
        job.finished = now_iso()
        self.save(job)
        return job

    def progress(self, job: Job) -> dict[str, Any] | None:
        path = Path(job.job_dir) / "progress.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


def _rq(path: str) -> str:
    """Quote a remote path, expanding a leading tilde through $HOME."""
    text = str(path)
    if text == "~":
        return '"$HOME"'
    if text.startswith("~/"):
        return f'"$HOME"/{shlex.quote(text[2:])}'
    return shlex.quote(text)


def _script(argv: list[str], cwd: Path, log_file: Path, exit_file: Path) -> str:
    command = " ".join(shlex.quote(part) for part in argv)
    return (
        "#!/bin/sh\n"
        f"cd {shlex.quote(str(cwd))} || {{ echo 127 > {shlex.quote(str(exit_file))}; exit 127; }}\n"
        f"{command} > {shlex.quote(str(log_file))} 2>&1\n"
        f"echo $? > {shlex.quote(str(exit_file))}\n"
    )
