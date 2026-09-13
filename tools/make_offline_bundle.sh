#!/bin/sh
# Build an offline installation bundle (project copy + wheelhouse) that can be
# transferred to another machine without network access.
#
# Usage:
#   ./tools/make_offline_bundle.sh [OUTPUT_DIR]     (default: dist-offline)
#   INCLUDE_PLOTS=0 ./tools/make_offline_bundle.sh  (skip matplotlib)
#   PYTHON=/path/to/python3 ./tools/make_offline_bundle.sh
#
# IMPORTANT: binary dependencies (pydantic-core, matplotlib) are
# platform-specific. Build the bundle on the same OS and CPU architecture as
# the target machine, or use --no-plots there if only pure Python is needed.

set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="${1:-$DIR/dist-offline}"
INCLUDE_PLOTS="${INCLUDE_PLOTS:-1}"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
    for c in python3 python; do
        if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
    done
fi
if [ -z "$PY" ]; then
    echo "ERROR: python3 not found" >&2
    exit 1
fi

echo "Using Python: $("$PY" --version 2>&1)"
echo "Building bundle in: $OUT"

rm -rf "$OUT"
mkdir -p "$OUT/wheelhouse"

if [ "$INCLUDE_PLOTS" = "1" ]; then
    echo "Collecting wheels for serpent2-mcp[plots] ..."
    (cd "$DIR" && "$PY" -m pip wheel --quiet ".[plots]" -w "$OUT/wheelhouse")
else
    echo "Collecting wheels for serpent2-mcp ..."
    (cd "$DIR" && "$PY" -m pip wheel --quiet "." -w "$OUT/wheelhouse")
fi

echo "Copying project files ..."
mkdir -p "$OUT/Serpent2-mcp"
tar -C "$DIR" \
    --exclude=.venv \
    --exclude=.git \
    --exclude=__pycache__ \
    --exclude='*.egg-info' \
    --exclude=.pytest_cache \
    --exclude=dist-offline \
    --exclude='*.tar.gz' \
    -cf - . | tar -C "$OUT/Serpent2-mcp" -xf -

tar -C "$OUT" -czf "$OUT.tar.gz" .
SIZE=$(du -h "$OUT.tar.gz" | awk '{print $1}')

echo ""
echo "Bundle ready: $OUT.tar.gz ($SIZE)"
echo ""
echo "On the target machine (same OS/architecture):"
echo "  tar -xzf $(basename "$OUT.tar.gz")"
echo "  cd Serpent2-mcp"
echo "  ./setup.sh --offline --wheelhouse ../wheelhouse"
