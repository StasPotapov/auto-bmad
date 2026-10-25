# Reports to the human — rules and templates

Read at Step 4 (open questions file), at Step 5 and before the final epic
report. The same rules live in the instructions of the `auto-bmad:bmad-story-runner` agent type — it writes
the story report by them; here they are needed to build the epic report and to notice when the
subagent's text does not follow them.

The templates below are in English. Render headings and text in the run language (the
`language` field from `auto-bmad plan`). The machine marker lines (`STORY_DONE`,
`STORY_BLOCKED`, `WINDOW_STOP`) are never translated.

## Rules

The report is read by a human who **did not write this code and does not know how the project is built**.
The engine wrote it. So:

- **No engine or BMad jargon.** The words `spec`, `deferred`, `loopback`, `triage`,
  `severity`, `patch applied` do not go into the report. Write what happened in substance:
  "found a problem, fixed it", "found it, deferred it — here is why".
- **No internal names without an explanation.** You mentioned a class, a file or a
  function — next to it, say in one phrase what it is responsible for.
- **Short.** A story report — up to half a screen. An epic report — up to a screen.
  If the human needs a detail, they will ask separately.
- **Every "Needs attention" item follows one template**, otherwise it cannot be understood:
  1. **What is wrong** — one sentence, in plain language.
  2. **What it risks** — what breaks or what will be missing, and when it hits.
  3. **Options** — 2–3 of them, each with its cost in one line (how much work / what we lose).
  4. **Recommended** — one option and why exactly this one.
- **"How to check" is an instruction, not a description.** The human must be able to follow it
  without asking questions: which command to run, what to open, where to tap, what they should
  see if all is well. It cannot be checked by hand yet (no UI, no entry point) — say so
  in one line and name what the engine checked instead of the human (tests, a script).

**Do not fix** anything from "Needs attention" while writing the report — the human decides the size of this work.

## Template: story done

The section text comes from the subagent ready — show it as is under your own heading,
adding the line with the numbers from the machine header.

```markdown
## Story <id> (<N>/<M>) done: <title>

<the "What was done", "How to check", "Needs attention" sections from the subagent's answer>

Files changed: <FILES> · commit `<COMMIT>`

STORY_DONE: <id> commit=<COMMIT> files=<FILES>
```

Edit the subagent's text in two cases only: it broke the rules above (jargon,
unexplained names, a wall of text two screens long) — fix it in place; the header came broken —
add a line saying that the subagent broke down.

In Epic mode, under the report and before the `STORY_DONE` line — one progress line:

```
Epic progress: <N> of <M> done, <M-N> left.
```

The last line is a machine marker: an external runner that watches the stream reads it
to see which story was finished, with which commit. Print it **verbatim and last**,
without formatting or characters around it: `STORY_DONE: 3-2 commit=a1b2c3d files=7`.
In parallel mode it ends the report of each story of the wave.

## Template: story blocked

```markdown
## Story <id> blocked: <title>

### What got done
<1–3 sentences in plain language. Nothing got done — say so.>

### Where it stopped
- What happened: <the blocking condition in human language, without quoting the engine>
- Why it did not resolve itself: <one sentence>

### What can be done
- Options: <2–3 options, each with its cost in one line>
- Recommended: <option> — <why>

### State
- Code: <committed / not committed, the tree is clean or not>
- Left in the epic: <list of unfinished stories> (Epic mode only)

STORY_BLOCKED: <id>
```

The last line is a machine marker for an external runner, like `STORY_DONE`: verbatim,
last, without formatting.

## Template: run stopped by the window

Printed **only** when `time_budget` decided so — that is, `window.py` answered
`take_next: false` at Step 6 (or P6). You cannot invent a stop by time yourself:
you have no clock, and a story that was already started is always finished.

```markdown
## Run stopped by the window: epic-<N>

### What got done
Stories closed: <X> of <Y>.
- **<story-id> — <title>** (`<hash>`)
- ...

### Why it stopped
<The reason from the `reason` field in human language: so many minutes were left to the end
of the time window — less than the reserve a whole story needs. I did not take the next one:
it would have been cut off in the middle, and the work would have been lost together with the clean tree.>

### State
- The tree is clean, everything is committed, the last commit is `<hash>`.
- Left in the epic: <list of ids of unclosed stories>.
- The next run takes this same epic and starts with story <id>.

WINDOW_STOP: epic-<N> done=<X> left=<Y>
```

The last line is a machine marker; an external runner reads it to tell a normal
stop from a breakdown. Print it **verbatim and last**,
without formatting or characters around it: `WINDOW_STOP: epic-7 done=2 left=4`.

## Template: epic done

This is the main text of the whole run: often the human reads only this.

```markdown
## Epic <N> done: <epic title>

<1–2 sentences: what the program can do now that it could not do before the epic.>

Stories: <X> of <Y> · commits: <Z> · files changed: <N> (+<A> / −<B> lines)

### Done by story
1. **<story-id> — <title>** (`<hash>`)
   <one or two lines in plain language: what exactly appeared or changed>
2. ...

### How to check
<A common scenario of 3–6 steps that goes through the result of the whole epic:
what to launch, what to open, what to tap, what should happen.
If the epic has several independent parts — a short block for each.
Nothing to check by hand — say so directly and list what was checked automatically.>

### Needs attention
<Combined across all stories, duplicates merged, sorted by importance — first what
hits sooner. Each item by the template:

**<Short name of the problem>**
- What is wrong: <one sentence>
- What it risks: <what breaks or what will be missing, and when>
- Options: <2–3 options, each with its cost in one line>
- Recommended: <option> — <why>

Nothing left — one line: "Nothing, the epic closed clean.">

### Run statistics
<Three lines from `auto-bmad stats show --last 1 --repo .`: the stories line, the tokens per story line,
the review line — as is. The command answered with code 2 — skip the block.>

### What next
- Epic retrospective: `bmad-retrospective`
- Project statistics for all time: `auto-bmad stats show`
- Walk through the changes with a human: `bmad-walkthrough`

Open questions of the epic are collected in `<questions_file>`.
```

The run went in parallel — add two lines at the start: how many waves there were and how many merges
needed conflict resolution.

## Open questions file of the epic

Written by the `open_questions.py` script at Step 4, one section per story, and it accumulates
over the whole epic. The point is that decision points do not have to be collected from eight specs and from the scrolled
chat: one file, in git, with a link to the spec and the commit for each item. Its path is
`questions_file` from `auto-bmad plan`.

**What goes into it.** Exactly the text the subagent returned in the "Needs attention" section —
item for item, by the same four-line template (what is wrong → what it risks → options →
recommended). Do not retell it in your own words and do not shorten it: the human reads the file weeks later,
when the chat report is long gone. The language rules are the same as for reports: no engine jargon,
names of files and classes — with a one-phrase explanation; the run language.

**What it does not have.** Stories closed clean (they are visible from the counter in the header),
a retelling of "what was done" (that is in the report and in the spec) and fixes: the file's items are work whose size
the human decides.

A blocked story (`STATUS: blocked`) goes there too, marked "blocked":
the text is the "Where it stopped" and "What can be done" blocks from the subagent's report.

The section shape (the script builds it; do not edit the file by hand):

```markdown
<!-- story:5-3 -->
## Story 5-3 — transfers between family members as internal

Spec: [spec-5-3-transfers-between-family-members-as-internal.md](spec-5-3-transfers-between-family-members-as-internal.md) · commit `a1b2c3d`

**<Short name of the problem>**
- What is wrong: <one sentence>
- What it risks: <what breaks or what will be missing, and when>
- Options: <2–3 options, each with its cost in one line>
- Recommended: <option> — <why>

<!-- /story:5-3 -->
```
