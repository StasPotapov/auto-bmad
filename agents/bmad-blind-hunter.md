---
name: bmad-blind-hunter
description: Find concrete defects in the whole story diff independently, using the original Blind Hunter payload and its context restrictions.
model: sonnet
effort: medium
---

Read and follow `../prompts/roles/blind-hunter.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
