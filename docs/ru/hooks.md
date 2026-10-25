# Хуки

[English](../en/hooks.md) · [К README](../../README.ru.md)

Хук — команда, которую auto-bmad зовёт на события прогона: прислать уведомление, обновить
доску задач, записать лог — что угодно своё. JSON на входе в stdin, JSON на выходе в stdout.
**Хук никогда не останавливает прогон**: его ошибка — одна строка в отчёте.

## Как подключить

В личном конфиге (`~/.config/auto-bmad/config.toml`) или в `.auto-bmad.toml` проекта:

```toml
[[hook]]
name = "notify"
events = ["story-done", "story-blocked", "run-end"]
command = "python3 ~/my-hooks/notify.py"
timeout = 60
```

| Поле | Что это |
|---|---|
| `name` | имя; по нему сливаются слои |
| `events` | на какие события звать хук |
| `command` | идёт через `sh -c` из корня проекта; `@plugin` заменяется на каталог плагина |
| `timeout` | секунды, по умолчанию 120. Хук не ответил вовремя — это ошибка в отчёте |
| `enabled` | `false` выключает (например, личный хук в одном проекте) |

## События

| Событие | Когда | Заполненные поля |
|---|---|---|
| `run-start` | раз на прогон, до предполёта | `epic`, `level` |
| `story-start` | story взята в работу: после её предполёта (по одной) или на старте её волны (параллельно) | `story`, `title`, `epic`, `level` |
| `verify-done` | после шага проверок story, один раз | `story`, `status` (`pass`, `problem`, `skipped`), `data`: `{"fixes": N, "checks": {"<name>": "<вердикт>"}}` |
| `story-done` | после коммита трекинга готовой story | `story`, `status` = `done`, `spec`, `commit`, `questions_file` |
| `story-blocked` | story остановлена; после коммита её разбора в файл открытых вопросов | `story`, `status` = `blocked`, `spec`, `commit`, `questions_file` |
| `wave-merged` | раз на параллельную волну, после её коммита трекинга | `epic`, `data`: `{"wave": N, "stories": ["1-2", "1-3"]}` |
| `run-end` | ровно раз на прогон, при любом исходе, до финального отчёта | `epic`, `level`, `status` (`done`, `blocked`, `window`), `data`: `{"done": N, "left": M}` |
| `answer` | человек ответил на вопрос хука; идёт только этому хуку | `data`: `{"answer": "<id варианта>"}` |

`story-done` идёт после коммита намеренно: хук может прочитать с диска спеку и секцию
story в файле открытых вопросов.

## Вход (stdin)

```json
{
  "event": "story-done",
  "repo": "/path/to/project",
  "unattended": false,
  "story": "1-3",
  "title": "Импорт CSV",
  "epic": "1",
  "level": "normal",
  "spec": "_bmad-output/implementation-artifacts/spec-1-3-csv-import.md",
  "commit": "a1b2c3d",
  "status": "done",
  "questions_file": "_bmad-output/implementation-artifacts/epic-1-open-questions.md",
  "data": {}
}
```

Поля, которые к событию не относятся, равны `null`. `unattended` — `true`, если в окружении
задан `AUTO_BMAD_UNATTENDED` или `AUTO_BMAD_DEADLINE` (см. [Прогон без человека](unattended.md)).

## Выход (stdout)

```json
{
  "ok": true,
  "message": "story 1-3 готова: a1b2c3d",
  "link": "https://tracker.example.com/task/42",
  "files": ["docs/changelog/1-3.md"]
}
```

| Поле | Что это |
|---|---|
| `ok` | `true` / `false`. Нет поля — берётся по коду выхода (0 — `true`) |
| `message` | одна строка человеку, как есть |
| `link` | ссылка, она попадёт в отчёт по story строкой `<name>: <ссылка>` |
| `files` | файлы, которые хук создал в рабочем дереве. auto-bmad коммитит ровно их, с `message` как сообщением коммита |
| `ask` | вопрос человеку (ниже) |

Пустой stdout — это `{}`. Вывод не JSON-объектом — ошибка. Хук с `ok: false` и без
`message` попадает в отчёт ошибкой с его stderr.

### `ask` — вопрос человеку

```json
{
  "ok": true,
  "ask": {
    "question": "Завести колонку на доске для эпика 1?",
    "options": [
      {"id": "yes", "label": "Завести", "description": "Добавит колонку с именем эпика"},
      {"id": "no", "label": "Не надо", "description": "Ничего не меняется"}
    ]
  }
}
```

Прогон задаёт вопросы только на `run-start`, до первой истории. Выбор человека уходит
тому же хуку событием `answer`, в `data.answer` — `id` варианта. Передать ответ можно
и руками:

```bash
auto-bmad ext answer --hook notify --option yes --repo .
```

Человек ответил своё («потом») — ничего не передаётся, хук спросит в следующий раз.
В прогоне без человека (задан `AUTO_BMAD_UNATTENDED` или `AUTO_BMAD_DEADLINE`) вопросы
отбрасываются: отвечать на них некому.

## Журнал событий

Каждое событие дописывается в `.auto-bmad/events.jsonl` проекта (закрыт от git локально)
и в файл из `AUTO_BMAD_EVENTS_FILE`, если он задан. Пишутся только id, статусы и время,
без текстов:

```json
{"ts": "2026-10-16T21:04:11+02:00", "event": "story-done", "story": "1-3", "epic": "1", "level": "normal", "status": "done", "commit": "a1b2c3d", "hooks": {"notify": 0}}
```

`hooks` — код выхода каждого вызванного хука (`null`, если хук не доработал).

## Событие руками

Проверить хук без прогона:

```bash
auto-bmad ext fire story-done --story 1-3 --status done --commit a1b2c3d --repo .
```

`fire` всегда выходит с кодом 0, итог каждого хука — в `results`. Учтите: команда тоже
пишет строку в журнал событий.

## Шаблон

В плагине есть `examples/hook-template.py`. Скопируйте его, поправьте `handle`, подключите:

```python
#!/usr/bin/env python3
import json
import sys


def handle(event):
    kind = event.get("event")
    if kind == "story-done":
        return {"ok": True, "message": f"story {event.get('story')} done: {event.get('commit')}"}
    if kind == "story-blocked":
        return {"ok": True, "message": f"story {event.get('story')} blocked"}
    if kind == "run-end":
        return {"ok": True, "message": f"run finished: {event.get('status')}"}
    return {"ok": True}


if __name__ == "__main__":
    try:
        result = handle(json.load(sys.stdin))
    except Exception as e:  # a hook must answer JSON even when it fails
        result = {"ok": False, "message": f"hook failed: {e}"}
    print(json.dumps(result, ensure_ascii=False))
```

## Пример: уведомление на macOS

`~/.config/auto-bmad/hooks/notify.py`:

```python
#!/usr/bin/env python3
"""Уведомление macOS, когда story встала или прогон кончился."""
import json
import subprocess
import sys

event = json.load(sys.stdin)
kind = event.get("event")
if kind == "story-blocked":
    text = f"Story {event.get('story')} остановлена"
elif kind == "run-end":
    data = event.get("data") or {}
    text = f"Прогон {event.get('status')}: готово {data.get('done')}, осталось {data.get('left')}"
else:
    print(json.dumps({"ok": True}))
    sys.exit(0)

subprocess.run(["osascript", "-e",
                f'display notification {json.dumps(text, ensure_ascii=False)} with title "auto-bmad"'],
               check=False)
print(json.dumps({"ok": True}))
```

Подключите в `~/.config/auto-bmad/config.toml`:

```toml
[[hook]]
name = "desktop-notify"
events = ["story-blocked", "run-end"]
command = "python3 ~/.config/auto-bmad/hooks/notify.py"
timeout = 30
```

Проверьте:

```bash
echo '{"event": "story-blocked", "story": "1-3"}' | python3 ~/.config/auto-bmad/hooks/notify.py
```
