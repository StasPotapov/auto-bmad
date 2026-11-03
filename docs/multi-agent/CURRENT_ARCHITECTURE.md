# Native chat orchestration

The main chat owns the epic queue, agent capacity, progress and blocker decisions.
Stories run in native subagents; implementation and independent review use native
roles with explicit configured models and effort. Python never launches a model.

The operational contract is [NATIVE.md](../../skills/auto-bmad/NATIVE.md).
`native_session.py` stores validated progress and evidence; `engine.py` renders the
BMad workflow. Existing worktree, test, verification, sprint and hook utilities remain.

The retired CLI queue and transport have been removed. Old run journals are historical
records, not resumable native sessions. Keep the previous complete runtime in a private
backup to inspect or explicitly recover those runs. Never convert them silently.

Native permissions are inherited from the main chat. Worktree assignment and reviewer
no-edit instructions are not separate operating-system sandboxes. Session records are
cooperative local records, not a security boundary against an agent with write access.

Validation evidence and untested surfaces: [NATIVE_VALIDATION.md](NATIVE_VALIDATION.md).
