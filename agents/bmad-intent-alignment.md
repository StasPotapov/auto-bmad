---
name: bmad-intent-alignment
description: Compare the implementation with the authoritative intent and acceptance criteria using the original Intent Alignment payload.
model: haiku
effort: high
---

Read and follow `../prompts/roles/intent-alignment.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
