# Serpent 2.1.32 — BOOT (вставь в начало нового чата)

Serpent 2 — continuous-energy 3D Monte Carlo переноса нейтронов/фотонов (VTT).
Вход — текстовый файл карт, разделитель — пробелы. Карта заканчивается там, где
начинается следующая карта (строки не важны, одна карта может занимать много строк).
Карты case-insensitive. Комментарии: `%` до конца строки, `/* ... */` (без вложенности).
Порядок карт свободный. `include "FILE"` — вложенный файл.

## 5 правил (сначала это)

1. Читай ТЗ и эталон буквально. Не меняй метод: `sg`↔`sb`, `dr`, геометрию — только по явной просьбе.
2. Не угадывай синтаксис: смотри `references/syntax-2.1.32.md` и `TASKS.md`. Опечатка в имени карты молча склеивает её с предыдущей картой.
3. Smoke first: `tools/serpent-lint.py input` → `sss2 input -noplot -norun` → маленький `set nps` → длинный счёт.
4. Проверяй каждый прогон: `_res.m` (`TOT_SRCRATE`, `NORM_COEF`, k-eff), `_det*.m`, для распада `_gsrc.m/_nsrc.m` (`tot` = физ. мощность для `set srcrate`). Пустой детектор или `rate 0` = чинить вход, не менять метод.
5. Версия 2.1.32: CLI только одинарный дефис (`-version`, `-norun`, `-noplot`, `-omp N`). Дока 2.2.x — только как diff (`references/diff-2.1-vs-2.2.md`).

## Минимум геометрии

```serpent
surf s_src sph -200 0 0 5
surf s_out sph 0 0 0 500
cell c_src  0 curium -s_src
cell c_inner 0 void  -s_out #c_src
cell c_out  0 outside  s_out
```

`-s` = внутри, `s`/`+s` = снаружи, `#cell` = вычесть ячейку. Мир обязан закрываться `outside`. `set bc 1` — чёрная граница.

## Материалы и данные (эталонная связка)

```serpent
mat curium -13.5 vol 0.5
Cm-250 1
set acelib "xsdata/data.xsdata"
set declib "xsdata/jef3.dec"
set nfylib "xsdata/sss_endfb7.nfy"
set pdatadir "xsdata/photon_data"
```

- Плотность/фракции: `>0` = атомные (1e24/см³), `<0` = массовые (г/см³). Не смешивать.
- Нейтроны: `H-1.03c`, `O-16.03c`, `U-235.03c`. Фотоны: `H-nat.84p`, `O-nat.84p` (нужны natural-алиасы + `acedata/mcplib84`).
- Распад: `Cm-250`/`270600`/`Ir-192`/`Co-60` — без суффикса библиотеки (decay-нуклид). `96250.03c` — транспортный, для `sg` может дать `emission rate 0`.
- `jef3.dec` = JEFF-3.3 (43 МБ, NEA). Нет на VTT — не подменять молча на `sss_endfb7.dec`.
- Пути — относительно каталога запуска `sss2`. Абсолютные пути из чужих эталонов переписать.

## Источники: sg → sb (задача 1.3)

```serpent
src isotope n
    sg -1 1
    sp -200 0 0
    srad 0 5
ene e 4 scale44
det NRG dr -11 void de e
set nps 10000 100
```

Прогон `sg` пишет `_gsrc.m/_nsrc.m`. Взять `tot` → второй прогон:

```serpent
src isotope n
    sp -200 0 0
    srad 0 5
    sb 15 1
        3.0E-03 0
        ... спектр из DET NRG, делённый на ширины групп ...
    sm curium
set srcrate 1.03089E+11
```

- Предопределённую сетку (`scale44`) нельзя в `de` напрямую — только через `ene e 4 scale44`.
- `sb` — параметр карты `src`, его строки продолжаются до следующей карты. Строка данных не должна начинаться с `mat/cell/set/det/...`.
- `dr -200` (доза на человеке), `dr -11` (спектр излучения). `dr -100 NAME` требует `fun NAME ...`.

## Детекторы, время, VR

```serpent
det HUMAN dm H2O dv 226194.671
tme TB 2 100 0 0.1
det LIFE dm D20 di TB
wwgen GENA 1E-12 4 3 -1 1
    -210 35 30
    -45 45 30
    -110 110 30
wwin WIN
    wi 1 5
        GENA 1
        GENA 1
        GENA 1
        GENA 1
        GENA 1
```

## Запуск и выходы

```sh
sss2 -version
sss2 case -noplot -norun   # быстрый полный парсинг входа
sss2 case -omp 4
```

Выходы: `case.out`, `case_res.m`, `case_det0.m`, `case_gsrc.m`, `case_nsrc.m`, `case.seed`.
Ошибка входа: `Input error in parameter "cell" on line 8 ...` — чинить и повторять (первая ошибка скрывает остальные).
`tools/serpent-lint.py` — статика до запуска; `tools/serpent-results.py` — сводка `.m`; `tools/doctor.sh` — проверка окружения.
