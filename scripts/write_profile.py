#!/usr/bin/env python3
"""Builds the level profile for the bmad-build-auto engine.

Writes _bmad/custom/bmad-build-auto.user.toml, the top layer of the engine's config
merge (_bmad/scripts/config_utils.py). The content depends only on the run level,
so it lives here and not in the skill instructions: the model has no need to read it.

The merge rules this relies on:
  * persistent_facts — a list of strings, APPENDED to the project's list;
  * review_layers — an array of tables merged BY id: a matching id replaces the entry
    whole, so a disabled layer is an empty instruction, not rewritten text (otherwise
    the agent type routing from the project config would be lost).

Usage:
    write_profile.py --level normal --repo /path/to/project [--force]

Model and effort overrides from [roles.*] in the config (scripts/roles.py) go into facts E
and G as Agent call parameters; `agent_args` in the output carries them for the roles the
skill launches itself (story-runner, verifier).

`[run] triage_subagent = true` in the config adds fact I: step-04 Classify (verdicts and
routes) runs in the auto-bmad:bmad-triager subagent. Off — the profile is the same as without
the key.

With a project test command (the project-tests check of the config) fact J sends every
test run of the engine through `auto-bmad test` (scripts/testrun.py): the folder's lock and
the kept result for unchanged code.

Exit codes: 0 — written, 1 — error, 2 — refused (a human wrote the file).
"""

import argparse
import json
import os
import re
import sys
from datetime import date

from gitexclude import ensure_excluded
from plan_run import run_section
from roles import read_config, resolve
from verify import command_check

MARKER = "# generator: auto-bmad"

# Layers disabled at each level (an entry with the same id and an empty instruction).
DISABLED = {
    "fast": ["blind-hunter", "verification-gap"],
    "normal": ["verification-gap"],
    "deep": [],
}

# Limit of bad_spec repair loops per review pass.
REPAIR_LIMIT = {"fast": 1, "normal": 2, "deep": 3}

# Review layer to agent type routing, inserted into fact E.
REVIEWER_ROUTING = {
    "fast": '`intent-alignment` uses `"auto-bmad:bmad-reviewer-lite"`; `edge-case-hunter` uses '
            '`"auto-bmad:bmad-reviewer-mid"`.',
    "normal": '`intent-alignment` uses `"auto-bmad:bmad-reviewer-lite"`; every other layer uses '
              '`"auto-bmad:bmad-reviewer-mid"`.',
    "deep": 'every layer uses `"auto-bmad:bmad-reviewer"`.',
}

FACT_A = """Follow-up review policy for this run, set deliberately by the project owner. It replaces the follow-up recommendation rule in step-04 Finalize. Set `followup_review_recommended: true` only when this pass patched an entry whose entry verdict was `high`. Patched `medium` entries never trigger it — at any volume, on any pass; the "two or more medium entries" condition does not apply in this run. The rest of that rule is unchanged: deferred, rejected and `false` findings never count, a `true` must still name the specific unverified risk under `## Auto Run Result`, and when no such risk can be named the value is `false`. Rationale: measured across fifteen completed stories, the medium-triggered second pass produced as many findings as the first and never surfaced a `high` that the first pass had missed."""

FACT_B = """Triage screening policy for this run, set deliberately by the project owner. It refines, and does not remove, the verification rule in step-04 Classify. Before verifying a finding at its cited location, screen it on the reviewer's own text: if the finding names no consequence for an end user and no consequence for a developer — no caller that will diverge, no invariant that will break, no behaviour that will change — then it is cosmetic by the same standard step-04 already applies when rejecting `low`. Grade it `low` on that basis, give it its triage-log row with the screening as its evidence, and route it by the existing `low` rules without reading the code at the cited location. Screen out ONLY on the absence of a named consequence. Whenever the finding names any consequence at all, however small, and whenever you are unsure whether it does, fall through to the full verification that step-04 describes — read the cited location, read beyond the changed lines, follow callers. Never screen out a finding that claims data loss, incorrect output, a security or privacy consequence, a crash, or a broken build, however weakly it is worded. Rationale: measured across fifteen completed stories, roughly six findings in ten end as `low` and are then rejected, and verifying each of them at full depth is the most expensive operation in the run."""

FACT_C = """Repair loop limit for this run, set deliberately by the project owner: the `bad_spec` loopback limit in step-04 Classify step 5 is {n}, not 5. Read and increment `review_loop_iteration` exactly as that step describes — only the threshold changes. When it exceeds {n}, append the triage-log entry for this pass, then HALT with status `blocked` and blocking condition `review repair loop exceeded {n} iterations (non-convergence)`."""

FACT_D = """Blind Hunter launch policy for this run, set deliberately by the project owner: when you launch the `blind-hunter` review layer, drop the finding-floor instructions from the prompt you send — the sentence computing `N = min(floor(sqrt(kB) + 1), 10)`, the instruction to state that arithmetic, the instruction to find at least N issues, and the instruction not to stop with an empty list. Send the rest of that layer's prompt unchanged, and put one line in their place: "Report every issue you actually find. An empty list is a valid result if you have genuinely looked; do not pad it." Everything else about the layer — its agent type, the diff file it reads, the no-severity rule — stays exactly as its instruction says. Rationale: the floor manufactures findings that this session must then verify at full depth, and the triage log shows those manufactured findings being rejected as `low`."""

FACT_E = """Model policy for this run, set deliberately by the project owner. Launch the step-03 implementation subagent with `subagent_type: "auto-bmad:bmad-implementer"`. For every step-04 review-layer subagent, pick the agent type by the layer's `id`: {routing} Use those agent types even when a layer's instruction text does not name one — they ship with the auto-bmad plugin and carry their own model and effort, and where an instruction does name a type, that naming does not override this mapping. The reviewers deliberately run on a different model than the session and than the implementation subagent: an independent model has different blind spots and catches what a same-model reviewer systematically misses, which is the whole point of the review layer. The per-layer split is deliberate too: the cheapest type goes only to a layer whose work is self-contained description, never to one that hunts defects or traverses the repository. This overrides the step-04 rule "All review subagents must run at the same model capability as the current session" — do not substitute the session model, do not swap the agent types, and do not treat the difference as a reason to halt. If an agent type is genuinely unavailable in this host, launch that subagent without it and record the substitution under `## Auto Run Result` — do not halt over it."""

FACT_F = """Subagent execution in this host is asynchronous. The Agent tool always returns immediately and the run is resumed by a completion notification; a blocking, in-turn subagent call does not exist here. Therefore the workflow.md rule "never end your turn to await a completion notification" cannot be satisfied literally, and it must NOT be read as a ban on ending the turn. In this host the sanctioned way to await subagents is: launch every subagent the step calls for in ONE message, then end the turn with a single short line naming what is being awaited. The notification resumes the run by itself, and the step's ordering guarantee still holds — all launches happen before any result is read. Ending the turn this way is waiting, not yielding: the run does not stall and no work is abandoned. What IS forbidden is keeping the turn alive with placeholder tool calls — `echo`, `sleep`, re-reading a file already read, repeated `git status`, or any call that inspects nothing. Such a call advances nothing, the subagent does not finish sooner because of it, and a loop of them burns the run's context for no result. Poll only when the poll reads real state that no notification will deliver, such as an external process this host does not track."""

FACT_G = """Context-compilation policy for this run, set deliberately by the project owner. When step-01 compiles the epic context, launch that subagent with `subagent_type: "auto-bmad:bmad-compiler-lite"`, with `compile-epic-context.md` as its prompt and the same inputs step-01 lists. The type ships with the auto-bmad plugin and carries its own model and effort; do not substitute the session model. Its work is self-contained extraction from planning documents, so the cheaper model is deliberate. Everything else in step-01 is unchanged: the cache check before compiling and the verification of the written file after it. If the agent type is genuinely unavailable in this host, launch that subagent without it and record the substitution under `## Auto Run Result` — do not halt over it."""


FACT_H = """Context economy for this run, set deliberately by the project owner. Every step of this session re-reads the whole context, so a file read once is paid for on every later step; these rules cut reads that bring nothing new and keep every read a judgement needs. (1) The full diff: step-03 Verify and step-04 still write the staged diff file exactly as they say — the review layers read that file themselves. Check its size with `wc -m`. Under 30000 characters, read it whole as step-03 says — it includes new untracked files: a small diff costs little and gives the whole change at once. Larger, this session does not read the whole file into its context. Read `git diff --stat <baseline_revision>` and `git status --porcelain` for the shape of the change — the second lists new untracked files, which `git diff` does not show — then the hunks you need with `git diff <baseline_revision> -- <path>`, the changed file at the lines in question, and every new untracked file in full. "Judge against the diff, not against the implementation subagent's report" still holds: judge against these hunks. When a fix changes code, rewrite the staged diff file; if it is still under 30000 characters, read it whole again, otherwise read only the hunks of the files the fix changed. (2) Triage in step-04: verify each finding at its cited location and beyond, as step-04 says. Collect that code for all findings of the pass in one call, not with a `grep` or `git` call per finding — each call re-reads the whole context. Once every layer has reported, write one JSON file with the Write tool (no heredoc) to `.auto-bmad/evidence/<spec file name>.json`: `{"base": "<baseline_revision>", "findings": [{"id": "<finding number>", "file": "<path>", "lines": "<from-to>", "diff": true, "grep": "<optional regular expression>", "grep_in": "<optional path; . is the whole repository>"}]}` — one entry per finding that needs code; `diff: true` adds the hunks of `git diff <baseline_revision>` that touch those lines. Then run `auto-bmad evidence --input <that file> --repo .` once, as its own Bash call: it returns, per finding, the numbered lines around the cited ones, the diff hunks and the grep hits. A finding those excerpts do not settle gets more code — its callers, a test, the whole file: collect what several findings still need in one more evidence file and call it again, and read a file directly only when an excerpt cannot show what you need. There is no limit on such targeted reads; a finding you cannot settle without more code gets more code. Before you route a finding `reject`, or grade it `false` or `low`, write in its triage-log evidence what code you read to decide: the file and lines (an evidence excerpt counts), or the command you ran. "Per the implementation report", "per the diff stat" or "per the finding text" is not evidence. The only exception is a finding screened out by the triage screening policy for naming no consequence; its evidence is that screening. (3) No repeated reads: do not read again a file whose content is already in this session and has not changed since — the spec you have just written or edited, `epic-<N>-context.md` after it was loaded once, a step file. The READY-FOR-DEVELOPMENT gate in step-02 still re-reads the spec file from disk, as it says — it checks what was really written — but re-reads only the `## HALT` and `## READY FOR DEVELOPMENT STANDARD` sections of workflow.md, not the whole file. To check a compiled `epic-<N>-context.md`, read its first line; load the file into context once. To read one section of the spec, read that section, not the whole file. Re-read anything whose exact text you no longer have and need."""


FACT_I = """Triage delegation for this run, set deliberately by the project owner. In step-04 Classify, steps 1–3 — the verdict on each finding, the grouping by root cause and the route of each entry — run in a subagent with a clean context, not in this session: by then this session's context is large, and every triage step re-reads all of it. Once every review layer has reported, launch ONE subagent with `subagent_type: "auto-bmad:bmad-triager"` and wait for it as the subagent execution policy says. Its prompt holds: the absolute path of this skill's `step-04-review.md`; the absolute path of `_bmad/custom/bmad-build-auto.user.toml` (it applies the triage screening policy and item (2) of the context economy policy from there); the absolute path of the spec file, the baseline revision and the absolute path of the staged diff file; whether this is a follow-up pass; and every review layer's report as is, labelled with the layer id, in the order the layers reported. It reads code and changes nothing in the story — the only file it writes is its evidence input under `.auto-bmad/evidence/`, which git does not see. It returns one row per finding in the `## Review Triage Log` row format, with verdict, route and evidence; the grouping; for each `patch` entry the file, what is wrong and what the smallest fix must do; for each `defer` entry the deferred-item fields; for each `intent_gap` or `bad_spec` entry its root cause. Take its verdicts and routes as they are: do not verify those findings again and do not re-read the code it cites. Then continue Classify from step 4 exactly as step-04 says — the log entry, the cascade of entries, the patches and `## Verification`, the defer list, the loopback limit — and Finalize. The row count must still equal the number of findings the layers reported: if its answer misses findings, launch it once more for the missing ones only. If it fails again, its answer does not follow the row format, or the agent type is genuinely unavailable in this host, triage the remaining findings in this session as step-04 says — collecting their code with one `auto-bmad evidence` call, by item (2) of the context economy policy, not a `grep` per finding — and record that under `## Auto Run Result` — do not halt over it."""


FACT_J = """Test runs for this run, set deliberately by the project owner. The project's test command is `{command}`. This session never runs it, or any part of it, directly: run `auto-bmad test --repo <the folder this story runs in>` instead — in step-03 Verify, in the re-run of `## Verification` after patches in step-04, and anywhere else the full suite runs. A `## Verification` command that runs only part of the suite (a part of `{command}`, one test file) goes as `auto-bmad test --command '<that command>' --repo <the folder>`. Run it in the foreground as its own Bash call with `timeout: 600000`; never with `run_in_background`. It holds the folder's test lock, so a run never overlaps another one that shares this folder's test databases and ports. It keeps each result by the content of the code: when the code has not changed since that command last ran in this folder — edits under `_bmad-output/` do not count — it returns the kept result at once with `reused: true`. A reused result is a real run of the command on this exact code: record it under Verification as passed or failed like any other run. The output is JSON: `verdict` is `pass` or `problem`, `tail` has the end of a failed output and `log` the full one. `verdict: running` means the tests outlived the wait and go on in the background: call exactly the same command again to wait for them (after a `--rerun` call, the same command without `--rerun`). Never wait for tests with `pgrep`, `sleep` or polling loops, and never start them another way while they run. After a code change the next call runs the tests again by itself; pass `--rerun` only after you fixed a failure whose cause is outside the code (Docker was not running), never to retry a code failure. Before the first test run of step-03 Verify, the implementation subagent has returned: if its report says a command of its own still runs, wait for that through `auto-bmad test`, never by watching its processes."""


# With fact I on, item (2) of fact H is the triager's rule, so the evidence is collected once.
H_TRIAGE = "(2) Triage in step-04:"
H_TRIAGE_DELEGATED = ("(2) Triage in step-04 — with the triage delegation policy it runs in the triage "
                      "subagent, and this item is that subagent's rule: this session collects no evidence "
                      "for the findings it triaged and does not verify them again. When this session "
                      "triages findings itself, as that policy's fallback, this item is its rule again. "
                      "For whoever triages:")


ARGS_RULE = """Where an agent type in this run's policies is followed by Agent parameters, pass exactly those `model` and `effort` parameters in that Agent call: the project owner set them in the auto-bmad config, and for that type they replace the model and effort it carries. An agent type that no policy follows with Agent parameters is launched without `model` and `effort`."""


def with_args(fact, args):
    """The fact with `model` / `effort` after each agent type that has overrides."""
    found = False

    def put(m):
        nonlocal found
        extra = args.get(m.group(2))
        if not extra:
            return m.group(0)
        found = True
        return m.group(0) + " with Agent parameters " + ", ".join(
            f'`{key}: "{extra[key]}"`' for key in ("model", "effort") if key in extra)

    out = re.sub(r'`(subagent_type: )?"auto-bmad:bmad-([a-z-]+)"`', put, fact)
    return f"{out} {ARGS_RULE}" if found else out


def triage_setting(cfg):
    """`[run] triage_subagent` of the merged config → (on, warning or None); off by default."""
    value = run_section(cfg).get("triage_subagent", False)
    if isinstance(value, bool):
        return value, None
    return False, f"[run].triage_subagent = {value!r}: must be true or false — triage stays in the session"


def build(level: str, args=None, triage_subagent=False, test_command=None) -> str:
    """args — {role: {"model"?, "effort"?}}, the overrides of roles.resolve.

    triage_subagent — fact I: step-04 Classify runs in the bmad-triager subagent ([run] of the config).
    test_command — fact J: the engine runs the project tests through `auto-bmad test`.
    """
    args = args or {}
    facts = [
        FACT_A,
        FACT_B,
        FACT_C.format(n=REPAIR_LIMIT[level]),
        FACT_D,
        with_args(FACT_E.format(routing=REVIEWER_ROUTING[level]), args),
        FACT_F,
        FACT_H.replace(H_TRIAGE, H_TRIAGE_DELEGATED) if triage_subagent else FACT_H,
    ]
    # Every story of the epic reuses the epic context; on deep it stays on the session model.
    if level != "deep":
        facts.append(with_args(FACT_G, args))
    if triage_subagent:
        facts.append(with_args(FACT_I, args))
    if test_command:
        facts.append(FACT_J.format(command=test_command))
    out = [
        "# GENERATED by auto-bmad — manual edits are overwritten by the next run.",
        MARKER,
        f"# level: {level}",
        f"# generated: {date.today().isoformat()}",
        "#",
        "# Permanent project settings live in bmad-build-auto.toml. This file does not cancel them,",
        "# it adds to them: facts are appended, layers are replaced only on a matching id.",
        "",
        "[workflow]",
        "",
        "persistent_facts = [",
    ]
    for fact in facts:
        out.append("  '''")
        out.append(fact)
        out.append("''',")
    out.append("]")
    for layer_id in DISABLED[level]:
        out += ["", "[[workflow.review_layers]]", f'id = "{layer_id}"', 'instruction = ""']
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", required=True, choices=sorted(DISABLED))
    ap.add_argument("--repo", default=".", help="project root")
    ap.add_argument("--force", action="store_true",
                    help="overwrite a file without the auto-bmad marker")
    args = ap.parse_args()

    custom_dir = os.path.join(args.repo, "_bmad", "custom")
    path = os.path.join(custom_dir, "bmad-build-auto.user.toml")

    if not os.path.isdir(custom_dir):
        message = f"missing folder {custom_dir} — the project does not look like BMad v6"
        print(message, file=sys.stderr)
        print(json.dumps({"error": message, "path": os.path.abspath(path)},
                         ensure_ascii=False))
        return 1

    if os.path.exists(path) and not args.force:
        with open(path, encoding="utf-8") as fh:
            head = fh.read(400)
        if MARKER not in head:
            message = (f"a human wrote {path} (no '{MARKER}' marker) — "
                       "the level is not applied, the file is untouched")
            print(message, file=sys.stderr)
            print(json.dumps({"error": message, "path": os.path.abspath(path)},
                             ensure_ascii=False))
            return 2

    cfg, warnings = read_config(args.repo)
    roles, errors, role_warnings = resolve(cfg)
    warnings += role_warnings
    if errors:
        message = "the [roles] config has errors — " + "; ".join(errors)
        print(message, file=sys.stderr)
        print(json.dumps({"error": message, "path": os.path.abspath(path)}, ensure_ascii=False))
        return 1
    agent_args = {role: r["args"] for role, r in roles.items() if r["args"]}
    triage, warning = triage_setting(cfg)
    if warning:
        warnings.append(warning)
    test_command, _ = command_check(args.repo, "project-tests")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build(args.level, agent_args, triage, test_command))

    # The profile is inside the working tree: unignored, it would make the tree dirty and stop the next preflight.
    excluded = ensure_excluded(args.repo, "_bmad/custom/bmad-build-auto.user.toml")

    print(json.dumps({
        "path": os.path.abspath(path),
        "level": args.level,
        "git_excluded": excluded,
        "disabled_layers": DISABLED[args.level],
        "repair_limit": REPAIR_LIMIT[args.level],
        "review_passes": {"fast": 1, "normal": 2, "deep": 3}[args.level],
        "agent_args": agent_args,
        "triage_subagent": triage,
        "test_command": test_command,
        "warnings": warnings,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
