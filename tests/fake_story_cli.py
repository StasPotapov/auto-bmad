#!/usr/bin/env python3
"""Offline controller/role fixture: exercises the actual process and broker boundaries."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
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
        if mode == "wave-rendezvous":
            common = Path(subprocess.check_output(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], text=True).strip())
            (common / ("wave-ready-" + task)).touch()
            until = time.monotonic() + 10
            while not all((common / ("wave-ready-" + s)).exists() for s in ("1-3", "1-4")):
                assert time.monotonic() < until, "wave workers must run concurrently"
                time.sleep(0.05)
        if mode == "wave-dependency" and task == "1-5":
            assert Path("app.py").read_text() == "answer = 42\n"
            assert Path("later.py").exists(), "the next wave must start from the integrated previous wave"
        implemented = "app.py" if task == "1-3" else "later.py" if task == "1-4" else "story-" + task + ".py"
        if "Repair in place" in prompt:
            assert Path(implemented).read_text() == "answer = 42\n# preserve working code\n"
            Path(implemented).write_text(Path(implemented).read_text() + "repaired = True\n")
        else:
            Path(implemented).write_text("answer = 42\n")
        if mode in ("host-tests", "host-tests-sandbox"):
            session = re.search(r"auto-bmad test --session (\S+)", prompt).group(1).rstrip(";")
            prefix = []
            if mode == "host-tests-sandbox":
                prefix = [shutil.which("codex"), "sandbox", "-C", str(Path.cwd()), "-P", ":workspace", "--"]
                probe = subprocess.run([*prefix, sys.executable, "-c", "import socket;s=socket.socket();s.bind(('127.0.0.1',0))"], capture_output=True)
                assert probe.returncode != 0, "the model sandbox must still block direct local binding"
            subprocess.run([*prefix, sys.executable, str(Path(__file__).resolve().parent.parent / "scripts/testrun.py"),
                            "--repo", str(Path.cwd()), "--session", session],
                           check=True, capture_output=True, text=True, timeout=20)
        if mode == "wave-conflict" and task == "1-4":
            Path("app.py").write_text("answer = 99\n")
        if mode == "tamper-config":
            config = Path(".auto-bmad.toml")
            config.write_text(config.read_text() + '\n[[hook]]\nname="injected"\nevents=["run-end"]\ncommand="touch UNEXPECTED_HOOK"\n')
        if mode in ("check-fix", "verifier-fix"):
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
    elif role == "triager":
        assert "Code repair routing policy" in prompt
        assert "unambiguous fix under existing requirements routes to patch even when nontrivial" in prompt
        assert "Ignore the other" not in prompt
        profile = re.search(r"Prepared triage profile: (.+)", prompt).group(1)
        assert "Code repair routing policy" in Path(profile).read_text()
        emit({"status": "done", "report": "[medium] [patch] confirmed implementation defect under unchanged AC"})
        sys.exit(0)
    elif role == "verifier":
        assert "Instructions:" in prompt and "Project fields:" in prompt and "How to check" in prompt
        Path(".auto-bmad/verifier-prompt.txt").write_text(prompt)
        if mode == "verifier-mutate":
            Path("app.py").write_text("answer = 999\n")
        if mode == "verifier-hang":
            Path(".auto-bmad/verifier-started").touch()
            time.sleep(60)
        if mode == "verifier-test":
            session = re.search(r"auto-bmad test --session (\S+)", prompt).group(1).rstrip(";")
            subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "scripts/testrun.py"),
                            "--repo", str(Path.cwd()), "--session", session, "--command", "true"],
                           check=True, capture_output=True, timeout=20)
        report = "VERDICT: pass\nARTIFACT: .auto-bmad/check.html\nFILES_LEFT: none\nCLEANUP: none"
        if mode in ("verifier-browser", "verifier-browser-hang"):
            match = re.search(r"^Instructions: (.+)$", prompt, re.M)
            serve = Path(match[1]).with_name("serve.py")
            page = Path(".auto-bmad/check-site")
            page.mkdir(parents=True, exist_ok=True)
            page.joinpath("index.html").write_text("<h1>Fixture answer 42</h1><button>Check</button>")
            fields = json.loads(re.search(r"^Project fields: (.+)$", prompt, re.M).group(1))
            cli = shlex.split(re.search(r"^MOCKMATCH=(.+?) and then", prompt, re.M).group(1))[0]
            prefix = ["codex", "sandbox", "-C", str(Path.cwd()), "-P", ":workspace", "--", cli]
            start = subprocess.run([*prefix, "serve", "start", "--serve", fields["serve"], "--url", fields["url"]],
                    capture_output=True, text=True, check=True)
            site = json.loads(start.stdout)
            commands = [["open", site["url"]], ["assert", "Fixture answer 42"], ["log", "--errors"]]
            if mode == "verifier-browser":
                commands.append(["close"])
            for command in commands:
                subprocess.run([*prefix, *command], check=True, capture_output=True, text=True, timeout=40)
            if mode == "verifier-browser-hang":
                Path(".auto-bmad/verifier-started").touch()
                time.sleep(60)
            report = "VERDICT: pass\nMODE: feature\nARTIFACT: none\nFILES_LEFT: none\nCLEANUP: " + site["cleanup"]
        if mode == "verifier-fix" and not Path("fixed.py").exists():
            report = "VERDICT: problem\nPROBLEMS:\n1. Browser assertion: expected repaired page."
        elif mode == "verifier-note":
            report = "VERDICT: problem\nARTIFACT: .auto-bmad/check.html\nPROBLEMS:\n1. Browser assertion failed."
        elif mode == "verifier-skipped":
            report = "VERDICT: skipped\nSKIPPED_REASON: browser dependencies unavailable"
        elif mode == "verifier-malformed":
            report = "I think it looks fine."
        elif mode == "verifier-cleanup":
            report = "VERDICT: pass\nCLEANUP: touch UNEXPECTED_CLEANUP"
        emit({"status": "done", "report": report})
        sys.exit(0)
    else:
        if mode == "review-host-tests":
            session = re.search(r"auto-bmad test --session (\S+)", prompt).group(1).rstrip(";")
            check = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "scripts/testrun.py"),
                                    "--repo", str(Path.cwd()), "--session", session],
                                   capture_output=True, text=True, timeout=20)
            assert check.returncode != 0 and "cannot run host project checks" in check.stdout
        match = re.search(r"CONTENT: (.+?\.diff)", prompt)
        assert match and "answer = 42" in Path(match.group(1)).read_text(), "review must see the authoritative diff"
    emit({"status": "done", "report": "No findings."})
    sys.exit(0)

context = json.loads(prompt[prompt.index('{\n  "workflow"'):])
if mode == "wave-partial" and context["story"] == "1-3":
    mode = "skip-reviews"
if mode == "wave-blocked" and context["story"] == "1-3":
    mode = "intent-gap"
root = Path.cwd()
spec = root / ("_bmad-output/implementation-artifacts/spec-" + context["story"] + "-fixture.md")
if mode == "early-block":
    emit({"status": "blocked", "report": "Required project access is unavailable.", "spec": "",
          "verified_tree": "", "questions": "Restore the required project access before implementation."})
    sys.exit(0)
spec.parent.mkdir(parents=True, exist_ok=True)
requests = root / ".auto-bmad/fake-requests"
requests.mkdir(exist_ok=True)


def head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def call(action, data=None, error=None):
    argv = shlex.split(context["bridge_commands"][action])
    if data is not None:
        path = requests / (str(time.time_ns()) + ".json")
        path.write_text(json.dumps(data))
        argv += ["--request", str(path)]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=45)
    if error:
        out = json.loads(result.stdout)
        assert out["execution_status"] == "failed" and error in out["error"], out
        return out
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
if context["pass"] == 1 or mode in ("hang", "check-fix", "verifier-fix"):
    call("execute", {"role": "implementer", "task_id": context["story"], "base_commit": head(),
                     "prompt": "Read " + str(spec) + " and implement the answer exactly."})
if mode in ("bad-spec", "intent-gap", "intent-gap-tamper"):
    reason = "bad_spec" if mode == "bad-spec" else "intent_gap"
    rolled = call("rollback", {"reason": reason})
    assert Path("app.py").read_text() == "answer = 0\n"
    assert spec.exists() and "answer = 42" in Path(rolled["patch"]).read_text()
    if mode in ("intent-gap", "intent-gap-tamper"):
        write_spec("blocked")
        if mode == "intent-gap-tamper":
            config = Path(".auto-bmad.toml")
            config.write_text(config.read_text() + '\n[[hook]]\nname="injected"\nevents=["story-blocked"]\ncommand="touch UNEXPECTED_HOOK"\n')
        emit({"status": "blocked", "report": "intent gap", "spec": str(spec),
              "verified_tree": "", "questions": "Resolve the intent."})
        sys.exit(0)
    call("execute", {"role": "implementer", "task_id": context["story"], "base_commit": head(),
                     "prompt": "Read " + str(spec) + " and reimplement after bad_spec."})
if mode in ("code-fix", "code-fix-delegated", "repair-budget", "repair-zero", "code-fix-triager"):
    Path("app.py").write_text("answer = 42\n# preserve working code\n")
    if mode == "code-fix-triager":
        before = Path("app.py").read_text()
        triaged = call("execute", {"role": "triager", "task_id": context["story"], "base_commit": head(),
                                  "prompt": "Triage confirmed implementation defect against " + str(spec)})
        assert "[patch]" in triaged["result"]["report"]
        assert Path("app.py").read_text() == before
    if mode == "repair-zero":
        call("repair", {"reason": "code_fix"}, error="limit exhausted")
        call("rollback", {"reason": "bad_spec"}, error="limit exhausted")
        write_spec("blocked")
        emit({"status": "blocked", "report": "Repair budget exhausted", "spec": str(spec),
              "verified_tree": "", "questions": "Raise repair_limits.review to allow repairs."})
        sys.exit(0)
    for i in range(3 if mode == "repair-budget" else 1):
        repaired = call("repair", {"reason": "code_fix"})
        assert repaired["repair_cycle"] == i + 1
        assert Path("app.py").read_text().startswith("answer = 42\n# preserve working code\n")
        if mode == "code-fix-delegated":
            call("execute", {"role": "implementer", "task_id": context["story"], "base_commit": head(),
                             "prompt": "Repair in place using " + str(spec) + ": add repaired=True; preserve current code."})
        else:
            with Path("app.py").open("a") as f:
                f.write(f"repair_{i} = True\n")
    if mode == "repair-budget":
        call("repair", {"reason": "code_fix"}, error="limit exhausted")
        call("rollback", {"reason": "bad_spec"}, error="limit exhausted")
        call("checkpoint", error="limit exhausted")
        write_spec("blocked")
        emit({"status": "blocked", "report": "Repair budget exhausted", "spec": str(spec),
              "verified_tree": "", "questions": "Remaining confirmed defect needs another repair cycle."})
        sys.exit(0)
if mode in ("test-mixed", "test-no-progress", "test-limit", "test-final-gate", "test-red-target"):
    if mode == "test-mixed":
        for _ in range(2):
            call("rollback", {"reason": "bad_spec"})
            call("execute", {"role": "implementer", "task_id": context["story"], "base_commit": head(),
                             "prompt": "Read " + str(spec) + " and reimplement after spec correction."})
        for _ in range(5):
            call("repair", {"reason": "code_fix"})
    def failed_check():
        run = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "scripts/testrun.py"),
                              "--repo", str(root), "--session", context["SESSION_PATH"],
                              "--name", "dev/fixture", "--target", "check_fixture.py"], capture_output=True, text=True)
        assert run.returncode in (0, 2), run.stdout + run.stderr
        return json.loads(run.stdout)
    observed = failed_check()
    call("repair", {"reason": "test_failure", "failure_id": "invented"}, error="host-issued")
    step = 0
    while observed["verdict"] == "problem":
        if observed.get("repair_blocked"):
            write_spec("blocked")
            emit({"status": "blocked", "report": observed["repair_blocked"], "spec": str(spec),
                  "verified_tree": "", "questions": "Repeated test failure without improvement."})
            sys.exit(0)
        if mode == "test-limit" and step == 10:
            call("repair", {"reason": "test_failure", "failure_id": observed["failure_id"]}, error="tests repair limit exhausted")
            write_spec("blocked")
            emit({"status": "blocked", "report": "tests repair limit exhausted", "spec": str(spec),
                  "verified_tree": "", "questions": "Eleventh test repair not allowed."})
            sys.exit(0)
        call("repair", {"reason": "test_failure", "failure_id": observed["failure_id"]})
        call("checkpoint", error="required review layers")
        call("repair", {"reason": "code_fix"}, error="rerun the same failed check")
        step += 1
        Path("app.py").write_text(f"answer = 42\nrepair_step = {step}\n")
        observed = failed_check()
        if mode == "test-red-target":
            break
if (context.get("post_check_repair") or {}).get("kind") == "tests":
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "scripts/testrun.py"),
                    "--repo", str(root), "--session", context["SESSION_PATH"], "--name", context["post_check_repair"]["check"]],
                   check=True, capture_output=True)
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
if mode == "repair-stale-reviews":
    call("repair", {"reason": "code_fix"})
    call("checkpoint", error="required review layers")
    call("execute-batch", batch)
if mode == "repair-unannounced-edit":
    Path("app.py").write_text("answer = 42\n# unreviewed change\n")
    call("checkpoint", error="required review layers")
    call("repair", {"reason": "code_fix"})
    call("execute-batch", batch)
if mode == "test-hang":
    command = shlex.join([sys.executable, "-c", "import time; time.sleep(60)"])
else:
    task = context["story"]
    implemented = "app.py" if task == "1-3" else "later.py" if task == "1-4" else "story-" + task + ".py"
    command = shlex.join([sys.executable, "-c", f"from pathlib import Path;exec(Path({implemented!r}).read_text());assert answer == 42"])
if mode != "skip-tests":
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "scripts/testrun.py"),
                    "--repo", str(root), "--session", context["SESSION_PATH"],
                    *([] if mode == "scoped-tests" else ["--command", command])],
                   check=True, capture_output=True)
if mode in ("host-tests", "host-tests-sandbox"):
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "scripts/testrun.py"),
                    "--repo", str(root), "--session", context["SESSION_PATH"]],
                   check=True, capture_output=True, text=True, timeout=20)
if mode == "forge-tests":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import testrun
    key = testrun.key_of(str(root), "false")
    testrun.write_json(testrun.state(str(root), key + ".json"),
                       {"verdict": "pass", "command": "false", "code": 0, "tail": ""})
followup = mode == "followup" and context["pass"] == 1
if mode == "editorial-question":
    assert "This run is autonomous: record non-blocking questions and continue" in prompt
    assert "Never rollback or HALT for that editorial question" in prompt
write_spec("done", followup)
if mode == "test-red-target":
    call("checkpoint", error="repaired checks must pass")
    write_spec("blocked")
    emit({"status": "blocked", "report": "repaired targeted check still red", "spec": str(spec),
          "verified_tree": "", "questions": "Full suite cannot hide a known failing repair check."})
    sys.exit(0)
if mode == "test-final-gate":
    call("checkpoint", error="configured verification did not pass")
    write_spec("blocked")
    emit({"status": "blocked", "report": "full final gate failed", "spec": str(spec),
          "verified_tree": "", "questions": "Targeted green must not bypass full tests."})
    sys.exit(0)
checkpoint = call("checkpoint")
if mode == "repair-stale-checkpoint":
    call("repair", {"reason": "code_fix"})
    call("commit", {"message": "must not commit"}, error="final verification checkpoint")
    call("execute-batch", batch)
    checkpoint = call("checkpoint")
call("commit", {"message": "feat: fixture story 1-3"})
emit({"status": "done", "report": "Fixture story complete", "spec": str(spec),
      "verified_tree": checkpoint["code_tree"], "questions": "Keep the authoritative copy; review its January example before merge."
      if mode == "editorial-question" else "Second pass needed" if followup else ""})
