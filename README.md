# serpent-kit — Serpent 2.1.32 + OpenCode

Портируемый набор для работы с Monte Carlo кодом переноса частиц
[Serpent 2](https://serpent.vtt.fi) (VTT, Финляндия) через любую нейросеть.
Ядро — файлы знаний и zero-deps инструменты, поэтому работает и в OpenCode
(через Skill), и в обычном чате (copy-paste `BOOT_2.1.32.md`).

Целевая версия — **Serpent 2.1.32 beta** (CLI только с одинарным дефисом:
`-version`, `-norun`, `-noplot`, `-omp N`).

## Что в репозитории, а чего нет

В репо: знания (`BOOT_2.1.32.md`, `TASKS.md`, `references/`), Skill для OpenCode,
инструменты (`tools/`, Python 3 без зависимостей + POSIX sh), пример
(`examples/`), установщик окружения (`setup.sh`). Код — MIT.

В репо нет и не будет: бинарника `sss2` (proprietary VTT), ядерных данных
(гигабайты + лицензия LANL/RSICC для фотонных `mcplib`), документации VTT (© VTT),
чужих входов и результатов расчётов (см. `.gitignore`).

## Требования

- Python 3 (3.10+, только стандартная библиотека) для `tools/*.py`;
- `sh`, `curl`/`wget` для `setup.sh` (режим `vtt`);
- свой бинарник `sss2` 2.1.32 и ядерные данные (см. ниже).

## Быстрый старт в новой папке (тест с нуля)

```sh
git clone <этот-репозиторий> serpent-kit && cd serpent-kit

# 1. Положить бинарник рядом (или в PATH):
cp /путь/к/sss2 ./sss2 && ./sss2 -version
#    -> "Version 2.1.32", ASCII-арт Serpent

# 2a. Данные уже есть (USB/архив с готовой папкой xsdata) — скопировать и
#     переписать пути в *.xsdata под новую машину:
./setup.sh --mode etalon --src /путь/к/готовой/xsdata --dest xsdata

# 2b. Или чистая установка с официального репозитория VTT
#     (мелкие файлы качаются сами; большой ACE-пакет 6-8 ГБ — по напечатанной ссылке):
./setup.sh --mode vtt --lib endfb71 --dest xsdata

# 3. Проверка окружения — должно быть READY:
./setup.sh --check --data xsdata

# 4. Smoke-тест: статика + парсинг входа реальным sss2:
python3 tools/serpent-lint.py examples/01_smoke_sphere.sh
./sss2 examples/01_smoke_sphere.sh -noplot -norun
#    -> "Processing completed, calculation terminated before transport cycle."
```

Ожидаемый `doctor` на готовом окружении:

```
exe: ./sss2 (Version 2.1.32, cli: single-dash)
  ok: acelib data.xsdata / ok: declib jef3.dec (JEFF-3.3) / ok: sss_endfb7.nfy
  ok: pdatadir photon_data (11 .dat) / ok: acedata/mcplib84 / ok: acedata/sssth1
doctor: READY
```

## Как решать задачи

1. Положи постановку рядом (в репо её не коммить). Открой `BOOT_2.1.32.md`
   (в OpenCode Skill подхватывается сам) и найди класс задачи в `TASKS.md`.
2. Пиши вход по `references/syntax-2.1.32.md`. Метод из постановки не меняй
   (`sg`/`sb`, отклик детектора, геометрию). Только ASCII, батчей `set nps` ≥ 20.
3. `python3 tools/serpent-lint.py <input>` — исправить все `error`.
4. `sss2 <input> -noplot -norun`, затем короткий прогон, затем длинный.
5. `python3 tools/serpent-results.py --summary <input>` — сводка `_res/_det/_gsrc/_nsrc`
   (`tot` из `_gsrc/_nsrc` = физ. мощность для `set srcrate` в SB-прогоне).

## Структура

```
setup.sh                  установка/проверка окружения (обёртка над tools/setup-env.sh)
BOOT_2.1.32.md            вставка в новый чат любой нейросети (~100 строк)
TASKS.md                  6 классов задач: синтаксис + что сверять
references/               syntax-2.1.32.md, data-2.1.32.md, diff-2.1-vs-2.2.md, pitfalls.md
examples/                 01_smoke_sphere.sh (проверен: lint чисто, -norun exit 0)
tools/
  serpent-lint.py         статика: ASCII, карты, sg/declib, de/ene, dr/fun, пути данных
  serpent-results.py      сводка .m-файлов, стриминг больших _det
  doctor.sh               проверка окружения (только читает)
  setup-env.sh            etalon/vtt раскладка данных, правка путей, stable-алиасы
.opencode/skill/serpent2/ SKILL.md (автоподхват в OpenCode)
```

## Данные: два режима и честное предупреждение

- `etalon`: клонирует твою рабочую связку (`acedata/`, `*.dec/nfy`, `photon_data/`,
  `data.xsdata` как шаблон) и переписывает абсолютные пути в `*.xsdata`.
  Существующий `--dest` без `--force` не затирает (делает `backup-*`).
- `vtt`: мелкие файлы (`sss_endfb7.dec/nfy`, `photon_data.tar.gz`, `mcplib.xsdata`)
  качаются с `serpent.vtt.fi`; большой ACE-пакет — вручную по выведенной ссылке.
- `jef3.dec` (распады JEFF-3.3, OECD NEA) **на VTT отсутствует**. Скрипт проверяет
  его шапку и никогда не подменяет другим файлом — привезти надо отдельно.
- `mcplib84` (фотонные ACE, LANL/RSICC) тоже привозится вручную; без него доступна
  вся нейтроника, недоступен только фотонный транспорт.

## Проверено (Serpent 2.1.32, реальный бинарник)

- `doctor` → READY; `-noplot -norun` проходят нейтронные, фотонные, `tme/di` и
  `wwgen/wwin` входы; `setup-env.sh --mode etalon` в пустую папку даёт
  ~5600 строк индекса, ~860×`.03c`/200×`.84p`, `gre7.00t`, `H-nat.84p`,
  `jef3.dec` JEFF-3.3, `photon_data` 11 `.dat`, `mcplib84` — всё `ok`, ноль
  stale-путей; связка `sg→sb` сходится (`nsrc tot` = `set srcrate`).
