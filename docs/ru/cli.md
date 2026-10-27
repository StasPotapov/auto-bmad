# Справка по CLI

[English](../en/cli.md) · [К README](../../README.ru.md)

`auto-bmad <команда> [аргументы]` запускает `scripts/<скрипт>.py` плагина через `python3`
(только stdlib). Пока плагин включён, его `bin/` лежит в PATH Bash-инструмента Claude Code.
Вне Claude Code зовите `bin/auto-bmad` по полному пути.

Большую часть команд зовёт сам прогон. Вам они нужны для настройки, статистики, разбора
проблем и уборки. Каждая команда принимает `--repo <папка>` (по умолчанию текущая) и `--help`.

Общий контракт:

- JSON в stdout. Причина неудачи — в поле `error` (у `preflight` — список `blocking`)
  и ещё в stderr;
- коды выхода: `0` — сделано, `1` — ошибка вызова (нет папки, нет нужного аргумента),
  `2` — «не сделал по правилу» (очередь пуста, аргумент неоднозначен, файл писал человек,
  предполёт нашёл блокирующее);
- `ext fire` и `ext answer` всегда выходят с `0`, итог хуков — в полях ответа;
- коммиты делает скилл. Два исключения: `story-finish` коммитит трекинг, файл вопросов
  и файлы хуков, а `verify fix-spec --commit-story` коммитит спеку.

| Команда | Скрипт |
|---|---|
| `setup` | `setup.py` |
| `plan` | `plan_run.py` |
| `preflight` | `preflight.py` |
| `profile` | `write_profile.py` |
| `spec` | `read_spec.py` |
| `sync` | `sync_sprint.py` |
| `questions` | `open_questions.py` |
| `verify` | `verify.py` |
| `window` | `window.py` |
| `worktree` | `worktree.py` |
| `ext` | `ext.py` |
| `stats` | `stats.py` |
| `story-finish` | `story_finish.py` |

## setup

Состояние проекта по этапам и запись настроек. Ничего не спрашивает; без `--write` ничего
не пишет. См. [Установка](install.md#настройка-проекта).

```bash
auto-bmad setup check [--repo .]
auto-bmad setup init [--repo .] [--level normal] [--parallel conservative] [--width 3] \
    [--android-module <m>] [--no-android] [--test-command CMD] [--write] [--force]
auto-bmad setup headless [--repo .] [--write] [--force]
```

`check` — этапы `env`, `bmad`, `plan`, `project`, `extras`, `headless` и `next`.
`init` — `.auto-bmad.toml` по найденному в проекте. `headless` — файл прав для `claude -p`
и готовая команда. Код 2 — файл уже есть (без `--force`).

## plan

Разбирает аргумент прогона и собирает очередь историй из `sprint-status.yaml`. Номера
сравниваются как числа, поэтому `1-*` не ловит `11-*`. Ретроспективы пропускаются, строки
`Waits` проверяются. Заголовки файла эпиков читаются той же грамматикой, что у парсера самого BMad
(`bmad-sprint-planning/scripts/sprint_plan.py`): `## Epic <N>: <название>`
и `### Story <N>.<M>: <название>`, у `<M>` может быть буква разделённой story (`### Story 2.6a: …`). Ключевые слова английские, название — на любом языке.
Заголовок с номером вне этой грамматики (`## Эпик 2: …`) не читается и попадает в `warnings`.

```bash
auto-bmad plan --arg "epic-1 --deep" [--repo .]
auto-bmad plan --arg "1-3"
auto-bmad plan --arg ""          # story по умолчанию
```

Отдаёт `level`, `parallel`, `parallel_width`, `mode` (`epic` / `story`), `epic`, `epic_title`,
`story`, `stories` (у каждой `id`, `num`, `title` и `goal`), `count`, `warnings`, иногда `note` и `waiting`.
Ещё отдаёт `language` и `questions_file`. `language` — язык прогона из `communication_language`
BMad, если он не задан — `null`. `questions_file` — файл открытых вопросов эпика, путь от корня
репозитория: `_bmad-output/implementation-artifacts/epic-<N>-open-questions.md`.
Номера story (`story`, `num`) — строки, как в ключах sprint-status BMad: `"3"` или `"6a"` для
разделённой story (ключ `2-6a-<slug>`, заголовок `### Story 2.6a: …`). Порядок: 6, 6a, 6b, 7. Код 2 — аргумент неоднозначен или зависимость
не выполнена.

## preflight

Все проверки перед story одним вызовом.

```bash
auto-bmad preflight [--repo .] [--parallel] [--level normal]
```

Блокирует (код 2): не git-репозиторий; грязное дерево; нет
`.claude/skills/bmad-build-auto/SKILL.md`, `_bmad/scripts/render_skill.py` или
`_bmad-output/implementation-artifacts/sprint-status.yaml`; нет `_bmad/custom/`; нет `uv`
в PATH; нет агент-типа `auto-bmad:bmad-story-runner`. Ещё отдаёт `branch`, `dirty_files`,
`test_command`, `warnings`.

Проверки после story с командой `preflight` тоже её запускают. С `--level` запускаются только
проверки этого уровня, на `fast` — ни одна. Код 2 даёт блокирующую строку `check <имя>: …`,
код 1 — предупреждение. Проверка `mockmatch` пользуется этим при заданном `design_project`.
Если вход в Claude Design не выполнен и сохранённой копии (`design`) нет, прогон блокируется.
Если копия есть, preflight предупреждает, что она может быть устаревшей.
Если задан `design_artifact`, а копии нет, прогон тоже блокируется: `claude -p` не читает артефакты.

С `--parallel`: под git ли файлы движка (`engine_untracked` с правилом игнора и починкой),
`parallel_ready`, оставшиеся worktree (`stale_worktrees`), `has_origin`, `worktree_base_ref`
и `git_excluded` для `.claude/worktrees/`.

## profile

Пишет профиль уровня `_bmad/custom/bmad-build-auto.user.toml` и закрывает его от git
локально. См. [Уровни](levels.md#профиль-уровня).

```bash
auto-bmad profile --level normal [--repo .] [--force]
```

Код 2 — файл писал человек (нет метки auto-bmad); `--force` перезапишет. Код 1 — нет `_bmad/custom/`.

## spec

Находит спеку story и читает её frontmatter. Говорит прогону, начинать, продолжать
или только синхронизировать.

```bash
auto-bmad spec --story 1-3 [--repo .]
auto-bmad spec --slug issue-12 [--repo .]   # задача вне эпиков: spec-issue-12-*.md
auto-bmad spec --story 1-3 --result [--repo .]
```

`--result` ещё отдаёт `auto_run_result` (последний раздел `## Auto Run Result`), `commit`
(последний коммит после `baseline_revision`, который менял код вне `_bmad-output/`) и `files`
(сколько файлов в этом коммите). Поэтому сабагенту story не нужно читать спеку ради отчёта.
Что не нашлось — `null`.

`route`: `resume`, `sync-only` или `ask-human`. Код 2 — спек ноль или больше одной.

## sync

Правит `sprint-status.yaml`: истории в `done`, эпик следом (`backlog` → `in-progress`,
все истории готовы → `done`), `last_updated` в формате файла. Комментарии и порядок сохраняются.

```bash
auto-bmad sync --story 1-3 [--story 1-5] [--status done] [--repo .] [--dry-run]
```

Код 2 — менять нечего.

## questions

Пишет секцию story в файл открытых вопросов эпика `epic-<N>-open-questions.md`.
Пункты — в stdin.

```bash
auto-bmad questions --story 1-3 --title "Импорт CSV" \
    --spec _bmad-output/implementation-artifacts/spec-1-3-csv-import.md \
    --commit a1b2c3d [--status done|blocked] [--repo .] < items.md
auto-bmad questions ... --items-file items.md     # то же, пункты из файла
auto-bmad questions --story 1-3 --none --repo .   # вопросов нет: убрать секцию
```

Отдаёт `path` (абсолютный) и `questions_file` (от корня репозитория). Код 2 — файл писал
человек или убирать было нечего.

## verify

Проверки после story. См. [Проверки](checks.md).

```bash
auto-bmad verify plan --story 1-3 --base <sha> --commit <sha> --level normal [--title T] [--repo .]
auto-bmad verify baseline [--repo .]
auto-bmad verify run --name project-tests [--repo .]
auto-bmad verify attempt --story 1-3 --level normal [--repo .]
auto-bmad verify fix-spec --spec <путь> --pass N [--repo .] < problems.md
auto-bmad verify fix-spec --spec <путь> --pass N --problems-file F --commit-story 1-3 [--repo .]
```

`plan` — какие проверки подходят к диффу story (`verifiers`, `skipped`, `fix_limit`).
`baseline` — один раз гонит тесты проекта и запоминает итог. `run` — гонит проверку
`kind = "command"` и отдаёт `verdict`. `attempt` — засчитывает починку и говорит, можно ли
ещё (`fix_allowed`). `fix-spec` — дописывает задачи починки в спеку `done` и переводит её
в `in-progress`. `--problems-file` берёт проблемы из файла, `--commit-story` ещё и коммитит
спеку. Код 2 — проверок нет, лимит исчерпан или спека не в `done`.

## window

Говорит, влезает ли следующая story (или волна) в окно времени и в лимиты подписки.
См. [Прогон без человека](unattended.md#окно-времени-и-лимиты-подписки).

```bash
auto-bmad window [--stage next-story|next-wave] [--deadline <epoch>] [--reserve-min N] \
    [--limits-file <путь>] [--stop-at-five-hour-pct N] [--stop-at-seven-day-pct N]
```

Аргументы главнее переменных окружения. Отдаёт `take_next` и `reason`. Код 2 — следующую
не брать. Нет ни окна, ни лимитов — всегда код 0.

## worktree

Показывает и убирает worktree параллельных историй, помогает продолжить прерванную работу.

```bash
auto-bmad worktree list [--repo .]
auto-bmad worktree prune [--repo .]                    # убрать worktree, чьи ветки влиты в HEAD
auto-bmad worktree remove --path <путь> [--repo .] [--force]
auto-bmad worktree remove --path <путь> --keep-branch  # освободить ветку для продолжения
auto-bmad worktree remove 1-3 [--repo .] [--force]     # worktree, созданный через add
auto-bmad worktree add 1-3 [--repo .]                  # продолжить прерванную story
auto-bmad worktree seed --from <основное дерево> [--repo .]  # локальные настройки BMad в worktree
```

`list` показывает worktree в `.claude/worktrees/` или на ветках `auto-bmad/*`. Основное
дерево в список не попадает. `--force` сносит и незакоммиченную работу.

## ext

Слои конфига, события и хуки. См. [Конфиг](config.md) и [Хуки](hooks.md).

```bash
auto-bmad ext config [--repo .]
auto-bmad ext fire <событие> [--story 1-3] [--title T] [--epic N] [--level L] [--spec P] \
    [--commit SHA] [--status S] [--questions-file P] [--data JSON] [--repo .]
auto-bmad ext answer --hook <name> --option <id> [--repo .]
```

`config` — собранный конфиг, его источники (`sources`) и предупреждения (`warnings`).
`fire` — зовёт хуки события и пишет журнал событий. `answer` — передаёт выбор человека
одному хуку.

## stats

Статистика прогонов. См. [Статистика](stats.md).

```bash
auto-bmad stats show [--epic N] [--last N] [--json] [--repo .]
auto-bmad stats record --session <id> [--repo .]
auto-bmad stats backfill [--repo .]
```

## story-finish

Шаги завершения story или волны одним вызовом. Прогон зовёт её вместо цепочки команд.
Без человека режим auto в Claude Code проверяет длинную цепочку целиком и может её
отклонить. Тогда пропадают все её части.

```bash
auto-bmad story-finish --input <файл.json> [--session <id>] [--repo .]
```

Вход — JSON-файл:

```json
{
  "epic": 1, "level": "normal",
  "stories": [
    {"story": "1-3", "title": "Импорт CSV", "spec": "<путь>", "commit": "<sha>",
     "status": "done", "questions": "<пункты «Требует внимания» или пусто>",
     "verify": {"status": "pass", "fixes": 0, "checks": {"project-tests": "pass"}}}
  ],
  "wave": 2,
  "run_end": {"status": "done", "done": 3, "left": 0}
}
```

Все ключи необязательные. `epic` нужен, только когда `stories` пуст. Порядок шагов:

1. `verify-done` для каждой story с `verify`;
2. `sync` для story со статусом `done`;
3. `questions` для каждой story: секция из `questions` или без секции, если там пусто.
   Story `blocked` требует текст блокера;
4. один коммит `sprint-status.yaml` и файла вопросов;
5. `story-done` / `story-blocked` на каждую story, затем `wave-merged`, если задан `wave`;
6. `run-end`, если задан `run_end`;
7. `stats record`, если передан `--session`.

Файлы, которые хук вернул в `files`, команда коммитит сразу после его события, с его
сообщением. Упавший шаг не мешает остальным. Ответ: `ok`, `commit` (коммит трекинга или
`null`), `steps` (у каждого `ok` и `detail`), `messages` и `links` от хуков, `warnings`,
`failed`. Код 2 — какой-то шаг упал (см. `failed`). Ошибка хука — только предупреждение.

