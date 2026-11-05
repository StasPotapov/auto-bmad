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
| `native` | `native_session.py` |
| `engine` | `engine.py` |
| `stub` | `stub.py` |
| `test` | `testrun.py` |

## setup

Состояние проекта по этапам и запись настроек. Ничего не спрашивает; без `--write` ничего
не пишет. См. [Установка](install.md#настройка-проекта).

```bash
auto-bmad setup check [--repo .]
auto-bmad setup agent --agent codex [--model MODEL] [--effort high] [--review-model MODEL] \
    [--review-effort E] \
    [--disable-agent-checks] [--layer project|local] [--add|--select] [--compact|--advanced] [--level fast|normal|deep] [--role ROLE] [--repo .] [--write]
auto-bmad setup agent --agent claude [--layer project|local] [--add|--select] [--repo .] [--write]
auto-bmad setup init [--repo .] [--level normal] [--parallel conservative] [--width 3] \
    [--android-module <m>] [--no-android] [--test-command CMD] [--write] [--force]
auto-bmad setup headless [--repo .] [--write] [--force]
auto-bmad setup allow [--repo .]
auto-bmad setup role --role <role> [--model M] [--effort E] [--layer project|user|local] [--repo .] [--write]
auto-bmad setup local [--repo .] [--write]
```

`check` — этапы `env`, `bmad`, `plan`, `project`, `execution`, `extras`, `headless` и `next`.
В `agents` перечислены клиенты. `execution` проверяет настройки и файлы движка без моделей, тестов и хуков.
Доступность нативных инструментов проверяется отдельно в текущем чате.
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

**Настройка клиента.** `$auto-bmad-setup` в Codex и `/auto-bmad:setup` в Claude используют общий helper.
Вход скилла определяет текущий клиент. При отдельном вызове служит `--executor codex|claude`.
Setup не определяет клиент по установленным executable.

`setup agent` показывает настройки моделей текущего клиента. По умолчанию он выбирает приватный
`.auto-bmad.local.toml`. Явный `--layer project` сохраняет возможность общих настроек.
`[executors.codex]` и `[executors.claude]` сосуществуют; изменение одного сохраняет другой.
Общие тесты, хуки и правила запуска остаются в проектном конфиге. Отслеживаемый local-файл отклоняется.

`--add` сохраняет backend, `--select` явно меняет его, `--write` применяет показанный план.
Codex wrapper передаёт свой клиент и `--add`; новый `init` задаёт начальный default проекта.
Повторный setup использует сохранённые модели и effort. `--level fast|normal|deep` меняет один
уровень; `--role <id>` меняет модель/effort одного реального субагента.
ID: `story-runner`, `implementer`, `context-compiler`, `blind-hunter`, `edge-case-hunter`,
`intent-alignment`, `verification-gap`, `triager`, `verifier`. У каждого слоя ревью свои настройки.
Например: `setup agent --agent codex --role blind-hunter --model gpt-6-astra --effort high`.
Добавьте `--level deep`, чтобы изменить только этого субагента на deep. Неизвестный ID требует
явной поддержки; подстановка общего ревьюера вместо него запрещена.
Для общих настроек используйте `init`, затем `agent` для приватных настроек клиента.
`--compact` переносит совместимые расширенные маршруты Codex с резервной копией.
Неподдержанные адаптеры и неполные маршруты дают ошибку вместо замены модели.
Прежние `--executable`, `--env` и `--timeout` в нативном режиме не поддерживаются.

Умолчания и приоритеты описаны в [конфигурации](config.md#компактные-модели-codex).
Имена моделей принадлежат адаптеру клиента; aliases Claude не переводятся в Codex ID.
Ревьюерам запрещены правки инструкцией, но они наследуют разрешения главного чата.
Проверки adbm/mockmatch сохраняются; `--disable-agent-checks` допустим только по явному выбору пользователя.

Перед записью setup проверяет все слои и отклоняет конфликтующие переопределения.
Запись атомарная; посторонние значения сохраняются, изменённые файлы получают копию в `.auto-bmad/setup-backups/`.
`init --force` не переносит существующий конфиг: используйте `agent`.
Для нативного Codex `headless` сообщает, что нужен активный чат. Claude сохраняет свой headless workflow.
Setup не запускает модели.

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
auto-bmad verify attempt --kind tests --story 1-3 --base <sha> --level normal --result-file failed.json [--repo .]
auto-bmad verify observe --story 1-3 --base <sha> --result-file rerun.json [--repo .]
auto-bmad verify fix-spec --spec <путь> --pass N [--repo .] < problems.md
auto-bmad verify fix-spec --spec <путь> --pass N --problems-file F --commit-story 1-3 [--repo .]
```

`plan` возвращает проверки и `repair_limits`; `fix_limit` — совместимый псевдоним бюджета tests.
`baseline` снимает исходный результат, `run` запускает командную проверку. `attempt` считает
отдельную категорию `--kind spec|review|tests` (по умолчанию review); для tests обязателен JSON
падения и последующий `observe` результата той же команды. Три попытки без прогресса блокируют
story. Журнал Codex сохраняет собственные результаты check/repair; Claude использует эти helpers. `fix-spec` остаётся ручным
инструментом изменения спеки, но обычная починка тестов его не вызывает. Код 2 — нет проверок,
исчерпан бюджет, нет прогресса или нарушено условие операции.

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

<a id="cli-backend-codex-и-последовательные-эпики"></a>

## Нативные субагенты Codex

Главный чат распределяет короткие задания, слоты и зависимости, передаёт решения пользователю.
Подготовку, планирование, диагностику, разбор замечаний, повторную проверку исправлений,
тесты с ожиданием, слияние и итоговый отчёт выполняют свежие изолированные субагенты.
Главный чат не читает исходники, диффы, полные отчёты, журналы и логи. Модели и effort ролей
сохраняются. Python-команды готовят план, сохраняют состояние и проверяют результаты.
Они не запускают модели и не управляют очередью stories.
Прежние точки запуска `run`, `agent` и `agent-smoke` удалены. Запасного запуска через CLI нет.

```bash
auto-bmad --executor codex native task-prepare --repo /path/to/project --arg "epic-1 --normal" --checkpoint bootstrap --host-limit 4 --root-thread-id <actual-root-UUID> --root-turn-id <actual-turn-UUID>
auto-bmad --executor codex native task-prepare --session /private/session.json --story 1-1 --role triager --checkpoint revalidation --input /private/handoff.json
auto-bmad --executor codex native task-start --task /private/task.json --agent-id actual-host-id
auto-bmad --executor codex native task-result --task /private/task.json --agent-id actual-host-id --confirm-completed
auto-bmad --executor codex native task-stop --task /private/task.json --agent-id actual-host-id --status failed --reason "observed host failure" --confirm-terminal
auto-bmad --executor codex native plan --repo /path/to/project --arg "epic-1 --normal"
auto-bmad --executor codex native init --repo /path/to/project --arg "epic-1 --normal"
auto-bmad --executor codex engine prepare --repo /path/to/worktree --output /private/new-manifest --level normal
auto-bmad --executor codex native record --session /private/session.json --request /private/event.json
auto-bmad --executor codex native record-batch --session /private/session.json --request /private/batch.json
auto-bmad --executor codex native summary --session /private/session.json --story 1-1
auto-bmad --executor codex native status --session /private/session.json
auto-bmad --executor codex native check --session /private/session.json --story 1-1
auto-bmad --executor codex native resume --session /private/session.json
```

Bootstrap требует `--host-limit` с фактическим общим лимитом текущего хоста: 4 в примере
подходит только хосту с четырьмя слотами. Передайте оба доступных фактических UUID через
`--root-thread-id` и `--root-turn-id`. Если хост их не предоставляет, укажите причину через
`--accounting-unavailable-reason`. Помощник сохраняет `host_metadata`; выдумывать UUID и
молча пропускать отсутствие учёта нельзя. Флаги `--fast`/`--normal`/`--deep` и настроенный
уровень по умолчанию в `--arg` сохраняют прежний смысл.

`task-prepare --checkpoint bootstrap --planning-only` поручает только планирование, без
инициализации сессии и изменений worktree; его `created_session` остаётся null.
`task-prepare` сохраняет входные данные и возвращает короткий `spawn` с настроенными моделью,
effort и `fork_turns: "none"`. После запуска `task-start` привязывает фактический ID агента;
до начала работы исполнитель один раз вызывает `task-binding --task TASK --wait-seconds 60`.
Команда локально ждёт сохранённую привязку без дополнительного сообщения главного чата.
При таймауте или отмене исполнитель останавливается и сообщает причину. Агент сам читает
полные данные и заполняет точный `receipt_template` с текущим отпечатком кода и хешами артефактов.
`task-result --confirm-completed` допустим только после фактического завершения агента;
команда проверяет происхождение результата, а не готовность story. Ответ помощника ограничен
4096 байтами UTF-8, квитанция — 16384 байтами, четырьмя короткими действиями и восемью ссылками.
Полные отчёты остаются на диске. Некорректный результат разбирает свежий специалист; главный
чат не читает код. Команды планирования, тестов и завершения ниже выполняют специалисты.
Если хост подтвердил failed/stopped без пригодной квитанции, `task-stop --status failed|stopped
--reason <фактическая-причина> --confirm-terminal` сохраняет терминальное состояние и историю.
Сначала дождитесь фактического завершения агента; команда сама его не останавливает и не
объявляет успех. Технический повтор сохраняет работу и лимиты; явная отмена не возобновляется
автоматически. Если хост фактически завершил агента, но квитанция отсутствует или некорректна,
используйте `task-stop --status failed --host-status completed --reason <ошибка-квитанции>
--confirm-terminal` с его настоящими ID задачи и агента. Журнал сохраняет completed агента
и failed задачи, не создаёт фиктивную квитанцию и не принимает доказательства. Host completed
допустим только с task failed, не stopped. Новый разрешённый агент запускается после явного
подтверждения терминального состояния нативным инструментом. См. [правила главного чата](../../skills/auto-bmad/ORCHESTRATOR.md).

Используйте пути session и manifest из ответа команд. Пути в примерах условные.
`native init --plan <файл>` принимает полный результат `native plan` и проверяет его актуальность.
Журнал хранится в общей служебной области Git, вне исходников проекта. Он содержит worktree,
идентификаторы агентов, этапы, счётчики исправлений, отчёты и результаты проверок.
Для `complete` нужны готовая спецификация, чистый закоммиченный worktree, актуальные ревью и командные проверки.
`complete` отмечает ветку проверенной, но ждёт финализации. Конечный finalizer проверяет
фактические артефакты finish и актуальные результаты, сохраняет запрос record-batch для
`complete` и/или `finalize`, затем возвращает `ready`. Пока сам агент работает, он не
применяет собственные события завершения. Главный чат видит фактическое завершение,
вызывает `task-result` и механически передаёт путь запроса из короткой квитанции в
`record-batch --request`; содержательное решение он не принимает. До запроса `finalize`
должны завершиться слияние, finish и проверки через `check` на итоговом дереве. Проверяются
tracking, история коммита, актуальность результатов, чистота worktree и отсутствие активных
агентов. Отказ проверки разбирает свежий специалист. Обширные/рискованные изменения объединённого кода требуют нового ревью; точечные — явного подтверждения применимости исходного ревью свежим triager.

`native record` принимает JSON-события `schedule`, `bind`, `phase`, `agent`, `review`, `review-revalidate`, `review-not-applicable`, `repair`, `retry`, `complete` и `finalize`.
Новые нативные планы требуют `schedule` до привязки stories; для одной story и последовательного
режима каждая волна содержит одну story. Новые сессии получают `orchestration_policy:
"thin-root-v1"`. Старые журналы сохраняют правила, схему агентов и закреплённый runtime.
Автоматического переноса нет. В `review-revalidate` поле `evaluated_by` содержит ID
завершённого зарегистрированного triager; JSON связывает его со story, слоем, исходным и
текущим отпечатками и полным решением по замечаниям. Для `review-not-applicable` нужен ID
завершённого story-runner/triager и JSON с точным условием, false, текущим отпечатком и
обоснованием. Проверка готовности заново проверяет происхождение и хеши. Оценка `main-chat`
сохраняется только для старых сессий.
`native record-batch` принимает `{"batch_id":"уникальный-постоянный-id","events":[...]}` и записывает
весь пакет атомарно с теми же проверками. Повтор идентичного пакета возвращает исходную краткую
квитанцию без повторного списания попыток; другой набор событий с тем же ID отклоняется.
Смещения событий в квитанции не являются версией результатов проверок. `record` сохраняет полный ответ.
`native summary` показывает краткое состояние без истории и вывода тестов; `--story` добавляет
актуальный отпечаток кода выбранной story. Сохранённый вердикт и совпадение отпечатка не заменяют
проверку доказательств. Полные замечания и диагностика остаются в журнале, отчётах и логах.
Главный чат Codex использует максимально долгий разрешённый прерываемый вызов ожидания
(сейчас API допускает 3600000 мс), без минутного опроса. Совет ограничивать блокирующие
shell-ожидания 60 секундами не ограничивает этот API. Явные жёсткие лимиты хоста обязательны;
о них нужно сообщить, а вызванные ими пробуждения помощник отключить не может. Тестов ждут
отдельные конечные verifier, соблюдая реальные ограничения инструментов без скрытых циклов.
Точные поля и передача работы агентам описаны в [NATIVE.md](../../skills/auto-bmad/NATIVE.md).
`native check` выполняет настроенные командные проверки и возвращает необходимые агентные проверки.
Для устройства и браузера агенты используют установленные скиллы adbm/mockmatch.

`native status` не знает, жив ли агент приложения. Перед продолжением главный чат проверяет сохранённые
идентификаторы через нативные инструменты. `native cancel` только записывает отмену: оркестратор должен
остановить агентов и дождаться их завершения. `native resume --confirm-cancelled` требует явного поручения
пользователя продолжить отменённый запуск. Resume не сбрасывает бюджеты и не запускает модели.

Для разрешённой автоматизации `native host-bind --session <session> --request <json>` сохраняет
фактические `thread_id` и `automation_id` в `host-continuation.json` рядом с журналом.
Сначала создайте автоматизацию штатным инструментом хоста: Python её не создаёт.
Повторная привязка не меняет владельца и не сбрасывает остановку. `native host-recover`
принимает те же ID, предыдущий `turn_id`, нормализованный `turn_status` и подтверждённый `cause`.
Результат — `continue`, `wait`, `already-claimed` или `stop`. Прерывание и вопросы к человеку
отключают восстановление. Сохранённый `technical_limit` ограничивает восстановления главного
хода между завершёнными stories отдельно от повторов story. Новое явное поручение человека
позволяет повторить `host-bind` с `resume_authorization_turn`, сохранив бюджет. Получение состояния
хоста и реальное отключение/включение автоматизации выполняет адаптер. См.
[правила продолжения Codex](../../integrations/codex/skills/auto-bmad/CONTINUATION.md).

Субагенты наследуют разрешения главного чата. Запрет правок в инструкции ревьюера не создаёт отдельную
read-only песочницу. Модели и effort задаёт `agent-config`; нативные инструменты должны поддерживать их.
`doctor` проверяет конфиг и файлы движка, но не выполняет живой вызов модели или субагента.
Расход токенов неизвестен, если хост не предоставляет его. Старые CLI receipts не подтверждают новый режим.

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


### Thin-root receipt preflight and compact acceptance

`native task-binding --task TASK --wait-seconds 60` waits locally once for the real
start binding; timeout/cancellation means stop, not a model polling loop.
`native task-receipt --task TASK --request DECISION` builds `result.json`; DECISION has
`state`, `next`, `actions`, `blocker`, `artifact_paths`, optional `created_session`.
`native task-preflight --task TASK --agent-id ID [--receipt FILE]` checks an existing receipt
without saving a terminal state. Both accept `--record-batch FILE` to preflight a hashed
same-story batch against current gates with only this producer's completion simulated.

After observing actual host completion, root can combine registration and journal application:
`native task-result --task TASK --agent-id ID --confirm-completed --record-batch FILE`.
The batch must be a hashed receipt artifact; it cannot bind stories or change agent liveness.
Gate rejection reports `receipt_accepted=true`, `batch_applied=false`, `state=blocked`;
no batch event is saved, and a fresh specialist handles diagnosis. Terminal registration
is retained. Never infer successful completion from command exit code alone.

`verify plan --working-tree ...` includes committed, staged, unstaged and untracked files
for detection. Native thin-root journal checks select this automatically; older journals
keep their original behavior. No model configuration or review/check requirement changes.


## Verification frequency for new native sessions

New sessions save `verification_policy="integration-full-v1"`; existing journals keep their
original gates. During implementation and repairs run registered focused tests plus
compile/build checks. Do not run the full suite or a full baseline by habit, after each
review, or once per story when stories will land together. `native check --session SESSION
--story ID --request PLAN.json` persists development evidence and validates fixed registered
commands. PLAN contains `checks` (objects with development check `name` and `targets`) and
`builds` (all registered build names). Names resolve from `project_tests.development` and
`project_tests.build`; no command is generated from source filenames. Missing focused
coverage is a blocker. If no build exists, save an explicit `build_not_applicable` reason;
registered builds cannot be skipped. A concrete `full_risk` explanation permits an early full
project check only when broad/architectural risk makes it necessary. It is not a routine
preparation step. Full baseline execution is not part of this policy.

`complete` needs current focused/build evidence and all mandatory independent/agent reviews;
it marks a story ready for integration, not ready to move main. The full gate runs on the
combined candidate **before main changes**, preferably once for all stories in that landing:
`auto-bmad land BRANCH --native-session SESSION --story ID [--story ID ...]`. This extends the
existing guarded merge-candidate worktree pipeline; it never changes the selected landing
mode. It checks every selected mandatory command, the full registered `project-tests`, and
registered builds. `--no-tests` is forbidden for this policy. Preserve story worktrees until
journal finalization. Never substitute a raw Git merge for this guard in an automatic run.
A different main HEAD after checks requires a new candidate.

Exact candidate code, config, command/timeout set and saved log hashes allow a successful
integration gate to be shared across included stories and reused at finalization. A changed
merge resolution, command, config or evidence invalidates reuse; a child branch pass alone
does not certify the combined candidate. Saved evidence lives in journal metadata even when
the temporary candidate worktree is removed. For an existing candidate, the finite verifier
can run/join `native integration-check --session SESSION --repo CANDIDATE --story ID ...`.
A running result is not a pass. After a failed full gate, repair the complete failure set,
then run focused regressions/build on the repaired candidate with `native check --repo
CANDIDATE --request PLAN.json ...`, then rerun the final full gate. A failed full gate cannot
immediately trigger another full execution without this current focused evidence.

Wave/dependency barriers and the configured landing mode are unchanged. One full gate per
whole epic applies when that epic has one combined landing; separate authorized landings
need their own exact-candidate proof. Do not silently combine landings or weaken reviews,
mandatory checks, clean-tree, ancestry or finalization requirements to reduce run counts.


```toml
[project_tests.development.unit]
command = "python3 -m pytest"
targets = ["tests/test_*.py"]
[project_tests.build.compile]
command = "python3 -m compileall -q app"
```

```json
{"checks":[{"name":"unit","targets":["tests/test_feature.py"]}],"builds":["compile"]}
```

These are configuration examples, not inferred commands for an unknown project.
