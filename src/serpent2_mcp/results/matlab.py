"""Parser for the Matlab-style output files written by Serpent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eEdD][+-]?\d+)?$")
_ASSIGN = re.compile(r"([A-Za-z_]\w*)\s*(\(\s*\d+\s*,\s*:\s*\))?\s*=\s*")


@dataclass
class MatValue:
    kind: str  # scalar | matrix | string | strings
    value: Any
    line: int = 0

    def scalar(self) -> float | None:
        if self.kind == "scalar":
            return float(self.value)
        if self.kind == "matrix" and self.value and len(self.value[0]) == 1:
            return float(self.value[0][0])
        return None

    def first_row(self) -> list[float]:
        if self.kind == "matrix" and self.value:
            return list(self.value[0])
        if self.kind == "scalar":
            return [float(self.value)]
        return []

    def rows(self) -> list[list[float]]:
        if self.kind == "matrix":
            return [list(row) for row in self.value]
        if self.kind == "scalar":
            return [[float(self.value)]]
        return []

    def mean_err(self, row: int = 0) -> tuple[float | None, float | None]:
        rows = self.rows()
        if not rows or row >= len(rows):
            return None, None
        values = rows[row]
        mean = values[0] if values else None
        err = values[1] if len(values) > 1 else None
        return mean, err


def _strip_comments(text: str) -> str:
    out_lines = []
    for line in text.splitlines():
        in_string = False
        cut = len(line)
        for i, ch in enumerate(line):
            if ch == "'":
                in_string = not in_string
            elif ch == "%" and not in_string:
                cut = i
                break
        out_lines.append(line[:cut])
    return "\n".join(out_lines)


def _to_float(token: str) -> float:
    token = token.replace("D", "E").replace("d", "e")
    if token.lower() in {"nan", "-nan"}:
        return float("nan")
    if token.lower() in {"inf", "+inf"}:
        return float("inf")
    if token.lower() == "-inf":
        return float("-inf")
    return float(token)


def _parse_matrix(content: str) -> tuple[str, Any]:
    rows_raw = [row for row in re.split(r"[;\n]+", content.strip()) if row.strip()]
    rows: list[list[float]] = []
    string_rows: list[list[str]] = []
    for row in rows_raw:
        if "'" in row:
            string_rows.append(re.findall(r"'([^']*)'", row))
            continue
        tokens = row.split()
        rows.append([_to_float(token) for token in tokens])
    if string_rows and not rows:
        return "strings", [item for row in string_rows for item in row]
    if rows:
        return "matrix", rows
    return "string", content.strip()


def parse_matlab(text: str) -> dict[str, MatValue]:
    text = _strip_comments(text)
    result: dict[str, MatValue] = {}
    i = 0
    n = len(text)
    while i < n:
        match = _ASSIGN.search(text, i)
        if not match:
            break
        name = match.group(1)
        indexed = bool(match.group(2))
        line = text.count("\n", 0, match.start()) + 1
        j = match.end()
        if j >= n:
            break
        ch = text[j]
        if ch == "'":
            k = j + 1
            parts: list[str] = []
            while k < n:
                if text[k] == "'" and k + 1 < n and text[k + 1] == "'":
                    parts.append("'")
                    k += 2
                    continue
                if text[k] == "'":
                    break
                parts.append(text[k])
                k += 1
            value = "".join(parts)
            k += 1
            while k < n and text[k] in " \t\r\n":
                k += 1
            if k < n and text[k] == ";":
                k += 1
            if indexed:
                existing = result.get(name)
                items = list(existing.value) if existing and existing.kind == "strings" else []
                items.append(value.strip())
                result[name] = MatValue("strings", items, line)
            else:
                result[name] = MatValue("string", value, line)
            i = k
            continue
        if ch == "[":
            end = text.find("]", j)
            if end == -1:
                break
            kind, value = _parse_matrix(text[j + 1:end])
            k = end + 1
            while k < n and text[k] in " \t\r\n":
                k += 1
            if k < n and text[k] == ";":
                k += 1
            result[name] = MatValue(kind, value, line)
            i = k
            continue
        end = text.find(";", j)
        if end == -1:
            end = n
        raw = text[j:end].strip()
        try:
            value = _to_float(raw)
            result[name] = MatValue("scalar", value, line)
        except ValueError:
            result[name] = MatValue("string", raw, line)
        i = end + 1
    return result


def parse_matlab_file(path: str | Path) -> dict[str, MatValue]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_matlab(text)


def parse_matlab_file_limited(
    path: str | Path,
    max_bytes: int | None = None,
    max_rows: int = 500,
    info: dict | None = None,
) -> dict[str, MatValue]:
    """Parse a Matlab file, streaming when it is larger than ``max_bytes``."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if max_bytes is not None and size > max_bytes:
        if info is not None:
            info["file_size"] = size
            info["streamed"] = True
        return parse_matlab_stream(path, max_rows=max_rows, info=info)
    if info is not None:
        info["file_size"] = size
        info["streamed"] = False
    return parse_matlab_file(path)


_ASSIGN_LINE = re.compile(r"^\s*([A-Za-z_]\w*)\s*(\(\s*\d+\s*,\s*:\s*\))?\s*=\s*(.*)$")


def parse_matlab_stream(
    path: str | Path,
    max_rows: int = 500,
    info: dict | None = None,
) -> dict[str, MatValue]:
    """Line-oriented parser with per-variable row limits (for huge files)."""
    result: dict[str, MatValue] = {}
    truncated: list[str] = []
    name: str | None = None
    indexed = False
    collecting = False
    rows: list[str] = []

    def finish_block() -> None:
        nonlocal name, indexed, collecting, rows
        assert name is not None
        kind, value = _parse_matrix("\n".join(rows))
        if indexed:
            existing = result.get(name)
            items = list(existing.value) if existing and existing.kind == "strings" else []
            if kind == "strings":
                items.extend(value)
            elif kind == "string":
                items.append(str(value).strip())
            result[name] = MatValue("strings", items)
        else:
            result[name] = MatValue(kind, value)
        name = None
        indexed = False
        collecting = False
        rows = []

    with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if collecting:
                if "]" in line:
                    rows.append(line.split("]", 1)[0])
                    finish_block()
                    continue
                if len(rows) < max_rows:
                    rows.append(line)
                elif name and name not in truncated:
                    truncated.append(name)
                continue
            match = _ASSIGN_LINE.match(line)
            if not match:
                continue
            name = match.group(1)
            indexed = bool(match.group(2))
            rhs = match.group(3).strip()
            if rhs.startswith("["):
                collecting = True
                rows = []
                body = rhs[1:]
                if "]" in body:
                    rows.append(body.split("]", 1)[0])
                    finish_block()
                elif body:
                    rows.append(body)
            elif "'" in rhs:
                strings = re.findall(r"'([^']*)'", rhs)
                if strings:
                    result[name] = MatValue("string", strings[0])
            else:
                raw = rhs.split(";", 1)[0].strip()
                try:
                    result[name] = MatValue("scalar", _to_float(raw))
                except ValueError:
                    if raw:
                        result[name] = MatValue("string", raw)
    if info is not None:
        info["truncated"] = truncated
    return result
