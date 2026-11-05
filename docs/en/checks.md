# Checks after a story

[Русский](../ru/checks.md) · [Back to README](../../README.md)

New native sessions (`integration-full-v1`) use focused tests and compile/build during
story work. The full suite runs on the combined candidate before main landing, normally
once per actual landing, and valid exact-candidate evidence is reused at finalization.
A failed full gate requires focused regressions/build after repair before the next full run.
Early full execution needs a concrete broad-risk reason. Missing focused coverage is a gap.
This policy also applies on fast: fast does not waive its development or landing gates.

Legacy journals keep their original behavior: checks after each story on normal/deep,
including the full project suite and configured device/browser checks; fast may omit those
legacy checks. Required independent reviews and configured agent checks remain in effect.

## Execution backend

Both native clients use the same checks and verdicts. The main chat delegates agent
checks to the configured native verifier and runs command checks through deterministic
helpers. Codex uses `execution.backend="native"`; Claude keeps its native plugin adapter.
Mock Match eyes keeps its own private client model settings and native role instructions.
Read the installed adbm/mockmatch skill before operating devices or browsers. Each check
must clean up the services it started and report anything left for the orchestrator.
Missing optional prerequisites remain explicit skips; they are never successful checks.
The removed CLI browser RPC and model subprocess transport are not fallback paths.
See the [native workflow](../../skills/auto-bmad/NATIVE.md) for evidence and repair rules.

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

**Legacy baseline policy.** Existing journals may execute the tests before the first story
(`auto-bmad verify baseline`). If they already fail, a failure after a story is reported
as `skipped` ("tests failed before the run"), not fixed: auto-bmad does not repair tests
that were red before it started. If no test command is found, the check is skipped.

**Repeats.** Tests run through [`auto-bmad test`](cli.md#test). When the story's code has not
changed since the engine ran the tests, the `project-tests` check takes that result instead of
running the suite again.

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

Use the installed Mock Match skill and its native eyes-role workflow. Eyes model/effort
come from Mock Match client settings, independently of auto-bmad. Reserve a native child
slot for that role and preserve its image limits and output contract. An unavailable
independent visual verdict is an explicit skip, never a verifier self-review.


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

Failed command check → collect all known failures → consume one `tests` attempt → fix
the entire known set → rerun the failed commands and affected regressions. Iterate until stable, exhausted or blocked for no progress.
Do not rewrite the spec or repeat review after localized fixes. Repeat independent review
only for extensive/risky cumulative changes; otherwise the main chat validates every fix
and explicitly retains prior coverage. The initial independent review remains mandatory.
New native sessions run focused tests/build after repairs, then one full gate on the final
combined candidate before main landing. Existing journals retain their final-check policy.

[`repair_limits`](config.md#repair_limits) defaults: `spec=2`, `review=5`, `tests=10`,
`no_progress=3`. Budgets are independent and persist across passes within the story.
Agent-verifier findings use `review`; actual plan corrections use `spec`.

New native Codex records focused/build checks with `native check --request PLAN.json`;
its guarded landing records the full candidate gate. Legacy journals retain `native check`.
Codex admits repairs through `native record`
(event `repair`, kind `tests`). The retained Claude adapter uses `verify attempt
--kind tests --result-file` and `verify observe --result-file`. Three attempts without
a pass or a strict reduction of known failing test IDs block the story and preserve work.
`verify fix-spec` is a manual tool, not the normal route for test repairs.


A scoped check matching the exact pre-story baseline also resolves a repaired regression
and resets the no-progress streak. Only the host's verified baseline equivalence counts;
an arbitrary skipped check cannot close a repair.

### When the limit is reached

An unresolved `on_fail="fix"` problem blocks the story for any check kind. Do not mark
it done, disable tests or weaken expectations. Environment failures require restoring
access rather than changing product code. Preexisting red baselines and explicit
`on_fail="note"` keep their existing rules and appear in the report.

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


## Verification frequency for new native sessions

New sessions save `verification_policy="integration-full-v1"`; existing journals keep their
original gates. During implementation and repairs run registered focused tests plus
compile/build checks. Do not run the full suite or a full baseline by habit, after each
review, or once per story when stories will land together. `native check --session SESSION
--story ID --request PLAN.json` persists development evidence and validates fixed registered
commands. PLAN contains `checks` (objects with development check `name` and `targets`) and
`builds` (all registered build names). Names resolve from `project_tests.development` and
`project_tests.build`; no command is generated from source filenames. Missing focused
coverage is a blocker. If no build exists, save an explicit `build_not_applicable` reason;
registered builds cannot be skipped. A concrete `full_risk` explanation permits an early full
project check only when broad/architectural risk makes it necessary. It is not a routine
preparation step. Full baseline execution is not part of this policy.

`complete` needs current focused/build evidence and all mandatory independent/agent reviews;
it marks a story ready for integration, not ready to move main. The full gate runs on the
combined candidate **before main changes**, preferably once for all stories in that landing:
`auto-bmad land BRANCH --native-session SESSION --story ID [--story ID ...]`. This extends the
existing guarded merge-candidate worktree pipeline; it never changes the selected landing
mode. It checks every selected mandatory command, the full registered `project-tests`, and
registered builds. `--no-tests` is forbidden for this policy. Preserve story worktrees until
journal finalization. Never substitute a raw Git merge for this guard in an automatic run.
A different main HEAD after checks requires a new candidate.

Exact candidate code, config, command/timeout set and saved log hashes allow a successful
integration gate to be shared across included stories and reused at finalization. A changed
merge resolution, command, config or evidence invalidates reuse; a child branch pass alone
does not certify the combined candidate. Saved evidence lives in journal metadata even when
the temporary candidate worktree is removed. For an existing candidate, the finite verifier
can run/join `native integration-check --session SESSION --repo CANDIDATE --story ID ...`.
A running result is not a pass. After a failed full gate, repair the complete failure set,
then run focused regressions/build on the repaired candidate with `native check --repo
CANDIDATE --request PLAN.json ...`, then rerun the final full gate. A failed full gate cannot
immediately trigger another full execution without this current focused evidence.

Wave/dependency barriers and the configured landing mode are unchanged. One full gate per
whole epic applies when that epic has one combined landing; separate authorized landings
need their own exact-candidate proof. Do not silently combine landings or weaken reviews,
mandatory checks, clean-tree, ancestry or finalization requirements to reduce run counts.


```toml
[project_tests.development.unit]
command = "python3 -m pytest"
targets = ["tests/test_*.py"]
[project_tests.build.compile]
command = "python3 -m compileall -q app"
```

```json
{"checks":[{"name":"unit","targets":["tests/test_feature.py"]}],"builds":["compile"]}
```

These are configuration examples, not inferred commands for an unknown project.
