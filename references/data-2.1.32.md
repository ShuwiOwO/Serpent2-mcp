# Данные 2.1.32 — эталонная связка (что, откуда, чем проверять)

## Состав рабочего каталога данных (~7 ГБ)

- `acedata/`: ~432 ACE-файла нейтронных библиотек (`.03c`: ENDF/JEFF/JENDL-смесь),
  single-файлы `mcplib63`, `mcplib84` (все `.63p`/`.84p` записи указывают внутрь них),
  файл `sssth1` (все `.00t` термальные записи: `gre7.00t`, `lwj3` и т.д.).
- `data.xsdata` ~5678 строк: ~864×`.03c`, ~200×`.84p`, ~188×`.63p`, `.00t` + natural-алиасы (`H-nat.84p`). Пути внутри — абсолютные (переписываются под машину командой `setup-env.sh`).
- `jef3.dec` 43 МБ = **JEFF-3.3, NEA Data Bank, Nov 2017**. Нет на `serpent.vtt.fi`. Нужен для HW3/HW4 (`set declib`).
- `sss_endfb7.dec` 35 МБ (ENDF/B-VII, BNL 2005) + `sss_endfb7.nfy` 6.6 МБ — есть на VTT (`other_data/`). Нужны для HW2/HW5 (declib) и всех нейтронных (nfylib).
- `sss_endfb7u.xsdir` 3327 строк + `xsdirconvert.pl` — рецепт конверсии MCNP xsdir → Serpent индекс (provenance смеси).
- `photon_data/` 11×`.dat` (физика фотонов для `set pdatadir`). Лежащий рядом `photon_data/data.xsdata` — мусор-дубликат нейтронного индекса, игнорировать.

## Что ставит `tools/setup-env.sh`

| Режим | Источник | Когда |
|---|---|---|
| `--mode etalon --src <эталон> --dest <xsdata>` | локальная копия: `acedata/`, `*.dec/nfy`, `photon_data/*.dat`, `data.xsdata` как шаблон путей | у тебя и у любого, у кого уже есть связка (USB/архив). Гигабайты не качаются |
| `--mode vtt --lib endfb71 --dest <xsdata>` | `serpent.vtt.fi`: `s2v0_endfb71.tar.gz` (7.1 ГБ) + `sss_endfb7.dec/nfy` + `photon_data.tar.gz` + `mcplib.xsdata` | чистая установка новому пользователю github |

В обоих режимах после раскладки скрипт:
1. Переписывает последний столбец `*.xsdata` (пути к ACE) на `<dest>/acedata/...` (абсолютные, как у VTT).
2. Проверяет natural-алиасы `.84p` (добавляет недостающие вида `H-nat.84p → H.84p` только если самого файла `mcplib84` хватает).
3. Проверяет `jef3.dec`: в `vtt`-режиме — `MISSING` с инструкцией (NEA/локальный файл), никакого молчаливого `jeff311`.
4. Печатает готовые строки для входа (относительные):
   `set acelib "xsdata/data.xsdata"`, `set declib "xsdata/jef3.dec"`, `set nfylib ...`, `set pdatadir ...`.
5. Без `--force` существующий `--dest` не затирает; делает `backup-<дата>`.

## Лицензии (почему этого нет на github)

- `sss2` — proprietary VTT. `mcplib84/63` — LANL/RSICC. Доки VTT — © VTT. В репо только код/скрипты/примеры.
- `.gitignore` уже режет `*.xsdata/*.dec/*.nfy/mcplib84/*_res.m/*_det*.m/*.seed/*.out` — данные и результаты расчётов не утекают.
- `jef3.dec` (JEFF-3.3, OECD NEA) — качать с NEA или брать из своей копии; `setup-env.sh` проверяет шапку файла и не подменяет его файлом с VTT.

## Быстрая сверка руками

```sh
wc -l xsdata/data.xsdata            # ~5600
grep -c '\.03c' xsdata/data.xsdata   # ~860
grep -c '84p' xsdata/data.xsdata     # ~200
grep 'gre7.00t' xsdata/data.xsdata   # → acedata/sssth1
ls xsdata/acedata | grep -c ace      # ~430
ls xsdata/photon_data                # 11 .dat
head -c 200 xsdata/jef3.dec          # JEFF-3.3 ...
```
