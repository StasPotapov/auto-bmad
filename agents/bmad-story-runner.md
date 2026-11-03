---
name: bmad-story-runner
description: Service type for the auto-bmad skill, or a caller's own skill that runs one task — runs ONE story (or one task) through the bmad-build-auto engine in an isolated context. Do NOT pick it for ordinary tasks: it exists only so that the engine's context (spec, diff, review layer reports, triage) lives and dies inside the subagent instead of piling up in the orchestrator's context. It is started by an instruction from this plugin's auto-bmad skill or from a caller's own skill, not by the model's choice.
model: opus[1m]
effort: medium
---

Read and follow `../prompts/roles/story-runner.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
