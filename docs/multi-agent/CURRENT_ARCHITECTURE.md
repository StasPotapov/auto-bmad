# Текущая архитектура auto-bmad

Дата исходного аудита: 2026-10-29. Ниже сохранено состояние до реализации; актуальный статус — в [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) и CLI reference. Утверждения «ещё нет» относятся к исходному аудиту.

## Вывод

auto-bmad можно расширить без замены BMAD lifecycle. Однако сейчас это Claude Code plugin со служебным CLI.
В репозитории нет самостоятельного исполнителя `auto-bmad run`, который выполняет story от начала до конца.
Главная работа миграции — перенос способа делегирования внутри внешнего BMAD-движка, а не добавление трёх команд запуска.

«Мультиагентность» здесь имеет два значения: несколько изолированных исполнителей и поддержка разных coding CLI.
Первое уже реализовано инструкциями Claude Code. Для второго нужны adapter contract, runtime и мост к движку.
Поддержку «любого агента» можно обещать только после проверки его возможностей по контракту.

## Область и ограничения

- Проверена локальная рабочая копия на `local development machine`.
- HEAD: `b5c78c377012d38048f758418a2cb56ea4e7070f`.
- Версия в `.claude-plugin/plugin.json`: `1.5.0`.
- В аудит включены существующие staged/unstaged изменения. Аудит не относится только к опубликованному релизу.
- Проверены `bin/`, `scripts/`, `agents/`, `skills/`, `hooks/`, `extensions/`, документация и тесты.
- Дополнительно прочитана установленная копия движка в `/path/to/project/.claude/skills/bmad-build-auto/`.
- Эта копия движка — локальный образец, а не подтверждение совместимости всех версий BMAD.
- Удалённый GitHub не проверялся. Модели, платные ревью и BMAD stories не запускались.

До аудита изменены: `agents/bmad-implementer.md`, `agents/bmad-story-runner.md`, `bin/auto-bmad`,
`docs/{en,ru}/{checks,cli,engine}.md`, `scripts/{land,verify,write_profile}.py`,
`skills/auto-bmad/{SKILL,PARALLEL}.md`. Уже добавлены `scripts/testrun.py` и `tests/test_testrun.py`.
Эти изменения аудит не исправляет и не перезаписывает.

## Кто управляет выполнением

| Узел | Фактическая ответственность | Источник |
|---|---|---|
| Главная Claude-сессия | Очередь, выбор волн, запуск story-runner, verification, merge, отчёт | `skills/auto-bmad/SKILL.md`, `PARALLEL.md` |
| Story runner | Одна story, вызов движка, повторный review pass, итоговый заголовок | `agents/bmad-story-runner.md` |
| Внешний BMAD engine | Исследование, spec, реализация, review layers, triage, исправления, commit | `.claude/skills/bmad-build-auto/` проекта |
| Служебный CLI | Детерминированные операции, вызываемые сессией | `bin/auto-bmad`, `scripts/*.py` |
| Внешний headless runner | Запускает Claude, передаёт окно времени и снимок лимитов | `scripts/setup.py`, `scripts/window.py` |

`bin/auto-bmad` выбирает Python-скрипт по подкоманде и делает `exec`.
Он не запускает LLM и не содержит цикл исполнения story.
Команды `plan`, `profile`, `spec`, `verify` и `story-finish` — компоненты процесса, а не сам процесс.

## Последовательность одной story

1. `plan_run.py` читает sprint tracking и epics, выбирает story и уровень.
2. Главная сессия вызывает preflight, пишет профиль уровня и получает исходное состояние тестов.
3. `read_spec.py` выбирает новую работу либо продолжение по существующей spec.
4. Главная сессия запускает `auto-bmad:bmad-story-runner` через Claude `Agent`.
5. Story runner вызывает `Skill: bmad-build-auto` с intent или абсолютным путём spec.
6. Движок рендерит snapshot workflow, выполняет lifecycle и коммитит код.
7. Story runner читает `spec --result`, при необходимости повторяет review в пределах лимита.
8. Главная сессия планирует внешние проверки через `verify.py`.
9. Проверка-команда выполняется скриптом. Проверку-агента выполняет `bmad-verifier`.
10. При проблеме `verify fix-spec` возвращает spec в работу, затем движок выполняет исправление.
11. `story_finish.py` обновляет tracking, вопросы, коммиты служебных файлов, события и статистику.

Подробный контракт движка и артефактов: [BMAD_EXECUTION_DESIGN.md](BMAD_EXECUTION_DESIGN.md).

## Конфигурация и роли

`ext.load()` сливает четыре слоя: defaults → personal → project → local.
Таблицы сливаются по ключам. `[[hook]]` и `[[verify]]` сливаются по `name`.
Остальные массивы заменяются целиком. Нечитаемый TOML пропускается с предупреждением.
В linked worktree отсутствующие project/local конфиги могут читаться из главного дерева.

`roles.py` знает восемь ролей: `story-runner`, `implementer`, `reviewer`, `reviewer-mid`,
`reviewer-lite`, `compiler-lite`, `triager`, `verifier`.
Модели и effort берутся из frontmatter `agents/*.md`, затем применяются `[roles.*]`.
Поддерживается только `provider = "anthropic"`; модели ограничены Claude Agent aliases.
Уровни меняют маршрутизацию review layers, отключённые слои и лимиты циклов.
Отдельных конфигураций маршрутов для `fast/normal/deep` сейчас нет.

`write_profile.py` пишет `_bmad/custom/bmad-build-auto.user.toml`.
Факты A–D и H задают политики качества и расхода контекста.
E/G/I задают Claude agent types, F — ожидание Claude Agent, J — тестовый CLI.
Эти тексты влияют на движок через инструкции; Python не контролирует каждый переход lifecycle.

## Параллельность и Git

`plan_run.py` строит очередь и параметры параллельности. Зависимости волн оценивает главная LLM-сессия по `PARALLEL.md`.
Python-планировщика графа story-зависимостей здесь нет.
Обычная параллельная волна использует Claude `Agent(isolation: "worktree")`.
Story runner проверяет изоляцию, задаёт ветку и исходный commit, копирует локальные BMAD-настройки.
Главная сессия последовательно сливает ветки и проверяет общий результат.

`worktree.py` уже умеет создавать, перечислять, наполнять и удалять worktrees.
`worktree start` создаёт дерево целого запуска `bmad/<target>`, которое позже сливает `land.py`.
Структурированной привязки agent attempt → точные base/head → lease worktree пока нет.
Блокировка в `testrun.py` защищает тесты одного каталога, а не всех пишущих агентов.

## Проверки, hooks и статистика

- `verify.py`: выбор checks по diff, command/agent checks, baseline, счётчик исправлений, изменение spec.
- `testrun.py`: блокировка тестов каталога, detached worker, timeout, результаты по хэшу дерева и команды.
- `stub.py` и `extensions/mockmatch/serve.py`: управление вспомогательными процессами.
- `ext.py`: события auto-bmad, JSON journal и shell hooks проекта.
- `hooks/hooks.json`, `session_end.py`: отдельный Claude `SessionEnd` для статистики.
- `stats.py`: разбор Claude transcripts, agent metadata, моделей, токенов и текстовых заголовков.
- `window.py`: мягкая остановка между stories/волнами по deadline, stop-file и снимку лимитов.

`window.py` не реализует timeout процесса и не обнаруживает лимиты всех провайдеров.
`testrun.py` запускает доверенные команды проекта через `sh -c`.
Это отдельный интерфейс от будущего запуска coding CLI через argv без shell.

## Recovery

Spec хранит стадию BMAD и позволяет повторно войти в движок.
Скрипты сохраняют состояние тестов, fixes, Git base для run worktree и часть статистики.
Для прерванной волны инструкции требуют осмотра веток и решения человека.
Единого журнала attempts с атомарным checkpoint и идемпотентными finishing effects нет.
Повтор `story-finish` может повторно вызвать hooks; контракт не даёт гарантию exactly-once.

## Находки ревью

| Приоритет | Находка и последствие | Основание | Действие |
|---|---|---|---|
| P1 | `land.test_in()` удаляет занятый фиксированный каталог после неудачного `git worktree remove`. Теряется несохранённая работа | `scripts/land.py:268–272`, воспроизведение ниже | Исправить до runtime, отдельным PR |
| P1 | CLI без Claude не исполняет story. Добавление адаптера без моста оставит spec/review/fix вне процесса | `bin/auto-bmad`, `agents/bmad-story-runner.md:123–187` | Сначала контракт движка и host bridge |
| P1 | Произвольный маршрут Kimi/Codex не проходит resolver; неизвестный `agent` только предупреждает и остаётся Claude | `scripts/roles.py:42–43, 79–121` | Строгая проверка новых настроек до запуска |
| P2 | Наличие skill в Claude cache считается доступностью проверки. Для другого CLI это неверно | `scripts/verify.py:70–86` | Проверять доступность через выбранный backend |
| P2 | Удаление и часть защит worktree зависят от инструкций. `--force`, `checkout -f` и cleanup могут уничтожать изменения | `scripts/worktree.py:246–269`, `scripts/land.py:264, 283–287` | Lease, ownership и проверка dirty перед каждым удалением |
| P2 | `story-finish` доверяет входному `done`. Независимой проверки commit/spec/verification перед sync нет | `scripts/story_finish.py:109–170` | Проверять структурированный результат перед finishing |
| P2 | Нет общего cancel/retry протокола. Transcript и SessionEnd привязаны к Claude | `scripts/stats.py`, `scripts/session_end.py` | Runtime events и журнал attempts |

Находки совместимости — ограничения относительно новой цели, а не заявление о поломке Claude-only режима.

### Воспроизведение P1 удаления

В одноразовом Git-репозитории создан обычный каталог `.claude/worktrees/auto-bmad-land` с `uncommitted.txt`.
Вызван `land.test_in(repo, None, "unused", HEAD)` с подменой только `run_tests` на успешный результат.
Git не смог удалить обычный каталог как worktree. Следующий `shutil.rmtree(..., ignore_errors=True)` удалил его.
Результат: `verdict=pass`, `existing_uncommitted_file_preserved=False`.
Проверка не затронула пользовательские файлы и не вызывала модели.

## Проверки аудита

Первый запуск `python3 -m unittest discover -s tests` в песочнице: 321 тест, 45 ошибок.
В трассировках есть запрет `ps` и связанных локальных операций. Это не зелёный baseline проекта.
Повторный запуск с доступом к локальным процессам: **321 тест, OK, 84.019 с**.
В логе остались ResourceWarning. Подробности проверки добавлены в roadmap.
Платные smoke/E2E не выполнялись. Текущие unit tests не доказывают переносимость движка между CLI.

## Рекомендуемая граница изменения

Сохранить scripts, TOML layers и BMAD lifecycle. Добавить узкий backend запуска и мост делегирования.
Старый plugin остаётся рабочим входом. Новый `auto-bmad run` станет самостоятельным входом в тот же процесс.
Роли переключаются внутри auto-bmad; Universal Harness остаётся необязательным источником инструкций и настроек.

Порядок работ: [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md).
