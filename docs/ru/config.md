# Конфиг

[English](../en/config.md) · [К README](../../README.ru.md)

Конфиг необязателен: без него прогон работает на встроенных умолчаниях. Конфиг задаёт:

| Раздел | Что задаёт |
|---|---|
| [`[run]`](#run) | уровень по умолчанию, параллельные волны и ширину волны, разбор находок ревью в сабагенте |
| [`[roles.*]`](#roles) | модель и effort каждой роли: реализатора, ревьюеров, проверяющего… |
| [`[verify_limits]`](#verify_limits) | сколько починок после проверок можно на одну story, по уровням |
| [`[[verify]]`](#verify) | проверки после story: тесты проекта, эмулятор Android, браузер, свои команды |
| [`[[hook]]`](#hook) | ваши скрипты на события прогона: сообщение в чат, карточка на доске |

Файл проекта `.auto-bmad.toml` пишет `/auto-bmad:setup` по тому, что нашёл в проекте.
Можно написать его и руками: возьмите за образец один из [примеров](#пример-android-проект) ниже.
После правки проверьте результат командой `auto-bmad ext config --repo .`, а модель и effort
ролей — командой `auto-bmad roles --repo .`.

## Три слоя

auto-bmad читает три TOML-файла. Каждый следующий слой главнее предыдущего.

| Слой | Файл | Для чего |
|---|---|---|
| умолчания | `defaults.toml` в плагине | встроенные проверки и лимиты; не правьте |
| личный | `~/.config/auto-bmad/config.toml` или файл из `$AUTO_BMAD_CONFIG` | ваши хуки и предпочтения на этой машине |
| проектный | `.auto-bmad.toml` в корне репозитория | настройки проекта; его коммитят |

Правила слияния:

- Таблицы (`[run]`, `[roles.*]`, `[verify_limits]`) сливаются по ключам.
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
| `worktree` | `true`, `false` — прогон идёт в своём worktree на ветке `bmad/<цель>`, слить потом через `auto-bmad land` ([Запуск](running.md#прогон-в-своём-worktree)); `--worktree` / `--no-worktree` главнее | `false` |
| `triage_subagent` | `true`, `false` — разбор находок ревью в сабагенте `bmad-triager` (факт I, [Под капотом](engine.md#факты)) | `false` |

Неверное значение игнорируется, берётся встроенное умолчание.

## `[roles.*]`

Модель и effort для роли. Пустой конфиг — у каждой роли модель и effort её агент-типа,
как в [таблице моделей](levels.md#модели).

```toml
[roles.implementer]
model = "sonnet"
effort = "high"

[roles.reviewer-mid]
effort = "high"

[roles.story-runner]
model = "opus[1m]"   # Opus с контекстом 1M; просто "opus" — обычный контекст
effort = "high"
```

| Ключ | Значения |
|---|---|
| `model` | `sonnet`, `opus`, `opus[1m]`, `haiku`, `fable`, `default` |
| `effort` | `low`, `medium`, `high`, `xhigh`, `max`, `default` |
| `provider` | только `anthropic`; другой провайдер пока не поддерживается |

Роли: `story-runner`, `implementer`, `reviewer`, `reviewer-mid`, `reviewer-lite`,
`compiler-lite`, `triager`, `verifier`. Оркестратор — главная сессия: его модель выбираете вы, в конфиг
он не входит.

Как это работает. Значение доходит до сабагента параметрами `model` и `effort` вызова `Agent`.
Они главнее модели и effort агент-типа. Для story-runner и verifier параметры передаёт скилл,
для остальных ролей — движок по профилю уровня (факты E, G и I). Файл агента в `.claude/agents/`
для этого не подходит: Claude Code читает агент-типы один раз, при старте сессии.

Ограничения:

- **Opus с контекстом 1M — пишите `model = "opus[1m]"`.** Просто `opus` даёт обычный
  контекст, preflight об этом предупреждает. `opus[1m]` доступен только ролям, у которых
  он стоит в агент-типе: story-runner и implementer. Вызов `Agent` не умеет передать `[1m]`,
  поэтому `opus[1m]` оставляет модель агент-типа, а у другой роли это ошибка preflight.
- Остальные значения `model` — псевдонимы из списка.
- `default` (или само значение по умолчанию, например `opus[1m]`) снимает переопределение
  нижнего слоя. Так проект возвращает роли модель агент-типа, если личный конфиг её сменил.
- Неверное значение, неизвестный `provider` — preflight останавливает прогон.
  Неизвестная роль или ключ — предупреждение, ключ не применяется.
- Какая модель реально работала в роли, видно в `auto-bmad stats show`, в строке
  «Output by role».

Проверить, что получилось после слияния слоёв: `auto-bmad roles --repo .`.

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
| `preflight` | команда, которую preflight запускает перед прогоном; поля проверки получает JSON в stdin; код 1 — предупреждение, 2 — блок |
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

# Веб: проверка в браузере через mockmatch (только для story с веб-UI) и сверка с дизайном.
[[verify]]
name = "mockmatch"
serve = "npm run dev"
url = "http://localhost:5173"
design_project = "https://claude.ai/design/p/<id>?file=Home.dc.html"   # свежая копия на каждую проверку
# design_artifact = "https://claude.ai/artifact/<id>"   # артефакт claude.ai типа «Design»; нужен design
design = "design/home.html"   # запасной вариант без входа в Claude Design; подойдёт и HTML-макет или PNG
widths = [1440, 390]

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
Блок `mockmatch` тоже не нужен: проверка идёт только для story, которые трогают веб-UI.

## Пример: личный конфиг

`~/.config/auto-bmad/config.toml`:

```toml
# На этой машине — deep, если проект или флаг не скажут иначе.
[run]
level = "deep"

# Ревью на deep — с максимальным effort; проект вернёт умолчание через effort = "default".
[roles.reviewer]
effort = "max"

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
| `.claude/worktrees/` | worktree параллельных историй и прогонов в своём worktree (`bmad-<цель>`) | закрыт локально через `.git/info/exclude` |
| `_bmad-output/implementation-artifacts/epic-<N>-open-questions.md` | открытые вопросы эпика | коммитит прогон |
