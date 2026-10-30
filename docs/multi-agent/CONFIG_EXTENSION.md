# Расширение конфигурации

## Цель

Сохранить TOML и существующее наследование. Новые настройки включают новый runtime явно.
Отсутствие новых настроек оставляет прежний Claude plugin workflow.
Схема реализована в `agent-config`; общий CLI делегирует роли через broker и запускает story или последовательный epic. Codex прошёл живой single-story smoke. Kimi/Claude CLI execution пока выключены до проверки их контрактов.
Пример ниже описывает целевую конфигурацию; он требует реальных моделей и проверенных возможностей адаптеров.

## Предлагаемая схема v1

```toml
[execution]
schema_version = 1
backend = "cli"             # legacy-plugin | cli
merge_policy = "manual"     # для cli в MVP только manual

[agents.codex-dev]
adapter = "codex"
executable = "codex"
arguments = []               # только adapter-approved flags
model = "CONFIGURE_CODEX_MODEL_ID"
effort = "high"              # только после проверки CLI + модели
permissions = "workspace-write"
timeout = 3600
environment_allowlist = ["PATH", "HOME", "TMPDIR", "CODEX_HOME"]
output_protocol = "codex-jsonl-v1"
capability_requirements = ["noninteractive", "structured_events", "engine_delegation_bridge"]

[agents.codex-review]
adapter = "codex"
executable = "codex"
model = "CONFIGURE_CODEX_MODEL_ID"
permissions = "read-only"
timeout = 1800
environment_allowlist = ["PATH", "HOME", "TMPDIR", "CODEX_HOME"]
output_protocol = "codex-jsonl-v1"
capability_requirements = ["noninteractive", "read_only_enforcement"]

[agents.kimi-dev]
adapter = "kimi"
executable = "kimi"
arguments = []
model = "CONFIGURE_LOCAL_K3_1_PRO_ALIAS"
# effort отсутствует: поддержку установленной версией ещё нужно установить.
permissions = "workspace-write" # логический запрос; без enforcement preflight блокирует
timeout = 3600
environment_allowlist = ["PATH", "HOME", "TMPDIR"]
output_protocol = "kimi-stream-json-v1"
capability_requirements = ["noninteractive", "engine_delegation_bridge"]

[roles.story-runner]
agent = "codex-dev"

[roles.implementer]
agent = "kimi-dev"

[roles.reviewer]
agent = "codex-review"

[roles.reviewer-mid]
agent = "codex-review"

[roles.reviewer-lite]
agent = "codex-review"

[roles.compiler-lite]
agent = "codex-dev"

[roles.verifier]
agent = "codex-review"

[routing.deep.implementer]
agent = "codex-dev"
```

Пример содержит placeholders и не пригоден для запуска без настройки.
Название K3.1 Pro из задания не принято за подтверждённый CLI model ID.
`permissions = "workspace-write"` выражает требование, а не добавляет Kimi отсутствующую песочницу.
Модель и enforced permission mode должен подтвердить `doctor`/smoke.
`triager` задаётся отдельно, если включён `run.triage_subagent`.
Профилю verifier могут требоваться браузер/устройство/процессы; read-only подходит не всем checks.
Готовность проверяется по конкретному check, а не только по имени роли.

## Поля Agent Profile

| Поле | Семантика |
|---|---|
| `adapter` | Зарегистрированный ID backend; не имя провайдера модели |
| `executable` | Путь или команда; разрешить через PATH один раз и зафиксировать |
| `arguments` | Literal argv, список строк; массив заменяется целиком |
| `model` | Реальный ID/alias выбранного CLI; Claude aliases не переводить автоматически |
| `effort` | Необязательное значение, проверяемое адаптером для модели |
| `permissions` | Требуемый режим с проверяемой реализацией |
| `timeout` | Положительное целое число секунд; общий предел attempt |
| `environment_allowlist` | Имена разрешённых переменных; значения секретов здесь не хранятся |
| `output_protocol` | Версионированный протокол, который понимает adapter |
| `capability_requirements` | Обязательные свойства backend; unsupported/unknown блокируют |

Не вводить наследование профилей друг от друга в MVP.
Четырёх слоёв TOML и level routing достаточно для исходной задачи.
Профили сливаются как обычные таблицы через существующий `ext.merge()`.

## Роли по фактической архитектуре

Сохранить восемь ролей из `roles.ROLES`.
`reviewer`, `reviewer-mid`, `reviewer-lite` пока обозначают существующие группы review layers.
Mapping layer → role остаётся в `write_profile.REVIEWER_ROUTING`, но выводится в resolved execution plan.
Не заменять его произвольным общим reviewer: иначе потеряется разница уровней.

`planner` и `architect` пока выполняются внутри story-runner/движка.
`documentation` пока не имеет отдельного этапа выполнения.
Не добавлять их как пустые конфигурационные роли.
Позднее отдельная роль допустима только после появления реального делегируемого handoff и теста.

## Порядок разрешения

1. Слить defaults, personal, project, local по существующим правилам.
2. Разрешить уровень из `[run]` и аргументов запуска, как сейчас.
3. Для каждой реальной роли взять `[roles.<role>].agent`.
4. Если существует `[routing.<level>.<role>].agent`, применить этот маршрут.
5. Получить соответствующий `[agents.<id>]` и проверить требования роли.
6. Зафиксировать весь resolved plan и источники в attempt manifest.

`routing` выбирает профиль целиком. Model/effort overrides в routing MVP не принимает.
Так resolver не получает две конкурирующие системы изменения параметров.
CLI `run --agent <id>` не вводить до определения его точной семантики для всех ролей.
Для smoke использовать явные fixture configs со всеми нужными маршрутами.

## Совместимость

Старые `[roles.*].model/effort/provider` продолжают работать в legacy backend без миграции.
Явный `[execution] backend="legacy-plugin"` отключает унаследованные CLI profiles/routing и
поля `roles.*.agent`, сохраняя сами нижние слои и native model/effort. Resolver сообщает это
в warnings. Без явного backend новые CLI-настройки по-прежнему блокируются: неявного fallback нет.
Значение `default` сохраняет прежний смысл сброса к frontmatter.
Старые `roles` JSON поля `agent_type`, `default`, `args`, `model`, `effort` сохраняются для старых callers.
Новый resolved plan выводится отдельно, с `schema_version`, adapter/profile и источниками.

В CLI backend роль без `agent` получает внутренний legacy Claude profile с прежними настройками.
Так частичный opt-in не меняет остальные роли молча, но `doctor` явно покажет Claude-зависимость.
Для Codex-only/Kimi-only fixture обязаны явно покрыть все активные роли.
`agent` и native `model/effort/provider` могут храниться у одной роли одновременно:
CLI берёт модель из выбранного профиля `agent`, native Claude — из `model/effort/provider`.
Для настройки модели изменить Agent Profile.
Не считать Anthropic provider тем же самым, что Claude adapter: CLI и модель — разные уровни.

## Ошибки и строгая проверка

Текущий `ext.load()` пропускает повреждённый TOML. Для новых execution настроек это опасно.
Если слой пропущен, CLI backend может случайно запустить другого агента с другими permissions.
Поэтому новый `run` должен получить diagnostics по каждому слою и блокироваться на ошибке чтения существующего слоя.
Legacy `ext config` и plugin остаются с прежними предупреждениями.
Нужен additive strict-loading API; нельзя молча сделать `ext.load()` строгим для всех callers.

В новом режиме ошибки: неизвестная роль/профиль/adapter/key, конфликтующие arguments,
неизвестный protocol, отрицательный timeout, unsupported effort/permissions и незаполненные placeholders.
До записи profile, запуска model и создания рабочих веток выполнить полную валидацию.
`doctor` не вызывает API и показывает `unknown`, если доступ требует inference.
Отдельный `agent-smoke --model <model-id> --allow-model` не входит в автоматические проверки и требует явного разрешения на модель.

Не добавлять значения секретов в config dump. Environment показывать только по именам.
Resolved config в logs содержит выбранные модели и permissions, но не credentials или содержимое auth stores.

## Проверки совместимости

- Старый TOML даёт прежние Agent args и profile facts на каждом уровне.
- Новый profile наследуется по четырём слоям; plain arrays заменяются, hooks/checks сливаются по `name`.
- Project/local override изменяет только выбранный маршрут.
- Неизвестный `agent` больше не остаётся проигнорированным ключом в новом режиме.
- Повреждённый local config блокирует CLI backend и не меняет legacy семантику.
- Профили A–E из roadmap разрешаются без правки workflow исходников.
