#!/bin/sh
# Portable installer for serpent2-mcp (macOS and Linux).
#
# Usage:
#   ./setup.sh                      install; then choose a data library interactively
#   ./setup.sh --data endfb71       install and download ENDF/B-VII.1 (recommended)
#   ./setup.sh --data jeff32        download JEFF-3.2
#   ./setup.sh --data jendl40       download JENDL-4.0
#   ./setup.sh --data none          skip the data download (do it later in OpenCode)
#   ./setup.sh --no-plots           skip matplotlib (smaller install)
#   ./setup.sh --dev                install test dependencies
#   ./setup.sh --offline [--wheelhouse DIR]
#                                   install from a local wheelhouse (no network)
#   ./setup.sh --status             print Python/venv status and exit
#
# Data options:
#   --data LIB        endfb71 | jeff32 | jendl40 | fendl30 | none
#   --data-dir DIR    destination for the data (default: <repo>/xsdata)
#   --no-photon       skip the photon physics data (photon transport only)
#   --no-thxs         skip the thermal scattering library (sss_thxs)
#   --yes             non-interactive: use ENDF/B-VII.1 when --data is omitted
#
# OpenCode options:
#   --opencode        write/merge opencode.json in the current directory
#   --opencode-global write/merge ~/.config/opencode/opencode.json
#   --no-opencode     never ask; print the manual instruction instead
#
# Skill options:
#   --skill           install SKILL.md into <launch dir>/.opencode/skill/serpent2 (default)
#   --global-skill    install into ~/.config/opencode/skill/serpent2
#   --no-skill        do not install the skill
#
# The neutron package includes ACE files, decay (dec) and fission-yield (nfy)
# data; the ENDF/B-VII decay/yield files used by older decks are downloaded
# too. Paths inside the directory files are rewritten to absolute local paths,
# stable aliases (data.xsdata/data.dec/data.nfy) and natural-element aliases
# are added. Downloads are resumable and show a one-line progress bar.
#
# Only mcplib84 (photon ACE cross sections, LANL/RSICC licensed) cannot be
# downloaded automatically; the script tells you exactly where to put it.
#
# Requires Python >= 3.10 (searched as: $PYTHON, python3, python).
# On Debian/Ubuntu: sudo apt install python3 python3-venv

set -eu

CALL_DIR=$(pwd)
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DIR"

WITH_PLOTS=1
WITH_DEV=0
OFFLINE=0
WHEELHOUSE=""
STATUS=0
DATA_CHOICE="auto"
DATA_DIR_FLAG=""
WITH_PHOTON=1
WITH_THXS=1
ASSUME_YES=0
OPENCODE_MODE="ask"
SKILL_MODE="local"

while [ $# -gt 0 ]; do
    case "$1" in
        --no-plots) WITH_PLOTS=0 ;;
        --dev) WITH_DEV=1 ;;
        --offline) OFFLINE=1 ;;
        --wheelhouse) shift; WHEELHOUSE="${1:-}" ;;
        --wheelhouse=*) WHEELHOUSE="${1#*=}" ;;
        --status) STATUS=1 ;;
        --data) shift; DATA_CHOICE="${1:-}" ;;
        --data=*) DATA_CHOICE="${1#*=}" ;;
        --data-dir) shift; DATA_DIR_FLAG="${1:-}" ;;
        --data-dir=*) DATA_DIR_FLAG="${1#*=}" ;;
        --no-photon) WITH_PHOTON=0 ;;
        --no-thxs) WITH_THXS=0 ;;
        --yes|-y) ASSUME_YES=1 ;;
        --opencode) OPENCODE_MODE="local" ;;
        --skill) SKILL_MODE="local" ;;
        --global-skill) SKILL_MODE="global" ;;
        --no-skill) SKILL_MODE="none" ;;
        --opencode-global) OPENCODE_MODE="global" ;;
        --no-opencode) OPENCODE_MODE="none" ;;
        -h|--help) sed -n '2,42p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

normalize_data() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        endf|endfb71|endf7|endf/b-vii.1|endf71) echo endfb71 ;;
        jeff|jeff32|jeff-3.2|jeff3.2) echo jeff32 ;;
        jendl|jendl40|jendl-4.0|jendl4) echo jendl40 ;;
        fendl|fendl30|fendl-3.0|fendl3.0) echo fendl30 ;;
        none|skip|no) echo none ;;
        *) echo "" ;;
    esac
}

if [ "$DATA_CHOICE" != "auto" ]; then
    NORMALIZED=$(normalize_data "$DATA_CHOICE")
    if [ -z "$NORMALIZED" ]; then
        echo "ERROR: unknown --data value '$DATA_CHOICE'." >&2
        echo "Use one of: endfb71, jeff32, jendl40, fendl30, none" >&2
        exit 2
    fi
    DATA_CHOICE="$NORMALIZED"
fi

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
    if [ -d "$DIR/xsdata" ]; then
        echo "data:   $DIR/xsdata ($(du -sh "$DIR/xsdata" 2>/dev/null | awk '{print $1}'))"
    else
        echo "data:   not downloaded yet"
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

# --- nuclear data -----------------------------------------------------------

DATA_DIR="${DATA_DIR_FLAG:-$DIR/xsdata}"
DATA_OK=0

if [ "$DATA_CHOICE" = "auto" ]; then
    if [ "$ASSUME_YES" = "1" ]; then
        DATA_CHOICE=endfb71
    elif [ -t 0 ]; then
        echo ""
        echo "Choose a neutron data library to download into $DATA_DIR (6-8 GB):"
        echo "  1) ENDF/B-VII.1  (endfb71, recommended)"
        echo "  2) JEFF-3.2      (jeff32)"
        echo "  3) JENDL-4.0     (jendl40)"
        echo "  4) FENDL-3.0     (fendl30, fusion)"
        echo "  5) skip (download later in OpenCode with serpent_setup_data)"
        printf 'Choice [1]: '
        choice=""
        read choice || choice=""
        case "$choice" in
            2) DATA_CHOICE=jeff32 ;;
            3) DATA_CHOICE=jendl40 ;;
            4) DATA_CHOICE=fendl30 ;;
            5) DATA_CHOICE=none ;;
            *) DATA_CHOICE=endfb71 ;;
        esac
    else
        echo ""
        echo "No interactive terminal: skipping the data download."
        echo "Run './setup.sh --data endfb71' later, or use serpent_setup_data in OpenCode."
        DATA_CHOICE=none
    fi
fi

if [ "$DATA_CHOICE" != "none" ] && [ "$OFFLINE" = "1" ]; then
    echo ""
    echo "Offline install: skipping the data download (needs network)."
    echo "Use serpent_setup_data in OpenCode when network is available."
    DATA_CHOICE=none
fi

if [ "$DATA_CHOICE" != "none" ]; then
    PHOTON_ARG="--no-photon"; [ "$WITH_PHOTON" = "1" ] && PHOTON_ARG=""
    THXS_ARG="--no-thxs"; [ "$WITH_THXS" = "1" ] && THXS_ARG=""
    REPO_ARG=""
    if [ -n "${SERPENT_DATA_REPO_URL:-}" ]; then REPO_ARG="--base-url $SERPENT_DATA_REPO_URL"; fi
    echo ""
    echo "Downloading '$DATA_CHOICE' into $DATA_DIR ..."
    echo "(includes ACE, decay/fission-yield data and, unless disabled, thermal scattering;"
    echo " the transfer is resumable — re-run the same command if it is interrupted)"
    if "$VENV_PY" -m serpent2_mcp.runner.datadl setup \
        --neutron "$DATA_CHOICE" --dest "$DATA_DIR" --rel-root "$DIR" $PHOTON_ARG $THXS_ARG $REPO_ARG; then
        DATA_OK=1
    else
        echo "WARNING: the data setup did not finish." >&2
        echo "Re-run it later with:" >&2
        echo "  $VENV_PY -m serpent2_mcp.runner.datadl setup --neutron $DATA_CHOICE --dest $DATA_DIR --rel-root $DIR" >&2
    fi
fi

if [ "$DATA_OK" = "1" ]; then
    case "$DATA_DIR" in
        "$DIR"/*) REL_DATA="${DATA_DIR#"$DIR"/}/" ;;
        *) REL_DATA="" ;;
    esac
    if [ -n "$REL_DATA" ]; then
        MCPLIB_PATH_NOTE="${REL_DATA}mcplib84"
    else
        MCPLIB_PATH_NOTE="$DATA_DIR/mcplib84"
    fi
    cat > "$DATA_DIR/README_mcplib84.txt" <<EOF
Photon transport only: place the MCPLIB84 photon ACE file here.

  1. Download the file from:
       https://nucleardata.lanl.gov/ace/mcplib84/
     (or take it from your licensed MCNP/RSICC data set)
  2. Save it exactly as:
       $(basename "$DATA_DIR")/mcplib84        <- this folder, file name "mcplib84"
  3. Verify: the file is about 15 MB and starts with "  1000.84p".
  4. In OpenCode run: serpent_check_data_paths  (or serpent_install_photon_data).

The directory files will reference: ${MCPLIB_PATH_NOTE}
Without this file only photon transport is unavailable; neutron calculations work.

Do not publish mcplib84: MCPLIB84 is LANL/RSICC licensed data.
EOF
    echo ""
    echo "Data ready: $DATA_DIR"
    echo ""
    echo "One optional file remains (photon transport only):"
    echo "  1. Download mcplib84 from https://nucleardata.lanl.gov/ace/mcplib84/"
    echo "  2. Save it exactly as: $DATA_DIR/mcplib84"
    echo "     (paths in the directory files use: ${MCPLIB_PATH_NOTE})"
    echo "  3. In OpenCode run serpent_check_data_paths (or serpent_install_photon_data)."
    echo "  Never publish mcplib84 (LANL/RSICC licensed data)."
    echo "  Details are also in $DATA_DIR/README_mcplib84.txt"
elif [ "$DATA_CHOICE" = "none" ]; then
    echo ""
    echo "No data installed. Download it later from OpenCode with:"
    echo "  serpent_setup_data(neutron=\"endfb71\", dest=\"xsdata\")"
fi

if [ ! -x "$DIR/sss2" ]; then
    echo ""
    echo "NOTE: ./sss2 was not found in this directory."
    echo "      Put your Serpent binary here (the workspace root), or set SERPENT_EXE."
fi

echo ""
echo "Done. Verify the server starts:"
echo "  $DIR/.venv/bin/python -m serpent2_mcp --status"

# --- skill ------------------------------------------------------------------

SKILL_SRC="$DIR/skills/serpent2/SKILL.md"
if [ "$SKILL_MODE" != "none" ] && [ -f "$SKILL_SRC" ]; then
    if [ "$SKILL_MODE" = "global" ]; then
        SKILL_DST="$HOME/.config/opencode/skill/serpent2"
    else
        SKILL_DST="$CALL_DIR/.opencode/skill/serpent2"
    fi
    mkdir -p "$SKILL_DST"
    cp "$SKILL_SRC" "$SKILL_DST/SKILL.md"
    echo ""
    echo "Skill installed: $SKILL_DST/SKILL.md"
elif [ "$SKILL_MODE" = "none" ]; then
    echo ""
    echo "Skill installation skipped (--no-skill)."
fi

# --- self-check -------------------------------------------------------------

if [ "$DATA_OK" = "1" ] && [ -x "$DIR/sss2" ]; then
    echo ""
    echo "Self-check: running a minimal input through ./sss2 -norun ..."
    if "$VENV_PY" -m serpent2_mcp.runner.datadl selfcheck --exe "$DIR/sss2" --data-dir "$DATA_DIR" 2>/dev/null         | sed -n '/^{/,$p'         | "$VENV_PY" -c 'import json,sys; d=json.load(sys.stdin); print("  ok:", d.get("ok"), "| exit:", d.get("exit_code"), "| errors:", d.get("errors")); sys.exit(0 if d.get("ok") else 1)'; then
        echo "Self-check passed."
    else
        echo "WARNING: self-check failed — see the report above; check the data directory and paths." >&2
    fi
fi

# --- opencode.json ----------------------------------------------------------

OC_TARGET=""
if [ "$OPENCODE_MODE" = "local" ]; then
    OC_TARGET="$CALL_DIR/opencode.json"
elif [ "$OPENCODE_MODE" = "global" ]; then
    OC_TARGET="$HOME/.config/opencode/opencode.json"
elif [ "$OPENCODE_MODE" = "ask" ] && [ -t 0 ]; then
    echo ""
    echo "Create/update the OpenCode configuration automatically?"
    echo "  1) yes, in this directory: $CALL_DIR/opencode.json"
    echo "  2) yes, globally:          $HOME/.config/opencode/opencode.json"
    echo "  3) no, I will add it myself"
    printf 'Choice [3]: '
    oc=""
    read oc || oc=""
    case "$oc" in
        1) OC_TARGET="$CALL_DIR/opencode.json" ;;
        2) OC_TARGET="$HOME/.config/opencode/opencode.json" ;;
        *) OC_TARGET="" ;;
    esac
fi

if [ -n "$OC_TARGET" ]; then
    mkdir -p "$(dirname "$OC_TARGET")"
    OC_ENV_ARGS="--lang ru"
    if [ "$DATA_OK" = "1" ]; then
        OC_ENV_ARGS="$OC_ENV_ARGS --env SERPENT_DATA_DIR=$DATA_DIR"
    fi
    if "$VENV_PY" -m serpent2_mcp.opencode_config \
        --path "$OC_TARGET" --venv-python "$DIR/.venv/bin/python" $OC_ENV_ARGS >/dev/null; then
        echo ""
        echo "OpenCode config written: $OC_TARGET"
        echo "Restart OpenCode for the MCP server to appear."
    else
        echo "WARNING: could not update $OC_TARGET; add this manually:" >&2
        echo "  \"mcp\": { \"serpent\": { \"type\": \"local\", \"command\": [\"$DIR/.venv/bin/python\", \"-m\", \"serpent2_mcp\"] } }" >&2
    fi
else
    echo ""
    echo "Add this to your opencode.json (project or ~/.config/opencode/opencode.json):"
    echo "  \"mcp\": { \"serpent\": { \"type\": \"local\", \"command\": [\"$DIR/.venv/bin/python\", \"-m\", \"serpent2_mcp\"] } }"
    echo "Or re-run: ./setup.sh --opencode   (writes it automatically)"
fi
