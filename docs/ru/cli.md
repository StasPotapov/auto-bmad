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
  предполёт нашёл блокирующее), `3` — тесты ещё идут в фоне (`test`, `verify baseline`,
  `verify run`): повторите тот же вызов;
- `ext fire` и `ext answer` всегда выходят с `0`, итог хуков — в полях ответа;
- коммиты делает скилл. Два исключения: `story-finish` коммитит трекинг, файл вопросов
  и файлы хуков, а `verify fix-spec --commit-story` коммитит спеку.

| Команда | Скрипт |
|---|---|
| `setup` | `setup.py` |
| `plan` | `plan_run.py` |
| `preflight` | `preflight.py` |
| `profile` | `write_profile.py` |
| `roles` | `roles.py` |
| `spec` | `read_spec.py` |
| `sync` | `sync_sprint.py` |
| `questions` | `open_questions.py` |
| `verify` | `verify.py` |
| `window` | `window.py` |
| `worktree` | `worktree.py` |
| `ext` | `ext.py` |
| `stats` | `stats.py` |
| `story-finish` | `story_finish.py` |
| `evidence` | `evidence.py` |
| `land` | `land.py` |
| `agent-config` | `agent_config.py` |
| `doctor` | `doctor.py` |
| `run` | `run_queue.py` (`--manifest`: `run_story.py`) |
| `engine` | `engine.py` |
| `agent-smoke` | `agent_smoke.py` |
| `stub` | `stub.py` |
| `test` | `testrun.py` |

## setup

Состояние проекта по этапам и запись настроек. Ничего не спрашивает; без `--write` ничего
не пишет. См. [Установка](install.md#настройка-проекта).

```bash
auto-bmad setup check [--repo .]
auto-bmad setup agent --agent codex [--model MODEL] [--effort high] [--review-model MODEL] \
    [--review-effort E] [--executable PATH] [--env JAVA_HOME] [--timeout 3600] \
    [--disable-agent-checks] [--layer project|local] [--add|--select] [--repo .] [--write]
auto-bmad setup agent --agent claude [--layer project|local] [--add|--select] [--repo .] [--write]
auto-bmad setup init [--repo .] [--level normal] [--parallel conservative] [--width 3] \
    [--android-module <m>] [--no-android] [--test-command CMD] [--write] [--force]
auto-bmad setup headless [--repo .] [--write] [--force]
auto-bmad setup allow [--repo .]
auto-bmad setup role --role <role> [--model M] [--effort E] [--layer project|user|local] [--repo .] [--write]
auto-bmad setup local [--repo .] [--write]
```

`check` — этапы `env`, `bmad`, `plan`, `project`, `execution`, `extras`, `headless` и `next`.
В `agents` перечислены исполнители. Для CLI блок `execution` проверяет профили и контракт движка,
без inference, тестов и hooks. Совместимость интерфейса ещё не доказывает успешный вызов модели.
`init` — `.auto-bmad.toml` по найденному в проекте. `headless` — файл прав для `claude -p`
и готовая команда. Код 2 — файл уже есть (без `--force`). `allow` — правила `allow`, которые
нужны прогону в режиме auto для этого проекта; те, которых ещё нет в настройках Claude Code
(`missing`); те, что режим auto не учитывает; конфликты с `deny` и `ask`; текст для
`autoMode.allow`. Команда ничего не пишет.
См. [Прогон без человека](unattended.md#режим-auto-правила-allow). `role` — таблица
[`[roles.<role>]`](config.md#roles) в `.auto-bmad.toml` или, с `--layer user`, в личном
конфиге. `--layer local` записывает настройки компьютера в игнорируемый `.auto-bmad.local.toml`,
с точной резервной копией прежнего содержимого и отказом перезаписывать отслеживаемый local-файл.
Без `--model` и `--effort` команда удаляет таблицу этого слоя. Значение `default`
снимает переопределение нижнего слоя. Без `--write` команда только показывает текст.
`local` — закрыт ли [`.auto-bmad.local.toml`](config.md#четыре-слоя) от git (`exists`,
`tracked`, `ignored`, `in_gitignore`, `fix`). Закрыт — значит, есть правило в `.gitignore`
проекта: правило только в `.git/info/exclude` или в глобальном файле игнора действует лишь на
этой машине. `--write` дописывает строку в `.gitignore`, если её там нет. `check` показывает то же
в `project.local`.
Код 1 — неверное значение или роль записана в форме, которую команда не правит (таблица
`[roles]`, inline-таблица): задайте её руками.

**Настройка исполнителя.** В Codex выбор собирает `$auto-bmad-setup`, в Claude Code — `/auto-bmad:setup`.
`agent` показывает безопасное изменение существующих настроек или создаёт настройки агента, если
выбранного слоя ещё нет. `init --agent codex --model MODEL` создаёт полный
новый конфиг с обычными флагами init. Прежний Claude — `--agent claude`; без `--agent` команда init
ведёт себя как раньше. Kimi и Claude CLI отмечены как недоступные.

Один `.auto-bmad.toml` хранит общие настройки проекта: модели Claude в `[roles.*]`, CLI-профили
в `[agents.*]` и `[routing.*]`, общие тесты/hooks/run. Этот файл коммитят с проектом.
Дополнения и личные настройки компьютера записывают в игнорируемый `.auto-bmad.local.toml`
через `--layer local`. Последний слой перекрывает проектные значения; копия всего конфига не нужна.
Setup не считает уже отслеживаемый local-файл приватным и отказывается его переписывать.

Скилл выбирает исполнителя по текущему чату на каждый запуск: Codex — Codex, Claude Code — native Claude.
Для запуска он не переписывает сохранённый default. `agent --agent codex --add --model MODEL --write`
добавляет настройки Codex, сохраняя `[execution].backend`. Без параметров профиля повторно используются
сохранённые модели/effort/таймауты/окружение (`profiles_reused=true`). Codex setup helper сам добавляет
`--agent codex --add` для команды `agent`; новый `init` задаёт начальный default.
`--layer local --add` записывает дополнения только для компьютера.

Вне известного скилла `auto-bmad --executor codex ...` (или `claude`) выбирает исполнителя одного запуска;
`AUTO_BMAD_EXECUTOR` передаёт выбор вложенным процессам. Без контекста используется сохранённый backend.
`setup agent --agent codex --select --write` явно меняет этот default; общая команда `agent` без `--add`
сохраняет прежнее поведение выбора. Для создания или изменения CLI-профилей нужен `--model`;
без параметров профиля сохраняются прежние значения.

Codex получает отдельные write/read-only review профили и маршруты для всех трёх уровней;
старые значения ролей сохраняются. `--review-model`/`--review-effort` по умолчанию берутся из write-профиля.
Агентные проверки (mockmatch, adbm и свои verifiers) сохраняются и выполняются через роль `verifier`.
`--disable-agent-checks` — необязательный явный отказ от них; настройки остаются в TOML с `enabled=false`.
Смена исполнителя не включает ранее отключённые проверки автоматически. Командные проверки, hooks
и настройки запуска сохраняются. Модели — точные CLI ID, а не Claude aliases.

Перед `--write` проверяются все слои конфига. Переопределение из local даёт ошибку, а не незаметную
смену модели; `agent --layer local` меняет выбор только на этой машине. Личный конфиг не переписывается.
Запись атомарная, под source lease; посторонние значения TOML сохраняются. Для изменённого существующего
файла создаётся закрытая точная копия в `.auto-bmad/setup-backups/`; повтор того же выбора копию не создаёт.
`init --agent` не трогает существующий файл даже с `--force`: для миграции служит `agent`.
`setup role` остаётся только для native Claude. Для CLI команда `headless` выдаёт общий запуск
и не пишет Claude permission settings. Setup сам не запускает работу.
Явный выбор native Claude отключает унаследованные CLI-маршруты, не меняя нижние слои;
native model/effort действуют, о неактивных CLI-маршрутах выводится предупреждение.
CLI-настройки без явного backend по-прежнему блокируются.

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
auto-bmad plan --arg "epic-1 --worktree"
```

Отдаёт `level`, `parallel`, `parallel_width`, `mode` (`epic` / `story`), `epic`, `epic_title`,
`story`, `stories` (у каждой `id`, `num`, `title` и `goal`), `count`, `warnings`, иногда `note` и `waiting`.
`worktree` — идёт ли прогон в своём worktree (`--worktree`, `--no-worktree`, `[run] worktree`).
При `true` ещё `worktree_name` (`epic-1`, `1-3`), `worktree_branch` (`bmad/epic-1`) и
`worktree_arg` — аргумент второго вызова `plan` уже внутри worktree.
Ещё отдаёт `language` и `questions_file`. `language` — язык прогона из `communication_language`
BMad, если он не задан — `null`. `questions_file` — файл открытых вопросов эпика, путь от корня
репозитория: `_bmad-output/implementation-artifacts/epic-<N>-open-questions.md`.
Номера story (`story`, `num`) — строки, как в ключах sprint-status BMad: `"3"` или `"6a"` для
разделённой story (ключ `2-6a-<slug>`, заголовок `### Story 2.6a: …`). Порядок: 6, 6a, 6b, 7. Код 2 — аргумент неоднозначен или зависимость
не выполнена.

Истории в `review` (код написан и ждёт ревью) стоят в начале `stories`. «Waits» сначала
проверяется по порядку номеров. История в `review` ничего не ждёт: она остаётся в очереди, даже
если очередь обрезана перед ней. История в `review` без спеки или с другой работой после неё (`later_commits` у `spec`)
в очередь не попадает: она в `skipped` (`id`, `title`, `reason`) и в `note`. Выбор по
умолчанию её тоже пропускает и пишет в `skipped` и `note`, если прошёл мимо неё. Если
назвать её одну (`--arg "5-1"`) — код 2.

## preflight

Все проверки перед story одним вызовом.

```bash
auto-bmad preflight [--repo .] [--parallel] [--level normal]
```

Блокирует (код 2): не git-репозиторий; грязное дерево; нет
`.claude/skills/bmad-build-auto/SKILL.md`, `_bmad/scripts/render_skill.py` или
`_bmad-output/implementation-artifacts/sprint-status.yaml`; нет `_bmad/custom/`; нет `uv`
в PATH; нет агент-типа `auto-bmad:bmad-story-runner`; неверное значение в
[`[roles.*]`](config.md#roles) (`model` или `effort` не из списка, `provider` не `anthropic`).
Ещё отдаёт `branch`, `dirty_files`,
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
локально. См. [Под капотом](engine.md).

```bash
auto-bmad profile --level normal [--repo .] [--force]
```

Код 2 — файл писал человек (нет метки auto-bmad); `--force` перезапишет. Код 1 — нет
`_bmad/custom/` или в конфиге `[roles]` есть ошибки.

`agent_args` в ответе — переопределения `model` / `effort` из [`[roles.*]`](config.md#roles)
по ролям. Для сабагентов движка профиль уже их содержит. Для `story-runner` и `verifier`
их передаёт сам скилл. `triage_subagent` — включил ли `[run] triage_subagent` факт I
([Под капотом](engine.md#факты)). `test_command` — тестовая команда для факта J; `null` —
команды нет, и факта J в профиле нет.

## roles

Модель и effort каждой роли после слияния слоёв конфига: умолчание агент-типа,
переопределение и то, что возьмёт прогон.

```bash
auto-bmad roles [--repo .]
```

`roles.<role>.args` — параметры для вызова `Agent`, `{}` без переопределения. Код 2 — в конфиге
есть ошибки (`errors`), preflight останавливает прогон на тех же ошибках.

## spec

Находит спеку story и читает её frontmatter. Говорит прогону, начинать, продолжать
или только синхронизировать.

```bash
auto-bmad spec --story 1-3 [--repo .]
auto-bmad spec --slug issue-12 [--repo .]   # задача вне эпиков: spec-issue-12-*.md
auto-bmad spec --story 1-3 --result [--repo .]
```

`--result` ещё отдаёт `auto_run_result` (последний раздел `## Auto Run Result`), `commit`
(коммит движка для story: последний после `baseline_revision`, где менялись и спека, и код вне
`_bmad-output/`, поэтому коммит более поздней story не берётся; спека ни разу не коммитилась с
кодом — последний коммит, который менял код) и `files`
(сколько файлов в этом коммите). Поэтому сабагенту story не нужно читать спеку ради отчёта.
Что не нашлось — `null`.

`route`: `resume`, `review`, `skip`, `sync-only` или `ask-human`. Код 2 — спек ноль или больше одной.
С `--story` в ответе ещё `sprint_status` — статус story в `sprint-status.yaml`. Спека `done`
у story в `review` там даёт `review`: движок заново делает ревью закоммиченного кода. Тогда в ответе ещё `commit` — коммит
движка для этой story (последний после базы, где менялись и спека, и код; merge-коммиты не считаются), и `later_commits` —
сколько коммитов кода другой работы после него (`null` — неизвестно: спеку коммитили отдельно от
кода). `later_commits` больше 0 даёт маршрут `skip` с `reason`: движок отревьюил бы и эту работу.
При `null` маршрут остаётся `review`. Story в
`review` без спеки — код 2 и `route: ask-human`. `baseline` — базовая ревизия спеки
(`baseline_revision`, у старых версий движка `baseline_commit`): база story для проверок
после прогона `review`.

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

`baseline` и `run` гоняют команду через [`test`](#test): замок папки и сохранённый результат.
Код 3 (`verdict: running`) — тесты ещё идут в фоне, повторите тот же вызов.

## test

Гоняет тесты проекта под замком папки и хранит результат для того же кода. Через эту
команду тесты гоняют все роли прогона: движок (факт J), implementer, `verify` и волны.

```bash
auto-bmad test [--repo .]                                  # проверка project-tests из конфига
auto-bmad test --command 'scripts/check.sh backend' [--repo .]   # часть набора
auto-bmad test --rerun [--repo .]                          # заново, хотя код не менялся
auto-bmad test --wait 60 [--repo .]                        # ждать 60 с, а не 540
auto-bmad test --name <проверка> --timeout 3600 [--repo .] # другая проверка kind=command, свой лимит
```

- **Замок.** В одной папке идёт один прогон. Второй ждёт первого, потому что тестовые базы,
  порты и сборка у папки общие. Соседние папки (worktree) друг друга не ждут. Если у папок
  проекта общие тестовые ресурсы, проект разводит их сам: в sample-project `check.sh` даёт каждой
  папке свои контейнеры и порты.
- **Сохранённый результат.** Ключ — содержимое рабочей копии вместе с неотслеживаемыми
  файлами и сама команда. Правки в `_bmad-output/` и `.auto-bmad/` ключ не меняют, коммит тоже.
  Тот же ключ — команда сразу отдаёт сохранённый итог с `reused: true`, зелёный или красный.
  Таймаут не сохраняется. Изменение дерева во время тестов даёт `tree_changed: true`;
  такой результат не сохраняется в кэш, новое дерево нужно проверить заново. Отчёты добавьте
  в ignore или пишите в `.auto-bmad/`. `--rerun` нужен, когда причина падения была вне кода: например,
  не был запущен Docker. Результат моложе 120 с он всё равно берёт: это ответ на его же
  прогон. После `running` повторяйте вызов без `--rerun`. `verify baseline` гоняет заново
  красный результат старше 15 минут: падение, сохранённое в другой день, не должно скрыть
  поломку story.
- **Долгий прогон.** Команда идёт в отдельном процессе и переживает вызов Bash. Через
  `--wait` секунд (по умолчанию 540) ответ — `verdict: running`, код 3. Тот же вызов ещё раз
  ждёт этот же прогон, а не запускает новый. Так же и когда сам прогон поменял дерево
  (отчёты, снапшоты). Лимит времени — `--timeout`, иначе `timeout` проверки (по умолчанию
  1800 с), и с `--command` тоже.

Ответ: `verdict` (`pass`, `problem`, `running`), `code`, `seconds`, `reused`, `tail` —
конец вывода при падении, `log` — полный вывод. Состояние лежит в `.auto-bmad/tests/` папки.
Там же `history.jsonl`: по строке на вызов, с временем прогона и `reused`.

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
auto-bmad worktree start epic-1 [--repo .]             # worktree всего прогона: создать или продолжить
```

`start` — worktree [прогона в своём worktree](running.md#прогон-в-своём-worktree): ветка
`bmad/<имя>` в `.claude/worktrees/bmad-<имя>` основного дерева, от его HEAD. Живой worktree
ветки команда продолжает (`resumed: true`), ветке без папки создаёт папку заново. Отдаёт
`path`, `branch`, `created`, `resumed`, `base_branch`, `seeded` (скопированные локальные
файлы; копируются только игнорируемые git), `left_in_main` (неигнорируемые локальные файлы,
оставлены в основном дереве — слои конфига читатели берут оттуда), `main_dirty` (незакоммиченные файлы основного дерева, в прогон они не попали) и
`land` (команда слияния). Worktree лежит внутри каталога проекта и закрыт от git в
`.git/info/exclude`. `list` и `prune` worktree прогонов не показывают.

`list` показывает worktree в `.claude/worktrees/` или на ветках `auto-bmad/*`. У каждого —
три последних коммита (`log`) и незакоммиченные файлы (`dirty`). `dirty: null` с `error` —
состояние неизвестно, `missing: true` — папки нет. Основное дерево в список не попадает. `--force` сносит и незакоммиченную работу.

## land

Сливает ветку [прогона в своём worktree](running.md#auto-bmad-land) в ветку основного
дерева. Работает из основного дерева и изнутри worktree.

```bash
auto-bmad land bmad/epic-1 [--repo .] [--no-tests] [--onto-current] [--cleanup]
```

Отдаёт `merged`, `base`, `merge_commit`, `conflicts`, `sprint_merged` (ключи, которые
изменило сведение `sprint-status.yaml`), `tests` (`verdict`, `command`, `tail`),
`removed_worktree`, `removed_branch`, `warnings`. При отказе `dirty` — незакоммиченные файлы
основного дерева. Код 2 — незакоммиченные правки, основное дерево на другой ветке, чем база
прогона (`recorded_base`; `--onto-current` всё равно сливает), ветка без своих коммитов
(`--cleanup` всё равно её убирает), конфликт в коде (файлы — в `conflicts` и в stderr),
тесты упали; тогда ничего не слито. Код 1 — нет такой ветки, основное дерево не на ветке,
git старше 2.38.

Тесты работают в новом временном worktree. Существующий каталог `auto-bmad-land` команда не удаляет.
Если тесты изменили tracked, untracked или ignored файлы, слияние останавливается.
Путь сохранённого дерева приходит в `tests.worktree`. Каталог `.auto-bmad/tests/` принадлежит
тестовому runner и не считается результатом проекта. Заблокированные Git metadata или неизвестное
состояние тоже останавливают слияние. Cleanup сохраняет run worktree с неизвестными файлами
и сообщает `warning_cleanup`.

## CLI backend: Codex и последовательные эпики

CLI runtime требует POSIX macOS/Linux (`fcntl`, process groups и fork); Windows не проверен.
Общий CLI ведёт очередь, а нативный `bmad-build-auto` — lifecycle каждой story. Профили ролей
задают адаптер, executable, модель, effort и permissions. Codex прошёл живой single-story smoke;
Kimi/Claude CLI adapters пока отказывают до проверки их контрактов. Старый Claude plugin остаётся отдельным режимом.
Схема конфига и пример профилей — [CONFIG_EXTENSION.md](../multi-agent/CONFIG_EXTENSION.md).

```bash
auto-bmad agent-config --repo . --level normal
auto-bmad doctor --repo . --level normal
auto-bmad run plan --repo . --arg "epic-1"
auto-bmad run --repo . --arg "1-3" --allow-model
auto-bmad run --repo . --arg "epic-1 --normal" --allow-model --timeout 7200
```

Новый `run` требует эффективный `execution.backend="cli"` и чистое исходное дерево.
Скилл Codex или `auto-bmad --executor codex run ...` выбирает CLI без изменения сохранённого default. Он создаёт уникальный linked worktree
из точного текущего HEAD, ветку `codex/auto-bmad/...`, переносит разрешённые локальные BMAD/CLI настройки,
фиксирует конфиг и готовит engine snapshot. Epic проходит последовательно, с новым controller на каждую story.
Готовые stories пропускаются, Waits и зависимости соблюдаются; при ошибке следующая story не запускается.
Источник остаётся на своей ветке. Результат содержит `run_completed`, `stories`, `done`, `left`, `remaining`,
`worktree`, `branch`, `session`, результаты hooks и `merge_policy="manual"`. Частичный или остановленный эпик — не success.
Слияние и push требуют отдельной команды человека. Runtime никогда не удаляет оставленный worktree.

Перед каждой story проверяется окно `window.py`, включая clean-stop и live-файл. Оно останавливает очередь
между stories. `--timeout` — отдельный жёсткий предел всего запуска, который может остановить текущую story.
`--parallel-fast`, `--width` и `--no-worktree` явно отклоняются; waves и автоматическое crash recovery пока не подключены.
`run-start`, `story-start` и `run-end` вызывают настроенные hooks; finishing story сохраняет прежние события.
Файлы hooks коммитятся в run worktree, вопрос hook возвращается человеку. Для unattended сохраняется политика ext.py.
Host hooks/checks наследуют окружение оператора, а модельные роли сохраняют явные environment allowlists.
Бюджеты обёрток учитывают настроенные timeout hooks и общий deadline. Изменённый конфиг не может
добавить новый hook посреди запуска. Если финальные hooks меняют проверенное дерево кода, результат — needs_attention.

```bash
auto-bmad run status --session /путь/из/ответа/session.json
auto-bmad run cancel --session /путь/из/ответа/session.json
```

Сессии и результаты хранятся в `<git-common-dir>/auto-bmad-sessions/<id>/`; run journal отделён от writable worktree.
Broker передаёт writer lease implementer/compiler/triager и принимает параллельный read-only batch review layers.
Каждый reviewer получает авторитетный diff от точного review base, включая новые и binary файлы, и свой контекст.
Для всех ролей `task_id` равен ID story; уникальные attempt IDs выдаёт broker.
Контроллер читает нативный workflow, сохраняет его activation/on_complete, triage, fix и followup политики.
Коммиты и rollback проходят через broker; backup patch сохраняется до rollback, intent gap блокирует запуск.
Проверки checkpoint и внешние command checks выполняются host под folder lock; их cache по дереву и команде
хранится в защищённом состоянии. Writable cache `.auto-bmad/tests/` не разрешает завершение story.
Тесты внутри ролей используют `auto-bmad test --session <session.json>`. Не отделяйте команды через setsid/daemonize.
Timeout, cancel и смерть host останавливают управляемые группы; cleanup sentinel удерживает inherited execution
lease до остановки session test workers и stubs этого run/tree. Если очистка неизвестна, `needs_attention`
сохраняет занятый lease. Worktree, журналы и изменения не стираются.
Проверки `kind="agent"` выполняются последовательно через профиль `verifier` после коммита движка.
Каждый новый verifier получает исходные инструкции, поля, сценарий story, точный base и прошлые проблемы.
`problem` запускает исправление с ревью; `on_fail="note"` и пропуски видны в questions. Первый план
сохраняется при исправлениях: повторяются проблемные проверки и тесты проекта. Отчёты и пути артефактов
остаются в `verification.details`; статистика содержит вызовы с `role="verifier"` и `check_name`.
Скиллы ищутся в каталогах Codex проекта и пользователя, а также пакетах плагинов, отдельно от Claude.
Артефакты verifier пишет в `.auto-bmad/`; изменение кода, index или HEAD останавливает запуск.
Встроенный mockmatch использует отдельный browser tool RPC: модель остаётся в песочнице, host принимает
только операции mockmatch и настроенные `serve`/`url`, без произвольных shell-команд и установки пакетов.
Недостающие поля сервера определяет host; CLI берётся из пользовательской/plugin установки вне проекта.
Состояние браузера и доски лежат в защищённом каталоге сессии `browser/`; модель не может подменить PID очистки.
Host не исполняет произвольные shell-команды CLEANUP: свои проверки и adbm очищают ресурсы до ответа.
Встроенная очистка mockmatch закрывает браузер и сервер также при отмене и смерти host.
Песочница Codex, сетевые права, доверие хукам и зависимости браузера/устройства продолжают действовать.
Условные review layers пока недоступны.

### Подготовленный snapshot и одиночный handoff

```bash
auto-bmad engine inspect --repo /путь/к/проекту
auto-bmad engine prepare --repo /путь/к/linked-worktree --output /новый/каталог --level normal
auto-bmad run --manifest /каталог/manifest.json --arg "1-3" --allow-model --timeout 3600
auto-bmad agent execute --manifest /каталог/manifest.json --request /путь/request.json --allow-model
```

`doctor` проверяет version/help без модели. `engine inspect` проверяет контракт и хэши; `prepare` создаёт
принадлежащий auto-bmad профиль и выполняет renderer offline через `uv`, без lifecycle hooks и модели.
Чужой профиль или symlink не перезаписывается. `--output` — новый каталог с существующим родителем.
Snapshot, config, profile и engine hashes перепроверяются при handoff и commit.
`execution_ready` связан с сохранённым [live receipt](../multi-agent/CODEX_STORY_SMOKE.json) и fingerprint движка;
это не проверка доступа текущей модели: `inference_checked=false`. Другой fingerprint не получает готовность по чужому smoke.
При ошибке renderer логи и профиль сохраняются.

Standalone запрос содержит `role`, `task_id`, `base_commit` (полный текущий HEAD) и `prompt` (исходный handoff).
Требуется linked worktree; основное дерево запрещено. Инструкции роли берутся из `agents/` без Claude frontmatter.
Reviewer требует read-only; malformed result, запись reviewer, смена ветки или rewrite base означают ошибку.
Read-only fingerprint включает submodules. Успешный leaf handoff сам по себе никогда не означает `story_completed`.
Внутри controller session доступны также `execute-batch`, `checkpoint`, `commit` и `rollback`.
Без session или явного `--allow-model` новая модель не запускается.

### Отдельный smoke транспорта

```bash
auto-bmad agent-smoke --model <точный-model-id> --allow-model --timeout 60
```

Один read-only Codex CLI в новом временном Git-репозитории, с сохранением private logs. Это не BMAD story
и не merge. Живые model calls всегда явные и могут расходовать лимит модели.

## stub

Фоновые серверы проверки: заглушка API, бэкенд. См.
[Проверки](checks.md#фоновые-серверы-проверки).

```bash
auto-bmad stub start <имя> [--port N] [--wait 30] [--run ID] [--repo .] -- <команда> [аргументы…]
auto-bmad stub stop <имя> [--repo .]
auto-bmad stub stop --all [--runs-only] [--repo .]
auto-bmad stub list [--repo .]
```

`start` запускает команду без shell (синтаксис shell — через `-- sh -c '…'`) в репозитории,
в своей группе процессов, пишет лог в `.auto-bmad/stubs/<имя>.log`, а `pid`, `pgid`, команду,
порт и время старта — в `.auto-bmad/stubs/<имя>.json` основного дерева (и из worktree тоже).
С `--port` отказывает, если порт занят, и до `--wait` секунд ждёт, что порт ответит. То же имя
с той же живой командой — `started: false`, с другой командой — код 2. Команда завершилась
или порт не ответил — код 2 с `log_tail`; то, что от команды ещё живо, тогда убивается
(`killed_group`). Команда, которая завершилась и оставила живую группу (ушла в фон),
записывается по группе (`leader_gone`). В записи есть и владелец: `tree` — рабочее дерево,
откуда заглушку запустили, `run` — `--run` или `$AUTO_BMAD_RUN` (пусто — запущена руками).
`ps` читается с `LC_ALL=C`, какая бы ни была локаль.

`stop` сверяет, что у записанного процесса те же pid, время старта и группа процессов. Строка
команды идёт только в отчёт. Процесс, который позже получил тот же pid, команда не трогает
(`note`). Если лидер группы уже завершился, группа останавливается, только пока все её
процессы стартовали после заглушки. TERM группе, KILL через 5 секунд, потом — только для
заглушки, которую она остановила, — до 10 секунд ждёт, что порт свободен (`port_free`).
Если `ps` не дал ответа, запись остаётся. `stop --all` останавливает заглушки своего рабочего
дерева (чужие — в `kept`), `--runs-only` — только заглушки прогона; так её зовёт `story-finish`.
Код 1 — плохое имя; код 2 — наша заглушка не остановилась, порт остался занят, состояние
неизвестно или запись битая (`error`). `list` — записанные заглушки с `alive`, `tree` и `run`.

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
auto-bmad stats show [--epic N] [--last N] [--calls] [--json] [--repo .]
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

0. `stop stubs` — `stub stop --all --runs-only`: фоновые серверы, которые оставила проверка; шаг виден,
   только если он что-то остановил или упал;
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

## evidence

Выдержки кода для всех находок ревью одного прохода одним вызовом. Сессия движка (или
сабагент triager) зовёт её при разборе находок вместо `grep` или `git diff` на каждую
находку: так требует факт H профиля уровня.

```bash
auto-bmad evidence --input .auto-bmad/evidence/<спека>.json [--base <rev>] [--context 3] [--repo .]
```

Вход — JSON-файл, его пишет инструмент Write:

```json
{
  "base": "<baseline_revision>",
  "findings": [
    {"id": "1", "file": "src/a.py", "lines": "40-52"},
    {"id": "2", "file": "src/b.py", "lines": "12", "diff": true},
    {"id": "3", "file": "src/c.py", "grep": "parse_date\\(", "grep_in": "."}
  ]
}
```

Поля находки: `lines` — `"12"`, `"40-52"`, `"12,40-52"` или список; `diff: true` — куски
`git diff <base> -- <файл>`, которые задевают эти строки; `grep` — регулярное выражение для
`git grep -E` в `grep_in` (путь, `.` — весь репозиторий; по умолчанию файл находки). В ответе
на каждую находку: `code` (строки с номерами и `--context` строк вокруг), `diff`, `grep`
(`hits`, `count`) и `error` для части, которая не вышла. Выдержка режется на 120 строках,
совпадения grep — на 20. Ошибка одной находки не роняет вызов. Код 1 — нет входа или JSON
битый. Команда закрывает `.auto-bmad/` от git, поэтому файл входа не пачкает дерево.
