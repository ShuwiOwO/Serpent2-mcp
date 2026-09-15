#!/bin/sh
# setup.sh — установка окружения Serpent 2.1.32 (portable, POSIX sh).
#
#   ./setup.sh --help
#   ./setup.sh --check [--data DIR] [--exe FILE]
#   ./setup.sh --mode etalon --src <готовая-папка-xsdata> --dest <dir> [--force]
#   ./setup.sh --mode vtt --lib endfb71 --dest <dir>
#
# Что делает: раскладывает/проверяет ядерные данные (03c + 84p + термальные),
# правит пути в *.xsdata, ставит Skill для OpenCode, в конце гоняет doctor.
# Сам Serpent (sss2, proprietary VTT) и данные в репо не входят — их
# привозит пользователь (см. --help и README-SERPENT-KIT.md).
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA="$DIR/xsdata"; EXE=""; MODE=""; SRC=""; LIB="endfb71"; FORCE=0; CHECK=0; SKILL=1

while [ $# -gt 0 ]; do
  case "$1" in
    --data) shift; DATA="${1:-}" ;;
    --data=*) DATA="${1#*=}" ;;
    --exe) shift; EXE="${1:-}" ;;
    --exe=*) EXE="${1#*=}" ;;
    --mode) shift; MODE="${1:-}" ;;
    --mode=*) MODE="${1#*=}" ;;
    --src) shift; SRC="${1:-}" ;;
    --src=*) SRC="${1#*=}" ;;
    --lib) shift; LIB="${1:-}" ;;
    --lib=*) LIB="${1#*=}" ;;
    --force) FORCE=1 ;;
    --check) CHECK=1 ;;
    --no-skill) SKILL=0 ;;
    -h|--help)
      echo "Usage:"
      echo "  ./setup.sh --check [--data DIR] [--exe FILE]"
      echo "  ./setup.sh --mode etalon --src <готовые-данные> --dest <dir> [--force]"
      echo "  ./setup.sh --mode vtt --lib endfb71 --dest <dir>"
      echo ""
      echo "Режимы данных:"
      echo "  etalon  скопировать готовую связку (acedata/, *.dec/nfy, photon_data/)"
      echo "          и переписать пути в *.xsdata под новую папку. Без --force"
      echo "          существующий --dest не трогает."
      echo "  vtt     скачать мелкие файлы с serpent.vtt.fi (dec/nfy/photon);"
      echo "          большой ACE-пакет (6-8 ГБ) скачать вручную по напечатанной ссылке."
      echo "  jef3.dec (JEFF-3.3, нужен для распадов) на VTT нет — привозится отдельно,"
      echo "  скрипт его проверяет и никогда не подменяет другим файлом."
      echo "  sss2 качать не умеет (proprietary VTT): положи бинарник рядом или в PATH."
      exit 0 ;;
    *) echo "Unknown option: $1 (see ./setup.sh --help)" >&2; exit 2 ;;
  esac
  shift
done

[ -z "$EXE" ] && { [ -x "$DIR/sss2" ] && EXE="$DIR/sss2" || EXE="sss2"; }

if [ "$CHECK" = "1" ] || [ -z "$MODE" ]; then
  [ -z "$MODE" ] && { echo "No --mode given: running checks only."; echo ""; }
  sh "$DIR/tools/doctor.sh" --data "$DATA" --exe "$EXE"
  exit $?
fi

ARGS="--mode $MODE --dest $DATA"
[ -n "$SRC" ] && ARGS="$ARGS --src $SRC"
[ "$MODE" = "vtt" ] && ARGS="$ARGS --lib $LIB"
[ "$FORCE" = "1" ] && ARGS="$ARGS --force"
# shellcheck disable=SC2086
sh "$DIR/tools/setup-env.sh" $ARGS || exit 1

if [ "$SKILL" = "1" ]; then
  DST="$DIR/.opencode/skill/serpent2"
  mkdir -p "$DST"
  cp "$DIR/.opencode/skill/serpent2/SKILL.md" "$DST/SKILL.md" 2>/dev/null || true
  echo "skill: $DST/SKILL.md"
fi

echo ""
sh "$DIR/tools/doctor.sh" --data "$DATA" --exe "$EXE"
