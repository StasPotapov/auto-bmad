---
name: bmad-verification-gap
description: Check verification coverage and missing regression evidence using the original Verification Gap payload.
model: sonnet
effort: medium
---

Read and follow `../prompts/roles/verification-gap.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
