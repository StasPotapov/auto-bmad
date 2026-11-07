"""Independent story repair budgets and conservative test progress detection."""

import re

DEFAULT_LIMITS = {"spec": 2, "review": 5, "tests": 10, "no_progress": 3}


def limits(cfg):
    configured = cfg.get("repair_limits", {})
    if not isinstance(configured, dict) or set(configured) - set(DEFAULT_LIMITS):
        raise ValueError("repair_limits table accepts spec, review, tests and no_progress (old level keys must be migrated)")
    result = {**DEFAULT_LIMITS, **configured}
    for level, value in result.items():
        if type(value) is not int or value < 0:
            raise ValueError(f"repair_limits.{level} must be a nonnegative integer")
    if result["no_progress"] < 1:
        raise ValueError("repair_limits.no_progress must be a positive integer")
    return result


CODE_FIX_POLICY = """Code repair routing policy. This overrides step-04 Classify's preference for bad_spec
for every nontrivial defect. When the existing authoritative requirements and acceptance criteria
unambiguously determine the correct behaviour, route an implementation defect to patch, including
a direct deviation from the spec. Repair the current code in place; preserve working changes and
the original review baseline. Do not rollback, rewrite the spec or invent a new requirement merely
to fix code. Log each confirmed finding, its requirement/evidence, fix and regression verification
in Review Triage Log and Verification. A trivial local fix with no new public surface or unproven
state may be applied by the controller; other code repairs go to the implementer with the existing
spec plus the verified findings and a bounded repair instruction, not a full reimplementation.
Never treat a new implementer session as native re-engagement. If the spec/plan actually needs
correction outside the intent-contract, keep bad_spec and its KEEP/rollback/reimplementation route.
Trace restrictions to the original user/story/AC/project policy before intent_gap.
Agent-added planning assumptions are not user prohibitions: correct a mistaken generated
plan through a bounded spec repair with source evidence, without asking routine permission.
If authoritative requirements conflict or leave business behaviour ambiguous, keep intent_gap;
do not guess, waive acceptance criteria or alter the intent-contract. Test failures use their own tests budget, never spec/review budgets, and do not rewrite acceptance
criteria. Iterate in place on the failed and related checks before repeating expensive independent
review. Do not disable tests, weaken assertions or change expected behaviour just to get green;
correct a test expectation only with evidence from authoritative requirements. Environment/access
failures are blockers, not code repair attempts. Stop after the configured consecutive attempts
without progress: a passing check or a strict reduction of reported failing test IDs is progress;
a different message or code edit alone is not. A scoped check verified by the host as matching
the exact pre-story baseline also resolves the regression; arbitrary skips do not. After collecting all active review-layer results, triage the entire list before editing.
Preserve a stable ID per finding and group shared root causes without dropping source rows.
Send every confirmed actionable finding in ONE repair batch; do not request a new independent
review while a known actionable finding remains unfixed. Count one repair cycle for the whole
batch, not per finding, file, patch, agent message or targeted diagnostic. If the implementer
returns a partial batch, continue that same batch and counter; do not relabel it a new cycle.
A real blocker is reported explicitly; it is never silently deferred to the next reviewer.
Require a closure table: finding ID, fixed/rejected/deferred, code or requirement evidence,
and regression-check result. Only the orchestrator may accept a rejection or a non-blocking
deferral; mandatory acceptance defects cannot be deferred. Verify all rows before closing the batch.
For failed tests, first collect all failures visible in the completed run, fix ALL known code/test
failures in one batch, then rerun the failed commands and affected regressions. Do not deliberately
fix one known failure and rerun the suite to rediscover the others. Focused diagnostics during the
batch are allowed when needed to understand a failure; they do not close the batch or spend a new
attempt. New failures exposed by the rerun form the next batch; preserve test budgets and progress rules.
Repeat-review policy overrides unconditional whole-review loopbacks: the first independent review
of the whole story is required. After fixes, assess their CUMULATIVE delta from the last independent
review, not only the latest small patch. Repeat independent review only for extensive or risky
changes: new behaviour/contracts, broad control/data-flow changes, auth/security, schema/migrations,
nontrivial conflict resolution, or uncertain impact. Severity or finding count alone is not a trigger.
For localized corrections with understood impact, the orchestrator checks every closure row,
inspects the cumulative patch and records why existing review coverage remains applicable.
Do not relaunch independent reviewers for these targeted fixes. Preserve the original reviewer
report and reviewed tree; record the orchestrator's current-code validation separately, never
claim that the old report reviewed newer code. Changed mandatory command/agent verification still
needs current evidence. Run the configured final gates once after the complete batch stabilizes;
these rules do not authorize dropping checks or marking unresolved confirmed defects done."""


def failed_tests(result, complete=False):
    """Recognize runner failure IDs; unknown output proves no reduction."""
    if isinstance(result.get("failure_ids"), list) and all(isinstance(x, str) for x in result["failure_ids"]):
        return set(result["failure_ids"])
    # Older cached results have only a bounded tail: a smaller visible set is not proof.
    if not complete and (result.get("tail_truncated") or len(result.get("tail", "").splitlines()) >= 60):
        return set()
    found = set()
    for line in result.get("tail", "").splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        match = re.match(r"FAILED (\S+)", line) or re.match(r"(?:FAIL|ERROR): (.+)", line)
        if match:
            found.add(match.group(1).split(" - ", 1)[0].strip())
        playwright = re.match(r"\d+\) (\[[^\]]+\]) › (.+?):\d+:\d+ › (.+)", line)
        if playwright:
            # Line numbers change when tests are added; project/file/title do not.
            title = re.sub(r"\s+─+\s*$", "", playwright[3]).strip()
            found.add(f"{playwright[1]} › {playwright[2]} › {title}")
    return found


def test_resolved(result):
    return result.get("verdict") == "pass" or (result.get("verdict") == "skipped"
                                               and result.get("baseline_equivalent") is True)


def complete_failure_ids(text, ids):
    """Only recognized runner summaries can prove a complete failing-ID set."""
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    for line in reversed(text.splitlines()):
        playwright = re.fullmatch(r'\s*(\d+) failed\s*', line)
        if playwright:
            return int(playwright[1]) > 0 and int(playwright[1]) == len(ids)
        unit = re.fullmatch(r'FAILED \(([^)]+)\)', line.strip())
        if unit:
            counts = re.findall(r'(?:failures|errors)=(\d+)', unit[1])
            return bool(counts) and sum(map(int, counts)) == len(ids)
        if re.search(r'\b\d+ (?:failed|error[s]?)\b', line) and (' in ' in line or '===' in line):
            counts = re.findall(r'\b(\d+) (?:failed|error[s]?)\b', line)
            return bool(counts) and sum(map(int, counts)) == len(ids)
    return False


def test_progress(before, after):
    if test_resolved(after):
        return True
    old, new = failed_tests(before), failed_tests(after)
    return bool(old and new and new < old)


def environment_failure(result):
    return result.get("code") in (126, 127) or any(marker in result.get("tail", "") for marker in (
        "Operation not permitted", "Cannot connect to the Docker daemon",
        "permission denied while trying to connect to the Docker"))
