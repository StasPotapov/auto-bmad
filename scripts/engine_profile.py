"""Native host adaptation of the shared BMAD instructions; never starts a model."""

import json
import tomllib

import write_profile as legacy

TRANSPORT_PREFIXES = ("Model policy", "Subagent execution", "Context-compilation policy", "Triage delegation",
                      "Independent repair budgets")


def build(level, triage_subagent=False, test_command=None, repair_budget=None):
    # Native triage always uses a finite specialist; the legacy opt-in must not
    # inject controller-side fallback instructions into a fresh native profile.
    original = tomllib.loads(legacy.build(level, triage_subagent=False, test_command=test_command,
                                        repair_budget=repair_budget))
    workflow = original["workflow"]
    facts = [fact for fact in workflow["persistent_facts"] if not fact.startswith(TRANSPORT_PREFIXES)]
    facts = [fact.replace('as its own Bash call with `timeout: 600000`',
                          'as its own foreground command through the host command tool')
             .replace('never with `run_in_background`', 'never as a detached command')
             .replace('in the foreground as its own Bash call with `timeout: 600000`',
                      'in the foreground through the host command tool') for fact in facts]
    # Shared quality rules retain their substance; native checkpoints assign
    # their technical decisions to specialists, never to the dispatching root.
    facts = [fact.replace("the orchestrator's closure check", "a fresh triager's closure check")
             .replace("may be applied by the controller", "may be applied by the assigned implementer")
             .replace("Only the orchestrator may accept", "Only a fresh triager may accept")
             .replace("the orchestrator checks every closure row", "a fresh triager checks every closure row")
             .replace("the orchestrator's current-code validation", "the completed triager's current-code validation")
             .replace("when you launch the `blind-hunter` review layer", "when preparing the `blind-hunter` review handoff")
             .replace("for the orchestrator to persist in the epic's open-questions file",
                      "through the root, after persisting it in the epic's open-questions file")
             for fact in facts]
    budget = legacy.REPAIR_LIMIT if repair_budget is None else repair_budget
    facts.append("Native repair budgets per story run: " + json.dumps(budget, sort_keys=True) + ". "
                 "A finite triager owns technical stop/continue recommendations; the root routes them and the "
                 "durable native session owns counters. Before a repair batch return a saved repair event with "
                 "kind spec, review or tests for the root to apply mechanically. "
                 "Do not reset counters on a new agent, pass, resume or changed error text. "
                 "Test failures use tests budget, code findings use review, requirement/spec corrections use spec. "
                 "Fix all known failures in the admitted batch before rerunning the failed checks; do not weaken checks. "
                 "Count consecutive test attempts without a pass or a strict reduction of known failing IDs; "
                 "stop at no_progress. Environment, access and permission failures are reported to the main chat "
                 "with concrete evidence; never bypass them or mislabel them as code repairs. "
                 "A story agent's blocked result is a request for an orchestrator decision, not authority to cancel the epic.")
    routing = {layer: layer for layer in ('blind-hunter', 'edge-case-hunter',
                                          'intent-alignment', 'verification-gap')}
    facts.append(
        "Native host transport policy for thin-root-v1. This overrides shared whole-story controller loops, "
        "Claude-specific Agent/Task/Skill launch and waiting instructions. The main chat is the dispatch-only "
        "root. Each specialist reads this rendered BMAD workflow and performs only its assigned finite checkpoint. "
        "Workflow references to this session mean the assigned specialist, never the root. When another role "
        "or checkpoint is needed, save the exact handoff and return; do not advance through its work yourself. "
        "Each task has zero child slots: specialists never spawn children or wait for downstream agents. "
        "The root alone uses collaboration tools to dispatch every new checkpoint in a fresh isolated context "
        "with fork_turns=none, the manifest's explicit model and effort (reasoning_effort in Codex), absolute "
        "worktree, file ownership and shared role prompt path. Preserve other agents' edits. "
        "Follow-up is only for unfinished work within the same task; a new checkpoint always gets a fresh agent. "
        "Missing capabilities are reported, never replaced by codex exec, a CLI model or Python queue. "
        "Only the root waits for native agent events with wait_agent under the host's interruptible wait limits. "
        "A finite verifier owns command-session/test waiting. No sleep loops, idle polling or timer-only reports. "
        "Return one bounded receipt with saved artifact paths, hashes, next-role inputs and any concrete blocker; "
        "send extra messages only for material transitions, blockers or required decisions. "
        "The root never reads source, diffs, full reports, test logs or rendered workflows, never runs or waits "
        "for tests, and never decides technical acceptance or semantic revalidation. It registers actual host "
        "agent IDs and terminal states, routes bounded receipts, and mechanically applies saved journal batches. "
        "Count the root and every active/waiting task against the global host capacity before dispatch. "
        "Batch independent reviewers when slots are scarce; never omit a required layer. "
        "Implementation uses role implementer with the original handoff and the spec as its source of truth. "
        "Review layer mapping: " + json.dumps(routing, sort_keys=True) + ". "
        "Each review-layer ID is its own configured subagent at every level; pass that exact profile. Unknown custom layers require explicit support, never a generic reviewer fallback. Keep original review context "
        "restrictions: never leak another layer's findings or implementation claims into a blind review. "
        "All required results must arrive before triage; a failed/missing result is not a clean review. "
        "Subagents share parent permissions; a no-edit instruction is not a separate read-only sandbox. "
        "Only one agent writes a story worktree at a time. Implementation/review tasks never merge branches "
        "or update sprint tracking. A fresh story-runner explicitly assigned integration/finalization owns "
        "merges, tracking and story-finish within its scope. No task may push, enlarge budgets or take another "
        "story outside its dispatch scope.")
    facts.append("Native completion policy. Keep the original baseline_revision throughout every repair and "
                 "review the whole story diff initially. Once fixes stabilize, repeat independent review only "
                 "for extensive or risky cumulative changes; otherwise a fresh triager inspects the cumulative "
                 "delta and all closure rows and saves targeted revalidation evidence. Bind exact story, layer, "
                 "source_tree, target_tree and evaluated_by to the completed registered triager ID, never "
                 "main-chat. Conditional review applicability needs saved JSON from a completed registered "
                 "story-runner or triager for the exact story, layer, condition and current tree. Preserve "
                 "original independent reports, all finding dispositions and mandatory current checks. "
                 "A finite verifier runs native session check and owns test launch, managed waits and failure "
                 "collection. A fresh finalization story-runner inspects the evidence, done spec, clean committed "
                 "tree, tracking and ancestry gates. It saves the complete/finalize record-batch request and "
                 "returns ready. The root first observes host completion and registers task-result, then "
                 "mechanically applies the saved batch. A live finalizer must never complete/finalize itself "
                 "while its agent remains active. A triager likewise returns its saved decision batch before "
                 "the root registers its completion and applies that batch. Gate rejection requires a fresh "
                 "specialist; the root must not investigate evidence or self-certify acceptance. "
                 "Do not report a story done merely because implementation or an agent process finished.")
    facts.append("Native context compilation: when the cache needs rebuilding, return the original "
                 "compile-epic-context payload for the root to dispatch to role context-compiler with its own "
                 "manifest model/effort at every level. A fresh preparation story-runner verifies the written "
                 "output as BMAD directs. Reuse valid cached context.")
    facts.append("Native triage delegation: at every level and regardless of the legacy triage_subagent setting, "
                 "the root dispatches a fresh role triager for step-04 Classify, diagnosis and revalidation. "
                 "It reads the prepared profile, ALL original active-layer reports, spec, baseline and evidence. "
                 "Preserve one row per finding, screening/context economy, Code repair routing policy and "
                 "concrete closure evidence. The triager persists technical verdicts and log rows, then returns "
                 "one complete repair handoff for the implementer; it never patches implementation or starts "
                 "downstream roles. Actual requirements conflicts go through the root to the user.")
    facts.append("Native verification ownership: the test-run policy applies only to the finite verifier "
                 "assigned checks/test-wait. Other checkpoints return required commands and saved evidence "
                 "references for dispatch. The verifier preserves managed test locks, exact-tree receipts, "
                 "baseline comparisons and required command/agent gates; a missing required result is never "
                 "a pass. After integration changes code, a fresh verifier checks the combined tree before "
                 "fresh finalization. Passing isolated-branch checks are not proof for changed combined code.")
    facts.append("Bounded-checkpoints-v1 override (only when the saved session/task declares that policy): "
                 "implementers may use native local-check for an admitted repair batch; triagers may use "
                 "diagnostic mode. These observations never record checks or accept a story. The verifier-only "
                 "rule above still owns independent acceptance. Preserve durable local/story/no-progress "
                 "budgets, every finding and requirements; unknown failures need triage. Read CHECKPOINTS.md "
                 "for repair-batch/amend/close and the mechanical repair-route. Use content-keyed compiler "
                 "reservation/publication; cached/waiting envelopes never spawn an idle agent. Review tasks "
                 "read only their sanitized role input, not this workflow or the journal. Older sessions "
                 "without this policy retain all prior semantics; never migrate issued tasks.")
    lines = [legacy.MARKER, "# backend: native; instruction preparation only", "[workflow]", "persistent_facts = ["]
    lines += ["  " + json.dumps(fact, ensure_ascii=False) + "," for fact in facts]
    lines.append("]")
    for layer in workflow.get("review_layers", []):
        lines += ["", "[[workflow.review_layers]]", "id = " + json.dumps(layer["id"]), 'instruction = ""']
    return "\n".join(lines) + "\n"
