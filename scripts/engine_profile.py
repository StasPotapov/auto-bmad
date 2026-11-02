"""CLI transport policy for BMAD customization; never rewrites engine step sources."""

import json
import tomllib

import write_profile as legacy

TRANSPORT_PREFIXES = ("Model policy", "Subagent execution", "Context-compilation policy", "Triage delegation")


def build(level, triage_subagent=False, test_command=None, repair_budget=None):
    original = tomllib.loads(legacy.build(level, triage_subagent=triage_subagent, test_command=test_command,
                                        repair_budget=repair_budget))
    workflow = original["workflow"]
    facts = [fact for fact in workflow["persistent_facts"] if not fact.startswith(TRANSPORT_PREFIXES + ("Independent repair budgets",))]
    budget = legacy.REPAIR_LIMIT if repair_budget is None else repair_budget
    facts.append("CLI repair budgets per story run: " + json.dumps(budget, sort_keys=True) + ". "
                 "This replaces native counters and verify attempt: only the broker owns the counters, across all passes. "
                 'Before review patches call repair with {"reason":"code_fix"}; bad_spec uses rollback. '
                 'For failed tests call repair with {"reason":"test_failure","failure_id":"<host-issued id>"}. '
                 "Each category has its own budget; test fixes never spend spec/review cycles. "
                 "Run the same failed check after each test repair to let the host assess progress. "
                 "Reproduce full-suite failures with a registered dev check before repair admission when possible. "
                 "Do not start another repair until its failed check result is recorded; use targeted checks during the loop, "
                 "all active independent reviews once stable, then checkpoint runs full configured tests and any pending repaired checks. "
                 "Record returned counts. On exhausted budget/no progress return blocked and preserve code. "
                 "Never reset counters or fabricate a failure id; environment failures are blockers, not code fixes.")
    facts = [fact.replace('as its own Bash call with `timeout: 600000`',
                          'as its own foreground command through the host command tool')
             .replace('never with `run_in_background`', 'never as a detached command')
             .replace('in the foreground as its own Bash call with `timeout: 600000`',
                      'in the foreground through the host command tool') for fact in facts]
    routing = {"intent-alignment": "reviewer-lite", "edge-case-hunter": "reviewer-mid",
               "blind-hunter": "reviewer-mid", "verification-gap": "reviewer-mid"}
    if level == "deep":
        routing = {layer: "reviewer" for layer in routing}
    facts.append(
        "CLI host transport policy. This replaces native Agent/Task/Skill launch and waiting rules, "
        "including the synchronous native-subagent requirement and same-session-model review rule. "
        "The BMAD lifecycle, handoff payloads, acceptance criteria, review instructions, activation "
        "steps and on_complete remain unchanged. Execute delegated work through the auto-bmad CLI "
        "delegation bridge named in the run manifest. Never substitute a native subagent or session "
        "model when the bridge is unavailable: HALT blocked with 'CLI delegation bridge unavailable'. "
        "Send the original implementation handoff payload to role implementer, with the spec as its "
        "sole source of truth. Review layer to role mapping: " + json.dumps(routing, sort_keys=True) + ". "
        "Keep each layer's context restrictions: claims and implementation reports are not shared "
        "with other layers. Unlisted custom layer IDs use reviewer on deep, otherwise reviewer-mid. "
        "Join every required result before triage. A failed or missing review "
        "result is blocked, not an empty finding list. During a delegated write the controller "
        "must not edit the worktree. Do not run detached child agents or merge/push branches.")
    facts.append("CLI Git transport: the host has already performed the metadata writability check. "
                 "Use its broker for commits and rollback instead of direct Git writes. Keep the "
                 "host's pinned review_base_commit as baseline_revision on every pass and repair, "
                 "so intermediate task/implementation commits cannot narrow the story review diff. "
                 "Native session re-engagement is unavailable: use controller patches for trivial code fixes, "
                 "otherwise delegate an in-place repair to implementer with the existing spec and findings. "
                 "Call repair before either path: code_fix uses review budget, test_failure uses tests budget. For test_failure iterate on the failed check until stable, then repeat all active reviews and full verification once on the final code.")
    if level != "deep":
        facts.append("CLI context compilation: use bridge role compiler-lite with the original "
                     "compile-epic-context payload and inputs. Verify the resulting file as BMAD directs.")
    if triage_subagent:
        facts.append("CLI triage delegation: route step-04 Classify steps 1–3 to bridge role triager. "
                     "Pass the prepared profile path and explicitly apply its Code repair routing policy as well as screening/context economy; preserve evidence requirements and one row per finding. "
                     "Steps 4–5, patches, log writes and loopbacks stay in the story controller.")
    lines = [legacy.MARKER, "# backend: cli; preparation only, execution requires a validated bridge", "[workflow]",
             "persistent_facts = ["]
    lines += ["  " + json.dumps(fact, ensure_ascii=False) + "," for fact in facts]
    lines.append("]")
    for layer in workflow.get("review_layers", []):
        lines += ["", "[[workflow.review_layers]]", "id = " + json.dumps(layer["id"]), 'instruction = ""']
    return "\n".join(lines) + "\n"
