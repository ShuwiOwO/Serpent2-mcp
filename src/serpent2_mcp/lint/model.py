"""Input tokenizer and card splitter for Serpent input files."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Issue:
    severity: str  # "error" | "warning" | "info"
    code: str
    message: str
    file: str
    line: int
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "hint": self.hint,
        }


@dataclass
class Token:
    text: str
    line: int
    quoted: bool = False

    @property
    def lower(self) -> str:
        return self.text.lower()


@dataclass
class Card:
    name: str
    option: str | None
    args: list[Token]
    file: str
    line: int

    @property
    def key(self) -> str:
        if self.name == "set" and self.option:
            return f"set:{self.option}"
        return self.name

    @property
    def display_name(self) -> str:
        if self.name == "set" and self.option:
            return f"set {self.option}"
        return self.name


@dataclass
class ParsedFile:
    path: str
    cards: list[Card] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)


def tokenize(text: str, filename: str) -> tuple[list[Token], list[Issue]]:
    tokens: list[Token] = []
    issues: list[Issue] = []
    buf: list[str] = []
    buf_line = 1
    line = 1
    i = 0
    n = len(text)

    def flush() -> None:
        nonlocal buf
        if buf:
            tokens.append(Token("".join(buf), buf_line))
            buf = []

    while i < n:
        ch = text[i]
        if ch == "\n":
            flush()
            line += 1
            i += 1
            continue
        if ch == "%":
            flush()
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            flush()
            start = line
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                if text[i] == "\n":
                    line += 1
                i += 1
            if i + 1 >= n:
                issues.append(
                    Issue("error", "syntax", "unterminated block comment '/*'", filename, start)
                )
                break
            i += 2
            continue
        if ch == '"':
            flush()
            start = line
            i += 1
            parts: list[str] = []
            while i < n and text[i] != '"':
                if text[i] == "\n":
                    parts.append(" ")
                    line += 1
                else:
                    parts.append(text[i])
                i += 1
            if i >= n:
                issues.append(
                    Issue("error", "syntax", "unterminated quoted string", filename, start)
                )
                tokens.append(Token("".join(parts), start, quoted=True))
                break
            i += 1
            tokens.append(Token("".join(parts), start, quoted=True))
            continue
        if ch.isspace():
            flush()
            i += 1
            continue
        if not buf:
            buf_line = line
        buf.append(ch)
        i += 1
    flush()
    return tokens, issues


def split_cards(
    tokens: list[Token],
    card_names: set[str],
    set_options: set[str],
    filename: str,
) -> tuple[list[Card], list[Issue]]:
    """Split a token stream into cards using reserved card names as boundaries."""
    cards: list[Card] = []
    issues: list[Issue] = []
    current: Card | None = None
    i = 0

    def start(name: str, line: int, option: str | None = None) -> None:
        nonlocal current
        current = Card(name=name, option=option, args=[], file=filename, line=line)
        cards.append(current)

    while i < len(tokens):
        tok = tokens[i]
        low = tok.lower
        if not tok.quoted and low in card_names:
            if low == "set":
                option: str | None = None
                if i + 1 >= len(tokens):
                    issues.append(
                        Issue("error", "syntax", "'set' card without an option at end of input", filename, tok.line)
                    )
                else:
                    nxt = tokens[i + 1]
                    i += 1
                    if nxt.quoted:
                        option = nxt.text.lower()
                    else:
                        option = nxt.lower
                        if option not in set_options and option not in card_names:
                            issues.append(
                                Issue(
                                    "warning",
                                    "unknown-set-option",
                                    f"unknown set option '{nxt.text}'",
                                    filename,
                                    nxt.line,
                                    hint="Check the option name with get_card('set <option>').",
                                )
                            )
                start("set", tok.line, option)
            else:
                start(low, tok.line)
        else:
            if current is None:
                issues.append(
                    Issue(
                        "error",
                        "syntax",
                        f"argument '{tok.text}' appears before any input card",
                        filename,
                        tok.line,
                        hint="The file must start with a card name, for example 'set title ...'.",
                    )
                )
                start("_orphan", tok.line)
            current.args.append(tok)
        i += 1

    return cards, issues


def split_cards_from_text(
    text: str, filename: str, card_names: set[str], set_options: set[str]
) -> ParsedFile:
    tokens, issues = tokenize(text, filename)
    cards, split_issues = split_cards(tokens, card_names, set_options, filename)
    return ParsedFile(path=filename, cards=cards, issues=issues + split_issues)
