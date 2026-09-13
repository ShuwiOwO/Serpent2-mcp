"""Writing/merging opencode.json for the MCP server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from serpent2_mcp.opencode_config import main, write_opencode_config


def test_write_new_config(tmp_path: Path):
    path = tmp_path / "opencode.json"
    result = write_opencode_config(path, ["/opt/venv/bin/python", "-m", "serpent2_mcp"], env={"SERPENT_LANG": "ru"})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["$schema"] == "https://opencode.ai/config.json"
    entry = data["mcp"]["serpent"]
    assert entry["type"] == "local"
    assert entry["command"] == ["/opt/venv/bin/python", "-m", "serpent2_mcp"]
    assert entry["environment"]["SERPENT_LANG"] == "ru"
    assert result["existing_file_updated"] is False


def test_merge_preserves_existing_config(tmp_path: Path):
    path = tmp_path / "opencode.json"
    path.write_text(
        json.dumps({"model": "x/y", "mcp": {"other": {"type": "local", "command": ["foo"]}}}),
        encoding="utf-8",
    )
    write_opencode_config(path, ["python", "-m", "serpent2_mcp"])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "x/y"
    assert data["mcp"]["other"]["command"] == ["foo"]
    assert data["mcp"]["serpent"]["command"] == ["python", "-m", "serpent2_mcp"]


def test_invalid_json_raises(tmp_path: Path):
    path = tmp_path / "opencode.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        write_opencode_config(path, ["python", "-m", "serpent2_mcp"])


def test_dry_run_does_not_write(tmp_path: Path):
    path = tmp_path / "opencode.json"
    result = write_opencode_config(path, ["python", "-m", "serpent2_mcp"], dry_run=True)
    assert result["dry_run"] is True
    assert not path.exists()


def test_cli_main(tmp_path: Path, capsys):
    path = tmp_path / "opencode.json"
    main(
        [
            "--path",
            str(path),
            "--venv-python",
            "/venv/python",
            "--lang",
            "ru",
            "--env",
            "SERPENT_DATA_DIR=/data/xsdata",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["server"] == "serpent"
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["mcp"]["serpent"]
    assert entry["command"][0] == "/venv/python"
    assert entry["environment"]["SERPENT_DATA_DIR"] == "/data/xsdata"
    assert entry["environment"]["SERPENT_LANG"] == "ru"


def test_cli_rejects_bad_env(tmp_path: Path):
    with pytest.raises(SystemExit):
        main(["--path", str(tmp_path / "opencode.json"), "--venv-python", "/p", "--env", "BROKEN"])
