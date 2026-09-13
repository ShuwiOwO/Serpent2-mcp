"""The portable installer script (syntax, help text, argument validation)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SETUP = ROOT / "setup.sh"


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX shell not available")
def test_setup_sh_syntax():
    result = subprocess.run(["sh", "-n", str(SETUP)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX shell not available")
def test_setup_sh_help_lists_data_options():
    result = subprocess.run(["sh", str(SETUP), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    for token in (
        "--data",
        "--data-dir",
        "--no-photon",
        "--no-thxs",
        "--yes",
        "--offline",
        "--status",
        "--opencode",
        "--no-opencode",
    ):
        assert token in result.stdout


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX shell not available")
def test_setup_sh_rejects_unknown_data_library():
    result = subprocess.run(
        ["sh", str(SETUP), "--data", "nonsense"], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 2
    assert "unknown --data value" in result.stderr


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX shell not available")
def test_setup_sh_status_runs():
    result = subprocess.run(["sh", str(SETUP), "--status"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0
    assert "Python:" in result.stdout
    assert "data:" in result.stdout
