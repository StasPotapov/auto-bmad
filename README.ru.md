<img src="assets/icon.png" width="96" alt="" align="right">

# auto-bmad

[English](README.md)

Плагин Claude Code. Он прогоняет story и целые эпики [BMad](https://github.com/bmad-code-org/BMAD-METHOD) v6
без человека.

## Что это

Движок BMad `bmad-build-auto` делает одну story за вызов. Если гнать весь эпик в одной
сессии, контекст копится, и последние истории идут медленно и дорого. auto-bmad запускает
каждую story в отдельном сабагенте: наверх приходит только короткий отчёт. Глубину ревью
задаёт уровень. Независимые истории эпика могут идти параллельно, каждая в своём git worktree.
После story идут тесты проекта и проверка на Android-эмуляторе, а найденное движок чинит сам.
На выходе — коммиты, обновлённый `sprint-status.yaml`, отчёт по каждой story и по эпику
и один файл с вопросами, которые решает человек.

## Как это работает

```
план ──► story в сабагенте ──► слои ревью ──► проверки и починка ──► коммит, синк, отчёт
 │        (bmad-build-auto)     (по уровню)    (тесты, эмулятор)            │
 └──────────────────────── следующая story или волна ◄──────────────────────┘
```

1. **План** — читает `sprint-status.yaml` и файл эпиков, собирает очередь, делает предполёт.
2. **Story в сабагенте** — `auto-bmad:bmad-story-runner` гонит движок: спека → код → коммит.
3. **Ревью** — 2, 3 или 4 слоя ревью на разных моделях, по уровню.
4. **Проверки и починка** — тесты проекта и другие проверки. Нашли проблему — движок чинит,
   до лимита.
5. **Коммит и отчёт** — синк трекинга, файл открытых вопросов, события хукам.

## Быстрый старт

1. Поставьте плагин. Скажите Claude Code «поставь плагин auto-bmad из маркетплейса
   StasPotapov/auto-bmad» или выполните:

   ```bash
   claude plugin marketplace add StasPotapov/auto-bmad
   claude plugin install auto-bmad@auto-bmad
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

```
/auto-bmad:auto-bmad epic-1            # весь эпик
/auto-bmad:auto-bmad 1-3               # одна story
/auto-bmad:auto-bmad                   # следующая story по sprint status
/auto-bmad:auto-bmad epic-1 --deep     # уровень на этот прогон: --fast | --normal | --deep
/auto-bmad:auto-bmad epic-1 --no-parallel
/auto-bmad:auto-bmad epic-1 --width 2  # не больше 2 историй в волне
```

В конце у вас: коммиты в текущей ветке (push прогон не делает), свежий `sprint-status.yaml`,
отчёт по каждой story («что сделано», «как проверить», «требует внимания»), отчёт по эпику
и файл `_bmad-output/implementation-artifacts/epic-<N>-open-questions.md`.
Статистика — `auto-bmad stats show`.

Прогон говорит с вами и пишет отчёты на вашем языке: это `communication_language` из BMad
или язык, на котором вы пишете. Сообщения коммитов и машинные метки остаются английскими.

## Без человека

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
| [Запуск](docs/ru/running.md) | аргументы, что происходит со story, отчёты, продолжение, параллельные волны |
| [Уровни](docs/ru/levels.md) | `fast` / `normal` / `deep`, слои ревью, модели |
| [Проверки](docs/ru/checks.md) | тесты проекта, проверка на эмуляторе, починка, свои проверки |
| [Конфиг](docs/ru/config.md) | слои конфига, `[run]`, `[verify_limits]`, `[[verify]]`, `[[hook]]`, примеры |
| [Хуки](docs/ru/hooks.md) | события прогона, вход и выход хука, журнал событий |
| [Прогон без человека](docs/ru/unattended.md) | `claude -p`, права, окно времени, cron, launchd, CI |
| [Статистика](docs/ru/stats.md) | `auto-bmad stats`, что меряется |
| [CLI](docs/ru/cli.md) | все подкоманды `auto-bmad` |
| [Примеры интеграций](docs/ru/examples.md) | хук доски задач, ночные прогоны с уведомлениями в чат, одна задача из трекера через story runner |
| [Пример](docs/ru/case-study.md) | настоящий прогон: Android-приложение, 4 эпика, 28 story за 10 часов, токены по эпикам |

## Лицензия

MIT
