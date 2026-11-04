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
worktree and `completed` journal. No model CLI was launched. That validation did not measure native tokens. The local rollout collector added later requires an exact root thread/turn binding; see ../en/stats.md.

That validation used persistent controllers with children. Current scheduled runs use
finite checkpoints and root-dispatched roles: a four-slot host can fit the root and three
roles for independent stories. Automated ledger fixtures cover that capacity and dependency
barriers; the historical serial live acceptance does not establish a full parallel epic.

## Orchestration overhead — 2026-11-04

Native journal fixtures cover all-or-none event batches, idempotent retries, repair budgets,
slot-order admission, independent-review evidence and compact summaries with stale/unknown
tree markers. Legacy single-event/full-state calls remain supported. Summary output is a
navigation view, not a completion verdict; full reports and check diagnostics remain on disk.
New native plans use finite checkpoints even for one story; existing journals retain their
topology. Controller handoffs preserve workflow state, findings, counters and evidence while
starting each new checkpoint with isolated context.

The Codex adapter requires interruptible event waiting and silence on empty timeouts. This is
a host orchestration contract, not a Python event loop or a change to the app's timer limits.
Static instructions and journal fixtures do not demonstrate zero wakeups in a production run
or measured token savings. A fresh installed-skill discovery and a complete production epic
using this revision have not been validated here.
