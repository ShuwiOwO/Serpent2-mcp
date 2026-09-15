---
name: serpent2
description: Use when writing, validating, running or analysing Serpent 2.1.32 Monte Carlo inputs (sss2, input cards, set acelib, sg/sb sources, detectors, _res.m/_gsrc results, dose). OpenCode-native, no MCP required.
---

# Serpent 2.1.32 (Monte Carlo transport, OpenCode-native)

Serpent 2 — continuous-energy 3D Monte Carlo (VTT). Вход — текст карт; карта
заканчивается следующей картой. Комментарии `%` и `/* ... */`. Версия эталона —
**2.1.32 beta**, CLI только одинарный дефис (`-version`, `-norun`, `-noplot`).

## Порядок работы (обязательно)

1. Прочитай ТЗ буквально. Если есть эталон (`TASKS.md` → HW), открой его и не меняй метод (`sg`/`sb`, `dr`, геометрию).
2. Прочитай `BOOT_2.1.32.md` целиком, затем нужное из `references/` (`syntax-2.1.32.md`, `data-2.1.32.md`, `pitfalls.md`, `diff-2.1-vs-2.2.md`).
3. Проверь вход: `python3 tools/serpent-lint.py <input>` — исправить все `error`.
4. Smoke: `sss2 <input> -noplot -norun`, затем маленький `set nps`, затем длинный счёт.
5. Разбери выходы: `python3 tools/serpent-results.py --summary <input>` (`_res.m`: `TOT_SRCRATE`, `NORM_COEF`; `_det*.m`; `_gsrc/_nsrc.m tot` = `set srcrate` для SB-варианта).
6. Окружение: `sh tools/doctor.sh [--data xsdata]`. Данные чинит `sh tools/setup-env.sh --help` (режимы `etalon`/`vtt`, `jef3.dec` не подменяется молча).

## Ловушки 2.1.32 (коротко)

- `sg` без decay-нуклида (`Cm-250`, не `96250.03c` для фотонов) → `rate 0`. Чинить материал, не метод.
- `de scale44` напрямую нельзя → `ene e 4 scale44` + `de e`. `dr -100` только с `fun`.
- Строки `sb` продолжаются до следующей карты; не начинать их с `mat/cell/set/det`.
- Пути `set acelib/declib/nfylib/pdatadir` — относительно каталога запуска `sss2`.
- `photon_data/data.xsdata` игнорировать (мусор-дубликат). `jef3.dec` (JEFF-3.3) не заменять на `sss_endfb7.dec`.
