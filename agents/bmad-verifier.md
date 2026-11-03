---
name: bmad-verifier
description: Service type of the auto-bmad plugin — checks ONE finished story after the engine's commit, following check instructions from the config (for example, on an Android device through adbm or in a browser through mockmatch). Do NOT pick it for ordinary tasks: the auto-bmad skill starts it at the check step, so that frames, logs and the build live in the subagent's context and only the verdict comes back up.
model: sonnet
effort: medium
---

Read and follow `../prompts/roles/verifier.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
