# Зависимости от Claude Code

Таблица ниже сохраняет исходный аудит до CLI backend. Актуальные запуск, setup и статистика
Codex описаны в [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) и CLI/stats reference.

## Вывод

Зависимость проходит через запуск, вложенное делегирование, политики движка, worktrees, проверки и статистику.
Переименование файлов агентов не создаст поддержку другого CLI.
Таблица описывает текущий код; последний столбец задаёт предлагаемое изменение.

| Точка | Что привязано к Claude | Что сделать |
|---|---|---|
| `.claude-plugin/plugin.json`, `marketplace.json` | Установка plugin и регистрация skills/agent types | Сохранить пакет; отдельно обеспечить CLI без plugin loader |
| `skills/auto-bmad/SKILL.md` | `Agent`, `Skill`, Todo/Task tools, completion notification, `${CLAUDE_SESSION_ID}` | Отделить UI-отчёт от backend-neutral вызовов |
| `agents/bmad-story-runner.md` | Вызов `Skill: bmad-build-auto`, вложенные Agent, ожидание и sandbox конкретного host | Ввести engine entry и delegation bridge |
| `agents/*.md` | Frontmatter `model`/`effort`, имена `auto-bmad:bmad-*` | Сохранить legacy; разделить role prompt и backend settings |
| `scripts/roles.py` | `MODELS`, `EFFORTS`, Anthropic-only provider и Agent `args` | Новый resolved profile рядом со старым результатом |
| `scripts/write_profile.py` | Факты E/F/G/I и `with_args()` встраивают синтаксис Agent | Генерация transport policies по backend; legacy output сохранить |
| `scripts/preflight.py` | Путь `.claude/skills`, наличие agent files вместо реальной доступности, `worktree.baseRef` | Engine locator и adapter-aware readiness |
| `skills/auto-bmad/PARALLEL.md` | `isolation: "worktree"`, EnterWorktree, ограничения Bash sandbox | Для нового CLI создавать дерево до запуска процесса и передавать cwd |
| `scripts/worktree.py` | `.claude/worktrees`, `CLAUDE.local.md`, `.claude/settings.local.json` | Сохранить совместимость путей; seed по разрешённому списку backend |
| `scripts/verify.py:skill_available()` | Только `.claude/skills`, `CLAUDE_CONFIG_DIR` и Claude plugin cache | Проверять конкретную проверку в контексте её agent profile |
| `scripts/setup.py` | `--tools claude-code`, Claude headless settings, Claude permissions и команда `claude -p` | Отдельные секции готовности и команды для каждого adapter |
| `scripts/mcp_status.py`, `extensions/mockmatch/preflight.py` | `claude mcp`, Claude Design MCP | Не объявлять универсальными; диагностировать требуемый backend |
| `hooks/hooks.json`, `scripts/session_end.py` | `SessionEnd`, `${CLAUDE_PLUGIN_ROOT}`, Claude metadata | Оставить legacy collector; finishing нового runtime не зависит от host hook |
| `scripts/stats.py` | Формат `~/.claude/projects`, `Agent/Task`, subagents metadata | Нормализованные runtime events; отдельный импорт старой статистики |
| `scripts/window.py` | Снимок окон `five_hour/seven_day` от внешнего runner | Сохранить чтение legacy; лимиты адаптера хранить с provider/profile и временем |
| `README*`, `docs/{en,ru}`, `examples/` | Slash commands, installation, headless, таблицы моделей | Обновить после проверенных сценариев, без преждевременных обещаний |

## Что можно переиспользовать

`common.py`, `plan_run.py`, `read_spec.py`, `sync_sprint.py`, `open_questions.py` и `evidence.py`
уже выполняют операции над Git и BMAD-артефактами без LLM API.
`ext.py` даёт готовые layers, события и hooks.
`verify.py` и `story_finish.py` дают готовые операции процесса, но нуждаются в проверке контекста запуска.
`testrun.py` и `stub.py` дают полезные механизмы локальных процессов. Они пока не являются общим agent runtime.

Shell-команды в пользовательских hooks и tests сохраняют прежнюю семантику.
Правило «без shell-интерполяции» относится к запуску CLI-адаптеров и не требует ломать существующие hooks.

## Что действительно выполняется внутри движка

Прочитаны `SKILL.md`, `workflow.md`, `step-01…04`, `spec-template.md` локального образца в `sample-project`.
Движок запускает renderer, получает immutable snapshot с абсолютными ссылками и выполняет его инструкции.
Внутри находятся compile epic context, исследование и spec, реализация отдельным агентом,
verification, параллельные review layers, triage, маршруты `intent_gap/bad_spec/patch/defer`, commit и HALT.

Движок требует subagents. Если их нет, он должен вернуть `blocked: no subagents`.
Кроме того, его исходный workflow требует синхронных вызовов. Текущий факт F подменяет это правило для Claude.
Следовательно, отсутствие ошибки запуска Kimi/Codex ещё не подтверждает исполнение lifecycle.

## Правила миграции

1. Сначала зафиксировать артефакты и профиль поддерживаемой версии движка.
2. Затем дать движку явный способ вызвать implementer/reviewers через auto-bmad CLI.
3. Отдельно проверить, что host сохраняет контекст и дожидается всех дочерних результатов.
4. Удалять Claude-specific правила только из нового backend-профиля.
5. Legacy путь продолжает использовать прежние Agent types, facts и события.

Для явно выбранного нового маршрута запрещён тихий fallback на session model или Claude.
Это отличается от текущих фактов E/G, которые допускают замену отсутствующего agent type с записью в отчёт.
Режим legacy сохраняет такую старую семантику. Новый режим возвращает ошибку capability/configuration.

## Граница Universal Harness

auto-bmad не устанавливает глобальные AGENTS.md, MCP, skills и hooks других CLI.
Он проверяет доступность того, что нужно конкретному запуску.
Подключённый harness может подготовить это окружение заранее.
Отсутствие harness не мешает `doctor`, fake tests и поддерживаемому выполнению story.
События `story-done` и `run-end` принадлежат auto-bmad; `SessionEnd` принадлежит Claude Code.
