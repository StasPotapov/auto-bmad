# Claude Code native adapter

This adapter supplies native tool/waiting behavior; role tasks and result contracts live
in `prompts/roles/`. The main auto-bmad chat orchestrates the run. Native model and effort
come from Claude frontmatter and its per-client overrides, never Codex model aliases.
`Skill: bmad-build-auto` invokes the engine in the story-runner's context. `Agent` launches
a child, and `SendMessage` forwards progress/results. Resolve all resources from the full
plugin root, not the project cwd. AI Workspace is optional delivery, never a runtime.

For story-runner only, preserve the native isolation contract below. These commands are
specific to Claude's harness-created worktree; Codex uses its own prepared worktree and
must never apply this initialization/reset to an existing branch.

## If the prompt says `Isolation`

The run is parallel: your story goes in a separate copy of the repository, so that it does not
fight neighbouring stories for the working tree. The directory was already given to you at
launch; you do not need to enter anything — and **you cannot enter another worktree, even if
you are given its path**: `EnterWorktree` answers with success, but Bash refuses to run commands
there ("Refusing to run it there") — the sandbox is pinned to the directory the harness gave you.
Work in your own.

First:

1. **Make sure you really are in a worktree and not in the main tree:**

   ```bash
   git rev-parse --git-dir           # a worktree has its own, inside .git/worktrees/<name>
   git rev-parse --git-common-dir    # the repository's shared .git
   ```

   **If the paths match, isolation did not work.** In the main tree git returns the same
   for both queries; in a linked worktree the first points inside `.git/worktrees/<name>`,
   and the second to the shared `.git`. Compare exactly these, not your root with the path
   from the `Main repository` line: `--show-toplevel` returns the resolved physical path,
   and on a symlink or on `/tmp` → `/private/tmp` it differs from the one you were sent even
   in the main tree — the check would decide you are in a worktree, and you would commit
   into the shared tree.

   If they match, stop at once: return `STATUS: blocked` with the reason "isolation did not
   give a worktree; working in the main tree is not allowed". Change nothing and do not
   commit — parallel stories would overwrite each other.

2. **Set the branch.** What to do depends on the `Base` line in the prompt.

   **Base is a sha** (a normal start of a story from scratch):

   ```bash
   git checkout -B <branch from the prompt> <sha from the prompt>
   ```

   This step is required, not a formality: the harness branches the worktree by its own
   setting (usually from `origin/<default-branch>`), and without this command you can end up
   on code other than what the previous stories of the epic built.

   **Base is a branch name `auto-bmad/<story-id>`** (resuming an interrupted story:
   the spec and commits are already in this branch; the orchestrator removed its directory):

   ```bash
   git checkout <branch from the prompt>
   ```

   Here it is exactly `checkout` without `-B`: with `-B` you would reset the branch and lose
   the work. After the switch, check `git log --oneline -3` — the commits of the previous run
   must be there. If they are not, do not silently start from scratch: return `blocked` with
   this reason.

3. **Copy the local BMad settings** — the level profile, `_bmad/config.user.toml`
   and other `*.user.*` files are in `.gitignore`, and a fresh worktree does not have them.
   Without `config.user.toml` the engine fails at render (`missing config value`):

   ```bash
   auto-bmad worktree seed --from <main repository> --repo .
   ```

   If `profile_copied: false`, say so in the report: the engine runs on the project settings,
   and the run level is not applied.

4. Then everything goes as usual. The engine's commits land in your branch — that is intended.

### In any case

Do not leave the worktree, do not switch branches beyond step 2, do not merge, do not touch
the main tree or other branches. The orchestrator merges the branches. Do not call
`ExitWorktree` or `EnterWorktree` — the first gives away your directory, and the second
is useless (see above).

## How to wait for subagents

`Agent` here is asynchronous: the call returns control at once, and the result comes
as a notification that resumes the run by itself. The engine spawns subagents itself —
wait for them like this: all launches of a step in one message → end the turn with one line
about what you wait for → the notification wakes you.

**Idle calls to hold the turn are forbidden**: `echo`, `sleep`, reading the same file again,
`git status` in a loop. The subagent does not finish faster because of them, and the run
goes into a loop of a hundred steps and burns the context.

**Tests are not waited for like subagents.** The project tests run only through
`auto-bmad test` (the test runs policy of the engine profile): a foreground Bash call that
waits by itself and answers `verdict: running` when the tests outlive it — then the same call
again. Never `pgrep`, `ps`, `lsof` or `sleep` to watch test processes: a test run left behind by
a subagent is waited for by the same `auto-bmad test` call, it holds the folder's lock.
