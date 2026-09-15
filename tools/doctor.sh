#!/bin/sh
# doctor.sh — check Serpent 2.1.32 work environment (portable, POSIX sh).
# Usage: sh tools/doctor.sh [--data DIR] [--exe FILE] [--json]
# Checks: sss2 version/CLI, data files (acelib/declib/nfylib/pdatadir,
# mcplib63/84, sssth1, jef3 vs sss_endfb7), skill/lint presence.
# Never modifies anything. Exit 0 if runnable, 1 if blocking problems.
set -eu

DATA=""; EXE=""; JSON=0
while [ $# -gt 0 ]; do
  case "$1" in
    --data) shift; DATA="${1:-}" ;;
    --data=*) DATA="${1#*=}" ;;
    --exe) shift; EXE="${1:-}" ;;
    --exe=*) EXE="${1#*=}" ;;
    --json) JSON=1 ;;
    -h|--help) sed -n '1,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
[ -z "$DATA" ] && DATA="$DIR/xsdata"
[ -z "$EXE" ] && { [ -x "$DIR/sss2" ] && EXE="$DIR/sss2" || EXE="sss2"; }

ok=1; warn=0
exe_ver=""; cli="unknown"
if command -v "$EXE" >/dev/null 2>&1 || [ -x "$EXE" ]; then
  out=$("$EXE" -version 2>&1 | grep -i "version" | head -n 3 || true)
  exe_ver=$(printf '%s' "$out" | grep -Eo '[Vv]ersion [0-9]+\.[0-9]+\.[0-9]+' | head -n1 || true)
  [ -z "$exe_ver" ] && exe_ver=$(printf '%s' "$out" | grep -Eo '2\.[0-9]+\.[0-9]+' | head -n1 || true)
  [ -z "$exe_ver" ] && exe_ver="found (parse failed)"
  cli="single-dash"
else
  ok=0; exe_ver="NOT FOUND"
fi

check() { # check <label> <path(s)...> ; exact=1 required
  label="$1"; shift
  for p in "$@"; do
    if [ -e "$p" ]; then echo "  ok: $label -> $p"; return 0; fi
  done
  echo "  MISSING: $label (tried: $*)"; return 1
}

fails=""; warns=""
add_fail() { fails="$fails $1"; ok=0; }
add_warn() { warns="$warns $1"; warn=1; }

echo "exe: $EXE ($exe_ver, cli: $cli)"
echo "data: $DATA"

check "acelib data.xsdata" "$DATA/data.xsdata" || add_fail acelib
check "declib sss_endfb7.dec" "$DATA/sss_endfb7.dec" || add_warn sss_endfb7.dec
if [ -f "$DATA/jef3.dec" ]; then
  head -c 120 "$DATA/jef3.dec" | grep -q "JEFF-3.3" && echo "  ok: declib jef3.dec (JEFF-3.3)" || echo "  ok: declib jef3.dec (header differs!)"
else
  echo "  MISSING: declib jef3.dec (JEFF-3.3, needed for HW3/HW4)"; add_warn jef3.dec
fi
check "nfylib sss_endfb7.nfy" "$DATA/sss_endfb7.nfy" || add_warn sss_endfb7.nfy
if [ -d "$DATA/photon_data" ]; then
  n=$(ls "$DATA/photon_data"/*.dat 2>/dev/null | wc -l | tr -d ' ')
  echo "  ok: pdatadir photon_data ($n .dat)"
  [ -f "$DATA/photon_data/data.xsdata" ] && echo "  note: photon_data/data.xsdata is junk duplicate, ignored"
else
  echo "  MISSING: pdatadir photon_data/"; add_warn pdatadir
fi
[ -f "$DATA/acedata/mcplib84" ] && echo "  ok: acedata/mcplib84" || { echo "  MISSING: acedata/mcplib84 (photon .84p needs it)"; add_warn mcplib84; }
[ -f "$DATA/acedata/mcplib63" ] && echo "  ok: acedata/mcplib63" || add_warn mcplib63
[ -e "$DATA/acedata/sssth1" ] && echo "  ok: acedata/sssth1 (thermal .00t)" || { echo "  MISSING: acedata/sssth1"; add_warn sssth1; }
[ -f "$DIR/BOOT_2.1.32.md" ] && echo "  ok: BOOT_2.1.32.md" || add_warn BOOT
[ -f "$DIR/.opencode/skill/serpent2/SKILL.md" ] && echo "  ok: skill" || add_warn skill
[ -f "$DIR/tools/serpent-lint.py" ] && echo "  ok: serpent-lint.py" || add_fail lint

if [ "$JSON" = "1" ]; then
  printf '{"exe":"%s","exe_version":"%s","data":"%s","ok":%s,"missing":"%s","warnings":"%s"}\n' \
    "$EXE" "$exe_ver" "$DATA" "$([ "$ok" = "1" ] && echo true || echo false)" "$fails" "$warns"
fi
[ "$ok" = "1" ] && { echo "doctor: READY (warnings:$warns)"; exit 0; } || { echo "doctor: BLOCKED (missing:$fails)"; exit 1; }
