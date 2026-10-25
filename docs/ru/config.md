# Конфиг

[English](../en/config.md) · [К README](../../README.ru.md)

## Три слоя

auto-bmad читает три TOML-файла. Каждый следующий слой главнее предыдущего.

| Слой | Файл | Для чего |
|---|---|---|
| умолчания | `defaults.toml` в плагине | встроенные проверки и лимиты; не правьте |
| личный | `~/.config/auto-bmad/config.toml` или файл из `$AUTO_BMAD_CONFIG` | ваши хуки и предпочтения на этой машине |
| проектный | `.auto-bmad.toml` в корне репозитория | настройки проекта; его коммитят |

Правила слияния:

- Таблицы (`[run]`, `[verify_limits]`) сливаются по ключам.
- Массивы таблиц `[[verify]]` и `[[hook]]` сливаются по полю `name`. Блок с тем же `name`
  дополняет и переопределяет поля. Новый `name` добавляет новый блок.
- `enabled = false` выключает хук или проверку.
- Остальные значения (и простые массивы вроде `apis`) заменяются целиком.
- Слой, который не читается, пропускается с предупреждением. Прогон идёт дальше.

Собранный конфиг и список прочитанных файлов:

```bash
auto-bmad ext config --repo .
```

Выключить личный хук в одном проекте — в `.auto-bmad.toml` этого проекта:

```toml
[[hook]]
name = "notify"
enabled = false
```

`@plugin` в `command`, `detect` и `instructions` заменяется на каталог, куда поставлен
плагин. Пишите его вместо пути в кэше: путь меняется при каждом обновлении.

## `[run]`

Умолчания запуска. Флаги команды (`--fast`, `--deep`, `--no-parallel`, `--width N` и др.) главнее.

| Ключ | Значения | По умолчанию |
|---|---|---|
| `level` | `fast`, `normal`, `deep` | `normal` |
| `parallel` | `conservative`, `aggressive`, `off` | `conservative` |
| `width` | размер волны, целое ≥ 1 | `3` |

Неверное значение игнорируется, берётся встроенное умолчание.

## `[verify_limits]`

Сколько починок после проверок можно на одну story, по уровням.
См. [Проверки](checks.md#цикл-починки).

```toml
[verify_limits]
fast = 0
normal = 2
deep = 3
```

## `[[verify]]`

Проверка после story. Все поля и примеры — [Проверки](checks.md#поля-блока-verify).

| Поле | Коротко |
|---|---|
| `name` | имя, ключ слияния |
| `kind` | `command` или `agent` (по умолчанию `agent`) |
| `levels` | по умолчанию `["normal", "deep"]` |
| `command` | команда для `kind = "command"`; `@test_command` — найденная команда тестов |
| `detect` | команда: подходит ли проверка к диффу story |
| `requires`, `install_hint` | нужный проверке скилл и как его поставить |
| `instructions` | markdown для агента |
| `on_fail` | `fix` (по умолчанию) или `note` |
| `timeout` | секунды для `kind = "command"`, по умолчанию 1800 |
| `enabled` | `false` выключает |
| другие поля | уходят агенту как поля проекта |

## `[[hook]]`

Команда на события прогона. Подробно — [Хуки](hooks.md).

| Поле | Что это |
|---|---|
| `name` | имя, ключ слияния |
| `events` | список событий, например `["story-done", "story-blocked", "run-end"]` |
| `command` | команда оболочки, идёт через `sh -c` из корня проекта |
| `timeout` | секунды, по умолчанию 120 |
| `enabled` | `false` выключает |

## Пример: Android-проект

`.auto-bmad.toml`:

```toml
# Умолчания запуска: флаги команды главнее.
[run]
level = "normal"            # fast | normal | deep
parallel = "conservative"   # conservative | aggressive | off
width = 3                   # историй в волне

# На normal — на одну починку больше умолчания.
[verify_limits]
normal = 3

# Юнит-тесты вместо найденного "./gradlew test".
[[verify]]
name = "project-tests"
command = "./gradlew :app:testDebugUnitTest"
timeout = 2400

# Проверка фичи на эмуляторе через adbm (только для story с UI).
[[verify]]
name = "adbm"
build = "./gradlew :app:assembleDebug"
apk = "app/build/outputs/apk/debug/app-debug.apk"
package = "com.example.app"
apis = [35]
notes = "Приложение ставит FLAG_SECURE: перед кадрами выключи защиту скриншотов в его настройках."
# serial = "<serial устройства>"   # разрешить физическое устройство; без него — только эмуляторы
# bug_before_after = false         # без сборок «до и после» для багов

# Статический анализ: проблемы в отчёт, без починки.
[[verify]]
name = "lint"
kind = "command"
command = "./gradlew :app:lintDebug"
on_fail = "note"
timeout = 1200

# Хук проекта: строка после каждой story.
[[hook]]
name = "notify"
events = ["story-done", "story-blocked", "run-end"]
command = "python3 tools/auto-bmad-notify.py"
timeout = 60
```

## Пример: Python-проект

`.auto-bmad.toml`:

```toml
[run]
level = "normal"
parallel = "off"            # по одной story

# Тесты через uv вместо найденного "pytest".
[[verify]]
name = "project-tests"
command = "uv run pytest -q"
timeout = 900

# Проверка типов; проблемы чинит движок, до лимита уровня.
[[verify]]
name = "types"
kind = "command"
command = "uv run mypy src"
on_fail = "fix"
timeout = 600
```

Блок `adbm` здесь не нужен: проверка идёт только в проектах с `settings.gradle(.kts)`.

## Пример: личный конфиг

`~/.config/auto-bmad/config.toml`:

```toml
# На этой машине — deep, если проект или флаг не скажут иначе.
[run]
level = "deep"

[[hook]]
name = "desktop-notify"
events = ["story-blocked", "run-end"]
command = "python3 ~/.config/auto-bmad/hooks/notify.py"
timeout = 30
```

`.auto-bmad.toml` проекта главнее этого файла.

## Что auto-bmad создаёт в проекте

| Путь | Что | В git |
|---|---|---|
| `.auto-bmad.toml` | конфиг проекта (пишет setup) | коммитить |
| `.claude/auto-bmad-headless.json` | права для прогона без человека (пишет setup) | коммитить |
| `_bmad/custom/bmad-build-auto.user.toml` | профиль уровня, переписывается каждый прогон | закрыт локально через `.git/info/exclude` |
| `.auto-bmad/` | журнал событий, статистика, состояние проверок | закрыт локально через `.git/info/exclude` |
| `.claude/worktrees/` | worktree параллельных историй | закрыт локально через `.git/info/exclude` |
| `_bmad-output/implementation-artifacts/epic-<N>-open-questions.md` | открытые вопросы эпика | коммитит прогон |
