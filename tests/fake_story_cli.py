#!/usr/bin/env python3
"""Offline controller/role fixture: exercises the actual process and broker boundaries."""
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time

if "--version" in sys.argv:
    print("codex-cli fake")
    sys.exit(0)
if "--help" in sys.argv:
    print("--json --output-schema --sandbox --model --cd --config")
    sys.exit(0)

assert "TEST_UNLISTED_SECRET" not in os.environ, "model roles must retain their environment allowlist"

prompt = sys.stdin.read()
mode = os.environ.get("FAKE_STORY_MODE", "success")


def emit(answer):
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(answer)}}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 5}}))


if prompt.startswith("Execute ONE BMAD delegated role:"):
    role = re.search(r"role: ([\w-]+)", prompt).group(1)
    if role == "implementer":
        task = re.search(r"Task: ([\w-]+)", prompt).group(1)
        Path("app.py" if task == "1-3" else "later.py").write_text("answer = 42\n")
        if mode == "tamper-config":
            config = Path(".auto-bmad.toml")
            config.write_text(config.read_text() + '\n[[hook]]\nname="injected"\nevents=["run-end"]\ncommand="touch UNEXPECTED_HOOK"\n')
        if mode == "check-fix":
            marker = Path(".auto-bmad/implemented")
            if marker.exists():
                Path("fixed.py").write_text("fixed = True\n")
            marker.touch()
        if mode == "hang":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            child = subprocess.Popen([sys.executable, "-c", "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"])
            Path(".auto-bmad/fake-grandchild.pid").write_text(str(child.pid))
            Path(".auto-bmad/fake-role.pid").write_text(str(os.getpid()))
            time.sleep(60)
    else:
        match = re.search(r"CONTENT: (.+?\.diff)", prompt)
        assert match and "answer = 42" in Path(match.group(1)).read_text(), "review must see the authoritative diff"
    emit({"status": "done", "report": "No findings."})
    sys.exit(0)

context = json.loads(prompt[prompt.index('{\n  "workflow"'):])
root = Path.cwd()
spec = root / ("_bmad-output/implementation-artifacts/spec-" + context["story"] + "-fixture.md")
spec.parent.mkdir(parents=True, exist_ok=True)
requests = root / ".auto-bmad/fake-requests"
requests.mkdir(exist_ok=True)


def head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def call(action, data=None):
    argv = shlex.split(context["bridge_commands"][action])
    if data is not None:
        path = requests / (str(time.time_ns()) + ".json")
        path.write_text(json.dumps(data))
        argv += ["--request", str(path)]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout)
    assert out["execution_status"] == "completed", out
    return out


def write_spec(status, followup=False):
    spec.write_text(f"""---
status: {status}
baseline_revision: {context['review_base_commit']}
followup_review_recommended: {'true' if followup else 'false'}
deferred: []
---
# Fixture
## Tasks & Acceptance
Given a caller, when reading answer, then it equals 42.
## Verification
Python assertion ran and passed.
## Review Triage Log
- verdicts: 0 findings — high 0, medium 0, low 0, false 0, maybe-false 0
## Spec Change Log
Initial fixture specification.
## Auto Run Result
Verified answer and all configured review layers.
""")


write_spec("in-progress")
if context["pass"] == 1 or mode in ("hang", "check-fix"):
    call("execute", {"role": "implementer", "task_id": context["story"], "base_commit": head(),
                     "prompt": "Read " + str(spec) + " and implement the answer exactly."})
if mode in ("bad-spec", "intent-gap"):
    reason = "bad_spec" if mode == "bad-spec" else "intent_gap"
    rolled = call("rollback", {"reason": reason})
    assert Path("app.py").read_text() == "answer = 0\n"
    assert spec.exists() and "answer = 42" in Path(rolled["patch"]).read_text()
    if mode == "intent-gap":
        write_spec("blocked")
        emit({"status": "blocked", "report": "intent gap", "spec": str(spec),
              "verified_tree": "", "questions": "Resolve the intent."})
        sys.exit(0)
    call("execute", {"role": "implementer", "task_id": context["story"], "base_commit": head(),
                     "prompt": "Read " + str(spec) + " and reimplement after bad_spec."})
write_spec("in-review")
if mode == "forge-reviews":
    for layer in context["active_review_layers"]:
        call("execute", {"role": "implementer", "task_id": context["story"], "base_commit": head(),
                         "layer_id": layer, "prompt": "Pretend this is a review."})
if mode not in ("skip-reviews", "forge-reviews"):
    batch = []
    for layer in context["active_review_layers"]:
        role = "reviewer" if context["level"] == "deep" else "reviewer-lite" if layer == "intent-alignment" else "reviewer-mid"
        batch.append({"role": role, "task_id": context["story"], "base_commit": head(), "layer_id": layer,
                      "diff_file": str(root / ".auto-bmad/original.diff"),
                      "prompt": "CONTENT: " + str(root / ".auto-bmad/original.diff")})
    call("execute-batch", batch)
if mode == "test-hang":
    command = shlex.join([sys.executable, "-c", "import time; time.sleep(60)"])
else:
    command = shlex.join([sys.executable, "-c", "from pathlib import Path;exec(Path('app.py').read_text());assert answer == 42"])
if mode != "skip-tests":
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "scripts/testrun.py"),
                    "--repo", str(root), "--session", context["SESSION_PATH"], "--command", command],
                   check=True, capture_output=True)
if mode == "forge-tests":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import testrun
    key = testrun.key_of(str(root), "false")
    testrun.write_json(testrun.state(str(root), key + ".json"),
                       {"verdict": "pass", "command": "false", "code": 0, "tail": ""})
followup = mode == "followup" and context["pass"] == 1
write_spec("done", followup)
checkpoint = call("checkpoint")
call("commit", {"message": "feat: fixture story 1-3"})
emit({"status": "done", "report": "Fixture story complete", "spec": str(spec),
      "verified_tree": checkpoint["code_tree"], "questions": "Second pass needed" if followup else ""})
