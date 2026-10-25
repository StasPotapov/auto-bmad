#!/usr/bin/env python3
"""Does one more story (or wave) fit into what is left of the run: time and subscription limit.

An external runner (cron, CI, a scheduler) may give the run a time window: it puts the
window end into `AUTO_BMAD_DEADLINE`. The skill closes the window itself, between stories,
and this script makes the decision: a story already started is always finished.
Killing the run at the deadline instead would stop it mid-story, lose the work
and leave a dirty tree that blocks the next run.

The second limit is the subscription windows. Only the runner that watches the stream
sees their usage; it puts a snapshot into `AUTO_BMAD_LIMITS_FILE`, and the thresholds
come in `AUTO_BMAD_STOP_AT_*_PCT`. The threshold stops the run where time does:
between stories, where a stop is clean.

Usage:
    window.py [--stage next-story|next-wave] [--deadline <epoch>] [--reserve-min N]
              [--limits-file <path>] [--stop-at-five-hour-pct N]
              [--stop-at-seven-day-pct N]

Source priority: argument → environment variable → no limit.

Exit 0 — take the next one (also when there are no limits), 2 — "not done by rule":
less than the reserve is left before the window end, or a subscription window is used
above the threshold. There is no exit 1: the script requires no arguments without
defaults and treats a broken variable as no limit — failing a run over garbage
in the environment is worse than finishing the whole epic.
"""

import argparse
import json
import os
import sys
import time

ENV_DEADLINE = "AUTO_BMAD_DEADLINE"
ENV_RESERVE = "AUTO_BMAD_RESERVE_MINUTES"
ENV_LIMITS = "AUTO_BMAD_LIMITS_FILE"
ENV_STOP_5H = "AUTO_BMAD_STOP_AT_FIVE_HOUR_PCT"
ENV_STOP_7D = "AUTO_BMAD_STOP_AT_SEVEN_DAY_PCT"

# The snapshot is written during the run; an older one is from a past run and is ignored.
LIMITS_STALE_SEC = 3 * 3600

# A wave ends with worktree merges and a sprint sync; an abandoned merge leaves worktrees
# and a dirty tree, so a wave needs the reserve plus a quarter of an hour.
WAVE_EXTRA_MIN = 15

DEFAULT_RESERVE_MIN = 60


def number(raw, warnings, what):
    """A number from a string or None. Garbage goes to warnings instead of failing."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(float(str(raw).strip()))
    except ValueError:
        warnings.append(f"{what} is not a number: \"{raw}\" — treating it as no limit")
        return None


def limits(path, now, warnings):
    """Subscription window snapshot: {key: (usage %, reset)}. No data — empty.

    A broken or stale file means no data, not a reason to stop the run.
    """
    if not path:
        return {}
    try:
        with open(path) as fh:
            snap = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        warnings.append(f"the limits snapshot is unreadable ({e}) — treating it as no data")
        return {}
    if not isinstance(snap, dict):
        warnings.append("the limits snapshot does not look like a snapshot — treating it as no data")
        return {}
    updated = snap.get("updated_at")
    if isinstance(updated, (int, float)) and now - updated > LIMITS_STALE_SEC:
        warnings.append("the limits snapshot is from a past run — treating it as no data")
        return {}
    out = {}
    for key in ("five_hour", "seven_day"):
        win = snap.get(key)
        if not isinstance(win, dict):
            continue
        util = win.get("utilization")
        if not isinstance(util, (int, float)):
            continue
        resets = win.get("resets_at")
        # The reset has passed: the window is empty, the snapshot does not know it yet.
        if isinstance(resets, (int, float)) and now >= resets:
            continue
        out[key] = (int(util * 100), resets)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stage", choices=("next-story", "next-wave"), default="next-story",
                   help="what is about to start: the next story or the next wave")
    p.add_argument("--deadline", help="window end, epoch; default from $" + ENV_DEADLINE)
    p.add_argument("--reserve-min", help="reserve in minutes; default from $" + ENV_RESERVE)
    p.add_argument("--limits-file",
                   help="subscription windows snapshot; default from $" + ENV_LIMITS)
    p.add_argument("--stop-at-five-hour-pct",
                   help="five-hour window threshold in %%; default from $" + ENV_STOP_5H)
    p.add_argument("--stop-at-seven-day-pct",
                   help="seven-day window threshold in %%; default from $" + ENV_STOP_7D)
    p.add_argument("--now", help="current time, epoch — tests only")
    a = p.parse_args()

    warnings = []
    now = number(a.now, warnings, "--now") or int(time.time())
    deadline = number(a.deadline or os.environ.get(ENV_DEADLINE), warnings, "window deadline")
    reserve = number(a.reserve_min or os.environ.get(ENV_RESERVE), warnings, "window reserve")
    if reserve is None or reserve < 0:
        reserve = DEFAULT_RESERVE_MIN

    needed = reserve + (WAVE_EXTRA_MIN if a.stage == "next-wave" else 0)
    out = {
        "window": deadline is not None,
        "stage": a.stage,
        "deadline": deadline,
        "deadline_human": time.strftime("%H:%M", time.localtime(deadline)) if deadline else None,
        "left_minutes": None,
        "reserve_minutes": reserve,
        "needed_minutes": needed,
        "take_next": True,
        "reason": "",
        "limits": {},
        "warnings": warnings,
    }

    if deadline is None:
        out["reason"] = "no window set — working without a time limit"
    else:
        left = int((deadline - now) // 60)
        out["left_minutes"] = left
        what = "wave" if a.stage == "next-wave" else "story"
        if left < 0:
            out["take_next"] = False
            out["reason"] = (f"the work window closed {-left} min ago "
                             f"(at {out['deadline_human']}) — not taking the next {what}")
        elif left < needed:
            out["take_next"] = False
            out["reason"] = (f"{left} min left until the window end ({out['deadline_human']}), "
                             f"{needed} needed — not taking the next {what}: "
                             f"it would be cut off midway")
        else:
            out["reason"] = (f"{left} min left until the window end ({out['deadline_human']}) "
                             f"with a reserve of {needed} — taking the next {what}")

    # Checked after time: both stop the same way, but the time reason is more precise.
    seen = limits(a.limits_file or os.environ.get(ENV_LIMITS), now, warnings)
    thresholds = (
        ("five_hour", "five-hour",
         number(a.stop_at_five_hour_pct or os.environ.get(ENV_STOP_5H), warnings,
                "five-hour window threshold")),
        ("seven_day", "seven-day",
         number(a.stop_at_seven_day_pct or os.environ.get(ENV_STOP_7D), warnings,
                "seven-day window threshold")),
    )
    for key, title, pct in thresholds:
        if key not in seen:
            continue
        used, resets = seen[key]
        out["limits"][key] = {"used_pct": used, "threshold_pct": pct or None,
                              "resets_at": resets}
        # Threshold 0 means "no limit".
        if not pct or used < pct:
            continue
        if out["take_next"]:
            what = "wave" if a.stage == "next-wave" else "story"
            when = ""
            if isinstance(resets, (int, float)):
                when = f", resets at {time.strftime('%H:%M', time.localtime(resets))}"
            out["take_next"] = False
            out["reason"] = (f"the {title} subscription window is {used}% used "
                             f"with a threshold of {pct}%{when} — not taking the next {what}")

    if not out["take_next"]:
        print(out["reason"], file=sys.stderr)
    for w in warnings:
        print(w, file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["take_next"] else 2


if __name__ == "__main__":
    sys.exit(main())
