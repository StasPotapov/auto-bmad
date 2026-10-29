# Исполнение BMAD через разные CLI

## Решение

Сохранить `bmad-build-auto` как владельца spec → implement → review → fix → commit.
Добавить в auto-bmad host bridge для делегирования ролей и самостоятельный CLI-вход.
Не копировать четыре этапа движка в новый Python state machine.

Обычный процесс CLI умеет выполнять команды, но не наследует Claude `Agent` и `Skill`.
Поэтому перенос включает entry wrapper движка и замену transport-инструкций в generated profile.
Этот слой должен пройти отдельный эксперимент до реализации эпиков и waves.

## Проверенный образец движка

Источник: `/path/to/project/.claude/skills/bmad-build-auto/`, локальное состояние на дату аудита.
Renderer: `/path/to/project/_bmad/scripts/render_skill.py`.
Это чтение чужого проекта для проверки контракта; файлы проекта не менялись.

`SKILL.md` запускает renderer ровно один раз. Затем агент открывает выданный `workflow.md` snapshot.
При ошибке рендера нельзя исполнять неотрендеренные исходники.
Workflow сохраняет HALT-результат в spec или отдельный result artifact.
Его `on_complete` и activation hooks могут содержать проектные действия; bridge не должен их терять.

| Этап движка | Что делает | Обязательные результаты |
|---|---|---|
| step-01 | Разрешает intent/spec, проверяет VCS, определяет resume, компилирует context | Единственная spec, epic context либо явный blocked result |
| step-02 | Исследует код, пишет spec и проверяет READY gate | Intent contract, code map, AC, verification, `ready-for-dev` |
| step-03 | Сохраняет baseline, делегирует implementer, проверяет diff и тесты | `baseline_revision`, `in-progress`, diff с новыми файлами, matrix test audit |
| step-04 Review | Собирает review layers по полному diff | Отчёт каждого активного слоя; claims только положенным слоям |
| step-04 Classify | Проверяет, группирует и маршрутизирует каждую находку | Triage log: одна строка на каждую находку |
| step-04 Fix | Выполняет `intent_gap`, `bad_spec`, `patch`, `defer` | Patch/KEEP/spec change log/deferred и ограниченные loopbacks |
| step-04 Finalize | Проверяет, коммитит, пишет результат и HALT | Чистое дерево, commit, `Auto Run Result`, status и followup flag |

Engine spec и sprint tracking используют разные статусы и имеют разных владельцев.
`spec.status=done` ещё не означает завершение внешних checks и обновление sprint.
`story_finish.py` обновляет sprint только после внешних gates.

## Артефакты, которые нужно сохранить

| Артефакт | Владелец и назначение |
|---|---|
| PRD, architecture, epics | Вход BMAD, не переписывается adapter |
| `epic-<N>-context.md` | Engine compiler, замкнутый контекст planning documents |
| `spec-<epic>-<story>-*.md` | Engine; intent contract, AC, code map, состояние |
| `baseline_revision` | Engine baseline, полный Git SHA |
| `review_loop_iteration`, `followup_review_recommended` | Engine и review policy |
| `Spec Change Log`, `Review Triage Log`, `deferred` | Полная история решений, по правилам движка |
| Diff и review-layer reports | Полный проверенный change set и отдельные результаты слоёв |
| `Auto Run Result` и fallback result | Терминальный статус движка, включая ранний HALT |
| `sprint-status.yaml`, `epic-<N>-open-questions.md` | Finishing auto-bmad |
| `.auto-bmad/` | Runtime attempts, checks, events, logs; не source of truth для AC |

Новые request/result manifests дополняют эти артефакты, а не заменяют их.
Diff и runtime files, нужные после сбоя, нельзя хранить только в исчезающем system temp.

## Предлагаемый host bridge

Добавить `scripts/engine.py` для обнаружения движка, запуска renderer и manifest snapshot.
Новый locator сначала поддерживает текущий путь `.claude/skills/bmad-build-auto`.
Путь engine сам по себе не означает, что для исполнения требуется Claude CLI.
Явный engine path можно добавить для другого расположения, с проверкой файлов и версии контракта.
Не искать произвольные skills по всему HOME.

Story-runner выбранного CLI получает entry prompt:

1. Абсолютные repo/worktree, story ID, intent либо единственный spec path.
2. Уровень и лимит review passes.
3. Путь результата `engine prepare` с canonical rendered workflow и fingerprint.
4. Backend-neutral правила вызова ролей и ожидания результата.
5. Явный запрет прямого native delegation для ролей, маршрутизированных через bridge.

Вызов движка остаётся чтением его rendered workflow и исполнением инструкций агентом.
Для Codex/Kimi не требуется существование Claude `Skill` tool.
Точная команда renderer берётся из поддержанного контракта движка, а не угадывается агентом.
Рендер запускается до передачи workflow story-runner, один раз для engine entry.
Resume/review pass создаёт новый entry с сохранённой spec по правилам движка.

Для nested roles добавить `auto-bmad agent execute --request <json>`.
Story-runner пишет request по schema и вызывает одну команду.
Python resolver выбирает профиль из закреплённой конфигурации, запускает CLI и возвращает structured result.
Агент не выбирает executable/model/permissions своими полями request.
В request остаются role, paths, layer ID, spec/base и handoff text по правилам движка.

`auto-bmad agent execute-batch --manifest <manifest.json> --session <session.json> --request <json>`
поддерживает одновременные read-only review layers.
Эта параллельность внутри review не равна параллельным story waves.
В пределах review шага движок должен получить результаты всех активных слоёв до triage.
Частичный результат не превращается в пустой список находок.

## Изменение профиля движка

Оставить факты качества A–D/H, лимиты и mapping review layers по уровню.
Для backend CLI генерировать отдельные transport policies вместо Claude E/F/G/I.
Они передают implementer, compiler, reviewer и optional triager через bridge.
Проверки после story вызывают тот же runtime с ролью verifier.
Fact J продолжает направлять tests через `auto-bmad test`.
Не переносить `timeout: 600000` как универсальный API параметр: это синтаксис Claude Bash tool.

Не делать строковые замены имён моделей в исходниках step-файлов.
Использовать существующие customization points и generated persistent facts.
Сохранить проектный implementation handoff, тексты review layers, activation и on_complete.
Если поддержанный движок не позволяет override transport без противоречия, остановить spike с `unsupported_engine`.
Тогда нужен небольшой upstream extension point, а не скрытый fork lifecycle.

Профиль обязан переопределить mandatory native subagents и same-session model policy в явной форме.
Возврат из вложенного CLI — блокирующий результат команды либо документированный runtime handle.
Claude completion notifications не применяются к Codex/Kimi автоматически.

## Владение записью и фиксы

Главный `run` координирует очередь и не редактирует код story.
Story-runner является контроллером lifecycle и может менять spec и финализировать commit.
При делегировании implementer runtime передаёт право записи дочернему attempt.
Контроллер на время handoff не пишет ни spec, ни код. После join право возвращается.
Нельзя просто держать non-reentrant lock родителем и требовать тот же lock от ребёнка: возникнет deadlock.
Lease protocol описан в [WORKTREE_AND_SAFETY.md](WORKTREE_AND_SAFETY.md).

Patch по возможности продолжает конкретную implementation session.
Если CLI не поддерживает безопасный resume с нужными параметрами, применяется разрешённый движком fallback в story-runner.
Fallback и фактический профиль фиксируются в журнале. Нельзя выдавать свежую сессию за прежнюю.
Не менять модель или права скрыто при resume.

Rollback из `bad_spec/intent_gap` должен сохранить patch и историю spec.
Разрешены только изменения текущей story в её owned worktree.
Перед запуском нужен чистый tree и точный baseline; чужие изменения блокируют rollback.

## Точный base и независимое ревью

На старте attempt закрепить полный `run_base_commit`. Перед реализацией движок пишет `baseline_revision`.
Зафиксировать оба значения и проверить, что изменение baseline объясняется шагами движка, а не чужим commit.
Сохранить `review_base_commit`, `review_head_commit`, working tree fingerprint и diff hash для каждого pass.
Текущий CLI закрепляет исходный review base на всю story, включая внешние fix attempts и bad_spec:
коммиты промежуточных задач не сужают diff и не заменяют baseline исходной реализации.
Review input включает tracked, staged, unstaged, deleted и untracked файлы, включая binary metadata.
Не использовать только последний commit или guessed merge-base.

Reviewer получает diff path, layer instruction и ровно тот контекст spec/intent, который полагается слою.
Не передавать всем слоям implementation report: текущий движок намеренно ограничивает claims.
Codex intent-alignment проверяет AC по spec/intent. Остальные слои сохраняют свои специализированные задания.
Если дерево изменилось во время review, результат устарел; повторить проверку изменённого состояния до commit.

Успех story подтверждает Python validator:

- единственная spec относится к нужной story и находится внутри разрешённых artifacts;
- engine завершил HALT без protocol/config/permission ошибки;
- spec содержит требуемые статусы, результат, AC и triage evidence;
- каждый обязательный review layer вернул результат;
- commit существует в этой ветке и соответствует проверенному состоянию;
- дерево чистое, тесты/checks имеют результаты, skips названы явно;
- исчерпанные passes/fixes отражены в рисках либо blocked по прежней политике.

Содержательную оценку AC выполняет движок/ревьюер. Validator проверяет структуру и свидетельства,
но не должен притворяться формальным доказательством корректности программы.

## Самостоятельный CLI

Добавить `auto-bmad run --arg "<story|epic и прежние флаги>" --repo <path>`.
Парсер использует `plan_run.py`; не вводить несовместимый язык выбора stories.
`run` последовательно вызывает существующие операции и engine entry через runtime.
Python здесь отвечает за очередь, attempts, внешние checks и finishing.
Повторные review passes и внешние fix attempts сохраняют существующие лимиты.
Внутренние `bad_spec/patch/defer` переходы остаются в BMAD.
`run status`, `run resume <run-id>` и `run cancel <run-id>` используют journal без daemon.

Начальный CLI поддерживает одну story, затем последовательный epic.
После реализации `run` можно вызывать из любой terminal-сессии или тонкого skill wrapper.
Постоянный управляющий Codex/Claude/Kimi не нужен.
Старый slash workflow продолжает работать отдельно до доказанной эквивалентности.

## Gates проверки переноса

Первый gate — engine spike на offline fixture: весь lifecycle использует bridge и сохраняет артефакты.
Второй gate — разрешённый пользователем Codex-only story smoke на настоящем движке.
Третий gate — Kimi-only и смешанные A/B с проверенным K3.1 Pro alias и permissions.
Четвёртый gate — последовательный epic и recovery на каждом переходе.
Последний gate — waves, merge policy и общие тестовые ресурсы.
Ни один gate нельзя заменить успешным ответом CLI «готово».
