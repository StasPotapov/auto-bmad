---
name: bmad-edge-case-hunter
description: Find missed edge cases and failure paths using the original Edge Case Hunter payload.
model: sonnet
effort: medium
---

Read and follow `../prompts/roles/edge-case-hunter.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
