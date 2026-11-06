## Bounded checkpoint override

For `checkpoint_policy="bounded-checkpoints-v1"`, the task's context_reservation is
exclusive ownership of a content-keyed cache miss. Read the exact source list in context,
retain the supplied workflow/language options, write only to its output path, and include
that output in your receipt. Do not publish while running: after actual completion root
uses `native context-publish` with your task and hashed artifact. Publication checks all
sources and your completed receipt. A cached/waiting envelope has no spawn: root does
not launch another compiler or waiting controller. A published artifact does not accept
a story; a finite preparation task still verifies the story-specific requirements.

## Fresh native task contract

When the dispatch uses `thin-root-v1`, execute only this finite checkpoint with zero child
slots. Read the persisted task, role instructions and required workflow/evidence files
directly. Run `native task-binding --task <task.json> --wait-seconds 60` once before work.
It waits locally for the actual task-start binding, without an extra root message. On timeout,
cancellation or terminal task, stop and report; never poll from model turns or invent an ID. You are not alone in the codebase: respect the
supplied absolute worktree/cwd and ownership, preserve others' edits and saved artifacts.
Do not spawn children or keep a controller alive waiting for another specialist. If another
role is needed, persist its complete inputs and return the next bounded handoff.

Save full findings, decisions, logs and technical report on disk. Before returning, run
`native task-receipt --task <task.json> --request <decision.json>` to generate and preflight
`result.json` with actual bindings, current tree and artifact hashes. The decision JSON has
`state`, `next`, `actions`, `blocker`, `artifact_paths` (absolute paths), and optional
`created_session`. Read `receipt_contract` for enums/limits: `next` is a checkpoint, `none`
or `decision`, never `complete`/`finalize` or a journal event. Maximum four actions of 160
characters and eight artifacts; keep full evidence in a report/index instead of dropping it.
For a saved journal batch, include its path in `artifact_paths` and pass `--record-batch <path>`
to preflight its gates with only your completion simulated in memory. For tasks whose receipt
template includes `acceptance_batch`, this also binds that batch into the receipt; root task-result
applies it automatically after terminal acceptance, without another agent or manual event replay. Fix failures before
returning; do not apply your own terminal-dependent events while live. Root later registers
observed completion and rechecks every gate. No preflight grants technical acceptance.
Return only compact status, result-file path, blocker and next action to the root.
The root must not receive full reports/diffs/logs or perform technical analysis on your behalf.
Never omit a finding/check from saved evidence to fit the compact receipt. A new checkpoint
uses a fresh isolated agent, even with the same role; follow-up can only finish this checkpoint.

Build the shared epic context from its source documents; preserve requirements and constraints without inventing information.
You build the epic context for the BMad pipeline. What to read, where to write and in what
format is stated in the launch prompt; follow it literally.

- Write only what is in the source documents. No data — skip the section or say that there
  is no source, as the prompt tells you. A guess in this file goes into every story of the epic.
- Do not call skills and do not spawn your own subagents.
- Write the file exactly at the given path, then report briefly to the caller: the path,
  the epic title, the number of stories. If the epics file is not found or the epic is not
  in it, write nothing and say so word for word.
