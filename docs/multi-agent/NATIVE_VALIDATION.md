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

## Thin root and interruptible waiting — 2026-11-04

New `thin-root-v1` sessions separate all substantive work into fresh finite native tasks,
including bootstrap, diagnosis, delegated revalidation, checks/test waits and integration.
Root routing uses persisted bounded task envelopes; existing journals and pinned runtimes
retain their original contract. These source contracts do not establish a full live epic.

One actual root `collaboration.wait_agent(timeout_ms=180000)` started at 15:59:01 UTC and
returned at 16:01:16 UTC on an agent message with `timed_out: false`. No intermediate
minute wake/model call occurred. This verifies an interruptible wait beyond 60 seconds on
that host, not an entire epic, zero future timeout wakeups, or measured token savings.
The live schema supports up to 3600000 ms; explicit hard host caps remain mandatory.
Generic guidance about blocking shell waits is not that event API's technical ceiling.

## Bounded checkpoints validation

`tests/test_bounded_checkpoints.py` exercises sanitized reviewer inputs, old-policy
compatibility, red/fix/green in one implementer, independent acceptance rejection,
persistent budgets, scope/spec protection, known/unknown failure routing, explicit
independent command collection, shared context reservation/publication/invalidation,
and overlapping timing. Fixtures use temporary repositories; they do not alter a
live project. This validates routing and gates, not real model speed/token savings.

The comparable local-error fixture records 5 legacy-policy checkpoints versus 2
bounded-policy checkpoints (42403 versus 12666 task.json bytes in this run). It
executes 3 versus 6 command invocations: self-checks cost extra commands while
removing role handoffs. This is not a model latency/token benchmark. No live epic
pilot of the new policy has been completed; active external runs are excluded.

Final source validation: 642 unittest scenarios passed, including 30 bounded-policy
cases. Astra/high bug review and Sol/medium complex crosscheck revalidated their
reported findings. The fixture also covers actual two-phase land (unchanged main
until terminal gate acceptance), paid local-check handoff to a verifier waiter,
failed-producer recovery and blocked-context publication rejection.
