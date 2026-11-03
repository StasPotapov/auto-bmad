---
name: bmad-triager
description: Service type for the bmad-build-auto pipeline — triages the review findings of one pass (step-04 Classify, steps 1–3 — verdict, grouping, route) in a clean context and changes nothing. Do NOT pick it for ordinary tasks and do not use it instead of /code-review: it exists only so that triage does not re-read the story session's large context on every step. Model Opus 5.5, effort high: verifying a finding against the code needs the same judgement as the session that used to do it. It is started by an instruction in _bmad/custom/bmad-build-auto.user.toml (fact I, auto-bmad writes it when `[run] triage_subagent = true`), not by the model's choice.
model: opus
effort: high
---

Read and follow `../prompts/roles/triager.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
