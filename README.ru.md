<img src="assets/icon.png" width="96" alt="" align="right">

# auto-bmad

[English](README.md)

auto-bmad выполняет задачи (stories) и целые эпики по плану [BMad](https://github.com/bmad-code-org/BMAD-METHOD) v6.
Он организует написание кода, независимое ревью, проверки и исправления, затем сохраняет коммиты и отчёты.
Работает в Codex и Claude Code.

## Возможности

- Выполняет одну story, следующую задачу по плану или целый эпик.
- Разделяет работу между субагентами и запускает независимые stories параллельно в отдельных git worktree.
- Настраивает глубину ревью уровнями `fast`, `normal` и `deep`.
- Запускает тесты проекта и настроенные проверки Android или веб-интерфейса; исправляет найденные проблемы до заданного лимита.
- Сохраняет прогресс, обновляет `sprint-status.yaml` и готовит отчёты с вопросами, которые требуют решения человека.

## Как это работает

```
план ──► story в сабагенте ──► слои ревью ──► проверки и починка ──► коммит, синк, отчёт
 │        (bmad-build-auto)     (по уровню)    (тесты, эмулятор)            │
 └──────────────────────── следующая story или волна ◄──────────────────────┘
```

1. **План** — читает `sprint-status.yaml` и файл эпиков, собирает очередь, делает предполёт.
2. **Story в сабагенте** — `auto-bmad:bmad-story-runner` гонит движок: спека → код → коммит.
3. **Ревью** — 2, 3 или 4 отдельных субагента ревью по уровню; у каждого свои модель и effort.
4. **Проверки и починка** — тесты проекта и другие проверки. Нашли проблему — движок чинит,
   до лимита.
5. **Коммит и отчёт** — синк трекинга, файл открытых вопросов, события хукам.

Работу над story — спеку, код, ревью, починку, коммит — делает движок BMad. auto-bmad
настраивает его под прогон без человека через профиль уровня с правилами. Что меняет каждое
правило — в разделе [Под капотом](docs/ru/engine.md).

## Быстрый старт

### Codex

Подключите скиллы по [инструкции установки](docs/ru/install.md#codex-и-локальный-скилл).
В папке проекта вызовите `$auto-bmad-setup`, затем `$auto-bmad epic-1` для запуска эпика
или `$auto-bmad 1-3` для одной story. Подробности — [Запуск в Codex](docs/ru/codex.md).

### Claude Code

1. Поставьте плагин. Он лежит в маркетплейсе [sp-tools](https://github.com/StasPotapov/sp-tools)
   вместе с другими моими плагинами. Скажите Claude Code «поставь плагин auto-bmad из маркетплейса
   StasPotapov/sp-tools» или выполните:

   ```bash
   claude plugin marketplace add StasPotapov/sp-tools
   claude plugin install auto-bmad@sp-tools
   ```

2. Перезапустите Claude Code.
3. В папке проекта выполните `/auto-bmad:setup`. Скилл проверит окружение, поможет поставить
   BMad 6.12+ (`npx bmad-method install`, модуль `bmm`, инструмент Claude Code), проведёт
   к плану BMad (PRD → архитектура → эпики → sprint planning) и запишет `.auto-bmad.toml`.
   После каждого шага, на который он вас отправил, вызовите его снова.

Нужны git, uv, Python 3.11+ и BMad 6.12+. Для проверок на Android — плагин
[adbm](https://github.com/StasPotapov/adbm), для веб-проверок — плагин
[mockmatch](https://github.com/StasPotapov/mockmatch). Подробно — [Установка](docs/ru/install.md).

## Запуск

Команды ниже — для Claude Code. Команды Codex приведены в [быстром старте](#codex).

```
/auto-bmad:auto-bmad epic-1            # весь эпик
/auto-bmad:auto-bmad 1-3               # одна story
/auto-bmad:auto-bmad                   # следующая story по sprint status
/auto-bmad:auto-bmad epic-1 --deep     # уровень на этот прогон: --fast | --normal | --deep
/auto-bmad:auto-bmad epic-1 --no-parallel
/auto-bmad:auto-bmad epic-1 --width 2  # не больше 2 историй в волне
/auto-bmad:auto-bmad epic-1 --worktree # прогон в своём worktree, слить потом: auto-bmad land bmad/epic-1
```

В конце у вас: коммиты в текущей ветке (push прогон не делает; с `--worktree` — в ветке
`bmad/<цель>`, см. [Запуск](docs/ru/running.md#прогон-в-своём-worktree)), свежий `sprint-status.yaml`,
отчёт по каждой story («что сделано», «как проверить», «требует внимания»), отчёт по эпику
и файл `_bmad-output/implementation-artifacts/epic-<N>-open-questions.md`.
Статистика — `auto-bmad stats show`.

Прогон говорит с вами и пишет отчёты на вашем языке: это `communication_language` из BMad
или язык, на котором вы пишете. Сообщения коммитов и машинные метки остаются английскими.

## Конфиг

Конфиг необязателен: без него прогон работает на встроенных умолчаниях. Файл проекта
`.auto-bmad.toml` пишет `/auto-bmad:setup`. Личные настройки живут в
`~/.config/auto-bmad/config.toml`. Настройки проекта только для этой машины — в
`.auto-bmad.local.toml` (вне git). Конфиг задаёт:

- **умолчания запуска** — уровень, параллельные волны, ширину волны, разбор находок ревью в сабагенте;
- **модели** — модель и effort каждого реального субагента, включая каждый слой ревью отдельно;
- **проверки после story** — тесты проекта, эмулятор Android, браузер, свои команды,
  и сколько починок они могут вызвать;
- **хуки** — ваши скрипты на события прогона: сообщение в чат, карточка на доске.

```toml
[run]
level = "deep"

[executors.codex.roles.blind-hunter]
model = "gpt-6-astra"
effort = "high"

[executors.codex.roles.edge-case-hunter]
model = "gpt-6-astra"
effort = "xhigh"

[executors.claude.roles.edge-case-hunter]
model = "sonnet"
effort = "high"
```

Каждый слой — отдельный субагент. Уровень выбирает включённые проверки и глубину;
явное переопределение для уровня меняет модель/effort субагента, сохраняя его назначение.

Как настроить и что значит каждый ключ — [Конфиг](docs/ru/config.md).

## Без человека

Пример для Claude Code:

```bash
auto-bmad setup headless --repo . --write    # один раз: .claude/auto-bmad-headless.json
mkdir -p .auto-bmad/runs
claude -p "/auto-bmad:auto-bmad epic-1" \
  --permission-mode acceptEdits --permission-prompts none \
  --settings .claude/auto-bmad-headless.json \
  --output-format stream-json --verbose > .auto-bmad/runs/epic-1.jsonl
```

Для cron, launchd и CI есть `examples/run-epic.sh` — см. [Прогон без человека](docs/ru/unattended.md).

## Документация

| Страница | О чём |
|---|---|
| [Установка](docs/ru/install.md) | требования, установка, `/auto-bmad:setup` по шагам, обновление |
| [Запуск в Codex](docs/ru/codex.md) | настройка, субагенты, продолжение и ограничения хоста |
| [Запуск](docs/ru/running.md) | аргументы, что происходит со story, отчёты, продолжение, параллельные волны |
| [Уровни](docs/ru/levels.md) | `fast` / `normal` / `deep`, слои ревью, модели по умолчанию |
| [Под капотом](docs/ru/engine.md) | движок BMad, профиль уровня и правила («факты»), которые меняют движок |
| [Проверки](docs/ru/checks.md) | тесты проекта, проверка на эмуляторе, починка, свои проверки |
| [Конфиг](docs/ru/config.md) | слои конфига, `[run]`, `[roles.*]`, `[verify_limits]`, `[[verify]]`, `[[hook]]`, примеры |
| [Хуки](docs/ru/hooks.md) | события прогона, вход и выход хука, журнал событий |
| [Прогон без человека](docs/ru/unattended.md) | `claude -p`, права, окно времени, cron, launchd, CI |
| [Статистика](docs/ru/stats.md) | `auto-bmad stats`, что меряется |
| [CLI](docs/ru/cli.md) | все подкоманды `auto-bmad` |
| [Примеры интеграций](docs/ru/examples.md) | хук доски задач, ночные прогоны с уведомлениями в чат, одна задача из трекера через story runner |
| [Пример](docs/ru/case-study.md) | настоящий прогон: Android-приложение, 4 эпика, 28 story за 10 часов, токены по эпикам |

## Лицензия

MIT
