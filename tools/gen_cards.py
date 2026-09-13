#!/usr/bin/env python3
"""Regenerate the bundled static card index from the official documentation.

Maintainer script.

Usage:
    .venv/bin/python tools/gen_cards.py                     # notes up to 800 chars
    .venv/bin/python tools/gen_cards.py --no-notes          # facts only (for public repos)
    .venv/bin/python tools/gen_cards.py --max-notes 0       # same as --no-notes
    .venv/bin/python tools/gen_cards.py --output /tmp/cards.json

The card names, parameter names, syntax signatures and links are factual API
data. The `notes` field contains excerpts from the official documentation
(© VTT) and should be omitted when redistributing the repository publicly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from serpent2_mcp.knowledge.sync import detect_docs_version, parse_objects_inv, parse_syntax_cards  # noqa: E402
from serpent2_mcp.util import http_get, http_get_text, now_iso  # noqa: E402

BASE = "https://serpent.vtt.fi/docs"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-notes", type=int, default=800, help="max characters of documentation notes (0 = none)")
    parser.add_argument("--no-notes", action="store_true", help="strip all documentation excerpts")
    parser.add_argument("--output", type=Path, default=None, help="output path (default: bundled package path)")
    args = parser.parse_args(argv)

    max_notes = 0 if args.no_notes else max(0, args.max_notes)

    syntax_url = f"{BASE}/syntax/index.html"
    labels: list[tuple[str, str]] = []
    try:
        labels = parse_objects_inv(http_get(f"{BASE}/objects.inv", timeout=60))
    except Exception as exc:  # noqa: BLE001
        print(f"objects.inv failed: {exc}")

    print(f"fetching {syntax_url} ...")
    html = http_get_text(syntax_url, timeout=240)
    cards, _sections = parse_syntax_cards(html, syntax_url, labels)

    version = None
    try:
        version = detect_docs_version(http_get_text(f"{BASE}/index.html", timeout=60))
    except Exception as exc:  # noqa: BLE001
        print(f"version detection failed: {exc}")

    packaged = []
    for card in cards:
        packaged.append(
            {
                "name": card["name"],
                "kind": card["kind"],
                "syntax": card["syntax"],
                "params": card["params"],
                "notes": card["notes"][:max_notes] if max_notes else "",
                "url": card["url"],
            }
        )

    payload = {
        "generated_at": now_iso(),
        "docs_version": version,
        "source_url": syntax_url,
        "count": len(packaged),
        "includes_doc_excerpts": bool(max_notes),
        "cards": packaged,
    }
    out = args.output or (ROOT / "src" / "serpent2_mcp" / "knowledge" / "cards_static.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    flavor = f"notes<={max_notes}" if max_notes else "no notes"
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(packaged)} cards, docs {version}, {flavor})")

    for name in ("surf", "cell", "mat", "src", "det"):
        match = next((c for c in packaged if c["kind"] == "card" and c["name"] == name), None)
        if match:
            print(f"  {name}: {match['syntax'][:120]}  params={match['params'][:8]}")
    match = next((c for c in packaged if c["kind"] == "set" and c["name"] == "acelib"), None)
    if match:
        print(f"  set acelib: {match['syntax'][:120]}")


if __name__ == "__main__":
    main()
