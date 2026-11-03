---
name: bmad-reviewer
description: Service type for the bmad-build-auto pipeline — a diff review layer at the `--deep` level, the smartest of the three reviewer types. Do NOT pick it for ordinary tasks and do not use it instead of /code-review: it exists only to set the model and effort of the BMad engine's reviewers (on purpose a different model than the code author's — a fresh look catches what one model's shared blind spots miss). Its cheaper siblings are bmad-reviewer-mid and bmad-reviewer-lite. It is started by an instruction in _bmad/custom/bmad-build-auto.user.toml, not by the model's choice.
model: sonnet
effort: high
---

Read and follow `../prompts/roles/reviewer.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
