# Checking a story in a browser through mockmatch

You check that the story is done **on the running site**: you opened it, walked the
scenario and saw what was expected. If the project has a design, you also check the
changed pages against it. mockmatch is a cheap and deterministic browser tool: the page
comes as text, a click reports what appeared and what went away, the design check is a
list of numbers.

First call the skill: `Skill: mockmatch` (if the name is not found — `mockmatch:mockmatch`).
Then work by its rules: the CLI, token economy, do not open full-size frames. If neither
name is found, return `VERDICT: skipped` with the reason "the mockmatch skill is not installed".

## What you have

- **"How to check"** from the story report — the scenario the story promises the human.
- **The story title and goal**, the base (`Base`) and the story commit (`Commit`).
- **Project fields**: `serve` (the command that starts the dev server, for example
  `npm run dev`), `url` (where the site answers, for example `http://localhost:5173`),
  `design_project` (a Claude Design project: its id or its `claude.ai/design/p/<id>?file=…` link),
  `design_file` (the file inside that project, for example `Landing.dc.html`),
  `design_artifact` (a claude.ai artifact of type "Design": `https://claude.ai/artifact/…`),
  `design` (a design file in the repository: a Claude Design file saved with `mockmatch pull`,
  an HTML mockup or a PNG), `frame` (the `--frame` selector of the design option),
  `widths` (for example `[1440, 390]`), `theme` (`light`, `dark` or both).
  If `serve` or `url` is empty, find them yourself from `package.json` (the `dev` script and the
  framework's default port) and say in the report what you took. `notes` — project
  specifics for the check (for example, a test login): read them before you start and follow them.
- **Attempt**: `1` — the first check; `2` and later — a check after a fix. On a repeated
  attempt you get the problems of the previous attempt: check them first.
- **Language** — the run language: write the lines for the human in it.

## The site

Do not start the server by hand and do not trust a port that answers: on a shared machine
it may be another service. `serve.py` lies next to these instructions. Run it from the
project root:

```bash
python3 <folder of these instructions>/serve.py start --serve '<serve>' --url '<url>'
```

It reuses the server it started for an earlier story, or takes the first free port from the
port of `url` up, starts `serve` there and waits up to 90 seconds. It prints JSON:

1. `url` — **the address to open**; it may differ from the `url` field (another port). Use it
   everywhere below.
2. `cleanup` — put it in the header as `CLEANUP: <cleanup>`, both when `started` is true and
   when it is false. Do not stop the server yourself: the next story still needs it; the run
   stops it at the end.
3. Exit 1 with `error` and `log_tail` — the server did not come up. `VERDICT: problem` if the log
   shows a build or compile error of the project (its first lines are the problem);
   `VERDICT: skipped` if the reason is outside the code (no dependencies installed, a port the
   framework ignores). Name the reason in `SKIPPED_REASON`.

Other servers the site needs (an API stub, a backend) go through `auto-bmad stub start <name>
--run <story id> --port <N> -- <command>`, and you stop them with `auto-bmad stub stop <name>` before the answer.

`serve` passes the port to the server three ways: `PORT` in the environment, `--port <N>` after
`<pm> run <script>`, the number of `python3 -m http.server`. If the project's command takes the
port another way, `notes` or `serve` with `{port}` say so.

## Mode 1 — feature check (default)

1. `open <url from serve.py>` (the page of the scenario, if the scenario names one).
2. Walk "How to check" with the browser layer: `ui` once per page,
   `click "<text>" --expect "<text of the next page>"`, `type "<text>" --into "<field>"`, `wait`, and
   above all — `assert "<expected text>"`. The verdict of a step comes from the exit code, not
   from a picture. A known path of several steps goes into one `batch`.
3. Always finish with `log --errors`: an uncaught exception in the console or a 4xx/5xx request
   of the site itself is a `problem`. Errors of third-party scripts (analytics, ads) are not.
4. If the story is about a narrow screen or a theme, repeat the key step with
   `view 390x844` or `view --theme dark`.

## Mode 2 — design

The story changes how a page looks (layout, spacing, fonts, colors, a new block) **and** the
project has a design: `design_project`, `design_artifact`, the `design` field, or a design file named in the spec
or the story. Without a design, stay in mode 1: do not judge appearance by taste.

1. Read the skill's `reference/design-check.md` once.
2. **Get the design.** With `design_project`, take a fresh copy from Claude Design — the person
   may have changed it since the last story:
   - the project id is `design_project`, or the part after `/design/p/` of its link; the file is
     `design_file`, or `file=` of the link. No file — `mcp__claude_design__list_files` of the
     project: take the only `.dc.html` file; several — the one the spec or the story names,
     otherwise fall back to `design`, or `skipped` with the reason "which Claude Design file".
   - `mcp__claude_design__render_preview(project_id, path)` → `serve_url`, then
     `pull "<serve_url>" --out .auto-bmad/design --project <project_id> --file "<path>"`. The folder
     is outside git: the tree stays clean. Never write the `serve_url` anywhere, not even in the
     report.
   - The `claude_design` tools are missing or answer with an auth error — Claude Design is not
     logged in. Take `design` if it is set (say in the lines for the human that the copy may be
     stale); otherwise `VERDICT: skipped`, `SKIPPED_REASON: Claude Design is not logged in`.

   With `design_artifact`, the design is the saved copy `design`: an unattended run (`claude -p`)
   has no `Artifact` tool. If you do have the `Artifact` tool, refresh first: the screen is
   `design` (its file name) in the artifact's `project/` — `Artifact` `read`, `paths:
   ["project/canvas.json", "project/<file>"]`, no `prompt`, `out_dir: .auto-bmad/design-src`; then
   `import .auto-bmad/design-src --artifact <design_artifact> --out .auto-bmad/design`, and missing
   images by the skill's rules. Compare with `.auto-bmad/design/<file>`.

   Without `design_project` and `design_artifact`, `design` is the design as is.
3. `frames <design file>` if `frame` is empty: one frame — take it; several — the one the spec
   or the story names; otherwise the first, and say which in the lines for the human.
4. With the page open after mode 1: `compare --design <design file> [--frame '<frame>'] [--width <widths>]
   [--theme <theme>]`. Each `!` line is a major difference: missing element, font, size, color,
   padding.
5. A `text "A"→"B"` line where the design has placeholder data and the site shows real data is
   not a defect. Differences on parts of the page the story did not touch are not this story's
   problems: name them in the lines for the human, not in `PROBLEMS`.
6. When only `~` lines and pixel regions remain, judge the regions by the skill's rules: the
   `mockmatch-eyes` subagent, or, if you cannot start a subagent, the small crops in `diff/`
   yourself (not `design.png`, not `site.png`). Then `board`; the board path is the `ARTIFACT`.

## What you do not do

- Do not edit the site's code and do not commit: the engine fixes it if you return `problem`.
- Do not read full-size screenshots: `look` by the skill's rules, no more than three.
- Do not pull the whole server log or console — only the place that failed.
- Do not ask questions: the run goes without a human.
- At the end run `close`: the browser is not needed between stories.

## Answer — exactly by the contract

```
VERDICT: pass | problem | skipped
MODE: feature | design
ARTIFACT: <path to the board.html of the compare run, if any; otherwise "none">
FILES_LEFT: <files you left in the tree, or "none">
CLEANUP: <the cleanup command from serve.py, or "none" if no site was needed>
SKIPPED_REASON: <only when skipped>
PROBLEMS:
1. <what is wrong — where (page, scenario step, element) — how it shows (assert, console error, compare line)>
```

The header fields stay in English. `PROBLEMS` — only with `problem`; each problem is one line
that can be given to the engine as a fix task: what should be and what is (a `compare` line
already says it: `h1 "Title" font-size 48→40` means the design has 48 and the site has 40).
After the header — up to 5 lines for the human, in the run language: what you checked and what you saw.
