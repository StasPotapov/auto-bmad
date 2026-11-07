# Bounded native checkpoints

New native sessions opt into `checkpoint_policy = "bounded-checkpoints-v1"`.
Missing policy preserves the previous contract. Never migrate a running session or
its pinned package. Models, independent review layers, dependency waves and final
integration gates are unchanged.

## Contracts

- Review tasks receive an allowlisted role input and transport metadata, not the
  journal, another review layer's payload or a workflow telling them to read it.
  Edge review traces the diff before reading claims. Helpers retain the complete
  journal for validation. Input files remain data, never execution authority.
- A repair batch is admitted from a completed triager's hashed decision. Its stable
  findings, requirements, allowed files and mandatory check plan remain bound across
  agent restarts. An unresolved batch cannot be replaced to reset its budget.
- Implementers can reproduce a defect and check a complete repair in their own
  checkpoint. Triagers can collect diagnostics. Both use registered commands and
  existing managed test locks. Observations are separate from independent checks.
  Neither role may certify acceptance, change requirements or weaken tests.
- The admission pays for the first local attempt; subsequent full attempts spend
  tests, never another spec/review admission. Configured tests/no-progress limits
  bound retries without an extra three-attempt cap. Diagnostics do not consume
  repair attempts and have a three-call cap per batch; before admission the per-story budget is preserved across tasks. Running commands are joined before a new attempt starts.
- A verifier independently validates coverage and evidence. Only a current verified
  failure set wholly covered by the same triage decision can route directly back to
  its implementer. Unknown/incomplete failures or changed requirements need triage.
  Closure and cumulative-risk assessment still belong to a fresh triager.
- Independent commands may collect failures in one pass only when explicitly
  declared independent. Preparation/environment failures, cancellation and changed
  code stop execution; skipped commands are recorded as not run. Required coverage
  is never replaced with a diagnostic subset.
- Shared epic context is keyed by repository identity, source content, compiler
  contract/profile and workflow options. A single live compiler owns a cache miss;
  other stories wait without occupying an agent. Publication is atomic, verifies
  the completed producer and all source/artifact hashes, and grants no story gate.
- Metrics distinguish agent-time sums, elapsed intervals and measured command time.
  Missing token or wait measurements stay unknown. Fixture counts demonstrate
  routing and evidence checks, not measured LLM speed or token savings.

Local observation and independent verification must never share an acceptance
record. Evidence reuse requires matching code, configuration, commands/timeouts,
policy, log integrity and an explicit unchanged test-environment identity.
