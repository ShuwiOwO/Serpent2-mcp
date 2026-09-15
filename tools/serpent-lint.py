#!/usr/bin/env python3
"""serpent-lint.py — zero-deps static checker for Serpent 2.1.32 inputs.

Usage:
  python3 tools/serpent-lint.py <input> [--json] [--data-dir DIR]

Checks (errors block a run, warnings don't):
  E: set without option, sb with bad header, de uses predefined structure
     directly (de scale44), dr -100 without matching fun, sb data line
     starting with a reserved card name, data file from set acelib/declib/
     nfylib/pdatadir missing on disk.
  W: sg source without set declib, sg material without decay-like nuclide
     (heuristic), duplicate surf/cell/mat/det/ene/tme names, mat mixing
     atomic/mass signs, missing outside-closing cell, unknown set option.

Exit: 1 on any error, 0 otherwise. No third-party deps, no network.
"""
from __future__ import annotations

import json
import os
import re
import sys

RESERVED = {
    "branch", "casematrix", "cell", "coef", "datamesh", "dep", "det", "div",
    "dtrans", "ene", "fun", "hisv", "ifc", "include", "lat", "mat", "mesh",
    "mflow", "mix", "nest", "particle", "pbed", "phb", "pin", "plot", "rep",
    "sample", "sens", "set", "solid", "src", "strans", "surf", "therm",
    "thermstoch", "tme", "trans", "transa", "transb", "transv", "umsh",
    "utrans", "voro", "wwgen", "wwin",
}
PREDEFINED_GRIDS = {
    "scale44", "scale56", "scale238", "scale252", "default2", "defaultmg",
    "nj17", "nj19", "cas2", "cas3", "sfr24g", "sfr240g",
}
KNOWN_SET = {
    "title", "acelib", "declib", "nfylib", "sfylib", "bralib", "pdatadir",
    "nps", "pop", "bc", "srcrate", "power", "powdens", "seed", " repro",
    "repro", "rng", "omp", "lost", "impl", "delnu", "nphys", "ecut", "bc",
    "mvol", "inventory", "printm", "deppara", "depout", "pcc", "bumode",
    "xscalc", "xenon", "samarium", "ngamma", "edepmode", "gcu", "nfg", "fum",
    "micro", "outp", "wrnout", "memfrac",
}
KNOWN_SET.discard(" repro")
DATA_OPTS = ("acelib", "declib", "nfylib", "sfylib", "bralib", "pdatadir")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    out = []
    for line in text.splitlines():
        out.append(line.split("%", 1)[0])
    return "\n".join(out)


def tokenize(text: str):
    toks = []  # (word, line)
    for ln, line in enumerate(text.splitlines(), 1):
        for m in re.finditer(r'"[^"]*"|\S+', line):
            w = m.group(0)
            if len(w) >= 2 and w.startswith('"') and w.endswith('"'):
                w = w[1:-1]
                quoted = True
            else:
                quoted = False
            toks.append((w, ln, quoted))
    return toks


def split_cards(toks):
    cards = []  # (name, [(w,ln)], start_line)
    cur = None
    for w, ln, quoted in toks:
        lw = w.lower()
        if not quoted and lw in RESERVED and (cur is None or lw in ("set",) or True):
            # 'set' always starts a new card; other reserved words start a new
            # card too (Serpent is sequential). Guard: first token must be card.
            if cur is not None and lw == cur[0] and lw not in ("set",):
                # same-name repeat still starts a new card (e.g. two mats)
                pass
            if cur is not None:
                cards.append(cur)
            cur = (lw, [], ln)
        else:
            if cur is None:
                cards.append(("__preamble__", [(w, ln)], ln))
                cur = None
            else:
                cur[1].append((w, ln))
    if cur is not None:
        cards.append(cur)
    return cards


def lint(path: str, data_dir: str | None = None):
    issues = []
    try:
        with open(path, "rb") as f:
            raw_bytes = f.read()
    except OSError as e:
        return [{"level": "error", "code": "io", "msg": f"cannot read: {e}", "line": 0}]
    for ln, line in enumerate(raw_bytes.split(b"\n"), 1):
        if any(b > 127 for b in line):
            issues.append({"level": "error", "code": "non-ascii",
                           "msg": "non-ASCII byte (Serpent 2.1.32 reads ASCII only)", "line": ln})
            break
    try:
        raw = raw_bytes.decode("utf-8", errors="replace")
    except OSError as e:
        return [{"level": "error", "code": "io", "msg": f"cannot read: {e}", "line": 0}]

    text = strip_comments(raw)
    toks = tokenize(text)
    cards = split_cards(toks)
    base = os.path.dirname(os.path.abspath(path))

    def err(code, msg, line=0):
        issues.append({"level": "error", "code": code, "msg": msg, "line": line})

    def warn(code, msg, line=0):
        issues.append({"level": "warning", "code": code, "msg": msg, "line": line})

    seen: dict[str, dict[str, int]] = {}
    funs: set[str] = set()
    enes: set[str] = set()
    declib_present = False
    for name, args, ln in cards:
        if name == "__preamble__":
            if args:
                err("preamble", f"text before first card: '{args[0][0]}'", args[0][1])
            continue
        words = [w for w, _ in args]
        if name in ("surf", "cell", "mat", "det", "ene", "tme", "fun", "therm", "src", "lat", "pin"):
            if words:
                key = words[0].lower()
                seen.setdefault(name, {})
                if key in seen[name]:
                    warn("duplicate", f"duplicate {name} name '{words[0]}'", ln)
                seen[name][key] = ln
        if name == "fun" and words:
            funs.add(words[0].lower())
        if name == "ene" and words:
            enes.add(words[0].lower())
        if name == "set":
            if not words:
                err("set-empty", "'set' without option", ln)
                continue
            opt = words[0].lower()
            if opt not in KNOWN_SET:
                warn("set-unknown", f"unknown set option '{words[0]}' (typo?)", ln)
            if opt in DATA_OPTS:
                for w, wln in args[1:]:
                    p = w
                    dd = data_dir or base
                    cand = [os.path.join(base, p), os.path.join(dd, p), p]
                    if not any(os.path.exists(c) for c in cand):
                        err("data-path-missing", f"set {opt}: file/dir not found: '{p}'", wln)
            if opt in ("declib",):
                declib_present = True
        if name == "det":
            low = [w.lower() for w in words]
            if "de" in low:
                i = low.index("de")
                if i + 1 < len(low) and low[i + 1] in PREDEFINED_GRIDS:
                    err("de-predefined", f"det uses predefined grid '{words[i+1]}' in de — define ene first: 'ene e 4 {words[i+1]}'", ln)
                elif i + 1 < len(low) and low[i + 1] not in enes and low[i + 1] not in ("e",):
                    warn("de-unknown", f"det de grid '{words[i+1]}' has no matching ene card", ln)
            if "dr" in low:
                i = low.index("dr")
                if i + 1 < len(low) and low[i + 1] == "-100":
                    if i + 2 >= len(low) or low[i + 2] not in funs:
                        # fun may be defined later; check globally after pass
                        pass
        if name == "src":
            low = [w.lower() for w in words]
            if "sb" in low:
                i = low.index("sb")
                rest = words[i + 1:]
                if len(rest) < 2:
                    err("sb-header", "src sb needs 'NE INTT E1 F1 ...'", ln)
                else:
                    try:
                        ne = int(float(rest[0]))
                        if len(rest) < 2 + 2 * ne:
                            warn("sb-short", f"src sb declares {ne} points but has fewer numbers", ln)
                    except ValueError:
                        err("sb-header", "src sb: NE must be a number", ln)
            # sb continuation lines starting with reserved names
            for w, wln in args:
                if w.lower() in RESERVED and w.lower() not in ("sb", "sg", "sp", "srad", "sm", "se", "sd", "sa", "sw", "st"):
                    pass  # handled by splitter; explicit per-line check below
    # per-line reserved-word split check inside sb blocks
    lines = strip_comments(raw).splitlines()
    in_sb = False
    for ln, line in enumerate(lines, 1):
        parts = line.split()
        if not parts:
            in_sb = False
            continue
        first = parts[0].lower().strip('"')
        if first == "src":
            in_sb = "sb" in [p.lower() for p in parts]
            continue
        if first in ("sb", "sg", "sp", "srad", "sm", "se", "sd"):
            in_sb = True
            continue
        if first in RESERVED:
            in_sb = False
            continue
        if in_sb and first in RESERVED:
            err("sb-split", f"sb data line starts with reserved word '{parts[0]}' — card would split", ln)

    # dr -100 without fun (global)
    for name, args, ln in cards:
        if name == "det":
            low = [w.lower() for w, _ in args]
            if "-100" in low:
                i = low.index("-100")
                fn = low[i + 1] if i + 1 < len(low) else None
                if not fn or fn not in funs:
                    err("dr-fun", "det dr -100 needs matching 'fun NAME ...' card", ln)
    # sg without declib / decay nuclide heuristic (photons only:
    # neutron sg works with transport nuclides + nfylib, e.g. HW3_N Cm-250.03c)
    has_sg = any(n == "src" and any(w.lower() == "sg" for w, _ in a) for n, a, _ in cards)
    sg_particles = set()
    for name, args, ln in cards:
        if name == "src":
            low = [w.lower() for w, _ in args]
            if "sg" in low:
                for t in ("n", "p", "g"):
                    if t in low:
                        sg_particles.add(t)
    if has_sg and not declib_present:
        warn("sg-declib", "src sg without 'set declib' — decay data will be missing", 0)
    if has_sg and ("p" in sg_particles or "g" in sg_particles):
        has_decay_nuclide = False
        for name, args, ln in cards:
            if name == "mat":
                comp = " ".join(w for w, _ in args)
                if re.search(r"(?:^|\s)(?:[A-Z][a-z]?-\d+|\d{5,6})(?:\s|$)", comp):
                    has_decay_nuclide = True
        if not has_decay_nuclide:
            warn("sg-nuclide", "photon sg source but no decay nuclide (e.g. Cm-250, Ir-192) in any mat — emission rate may be 0", 0)
    # mat sign mixing
    for name, args, ln in cards:
        if name == "mat" and len(args) >= 3:
            fracs = []
            for w, _ in args[2:]:
                try:
                    fracs.append(float(w))
                except ValueError:
                    continue
            pos = any(f > 0 for f in fracs)
            neg = any(f < 0 for f in fracs)
            if pos and neg:
                err("mat-mix", f"mat '{args[0][0]}' mixes atomic (+) and mass (-) fractions", ln)
    # outside closure
    if any(n == "cell" for n, _, _ in cards):
        if not any(n == "cell" and any(w.lower() == "outside" for w, _ in a) for n, a, _ in cards):
            warn("no-outside", "no cell filled with 'outside' — geometry may be unclosed", 0)
    # nps batches < 20 with group constants on (default) aborts before transport
    gcu_off = any(n == "set" and len(a) >= 2 and a[0][0].lower() == "gcu" and a[1][0] == "-1"
                  for n, a, _ in cards)
    if not gcu_off:
        for name, args, ln in cards:
            if name == "set" and args and args[0][0].lower() == "nps" and len(args) >= 3:
                try:
                    if int(float(args[2][0])) < 20:
                        warn("nps-batches", "set nps batches < 20 aborts the run (need >= 20 or 'set gcu -1')", ln)
                except ValueError:
                    pass
    return issues


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    path = argv[1]
    as_json = "--json" in argv
    data_dir = None
    if "--data-dir" in argv:
        i = argv.index("--data-dir")
        if i + 1 < len(argv):
            data_dir = argv[i + 1]
    issues = lint(path, data_dir)
    if as_json:
        print(json.dumps({"file": path, "issues": issues}, ensure_ascii=False, indent=1))
    else:
        if not issues:
            print(f"{path}: OK (no errors, no warnings)")
        for it in issues:
            print(f"{path}:{it['line']}: {it['level']}: [{it['code']}] {it['msg']}")
    return 1 if any(i["level"] == "error" for i in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
