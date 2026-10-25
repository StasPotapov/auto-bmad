# Установка и настройка

[English](../en/install.md) · [К README](../../README.ru.md)

## Что нужно

| Что | Зачем |
|---|---|
| Claude Code | auto-bmad — плагин Claude Code |
| git | каждая story кончается коммитом; проект должен быть git-репозиторием |
| uv | BMad рендерит движок `bmad-build-auto` через `uv run` |
| Python 3.11+ как `python3` | CLI `auto-bmad` — скрипты на чистой stdlib; конфиг читается через `tomllib` (3.11+) |
| BMad 6.12+ с модулем `bmm` | auto-bmad управляет движком BMad `bmad-build-auto`, а не заменяет его |
| `npx` (Node.js) | только для установщика BMad |
| плагин [adbm](https://github.com/StasPotapov/adbm) | по желанию; только для проверок на Android-эмуляторе |
| плагин [mockmatch](https://github.com/StasPotapov/mockmatch) | по желанию, рекомендуется для веб-проектов; проверки в headless-браузере и сверка с дизайном |

## Установка плагина

Попросите Claude Code: «поставь плагин auto-bmad из маркетплейса StasPotapov/auto-bmad».
Или выполните две команды сами:

```bash
claude plugin marketplace add StasPotapov/auto-bmad
claude plugin install auto-bmad@auto-bmad
```

Перезапустите Claude Code. Плагин добавляет:

- скилл `/auto-bmad:auto-bmad` — сам прогон;
- скилл `/auto-bmad:setup` — настройку проекта по шагам;
- типы сабагентов для прогона (`auto-bmad:bmad-story-runner`, ревьюеры, проверяющий);
- CLI `auto-bmad`. Пока плагин включён, его `bin/` лежит в PATH Bash-инструмента
  Claude Code. Вне Claude Code зовите CLI по полному пути в каталоге плагина.

Для проверок на Android поставьте ещё adbm и снова перезапустите Claude Code:

```bash
claude plugin marketplace add StasPotapov/sp-tools
claude plugin install adbm@sp-tools
```

Для веб-проверок поставьте mockmatch и перезапустите Claude Code. Затем попросите агента
выполнить `mockmatch doctor --install`: он создаст отдельный venv с Playwright и Chromium.

```bash
claude plugin marketplace add StasPotapov/sp-tools
claude plugin install mockmatch@sp-tools
```

## Настройка проекта

Откройте Claude Code в папке проекта и выполните:

```
/auto-bmad:setup
```

Скилл делает работу сам и спрашивает вас только в точках решения. Его можно звать сколько
угодно раз. Он отправил вас что-то поставить, перезапустить или спланировать — сделайте это
и снова вызовите `/auto-bmad:setup`. Скилл всегда начинает с фактов:

```bash
auto-bmad setup check --repo .
```

Команда печатает JSON: блок на каждый этап и поле `next` — первый незакрытый этап
и что сделать. `ready: true` — все обязательные этапы пройдены.

| Блок | Что в нём |
|---|---|
| `env` | `git`, `uv`, `python` и `python_ok` (3.11+), `npx`, `git_repo` (папка — git-репозиторий) |
| `bmad` | `installed`, `version`, `version_ok` (6.12+), `engine` (есть `.claude/skills/bmad-build-auto/SKILL.md`), `user_config`, команда `install`; `update`, если версия старая |
| `plan` | `epics` (путь к файлу эпиков в `_bmad-output/planning-artifacts/`), `sprint_status` (есть `_bmad-output/implementation-artifacts/sprint-status.yaml`) |
| `project` | `config` (есть `.auto-bmad.toml`), `test_command` (найденная команда тестов), `android` (модуль приложения, команда сборки, путь к APK, package, другие модули в `candidates`), `web` (найденный фронтенд: папка, фреймворк, команда `serve`, `url`) |
| `extras` | `adbm` (стоит ли; только для Android), `mockmatch` (стоит ли; только для веб-проектов), `personal_config` (путь к личному конфигу, если он есть) |
| `headless` | `settings` (путь к `.claude/auto-bmad-headless.json`, если он есть) |

### Этап 1 — окружение (`env`)

Нет `git`, `uv` или Python 3.11+, либо папка не git-репозиторий. Скилл называет, чего нет,
и команду установки (например, `brew install uv`, `git init`). Системные пакеты он сам
не ставит. Поставьте и вызовите `/auto-bmad:setup` снова.

### Этап 2 — BMad (`bmad`)

BMad нет, он старше 6.12 или в нём нет движка `bmad-build-auto`. Скилл предложит два пути:

- **Установщик запускаете вы** (рекомендуется: он спросит имя, язык и папки):

  ```bash
  cd /path/to/project
  npx bmad-method install
  ```

  Выберите модуль **BMad Method (bmm)** и инструмент **Claude Code**.
- **Скилл ставит сам, с умолчаниями:**

  ```bash
  npx bmad-method install --yes --modules bmm --tools claude-code
  ```

Старый BMad скилл обновляет так:

```bash
npx bmad-method install --yes --action update --modules bmm
```

Обновление перезаписывает файлы BMad в `_bmad/` и `.claude/skills/`. Ваши файлы плана
в `_bmad-output/` остаются. После установки или обновления перезапустите Claude Code:
новые скиллы BMad видны только после перезапуска.

### Этап 3 — план (`plan`)

auto-bmad реализует story, но не придумывает продукт. Ему нужны файл эпиков
и `sprint-status.yaml`. Их делаете вы вместе со скиллами планирования BMad:

| Шаг | Скилл BMad | Итог |
|---|---|---|
| Требования | `bmad-prd` (можно сначала `bmad-product-brief`) | PRD |
| Архитектура | `bmad-create-architecture` | документ архитектуры |
| Эпики и истории | `bmad-create-epics-and-stories` | файл эпиков |
| Планирование спринта | `bmad-sprint-planning` | `sprint-status.yaml` |

Не знаете, где вы сейчас, — `bmad-help` подскажет следующий шаг. Скилл настройки может
запустить следующий скилл планирования, но сам план за вас не пишет.

### Этап 4 — настройки проекта (`project`)

Скилл задаёт до четырёх вопросов за раз:

1. **Уровень по умолчанию** — `normal` (рекомендуется), `fast` или `deep`. См. [Уровни](levels.md).
2. **Параллельные истории** — `conservative` (рекомендуется), `aggressive` или `off`.
   См. [Запуск](running.md#параллельные-волны).
3. **Модуль Android-приложения** — только если модулей-приложений больше одного.
4. **Проверки на Android** — только для Android-проекта: проверять каждую story с UI
   на эмуляторе через adbm или только тестами.
5. **Веб-проверки** — только для веб-проекта: проверять каждую story с UI в headless-браузере
   через mockmatch (рекомендуется) или только тестами. Скилл показывает найденные `serve`
   и `url` и просит их поправить. Если в проекте есть файл дизайна, скилл предлагает `design`.
   Проекту с несколькими Android-модулями и веб-фронтендом этот вопрос придёт вторым вызовом.

Потом скилл пишет `.auto-bmad.toml`:

```bash
auto-bmad setup init --repo . --level normal --parallel conservative --write
```

Другие опции `init`:

| Опция | Что делает |
|---|---|
| `--width N` | размер волны в параллельном прогоне (по умолчанию 3) |
| `--test-command "<cmd>"` | команда тестов, если её не нашли |
| `--android-module <m>` | какой модуль проверять, если их несколько |
| `--no-android` | пишет `enabled = false` для проверки `adbm` |
| `--no-web` | пишет `enabled = false` для проверки `mockmatch` |
| `--force` | перезаписать готовый `.auto-bmad.toml` |

Без `--write` команда только показывает текст. Файл уже есть — с `--write` она вернёт
код 2 и `exists: true`. Тогда скилл покажет разницу и спросит вас до `--force`.

Так выглядит файл для Android-проекта:

```toml
[run]
level = "normal"
parallel = "conservative"
width = 3

[[verify]]
name = "project-tests"
command = "./gradlew test"

[[verify]]
name = "adbm"
build = "./gradlew :app:assembleDebug"
apk = "app/build/outputs/apk/debug/app-debug.apk"
package = "com.example.app"
apis = [35]
```

Закоммитьте `.auto-bmad.toml`. Он нужен в репозитории. А незакоммиченный файл делает дерево
грязным, и на грязном дереве прогон встаёт.

### Этап 5 — дополнительно

Выберите что угодно из списка или ничего:

- **Прогон без человека.** Скилл пишет `.claude/auto-bmad-headless.json` — файл прав
  для `claude -p`:

  ```bash
  auto-bmad setup headless --repo . --write
  ```

  В ответе — сам файл и готовая команда `claude -p`. См. [Прогон без человека](unattended.md).
  Этот файл тоже закоммитьте.
- **Хуки.** Скилл копирует `examples/hook-template.py` куда скажете и добавляет блок
  `[[hook]]` в конфиг. См. [Хуки](hooks.md).

### Этап 6 — финальная проверка

```bash
auto-bmad preflight --repo .
auto-bmad verify baseline --repo .
```

`preflight` перечисляет всё, что остановит прогон (см. [CLI](cli.md#preflight)).
`verify baseline` один раз гонит тесты проекта. Если они уже падают, прогон
не будет их чинить.

## Обновление плагина

Плагин ставится копией в кэш плагинов Claude Code, а не ссылкой на исходники маркетплейса.
Новая версия:

```bash
claude plugin update auto-bmad@auto-bmad
```

Потом перезапустите Claude Code. В своём конфиге ссылайтесь на файлы плагина через
`@plugin/…` (см. [Конфиг](config.md)), а не через путь в кэше: путь меняется с версией.

## Запуск из локальной копии

Попробовать локальную копию без установки:

```bash
claude --plugin-dir /path/to/auto-bmad
```

Тесты самого плагина:

```bash
python3 -m unittest discover -s tests
claude plugin validate .
```
