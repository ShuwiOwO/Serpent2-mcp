#!/usr/bin/env python3
"""serpent-results.py — zero-deps summary of Serpent 2.1.32 .m outputs.

Usage:
  python3 tools/serpent-results.py --summary <input-base> [--json]
  python3 tools/serpent-results.py --file <file.m> [--json] [--max-lines N]

<input-base>: path to the input file (extension insensitive). Finds
  <base>_res.m, <base>_det*.m, <base>_dep.m, <base>_gsrc.m, <base>_nsrc.m
  (also handles full names like HW3_N.sh -> HW3_N.sh_res.m).

Prints TOT_SRCRATE / NORM_COEF / k-eff from _res.m, detector bin counts and
first means, gsrc/nsrc tot (== set srcrate for SB runs). Big files are
streamed with --max-lines (default 4000) and flagged truncated.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

MAX_LINES = 4000


def parse_matlab_limited(path, max_lines=MAX_LINES):
    """Stream a Serpent .m file; return {scalars, vectors, truncated}."""
    scalars: dict[str, float | str] = {}
    vec_len: dict[str, int] = {}
    first_vals: dict[str, list] = {}
    lines_read = 0
    truncated = False
    # scalar: NAME = 1.23E+11;  vector start: DETNAME = [ ... ];
    scalar_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_\[\]]*)\s*=\s*([^;\[]*);")
    vec_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\[")
    cur_vec = None
    cur_count = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                lines_read += 1
                if lines_read > max_lines:
                    truncated = True
                    break
                s = line.strip()
                if not s or s.startswith("%"):
                    continue
                if cur_vec is not None:
                    if "]" in s:
                        cur_vec = None
                    else:
                        nums = s.split()
                        cur_count += len(nums)
                        vec_len[cur_vec] = cur_count
                        if cur_vec not in first_vals and nums:
                            first_vals[cur_vec] = nums[:6]
                    continue
                m = scalar_re.match(s)
                if m and "[" not in s:
                    name, val = m.group(1), m.group(2).strip()
                    try:
                        scalars[name] = float(val.split()[0])
                    except ValueError:
                        scalars[name] = val[:80]
                    continue
                m = vec_re.match(s)
                if m:
                    cur_vec = m.group(1)
                    cur_count = 0
                    rest = s.split("[", 1)[1]
                    if "]" in rest:
                        cur_vec = None
                    continue
    except OSError as e:
        return {"error": str(e)}
    return {"scalars": scalars, "vectors": vec_len, "first": first_vals,
            "truncated": truncated, "lines": lines_read}


def find_outputs(base):
    root, _ = os.path.splitext(base)
    cands = [base, root]
    out: dict[str, list[str]] = {"res": [], "det": [], "dep": [], "gsrc": [], "nsrc": [], "other": []}
    seen = set()
    for c in cands:
        for pat, key in [(c + "_res.m", "res"), (c + "_det*.m", "det"),
                         (c + "_dep.m", "dep"), (c + "_gsrc.m", "gsrc"),
                         (c + "_nsrc.m", "nsrc")]:
            for g in glob.glob(pat):
                if g not in seen:
                    seen.add(g)
                    out[key].append(g)
    return out


def summarize(base, max_lines=MAX_LINES):
    out = find_outputs(base)
    res = {"input": base, "files": out, "keff": None, "keff_err": None,
           "tot_srcrate": None, "norm_coef": None, "detectors": [],
           "gsrc_tot": None, "nsrc_tot": None, "truncated": []}
    for f in out["res"][:1]:
        d = parse_matlab_limited(f, max_lines)
        sc = d.get("scalars", {})
        for k in ("TOT_SRCRATE", "SRC_TOT_SRCRATE", "TOT_NSRCRATE"):
            if k in sc:
                res["tot_srcrate"] = sc[k]
                break
        res["norm_coef"] = sc.get("NORM_COEF")
        if "ABS_KEFF" in sc:
            res["keff"] = sc["ABS_KEFF"]
        if "ABS_KEFF_ERR" in sc:
            res["keff_err"] = sc["ABS_KEFF_ERR"]
        if d.get("truncated"):
            res["truncated"].append(f)
    for f in out["det"]:
        d = parse_matlab_limited(f, max_lines)
        res["detectors"].append({"file": f, "vectors": d.get("vectors", {}),
                                 "truncated": d.get("truncated")})
        if d.get("truncated"):
            res["truncated"].append(f)
    for key in ("gsrc", "nsrc"):
        for f in out[key][:2]:
            d = parse_matlab_limited(f, max_lines)
            sc = d.get("scalars", {})
            tot = sc.get("tot", sc.get("TOT"))
            if tot is not None:
                res[key + "_tot"] = tot
    return res


def main(argv):
    if "--help" in argv or "-h" in argv or len(argv) < 2:
        print(__doc__)
        return 0
    as_json = "--json" in argv
    ml = MAX_LINES
    if "--max-lines" in argv:
        i = argv.index("--max-lines")
        ml = int(argv[i + 1])
    if "--file" in argv:
        i = argv.index("--file")
        d = parse_matlab_limited(argv[i + 1], ml)
        print(json.dumps(d, ensure_ascii=False, indent=1) if as_json else
              f"{argv[i+1]}: scalars={len(d.get('scalars', {}))} vectors={list(d.get('vectors', {}))[:8]} truncated={d.get('truncated')}")
        return 0
    base = argv[argv.index("--summary") + 1] if "--summary" in argv else argv[1]
    r = summarize(base, ml)
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f"input: {r['input']}")
        print(f"keff: {r['keff']} err: {r['keff_err']}")
        print(f"TOT_SRCRATE: {r['tot_srcrate']} NORM_COEF: {r['norm_coef']}")
        print(f"gsrc_tot: {r['gsrc_tot']} nsrc_tot: {r['nsrc_tot']}")
        for d in r["detectors"]:
            print(f"det {d['file']}: {list(d['vectors'])[:6]} truncated={d['truncated']}")
        if r["truncated"]:
            print(f"truncated: {r['truncated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
