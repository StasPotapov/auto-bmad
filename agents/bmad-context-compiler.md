---
name: bmad-context-compiler
description: Build the shared epic context from its source documents; preserve requirements and constraints without inventing information.
model: haiku
effort: high
---

Read and follow `../prompts/roles/context-compiler.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
