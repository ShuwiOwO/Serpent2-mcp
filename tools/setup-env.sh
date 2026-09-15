#!/bin/sh
# setup-env.sh — (re)create a working Serpent 2.1.32 data dir (portable, POSIX sh).
#
#   sh tools/setup-env.sh --mode etalon --src <etalon-xsdata-dir> --dest <dir> [--force]
#   sh tools/setup-env.sh --mode vtt --lib endfb71 --dest <dir>
#   sh tools/setup-env.sh --check --dest <dir>   # verify only
#
# etalon mode: copy acedata/*.dec/*.nfy/photon_data + data.xsdata as path template
#   from your reference folder (USB/archive), then repoint absolute paths inside
#   *.xsdata to --dest. Never overwrites --dest without --force (makes backup-*).
# vtt mode: download small files (dec/nfy/photon_data/mcplib.xsdata) from
#   https://serpent.vtt.fi/repository; big ACE tarballs (6-8 GB) print exact URLs
#   + expected sizes (download with curl/wget, then re-run etalon mode on it).
# jef3.dec (JEFF-3.3, NEA) is NEVER silently replaced by jeff311. If missing it
# is reported as MISSING with instructions.
set -eu

MODE=""; SRC=""; DEST=""; LIB="endfb71"; FORCE=0; CHECK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) shift; MODE="${1:-}" ;;
    --mode=*) MODE="${1#*=}" ;;
    --src) shift; SRC="${1:-}" ;;
    --src=*) SRC="${1#*=}" ;;
    --dest) shift; DEST="${1:-}" ;;
    --dest=*) DEST="${1#*=}" ;;
    --lib) shift; LIB="${1:-}" ;;
    --force) FORCE=1 ;;
    --check) CHECK=1 ;;
    -h|--help) sed -n '1,16p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

REPO="https://serpent.vtt.fi/repository"
[ -z "$DEST" ] && { echo "ERROR: --dest required" >&2; exit 2; }

repoint_xsdata() { # repoint_xsdata <file> <dest>
  python3 - "$1" "$2" <<'EOF'
import sys
f, dest = sys.argv[1], sys.argv[2]
out = []
with open(f, encoding='utf-8', errors='replace') as fh:
    for line in fh:
        s = line.rstrip('\n')
        if not s.strip() or s.lstrip().startswith('%'):
            out.append(line); continue
        parts = s.split()
        if len(parts) >= 9 and parts[-1].startswith('/'):
            base = parts[-1].rsplit('/', 1)[-1]
            # keep subdir structure for acedata files: acedata/<base>
            parts[-1] = dest.rstrip('/') + '/acedata/' + base
            # sssth1/mcplib single files live directly in acedata/
            out.append(' '.join(parts) + '\n')
        else:
            out.append(line)
with open(f, 'w', encoding='utf-8') as fh:
    fh.writelines(out)
print(f"repointed {f} -> {dest}/acedata/")
EOF
}

verify_dest() { # verify_dest <dest>
  d="$1"; rc=0
  [ -f "$d/data.xsdata" ] || { echo "MISSING: $d/data.xsdata"; rc=1; }
  if [ -f "$d/data.xsdata" ]; then
    echo "lines data.xsdata: $(wc -l < "$d/data.xsdata" | tr -d ' ')"
    echo ".03c: $(grep -c '\.03c' "$d/data.xsdata" || true)  84p: $(grep -c '84p' "$d/data.xsdata" || true)  63p: $(grep -c '63p' "$d/data.xsdata" || true)"
    grep -q 'gre7.00t' "$d/data.xsdata" && echo "ok: gre7.00t present" || { echo "MISSING: gre7.00t in index"; rc=1; }
    grep -q 'H-nat.84p' "$d/data.xsdata" && echo "ok: H-nat.84p alias" || echo "WARN: no H-nat.84p alias"
  fi
  [ -f "$d/jef3.dec" ] && head -c 120 "$d/jef3.dec" | grep -q "JEFF-3.3" && echo "ok: jef3.dec (JEFF-3.3)" || echo "MISSING/WARN: jef3.dec (JEFF-3.3 from OECD NEA, not VTT)"
  [ -f "$d/sss_endfb7.dec" ] && echo "ok: sss_endfb7.dec" || echo "MISSING: sss_endfb7.dec"
  [ -f "$d/sss_endfb7.nfy" ] && echo "ok: sss_endfb7.nfy" || echo "MISSING: sss_endfb7.nfy"
  [ -d "$d/photon_data" ] && echo "ok: photon_data ($(ls "$d/photon_data"/*.dat 2>/dev/null | wc -l | tr -d ' ') .dat)" || echo "MISSING: photon_data/"
  [ -f "$d/acedata/mcplib84" ] && echo "ok: acedata/mcplib84" || echo "MISSING: acedata/mcplib84 (LANL/RSICC, photon .84p)"
  [ -e "$d/acedata/sssth1" ] && echo "ok: acedata/sssth1" || echo "MISSING: acedata/sssth1"
  echo "--- use in input (relative to run dir) ---"
  echo "set acelib \"xsdata/data.xsdata\""
  echo "set declib \"xsdata/jef3.dec\""
  echo "set nfylib \"xsdata/sss_endfb7.nfy\""
  echo "set pdatadir \"xsdata/photon_data\""
  return $rc
}

if [ "$CHECK" = "1" ]; then verify_dest "$DEST"; exit $?; fi

if [ "$MODE" = "etalon" ]; then
  [ -z "$SRC" ] && { echo "ERROR: --src required for etalon mode" >&2; exit 2; }
  [ -d "$SRC" ] || { echo "ERROR: src not a dir: $SRC" >&2; exit 2; }
  if [ -e "$DEST" ] && [ "$FORCE" != "1" ]; then
    echo "ERROR: dest exists: $DEST (use --force to backup+overwrite)" >&2; exit 1
  fi
  if [ -e "$DEST" ]; then
    bk="${DEST}-backup-$(date +%Y%m%d-%H%M%S)"; echo "backup: $DEST -> $bk"; mv "$DEST" "$bk"
  fi
  mkdir -p "$DEST/acedata" "$DEST/photon_data"
  echo "copy acedata/ (6+ GB, may take a while)..."
  cp -a "$SRC/acedata/." "$DEST/acedata/"
  for f in jef3.dec sss_endfb7.dec sss_endfb7.nfy data.xsdata data_u.xsdata sss_endfb7u.xsdir xsdirconvert.pl; do
    [ -f "$SRC/$f" ] && cp -a "$SRC/$f" "$DEST/$f" && echo "copied $f" || echo "note: $f not in src, skipped"
  done
  if [ -d "$SRC/photon_data" ]; then
    for f in "$SRC"/photon_data/*.dat; do cp -a "$f" "$DEST/photon_data/" 2>/dev/null || true; done
    echo "copied photon_data/*.dat"
  fi
  repoint_xsdata "$DEST/data.xsdata" "$DEST"
  # stable aliases (symlink or copy)
  (cd "$DEST" && ln -sf sss_endfb7.dec data.dec 2>/dev/null || cp -a sss_endfb7.dec data.dec 2>/dev/null || true)
  (cd "$DEST" && ln -sf sss_endfb7.nfy data.nfy 2>/dev/null || cp -a sss_endfb7.nfy data.nfy 2>/dev/null || true)
  echo "--- verify ---"; verify_dest "$DEST"; exit $?
fi

if [ "$MODE" = "vtt" ]; then
  mkdir -p "$DEST"
  echo "VTT small files into $DEST ..."
  for f in "other_data/sss_endfb7.dec" "other_data/sss_endfb7.nfy" "photon_data/mcplib.xsdata"; do
    base=$(basename "$f")
    [ -f "$DEST/$base" ] && { echo "exists: $base"; continue; }
    echo "get $f"; curl -fL --retry 3 -o "$DEST/$base" "$REPO/$f" || wget -O "$DEST/$base" "$REPO/$f"
  done
  mkdir -p "$DEST/photon_data"
  if [ ! -f "$DEST/photon_data/ComptonProfiles.dat" ]; then
    echo "get photon_data.tar.gz (7.7 MB)..."; curl -fL --retry 3 -o /tmp/photon_data.tar.gz "$REPO/photon_data/photon_data.tar.gz" || wget -O /tmp/photon_data.tar.gz "$REPO/photon_data/photon_data.tar.gz"
    tar -xzf /tmp/photon_data.tar.gz -C "$DEST"
  fi
  echo ""
  echo "Big ACE package NOT auto-downloaded here (6-8 GB). For --lib $LIB:"
  case "$LIB" in
    endfb71) echo "  $REPO/Serpent_2_xsdata/s2v0_endfb71.tar.gz (7116693776 bytes)" ;;
    jeff32) echo "  $REPO/Serpent_2_xsdata/s2v0_jeff32.tar.gz (7886497260 bytes)" ;;
    jendl40) echo "  $REPO/Serpent_2_xsdata/s2v0_jendl40.tar.gz (6612916648 bytes)" ;;
    *) echo "  unknown lib: $LIB" ;;
  esac
  echo "Download, extract into $DEST, then run: sh tools/setup-env.sh --check --dest $DEST"
  echo "NOTE: VTT has NO JEFF-3.3 jef3.dec. Bring your own (OECD NEA) or use sss_endfb7.dec."
  verify_dest "$DEST"; exit 0
fi

echo "ERROR: --mode required (etalon|vtt)" >&2; exit 2
