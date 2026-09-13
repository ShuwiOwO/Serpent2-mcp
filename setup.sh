#!/bin/sh
# Portable installer for serpent2-mcp (macOS and Linux).
#
# Usage:
#   ./setup.sh                 install (base + plots), online
#   ./setup.sh --no-plots      skip matplotlib (smaller install)
#   ./setup.sh --dev           install test dependencies as well
#   ./setup.sh --offline [--wheelhouse DIR]
#                              install from a local wheelhouse (no network)
#   ./setup.sh --status        print Python/venv status and exit
#
# Requires Python >= 3.10 (searched as: $PYTHON, python3, python).
# On Debian/Ubuntu: sudo apt install python3 python3-venv

set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DIR"

WITH_PLOTS=1
WITH_DEV=0
OFFLINE=0
WHEELHOUSE=""
STATUS=0

while [ $# -gt 0 ]; do
    case "$1" in
        --no-plots) WITH_PLOTS=0 ;;
        --dev) WITH_DEV=1 ;;
        --offline) OFFLINE=1 ;;
        --wheelhouse) shift; WHEELHOUSE="${1:-}" ;;
        --wheelhouse=*) WHEELHOUSE="${1#*=}" ;;
        --status) STATUS=1 ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ -n "${PYTHON:-}" ]; then
    CANDIDATES="$PYTHON"
else
    CANDIDATES="python3 python"
fi

PY=""
for c in $CANDIDATES; do
    if command -v "$c" >/dev/null 2>&1; then
        if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PY="$c"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "ERROR: Python >= 3.10 not found. Install Python 3 and re-run (or set PYTHON=/path/to/python3)." >&2
    echo "  Debian/Ubuntu: sudo apt install python3 python3-venv" >&2
    echo "  Fedora/RHEL:   sudo dnf install python3 python3-pip" >&2
    exit 1
fi

if [ "$STATUS" = "1" ]; then
    echo "Python: $("$PY" --version 2>&1) ($PY)"
    if [ -x ".venv/bin/python" ]; then
        echo "venv:   $DIR/.venv ($(.venv/bin/python --version 2>&1))"
        .venv/bin/python -c "import serpent2_mcp; print('package:', serpent2_mcp.__version__)" 2>/dev/null || echo "package: not installed"
    else
        echo "venv:   missing (run ./setup.sh)"
    fi
    exit 0
fi

echo "Using Python: $("$PY" --version 2>&1) ($PY)"

if [ ! -x ".venv/bin/python" ]; then
    echo "Creating virtual environment in .venv ..."
    "$PY" -m venv .venv
fi

VENV_PY=".venv/bin/python"

EXTRAS=""
if [ "$WITH_PLOTS" = "1" ]; then EXTRAS="plots"; fi
if [ "$WITH_DEV" = "1" ]; then
    if [ -n "$EXTRAS" ]; then EXTRAS="$EXTRAS,test"; else EXTRAS="test"; fi
fi

if [ "$OFFLINE" = "1" ]; then
    if [ -z "$WHEELHOUSE" ]; then
        WHEELHOUSE="$DIR/wheelhouse"
    fi
    if [ ! -d "$WHEELHOUSE" ]; then
        echo "ERROR: offline install requested but wheelhouse not found: $WHEELHOUSE" >&2
        echo "Build it on a machine with network and the same OS/architecture:" >&2
        echo "  ./tools/make_offline_bundle.sh" >&2
        exit 1
    fi
    TARGET="serpent2-mcp"
    if [ -n "$EXTRAS" ]; then TARGET="serpent2-mcp[$EXTRAS]"; fi
    echo "Installing $TARGET from $WHEELHOUSE (offline) ..."
    "$VENV_PY" -m pip install --quiet --no-index --find-links "$WHEELHOUSE" "$TARGET"
    echo ""
    echo "NOTE: installed from wheels, so code updates require re-running this command."
else
    echo "Upgrading pip ..."
    "$VENV_PY" -m pip install --quiet --upgrade pip
    if [ -n "$EXTRAS" ]; then
        echo "Installing serpent2-mcp[$EXTRAS] (editable) ..."
        "$VENV_PY" -m pip install --quiet -e ".[$EXTRAS]"
    else
        echo "Installing serpent2-mcp (editable) ..."
        "$VENV_PY" -m pip install --quiet -e .
    fi
fi

echo ""
echo "Done. Verify the server starts:"
echo "  $DIR/.venv/bin/python -m serpent2_mcp --status"
echo ""
echo "Add this to your opencode.json (see README.md for details):"
echo "  \"mcp\": { \"serpent\": { \"type\": \"local\", \"command\": [\"$DIR/.venv/bin/python\", \"-m\", \"serpent2_mcp\"] } }"
