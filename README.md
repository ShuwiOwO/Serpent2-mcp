# serpent2-mcp — MCP-сервер для Serpent 2

MCP-сервер (Model Context Protocol) для нейтронно-физических расчётов в
[Serpent 2](https://serpent.vtt.fi). Даёт ИИ-ассистенту (OpenCode, Claude
Desktop, Cursor и др.) три возможности:

1. **Знать язык Serpent** — конспект, точный синтаксис всех карт и
   `set`-опций из официальной документации, готовые примеры.
2. **Проверять и запускать расчёты** — статический линтер (3 уровня, включая
   `sss2 --noplot --norun`), фоновые задачи, логи, остановка.
3. **Разбирать результаты** — `_res.m` / `_det.m` / `_dep.m` в JSON,
   читаемые сводки и графики PNG.

Сервер не содержит кода Serpent (он проприетарный): нужен ваш собственный
бинарник `sss2` — локальный или доступный по SSH.

**Требования:** Python ≥ 3.10, MCP-клиент (OpenCode), интернет один раз для
кэша документации; для расчётов — установленный Serpent 2 с библиотеками
данных.

---

## Быстрый старт

### 1. Установка

```sh
cd /путь/к/Serpent2-mcp
./setup.sh                    # установка + интерактивный выбор библиотеки данных
# ./setup.sh --data endfb71   # без вопросов: ENDF/B-VII.1 (6.6 ГБ)
# ./setup.sh --data jeff32    # JEFF-3.2
# ./setup.sh --data jendl40   # JENDL-4.0
# ./setup.sh --data none      # только сервер, данные позже
# ./setup.sh --no-plots       # без графиков (меньше зависимостей)
# ./setup.sh --status         # проверить, что установлено
```

Установщик сразу скачивает данные в `./xsdata`: выбранный нейтронный пакет
(ACE + dec + nfy), термальное рассеяние (`sss_thxs`) и фотонную физику
(`photon_data`), после чего прописывает пути в directory-файлах относительно
корня workspace. Единственный файл, который нужно положить вручную —
`mcplib84` для фотонного транспорта; в конце установки скрипт печатает
заметный блок с точным путём и создаёт `xsdata/README_mcplib84.txt` с
инструкцией. Данные можно не качать сейчас: `--data none`, а позже —
`serpent_setup_data` из OpenCode.

В `xsdata/` создаются стабильные имена `data.xsdata` / `data.dec` / `data.nfy`
(симлинки на реальные файлы), пути внутри `*.xsdata` прописываются
**абсолютными** (как у VTT), и добавляются natural-алиасы (`H-nat.84p` и т.п.)
для совместимости со старыми колодами. Дополнительно скачиваются
`sss_endfb7.dec`/`sss_endfb7.nfy` — имена, которые используют старые задания
(JEFF-3.3 decay на VTT отсутствует; ближайший хостируемый файл —
`s2v0_jeff311.dec`, доступен как `download_data_library("jef3")`).

Загрузка идёт одним соединением с докачкой после обрыва (`.part` + Range).
В терминале рисуется однострочный прогресс-бар с процентом, скоростью и ETA;
в фоновых задачах MCP (не-TTY) вместо него — редкие строки в лог (раз в
10 секунд). Скорость ограничена маршрутом до `serpent.vtt.fi`; если у вас
есть зеркало, укажите `SERPENT_DATA_REPO_URL=https://...` — ссылки на пакеты
будут переписаны на него. Альтернатива для больших библиотек: скачать один
раз на быстрой машине и перенести каталог `xsdata/` (rsync/scp).

Установщик также копирует `SKILL.md` в `<папка запуска>/.opencode/skill/serpent2/`
(флаги `--skill`, `--global-skill`, `--no-skill`) и, если рядом лежит `./sss2`,
запускает self-check: собирает минимальный вход из установленных directory-файлов
и прогоняет `./sss2 -noplot -norun`.

В конце установщик спросит, создать ли `opencode.json` автоматически:
`1` — в текущем каталоге (откуда запущен `./setup.sh`), `2` — глобально в
`~/.config/opencode/opencode.json`, `3` — не создавать (будет напечатана
инструкция). Неинтерактивные варианты: `--opencode`, `--opencode-global`,
`--no-opencode`. Существующий конфиг не затирается — запись сервера
добавляется/обновляется, остальные ключи сохраняются.

Альтернатива — `pipx install .`; тогда в конфиге OpenCode команда будет
`["serpent2-mcp"]` вместо пути к python из `.venv`.

### 2. Подключение к OpenCode

Добавьте в `opencode.json` проекта или в глобальный
`~/.config/opencode/opencode.json` (можно взять готовый
`opencode.example.json` и поправить путь):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "serpent": {
      "type": "local",
      "command": ["/полный/путь/Serpent2-mcp/.venv/bin/python", "-m", "serpent2_mcp"]
    }
  }
}
```

После изменения конфига **перезапустите OpenCode**.

### 3. Проверка

Спросите ассистента: «вызови serpent_get_environment» — он покажет
найденный `sss2`, версию, стиль CLI и пути к данным. Или из терминала:

```sh
.venv/bin/python -m serpent2_mcp --status
```

При первом запуске сервер в фоне скачивает кэш документации (~1 минута);
до завершения работают `serpent_get_card` (встроенный индекс) и
`serpent_get_reference`, а полнотекстовый поиск сообщит об ожидании.

### 4. Бинарник Serpent и данные

По умолчанию сервер ищет:

- `sss2` — в рабочей папке OpenCode (на глубину 3), затем в `PATH`;
- данные — `*.xsdata`, `*.dec`, `*.nfy` рядом с рабочей папкой (глубина 3).

Если Serpent лежит в другом месте, добавьте в блок `environment`:

```json
"environment": {
  "SERPENT_EXE": "/mnt/Serpent2/sss2",
  "SERPENT_DATA_DIR": "/mnt/Serpent2/xsdata"
}
```

На macOS без Serpent доступны все «знаниевые» инструменты, статическая
валидация и скачивание данных; расчёты можно запускать на Linux по SSH.

Данные с нуля в пустой рабочей папке (где уже лежит `./sss2`): вызовите
`serpent_setup_data(neutron="endfb71")` — он скачает нейтронную библиотеку и
термальное рассеяние, пропишет пути относительно корня workspace и вернёт
готовые `set`-строки (подробнее — «Установка данных с нуля»).

---

## Установка на другой ПК (Linux)

### С интернетом на целевой машине

Скопируйте репозиторий (`git clone`, `rsync -a`, `scp -r` или архивом),
поставьте Python и запустите установщик:

```sh
# Debian/Ubuntu:
sudo apt install python3 python3-venv
# Fedora/RHEL:
# sudo dnf install python3 python3-pip

tar -xzf Serpent2-mcp.tar.gz        # если переносили архивом
cd Serpent2-mcp
./setup.sh                          # или ./setup.sh --data endfb71 / --data none
./setup.sh --status                 # python, venv, версия пакета, данные
```

`setup.sh` использует только POSIX sh, работает на macOS и Linux, не требует
root и не трогает систему: всё ставится в локальный `.venv` внутри папки.

### Полностью офлайн

На машине с интернетом и **той же ОС/архитектурой** (например, тоже Linux
x86_64) соберите бандл «проект + все wheel-пакеты»:

```sh
cd Serpent2-mcp
./tools/make_offline_bundle.sh                    # → dist-offline.tar.gz
# INCLUDE_PLOTS=0 ./tools/make_offline_bundle.sh  # без matplotlib

scp dist-offline.tar.gz user@target:
```

На целевой машине:

```sh
tar -xzf dist-offline.tar.gz
cd Serpent2-mcp
./setup.sh --offline --wheelhouse ../wheelhouse --data none
# затем при появлении сети: ./setup.sh --data endfb71
# или из OpenCode: serpent_setup_data(neutron="endfb71")
```

`pydantic-core` и `matplotlib` содержат платформенные бинарники, поэтому
wheelhouse собирается под ту же ОС/архитектуру. Офлайн-установка ставится из
wheel-файлов: для обновления распакуйте новый бандл и повторите команду.

### Без установки на Linux вообще

Если OpenCode работает на macOS, а Serpent — на Linux-сервере, ставить
сервер на Linux не нужно: включите SSH-бэкенд (см. ниже), MCP-процесс
останется на Mac, а `sss2` будет запускаться на удалённой машине.

### Конфиг на Linux-машине

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "serpent": {
      "type": "local",
      "command": ["/home/USER/Serpent2-mcp/.venv/bin/python", "-m", "serpent2_mcp"],
      "environment": {
        "SERPENT_EXE": "/mnt/Serpent2/sss2",
        "SERPENT_DATA_DIR": "/mnt/Serpent2/xsdata"
      }
    }
  }
}
```

Skill (`SKILL.md`) при работе в папке репозитория подхватывается
автоматически; для других проектов скопируйте `skills/serpent2/` в
`~/.config/opencode/skill/serpent2/`.

---

## Конфигурация

Все параметры опциональны. Порядок применения: значения по умолчанию → файл
`serpent2-mcp.toml` (в проекте или `~/.config/serpent2-mcp/config.toml`) →
переменные окружения `SERPENT_*`. Шаблон — `serpent2-mcp.example.toml`.
Файлы `opencode.json` и `serpent2-mcp.toml` добавлены в `.gitignore`, так как
обычно содержат машинозависимые абсолютные пути.

| Переменная | Назначение |
|---|---|
| `SERPENT_EXE` | путь к `sss2` (или имя команды) |
| `SERPENT_DATA_DIR` | каталоги с данными (через `:`/`;`) |
| `SERPENT_ACELIB`, `SERPENT_DECLIB`, `SERPENT_NFYLIB` | явные файлы данных |
| `SERPENT_BACKEND` | `local` (по умолчанию) или `ssh` |
| `SERPENT_SSH_HOST` | `user@host` для удалённых запусков |
| `SERPENT_SSH_WORKDIR` | рабочий каталог на удалённой машине |
| `SERPENT_SSH_JOBDIR` | каталог задач на удалённой машине (по умолч. `~/.serpent2-mcp/jobs`) |
| `SERPENT_SSH_OPTS` | доп. опции ssh, например `-o BatchMode=yes` |
| `SERPENT_OMP` | число OpenMP-потоков по умолчанию |
| `SERPENT_MPI_LAUNCHER` | шаблон запуска MPI, по умолч. `mpirun -np {n}` |
| `SERPENT_JOB_TIMEOUT` | убить задачу через N секунд (0 = никогда) |
| `SERPENT_EXTRA_ROOTS` | дополнительные разрешённые каталоги |
| `SERPENT_ALLOW_OUTSIDE` | `1` — разрешить запуск файлов вне рабочей папки |
| `SERPENT_DOCS_AUTO_SYNC` | `0` — не обновлять документацию автоматически |
| `SERPENT_DATA_REPO_URL` | зеркало репозитория данных VTT (например, `https://mirror.example/serpent`) |
| `SERPENT_LANG` | язык сводок/подписей графиков: `ru` или `en` |

### Запуск на Linux по SSH (с macOS)

```json
"environment": {
  "SERPENT_BACKEND": "ssh",
  "SERPENT_SSH_HOST": "user@server",
  "SERPENT_SSH_WORKDIR": "/home/user/serpent/runs"
}
```

Сервер создаст каталог задачи на удалённой машине, загрузит `run.sh`,
запустит `sss2` через `nohup`, читает лог, умеет останавливать задачу.
Входной файл должен существовать по тому же пути на удалённой машине
(общий каталог, rsync или NFS). Уровень 3 валидации (`sss2 --norun`) для
SSH-бэкенда недоступен — используйте его на самом хосте.

---

## Инструменты

| Инструмент | Что делает |
|---|---|
| `serpent_get_environment` | находит `sss2`, версию, стиль CLI (`-`/`--`), данные, статус кэша доков |
| `serpent_get_reference` | конспект Serpent (тема: `geometry`, `burnup`, `sources`, `versions`, …) |
| `serpent_search_docs` | полнотекстовый поиск по официальной документации |
| `serpent_get_card` | точный синтаксис карты/опции (`surf`, `set acelib`, `sb`, …) |
| `serpent_list_cards` | список всех карт и `set`-опций |
| `serpent_get_examples` | встроенные примеры (pin cell, защита, burnup, групповые константы) |
| `serpent_validate_input` | статические проверки + `sss2 --noplot --norun` (уровень 3) |
| `serpent_run` | фоновый запуск, возвращает `job_id` |
| `serpent_job_status` | статус задачи, прогресс и хвост лога (без id — список задач) |
| `serpent_job_output` | больше лога |
| `serpent_job_kill` | остановить задачу |
| `serpent_get_results` | сводка `_res.m`/`_det.m`/`_dep.m` в JSON |
| `serpent_plot_results` | PNG: спектры детекторов, k-eff, burnup, произвольные переменные |
| `serpent_setup_data` | с нуля: нейтронный пакет + термальное рассеяние + dec/nfy + photon data, абсолютные пути, алиасы, готовые `set`-строки |
| `serpent_selfcheck` | проверка установки: минимальный `-norun` прогон, версия, ошибки, нехватка файлов |
| `serpent_list_energy_structures` | предопределённые энергосетки для `ene NAME 4 <structure>` (scale44/56/238/…, `_ext`) |
| `serpent_mcplib84_instructions` | что и куда положить вручную (MCPLIB84 — лицензия LANL/RSICC) |
| `serpent_list_data_libraries` | каталог библиотек VTT (ENDF/B-VII.1, JEFF-3.2, JENDL-4.0, FENDL-3.0, …) |
| `serpent_download_data_library` | фоновая докачка библиотеки с resume и распаковкой |
| `serpent_install_photon_data` | фотонные данные: VTT `mcplib.xsdata` + `photon_data` и привязка `mcplib84` из `acedata/` с патчем путей |
| `serpent_check_data_paths` | проверка/починка путей внутри `*.xsdata` (`apply=false` — только отчёт) |
| `serpent_sync_docs` | обновить/пересобрать кэш документации |

Типовой цикл: `get_card` → `validate_input` → `run` → `job_status` →
`get_results` → `plot_results`. Все расчёты фоновые и не блокируют чат.

---

## Ядерные данные

Инструмент `serpent_download_data_library` качает данные с официального
репозитория VTT `https://serpent.vtt.fi/repository/`. Каталог
(`serpent_list_data_libraries`) знает основные библиотеки и принимает
понятные псевдонимы: `JEFF`, `JEFF-3.2`, `ENDF/B-VII.1`, `JENDL`,
`JENDL-4.0`, `FENDL`, `thermal`, `photon`, `edep` и т.д.

| Ключ | Что это | Размер |
|---|---|---|
| `endfb71` | ENDF/B-VII.1 (0…1800 K), каталог `data.xsdata` | 6.63 ГБ |
| `jeff32` | JEFF-3.2 | 7.34 ГБ |
| `jendl40` | JENDL-4.0 | 6.16 ГБ |
| `fendl30` | FENDL-3.0 rev.4 (термояд) | 7.20 ГБ |
| `endfb71_edep` | спец. библиотека для energy deposition | 3.77 ГБ |
| `thxs` | библиотеки теплового рассеяния S(α,β) | 91 МБ |
| `sss_endfb7.dec`, `sss_endfb7.nfy` | данные распада и выходы деления | 35 МБ / 7 МБ |
| `photon_data` | фотонная физика для `set pdatadir` (VTT) | 7.7 МБ |
| `photon_xsdata` | отдельный directory-файл `mcplib.xsdata` (VTT), если в основном `data.xsdata` нет `.84p` | 15 КБ |
| `mcplib84` | ACE-данные MCPLIB84 — обычно уже лежат в `acedata/` пакета xsdata | ~15–200 МБ |
| `jeff40.xsdata`, `endfb81.xsdata`, `jendl5.xsdata`, `fendl32c.xsdata` | исправленные directory-файлы для новых оценок | < 1 МБ |

Куда кладётся:

- по умолчанию — в первый каталог из `SERPENT_DATA_DIR`, иначе в `./xsdata`
  рядом с рабочей папкой (там же, где обычно лежит `sss2`);
- `.tar.gz` распаковывается **прямо в этот каталог**, поэтому рядом
  появляются `data.xsdata`, `acedata/`, `*.dec`, `*.nfy` — их и указывайте в
  `set acelib` / `set declib` / `set nfylib`;
- загрузка идёт в фоне: `serpent_job_status(job_id)` показывает
  `progress` (байты/всего) и хвост лога; докачка после обрыва
  поддерживается (`.part` + `Range`);
- данные скачиваются **на машине, где запущен MCP-сервер**; для удалённых
  расчётов их нужно получить на целевом хосте.

### Установка данных с нуля

Данные можно поставить сразу установщиком (`./setup.sh --data endfb71`), а
можно позже из OpenCode — один вызов готовит каталог целиком (фоновая задача,
6–8 ГБ):

```
serpent_setup_data(neutron="endfb71", dest="xsdata")
#   neutron: endfb71 | jeff32 | jendl40 | fendl30
#   with_photon=true по умолчанию
```

Что происходит: скачивается и распаковывается нейтронный пакет (внутри уже
есть decay/fission-yield данные) **и термальное рассеяние** (`sss_thxs`,
~253 МБ), все пути `/xs/data/...` внутри `*.xsdata` переписываются на
локальные файлы **относительно корня рабочей папки**, затем ставится фотонная
физика. По завершении (`serpent_job_status` → `progress`) в отчёте и в
`serpent_get_environment` будут готовые строки:

```
set acelib "xsdata/data.xsdata"
set declib "xsdata/sss_endfb7.dec"
set nfylib "xsdata/sss_endfb7.nfy"
set pdatadir "xsdata/photon_data"
```

Если каких-то файлов не хватает, инструмент вернёт `state: partial` и список
`missing`. Единственный файл, который **нельзя** скачать автоматически —
`mcplib84` (фотонные ACE-кросс-секции, лицензия LANL/RSICC, США). По нему
`setup_data` вернёт блок `manual_download` с точным путём, а подсказать
человеку можно инструментом:

```
serpent_mcplib84_instructions()
# → download_url, place_file_at (например "xsdata/mcplib84"), абсолютный путь,
#   альтернатива photon_libraries/mcplib84, проверка файла и следующий шаг
```

После того как файл положен, достаточно вызвать
`serpent_install_photon_data` или `serpent_check_data_paths` — пути будут
проверены и прописаны. Если фотонный транспорт не нужен, `mcplib84` можно
игнорировать: нейтронные расчёты полностью готовы.

Библиотеки JEFF-4.0, ENDF/B-VIII.1, JENDL-5 и FENDL-3.2c (сами ACE-данные)
распространяются не VTT, а OECD/NEA, NNDC, JAEA и IAEA; в каталоге для них
есть только исправленные directory-файлы.

### Фотонные данные (photon transport)

Фотонные кросс-секции — это ACE-файл `mcplib84`, на который ссылаются записи
`.84p` в directory-файле. Важно:

- **пакеты VTT содержат только нейтронные данные** (см. VTT-R-00118-18:
  «includes only free-atom neutron interaction data»), поэтому `mcplib84` в
  них нет;
- VTT хостит физические данные для `set pdatadir` (`photon_data.tar.gz`) и
  отдельный directory-файл `mcplib.xsdata` (только индекс, без данных);
- в сборках/старых рабочих папках (как `Serpent2/xsdata` с кластера)
  `mcplib84` обычно уже лежит в `acedata/`, и основной `data.xsdata` содержит
  записи `.84p`/`.63p` — тогда всё работает сразу, без `mcplib.xsdata`.

Рабочий процесс:

```
# 1. Нейтронная библиотека + фотонная физика одним вызовом:
serpent_setup_data(neutron="endfb71", dest="xsdata")

# 2. Если mcplib84 есть в xsdata/acedata/ или photon_libraries/ — инструмент
#    найдёт его сам. Если нет — передайте его явно:
serpent_setup_data(neutron="endfb71", dest="xsdata",
                   ace_file="photon_libraries/mcplib84")
#    или ace_url="https://..."

# 3. В input (пути — относительно каталога запуска sss2, т.е. корня workspace):
set acelib "xsdata/data.xsdata" "xsdata/mcplib.xsdata"
set pdatadir "xsdata/photon_data"
```

Проверить и починить пути во всех `*.xsdata` можно инструментом
`serpent_check_data_paths(directory="xsdata")` (или `apply=false` для отчёта
без записи): он находит каждый файл по имени, переписывает пути и показывает,
чего не хватает (например, `mcplib84`).

Источник `mcplib84`, если его нет: `https://nucleardata.lanl.gov/ace/mcplib84/`
(сайт LANL периодически недоступен) или другая ваша копия LANL/RSICC.
**Не публикуйте данные LANL/RSICC (`photon_libraries/`, `data/`, `mcplib84`)
в открытом репозитории**; эти пути добавлены в `.gitignore`.

---

## Документация и версии

- Кэш документации: `~/.cache/serpent2-mcp/docs/serpent2.sqlite3`
  (477 разделов, 56 страниц, 229 карт; автосинк раз в 30 дней,
  принудительно — `serpent_sync_docs(force=true)`).
- Офлайн всегда работают `serpent_get_card`, `serpent_list_cards`,
  `serpent_get_reference`, `serpent_get_examples` — на встроенном индексе
  `cards_static.json` и рукописном `primer.md`.
- Целевая версия — актуальная документация (0.21.0 / Serpent 2.2.5).
  `serpent_get_environment` предупреждает о beta/старых версиях, стиль CLI
  (`--norun` или `-norun`) подбирается автоматически; различия версий
  смотрите в `serpent_get_reference("versions")`.

## Skill и AGENTS.md

- `.opencode/skill/serpent2/SKILL.md` — при работе в этом репозитории
  OpenCode подхватывает skill сам; для других проектов скопируйте в
  `~/.config/opencode/skill/serpent2/`.
- `AGENTS.example.md` — правила для `AGENTS.md` проекта, обязывающие
  ассистента пользоваться `serpent_*` инструментами.

## Обновление

```sh
# онлайн-установка (editable):
cd Serpent2-mcp && git pull && ./setup.sh     # зависимости обновятся при необходимости

# офлайн-установка:
# повторить сборку бандла и `./setup.sh --offline --wheelhouse ../wheelhouse`
```

## Разработка и тесты

```sh
./setup.sh --dev
.venv/bin/python -m pytest tests -q     # 78 тестов, Serpent не требуется
.venv/bin/python tools/gen_cards.py     # пересобрать индекс карт из docs
```

Индекс `cards_static.json` содержит только факты (имена карт и параметров,
синтаксис, ссылки) — без текстов документации VTT, поэтому его можно
публиковать. Полные описания подтягиваются из локального кэша после первого
синка. Для локального использования описания можно вернуть в индекс:

```sh
.venv/bin/python tools/gen_cards.py --max-notes 800   # не публиковать этот файл
```

Тесты используют «фейковый `sss2`»: эмулируют успешный/неуспешный запуск,
SSH-бэкенд и докачку по локальному HTTP-серверу.

## Возможные проблемы

| Симптом | Решение |
|---|---|
| `sss2 not found` | положите `./sss2` в рабочую папку, добавьте в `PATH` или задайте `SERPENT_EXE` |
| `path ... outside the allowed roots` | укажите `SERPENT_EXTRA_ROOTS` или `SERPENT_ALLOW_OUTSIDE=1` |
| Сервер не появился в OpenCode | проверьте JSON конфига, перезапустите OpenCode, `./setup.sh --status` |
| `matplotlib is not installed` | `./setup.sh` (с графиками) — или используйте сервер без `plot_results` |
| Поиск по докам пуст | первый синк ещё идёт: `serpent_sync_docs` или подождите минуту |
| Старая версия Serpent | `serpent_get_environment` показывает версию (например, `2.1.32 beta`) и предупреждает о расхождении с докой 2.2.5; флаги CLI подбираются автоматически (`-norun`/`--norun`) |
| Загрузка данных прервалась | повторите ту же команду (`./setup.sh --data ...` или `serpent_setup_data`) — докачка с `.part` продолжит с места обрыва |
| `Photon/Neutron emission rate 0.00000E+00` после `sg` | в материале нет decay-нуклидов: добавьте нуклид без библиотечного суффикса (`Cm-250`, `270600`) и `set declib` |
| Детектор пуст или падает `de scale44` | предопределённые сетки нельзя использовать в `de` напрямую: сначала `ene e 4 scale44` |
| `dr -100` не работает | нужен `fun NAME 1 5 E1 F1 …` с тем же именем |
| Огромный `_det.m` читается долго | сервер стримит файлы >20 МБ (значения усечены, для спектров — `serpent_plot_results`) |
| Данные качаются медленно | скорость ограничена маршрутом до VTT; попробуйте зеркало `SERPENT_DATA_REPO_URL` или перенесите готовый каталог `xsdata/` с другой машины |
| Level 3 не запускается | нет `sss2` (SSH-бэкенд) — используйте уровень 2 на хосте с Serpent |
| Старый Serpent не знает флаг | сервер сам подбирает `-`/`--` по выводу `sss2`; проверьте `serpent_get_environment` |

## Лицензия

Код сервера, тесты, skill и скрипты — **MIT** (см. `LICENSE`). Лицензия не
распространяется на Serpent 2 (проприетарное ПО VTT, сервер его не содержит
и не распространяет) и на документацию VTT, которая скачивается в локальный
кэш; `cards_static.json` в репозитории содержит только фактические данные
(имена, параметры, синтаксис) без текстов документации.

## Ограничения

- Docker-бэкенд зарезервирован, но не реализован (планируется `docker exec`
  в контейнер с вашим `sss2`).
- Уровень 3 валидации (`sss2 --norun`) недоступен через SSH-бэкенд.
- Кэш документации — © VTT; в репозиторий не коммитится, собирается
  локально. `cards_static.json` в коммите содержит только фактические
  данные (имена, параметры, синтаксис). Serpent — проприетарное ПО с
  экспортными ограничениями; сервер лишь управляет вашей установкой.
