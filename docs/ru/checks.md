# Проверки после story

[English](../en/checks.md) · [К README](../../README.ru.md)

Новые нативные сессии (`integration-full-v1`) выполняют адресные тесты и компиляцию/сборку
в ходе story. Полный набор запускается на объединённом кандидате до изменения main,
обычно один раз на фактическое слияние. Finalize использует действующие доказательства
того же кандидата. После упавшего полного набора сначала нужны адресные регрессии и сборка
после исправления. Досрочный полный запуск требует конкретной причины широкого риска.
Отсутствие адресных команд — пробел в настройке. Уровень fast не отменяет эти этапы.

Старые журналы сохраняют прежний порядок: проверки после каждой story на normal/deep,
включая полный набор и настроенные проверки устройства/браузера; fast может их пропускать.
Обязательное независимое ревью и настроенные агентные проверки сохраняются.

## Исполнитель

Оба нативных клиента используют общие проверки и вердикты. Главный чат передаёт
агентные проверки нативному проверяющему, а команды тестов запускает через служебные
утилиты. Codex использует `execution.backend="native"`, Claude — свой нативный адаптер.
Mock Match eyes сохраняет собственные клиентские настройки модели и инструкции роли.
Перед работой с устройствами или браузером прочитайте установленный скилл adbm/mockmatch.
Проверяющий освобождает запущенные им ресурсы и сообщает оркестратору, что осталось.
Отсутствующие необязательные зависимости означают явный пропуск, а не успешную проверку.
Удалённые CLI browser RPC и запуск моделей отдельными процессами не служат запасным путём.
Правила доказательств и исправлений — в [общем процессе](../../skills/auto-bmad/NATIVE.md).

## Встроенные проверки

Все три описаны в `defaults.toml` плагина. Настраиваются в вашем `.auto-bmad.toml` по `name`.

### `project-tests`

Гонит все тесты проекта.

```toml
[[verify]]
name = "project-tests"
kind = "command"
command = "@test_command"
levels = ["normal", "deep"]
on_fail = "fix"
timeout = 1800
```

`@test_command` — команда, которую auto-bmad сам нашёл в проекте. Он смотрит эти файлы
в таком порядке:

| Файл | Команда |
|---|---|
| `package.json` со скриптом `test` | `npm test` |
| `Makefile` с целью `test:` | `make test` |
| `pyproject.toml` или `pytest.ini` | `pytest` |
| `gradlew` | `./gradlew test` |
| `Cargo.toml` | `cargo test` |

Своя команда — в `.auto-bmad.toml`:

```toml
[[verify]]
name = "project-tests"
command = "./gradlew :app:testDebugUnitTest"
```

**Старые журналы: baseline.** Прежняя политика допускает тесты до первой story
(`auto-bmad verify baseline`). Новая integration-full-v1 не запускает полный baseline
в setup или по умолчанию в разработке.
Если они уже падают, падение после story считается `skipped` («тесты падали и до прогона»)
и не чинится: тесты, красные до старта, auto-bmad не трогает. Команды тестов нет —
проверка пропускается.

**Повторы.** Тесты гоняются через [`auto-bmad test`](cli.md#test). Если код story не менялся
с прогона движка, проверка `project-tests` берёт его результат и не гоняет набор заново.

### `adbm`

Проверяет фичу на настоящем приложении на Android-эмуляторе через плагин
[adbm](https://github.com/StasPotapov/adbm). Идёт только когда:

- в проекте есть `settings.gradle` или `settings.gradle.kts`;
- дифф story трогает UI Android: ресурсы `res/`, `AndroidManifest.xml` или файлы Kotlin/Java
  с `@Composable`, Activity, Fragment или View.

adbm не стоит — проверка пропускается, а в отчёте по story сказано, как его поставить.

Поля проекта (в `.auto-bmad.toml`):

| Поле | Что это |
|---|---|
| `build` | команда сборки, например `./gradlew :app:assembleDebug` |
| `apk` | путь к собранному APK |
| `package` | application id, например `com.example.app` |
| `apis` | уровни API Android для проверки, например `[35]`. Одного хватает, если story не про разницу версий |
| `notes` | особенности проекта, которые проверка должна учесть первым делом, словами (например: «перед кадрами выключи FLAG_SECURE в настройках приложения») |
| `serial` | физическое устройство, разрешённое проекту. Без него — только эмуляторы |
| `bug_before_after` | `false` выключает режим «до и после» для багов (по умолчанию `true`) |

`build`, `apk` или `package` пустые — проверка найдёт их в `build.gradle*` сама и скажет,
что взяла.

Режимы:

| Режим | Когда | Что делает |
|---|---|---|
| фича (по умолчанию) | всегда | собирает APK, ставит на эмулятор (поднимает, если нужно), проходит сценарий «Как проверить» из отчёта story по тексту экрана (`tap`, `type`, `assert`), смотрит лог на падения. Путь длиннее 3–4 шагов сохраняет в Maestro-flow `.adbm/flows/story-<id>.yaml` и прогоняет его после починки |
| внешний вид | story меняет вёрстку, тему, отступы, insets или системные панели | добавляет кадры изменённых экранов, доску сравнения и вердикт сабагента adbm, который смотрит картинки |
| до и после | только исправление бага с шагами воспроизведения, и `bug_before_after` не `false` | собирает приложение на коммите до story, воспроизводит баг, потом проходит тот же сценарий на исправленной сборке |

**Только эмулятор.** На физический телефон проверка ничего не ставит, пока в проекте нет
`serial`. Эмулятор, который проверка подняла сама, после story она не гасит: он нужен
следующей story. Гасит его прогон, один раз в конце (см. `CLEANUP` ниже).

**Сохранённый flow.** Maestro-flow, оставленный в дереве, прогон коммитит отдельным
коммитом. Так следующий предполёт видит чистое дерево.

### `mockmatch`

Используйте установленный скилл Mock Match и его нативную визуальную роль. Её модель
и effort берутся из клиентских настроек Mock Match отдельно от auto-bmad. Выделите роли
слот субагента и соблюдайте её ограничения изображений и формат результата. Если
независимый вердикт недоступен, явно запишите пропуск; verifier не заменяет его собой.


Проверяет фичу на запущенном сайте в headless-браузере через плагин
[mockmatch](https://github.com/StasPotapov/mockmatch). Если у проекта есть дизайн,
проверка ещё сверяет с ним изменённые страницы. Идёт только когда дифф story трогает веб-UI:
вёрстку и стили (`.html`, `.css`, `.scss`, `.vue`, `.svelte`, `.astro`, `.jsx`, `.tsx`…).
Если над файлом есть `package.json` (в его папке или выше, подойдёт и `frontend/`), ещё считаются
JS/TS в папках UI (`components`, `pages`, `app`, `routes`, `views`, `layouts`, `ui`, `lib`),
конфиг Tailwind или PostCSS, файлы в `public/` и `static/`. Тесты и снимок `design/` не считаются.

mockmatch не стоит — проверка пропускается, а в отчёте по story сказано, как его поставить.
Это рекомендация. Проверка читает страницу текстом и сверяет её с дизайном числами, поэтому
она детерминированная и тратит намного меньше токенов, чем скриншоты.

Поля проекта (в `.auto-bmad.toml`):

| Поле | Что это |
|---|---|
| `serve` | команда, которая поднимает dev-сервер, например `npm run dev`. `{port}` в ней заменяется на выбранный порт |
| `url` | где отвечает сайт, например `http://localhost:5173` |
| `design_project` | проект Claude Design: его id или ссылка `claude.ai/design/p/<id>?file=…`. Проверяющий берёт свежую копию дизайна на каждую проверку |
| `design_file` | файл внутри этого проекта, например `Home.dc.html`. Не нужен, если в ссылке есть `file=` или в проекте один файл |
| `design_artifact` | артефакт claude.ai типа «Design» (`https://claude.ai/artifact/…`). Нужен вместе с `design`: прогон без человека не читает артефакты, поэтому сверяет с сохранённой копией |
| `design` | файл дизайна в репозитории: файл Claude Design, сохранённый через `mockmatch pull`, экран артефакта, сохранённый через `mockmatch import`, HTML-макет или PNG. При `design_project` это запасной вариант без входа. Без полей дизайна режима «дизайн» нет |
| `frame` | селектор `--frame` нужного варианта дизайна (список даёт `mockmatch frames <файл>`) |
| `widths` | ширины для сверки с дизайном, например `[1440, 390]` |
| `theme` | `light`, `dark` или обе |
| `notes` | особенности проекта простыми словами (например, тестовый логин) |

`serve` или `url` пустые — проверяющий берёт их из `package.json` и пишет, что взял.

Режимы:

| Режим | Когда | Что делает |
|---|---|---|
| фича (по умолчанию) | всегда | открывает сайт (поднимает `serve`, если `url` не отвечает), проходит сценарий «Как проверить» по тексту страницы (`click --expect`, `type`, `assert`), затем смотрит консоль и запросы самого сайта на ошибки |
| дизайн | story меняет вид страницы, и у проекта есть дизайн | гонит `mockmatch compare` против дизайна: каждая строка `!` (нет элемента, шрифт, размер, цвет, отступ) — проблема; пиксельные участки судит сабагент `mockmatch-eyes`; доска — артефакт |

**Claude Design.** Дизайн приходит через MCP `claude_design`, а у него свой вход.
`/auto-bmad:setup` показывает состояние входа и предлагает выбрать проект и файл из списка.
Перед каждым прогоном `preflight --level` проверяет вход (`claude mcp get claude_design`, около 2 с).
Если входа нет, а в `design` есть сохранённая копия, preflight предупреждает, и проверка сверяет с копией.
Если копии нет, прогон останавливается и пишет, что сделать. Проверяющий кладёт копию в `.auto-bmad/design/`.
Эта папка вне git, поэтому дерево остаётся чистым. Войти: `/mcp` → `claude_design` → Authenticate.

**Артефакт Design.** Артефакт claude.ai типа «Design» не лежит в Claude Design. Инструмент
`Artifact`, который его читает, есть только в обычной сессии, в `claude -p` его нет. Поэтому
проверка сверяет с копией в репозитории. Копию делает агент в сессии: он скачивает экраны
(`project/<Экран>.dc.html`) и сохраняет их командой `mockmatch import`. Затем закоммить `design/`
и задай `design`. Если `design_artifact` задан, а копии нет, preflight блокирует прогон. В прогоне
с человеком проверяющий сначала обновляет копию в `.auto-bmad/design/`.

**Dev-сервер и порт.** Ответ на порту ничего не доказывает: на общей машине там может
работать другой сервис. Поэтому `extensions/mockmatch/serve.py` повторно берёт только сервер,
который сам поднял для прошлой story. Иначе он ищет первый свободный порт, начиная с порта
из `url`, и поднимает там `serve`. Порт доходит до сервера так: `PORT` в окружении, `--port N`
после `<pm> run <script>` (для npm — `-- --port N`), номер у `python3 -m http.server` или `{port}`
в `serve`. После story сервер не гасится: он нужен следующей story. Гасит его прогон, один раз
в конце (см. `CLEANUP` ниже).

## Цикл починки

Командная проверка упала → собрать весь известный список сбоев → списать одну попытку
`tests` → исправить все известные сбои → повторить упавшие и связанные тесты. Повторять до стабилизации, лимита или остановки
без прогресса. Спеку не переписывать, полное ревью не запускать на каждой попытке.
Повторное независимое ревью нужно только после обширных или рискованных изменений.
После точечных исправлений главный чат проверяет закрытие каждого пункта и сохраняет
обоснование применимости исходного ревью. Первое независимое ревью обязательно.
Итоговые настроенные проверки выполняются после стабилизации всего пакета исправлений.

Бюджеты [`repair_limits`](config.md#repair_limits): `spec=2`, `review=5`, `tests=10`,
`no_progress=3`. Они независимы и не сбрасываются повторным проходом внутри story.
Находки agent-проверок используют `review`; реальные ошибки плана — `spec`.

Новый нативный Codex сохраняет адресные тесты/сборку через `native check --request PLAN.json`,
а полный gate — через guarded landing до изменения main. Старые журналы сохраняют прежний
`native check`. Попытка исправления записывается через
`native record` (событие `repair`, вид `tests`). Адаптер Claude использует
`verify attempt --kind tests --result-file` и `verify observe --result-file`. Три попытки
без успешной проверки или строгого уменьшения набора падающих тестов блокируют story
и сохраняют работу. `verify fix-spec` — ручной инструмент, а не обычный путь починки тестов.


### Лимит исчерпан

Нерешённая проблема проверки с `on_fail="fix"` блокирует story независимо от типа
проверки. Нельзя объявлять её готовой, отключать тесты или ослаблять ожидания.
Ошибки окружения требуют восстановления доступа, а не изменения продуктового кода.
Ранее существовавшие красные baseline и явно настроенный `on_fail="note"` сохраняют
свои прежние правила и отражаются в отчёте.

### `on_fail`

| Значение | Что делает |
|---|---|
| `fix` (по умолчанию) | движок чинит проблему, до лимита |
| `note` | без починки; проблема уходит в «требует внимания» |

## CLEANUP

Проверка может оставить команду уборки (например, погасить эмулятор, который подняла).
Прогон запоминает каждую команду один раз и выполняет их в конце прогона, перед событием
`run-end`. Уборка упала — это строка в отчёте, прогон она не останавливает.

## Фоновые серверы проверки

Проверке часто нужен сервер, который работает, пока она проверяет: заглушка API, бэкенд.
Verifier запускает и останавливает такие серверы только через [`auto-bmad stub`](cli.md#stub),
никогда через `kill $(cat …)` или `pkill`: в прогоне без человека хук прав их отклоняет,
и сервер живёт дольше прогона.

```bash
auto-bmad stub start api --run 1-3 --port 8000 -- python3 stub.py
auto-bmad stub stop api
```

`stub start` запускает команду в своей группе процессов и пишет её в
`.auto-bmad/stubs/<имя>.json` вместе с владельцем: рабочим деревом и прогоном (`--run`,
id story). `stub stop` останавливает только то, что записал: сигнал идёт процессу, только
пока совпадают pid, время старта и группа процессов. Поэтому процесс, который позже получил
тот же pid, команда не трогает. После каждой story и ещё раз в конце прогона (`run-end`)
`story-finish` зовёт `stub stop --all --runs-only`: заглушки прогона в этом дереве гаснут,
даже если verifier их забыл, а сервер, который вы подняли руками без `--run`, остаётся. Dev-сервер проверки
`mockmatch` остаётся на своём механизме (`serve.py` и `CLEANUP`): он служит всем story прогона.

## Своя проверка

Добавьте блок `[[verify]]` в `.auto-bmad.toml` (или в личный конфиг). Всегда задавайте
`kind`: проверка без `kind` считается `agent`.

### `kind = "command"`

Команда оболочки. Код 0 — `pass`, любой другой — `problem`. Последние 60 строк вывода
уходят в починку.

```toml
[[verify]]
name = "lint"
kind = "command"
command = "npm run lint"
levels = ["normal", "deep"]
on_fail = "fix"
timeout = 600
```

Команда идёт через `sh -c` из корня проекта. `timeout` — в секундах (по умолчанию 1800).
Не уложилась — `problem`.

### `kind = "agent"`

Сабагент (`auto-bmad:bmad-verifier`, Sonnet, medium) работает по вашей markdown-инструкции.

```toml
[[verify]]
name = "api-smoke"
kind = "agent"
instructions = "docs/checks/api-smoke.md"
detect = "python3 scripts/touches_api.py"
on_fail = "fix"
base_url = "http://localhost:8080"          # своё поле, уходит сабагенту как есть
```

Сабагент получает: id, заголовок и цель story, `Base` (коммит до story) и `Commit`
(коммит story), имя проверки, путь к вашей инструкции, все свои поля блока в JSON
(«поля проекта»), секцию «Как проверить» из отчёта story, номер захода, а со второго
захода — проблемы прошлого. Он работает в корне проекта, код не правит и не коммитит.
На файл внутри плагина ссылайтесь через `@plugin/…`. Образец от плагина —
`extensions/adbm/verify.md`.


### Поля блока `[[verify]]`

| Поле | Что это |
|---|---|
| `name` | имя; по нему сливаются слои и считаются починки |
| `kind` | `command` или `agent` (по умолчанию `agent`) |
| `levels` | уровни, на которых идёт проверка (по умолчанию `["normal", "deep"]`) |
| `command` | для `kind = "command"`; `@test_command` — найденная команда тестов |
| `detect` | команда: подходит ли проверка к story. В stdin — JSON `{"files": [...], "story": "...", "title": "..."}` (файлы диффа story). Код 0 — подходит, иначе пропуск. Идёт из корня проекта, лимит 60 с |
| `requires` | скилл, без которого проверку не запустить. Нет его — пропуск с советом `install_hint` |
| `preflight` | команда, которую preflight запускает перед прогоном. Поля проверки она получает JSON в stdin. Код 1 — предупреждение, 2 — блок, первая строка stdout — сообщение |
| `install_hint` | как поставить то, чего нет |
| `instructions` | markdown-инструкция для `kind = "agent"` |
| `on_fail` | `fix` или `note` |
| `timeout` | секунды, для `kind = "command"` (по умолчанию 1800) |
| `enabled` | `false` выключает проверку |
| любое другое | уходит сабагенту как «поля проекта» |

Командные проверки идут по одной внутри worktree. Нативные проверки в разных worktree
могут выполняться одновременно и не удерживают общую блокировку журнала. Проверки,
использующие общие устройства, браузер, порты или другие ресурсы машины, идут последовательно.

## Контракт вердикта

Проверка-агент кончает ответ такой шапкой:

```
VERDICT: pass | problem | skipped
MODE: <по желанию, своя метка>
ARTIFACT: <путь к отчёту или доске, или "none">
FILES_LEFT: <файлы, оставленные в дереве, или "none">
CLEANUP: <команда на конец прогона, или "none">
SKIPPED_REASON: <только при skipped>
PROBLEMS:
1. <что не так — где — чем видно>
```

Минимум — `VERDICT`, `SKIPPED_REASON` при `skipped` и `PROBLEMS` при `problem`. Каждая
проблема — одна строка, которую движок может взять задачей на починку: что должно быть
и что есть. После шапки — до 5 строк для человека, на языке из поля `Language:`
промпта. Сама шапка остаётся английской.

Как прогон читает шапку:

- шапки нет — вердикт считается `skipped` («проверка вернулась не по контракту»);
- `ARTIFACT` — ссылка в отчёте по story;
- `FILES_LEFT` — прогон коммитит эти файлы отдельным коммитом;
- `CLEANUP` — выполняется один раз в конце прогона.

После проверок хукам идёт событие `verify-done`, одно на story: общий статус
и `{"fixes": N, "checks": {"<name>": "<вердикт>"}}`.


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

## Локальные проверки исправлений

В новых сессиях `bounded-checkpoints-v1` разработчик запускает `native local-check`
внутри согласованной пачки. Это наблюдения, а не независимая приёмка. Для команд
`project_tests.development` и `project_tests.build` можно явно задать
`independent = true`: после обычного падения выполнятся остальные независимые
проверки. Зависимые команды получат not-run с причиной. Отказ окружения, отмена
или изменение кода останавливают проход; пропущенное не считается успехом.

Необязательное поле `environment: {path, sha256}` в плане проверок ссылается на
сохранённое описание идентичности тестовой среды. Без него успешный результат
не переиспользуется между вызовами native check. Изменение файла запрещает
переиспользование; вызывающая роль обновляет описание при смене сервисов, БД,
зависимостей или фикстур. Проверяющий независимо оценивает полноту покрытия.
Локальный результат никогда не становится независимой приёмкой автоматически.

[Команды и схемы](../../skills/auto-bmad/CHECKPOINTS.md): решения triager, стабильные
ID пачек, лимиты, прямой возврат известных падений и независимое закрытие.

Независимая проверка новой сессии требует `--task TASK`. До завершения производителя
её результат остаётся staged; `pending_evidence` включают в квитанцию. Land получает
`--native-task TASK` и не меняет main до приёмки завершённой задачи. Следующая
задача интеграции использует принятый результат без повторного полного прогона.
