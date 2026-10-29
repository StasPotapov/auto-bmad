# Контракт CLI-адаптера

## Статус

Это дизайн интерфейса с частичной реализацией. Текущие `agent_adapters.py`, `agent_runtime.py`, `agent_dispatch.py` и `run_queue.py` реализуют Codex transport и общий story/epic вход; Codex прошёл живую story. Kimi/Claude execution, resume и остальные gates ниже остаются планом. Нормативные команды — в CLI reference.
Адаптер отвечает за transport и параметры конкретного coding CLI.
BMAD lifecycle остаётся в движке; Git и policy gates остаются в auto-bmad.

Текущий parser возвращает `consume`, `finish` и `snapshot`: последний содержит только счётчики
usage по завершённым turns, имена/количество инструментов и признак незавершённого turn.
Runtime сохраняет snapshot также при ошибке или отмене, отдельно от task success. Модель/роль
берутся из host profile, а не из отчёта модели. Общая CLI-статистика читает эти snapshots;
для прежних Codex-журналов есть отдельный импорт JSONL. Семантика активного Codex adapter:
input включает cached input; неизвестные поля usage не превращаются в измеренный ноль.

## Минимальный интерфейс v1

| Операция | Вход | Выход и правило |
|---|---|---|
| `detect` | executable, разрешённые version/help probes | Путь, версия, fingerprint интерфейса; без LLM-запроса |
| `capabilities` | Fingerprint и данные проверенного adapter | Возможности с `supported/unsupported/unknown`; unknown не означает supported |
| `validate` | Profile, role request, capabilities | Диагностика до запуска; никаких тихих замен |
| `launch` | LaunchRequest | Handle процесса; argv list, cwd, env, без `shell=True` и `sh -c` |
| `collect` | Handle, новые stdout/stderr bytes | События transport и финальный raw result |
| `cancel` | Handle, причина, grace deadline | Остановка принадлежащих attempt процессов с отчётом cleanup |
| `normalize_result` | Raw result и ожидаемый role schema | Версионированный ExecutionResult; transport success отдельно от task success |

Runtime управляет чтением потоков, timeout и журналом. Адаптер знает формат CLI и переводит события.
Для реализации достаточно stdlib Python, как в текущих scripts. Plugin discovery по произвольным Python entrypoints в MVP не нужен.
Реестр adapter IDs позволяет позднее добавить другой CLI отдельным модулем и contract tests.

## LaunchRequest

Обязательные поля:

- `schema_version`, `run_id`, `task_id`, `attempt_id`, `role`, `profile_id`;
- `repo`, `cwd`, `worktree_id`, полные `base_commit` и ожидаемый исходный `head_commit`;
- `prompt_path`, `context_paths`, `result_schema`, `result_path`;
- `model`, `effort` либо явное отсутствие, `permissions`, `timeout_seconds`;
- `environment_allowlist`, разрешённые adapter arguments;
- `parent_attempt_id` и delegated lease для вложенного задания;
- optional `resume_handle`, применимый только к тому же adapter/profile/task/worktree.

Prompt и context передаются как данные. Ссылки на файлы проверяются до запуска.
Конфигурация, diff и вывод агента не могут менять разрешения, adapter или список environment.
Runtime сохраняет resolved config hash и engine snapshot hash рядом с attempt.

## Capabilities

Минимальный набор: `noninteractive`, `structured_events`, `structured_final`, `stdin_prompt`,
`model_selection`, `effort_values`, `permission_modes`, `read_only_enforcement`, `cwd`,
`session_resume`, `usage_reporting`, `cancel_process_group`, `engine_delegation_bridge`.

Effort проверяется для сочетания версии CLI и модели. Общего enum `low…max` для всех провайдеров нет.
Permissions описывают фактические ограничения. Approval mode не равен файловой песочнице.
`--plan` и просьба агенту «ничего не менять» не доказывают read-only enforcement.
Если обязательная возможность неизвестна, preflight блокирует выбранный маршрут.
Модель, доступная локально по alias, ещё не доказывает доступ аккаунта к inference.

## ExecutionResult v1

```json
{
  "schema_version": 1,
  "run_id": "run-…",
  "task_id": "1-3",
  "attempt_id": "attempt-…",
  "role": "implementer",
  "profile_id": "codex-dev",
  "adapter": "codex",
  "cli_version": "…",
  "model_requested": "configured-model-id",
  "model_observed": null,
  "execution_status": "completed",
  "task_status": "done",
  "exit_code": 0,
  "base_commit": "full-sha",
  "head_commit": "full-sha",
  "worktree": "/absolute/path",
  "changed_files": [],
  "artifacts": [],
  "usage": null,
  "error": null,
  "resume_handle": null
}
```

`execution_status`: `completed`, `failed`, `timed_out`, `cancelled`, `needs_attention`, `interrupted`.
`task_status`: `done`, `blocked`, `ready-for-dev`, `in-progress`, `in-review` либо `null`.
Результат implementer не означает `story done`; итог story подтверждает engine/result validator.
`error.kind`: `config`, `not_found`, `authentication`, `permission`, `rate_limit`, `transient`,
`protocol`, `engine_blocked`, `process`, `cleanup_failed`.
Отсутствующая метрика хранится как `null`, а не как нулевой расход.
Существующие текстовые заголовки Claude преобразуются отдельным legacy parser.

Код выхода 0 без валидного финального результата — ошибка протокола.
Правильный JSON без подтверждённых артефактов — ещё не успешная story.
Неизвестное необязательное stream event сохраняется в raw log. Повреждённый terminal event не игнорируется.
Размер строки, общий объём и время тишины ограничиваются. Большой diff не вставляется в event JSON.

## Локальная проверка интерфейсов

На 2026-10-29 проверены только version/help; inference не запускался.

| CLI | Установленная версия | Подтверждено локальным help | Ещё проверить |
|---|---|---|---|
| Codex | `0.165.0-alpha.1.2` | `exec`, `-C`, `--model`, `--sandbox`, `--json`, `--output-schema`, `-o`, `resume` | Model/effort для выбранного профиля, реальный stream, доверие hooks, вложенный bridge |
| Kimi | `2.4.0` | `-p`, `-m`, `--output-format stream-json`, `--agent-file`, `--skills-dir`, `--session` | Alias K3.1 Pro, effort, enforced permissions, terminal events/usage, bridge |
| Claude | `2.1.312` | `--print`, output formats, permissions и plugin-related flags в help | Headless plugin discovery и регрессия engine на fixture |

Проверка help Codex вывела предупреждение о невозможности создать PATH aliases в песочнице.
Команды version/help при этом завершились успешно. Этот результат не подтверждает работоспособность inference.

Предлагаемые argv, после разрешения реальных параметров:

```python
[codex_path, "exec", "-C", worktree, "--model", model,
 "--sandbox", "workspace-write", "--json", "--output-schema", schema,
 "-o", result_file, "-"]  # prompt через stdin

[kimi_path, "-m", model_alias, "--output-format", "stream-json",
 "-p", prompt]  # cwd задаёт runtime; поддержка stdin пока не подтверждена
```

Это эскизы, не готовые команды unattended запуска.
У Kimi help не подтверждает универсальный effort или файловую песочницу.
Документация Kimi уточняет: `-p` уже использует auto permission policy без подтверждений.
Сочетания `-p` с `--auto`, `--yolo` и `--plan` запрещены; static deny rules продолжают действовать.
Поэтому отсутствие `--auto` в argv не делает prompt mode ограниченным.
Не добавлять эти флаги и не выдавать prompt mode за enforced workspace sandbox.
Без документированного ограниченного режима нужен отдельно проверенный внешний sandbox либо отказ выбранного permission profile.
Для Claude сохранить существующий plugin workflow; CLI adapter подключить отдельно.
Не включать обходы sandbox, approvals, hook trust и exec rules.

Codex review должен читать diff относительно сохранённого полного SHA и acceptance criteria spec.
Для BMAD-слоя удобнее `codex exec` с role prompt и schema: severity и triage задаёт движок.
`codex exec review --base <sha>` тоже есть в help, но его merge-base semantics нельзя считать точным `base..head` без проверки.

## Runtime и восстановление

Runtime создаёт отдельную process group, читает оба потока параллельно и пишет ограниченные private logs.
Обычная остановка по deadline завершает текущую story через `window.py`.
Cancel/жёсткий timeout посылает TERM, ждёт grace interval, затем KILL только принадлежащей группе.
Если CLI отделяет потомков, одного killpg недостаточно: нужен проверенный механизм остановки потомков или блокирующая capability.
При неясной принадлежности PID cleanup возвращает `needs_attention`, не применяет `pkill` по имени.
Отдельно учитываются detached workers `testrun`/`stub`; они не должны потеряться при отмене родителя.

Retry допускается для подтверждённой временной ошибки с лимитом попыток и backoff.
429 с reset/retry-after останавливает новые задания до разрешённого времени.
Смена аккаунта, credentials или провайдера для обхода лимита запрещена.
После побочных эффектов нельзя просто повторить prompt: сначала reconcile Git, spec и checkpoint.
Auth/config/permissions/protocol errors не повторяются бесконечно.

Environment строится по allowlist. Не копировать `os.environ` целиком в CLI разных провайдеров.
`HOME`, PATH и backend auth store могут быть нужны самому CLI; это отдельный задокументированный доступ.
Уменьшение environment не закрывает доступ к домашним credentials без файловой песочницы.
Не копировать auth files в worktree и не писать их значения в resolved config/logs.
Аргументы `--model/--cd/--sandbox/--output-*` принадлежат адаптеру; конфликтующие user arguments отклонять.
Без shell остаётся риск семантического override через дополнительные CLI flags.

## Contract tests

Fake CLI должен выдавать нормальный stream, неверный JSON, неизвестные события, большой stderr,
exit 0 без результата, exit != 0 с результатом, auth/permission/rate-limit и незавершённый stream.
Проверить отсутствие deadlock, timeout/cancel, потомков, literal argv со спецсимволами, environment leak и повтор после сбоя.
Все эти тесты работают offline и не вызывают модели.

Источники: [OpenAI: non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[Kimi: CLI reference](https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html).
Kimi reference проверен через Context7 по исходнику `moonshotai/kimi-code/docs/en/reference/kimi-command.md`.
Локальный help имеет приоритет при расхождении с документацией другой версии.
