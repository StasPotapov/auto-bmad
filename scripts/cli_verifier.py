"""Host-owned post-story agent checks, using the same configured role transport."""

import json
from pathlib import Path
import re
import shlex
import sys
import threading
import uuid

from agent_runtime import atomic_json, execute
from execution_state import revision

ROOT = Path(__file__).resolve().parent.parent
SERVE = ROOT / "extensions/mockmatch/serve.py"
HEADERS = {"VERDICT", "MODE", "ARTIFACT", "FILES_LEFT", "CLEANUP", "SKIPPED_REASON", "PROBLEMS"}


def parse(report):
    fields, problems = {}, []
    collecting = False
    for line in report.splitlines():
        match = re.fullmatch(r"([A-Z_]+):\s*(.*)", line)
        if match and match[1] in HEADERS:
            key, value = match.groups()
            if key in fields:
                raise ValueError(f"duplicate verifier header: {key}")
            fields[key] = value.strip()
            collecting = key == "PROBLEMS"
        elif collecting:
            match = re.match(r"\s*(?:\d+[.)]|[-*])\s+(.+)", line)
            if match:
                problems.append(match[1])
            elif line.strip():
                collecting = False
    verdict = fields.get("VERDICT")
    if verdict not in ("pass", "problem", "skipped"):
        verdict = "skipped"
        fields["SKIPPED_REASON"] = "the check returned outside the contract"
    if verdict == "problem" and not problems:
        raise ValueError("verifier reported problem without actionable PROBLEMS")
    if verdict == "skipped" and not fields.get("SKIPPED_REASON"):
        fields["SKIPPED_REASON"] = "the check supplied no skip reason"
    return {"verdict": verdict, "problems": problems, "artifact": fields.get("ARTIFACT", "none"),
            "files_left": fields.get("FILES_LEFT", "none"), "cleanup": fields.get("CLEANUP", "none"),
            "reason": fields.get("SKIPPED_REASON"), "report": report}


def run(broker, item, target, answer, base, attempt, previous):
    instructions = Path(item.get("instructions") or "")
    if not instructions.is_absolute():
        instructions = broker.root / instructions
    if not instructions.is_file():
        raise ValueError(f"{item['name']}: missing verifier instructions: {instructions}")
    if instructions.resolve() == ROOT / "extensions/mockmatch/verify.md":
        broker.mockmatch_checked = True
    skill = item.get("skill_path")
    if item.get("skill") and (not skill or not Path(skill).is_file()):
        raise ValueError(f"{item['name']}: required CLI skill disappeared; plan again")
    from verifier_tools import prepare
    bridge = prepare(broker, item) if instructions.resolve() == ROOT / "extensions/mockmatch/verify.md" else None
    if instructions.resolve() == ROOT / "extensions/mockmatch/verify.md":
        atomic_json(broker.private / "verifier-cleanup.json", {
            "repo": str(broker.root), "project": str(broker.private / "browser"),
            "browser_cli": broker.verifier_tool["cli"] if bridge else None})
        if not bridge:
            return {"name": item["name"], "attempt": attempt, "verdict": "skipped", "problems": [],
                    "reason": "mockmatch needs a trusted user/plugin CLI installation outside the project", "artifact": "none"}
    fields = broker.verifier_tool["fields"] if bridge else item["fields"]
    budget = item.get("timeout")
    if budget is not None and (type(budget) is not int or budget <= 0):
        raise ValueError(f"{item['name']}: timeout must be a positive integer")
    prompt = f"""Check the story by the instructions and return a verdict by their contract.
Story: {broker.story} — {target['stories'][0]['title']}
Goal: {target['stories'][0].get('goal', '—')}
Base: {base}
Commit: {revision(broker.root)}
Check: {item['name']}
Instructions: {instructions.resolve()}
Project fields: {json.dumps(fields, ensure_ascii=False)}
Attempt: {attempt}
Previous problems: {json.dumps(previous, ensure_ascii=False)}
Project root: {broker.root}
Language: follow the language of the story report below.
Required skill: {skill or 'none'}
Read Instructions and the Required skill in full, including their referenced files as needed.
Skill/Read/Bash are actions using available file/command tools, not Claude tool names.
If a design service is unavailable, follow the instructions' saved-design fallback or report skipped with a reason.
Do not edit, stage or commit project files. Store all check artifacts under .auto-bmad/ (including browser output:
use the browser bridge below for mockmatch commands).
Run cleanup before returning; CLEANUP must be none, except the built-in mockmatch serve.py stop command.
Do not delegate: evaluate the small design crops yourself when a visual subagent is unavailable.
All stubs must use --run {broker.id}; stop your stubs before returning.
Never run a separate story or use the story controller broker commands.

How to check (original story report):
{answer['report']}
"""
    if bridge:
        prompt += f"""\nCLI browser integration (takes precedence over command paths in the skill):
The browser is a host tool. Keep the model sandbox unchanged. Every mockmatch command MUST use
MOCKMATCH={shlex.quote(str(bridge))} and then "$MOCKMATCH" <command> <args>. Do not invoke the original CLI.
Replace python3 <instructions>/serve.py <args> with "$MOCKMATCH" serve <args>.
The bridge supports only this check's configured server and mockmatch operations, without arbitrary host shell.
Use artifacts under .auto-bmad/; do not use --open or install packages.
Browser state and its generated boards are host-owned under the protected session/browser directory;
read the paths returned by the tool. Do not write that state directly.
Browser artifact root: {broker.private / 'browser'}
"""
    request = {"role": "verifier", "task_id": broker.story, "base_commit": revision(broker.root),
               "prompt": prompt, "check_name": item["name"]}
    broker.verifying, broker.verification_timeout = True, budget
    (broker.private / "tests-closed").unlink(missing_ok=True)
    result, errors = {}, []
    def dispatch():
        try:
            result.update(broker.handoff(request))
        except BaseException as e:
            errors.append(e)
    worker = threading.Thread(target=dispatch)
    worker.start()
    try:
        while worker.is_alive():
            broker.serve_verifier_tools()
            worker.join(0.05)
    finally:
        if worker.is_alive():
            broker.stop.event.set()
            worker.join()
        broker.verifying, broker.verification_timeout = False, None
        broker.verifier_tool = None
    if errors:
        raise errors[0]
    if result.get("execution_status") != "completed" or result.get("result", {}).get("status") != "done":
        raise ValueError(f"{item['name']}: verifier {result.get('execution_status')}; inspect {result.get('attempt')}")
    verdict = parse(result["result"]["report"])
    if bridge and verdict["artifact"].lower() != "none":
        from verifier_tools import local_path
        verdict["artifact"] = local_path(broker, verdict["artifact"])
    verdict.update(name=item["name"], attempt=attempt, role_attempt=result["attempt"])
    atomic_json(broker.private / f"check-{uuid.uuid4().hex}.json", verdict)
    cleanup = verdict["cleanup"]
    if cleanup.lower() != "none":
        try:
            args = shlex.split(cleanup)
        except ValueError as e:
            raise ValueError("invalid verifier cleanup command") from e
        if not (getattr(broker, "mockmatch_checked", False) and len(args) == 3 and Path(args[0]).name in ("python3", "python") and
                Path(args[1]).resolve() == SERVE and args[2] == "stop"):
            raise ValueError(f"{item['name']}: deferred cleanup is unsupported; the verifier must clean up before returning")
    return verdict


def cleanup(broker):
    """Also runs on a failed/cancelled verifier that never returned its CLEANUP header."""
    return cleanup_session(broker.session_path, broker.host_environment(), broker.lease_fd)


def cleanup_session(session, env=None, lease_fd=None):
    session = Path(session)
    path = session.parent / "verifier-cleanup.json"
    if not path.exists():
        return []
    config = json.loads(path.read_text())
    if config["repo"] != json.loads(session.read_text())["repo"]:
        raise ValueError("verifier cleanup belongs to another worktree")
    import os
    environment = {**(env if env is not None else os.environ), "MOCKMATCH_PROJECT": config["project"],
                   "AUTO_BMAD_MOCKMATCH_STATE_DIR": str(session.parent / "browser-server")}
    commands = [[sys.executable, str(SERVE), "stop"]]
    if config.get("browser_cli") and (Path(config["project"]) / "build/mockmatch/session.json").exists():
        commands.insert(0, [config["browser_cli"], "close"])
    problems = []
    for argv in commands:
        directory = session.parent / (uuid.uuid4().hex + "-browser-cleanup")
        result = execute(argv, cwd=config["repo"], env=environment, stdin="", directory=directory, timeout=10,
                         structured=False, consume=lambda _: None,
                         finish=lambda code: {"execution_status": "completed" if code == 0 else "failed"},
                         manage_signals=False, lease_fd=lease_fd)
        if result["execution_status"] != "completed":
            problems.append(f"browser cleanup failed; inspect {directory}")
    return problems
