# План инкрементальной реализации

## Выбор по текущему агенту и локальные дополнения

Общий `.auto-bmad.toml` коммитят с проектом; игнорируемый `.auto-bmad.local.toml` дополняет
и перекрывает его на машине. Setup добавляет профиль через `--add`, сохраняя записанный default.
Codex setup helper знает свой executor и добавляет Codex без вопроса о переключении.
Скиллы передают контекст `AUTO_BMAD_EXECUTOR` вложенным процессам: Codex выбирает CLI,
Claude Code — native. Флаг `auto-bmad --executor codex|claude ...` задаёт контекст вручную.
Без контекста CLI сохраняет прежний fallback на `[execution].backend`; `--select` явно меняет default.
Локальные native модели/effort настраиваются через `setup role --layer local`; прямой `roles.*.agent`
совместим с native полями. Фикстура полной story проверяет выбор Codex при сохранённом native default
и сохранность общего TOML; оба skill helper выбирают свой backend. Нового live inference не было.

## Общий конфиг исполнителей

Один `.auto-bmad.toml` сохраняет настройки Claude Code и Codex одновременно: native роли
в `[roles.*]`, CLI-профили и маршруты в `[agents.*]`/`[routing.*]`. Общие hooks, проверки,
параллелизм и остальные настройки не дублируются. Общая команда setup с `--select` меняет
`[execution].backend`, сохраняет неактивные профили и выбирает Codex без обязательного `--model`.
Фронтенды добавляют настройки через `--add`, сохраняя default, как описано выше.
`profiles_reused=true` означает выбор сохранённых моделей/effort/таймаутов/окружения;
явное создание или изменение профилей по-прежнему требует точного `--model`.
Старый TOML читается без миграции; local может хранить только переключатель исполнителя.
Проверки: **75 тестов, OK**; ревью `gpt-6.1-sol/medium`, сверка `gpt-6-luna/medium`.
Подтверждённых ошибок кода не найдено; исправлен synopsis необязательного `--model`.

## CLI agent checks — 2026-10-30

Codex backend сохраняет mockmatch/adbm и пользовательские agent checks при setup.
Отдельный профиль роли verifier выполняет проверку после story commit; host передаёт исходные
инструкции, поля проекта, сценарий, base и прошлые проблемы. План сохраняется при fix loop;
повторяются problem checks и project-tests. Ответы, артефакты и skip reasons сохраняются в result,
verifier calls и имя проверки попадают в общую статистику. Изменение кода/index/HEAD проверяющим
останавливает запуск. Custom-артефакты пишутся в `.auto-bmad/`, browser boards — в защищённый
каталог сессии `browser/`; произвольный CLEANUP не исполняется host.
Встроенная очистка mockmatch останавливает браузер и сервер при ошибке, отмене и смерти host;
adbm и custom verifiers очищают свои ресурсы внутри sandbox до ответа.

Прогон с настоящими mockmatch 0.1.2 и Chromium 156.0.8078.4 на временном HTTP-сайте:
полная fixture story, открытие страницы, assertion и очистка — OK. Роли в этом прогоне
подставные; нового live Codex inference не было. Sandbox, сеть и доверие хукам не ослабляются.
Первый полный набор: **463 теста, OK, 484.620 с**. Ревью Sol/high и сверка Luna/medium нашли
три дефекта и устаревшую запись roadmap: отсутствие browser session при cleanup, tests-closed перед
verifier и baseline при resume. Они исправлены. Затем добавлен отдельный browser tool RPC:
Chromium требует Mach IPC, запрещённый стандартной модельной песочницей. Client bridge работает
в настоящей Codex `:workspace` без сети; host запускает только разрешённые mockmatch операции и
настроенный сервер. PID-состояние и доски защищены в Git metadata; глобальные права не меняются.
Повторное ревью Sol/high нашло четыре дефекта bridge: CLI из project skills, обход схемы URL
через batch/--site, пустые serve/url и несогласованные пути pull/frames/compare. Они исправлены:
исполняется только установленный user/plugin CLI вне проекта; URL проверяются во всех ветках;
сервер определяется host; входные и выходные пути имеют общее отображение. Два замечания Luna
по актуальности документации закрыты. Итог: **468 тестов, OK, 509.471 с**; после исправлений —
**104 целевых теста, OK** (story 35, verifier/setup/runtime/dispatch 69) и отдельный opt-in browser
smoke, **OK, 15.047 с**. Настоящие mockmatch/Chromium подтвердили feature, pull/frames/compare/board,
отмену и SIGKILL host, включая активный RPC запуска сервера. Лимиты и команда воспроизведения —
в [CODEX_VERIFIER_SMOKE.json](CODEX_VERIFIER_SMOKE.json). Android smoke не запускался.

## Статистика CLI

Codex usage автоматически попадает в основной `.auto-bmad/stats/runs.jsonl`: модели, роли,
эпики и отдельные вызовы (`stats show --epic N --calls`, JSON aggregates). Snapshot сохраняется
при ошибке/отмене, повторный сбор не дублирует расход. Учитываются контроллер, роли и retries;
неизвестный расход отделён от измеренного нуля, cached input не прибавляется к total input повторно.
Журналы старого живого smoke восстановлены без inference: 6 вызовов, input 2 523 895,
из него cached 2 301 952, uncached 221 943; output 16 216. Цены и окружающий чат не учитываются.
Legacy Claude collector сохранён. В статистику не экспортируются промпты, код и tool arguments.

Ревью: `gpt-6.1-sol/high`, независимая сверка `gpt-6-luna/medium`. Четыре подтверждённых P2
исправлены: история ревью после удаления worktree, неизвестное окончание running, видимость
ошибок пустого отчёта и tools до первого usage. Дополнительно защищены lock от symlink и
свободный task ID от экспорта приватного пути. Общий прогон — **445 тестов, OK, 415.477 с**;
после исправлений — **35 целевых проверок, OK** (CLI stats 19, legacy stats 16).
Полный fake-CLI epic подтвердил автоматический сбор в основном дереве и отсутствие дублей.

## Setup исполнителя

`$auto-bmad-setup` и общий `setup agent` выбирают Codex CLI или native Claude, модели write/review
и слой project/local. `init --agent` создаёт новый конфиг; существующий переносится без сброса
остальных настроек, с точной закрытой резервной копией. Все уровни проверяются до записи.
Agent checks отключаются только явным выбором. Kimi/Claude CLI остаются недоступными.
Явный native backend отключает унаследованные CLI-маршруты с предупреждением, не меняя нижние слои.

Ревью setup-инкремента: Codex CLI `gpt-6.1-sol/medium` по замеру и независимый crosscheck
`gpt-6-luna/medium`. Подтверждённый P2 переключения native поверх нижнего CLI-слоя исправлен.
Общий прогон — **429 тестов, OK, 412.530 с**; после исправления — **62 целевые проверки, OK**
(setup 36, agent config 8, roles 18). Generated setup profiles прошли полную story через fake CLI.
Формат Codex-скилла проверен штатным валидатором. Проверка реального CLI использовала только
version/help и plan, без inference; отсутствие installation manifest отдельно осталось блокером.

## Состояние после живой story и подключения эпиков

Codex прошёл полный живой цикл одной story на `gpt-6.1-sol/high` с настоящим BMAD workflow:
compiler → spec → implementer → три review layers → тесты → broker commit → sprint tracking.
Receipt: [CODEX_STORY_SMOKE.json](CODEX_STORY_SMOKE.json). Первый прогон выявил неявное требование
к task_id; контракт уточнён, повтор прошёл в новом worktree. Исходная ветка осталась прежней.

Общий `auto-bmad run --repo ... --arg ...` создаёт отдельную ветку и worktree, готовит snapshot
и ведёт story или последовательный epic. Все роли задаются профилями и адаптерами; parser/argv/detect
живут в transport layer, lifecycle BMAD общий. `run plan` не вызывает модель. Скилл — тонкая обёртка;
Codex и Claude metadata разделены, legacy workflow сохранён. Модели не подменяются между backend.

Epic очередь соблюдает done/Waits, окна и остановку после ошибки. Source HEAD не меняется;
merge и push ручные. Журналы, test proof и leases защищены в Git metadata, изменения не удаляются.
На момент этого инкремента readiness соответствовал receipt fingerprint, а не одному факту установки.
Kimi/Claude CLI adapters, agent verifiers, условные review layers, waves и crash resume ещё требовали
отдельных gates. Agent verifiers подключены в новом инкременте выше.
Остальные записи инкрементов ниже — история реализации; существующий plugin cache не редактировался.

Итоговое ревью общего патча выполнено через Codex CLI `gpt-6.1-sol/high` и независимую сверку
требований. Исправлены четыре подтверждённых P2: окружение host-проверок, служебные переменные
finishing, бюджет таймаутов hooks и кэширование непроверенного дерева. Дополнительно закрыты
изменение hook-конфига во время запуска, захват чужих staged-файлов hook-коммитом и изменение
проверенного кода финальными hooks. Копия Git index сохраняет исходное время: быстрая правка
того же размера теперь учитывается в хеше. Целевые проверки: story — 26, queue — 17, test runner — 21, OK.
Итоговый полный набор после исправлений: **410 тестов, OK, 396.844 с**; `git diff --check` чистый.
Тесты очереди используют fake CLI, дополнительных платных прогонов epic не выполнялось.

## Рекомендация аудита

Сначала исправить потерю файлов и доказать переносимость одной story.
Затем добавить самостоятельный CLI, переключение ролей, последовательный epic и восстановление.
Параллельные waves включать после этих проверок.
Адаптеры CLI сами по себе не дают BMAD-совместимость.

Это план будущих PR. В рамках аудита не изменены engine, runtime, конфиги и существующий код.
PR в удалённом репозитории не создавались. Коммиты и push не выполнялись.

## Первый инкремент реализации (история)

После аудита пользователь разрешил начать разработку. Исходный аудит ниже сохранён как историческая база.

- Исправлен P1 в `land`: уникальное дерево проверки, сохранение изменённых/неизвестных файлов и отказ от forced cleanup.
- Добавлен strict reader, профили и level routing (`agent-config`); старый plugin отказывает на новых маршрутах.
- Добавлен начальный argv-only transport: streams, output limits, timeout/cancel и private attempt status.
- Добавлены process lease worktree, инспекция engine contract и offline `doctor`.
- Добавлен Codex JSONL parser и явный opt-in `agent-smoke` без BMAD и merge.
- Пока нет CLI delegation bridge, story `run`, Kimi/Claude execution adapters, recovery/fix orchestration и waves нового backend.

Это не завершение PR 2–6 и не заявление о готовности Codex story execution.
Следующий внешний gate — разрешённая проверка Codex transport на выбранной модели.
Она нужна до интеграции транспорта в engine bridge. Live smoke автоматически не запускается.

Проверка инкремента: полный unittest suite — **349 тестов, OK, 95.596 с**.
Ревью кода: `gpt-6.1-sol`, effort `high`. Пять подтверждённых замечаний исправлены:
seed через symlink, SIGTERM контроллера, недоступный слой конфига, относительный executable и таймаут подготовки smoke.
Независимая сверка: `gpt-6-luna`, effort `medium`; одно устаревшее утверждение в CONFIG_EXTENSION исправлено.
Дополнительно сохранена команда тестов из local config run worktree; добавлен regression test.
Лог ревью: `/private/tmp/auto-bmad-implementation-review.log`.
Лог полного набора: `/private/tmp/auto-bmad-implementation-tests-final.log`.
Эти временные логи не входят в репозиторий. После последних уточнений целевые tests тоже прошли:
34 для land, 6 для worktree, 20 для agent config/runtime.
После отдельного разрешения пользователя transport smoke на `gpt-6.1-sol` прошёл:
Codex CLI `0.165.0-alpha.1.2`, read-only, 5.853 с, exit 0, ожидаемый JSON marker.
Первая попытка остановилась до inference на системном запрете app-server initialization.
Повтор с системным разрешением сохранил read-only sandbox самого Codex.
Результат: `/var/folders/6k/dcywbhvn2ns9lcjhgg6ntmj40000gn/T/auto-bmad-smoke-vjrb6f9g/result.json`.

Следующий инкремент добавляет `engine prepare` и CLI transport policies без изменения исходников BMAD.
Реальный renderer установленного движка проверен на временной копии с синтетическим config:
`/var/folders/6k/dcywbhvn2ns9lcjhgg6ntmj40000gn/T/auto-bmad-engine-render-xvmfrntt/package/manifest.json`.
Он создал snapshot workflow, не запускал модель и сохранил `execution_ready=false`.
Автоматическая связь dispatcher со story-controller, передача writer lease и полноценное выполнение story остаются следующими этапами.
Новый полный набор прошёл: 352 теста, OK, 95.627 с. После уточнения чтения config повторно прошли 3 целевых теста.
Дополнительный offline render сохранил проектные activation/on_complete инструкции без их выполнения.
Лог тестов: `/private/tmp/auto-bmad-engine-bridge-tests.log`.
Обязательное внешнее ревью этого инкремента не выполнено: автоматическая проверка запретила отправку
патча модели `gpt-6.1-sol` через Codex CLI, поскольку разрешение smoke не покрывает исходники для ревью.
Попытка остановлена до запуска reviewer. После отдельного разрешения пользователя ревью выполнено
через Codex CLI `gpt-6.1-sol/high`; независимый crosscheck выполнен на той же разрешённой модели и effort.
Исправлены два замечания кода: явный `UV_OFFLINE=1` и проверка snapshot directory до renderer.
Исправлено замечание crosscheck: Claude Bash tool syntax удалён из CLI политики тестов.

Следующий небольшой шаг добавляет `agent execute`: один явный handoff implementer/reviewer/другой leaf-роли,
JSON request/result, проверка подготовленной конфигурации и полного base SHA, linked worktree и execution lock.
Роль reviewer требует read-only. Непредвиденные изменения и protocol errors сохраняют результаты и завершаются ошибкой.
Вызов требует `--allow-model`. Автоматический вызов из story-controller пока не включён: сначала нужна
передача writer lease и отмена вложенных процессов. `execution_ready` и `story_completed` остаются false.
Новых живых модельных тестов после разрешённого transport smoke не запускалось.

Ревью single-role dispatcher выполнено на `gpt-6.1-sol/high`; независимый crosscheck на той же модели и effort
не нашёл новых расхождений документации. Исправлены три замечания кода: инструкции роли включаются в prompt,
Git submodules участвуют в fingerprint, подготовленный профиль BMAD защищён отдельным хэшем.
Добавлена проверка смены ветки/переписывания base без отката или удаления работы.
Финальный полный набор: **362 теста, OK, 102.965 с**. После последних уточнений manifest/envelope повторно прошли 9 dispatcher tests.
Логи: `/private/tmp/auto-bmad-role-dispatch-review.log`, `/private/tmp/auto-bmad-role-dispatch-tests-final.log`.
Следующий этап — отдельный story-controller с явной передачей writer lease, ожиданием всех дочерних результатов
и отменой вложенных процессов. Текущий dispatcher под внешним controller lease намеренно отказывает.

## Документы

- [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md) — устройство, область аудита и находки.
- [CLAUDE_DEPENDENCIES.md](CLAUDE_DEPENDENCIES.md) — точки привязки к Claude.
- [AGENT_ADAPTER_CONTRACT.md](AGENT_ADAPTER_CONTRACT.md) — adapter/runtime контракт и проверенные CLI.
- [CONFIG_EXTENSION.md](CONFIG_EXTENSION.md) — TOML, роли, наследование, совместимость.
- [BMAD_EXECUTION_DESIGN.md](BMAD_EXECUTION_DESIGN.md) — сохранение lifecycle и delegation bridge.
- [WORKTREE_AND_SAFETY.md](WORKTREE_AND_SAFETY.md) — leases, merge, cleanup и recovery.

## Результат проверки существующей базы

Команда: `python3 -m unittest discover -s tests`.
В обычной песочнице: 321 тест, 45 ошибок; среди причин — запрет `ps` и локальных операций.
Повтор с разрешением локальных процессов: **321 тест, OK, 84.019 с**.
В логе есть `ResourceWarning` об открытых файлах и процессах. Не считать их провалом набора, но учитывать при runtime cleanup.
Лог повторного запуска: `/private/tmp/auto-bmad-audit-tests.log`; это временный файл, не постоянный артефакт проекта.
В негативном тесте выводится ошибка `provider='kimi'`: это ожидаемая диагностика, а не провал набора.

Отдельно подтверждён P1: `land.test_in()` удаляет прежний каталог с несохранённым файлом.
Тесты адаптеров и платные smoke отсутствуют. Зелёный набор не доказывает поддержку Codex/Kimi.
Проверены version/help: Codex `0.165.0-alpha.1.2`, Kimi `2.4.0`, Claude `2.1.312`.
Inference и доступ к конкретным моделям не проверены.

## Порядок PR

### PR 1. Сохранность временных worktrees

Файлы: `scripts/land.py`, `scripts/worktree.py`, `tests/test_land.py`, `tests/test_worktree.py`.

- Убрать удаление занятого фиксированного каталога через `rmtree` после ошибки Git.
- Создавать уникальное дерево для проверки merge commit, с явным ownership.
- Оставлять dirty/untracked/новый ignored output после tests и сообщать путь.
- Не использовать безусловный `checkout -f`/`remove --force` для результата пользователя.

Готово: старый каталог и файл сохраняются; чужой путь не удаляется; обычный `land` проходит прежние regression tests.
Добавить тесты занятого пути, dirty worktree, ошибки статуса, symlink и изменений после tests.
Риск: cleanup начнёт оставлять больше деревьев; нужен понятный отчёт вместо скрытого удаления.
Этот PR исправляет подтверждённый дефект независимо от multi-agent расширения.

### PR 2. Контракт движка и fixtures

Новые файлы: `scripts/engine.py`, `tests/test_engine.py`, `tests/fixtures/bmad-engine/`.
Существующие: `scripts/preflight.py`, `tests/test_preflight.py`.

- Описать минимальную поддерживаемую версию/форму engine customization и spec artifacts.
- Проверить renderer entry, абсолютные snapshot references и ранний HALT.
- Сохранить fingerprint engine inputs и snapshot.
- Сделать synthetic fixture, который не копирует проектные данные из `sample-project`.
- Зафиксировать invariants фактов A–J, layers, limits и resume statuses.

Готово: неизвестный engine диагностируется до выполнения; fixture воспроизводит артефакты этапов.
Риск: установленный engine может не иметь достаточных customization points.
Решение gate: если bridge требует переписывать lifecycle, остановить перенос и согласовать узкий upstream extension point.

### PR 3. Agent Profiles и role routing

Файлы: `scripts/ext.py`, `scripts/roles.py`, `defaults.toml`, `scripts/setup.py`.
Тесты: `tests/test_ext.py`, `test_local_config.py`, `test_roles.py`, `test_setup.py`, новый `test_agent_config.py`.

- Добавить схему из CONFIG_EXTENSION с opt-in backend.
- Добавить strict diagnostics для нового execution reader, сохранив legacy loader.
- Разрешать профили и level routing без запуска процессов.
- Сохранить старые Agent args и значения `default`.

Готово: все четыре слоя и A–E configurations разрешаются однозначно; ошибки не возвращают Claude defaults молча.
Проверить конфликт `agent` с legacy overrides, неизвестные ключи, arrays и malformed TOML.
Риск: частичная конфигурация может незаметно оставить Claude. Resolved plan обязан показать все активные роли.

### PR 4. Runtime и fake CLI

Новые файлы: `scripts/agent_runtime.py`, `scripts/agent_protocol.py`, `scripts/adapters/base.py`,
`tests/fake_cli.py`, `tests/test_agent_runtime.py`, `tests/test_agent_protocol.py`.

- Реализовать argv-only launch, cwd, env allowlist, stdout/stderr streaming и result validation.
- Добавить timeout, process identity, cancel, bounded retries и private raw logs.
- Сохранить manifest/checkpoints через atomic replace.
- Дать fake CLI режимы malformed/truncated output, 429, auth, stderr flood, child processes и hang.

Готово: тесты offline; нет deadlock и секретов в output; error kinds различаются; exit 0 без результата отвергается.
Не делать бесконтрольный retry после частичных изменений.
Риск: detached процессы CLI и существующий `testrun` требуют отдельного ownership cleanup.

### PR 5. Владение worktree и delegated writer

Файлы: `scripts/worktree.py`, новый `scripts/execution_state.py`, `scripts/agent_runtime.py`.
Тесты: `tests/test_worktree.py`, новые `test_execution_state.py`, `test_worktree_leases.py`.

- Привязать run/task/profile/base/head к canonical worktree.
- Ввести межпроцессный lease и передачу writer-права implementer.
- Сохранить существующие пути и ветки legacy; новые именовать уникально.
- Закрепить config snapshot и seed allowlist без credentials.

Готово: конкурирующий процесс блокируется; handoff родитель → ребёнок → родитель не зависает.
Проверить PID reuse, controller crash, seed failure, разные написания одного пути и чужое изменение дерева.
Риск: lease — кооперативная блокировка, не системная песочница. Enforcement permissions проверяется отдельно.

### PR 6. Codex adapter и offline doctor

Новые файлы: `scripts/adapters/codex.py`, `scripts/doctor.py`, `tests/test_adapter_codex.py`, fixtures CLI streams.
Изменить `bin/auto-bmad` только для новых служебных entrypoints.

- Версионно проверить help и capabilities, не зашивать устаревший `--full-auto`.
- Реализовать JSONL events и schema final output.
- Проверить модель/effort и реальные permissions.
- Не обходить hook trust и exec policies.

Готово offline: контрактные fixtures проходят; unsupported flags/effort дают ошибку до запуска.
Готово live: после отдельного разрешения выполнить ограниченный smoke с выбранной моделью.
Риск: установлен alpha CLI; интерфейс нельзя считать стабильным по одному номеру версии.

### PR 7. Engine host bridge: одна Codex story

Файлы: `scripts/engine.py`, `scripts/write_profile.py`, новый `scripts/agent_dispatch.py`,
новые backend-neutral entry prompts под `runtime/`, `bin/auto-bmad`.
Тесты: `tests/test_engine_bridge.py`, `test_write_profile.py`, `test_agent_dispatch.py`.

- Дать rendered workflow вместо Claude Skill tool.
- Перенаправить implementer/compiler/reviewers/optional triager через runtime CLI.
- Сохранить handoffs, AC, слой claims, limits, triage и fixes.
- Сохранить неизменным generated profile legacy backend.
- Сделать result validator с точным base/diff hash и engine artifacts.

Готово offline: fake engine/story проходит spec → code → review → fix → commit и все resume routes.
Готово live: одна Codex-only story создаёт нативные BMAD artifacts и проходит gates.
Недостаточно: модель вернула `done`, но нет результатов layers/verification/commit.
Риск: LLM проигнорирует transport policy и вызовет native tool. Это выявляется trace assertions и блокирует gate.

### PR 8. Самостоятельный `run` и внешние checks

Новые файлы: `scripts/run.py`, `scripts/result_validation.py`, `tests/test_run_story.py`.
Изменить `bin/auto-bmad`, `scripts/{verify,story_finish,preflight}.py` и их тесты.

- Собрать одну story из существующих scripts без отдельного управляющего агента.
- Подключить command и agent checks, fix-spec, followup passes, questions и finishing.
- Перед sync проверять engine result и подтверждённый commit.
- Включить manual merge policy и явный terminal status.

Готово: запуск из обычного terminal работает без Codex desktop и без Universal Harness.
Проверить fast/normal/deep, red baseline, skipped checks, fix exhaustion, blocked result и early HALT.
Риск: Python не должен дублировать внутреннюю логику BMAD bad_spec/patch loops.

### PR 9. Kimi и Claude CLI adapters

Новые файлы: `scripts/adapters/{kimi,claude}.py`, `tests/test_adapter_{kimi,claude}.py` и stream fixtures.
Изменить `scripts/{doctor,setup,verify}.py` для backend-aware capabilities/skills.

- Подтвердить локальный alias K3.1 Pro, не выводить его из маркетингового имени.
- Нормализовать Kimi stream и терминальные результаты.
- Установить фактическое enforcement permissions. `-p` уже использует auto policy; отсутствие `--auto` не ограничивает его.
- Реализовать Claude CLI entry с plugin loading и прежними profile policies.
- Legacy slash/plugin путь продолжает работать без миграции.

Готово: offline contract tests каждого adapter; затем разрешённые live smoke всех пяти сценариев.
Если Kimi не обеспечивает требуемые права, маршрут блокируется до проверенного внешнего ограничения.
Риск: это может заблокировать Kimi reviewer/implementer gate; не выдавать частичную поддержку за MVP.
Этот PR можно разделить на Kimi и Claude части, чтобы не смешивать review.

### PR 10. Recovery и статистика

Файлы: `scripts/{run,execution_state,stats,story_finish,ext,window}.py`, новый `scripts/run_events.py`.
Тесты: новые `tests/test_run_recovery.py`, `test_run_cancel.py`, существующие `test_stats.py`, `test_window.py`, `test_story_finish.py`.

- Добавить `status/resume/cancel`, reconcile manifest с Git/spec и idempotency keys.
- Продолжать после commit до потерянного ответа без повторной реализации.
- Сохранять model requested/observed и неизвестные метрики как null.
- Не смешивать Claude оценку output tokens с точными метриками другого backend.
- Поддержать pause по rate limit/deadline без смены аккаунтов и скрытых fallback.
- Оставить Claude transcript importer и SessionEnd как совместимый legacy путь.

Готово: fault injection до/после spawn, spec write, commit, verify, sync, hook и journal flush.
Проверить отсутствие двойных tracking commits/statistics и явную неоднозначность внешнего hook.
Риск: arbitrary hook нельзя сделать exactly-once только локальным журналом.

### PR 11. Последовательный epic

Файлы: `scripts/run.py`, `scripts/plan_run.py`, `scripts/window.py`, tests `test_run_epic.py`, `test_plan_run.py`.

- Выполнять существующую очередь строго последовательно.
- Соблюдать зависимости, blocked stories, окно времени и лимиты.
- Остановить run при отказе проверки; не продолжать зависимые stories.

Готово: offline epic fixture минимум с тремя stories, blocked middle story и resume.
После разрешения — live epic smoke выбранного профиля.
Риск: spec/resume маршруты и изменяющийся HEAD могут захватить чужие изменения; точные базы обязательны.

### PR 12. Waves и разрешённая интеграция

Файлы: `scripts/{run,worktree,land}.py`, новый `scripts/waves.py`, `skills/auto-bmad/PARALLEL.md`.
Тесты: `test_run_waves.py`, `test_worktree_leases.py`, `test_land.py`, `test_window.py`.

- Зафиксировать machine-readable wave plan, сохранив правила conservative/aggressive.
- Не утверждать, что `plan_run.py` уже вычисляет story dependency graph.
- Дать каждой story отдельный owned worktree и base SHA.
- Параллельные агенты не пишут tracking общего дерева.
- На границе волны вернуть `awaiting_merge`, если нет конкретного разрешения на интеграцию.
- После разрешённого merge проверить общий результат и только затем выполнить finishing.

Готово: независимые stories идут параллельно; зависимые ждут; чужой worktree сохраняется при любой ошибке.
Проверить конфликт кода, shared tests/DB/ports, cancel одного участника, crash до/после merge и stale approval.
Риск: правила legacy waves разрешают автоматический merge; новый режим не должен унаследовать это случайно.

### PR 13. Документация, упаковка и необязательный harness

Файлы: `README.md`, `README.ru.md`, `docs/{en,ru}/{config,cli,engine,running,checks,stats,hooks}.md`,
`skills/{auto-bmad,setup}/SKILL.md`, `examples/`, metadata только при необходимости релиза.
Добавить smoke opt-in runner и понятную матрицу поддержанных версий.

Готово: установка CLI без Claude plugin/harness документирована и проверена.
Старые команды и примеры остаются применимыми; новые флаги не обещают непроверенные возможности.
Harness предоставляет окружение добровольно; auto-bmad не управляет его глобальными файлами.
Риск: поддержка второй системы глобальных hooks внутри auto-bmad нарушит архитектурную границу.

## Сценарии A–E

Каждый сценарий проверяется сменой TOML, а не редактированием workflow.
`story-runner`, compiler, triager и verifier тоже должны иметь явные профили в fixture.

| Сценарий | Implementer | Все активные reviewer роли | Остальные активные роли |
|---|---|---|---|
| A | Kimi K3.1 Pro | Codex | Явно выбранные профили fixture |
| B | Codex | Kimi K3.1 Pro | Явно выбранные профили fixture |
| C | Codex | Codex | Codex |
| D | Kimi K3.1 Pro | Kimi K3.1 Pro | Kimi |
| E | Старые Claude defaults | Старые Claude defaults | Прежний plugin workflow; отдельно Claude CLI |

Каждый сценарий должен пройти engine artifacts, AC review, verification, fix loop и recovery.
Для fast учитывать реально отключённые layers, а не требовать отсутствующий слой.
Для normal/deep проверить limits и число triage rows.
В C/D независимость достигается отдельными контекстами ролей; другой model provider не требуется.

## Что запускается автоматически

Offline: resolver, routing, fake CLI contract tests, worktree isolation, failure/recovery,
synthetic BMAD lifecycle fixture, epic fixture и regression старого профиля.
После изменения scripts запускать существующий unittest suite и новые целевые tests.
После содержательных изменений кода выполнить `$review` из главной сессии по правилам проекта.
Платные модели не включать в unittest discovery или обязательный CI.

Live smoke: только отдельная явно вызванная команда с разрешением пользователя,
выбранными моделями, лимитом времени и небольшим одноразовым проектом.
Флаг запуска smoke не должен молча авторизовывать merge, обход approvals или hooks.
Разрешение на один smoke не считать разрешением на все будущие платные проверки.

## Требует решения перед соответствующим этапом

- **Engine baseline:** выбрать версию/commit BMAD для официальной поддержки. Рекомендация: один fingerprint в MVP и понятный отказ остальным.
- **Kimi permissions:** подтвердить допустимый механизм ограничения. Рекомендация: не объявлять режим read-only без enforcement.
- **K3.1 Pro:** указать или обнаружить документированным способом локальный alias. Help подтверждает `-m`, но не конкретный model ID.
- **Legacy merge:** задание одновременно требует старое Claude поведение и запрет auto merge. Рекомендация: legacy оставить, новый CLI — manual; унификацию решить отдельно.

Эти решения не мешают завершить аудит и offline PR 1–5.
Не начинать большой рефакторинг до проверки engine bridge и согласования архитектуры.


### Инкремент: story controller и lease handoff

Добавлен экспериментальный `auto-bmad run`: одна story в подготовленном linked worktree, нативный
BMAD workflow, controller session и broker для implementer/compiler/triager/review layers.
Broker передаёт writer lease, строит точный review diff, хранит результаты вне writable worktree,
принимает checkpoint, rollback с backup patch и commit. Root lease удерживается до очистки процессов.
Тесты привязаны к session; timeout/cancel и смерть controller останавливают управляемые группы.
Followup и check fix повторяют вход в движок с существующей spec. Tracking выполняет `story-finish`;
слияние ручное. На момент этого исторического инкремента epic/waves, автоматическое crash recovery,
условные слои и agent verifiers были выключены; последующие изменения описаны выше.
Подставной CLI проверяет полный цикл и аварийные сценарии. Живой full-story smoke не запускался;
`execution_ready=false` сохраняется. Старые записи выше описывают состояние предыдущих инкрементов.


Проверка story-controller: полный набор **382 теста, OK, 224.923 с** до последних исправлений
ревью; затем повторно проверены затронутые runtime/dispatcher/lease/controller сценарии.
Код проверен через Codex CLI `gpt-6.1-sol/high`; независимая сверка документации и требований —
на той же явно разрешённой модели и effort. Исправлены обход review layers, недоверенный test cache,
сохранение baseline, относительный/пустой AUTO_BMAD_CONFIG, note-ошибки проверок, статус cleanup,
удержание inherited flock при обычном выходе host, исчезающий stub record и бинарный stdout тестов.
Проверены forged cache, SIGKILL host при тестах и SIGSTOP worker с сохранением execution lease.
Проверка renderer на настоящих исходниках BMAD и фикстура полного запуска внутри sandbox прошли без модели.
Живой full-story запуск и установка обновлённого скилла не выполнялись.
