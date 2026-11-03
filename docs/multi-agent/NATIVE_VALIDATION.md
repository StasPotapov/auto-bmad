# Native adapter validation — 2026-11-03

This is local validation of the 2.0.0 source, not a published release or a claim
that every host/device integration has been exercised.

| Surface | Evidence | Limit |
|---|---|---|
| Codex native BMad story | Live synthetic story: rendered BMad workflow, context compiler, implementer, three independent review agents, managed tests, story commit, tracking commit, journal `complete` and `finalize` | One story, no device/browser or full production epic |
| Main-chat control | Live phase messages and agent IDs recorded in the passive journal; two reviewers overlapped within the granted slots | Does not establish unattended recovery after app termination |
| Recovery and gates | Automated fixtures: repair budgets, stale evidence, changed config/snapshot/branch, cancellation, competing-session resume, finalization and explicit note policy | Controlled fixtures, not simulated application crashes |
| Client portability | Both Codex and Claude planning/doctor tested with trap model executables; separate client settings and repeated setup tested | Claude native model execution was not available for this validation |
| Independent source review | Astra/high bug review and Sol/medium contract/documentation review; confirmed findings corrected and rechecked | Local source scope |

The live fixture normalized whitespace in a pure Python function, preserved an unrelated
module, passed its tests and all three active BMad review layers, and ended with a clean
worktree and `completed` journal. No model CLI was launched. Native token accounting
remains unavailable unless the host provides measured per-agent usage.

Multi-story native scheduling is capacity-limited: a main chat plus two controllers must
still leave slots for their children. The serial live acceptance does not establish a
full parallel epic; validate the actual host capacity before increasing wave width.
