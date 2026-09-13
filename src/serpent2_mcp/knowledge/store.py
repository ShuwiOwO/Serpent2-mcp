"""SQLite storage for the documentation corpus and the card index."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS pages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc TEXT NOT NULL,
    title TEXT,
    section TEXT,
    url TEXT,
    text TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS pages_key ON pages(doc, section);
CREATE TABLE IF NOT EXISTS cards(
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    syntax TEXT,
    params TEXT,
    notes TEXT,
    url TEXT,
    PRIMARY KEY (name, kind)
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts
USING fts5(doc, title, section, text, tokenize='unicode61 remove_diacritics 2');
"""


def normalize_card_name(raw: str) -> tuple[str, str | None]:
    """Return (name, kind_hint) for user input like 'surf' or 'set acelib'."""
    text = (raw or "").strip().lower()
    text = re.sub(r"^(serpent|s2)[_\s:]*", "", text)
    text = text.replace("syntax-", "").replace("syntax_", "")
    if text.startswith("set ") or text.startswith("set-") or text.startswith("set_"):
        return re.sub(r"^set[\s_-]+", "", text).strip(), "set"
    return text, None


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.fts = True
        try:
            self.conn.executescript(_FTS_SCHEMA)
        except sqlite3.OperationalError:
            self.fts = False
        self.conn.commit()

    # -- meta --------------------------------------------------------------

    def set_meta(self, values: dict[str, Any]) -> None:
        with self.conn:
            for key, value in values.items():
                self.conn.execute(
                    "INSERT INTO meta(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)),
                )

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except ValueError:
            return row["value"]

    def all_meta(self) -> dict[str, Any]:
        return {row["key"]: self.get_meta(row["key"]) for row in self.conn.execute("SELECT key FROM meta")}

    @property
    def synced_at(self) -> str | None:
        return self.get_meta("synced_at")

    @property
    def docs_version(self) -> str | None:
        return self.get_meta("docs_version")

    def is_ready(self) -> bool:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM pages").fetchone()
        return bool(row and row["n"] > 0)

    # -- pages -------------------------------------------------------------

    def replace_doc(self, doc: str, url: str, sections: list[dict[str, str]]) -> int:
        with self.conn:
            if self.fts:
                self.conn.execute("DELETE FROM pages_fts WHERE doc=?", (doc,))
            self.conn.execute("DELETE FROM pages WHERE doc=?", (doc,))
            for sec in sections:
                cur = self.conn.execute(
                    "INSERT OR REPLACE INTO pages(doc, title, section, url, text) VALUES(?,?,?,?,?)",
                    (doc, sec.get("title", ""), sec.get("section", ""), sec.get("url", url), sec.get("text", "")),
                )
                if self.fts:
                    self.conn.execute(
                        "INSERT INTO pages_fts(rowid, doc, title, section, text) VALUES(?,?,?,?,?)",
                        (cur.lastrowid, doc, sec.get("title", ""), sec.get("section", ""), sec.get("text", "")),
                    )
        return len(sections)

    def replace_cards(self, cards: list[dict[str, Any]]) -> int:
        with self.conn:
            self.conn.execute("DELETE FROM cards")
            for card in cards:
                self.conn.execute(
                    "INSERT OR REPLACE INTO cards(name, kind, syntax, params, notes, url) VALUES(?,?,?,?,?,?)",
                    (
                        card["name"],
                        card["kind"],
                        card.get("syntax", ""),
                        json.dumps(card.get("params", [])),
                        card.get("notes", ""),
                        card.get("url", ""),
                    ),
                )
        return len(cards)

    def search(self, query: str, kind: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        results: list[dict[str, Any]] = []
        docs_filter = _kind_filter(kind)
        if self.fts:
            where = ""
            params: list[Any] = [query]
            if docs_filter:
                placeholders = ",".join("?" for _ in docs_filter)
                where = f" AND p.doc IN ({placeholders})"
                params.extend(docs_filter)
            params.append(limit)
            sql = (
                "SELECT p.doc, p.title, p.section, p.url, p.text, "
                "       snippet(pages_fts, 3, '<<', '>>', ' … ', 24) AS snip, "
                "       bm25(pages_fts) AS rank "
                "FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid "
                "WHERE pages_fts MATCH ?" + where + " ORDER BY rank LIMIT ?"
            )
            try:
                rows = self.conn.execute(sql, params).fetchall()
                results = [_row_to_result(row) for row in rows]
            except sqlite3.OperationalError:
                results = []
        if results:
            return results
        return self._search_like(query, docs_filter, limit)

    def _search_like(self, query: str, docs_filter: list[str] | None, limit: int) -> list[dict[str, Any]]:
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 1]
        if not terms:
            return []
        where = " AND ".join("lower(COALESCE(title,'') || ' ' || COALESCE(section,'') || ' ' || COALESCE(text,'')) LIKE ?" for _ in terms)
        params: list[Any] = [f"%{t}%" for t in terms]
        if docs_filter:
            placeholders = ",".join("?" for _ in docs_filter)
            where += f" AND doc IN ({placeholders})"
            params.extend(docs_filter)
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT doc, title, section, url, text FROM pages WHERE {where} LIMIT ?", params
        ).fetchall()
        return [_row_to_result(row) for row in rows]

    # -- cards -------------------------------------------------------------

    def get_card(self, raw_name: str) -> dict[str, Any] | None:
        name, kind = normalize_card_name(raw_name)
        if not name:
            return None
        if kind:
            row = self.conn.execute(
                "SELECT * FROM cards WHERE name=? AND kind=?", (name, kind)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT * FROM cards WHERE name=? ORDER BY kind", (name,)).fetchone()
        if row is None and kind is None:
            row = self.conn.execute("SELECT * FROM cards WHERE name=? AND kind='set'", (name,)).fetchone()
        return _row_to_card(row) if row else None

    def cards(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind in {"card", "set"}:
            rows = self.conn.execute("SELECT * FROM cards WHERE kind=? ORDER BY name", (kind,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM cards ORDER BY kind, name").fetchall()
        return [_row_to_card(row) for row in rows]

    def card_names(self, kind: str | None = None) -> list[str]:
        if kind in {"card", "set"}:
            rows = self.conn.execute("SELECT name FROM cards WHERE kind=? ORDER BY name", (kind,)).fetchall()
        else:
            rows = self.conn.execute("SELECT name FROM cards ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    def stats(self) -> dict[str, Any]:
        pages = self.conn.execute("SELECT COUNT(*) AS n FROM pages").fetchone()["n"]
        docs = self.conn.execute("SELECT COUNT(DISTINCT doc) AS n FROM pages").fetchone()["n"]
        cards = self.conn.execute("SELECT COUNT(*) AS n FROM cards").fetchone()["n"]
        return {
            "pages": pages,
            "docs": docs,
            "cards": cards,
            "fts5": self.fts,
            "synced_at": self.synced_at,
            "docs_version": self.docs_version,
            "db_path": str(self.path),
        }

    def close(self) -> None:
        self.conn.close()


def _kind_filter(kind: str | None) -> list[str] | None:
    if not kind or kind == "all":
        return None
    if kind in {"card", "cards", "syntax"}:
        return ["syntax"]
    if kind in {"wiki"}:
        return ["wiki/input_syntax_manual", "wiki/pitfalls", "wiki/output_parameters", "wiki/examples", "wiki/install"]
    if kind in {"guide", "user_guide"}:
        return [d for d in _GUIDE_DOCS]
    if kind == "extra":
        return [d for d in _EXTRA_DOCS]
    return None


_GUIDE_DOCS = [
    "user_guide/general_input",
    "user_guide/geometry",
    "user_guide/materials",
    "user_guide/sources",
    "user_guide/detectors",
    "user_guide/nuclear_data",
    "user_guide/running_overview",
    "user_guide/criticality_simulation",
    "user_guide/external_source_simulation",
    "user_guide/burnup_calculation",
    "user_guide/gc_generation",
    "user_guide/automated_gc",
    "user_guide/output_files",
    "user_guide/standard_output",
    "user_guide/detector_output",
    "user_guide/burnup_output",
    "user_guide/nuc_mat_output",
    "user_guide/other_output",
    "user_guide/history_output",
    "user_guide/multiphys",
    "user_guide/variance_reduction",
    "user_guide/sensitivity",
    "user_guide/calculation_options",
    "user_guide/parallelisation",
    "user_guide/statistics",
    "user_guide/geometry_plotting",
    "user_guide/mesh_plotting",
    "user_guide/builtin_tools",
    "user_guide/mc_volumes",
    "user_guide/normalisation",
    "installation/data_libraries",
]

_EXTRA_DOCS = [
    "extra/csg_surfaces",
    "extra/lattice_types",
    "extra/endf_reactions",
    "extra/datamesh",
    "extra/units",
    "extra/reserved_card_names",
    "extra/fallbacks",
    "extra/bugs",
    "extra/isotope_fractions",
    "data/interaction_data",
    "data/input_data",
    "tutorial/index",
]


def _row_to_result(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    text = row["text"] or ""
    snippet = row["snip"] if "snip" in keys and row["snip"] else text[:400]
    if snippet == text[:400]:
        snippet = re.sub(r"\s+", " ", snippet).strip()
    return {
        "doc": row["doc"],
        "title": row["title"],
        "section": row["section"],
        "url": row["url"],
        "snippet": snippet,
        "text": text,
    }


def _row_to_card(row: sqlite3.Row) -> dict[str, Any]:
    try:
        params = json.loads(row["params"] or "[]")
    except ValueError:
        params = []
    return {
        "name": row["name"],
        "kind": row["kind"],
        "syntax": row["syntax"] or "",
        "params": params,
        "notes": row["notes"] or "",
        "url": row["url"] or "",
    }
