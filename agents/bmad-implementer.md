---
name: bmad-implementer
description: Service type for the bmad-build-auto pipeline — implements a story from a ready spec. Do NOT pick it for ordinary tasks: it exists only to set the model and effort of the BMad engine's implementer subagent. It is started by an instruction in _bmad/custom/bmad-build-auto.user.toml (auto-bmad writes it), not by the model's choice.
model: opus[1m]
effort: medium
---

Read and follow `../prompts/roles/implementer.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
