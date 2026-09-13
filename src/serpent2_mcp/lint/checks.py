"""Serpent-specific static checks (levels 1 and 2 of input validation)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..knowledge.store import Store
from ..knowledge.sync import load_static_cards
from .model import Card, Issue, ParsedFile, Token, split_cards_from_text
from .surface_types import SURFACE_TYPES

_NUMERIC = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eEdD][+-]?\d+)?$")
_ZAID_LIKE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")

# Card -> short description of what the first argument defines.
NAMED_CARDS: dict[str, str] = {
    "surf": "surface",
    "cell": "cell",
    "mat": "material",
    "mix": "material",
    "det": "detector",
    "ene": "energy grid",
    "datamesh": "data mesh",
    "tme": "time bin structure",
    "therm": "thermal scattering library",
    "rep": "reprocessor",
    "mflow": "material flow",
    "wwin": "weight window",
    "wwgen": "weight window mesh",
}

UNIVERSE_CARDS = {"lat", "nest", "pin", "pbed", "particle", "solid", "voro", "umsh"}

# Tokens that are legitimate alphabetic argument values almost everywhere.
COMMON_VALUES = {
    "void",
    "outside",
    "fill",
    "fiss",
    "all",
    "sum",
    "n",
    "p",
    "g",
    "yes",
    "no",
    "on",
    "off",
    "line",
    "histogram",
    "linlin",
    "linlog",
    "loglin",
    "loglog",
    "dec",
    "act",
    "pro",
    "sep",
    "name",
    "file",
    "usr",
    "none",
    "auto",
}

SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def is_numeric(text: str) -> bool:
    return bool(_NUMERIC.match(text))


@dataclass
class Index:
    card_names: set[str] = field(default_factory=set)
    set_options: set[str] = field(default_factory=set)
    params: dict[str, set[str]] = field(default_factory=dict)
    surface_types: set[str] = field(default_factory=lambda: set(SURFACE_TYPES))

    @classmethod
    def from_cards(cls, cards: list[dict]) -> "Index":
        index = cls()
        for card in cards:
            if card["kind"] == "set":
                index.set_options.add(card["name"])
                key = f"set:{card['name']}"
            else:
                index.card_names.add(card["name"])
                key = card["name"]
            index.params[key] = {p.lower() for p in card.get("params", [])}
        index.card_names.add("set")
        return index

    @classmethod
    def from_store(cls, store: Store) -> "Index":
        cards = store.cards()
        if cards:
            return cls.from_cards(cards)
        return cls.from_static()

    @classmethod
    def from_static(cls) -> "Index":
        payload = load_static_cards()
        return cls.from_cards(payload.get("cards", []))

    def card_params(self, card: Card) -> set[str]:
        return self.params.get(card.key, set())


@dataclass(slots=True)
class Definitions:
    surfaces: dict[str, Card] = field(default_factory=dict)
    cells: dict[str, Card] = field(default_factory=dict)
    materials: dict[str, Card] = field(default_factory=dict)
    detectors: dict[str, Card] = field(default_factory=dict)
    misc: dict[tuple[str, str], Card] = field(default_factory=dict)
    universes: set[str] = field(default_factory=set)
    burnable: set[str] = field(default_factory=set)


class Linter:
    """Parse an input file (with includes) and run static checks."""

    def __init__(self, index: Index, workspace: Path, max_include_depth: int = 12):
        self.index = index
        self.workspace = Path(workspace)
        self.max_include_depth = max_include_depth
        self.files: list[ParsedFile] = []
        self._seen: set[str] = set()

    # -- ingestion ---------------------------------------------------------

    def add_path(self, path: Path, display: str | None = None) -> None:
        resolved = Path(path).expanduser()
        try:
            resolved = resolved.resolve()
        except OSError:
            resolved = Path(path)
        key = str(resolved)
        if key in self._seen:
            return
        display = display or self._display(resolved)
        if len(self.files) > self.max_include_depth:
            self._issue("error", "include-depth", "include nesting too deep", display, 0)
            return
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._issue("error", "file-unreadable", f"cannot read file: {exc}", display, 0)
            return
        self._seen.add(key)
        self.add_text(text, display, base_dir=resolved.parent)

    def add_text(self, text: str, filename: str, base_dir: Path | None = None) -> None:
        parsed = split_cards_from_text(
            text, filename, self.index.card_names, self.index.set_options
        )
        self.files.append(parsed)
        base = Path(base_dir) if base_dir else self.workspace
        for card in parsed.cards:
            if card.name != "include":
                continue
            if not card.args:
                self._issue("error", "include-missing", "'include' without a file name", card.file, card.line)
                continue
            name = card.args[0].text
            candidate = (base / name).expanduser()
            if not candidate.is_file():
                candidate = (self.workspace / name).expanduser()
            if not candidate.is_file():
                self._issue(
                    "error",
                    "include-missing",
                    f"included file not found: {name}",
                    card.file,
                    card.line,
                    hint="Paths are resolved relative to the including file, then the workspace.",
                )
                continue
            self.add_path(candidate)

    def _display(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.workspace))
        except ValueError:
            return str(path)

    def _issue(self, severity: str, code: str, message: str, file: str, line: int, hint: str = "") -> None:
        self.files.append(ParsedFile(path=file, issues=[Issue(severity, code, message, file, line, hint)]))

    # -- checks ------------------------------------------------------------

    def run(self) -> list[Issue]:
        issues: list[Issue] = [issue for parsed in self.files for issue in parsed.issues]
        cards: list[Card] = [card for parsed in self.files for card in parsed.cards]
        defs = self._collect(cards)

        for card in cards:
            issues.extend(self._check_card(card, defs))

        issues.extend(self._check_global(cards, defs))
        issues.sort(key=lambda issue: (issue.file, issue.line, SEVERITY_RANK.get(issue.severity, 9), issue.code))
        return issues

    def _collect(self, cards: list[Card]) -> Definitions:
        defs = Definitions()
        for card in cards:
            args = card.args
            if card.name in NAMED_CARDS and args:
                name = args[0].text
                if card.name == "surf":
                    defs.surfaces[name] = card
                elif card.name == "cell":
                    defs.cells[name] = card
                    if len(args) > 1 and is_numeric(args[1].text):
                        defs.universes.add(_norm_num(args[1].text))
                elif card.name in {"mat", "mix"}:
                    defs.materials[name] = card
                    if card.name == "mat" and _has_burn(card):
                        defs.burnable.add(name)
                elif card.name == "det":
                    defs.detectors[name] = card
                else:
                    defs.misc[(card.name, name)] = card
            elif card.name in UNIVERSE_CARDS and args and is_numeric(args[0].text):
                defs.universes.add(_norm_num(args[0].text))
        return defs

    def _check_card(self, card: Card, defs: Definitions) -> list[Issue]:
        issues: list[Issue] = []
        name = card.name
        if name == "surf":
            issues.extend(self._check_surf(card))
        elif name == "cell":
            issues.extend(self._check_cell(card, defs))
        elif name == "mat":
            issues.extend(self._check_mat(card))
        elif name == "det":
            issues.extend(self._check_det(card, defs))
        elif name == "div":
            issues.extend(self._check_div(card, defs))
        elif name == "src":
            issues.extend(self._check_src(card))
        elif name == "set":
            issues.extend(self._check_set(card, defs))
        issues.extend(self._check_unknown_params(card))
        return issues

    # -- individual cards --------------------------------------------------

    def _check_surf(self, card: Card) -> list[Issue]:
        args = card.args
        if len(args) < 2:
            return [
                Issue(
                    "error",
                    "surf-args",
                    "'surf' needs at least a name and a surface type",
                    card.file,
                    card.line,
                )
            ]
        stype = args[1].text.lower()
        if stype not in self.index.surface_types:
            return [
                Issue(
                    "warning",
                    "surf-type",
                    f"unknown surface type '{args[1].text}'",
                    card.file,
                    args[1].line,
                    hint="See the CSG surface types appendix or call get_card('surf').",
                )
            ]
        return []

    def _check_cell(self, card: Card, defs: Definitions) -> list[Issue]:
        issues: list[Issue] = []
        args = card.args
        if len(args) < 3:
            return [
                Issue(
                    "error",
                    "cell-args",
                    "'cell' needs at least NAME, UNIVERSE and MATERIAL (or 'fill' UNIVERSE)",
                    card.file,
                    card.line,
                )
            ]
        uni = args[1]
        if not is_numeric(uni.text):
            issues.append(
                Issue(
                    "warning",
                    "cell-universe",
                    f"universe identifier '{uni.text}' is not an integer",
                    card.file,
                    uni.line,
                )
            )
        rest = args[2:]
        if rest and rest[0].lower == "fill":
            if len(rest) < 2:
                issues.append(
                    Issue("error", "cell-fill", "'fill' without a universe", card.file, rest[0].line)
                )
            else:
                fill = rest[1]
                if is_numeric(fill.text):
                    if _norm_num(fill.text) not in defs.universes and fill.text not in {"0"}:
                        issues.append(
                            Issue(
                                "error",
                                "undef-universe",
                                f"cell fills universe '{fill.text}' which is not defined",
                                card.file,
                                fill.line,
                            )
                        )
                else:
                    issues.append(
                        Issue(
                            "warning",
                            "cell-fill",
                            f"fill target '{fill.text}' is not an integer universe id",
                            card.file,
                            fill.line,
                        )
                    )
            surfaces = rest[2:]
        else:
            material = rest[0]
            if material.lower not in {"void", "outside"} and material.text not in defs.materials:
                issues.append(
                    Issue(
                        "error",
                        "undef-material",
                        f"cell uses material '{material.text}' which is not defined",
                        card.file,
                        material.line,
                        hint="Define it with 'mat'/'mix', or use 'void'/'outside'.",
                    )
                )
            surfaces = rest[1:]

        for tok in surfaces:
            text = tok.text
            if text.startswith("#"):
                ref = text[1:]
                if not tok.quoted and ref not in defs.cells:
                    issues.append(
                        Issue(
                            "error",
                            "undef-cell",
                            f"cell references undefined cell '#{ref}'",
                            card.file,
                            tok.line,
                        )
                    )
                continue
            ref = text.lstrip("+-")
            if not ref or tok.quoted:
                continue
            if is_numeric(ref):
                if _norm_num(ref) not in defs.surfaces:
                    issues.append(
                        Issue(
                            "error",
                            "undef-surface",
                            f"cell references undefined surface '{text}'",
                            card.file,
                            tok.line,
                            hint="Every surface used in a cell must be defined with a 'surf' card.",
                        )
                    )
            elif ref not in defs.surfaces:
                issues.append(
                    Issue(
                        "warning",
                        "undef-surface",
                        f"cell references surface '{text}' which is not defined",
                        card.file,
                        tok.line,
                    )
                )
        return issues

    def _check_mat(self, card: Card) -> list[Issue]:
        issues: list[Issue] = []
        args = card.args
        if len(args) < 2:
            return [
                Issue("error", "mat-args", "'mat' needs a name and a density", card.file, card.line)
            ]
        density = args[1]
        if not is_numeric(density.text):
            issues.append(
                Issue(
                    "warning",
                    "mat-density",
                    f"material density '{density.text}' is not numeric",
                    card.file,
                    density.line,
                )
            )
        signs: list[tuple[int, Token]] = []
        fractions = 0
        parse_options = {"moder", "burn", "vol", "mass", "tmp", "tms", "tft", "rgb", "fix"}
        i = 2
        while i < len(args):
            token = args[i]
            if token.lower in parse_options:
                i += 1
                continue
            if is_numeric(token.text) and i > 0:
                prev = args[i - 1]
                if not is_numeric(prev.text) and prev.lower not in parse_options:
                    value = float(token.text.replace("D", "E").replace("d", "e"))
                    signs.append((1 if value >= 0 else -1, token))
                    fractions += 1
            i += 1
        if fractions == 0:
            issues.append(
                Issue(
                    "warning",
                    "mat-empty",
                    f"material '{args[0].text}' has no nuclide composition",
                    card.file,
                    card.line,
                )
            )
        elif 1 in {s for s, _ in signs} and -1 in {s for s, _ in signs}:
            issues.append(
                Issue(
                    "error",
                    "mat-units",
                    f"material '{args[0].text}' mixes positive and negative fractions "
                    "(atomic and mass units must not be mixed)",
                    card.file,
                    card.line,
                )
            )
        return issues

    def _check_det(self, card: Card, defs: Definitions) -> list[Issue]:
        issues: list[Issue] = []
        args = card.args
        for i, token in enumerate(args[:-1]):
            low = token.lower
            ref = args[i + 1]
            if low == "dc" and ref.text not in defs.cells:
                issues.append(
                    Issue("error", "undef-cell", f"detector references undefined cell '{ref.text}'", card.file, ref.line)
                )
            elif low == "dm" and ref.text not in defs.materials:
                issues.append(
                    Issue(
                        "error",
                        "undef-material",
                        f"detector references undefined material '{ref.text}'",
                        card.file,
                        ref.line,
                    )
                )
            elif low == "dl" and is_numeric(ref.text) and _norm_num(ref.text) not in defs.universes:
                issues.append(
                    Issue(
                        "warning",
                        "undef-universe",
                        f"detector references undefined lattice universe '{ref.text}'",
                        card.file,
                        ref.line,
                    )
                )
            elif low == "du" and is_numeric(ref.text) and ref.text not in {"-1"} and _norm_num(ref.text) not in defs.universes:
                issues.append(
                    Issue(
                        "warning",
                        "undef-universe",
                        f"detector references undefined universe '{ref.text}'",
                        card.file,
                        ref.line,
                    )
                )
        return issues

    def _check_div(self, card: Card, defs: Definitions) -> list[Issue]:
        if not card.args:
            return [Issue("error", "div-args", "'div' needs a material name", card.file, card.line)]
        material = card.args[0]
        if material.text not in defs.materials:
            return [
                Issue(
                    "error",
                    "undef-material",
                    f"'div' references undefined material '{material.text}'",
                    card.file,
                    material.line,
                )
            ]
        if material.text not in defs.burnable:
            return [
                Issue(
                    "warning",
                    "div-burn",
                    f"'div' material '{material.text}' is not marked 'burn 1'",
                    card.file,
                    card.line,
                )
            ]
        return []

    def _check_src(self, card: Card) -> list[Issue]:
        issues: list[Issue] = []
        args = card.args
        has_spatial = any(t.lower in {"sp", "sc", "sm", "su", "ss"} for t in args)
        has_energy = any(t.lower in {"se", "sb", "sr", "sf", "sg"} for t in args)
        if not has_spatial:
            issues.append(
                Issue(
                    "warning",
                    "src-spatial",
                    "source has no spatial distribution (sp/sc/sm/su/ss) — default is volumetric over fissile materials",
                    card.file,
                    card.line,
                )
            )
        if not has_energy:
            issues.append(
                Issue(
                    "warning",
                    "src-energy",
                    "source has no energy definition (se/sb/sr/sf)",
                    card.file,
                    card.line,
                )
            )
        for i, token in enumerate(args):
            if token.lower != "sb" or token.quoted:
                continue
            if i + 2 >= len(args):
                issues.append(
                    Issue("warning", "sb-count", "'sb' needs NE and INTT arguments", card.file, token.line)
                )
                break
            ne_tok, intt_tok = args[i + 1], args[i + 2]
            if not (is_numeric(ne_tok.text) and is_numeric(intt_tok.text)):
                continue
            ne = int(float(ne_tok.text))
            j = i + 3
            count = 0
            while j < len(args) and is_numeric(args[j].text):
                count += 1
                j += 1
            if ne > 0 and count not in {ne, 2 * ne}:
                issues.append(
                    Issue(
                        "info",
                        "sb-count",
                        f"'sb' declares NE={ne} but {count} numeric values follow "
                        f"({count // 2} E/F pairs before the next parameter)",
                        card.file,
                        token.line,
                        hint="NE counts spectrum points; verify against the version in use.",
                    )
                )
        return issues

    def _check_set(self, card: Card, defs: Definitions) -> list[Issue]:
        issues: list[Issue] = []
        option = card.option
        if option is None:
            return issues
        if option in {"acelib", "declib", "nfylib", "sfylib", "bralib", "pdatadir"} and not card.args:
            issues.append(
                Issue("error", "set-args", f"'set {option}' needs a file path", card.file, card.line)
            )
        if option == "gcu":
            for tok in card.args:
                if is_numeric(tok.text) and tok.text not in {"-1"} and _norm_num(tok.text) not in defs.universes:
                    issues.append(
                        Issue(
                            "warning",
                            "undef-universe",
                            f"'set gcu' references universe '{tok.text}' which may not be defined",
                            card.file,
                            tok.line,
                        )
                    )
        if option == "title" and not card.args:
            issues.append(Issue("warning", "set-args", "'set title' without a title", card.file, card.line))
        return issues

    def _check_unknown_params(self, card: Card) -> list[Issue]:
        params = self.index.card_params(card)
        # Only cards whose syntax enumerates named parameters are checked, and
        # only for tokens that start a source line.
        if len(params) < 2 or card.name in {"cell", "surf", "set"}:
            return []
        issues: list[Issue] = []
        prev_line = card.line
        for token in card.args:
            line_leading = token.line != prev_line
            prev_line = token.line
            text = token.text
            if not line_leading or token.quoted or not text.isalpha():
                continue
            low = text.lower()
            if low in params or low in COMMON_VALUES:
                continue
            issues.append(
                Issue(
                    "warning",
                    "unknown-param",
                    f"unrecognized parameter '{text}' in '{card.display_name}'",
                    card.file,
                    token.line,
                    hint="If this starts a new card, check its spelling; otherwise check the card syntax.",
                )
            )
        return issues

    def _check_global(self, cards: list[Card], defs: Definitions) -> list[Issue]:
        issues: list[Issue] = []
        # Duplicate names for well-known cards.
        for card_name, label in (
            ("surf", "surface"),
            ("cell", "cell"),
            ("mat", "material"),
            ("mix", "material"),
            ("det", "detector"),
            ("ene", "energy grid"),
            ("datamesh", "data mesh"),
            ("tme", "time bin structure"),
            ("therm", "thermal scattering library"),
        ):
            seen: dict[str, Card] = {}
            for card in cards:
                if card.name != card_name or not card.args:
                    continue
                key = card.args[0].text
                if key in seen:
                    issues.append(
                        Issue(
                            "error",
                            "dup-name",
                            f"duplicate {label} name '{key}' (first defined line {seen[key].line} in {seen[key].file})",
                            card.file,
                            card.args[0].line,
                        )
                    )
                else:
                    seen[key] = card

        set_options = {card.option for card in cards if card.name == "set" and card.option}
        if "acelib" not in set_options:
            issues.append(
                Issue(
                    "warning",
                    "no-acelib",
                    "no 'set acelib' found (required unless SERPENT_ACELIB/SERPENT_DATA is set)",
                    cards[0].file if cards else "input",
                    cards[0].line if cards else 1,
                )
            )
        has_pop = "pop" in set_options
        has_nps = "nps" in set_options
        if has_pop and has_nps:
            issues.append(
                Issue(
                    "warning",
                    "both-source-modes",
                    "'set pop' (criticality) and 'set nps' (external source) are both defined",
                    cards[0].file if cards else "input",
                    cards[0].line if cards else 1,
                )
            )
        elif not has_pop and not has_nps:
            issues.append(
                Issue(
                    "warning",
                    "no-source-mode",
                    "no simulation mode defined: use 'set pop' (criticality) or 'src' + 'set nps' (external source)",
                    cards[0].file if cards else "input",
                    cards[0].line if cards else 1,
                )
            )
        if "title" not in set_options:
            issues.append(
                Issue(
                    "info",
                    "no-title",
                    "no 'set title' — recommended to label the calculation case",
                    cards[0].file if cards else "input",
                    cards[0].line if cards else 1,
                )
            )
        return issues


def _norm_num(text: str) -> str:
    try:
        value = float(text)
    except ValueError:
        return text
    if value.is_integer():
        return str(int(value))
    return text


def _has_burn(card: Card) -> bool:
    args = card.args
    for i, token in enumerate(args[:-1]):
        if token.lower == "burn":
            nxt = args[i + 1]
            return nxt.text.strip() in {"1"} or (is_numeric(nxt.text) and float(nxt.text) != 0)
    return False


def load_index(store: Store | None = None) -> Index:
    if store is not None:
        try:
            return Index.from_store(store)
        except Exception:  # noqa: BLE001
            pass
    return Index.from_static()


def lint_path(
    path: str | Path,
    index: Index | None = None,
    workspace: Path | None = None,
) -> tuple[list[Issue], list[str]]:
    """Lint an input file (following includes). Returns (issues, files)."""
    index = index or load_index()
    path = Path(path)
    workspace = Path(workspace) if workspace else path.resolve().parent
    linter = Linter(index, workspace)
    linter.add_path(path)
    issues = linter.run()
    files = [parsed.path for parsed in linter.files]
    return issues, files


def lint_text(text: str, filename: str = "input", index: Index | None = None) -> list[Issue]:
    index = index or load_index()
    linter = Linter(index, Path.cwd())
    linter.add_text(text, filename)
    return linter.run()
