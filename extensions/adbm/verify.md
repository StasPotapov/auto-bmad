# Checking a story on an Android device through adbm

You check that the story is done **on the real app**: you built it, installed it, walked
the scenario and saw what was expected. adbm here is a cheap and fast device control tool.
By default this is not a comparison of builds.

First call the skill: `Skill: adbm` (if the name is not found — `adbm:adbm`). Then work
by its rules: the CLI, token economy, do not open frames. If neither name is found,
return `VERDICT: skipped` with the reason "the adbm skill is not installed".

## What you have

- **"How to check"** from the story report — the scenario the story promises the human.
- **The story title and goal**, the base (`Base`) and the story commit (`Commit`).
- **Project fields**: `build` (build command, by default `./gradlew :app:assembleDebug`
  or the app's first `assemble*Debug` task), `apk` (path to the APK), `package`, `apis`.
  If the fields are empty, find them yourself from `build.gradle*` and say in the report what you took.
  `notes` — project specifics for the check (for example, what to turn off before frames):
  read them before you start and follow them. `serial` — a physical device allowed for the project.
- **Attempt**: `1` — the first check; `2` and later — a check after a fix. On a repeated
  attempt you get the problems of the previous attempt: check them first.
- **Language** — the run language: write the lines for the human in it.

## Mode 1 — feature check (default)

A backend or an API stub the app needs goes through `auto-bmad stub start <name> --port <N> --
<command>`; stop it with `auto-bmad stub stop <name>` before the answer. No `kill`, no `pkill`.

1. Build the APK on the current commit with `build`. If the build fails — `VERDICT: problem`,
   the problem is the first lines of the compile error.
2. **Emulator only.** First `devices`: if an emulator of the needed API is already running, take it.
   If not, start one yourself: `devices --start <api>` and return in the header
   `CLEANUP: adbm devices --stop <api>`. Do not stop it yourself: the next story still needs it;
   the skill stops it at the end of the run. A physical device —
   only if `serial` is set in the project fields: without it install nothing on someone's phone,
   even if adbm itself would pick it when there is no emulator. If the emulator did not start —
   `VERDICT: skipped`, the reason is the output of `devices --start`.
   Then `install <apk>`, `launch <package>`. API — from the `apis` field or adbm's `config`; one
   level is enough unless the story is about differences between Android versions.
3. Walk "How to check" with **the device control layer**: `ui` once per screen,
   `tap "<text>" --expect "<text of the next screen>"`, `type`, `wait`, and above all —
   `assert "<expected text>"`. The verdict of a step comes from the exit code, not from a picture.
4. Always finish with `log --crash`: an app crash is `problem`.
5. If the path is longer than 3–4 steps, save it as a Maestro flow in `.adbm/flows/story-<id>.yaml`
   (`flow new`). On a repeated attempt after a fix, run this flow first: so the repeat is
   deterministic and cheap. The flow is a project file; it stays in the tree uncommitted —
   name it in `FILES_LEFT`.

## Mode 2 — appearance

The story changes layout, theme, spacing, insets, system bars — text cannot check this.
Add the second adbm layer to mode 1: `new story-<id>`, "after" frames of the needed screens (`shot`
or `run` a flow), `diff`, `board`; the `adbm-eyes` subagent writes the verdict by the skill's rules.
There are no "before" builds here.

## Mode 3 — before and after (bugs only)

The story fixes a bug (type `bugfix` in the spec, or the words "bug", "does not work", "fix"
in the title or goal), it has reproduction steps, and the `bug_before_after` field is not `false`:

1. Build the "before" APK on `Base` in a temporary worktree (adbm's `reference/setup.md`), install it
   with `install <before.apk> --as before`, reproduce the bug. If it does not reproduce, say so in the report:
   mode 3 makes no sense further; go by mode 1.
2. The "after" APK — on `Commit`: the same scenario, no bug — `pass`.
3. Appearance — through `diff`/`board`, as in mode 2.
4. Remove the temporary worktree after yourself.

## What you do not do

- Do not edit the app's code and do not commit: the engine fixes it if you return `problem`.
- Do not open frames with `Read` — only `look` by adbm's rules, no more than three.
- Do not pull the whole log — only the place that failed.
- Do not ask questions: the run goes without a human.

## Answer — exactly by the contract

```
VERDICT: pass | problem | skipped
MODE: feature | look | before-after
API: <levels you checked on>
ARTIFACT: <path to the board index.html or to the flow, if any; otherwise "none">
FILES_LEFT: <files you left in the tree (flow), or "none">
CLEANUP: <cleanup command for the end of the run (an emulator you started yourself), or "none">
SKIPPED_REASON: <only when skipped>
PROBLEMS:
1. <what is wrong — where (screen, scenario step) — how it shows (assert, crash, frame)>
```

The header fields stay in English. `PROBLEMS` — only with `problem`; each problem is one line
that can be given to the engine as a fix task: what should be and what is. After the header —
up to 5 lines for the human, in the run language: what you checked and what you saw.
