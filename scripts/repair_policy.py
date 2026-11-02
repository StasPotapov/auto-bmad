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
If authoritative requirements conflict or leave business behaviour ambiguous, keep intent_gap;
do not guess, waive acceptance criteria or alter the intent-contract. Test failures use their own tests budget, never spec/review budgets, and do not rewrite acceptance
criteria. Iterate in place on the failed and related checks before repeating expensive independent
review. Do not disable tests, weaken assertions or change expected behaviour just to get green;
correct a test expectation only with evidence from authoritative requirements. Environment/access
failures are blockers, not code repair attempts. Stop after the configured consecutive attempts
without progress: a passing check or a strict reduction of reported failing test IDs is progress;
a different message or code edit alone is not. A scoped check verified by the host as matching
the exact pre-story baseline also resolves the regression; arbitrary skips do not. Once tests stabilize, regenerate the whole-story
diff and repeat every active independent review layer and all required full checks before completion. Do not reuse pre-repair review results or mark unresolved
confirmed defects done. Count one repair cycle for a batch of fixes, not one for each finding."""


def failed_tests(result, complete=False):
    """Recognize stable pytest/unittest/Jest failure IDs; unknown output proves no reduction."""
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
    return found


def test_resolved(result):
    return result.get("verdict") == "pass" or (result.get("verdict") == "skipped"
                                               and result.get("baseline_equivalent") is True)


def test_progress(before, after):
    if test_resolved(after):
        return True
    old, new = failed_tests(before), failed_tests(after)
    return bool(old and new and new < old)


def environment_failure(result):
    return result.get("code") in (126, 127) or any(marker in result.get("tail", "") for marker in (
        "Operation not permitted", "Cannot connect to the Docker daemon",
        "permission denied while trying to connect to the Docker"))
