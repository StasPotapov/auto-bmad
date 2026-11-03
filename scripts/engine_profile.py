"""Native host adaptation of the shared BMAD instructions; never starts a model."""

import json
import tomllib

import write_profile as legacy

TRANSPORT_PREFIXES = ("Model policy", "Subagent execution", "Context-compilation policy", "Triage delegation",
                      "Independent repair budgets")


def build(level, triage_subagent=False, test_command=None, repair_budget=None):
    original = tomllib.loads(legacy.build(level, triage_subagent=triage_subagent, test_command=test_command,
                                        repair_budget=repair_budget))
    workflow = original["workflow"]
    facts = [fact for fact in workflow["persistent_facts"] if not fact.startswith(TRANSPORT_PREFIXES)]
    facts = [fact.replace('as its own Bash call with `timeout: 600000`',
                          'as its own foreground command through the host command tool')
             .replace('never with `run_in_background`', 'never as a detached command')
             .replace('in the foreground as its own Bash call with `timeout: 600000`',
                      'in the foreground through the host command tool') for fact in facts]
    budget = legacy.REPAIR_LIMIT if repair_budget is None else repair_budget
    facts.append("Native repair budgets per story run: " + json.dumps(budget, sort_keys=True) + ". "
                 "The main chat owns stop/continue decisions and the durable native session owns counters. "
                 "Before a repair batch ask the main chat to record a repair event with kind spec, review or tests. "
                 "Do not reset counters on a new agent, pass, resume or changed error text. "
                 "Test failures use tests budget, code findings use review, requirement/spec corrections use spec. "
                 "Fix all known failures in the admitted batch before rerunning the failed checks; do not weaken checks. "
                 "Count consecutive test attempts without a pass or a strict reduction of known failing IDs; "
                 "stop at no_progress. Environment, access and permission failures are reported to the main chat "
                 "with concrete evidence; never bypass them or mislabel them as code repairs. "
                 "A story agent's blocked result is a request for an orchestrator decision, not authority to cancel the epic.")
    routing = {"intent-alignment": "reviewer-lite", "edge-case-hunter": "reviewer-mid",
               "blind-hunter": "reviewer-mid", "verification-gap": "reviewer-mid"}
    if level == "deep":
        routing = {layer: "reviewer" for layer in routing}
    facts.append(
        "Native host transport policy. This overrides Claude-specific Agent/Task/Skill launch and waiting "
        "instructions. The main chat is the only epic orchestrator. A native story-runner reads this rendered "
        "BMAD workflow and executes its lifecycle in its own context; it does not launch a CLI model or Python queue. "
        "Use the current host's collaboration tools for native subagents. Read the shared role prompt and pass the "
        "manifest's explicit model and effort (reasoning_effort in Codex), fork_turns=none, absolute worktree, "
        "scope ownership and exact handoff. Missing capabilities are reported, never replaced by codex exec. "
        "Use followup_task for an idle existing agent and send_message for a running agent; a replacement agent "
        "receives saved spec/worktree/evidence and is not called the same session. Wait with wait_agent, without "
        "sleep or status polling, and forward results to the main chat. Each phase change, agent start, failed check "
        "and final result must be reported with story, phase, role, agent id, worktree and evidence. "
        "The main chat grants a total slot budget including itself, controllers and children; never spawn beyond "
        "that grant. Batch reviewers when slots are scarce, preserving their independence. "
        "Implementation uses role implementer with the original handoff and the spec as its source of truth. "
        "Review layer mapping: " + json.dumps(routing, sort_keys=True) + ". "
        "Unlisted custom layers use reviewer on deep, otherwise reviewer-mid. Keep original review context "
        "restrictions: never leak another layer's findings or implementation claims into a blind review. "
        "All required results must arrive before triage; a failed/missing result is not a clean review. "
        "Subagents share parent permissions; a no-edit instruction is not a separate read-only sandbox. "
        "Only one agent writes a story worktree at a time; the controller waits while implementation writes. "
        "Do not merge branches, update sprint tracking, launch detached model processes or push.")
    facts.append("Native completion policy. Keep the original baseline_revision throughout every repair and "
                 "review the whole story diff initially. Once fixes stabilize, repeat independent review only for extensive or risky cumulative changes; otherwise the main chat records targeted revalidation, "
                 "with required final checks on the current code. Report reviewed code identity, report paths and "
                 "check results to the main chat. The main chat records review attestations, runs native session "
                 "check, and accepts complete only with current evidence, done spec and clean committed tree. "
                 "Do not report a story done merely because implementation or an agent process finished.")
    if level != "deep":
        facts.append("Native context compilation: delegate the original compile-epic-context payload to native "
                     "role compiler-lite with its manifest profile, within the granted slots; verify its output as BMAD directs.")
    if triage_subagent:
        facts.append("Native triage delegation: delegate step-04 Classify steps 1–3 to native role triager with "
                     "the prepared profile, original review reports, spec, baseline and evidence. Preserve one row per finding, "
                     "screening/context economy and Code repair routing policy. Steps 4–5, patches and log writes remain "
                     "with the story-runner; the main chat owns stop decisions.")
    lines = [legacy.MARKER, "# backend: native; instruction preparation only", "[workflow]", "persistent_facts = ["]
    lines += ["  " + json.dumps(fact, ensure_ascii=False) + "," for fact in facts]
    lines.append("]")
    for layer in workflow.get("review_layers", []):
        lines += ["", "[[workflow.review_layers]]", "id = " + json.dumps(layer["id"]), 'instruction = ""']
    return "\n".join(lines) + "\n"
