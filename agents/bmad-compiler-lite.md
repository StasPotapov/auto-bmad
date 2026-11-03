---
name: bmad-compiler-lite
description: Service type for the bmad-build-auto pipeline — builds `epic-<N>-context.md` from the epics file and the planning documents (step step-01, prompt compile-epic-context.md). Do NOT pick it for ordinary tasks: it exists only to set the model and effort of this subagent. Model Haiku 5.5, effort high: the work is closed — read the documents and compress what the epic needs into 800–1500 tokens, with no code and no bug hunting; every story of the epic reuses the file, so effort is no lower than high. It is started by an instruction in _bmad/custom/bmad-build-auto.user.toml (fact G, auto-bmad writes it), not by the model's choice.
model: haiku
effort: high
---

Read and follow `../prompts/roles/compiler-lite.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
