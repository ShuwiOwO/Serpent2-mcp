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
./setup.sh              # создаёт .venv и ставит зависимости (+ matplotlib)
# ./setup.sh --no-plots  # без графиков (меньше зависимостей)
# ./setup.sh --status    # проверить, что установлено
```

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
./setup.sh                          # или ./setup.sh --no-plots
./setup.sh --status                 # python, venv, версия пакета
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
./setup.sh --offline --wheelhouse ../wheelhouse
# добавьте --no-plots, если бандл собран без matplotlib
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
| `serpent_list_data_libraries` | каталог библиотек VTT (ENDF/B-VII.1, JEFF-3.2, JENDL-4.0, FENDL-3.0, …) |
| `serpent_download_data_library` | фоновая докачка библиотеки с resume и распаковкой |
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
| `photon_data`, `mcplib84` | фотонные данные | 7.7 МБ / 15 КБ |
| `jeff40.xsdata`, `endfb81.xsdata`, `jendl5.xsdata`, `fendl32c.xsdata` | исправленные directory-файлы для новых оценок | < 1 МБ |

Куда кладётся:

- по умолчанию — в первый каталог из `SERPENT_DATA_DIR`, иначе в `./data`
  рядом с рабочей папкой;
- `.tar.gz` распаковывается **прямо в этот каталог**, поэтому рядом
  появляются `data.xsdata`, `*.dec`, `*.nfy` — их и указывайте в
  `set acelib` / `set declib` / `set nfylib`;
- загрузка идёт в фоне: `serpent_job_status(job_id)` показывает
  `progress` (байты/всего) и хвост лога; докачка после обрыва
  поддерживается (`.part` + `Range`);
- данные скачиваются **на машине, где запущен MCP-сервер**; для удалённых
  расчётов их нужно получить на целевом хосте.

Библиотеки JEFF-4.0, ENDF/B-VIII.1, JENDL-5 и FENDL-3.2c (сами ACE-данные)
распространяются не VTT, а OECD/NEA, NNDC, JAEA и IAEA; в каталоге для них
есть только исправленные directory-файлы.

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
.venv/bin/python -m pytest tests -q     # 36 тестов, Serpent не требуется
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
