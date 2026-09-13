"""Create or update an OpenCode configuration with the serpent MCP server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .util import atomic_write

DEFAULT_SERVER = "serpent"
DEFAULT_SCHEMA = "https://opencode.ai/config.json"


def write_opencode_config(
    path: str | Path,
    command: list[str],
    server: str = DEFAULT_SERVER,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Merge an MCP server entry into an opencode.json file.

    Existing configuration is preserved; invalid JSON raises ValueError.
    """
    target = Path(path).expanduser()
    data: dict = {}
    existed = target.is_file()
    if existed:
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"{target} contains invalid JSON: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError(f"{target} does not contain a JSON object")
        data = loaded
    data.setdefault("$schema", DEFAULT_SCHEMA)
    mcp = data.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        raise ValueError(f"'mcp' in {target} is not a JSON object")
    entry: dict = {"type": "local", "command": list(command), "enabled": True}
    if env:
        entry["environment"] = dict(env)
    mcp[server] = entry
    if not dry_run:
        atomic_write(target, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return {
        "path": str(target),
        "server": server,
        "command": list(command),
        "existing_file_updated": existed,
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, help="opencode.json path to create or update")
    parser.add_argument("--venv-python", required=True, help="absolute path to the venv python")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="MCP server name (default: serpent)")
    parser.add_argument("--lang", default=None, help="optional SERPENT_LANG value")
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="extra environment variable for the server entry (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    env: dict[str, str] = {}
    if args.lang:
        env["SERPENT_LANG"] = args.lang
    for item in args.env:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise SystemExit(f"invalid --env value '{item}', expected KEY=VALUE")
        env[key] = value
    result = write_opencode_config(
        args.path,
        [args.venv_python, "-m", "serpent2_mcp"],
        server=args.server,
        env=env or None,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
