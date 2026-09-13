"""Download and index the official Serpent documentation.

The corpus is stored locally (SQLite + FTS5) so that the model can query exact
card syntax and guide sections. Nothing is bundled with the repository except a
compact static card index and the hand-written primer, so the server works
offline from the first start.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup

from .. import __version__
from ..config import Settings, load_settings
from ..util import http_get, http_get_text, now_iso, stderr_log
from .store import Store

# Documentation pages worth indexing (Sphinx site).
SPHINX_PAGES: dict[str, str] = {
    "index": "index.html",
    "user_guide/general_input": "user_guide/general_input.html",
    "user_guide/geometry": "user_guide/geometry.html",
    "user_guide/materials": "user_guide/materials.html",
    "user_guide/sources": "user_guide/sources.html",
    "user_guide/detectors": "user_guide/detectors.html",
    "user_guide/nuclear_data": "user_guide/nuclear_data.html",
    "user_guide/running_overview": "user_guide/running_overview.html",
    "user_guide/criticality_simulation": "user_guide/criticality_simulation.html",
    "user_guide/external_source_simulation": "user_guide/external_source_simulation.html",
    "user_guide/burnup_calculation": "user_guide/burnup_calculation.html",
    "user_guide/gc_generation": "user_guide/gc_generation.html",
    "user_guide/automated_gc": "user_guide/automated_gc.html",
    "user_guide/output_files": "user_guide/output_files.html",
    "user_guide/normalisation": "user_guide/normalisation.html",
    "user_guide/nuc_mat_output": "user_guide/nuc_mat_output.html",
    "user_guide/standard_output": "user_guide/standard_output.html",
    "user_guide/detector_output": "user_guide/detector_output.html",
    "user_guide/history_output": "user_guide/history_output.html",
    "user_guide/burnup_output": "user_guide/burnup_output.html",
    "user_guide/coefout": "user_guide/coefout.html",
    "user_guide/mdepout": "user_guide/mdepout.html",
    "user_guide/other_output": "user_guide/other_output.html",
    "user_guide/multiphys": "user_guide/multiphys.html",
    "user_guide/variance_reduction": "user_guide/variance_reduction.html",
    "user_guide/sensitivity": "user_guide/sensitivity.html",
    "user_guide/calculation_options": "user_guide/calculation_options.html",
    "user_guide/parallelisation": "user_guide/parallelisation.html",
    "user_guide/statistics": "user_guide/statistics.html",
    "user_guide/geometry_plotting": "user_guide/geometry_plotting.html",
    "user_guide/mesh_plotting": "user_guide/mesh_plotting.html",
    "user_guide/builtin_tools": "user_guide/builtin_tools.html",
    "user_guide/mc_volumes": "user_guide/mc_volumes.html",
    "user_guide/matpos": "user_guide/matpos.html",
    "user_guide/check_stl": "user_guide/check_stl.html",
    "installation/data_libraries": "installation/data_libraries.html",
    "data/interaction_data": "data/interaction_data.html",
    "data/input_data": "data/input_data.html",
    "extra/csg_surfaces": "extra/csg_surfaces.html",
    "extra/lattice_types": "extra/lattice_types.html",
    "extra/endf_reactions": "extra/endf_reactions.html",
    "extra/datamesh": "extra/datamesh.html",
    "extra/units": "extra/units.html",
    "extra/reserved_card_names": "extra/reserved_card_names.html",
    "extra/fallbacks": "extra/fallbacks.html",
    "extra/bugs": "extra/bugs.html",
    "extra/isotope_fractions": "extra/isotope_fractions.html",
    "extra/pitfalls": "extra/pitfalls.html",
    "tutorial/index": "tutorial/index.html",
}

# Wiki pages (MediaWiki) that complement the new docs.
WIKI_PAGES: dict[str, str] = {
    "wiki/input_syntax_manual": "Input_syntax_manual",
    "wiki/pitfalls": "Pitfalls_and_troubleshooting",
    "wiki/output_parameters": "Output_parameters",
    "wiki/examples": "Collection_of_example_input_files",
    "wiki/install": "Installing_and_running_Serpent",
    "wiki/validation": "Validation_and_verification",
}

WIKI_BASE = "https://serpent.vtt.fi/mediawiki/index.php/"

_SKIP_SECTION_IDS = {"syntax-manual", "syntax-manual-cards", "syntax-manual-options", "syntax-cards", "syntax-options"}
_SKIP_NAMES = {
    "manual",
    "manual_cards",
    "manual_options",
    "cards",
    "options",
    "set",
}

# Cards that exist in older Serpent versions but no longer have a section in the
# current syntax manual. Kept known so that linters accept legacy inputs.
LEGACY_CARDS = {
    "dtrans": "Obsolete; use 'trans d' instead (legacy geometry transformation).",
    "ftrans": "Obsolete; use 'trans f' instead (legacy fission source transformation).",
    "strans": "Legacy surface transformation card; use the trans card instead.",
    "umsh": "Unstructured mesh geometry definition (see user guide).",
    "utrans": "Transformation for unstructured mesh geometry (see trans card).",
}

_sync_lock = threading.Lock()
SYNC_STATE: dict[str, Any] = {"state": "idle", "detail": "", "started": None, "finished": None}

PROGRESS: Callable[[str], None] = stderr_log


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def _section_text(section) -> str:
    clone = BeautifulSoup(str(section), "html.parser")
    for tag in clone.find_all(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = clone.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def parse_sections(html: str, page_url: str) -> list[dict[str, str]]:
    """Split a Sphinx page into leaf sections."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find(attrs={"role": "main"}) or soup.find("div", class_="document") or soup
    sections: list[dict[str, str]] = []
    for section in main.find_all("section", id=True):
        if section.find("section") is not None:
            continue
        title_el = section.find(re.compile(r"^h[1-6]$"))
        title = title_el.get_text(" ", strip=True) if title_el else section.get("id", "")
        text = _section_text(section)
        if len(text) < 30:
            continue
        sections.append(
            {
                "section": section.get("id", title),
                "title": title,
                "url": f"{page_url}#{section.get('id')}",
                "text": text,
            }
        )
    if not sections:
        text = _section_text(main)
        if text:
            sections.append({"section": "page", "title": "", "url": page_url, "text": text})
    return sections


def parse_objects_inv(data: bytes) -> list[tuple[str, str]]:
    """Return (label, uri) pairs from a Sphinx objects.inv file."""
    import zlib

    try:
        parts = data.split(b"\n", 4)
        body = zlib.decompress(parts[4]).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return []
    out: list[tuple[str, str]] = []
    for line in body.splitlines():
        fields = line.split(" ", 4)
        if len(fields) >= 5 and fields[1] == "std:label":
            out.append((fields[0], fields[3]))
    return out


def parse_syntax_cards(
    html: str,
    page_url: str,
    labels: list[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Parse the input syntax manual into card records and searchable sections.

    Card and option names come from the ``objects.inv`` labels (authoritative,
    complete), while syntax strings, parameter keywords and notes are read from
    the page sections. Sections that carry a syntax paragraph but are not in
    ``objects.inv`` are still indexed (covers legacy cards such as ``strans``).
    """
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find(attrs={"role": "main"}) or soup

    parsed_sections: dict[str, dict[str, Any]] = {}
    for section in main.find_all("section", id=True):
        syntax_p = section.find("p", class_="input-syntax")
        if syntax_p is None:
            continue
        sid = section.get("id", "")
        if sid in _SKIP_SECTION_IDS or sid.startswith("input-"):
            continue
        title_el = section.find(re.compile(r"^h[1-6]$"))
        title = title_el.get_text(" ", strip=True) if title_el else sid
        anchor = None
        target = section.find_previous("span", class_="target", id=re.compile(r"^syntax-"))
        if target is not None and target.find_next("section") is section:
            anchor = target.get("id")
        anchor = anchor or f"syntax-{sid}"
        syntax = re.sub(r"\s+", " ", syntax_p.get_text(" ", strip=True))
        params: list[str] = []
        for strong in syntax_p.find_all("strong"):
            token = strong.get_text(" ", strip=True).lower()
            if token.startswith("set "):
                token = token[len("set "):]
            for piece in token.split():
                if piece.isalpha() and piece not in {"set", sid, sid.replace("-", ""), sid.removeprefix("set-")} and piece not in params:
                    params.append(piece)
        parsed_sections[sid] = {
            "sid": sid,
            "title": title,
            "anchor": anchor,
            "syntax": syntax,
            "params": params,
            "text": _section_text(section),
        }

    def find_section(name: str, kind: str) -> dict[str, Any] | None:
        candidates = [f"{name.replace('_', '-')}"]
        if kind == "set":
            candidates = [f"set-{name.replace('_', '-')}", f"set-{name}", name]
        for candidate in candidates:
            if candidate in parsed_sections:
                return parsed_sections[candidate]
        return None

    cards: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_card(
        name: str,
        kind: str,
        section: dict[str, Any] | None,
        label_uri: str | None,
        fallback_notes: str = "",
    ) -> None:
        key = (name, kind)
        if key in seen or not name:
            return
        seen.add(key)
        anchor = section["anchor"] if section else f"syntax-{kind}-{name}" if kind == "set" else f"syntax-{name}"
        if label_uri and "#" in label_uri:
            anchor = label_uri.split("#", 1)[1]
        text = section["text"] if section else fallback_notes
        cards.append(
            {
                "name": name,
                "kind": kind,
                "syntax": section["syntax"] if section else "",
                "params": section["params"] if section else [],
                "notes": text[:1500],
                "url": f"{page_url}#{anchor}",
            }
        )

    if labels:
        for label, uri in labels:
            if label.startswith("syntax_set_"):
                name = label[len("syntax_set_"):]
                if name not in _SKIP_NAMES:
                    add_card(name, "set", find_section(name, "set"), uri)
            elif label.startswith("syntax_"):
                name = label[len("syntax_"):]
                if name not in _SKIP_NAMES:
                    add_card(name, "card", find_section(name, "card"), uri)

    for sid, section in parsed_sections.items():
        is_set = sid.startswith("set-")
        name = sid[len("set-"):] if is_set else sid
        add_card(name, "set" if is_set else "card", section, None)

    for name, note in LEGACY_CARDS.items():
        add_card(name, "card", None, None, fallback_notes=note)

    cards.sort(key=lambda c: (c["kind"], c["name"]))

    sections: list[dict[str, str]] = []
    for card in cards:
        section_lookup = find_section(card["name"], card["kind"])
        text = section_lookup["text"] if section_lookup else card["notes"]
        if not text:
            text = card["syntax"]
        sections.append(
            {
                "section": card["url"].split("#", 1)[-1],
                "title": f"set {card['name']}" if card["kind"] == "set" else f"card {card['name']}",
                "url": card["url"],
                "text": text,
            }
        )
    return cards, sections


def parse_wiki_page(html: str, page_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find(id="mw-content-text") or soup.find(id="content") or soup
    for tag in content.find_all(["script", "style"]):
        tag.decompose()
    for tag in content.find_all(class_=re.compile("navbox|toc|mw-editsection|reference")):
        tag.decompose()
    sections: list[dict[str, str]] = []
    for heading in content.find_all(re.compile(r"^h[123]$")):
        title = heading.get_text(" ", strip=True)
        parts: list[str] = []
        for sibling in heading.next_siblings:
            name = getattr(sibling, "name", None)
            if name and re.match(r"^h[123]$", name):
                break
            if name:
                piece = sibling.get_text(" ", strip=True)
                if piece:
                    parts.append(piece)
        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if len(text) >= 40:
            anchor = heading.find("span", id=True)
            section_id = anchor.get("id") if anchor else title.lower().replace(" ", "_")[:80]
            sections.append(
                {
                    "section": section_id,
                    "title": title,
                    "url": f"{page_url}#{section_id}",
                    "text": text,
                }
            )
    if not sections:
        text = re.sub(r"\s+", " ", content.get_text(" ", strip=True)).strip()
        sections.append({"section": "page", "title": "", "url": page_url, "text": text})
    return sections


def detect_docs_version(html: str) -> str | None:
    text = html
    if "<" in html:
        try:
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        except Exception:  # noqa: BLE001
            pass
    match = re.search(r"Document version\s*[:\s]\s*([0-9]+\.[0-9]+\.[0-9]+)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Static card index (bundled fallback)
# ---------------------------------------------------------------------------


def static_cards_path() -> Path:
    return Path(__file__).with_name("cards_static.json")


def load_static_cards() -> dict[str, Any]:
    path = static_cards_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"cards": [], "docs_version": None, "generated_at": None, "source_url": None}


def seed_store_cards(store: Store) -> None:
    """Populate the card table from the bundled index when the cache is empty."""
    if store.card_names():
        return
    payload = load_static_cards()
    cards = payload.get("cards") or []
    if cards:
        store.replace_cards(cards)
        if payload.get("docs_version"):
            store.set_meta({"docs_version_static": payload["docs_version"]})


# ---------------------------------------------------------------------------
# Synchronization
# ---------------------------------------------------------------------------


def db_path(settings: Settings) -> Path:
    return settings.cache_dir / "docs" / "serpent2.sqlite3"


def is_fresh(store: Store, settings: Settings) -> bool:
    synced_at = store.synced_at
    if not synced_at:
        return False
    try:
        when = time.mktime(time.strptime(synced_at[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return False
    age_days = (time.time() - when) / 86400.0
    return age_days < settings.docs_max_age_days


def sync(settings: Settings, force: bool = False, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    log = log or stderr_log
    store = Store(db_path(settings))
    try:
        seed_store_cards(store)
        if not force and is_fresh(store, settings) and store.is_ready():
            return {"status": "fresh", **store.stats()}

        base = settings.docs_url.rstrip("/")
        errors: list[str] = []
        counts: dict[str, int] = {}

        log("syncing Serpent documentation ...")
        version = None
        try:
            index_html = http_get_text(f"{base}/index.html", timeout=60)
            version = detect_docs_version(index_html)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"index: {exc}")

        # Syntax manual (cards + full sections)
        labels: list[tuple[str, str]] = []
        try:
            inventory = http_get(f"{base}/objects.inv", timeout=60)
            labels = parse_objects_inv(inventory)
            log(f"  objects.inv: {len(labels)} labels")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"objects.inv: {exc}")
        try:
            syntax_html = http_get_text(f"{base}/syntax/index.html", timeout=180)
            cards, sections = parse_syntax_cards(syntax_html, f"{base}/syntax/index.html", labels)
            store.replace_cards(cards)
            counts["syntax"] = store.replace_doc(
                "syntax", f"{base}/syntax/index.html", sections
            )
            log(f"  syntax manual: {len(cards)} cards, {len(sections)} sections")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"syntax: {exc}")
            log(f"  syntax manual FAILED: {exc}")

        for doc, path in SPHINX_PAGES.items():
            url = f"{base}/{path}"
            try:
                html = http_get_text(url, timeout=90)
                sections = parse_sections(html, url)
                counts[doc] = store.replace_doc(doc, url, sections)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{doc}: {exc}")
                continue

        for doc, title in WIKI_PAGES.items():
            url = f"{WIKI_BASE}{title.replace(' ', '_')}"
            try:
                html = http_get_text(url, timeout=90)
                sections = parse_wiki_page(html, url)
                counts[doc] = store.replace_doc(doc, url, sections)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{doc}: {exc}")
                continue

        store.set_meta(
            {
                "synced_at": now_iso(),
                "docs_version": version,
                "base_url": base,
                "counts": counts,
                "errors": errors,
                "server_version": __version__,
            }
        )
        stats = store.stats()
        log(f"documentation sync complete: {stats}")
        return {"status": "synced", **stats, "errors": errors}
    finally:
        store.close()


def sync_status(settings: Settings) -> dict[str, Any]:
    state = dict(SYNC_STATE)
    try:
        store = Store(db_path(settings))
        state.update(store.stats())
        store.close()
    except Exception as exc:  # noqa: BLE001
        state["error"] = str(exc)
    return state


def ensure_sync_async(settings: Settings, force: bool = False) -> None:
    """Start a background sync if the cache is missing or stale."""

    def worker(force_sync: bool) -> None:
        with _sync_lock:
            SYNC_STATE.update({"state": "running", "detail": "syncing docs", "started": now_iso(), "finished": None})
            try:
                result = sync(settings, force=force_sync)
                SYNC_STATE.update(
                    {"state": "done", "detail": result.get("status", "done"), "finished": now_iso(), "result": result}
                )
            except Exception as exc:  # noqa: BLE001
                SYNC_STATE.update({"state": "error", "detail": str(exc), "finished": now_iso()})
                stderr_log(f"docs sync failed: {exc}")

    store = Store(db_path(settings))
    seed_store_cards(store)
    fresh = is_fresh(store, settings) and store.is_ready()
    store.close()
    if fresh and not force:
        return
    if SYNC_STATE.get("state") == "running":
        return
    threading.Thread(target=worker, args=(force,), daemon=True, name="serpent-docs-sync").start()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sync the Serpent documentation cache.")
    parser.add_argument("--force", action="store_true", help="re-download everything")
    parser.add_argument("--workspace", default=None, help="workspace directory (default: cwd)")
    parser.add_argument("--status", action="store_true", help="print cache status and exit")
    args = parser.parse_args(argv)

    settings = load_settings(args.workspace)
    if args.status:
        print(json.dumps(sync_status(settings), indent=2, ensure_ascii=False))
        return
    result = sync(settings, force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
