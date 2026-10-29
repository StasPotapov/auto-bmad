# CLI backend

Use this mode when the project's resolved `execution.backend` is `cli`. The chat launches and reports;
the shared runtime owns the story queue and the native BMAD controller owns each story's lifecycle.

1. Take the exact story/epic and level from the user's request. An empty argument selects the next unfinished story.
   The read-only `plan` command shows the queue and role profiles. Missing profiles or capabilities are blockers;
   never guess a model ID, replace an adapter or disable a check to make the run succeed.
2. When the user asks to run that scope, execute:

   ```text
   python3 <this-skill-directory>/scripts/run.py --repo <absolute-project-root> --arg "<user arguments>" --allow-model
   ```

   This may consume the configured models' quota and creates local commits. The user's request to execute
   this story/epic authorizes this run; do not ask again for the same scope. If they asked only for a plan, stop after `plan`.
3. Wait for that command. If the shell tool yields a session handle, join it. Do not start another run because
   the first command is still running. For progress or cancellation use the returned controller session:

   ```text
   python3 <this-skill-directory>/scripts/run.py status --session <session.json>
   python3 <this-skill-directory>/scripts/run.py cancel --session <session.json>
   ```

4. Report `run_completed`, completed and remaining stories, test/check outcomes, concrete questions,
   and the worktree/branch. A failed role, `needs_attention`, `window`, or partial queue is not success.
   A configured hook may require a human answer; show its saved question rather than inventing an answer.
   Use the plan's language, or the user's language if unset. Keep the report short.

The CLI creates a unique `codex/auto-bmad/...` branch and an isolated worktree from the source's exact clean HEAD.
The source branch stays unchanged. Epics run sequentially, with a fresh controller per story, synchronized
sprint tracking and the existing wait/dependency policy. Time-window checks happen between stories.
`--timeout` is a separate total hard limit. No automatic merge, push, worktree deletion or crash resume occurs.
Explicit `--parallel-fast`, `--width` and `--no-worktree` are unsupported in this backend.

The runtime launches roles through adapters and configured profiles. Codex execution has a live single-story
validation. Kimi and Claude CLI adapters currently fail closed until their permission/result contracts are
validated; native Claude Code keeps the separate legacy path. Agent-based external verifiers and conditional
review layers remain unsupported. Report these capability limits without switching to manual implementation.

This skill must ship with the plugin's `scripts/` and `bin/`; installing only a copied `SKILL.md` is insufficient.
For local development, link the entire skill folder to the source checkout. Do not edit installed plugin caches.
