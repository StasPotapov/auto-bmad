# Checks after a story

[Русский](../ru/checks.md) · [Back to README](../../README.md)

The BMad engine verifies a story with the commands from its spec. After the engine's
commit, auto-bmad runs checks the engine does not see: the whole project test suite, the
feature on an Android emulator or in a browser, and any check you add. If a check finds a problem, the
engine fixes it and the check runs again.

Checks run on `normal` and `deep`. On `fast` there are none.

## Built-in checks

All three are defined in the plugin's `defaults.toml`. You configure them in your
`.auto-bmad.toml` by `name`.

### `project-tests`

Runs the whole project test suite.

```toml
[[verify]]
name = "project-tests"
kind = "command"
command = "@test_command"
levels = ["normal", "deep"]
on_fail = "fix"
timeout = 1800
```

`@test_command` means "the command auto-bmad finds in the project". It looks at these
files, in this order:

| File | Command |
|---|---|
| `package.json` with a `test` script | `npm test` |
| `Makefile` with a `test:` target | `make test` |
| `pyproject.toml` or `pytest.ini` | `pytest` |
| `gradlew` | `./gradlew test` |
| `Cargo.toml` | `cargo test` |

Set your own command in `.auto-bmad.toml`:

```toml
[[verify]]
name = "project-tests"
command = "./gradlew :app:testDebugUnitTest"
```

**Baseline.** Before the first story, the run executes the tests once
(`auto-bmad verify baseline`). If they already fail, a failure after a story is reported
as `skipped` ("tests failed before the run"), not fixed: auto-bmad does not repair tests
that were red before it started. If no test command is found, the check is skipped.

### `adbm`

Checks the feature on a real app on an Android emulator, through the
[adbm](https://github.com/StasPotapov/adbm) plugin. It runs only when:

- the project has `settings.gradle` or `settings.gradle.kts`, and
- the story's diff touches Android UI: `res/` resources, `AndroidManifest.xml`, or
  Kotlin/Java files with `@Composable`, an Activity, a Fragment or a View.

Without adbm installed, the check is skipped and the story report tells you how to install it.

Project fields (in `.auto-bmad.toml`):

| Field | Meaning |
|---|---|
| `build` | build command, for example `./gradlew :app:assembleDebug` |
| `apk` | path to the built APK |
| `package` | application id, for example `com.example.app` |
| `apis` | Android API levels to check on, for example `[35]`; one is enough unless the story is about version differences |
| `notes` | project specifics the checker must handle first, in plain words (for example "turn off FLAG_SECURE in the app settings before taking frames") |
| `serial` | a physical device the project allows. Without it, only emulators are used |
| `bug_before_after` | `false` turns off the before/after mode for bugs (default `true`) |

Empty `build`, `apk` or `package` — the checker finds them in `build.gradle*` and says
what it took.

Modes:

| Mode | When | What it does |
|---|---|---|
| feature (default) | always | builds the APK, installs it on an emulator (starts one if needed), walks the story's "How to check" scenario through the screen text (`tap`, `type`, `assert`), checks the log for crashes. A path longer than 3–4 steps is saved as a Maestro flow in `.adbm/flows/story-<id>.yaml` and replayed after a fix |
| look | the story changes layout, theme, spacing, insets or system bars | adds screenshots of the changed screens, a diff board and a verdict from adbm's image-reviewing subagent |
| before/after | only for a bug fix with reproduction steps, and `bug_before_after` is not `false` | builds the app at the commit before the story, reproduces the bug, then checks the same scenario on the fixed build |

**Emulator only.** The checker never installs anything on a physical phone unless the
project sets `serial`. If it starts an emulator itself, it does not stop it after the
story (the next story may need it); the run stops it once at the end (see `CLEANUP` below).

**Saved flow.** A Maestro flow left in the tree is committed by the run as a separate
commit, so the next preflight finds a clean tree.

### `mockmatch`

Checks the feature on the running site in a headless browser, through the
[mockmatch](https://github.com/StasPotapov/mockmatch) plugin, and, when the project has a
design, checks the changed pages against it. It runs only when the story's diff touches the
web UI: markup and styles (`.html`, `.css`, `.scss`, `.vue`, `.svelte`, `.astro`, `.jsx`,
`.tsx`…), and for a file under a `package.json` (in its folder or above, so a `frontend/`
subfolder counts too) also JS/TS in UI folders (`components`, `pages`, `app`, `routes`,
`views`, `layouts`, `ui`, `lib`), a Tailwind or PostCSS config, files in `public/` or
`static/`. Test files and the `design/` snapshot do not count.

Without mockmatch installed, the check is skipped and the story report tells you how to
install it. It is a recommendation: the browser check reads the page as text and compares
it with the design in numbers, so it is deterministic and costs far fewer tokens than
screenshots.

Project fields (in `.auto-bmad.toml`):

| Field | Meaning |
|---|---|
| `serve` | the command that starts the dev server, for example `npm run dev`. `{port}` in it is replaced with the chosen port |
| `url` | where the site answers, for example `http://localhost:5173` |
| `design_project` | a Claude Design project: its id or its `claude.ai/design/p/<id>?file=…` link. The checker pulls a fresh copy of the design for each check |
| `design_file` | the file inside that project, for example `Home.dc.html`; not needed when the link has `file=` or the project has one file |
| `design_artifact` | a claude.ai artifact of type "Design" (`https://claude.ai/artifact/…`). Needs `design`: an unattended run cannot read artifacts, so it compares with the saved copy |
| `design` | a design file in the repository: a Claude Design file saved with `mockmatch pull`, an artifact screen saved with `mockmatch import`, an HTML mockup or a PNG. With `design_project` it is the fallback without the login. Without a design field there is no design mode |
| `frame` | the `--frame` selector of the design option (`mockmatch frames <file>` lists them) |
| `widths` | widths for the design check, for example `[1440, 390]` |
| `theme` | `light`, `dark` or both |
| `notes` | project specifics in plain words (for example a test login) |

Empty `serve` or `url` — the checker takes them from `package.json` and says what it took.

Modes:

| Mode | When | What it does |
|---|---|---|
| feature (default) | always | opens the site (starts `serve` if `url` does not answer), walks the story's "How to check" scenario through the page text (`click --expect`, `type`, `assert`), then checks the console and the site's own requests for errors |
| design | the story changes how a page looks and the project has a design | runs `mockmatch compare` against the design: each `!` line (missing element, font, size, color, padding) is a problem; pixel regions get a verdict from the `mockmatch-eyes` subagent; the board is the artifact |

**Claude Design.** The design comes through the `claude_design` MCP, which has its own login.
`/auto-bmad:setup` shows its state and lists your projects and files to pick from. Before each
run, `preflight --level` checks the login (`claude mcp get claude_design`, ~2 s): not logged in
with a saved copy in `design` — a warning, the check compares with the copy; without a copy —
the run stops with what to do. The checker pulls the copy into `.auto-bmad/design/`, outside git,
so the tree stays clean. Log in with `/mcp` → `claude_design` → Authenticate.

**Design artifact.** A claude.ai artifact of type "Design" is not in Claude Design, and the
`Artifact` tool that reads it exists only in an interactive session, not in `claude -p`. So the
check compares with a copy in the repository: in a session the agent reads the screens
(`project/<Screen>.dc.html`) and saves them with `mockmatch import`; commit `design/` and set
`design`. Preflight blocks the run when `design_artifact` is set and the copy is missing. In an
interactive run the checker refreshes the copy into `.auto-bmad/design/` first.

**Dev server and port.** A port that answers is not trusted: on a shared machine it may be
another service. `extensions/mockmatch/serve.py` reuses only a server it started itself for an
earlier story; otherwise it takes the first free port from the port of `url` up and starts
`serve` there. The port reaches the server as `PORT` in the environment, as `--port N` after
`<pm> run <script>` (`-- --port N` for npm), as the number of `python3 -m http.server`, or through
`{port}` in `serve`. The server is not stopped after the story (the next story needs it); the run
stops it once at the end (see `CLEANUP` below).

## The fix loop

```
check → problem? → fix allowed? → problems added to the spec as tasks
      → engine implements only the new tasks, reviews the fix diff, commits
      → checks again (the next round)
```

| Level | Fixes per story |
|---|---|
| `fast` | 0 (no checks) |
| `normal` | 2 |
| `deep` | 3 |

Change the limits in `[verify_limits]`:

```toml
[verify_limits]
normal = 3
deep = 4
```

A fix is counted when it starts, even if the engine stops during it. After every fix the
checks run again, so the last fix is confirmed too. Checks that already passed are not
repeated, except `project-tests`: a fix may break them.

If the engine stops (`blocked`) during a fix, the story is blocked as usual. Its spec stays
`in-progress` with the fix tasks, and the next run continues it.

### When the limit is reached

The last check after the last fix still reports a problem:

| Check | Result |
|---|---|
| `adbm`, `mockmatch` or your own check | The story is still `done`: the work is committed and reviewed. A "needs attention" item says what is left, how it shows, how many fixes there were, and links the check's artifact |
| `project-tests`, baseline green | The tests are broken and could not be fixed: the story is `blocked`, the epic stops |
| `project-tests`, no baseline taken | Treated as a green baseline |

### `on_fail`

| Value | Meaning |
|---|---|
| `fix` (default) | the engine fixes the problem, up to the limit |
| `note` | no fix; the problem goes to "needs attention" |

## CLEANUP

A check can leave a cleanup command (for example, stop an emulator it started). The run
remembers each command once and runs them at the end of the run, before the `run-end` hook
event. A failed cleanup becomes a line in the report; it does not stop anything.

## Background servers of a check

A check often needs a server that keeps running while it checks: an API stub, a backend.
The verifier starts and stops such servers only through [`auto-bmad stub`](cli.md#stub),
never with `kill $(cat …)` or `pkill`: in an unattended run the permission hook denies
those, and the server outlives the run.

```bash
auto-bmad stub start api --run 1-3 --port 8000 -- python3 stub.py
auto-bmad stub stop api
```

`stub start` runs the command in its own process group and records it in
`.auto-bmad/stubs/<name>.json` with its owner: the working tree and the run (`--run`, the
story id). `stub stop` stops only what it recorded: it signals the process only while its
pid, start time and process group still match, so a process that got the same pid later is
left alone. After each story and once more at the end of the run (`run-end`)
`story-finish` calls `stub stop --all --runs-only`: the run's stubs of this tree stop even
when the verifier forgot them, and a server you started by hand without `--run` stays. The dev server of the `mockmatch` check
keeps its own mechanism (`serve.py` and `CLEANUP`): it serves every story of the run.

## Writing your own check

Add a `[[verify]]` block to `.auto-bmad.toml` (or to your personal config). Always set
`kind`: a check without `kind` is treated as `agent`.

### `kind = "command"`

A shell command. Exit code 0 is `pass`, anything else is `problem`; the last 60 lines of
output are passed to the fix.

```toml
[[verify]]
name = "lint"
kind = "command"
command = "npm run lint"
levels = ["normal", "deep"]
on_fail = "fix"
timeout = 600
```

The command runs through `sh -c` from the project root. `timeout` is in seconds
(default 1800); a timeout is a `problem`.

### `kind = "agent"`

A subagent (`auto-bmad:bmad-verifier`, Sonnet, medium) follows your markdown instructions.

```toml
[[verify]]
name = "api-smoke"
kind = "agent"
instructions = "docs/checks/api-smoke.md"
detect = "python3 scripts/touches_api.py"
on_fail = "fix"
base_url = "http://localhost:8080"          # extra field, passed to the subagent as is
```

The subagent gets: the story id, title and goal, `Base` (commit before the story) and
`Commit` (the story commit), the check name, the path to your instructions, all extra
fields of the block as JSON ("project fields"), the story's "How to check" section, the
round number, and from round 2 the problems of the previous round. It works in the project
root, does not change code and does not commit. Use `@plugin/…` to point at a file inside
the plugin. The plugin's own example is `extensions/adbm/verify.md`.



### Fields of a `[[verify]]` block

| Field | Meaning |
|---|---|
| `name` | identifier; layers are merged by it, fixes are counted by it |
| `kind` | `command` or `agent` (default `agent`) |
| `levels` | levels the check runs on (default `["normal", "deep"]`) |
| `command` | for `kind = "command"`; `@test_command` is the detected test command |
| `detect` | a command that decides whether the check applies to the story. Gets JSON `{"files": [...], "story": "...", "title": "..."}` on stdin (the files of the story diff); exit 0 — applies, otherwise skipped. Runs from the project root, 60 s limit |
| `requires` | a skill the check needs; if it is not installed, the check is skipped with `install_hint` |
| `preflight` | a command preflight runs before the run: the check fields as JSON on stdin; exit 1 — a warning, 2 — blocking, the first stdout line is the message |
| `install_hint` | how to install what is missing |
| `instructions` | markdown instructions for `kind = "agent"` |
| `on_fail` | `fix` or `note` |
| `timeout` | seconds, for `kind = "command"` (default 1800) |
| `enabled` | `false` turns the check off |
| anything else | passed to the agent subagent as "project fields" |

Checks run one at a time, in config order: emulators, ports and builds are shared on the machine.

## The verdict contract

An agent check must end its answer with a header like this:

```
VERDICT: pass | problem | skipped
MODE: <optional, your own label>
ARTIFACT: <path to a report or board, or "none">
FILES_LEFT: <files left in the tree, or "none">
CLEANUP: <command to run at the end of the run, or "none">
SKIPPED_REASON: <only for skipped>
PROBLEMS:
1. <what is wrong — where — how it shows>
```

The minimum is `VERDICT`, `SKIPPED_REASON` for `skipped`, and
`PROBLEMS` for `problem`. Write each problem as one line the engine can take as a fix task:
what should be and what is. After the header, up to 5 lines for a human, in the language
from the `Language:` field of the prompt. The header itself stays in English.

How the run uses the header:

- no header — the verdict counts as `skipped` ("the check did not answer by contract");
- `ARTIFACT` — linked in the story report;
- `FILES_LEFT` — committed by the run as a separate commit;
- `CLEANUP` — run once at the end of the run.

After the checks, the `verify-done` hook event fires once per story with the overall status
and `{"fixes": N, "checks": {"<name>": "<verdict>"}}`.
