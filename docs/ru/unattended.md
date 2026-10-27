# Прогон без человека

[English](../en/unattended.md) · [К README](../../README.ru.md)

auto-bmad может прогнать эпик, когда за клавиатурой никого нет: из терминала, cron, launchd
или CI. Для этого служит режим печати Claude Code (`claude -p`) и файл прав.

## 1. Файл прав

```bash
auto-bmad setup headless --repo . --write
```

Команда пишет `.claude/auto-bmad-headless.json` (или это делает `/auto-bmad:setup` на этапе 5).
Без `--write` она только показывает файл и команду. Файл уже есть — `--write` вернёт код 2.
Перезаписать — `--force`.

**Разрешено** — всё, без чего прогон не живёт:

- `auto-bmad`, `uv run`;
- git: `status`, `log`, `diff`, `show`, `add`, `commit`, `checkout`, `switch`, `worktree`,
  `merge`, `rev-parse`, `stash`;
- `ls`, `cat`, `grep`, `sed`, `wc`, `mkdir`;
- первое слово найденной команды тестов (например, `npm`, `pytest`, `./gradlew`);
- для Android: `./gradlew`, `adb`, `adbm` и полный путь к CLI adbm, если он нашёлся.
- для веб-проектов: `mockmatch`, `curl`, первое слово команды dev-сервера
  (например, `npm`) и полный путь к CLI mockmatch, если он нашёлся.

**Запрещено** — это делает человек:

- `git push`, `git reset --hard`, `git clean -f`, `git branch -D`, `rm -rf`.

Push прогон не делает никогда. Коммиты смотрите и пушите вы (или шаг вашего CI).

Закоммитьте файл. Незакоммиченный файл делает дерево грязным, а на грязном дереве
предполёт встаёт. Если вашу команду тестов auto-bmad не нашёл сам (вы задали её
в `.auto-bmad.toml`), допишите её в `allow` руками.

## 2. Команда

```bash
mkdir -p .auto-bmad/runs
claude -p "/auto-bmad:auto-bmad epic-1" \
  --permission-mode acceptEdits --permission-prompts none \
  --settings .claude/auto-bmad-headless.json \
  --output-format stream-json --verbose > .auto-bmad/runs/epic-1.jsonl
```

- `--permission-mode acceptEdits` — правки файлов принимаются;
- `--permission-prompts none` — всё, что спросило бы разрешение, отклоняется. Прогон
  не зависнет на вопросе;
- `--settings` — файл прав выше;
- `--output-format stream-json --verbose` — весь прогон строками JSON, чтобы прочитать потом.

Лог пишите в `.auto-bmad/`: эта папка закрыта от git. Лог в корне проекта сделает дерево
грязным, и предполёт встанет.

Уровень и другие флаги — внутри кавычек: `"/auto-bmad:auto-bmad epic-1 --deep"`.

## Режим auto: правила allow

Бот или скрипт может запускать Claude Code и в режиме auto (`"defaultMode": "auto"`
в `settings.json`) вместо файла прав. Тогда команду никто не подтверждает. Каждый вызов
идёт так: правило `allow` или `deny` решает сразу; чтение и правка файлов в рабочей папке
проходят; всё остальное проверяет классификатор, и иногда он вызов отклоняет. Отклонённый
вызов завершения теряет коммит, синк спринта, события хуков и статистику story. Поэтому
дайте прогону правила `allow` на то, что он зовёт, и опишите классификатору, что такое прогон.

Чего не хватает в ваших настройках для проекта:

```bash
auto-bmad setup allow --repo .
```

Команда собирает `allow`, `deny` и `ask` из `~/.claude/settings.json`, `.claude/settings.json`
и `.claude/settings.local.json` и печатает:

| Поле | Что это |
|---|---|
| `allow` | все правила, которые нужны прогону в этом проекте |
| `missing` | правила, которых нет ни в одном файле настроек. Более широкое правило тоже считается: `Bash(git:*)` или `Bash(git *)` покрывает `Bash(git merge:*)`, `Skill(*)` покрывает `Skill` |
| `dropped_in_auto_mode` | правила, которые режим auto не учитывает (см. ниже): такие вызовы всё равно идут к классификатору |
| `conflicts` | нужные правила, которые задевает `deny` или `ask`: `deny` отклоняет вызов, `ask` ждёт человека, которого нет |
| `auto_mode_allow` | текст для блока `autoMode.allow` (см. ниже) |
| `deny` | что запретить |

**Нужны всегда:**

| Правило | Кто его использует |
|---|---|
| `Read`, `Glob`, `Grep`, `Edit`, `Write` | движок читает и пишет код и спеки; прогон пишет вход `story-finish` |
| `Agent` | сабагент story, implementer, ревьюеры, проверки. Режим auto это правило не учитывает |
| `SendMessage` | прогон передаёт сабагенту итог его собственных сабагентов |
| `Skill` | движок `bmad-build-auto`; проверки зовут `adbm` и `mockmatch` как скиллы |
| `TaskCreate`, `TaskUpdate`, `TaskList` | список задач прогона (`TodoWrite` правила не требует: Claude Code разрешает его сам) |
| `Bash(auto-bmad:*)` | все скрипты прогона: план, предполёт, синк, вопросы, `story-finish`, статистика |
| `Bash(uv run:*)` | движок рендерит свой скилл через `uv run …/render_skill.py`. Режим auto, скорее всего, не учитывает это правило: это запуск через пакетный менеджер |
| `Bash(git status:*)`, `Bash(git log:*)`, `Bash(git diff:*)`, `Bash(git show:*)`, `Bash(git rev-parse:*)` | чтение дерева, база story, дифф |
| `Bash(git add:*)`, `Bash(git commit:*)` | движок коммитит story, прогон коммитит трекинг и файлы хуков |
| `Bash(git checkout:*)`, `Bash(git switch:*)`, `Bash(git worktree:*)`, `Bash(git merge:*)`, `Bash(git stash:*)` | параллельные волны: ветка на story и слияние обратно |
| `Bash(ls:*)`, `Bash(cat:*)`, `Bash(grep:*)`, `Bash(sed:*)`, `Bash(wc:*)`, `Bash(mkdir:*)` | мелкие чтения движка |

**Зависят от проекта** (`setup allow` добавляет их сам):

| Правило | Когда |
|---|---|
| команда тестов | у проекта есть тесты. Её первое слово (`Bash(./gradlew:*)`, `Bash(pytest:*)`); если это слово — интерпретатор или пакетный менеджер, то вся команда (`Bash(python3 -m pytest:*)`, `Bash(npm test:*)`) |
| `Bash(./gradlew:*)`, `Bash(adb:*)`, `Bash(adbm:*)` и полный путь к CLI adbm | Android-приложение: проверка на устройстве |
| `Bash(mockmatch:*)`, `Bash(curl:*)`, команда dev-сервера (по тому же правилу, что и тесты), полный путь к CLI mockmatch | веб-приложение: проверка в браузере |
| `mcp__claude_design__list_projects`, `…get_project`, `…list_files`, `…render_preview` | веб-приложение: проверка дизайна читает макет из Claude Design, если он задан |

**Запретить** — это делает человек: `Bash(git push:*)`, `Bash(git reset --hard:*)`,
`Bash(git clean -f:*)`, `Bash(git branch -D:*)`, `Bash(rm -rf:*)`.

**Что режим auto не учитывает.** При входе в режим auto Claude Code убирает правила `allow`,
которые дают выполнить любой код: `Bash(*)`, интерпретатор по имени (`Bash(python3:*)`),
запуск через пакетный менеджер и `Agent`. Узкое правило с целой командой остаётся. Поэтому
`setup allow` даёт команду тестов целиком, если она начинается с интерпретатора. Не добавляйте
«на всякий случай» `Bash(python3:*)` и `Bash(git -C:*)`. Первое режим auto не учитывает,
а в других режимах оно пускает любой код. Второе пропускает `git -C <папка> push` мимо
запрета `git push`. Прогону не нужно ни то, ни другое.

**Опишите классификатору, что такое прогон.** Вызовы, которые не покрыло правило, —
сабагенты, `uv run` — всё равно идут к классификатору. Блок `autoMode` описывает ему обычную
работу простыми словами. Положите его в `~/.claude/settings.json` или в `.claude/settings.local.json`
проекта: из общего `.claude/settings.json` Claude Code его не читает. Оставьте `"$defaults"`,
иначе встроенные защиты пропадут:

```json
"autoMode": {
  "allow": [
    "$defaults",
    "auto-bmad runs (the auto-bmad Claude Code plugin with the BMad engine) in this user's own repositories are routine: …"
  ]
}
```

Полный текст — в поле `auto_mode_allow` команды `setup allow`. `claude auto-mode config`
показывает правила классификатора с учётом ваших настроек.

Всё это добавьте сами: агент не должен править свои права, и режим auto режет такую правку
как изменение самого себя.

Сам прогон держит один вызов `auto-bmad` на вызов Bash и передаёт текст через файлы,
а не через heredoc или пайп в `python3 -c`: правило allow совпадает с простой командой,
а цепочку всё равно проверяет классификатор. Шаги завершения story — одна команда,
`auto-bmad story-finish` (см. [CLI](cli.md#story-finish)). Даже если вызов отклонён, хук
плагина `SessionEnd` запишет статистику сессии (см. [Статистика](stats.md)).

## 3. Готовый скрипт

В плагине есть `examples/run-epic.sh`:

```bash
run-epic.sh <папка проекта> <epic-N | N-M> [--fast|--normal|--deep]
```

Скрипт переходит в проект, пишет лог в `.auto-bmad/runs/<ГГГГммдд-ЧЧММСС>.jsonl` и запускает
команду выше. Скопируйте его в постоянное место: путь плагина меняется при обновлении.

```bash
cp "$(dirname "$(command -v auto-bmad)")/../examples/run-epic.sh" ~/bin/run-epic.sh
chmod +x ~/bin/run-epic.sh
~/bin/run-epic.sh ~/src/my-app epic-1 --normal
```

`command -v auto-bmad` работает в Bash-инструменте Claude Code: там `bin/` плагина в PATH.
Вне его скопируйте скрипт из репозитория плагина.

## Окно времени и лимиты подписки

Прогон может остановиться между историями, когда кончается время или подписка. Начатую
story он не бросает никогда: окно решает только, брать ли **следующую** story (или волну).
Решает `auto-bmad window`. Он читает такие переменные окружения:

| Переменная | Что это | По умолчанию |
|---|---|---|
| `AUTO_BMAD_DEADLINE` | конец окна, Unix-время в секундах | окна нет |
| `AUTO_BMAD_RESERVE_MINUTES` | сколько минут нужно на story. Следующая берётся, только если столько осталось (на волну — ещё 15) | 60 |
| `AUTO_BMAD_LIMITS_FILE` | путь к JSON-снимку выработки подписки (ниже) | нет |
| `AUTO_BMAD_STOP_AT_FIVE_HOUR_PCT` | не брать новые истории, когда пятичасовое окно выработано на столько % | без порога |
| `AUTO_BMAD_STOP_AT_SEVEN_DAY_PCT` | то же для недельного окна, % | без порога |
| `AUTO_BMAD_LIVE_FILE` | путь к JSON, который раннер может менять во время прогона: `deadline`, `reserve_minutes`, `stop_at_five_hour_pct`, `stop_at_seven_day_pct`. Читается перед каждой историей; ключ из файла главнее переменной выше | нет |
| `AUTO_BMAD_STOP_FILE` | путь к файлу-флагу: пока файл есть, прогон доделывает текущую историю или волну и новых не берёт — чистая остановка без убийства процесса | нет |

Битое значение считается «ограничения нет». Остановился прогон по окну — финальный отчёт
называется «прогон остановлен по окну», а последней идёт машинная строка:

```
WINDOW_STOP: epic-1 done=2 left=4
```

Другие машинные строки вывода помогают скрипту, который читает поток: `WORK_START`, когда
взята story или волна, `STORY_DONE` и `STORY_BLOCKED` в конце каждого отчёта по story.
Они печатаются дословно на любом языке прогона. Полный список и пример раннера —
в [Примерах интеграций](examples.md#метки-в-выводе).

Пример: работать не дольше 6 часов.

```bash
AUTO_BMAD_DEADLINE=$(( $(date +%s) + 6*3600 )) ~/bin/run-epic.sh ~/src/my-app epic-1
```

Снимок выработки — ваш файл, auto-bmad его не делает. Формат:

```json
{
  "updated_at": 1760640000,
  "five_hour": {"utilization": 0.42, "resets_at": 1760652000},
  "seven_day": {"utilization": 0.18, "resets_at": 1761100000}
}
```

`utilization` — доля (0.42 = 42 %). Снимок старше 3 часов не учитывается. Окно,
у которого `resets_at` уже в прошлом, — тоже.

## Другие переменные окружения

| Переменная | Что это |
|---|---|
| `AUTO_BMAD_UNATTENDED` | любое непустое значение — прогон без человека: хуки получают `"unattended": true`, их вопросы отбрасываются. `AUTO_BMAD_DEADLINE` действует так же |
| `AUTO_BMAD_EVENTS_FILE` | ещё один файл, куда пишется журнал событий |
| `AUTO_BMAD_CONFIG` | путь к личному конфигу вместо `~/.config/auto-bmad/config.toml` |

## cron

```cron
# Каждую ночь в 01:00, не дольше 5 часов.
0 1 * * * PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin AUTO_BMAD_UNATTENDED=1 AUTO_BMAD_DEADLINE=$(( $(date +\%s) + 5*3600 )) $HOME/bin/run-epic.sh $HOME/src/my-app epic-1 >> $HOME/auto-bmad-cron.log 2>&1
```

У cron короткий PATH: проверьте, что в нём есть `claude`, `git`, `uv` и `python3`.
`%` в crontab нужно экранировать: `\%`.

## launchd (macOS)

`~/Library/LaunchAgents/com.example.auto-bmad.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.auto-bmad</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>AUTO_BMAD_DEADLINE=$(( $(date +%s) + 5*3600 )) "$HOME/bin/run-epic.sh" "$HOME/src/my-app" epic-1</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>AUTO_BMAD_UNATTENDED</key><string>1</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>1</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/tmp/auto-bmad.out</string>
  <key>StandardErrorPath</key><string>/tmp/auto-bmad.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.example.auto-bmad.plist
```

## CI

Набросок для GitHub Actions. На раннере нужны Claude Code с авторизацией, плагин, `uv`
и Python 3.11+. BMad и план должны уже лежать в репозитории.

```yaml
name: auto-bmad epic
on:
  workflow_dispatch:
    inputs:
      target: {description: "epic-N or N-M", required: true, default: "epic-1"}
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: astral-sh/setup-uv@v5
      - run: curl -fsSL https://claude.ai/install.sh | bash
      - run: |
          claude plugin marketplace add StasPotapov/sp-tools
          claude plugin install auto-bmad@sp-tools
      - run: |
          git config user.name "auto-bmad"
          git config user.email "auto-bmad@example.com"
          mkdir -p .auto-bmad/runs
          claude -p "/auto-bmad:auto-bmad ${{ inputs.target }}" \
            --permission-mode acceptEdits --permission-prompts none \
            --settings .claude/auto-bmad-headless.json \
            --output-format stream-json --verbose > .auto-bmad/runs/ci.jsonl
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}   # или CLAUDE_CODE_OAUTH_TOKEN
          AUTO_BMAD_UNATTENDED: "1"
      # Прогон не пушит. Здесь запушьте коммиты в ветку и откройте pull request.
      - uses: actions/upload-artifact@v4
        with: {name: auto-bmad-log, path: .auto-bmad/}
```

Нативный установщик ставит Claude Code на раннер. `npm install -g @anthropic-ai/claude-code`
тоже работает, ему нужен Node.js 22+. Для авторизации заведите один секрет: API-ключ
в `ANTHROPIC_API_KEY` или токен подписки из `claude setup-token` в `CLAUDE_CODE_OAUTH_TOKEN`.
Если заданы оба, побеждает API-ключ. `--permission-prompts none` требует Claude Code
2.1.259 или новее. Подробно — [Set up Claude Code](https://code.claude.com/docs/en/setup)
и [Authentication](https://code.claude.com/docs/en/authentication).

Официальный [GitHub Action для Claude Code](https://code.claude.com/docs/en/github-actions)
(`anthropics/claude-code-action@v1`) тоже ставит плагины, через входы `plugin_marketplaces`
и `plugins`. Здесь показан голый CLI: та же команда работает в cron и launchd.

## Где логи

| Что | Где |
|---|---|
| Вся сессия (stream-json) | куда перенаправили; `run-epic.sh` пишет в `.auto-bmad/runs/<время>.jsonl` |
| Журнал событий | `.auto-bmad/events.jsonl` и `$AUTO_BMAD_EVENTS_FILE` |
| Статистика | `.auto-bmad/stats/runs.jsonl` |
| Состояние проверок (baseline, счётчики починок) | `.auto-bmad/verify/` |
| Транскрипты Claude Code | `~/.claude/projects/<проект>/` |
| Итог для человека | отчёты по story и эпику в выводе сессии; файл открытых вопросов в `_bmad-output/implementation-artifacts/` |
