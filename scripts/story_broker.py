"""Per-run file rendezvous: the controller owns all role launches and write handoffs."""

from concurrent.futures import ThreadPoolExecutor
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
import subprocess
import sys
import shlex

import agent_dispatch
from agent_runtime import atomic_json, execute, environment
from common import ARTIFACTS, frontmatter, is_story_spec, parse_story
from worktree import uncommitted
from execution_state import canonical, revision, ControllerWatch
import testrun
import cli_stats


def checked_session(path, manifest):
    path = Path(path).resolve(strict=True)
    data = json.loads(Path(manifest).read_text())
    root, common = canonical(data["repo"])
    if not path.is_relative_to(common / "auto-bmad-sessions") or path.name != "session.json":
        raise ValueError("session must be issued by the controller in shared Git metadata")
    session = json.loads(path.read_text())
    if session["repo"] != str(root) or session["manifest_hash"] != hashlib.sha256(Path(manifest).read_bytes()).hexdigest():
        raise ValueError("session does not match the prepared manifest")
    return path, session, root, common


def client(session_path, manifest, action, request_path=None):
    session_path, session, root, common = checked_session(session_path, manifest)
    state = (root / session["state_rel"]).resolve(strict=True)
    if not state.is_relative_to(root / ".auto-bmad"):
        raise ValueError("invalid session state path")
    payload = json.loads(Path(request_path).read_text()) if request_path else None
    if action != "checkpoint" and payload is None:
        raise ValueError("role handoff requires --request")
    ticket = uuid.uuid4().hex
    atomic_json(state / "inbox" / (ticket + ".json"), {"action": action, "payload": payload})
    answer = session_path.parent / "outbox" / (ticket + ".json")
    watch = ControllerWatch(root, session_path)
    while True:
        if answer.exists():
            return json.loads(answer.read_text())
        live = json.loads(session_path.read_text())
        if live["status"] != "running":
            raise ValueError("controller session ended before the handoff completed")
        if not watch.alive():
            raise ValueError("controller is no longer active")
        time.sleep(0.05)


class Stop:
    def __init__(self, cancel_file):
        self.event = threading.Event()
        self.controller_done = threading.Event()
        self.cancel_file = cancel_file
        self.deadline = None

    def is_set(self):
        return self.event.is_set() or self.cancel_file.exists() or (
            self.deadline is not None and time.monotonic() >= self.deadline)


class Broker:
    def __init__(self, root, manifest_path, story, base, lease_fd):
        self.root, common = canonical(root)
        self.manifest = json.loads(Path(manifest_path).read_text())
        self.story, self.base, self.lease_fd = story, base, lease_fd
        self.id = uuid.uuid4().hex
        self.private = common / "auto-bmad-sessions" / self.id
        self.private.mkdir(parents=True, mode=0o700)
        self.manifest_path = self.private / "manifest.json"
        atomic_json(self.manifest_path, self.manifest)
        self.state = self.root / ".auto-bmad/runs" / self.id
        if not self.state.resolve().is_relative_to(self.root):
            raise ValueError("run state escapes the worktree")
        (self.state / "inbox").mkdir(parents=True, mode=0o700)
        (self.private / "outbox").mkdir(mode=0o700)
        self.session_path = self.private / "session.json"
        self.stop = Stop(self.private / "cancel")
        self.records = []
        self.checkpoints = []
        self.writer = threading.Lock()
        self.journal_lock = threading.Lock()
        self.active = set()
        self.passno = 0
        self.round = 0
        self.commits = []
        self.require_implementer = True
        self.initial_owned_paths = set()
        self.baseline_test_verdict = None
        self.test_records = {}
        self.blocked_reason = None
        self.config_env = os.environ.get("AUTO_BMAD_CONFIG")
        if self.config_env:
            self.config_env = os.path.abspath(self.config_env)
        self.host_env = {**os.environ, **self.environment(["PATH", "AUTO_BMAD_CONFIG"])}
        if self.host_env.get("AUTO_BMAD_EVENTS_FILE"):
            self.host_env["AUTO_BMAD_EVENTS_FILE"] = os.path.abspath(os.path.expanduser(self.host_env["AUTO_BMAD_EVENTS_FILE"]))
        self.session = {"schema_version": 1, "repo": str(self.root), "story": story, "status": "running",
                        "queue_id": os.environ.get("AUTO_BMAD_QUEUE_ID"),
                        "manifest_hash": hashlib.sha256(self.manifest_path.read_bytes()).hexdigest(),
                        "state_rel": str(self.state.relative_to(self.root)), "writer": "controller"}
        self.session.update(controller_pid=os.getpid(), liveness="pulse+flock")
        from verify import command_check
        self.session["test_command"], self.session["test_timeout"] = command_check(str(self.root), "project-tests")
        self.save()
        self.pulse_done = threading.Event()
        self.pulse()
        self.pulse_thread = threading.Thread(target=self.keep_alive, daemon=True)
        self.pulse_thread.start()

    def pulse(self):
        atomic_json(self.private / "pulse.json", {"at": time.monotonic()})

    def keep_alive(self):
        while not self.pulse_done.wait(0.1):
            try:
                self.pulse()
            except OSError:
                self.stop.event.set()
                return

    def environment(self, names):
        env = environment(names)
        if "PATH" in names:
            bin_dir = str(Path(__file__).resolve().parent.parent / "bin")
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", os.defpath)
        if "AUTO_BMAD_CONFIG" in names and self.config_env is not None:
            env["AUTO_BMAD_CONFIG"] = self.config_env
        return env

    def host_environment(self):
        return dict(self.host_env)

    def save(self):
        atomic_json(self.session_path, self.session)

    def cancelled(self):
        return self.stop.is_set() or self.stop.controller_done.is_set()

    def is_set(self):
        return self.cancelled()

    @contextlib.contextmanager
    def authorize(self, root, manifest, request):
        if root != self.root or manifest != self.manifest:
            raise ValueError("handoff does not belong to this story session")
        if request["task_id"] != self.story:
            raise ValueError(f"task_id must be the session story {self.story!r}, received {request['task_id']!r}; attempt IDs are assigned by the broker")
        if self.cancelled():
            raise ValueError("controller cancelled the handoff")
        readonly = request["role"] in agent_dispatch.REVIEWERS
        if not readonly and ("layer_id" in request or "diff_file" in request):
            raise ValueError("only reviewer roles may carry review layer fields")
        if readonly:
            layer = request.get("layer_id")
            layers = self.manifest.get("review_layers", [])
            if layer not in layers:
                raise ValueError("review handoff requires an active layer_id")
            expected = "reviewer" if manifest["level"] == "deep" else (
                "reviewer-lite" if layer == "intent-alignment" else "reviewer-mid")
            if request["role"] != expected:
                raise ValueError("review layer was routed to the wrong role")
        elif not self.writer.acquire(blocking=False):
            raise ValueError("another role already owns the writer lease")
        try:
            with self.journal_lock:
                if (readonly and self.writer.locked()) or (not readonly and self.active):
                    raise ValueError("writer and read-only leases must not overlap")
                self.active.add(threading.get_ident())
                self.session["writer"] = None if readonly else request["role"]
                self.save()
            yield root
        finally:
            with self.journal_lock:
                self.active.discard(threading.get_ident())
                self.session["writer"] = "controller" if not self.active else None
                self.save()
            if not readonly:
                self.writer.release()

    def handoff(self, request):
        if not isinstance(request, dict) or not isinstance(request.get("prompt"), str) or not request["prompt"].strip():
            raise ValueError("handoff must be an object")
        ticket = uuid.uuid4().hex
        data = None
        request = dict(request)
        request["prompt"] = request.get("prompt", "").replace("auto-bmad test", "auto-bmad test --session " + shlex.quote(str(self.session_path)))
        request["prompt"] += ("\nSession execution policy: do not commit, stage, reset, merge or push. "
                              "The controller owns Git finalization. All tests must use auto-bmad test --session " +
                              str(self.session_path) + "; all stubs must use --run " + self.id + ".")
        if request.get("role") in agent_dispatch.REVIEWERS:
            old = request.get("diff_file")
            if not isinstance(old, str) or not old or old not in request.get("prompt", ""):
                raise ValueError("review handoff must bind diff_file in its original prompt")
            diff = subprocess.run(["git", "-C", str(self.root), "diff", "--binary", self.base, "--"], capture_output=True)
            if diff.returncode:
                raise ValueError("cannot build the exact-base review diff")
            data = diff.stdout
            untracked = agent_dispatch.git(str(self.root), "ls-files", "--others", "--exclude-standard", "-z")
            if untracked.returncode:
                raise ValueError("cannot collect new review files")
            for rel in filter(None, untracked.stdout.split("\0")):
                part = subprocess.run(["git", "-C", str(self.root), "diff", "--no-index", "--binary", "--", "/dev/null", rel], capture_output=True)
                if part.returncode not in (0, 1):
                    raise ValueError("cannot include an untracked file in review")
                data += part.stdout
            bound = self.private / (ticket + ".diff")
            bound.write_bytes(data)
            request["prompt"] = request["prompt"].replace(old, str(bound))
            request["diff_file"] = str(bound)
        path = self.private / (ticket + ".request.json")
        atomic_json(path, request)
        result = agent_dispatch.dispatch(self.manifest_path, path, context=self, cancel=self,
                                         lease_fd=self.lease_fd)
        with self.journal_lock:
            record = {"pass": self.passno, "round": self.round, "request": request, "result": result,
                      "review_base": self.base, "diff_hash": hashlib.sha256(data).hexdigest() if data is not None else None}
            self.records.append(record)
            atomic_json(self.private / "roles.json", self.records)
        published = cli_stats.publish(self.root, self.session_path)
        if published.get("error"):
            with self.journal_lock:
                self.session["stats_error"] = published["error"]
                self.save()
        return result

    def command(self, argv, name, codes=(0,), timeout=60):
        directory = self.private / (uuid.uuid4().hex + "-" + name)
        result = execute(argv, cwd=str(self.root), env=self.host_environment(),
                         stdin="", directory=directory, timeout=timeout, structured=False, consume=lambda _: None,
                         finish=lambda code: {"execution_status": "completed" if code in codes else "failed"},
                         cancel=self.stop, manage_signals=False, lease_fd=self.lease_fd)
        if result["execution_status"] != "completed":
            raise ValueError(f"{name} {result['execution_status']}; inspect {directory}")
        return (directory / "stdout.jsonl").read_text()

    def tree(self):
        value = json.loads(self.command([sys.executable, str(Path(testrun.__file__).resolve()),
                                        "--tree", "--repo", str(self.root)], "tree"))["tree"]
        if not value:
            raise ValueError("cannot capture the code tree")
        return value

    def tests(self, command, timeout):
        """Host-only verification: writable agents cannot supply or replace its cache."""
        folder = self.root / ".auto-bmad/tests"
        if not folder.resolve().is_relative_to(self.root):
            raise ValueError("test state escapes the worktree")
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "lock").open("a") as lock:
            while True:
                if self.stop.is_set():
                    raise ValueError("run cancelled while waiting for the test lock")
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.05)
            tree = self.tree()
            key = (tree, command)
            if key in self.test_records:
                return {**self.test_records[key], "reused": True}
            directory = self.private / (uuid.uuid4().hex + "-verification")
            result = execute(["sh", "-c", command], cwd=str(self.root),
                             env=self.host_environment(),
                             stdin="", directory=directory, timeout=timeout or testrun.DEFAULT_TIMEOUT,
                             consume=lambda _: None, structured=False,
                             finish=lambda code: {"execution_status": "completed" if code == 0 else "failed"},
                             cancel=self.stop, manage_signals=False, lease_fd=self.lease_fd, lease_fds=(lock.fileno(),))
            if result["execution_status"] not in ("completed", "failed") or result.get("error"):
                raise ValueError(f"verification {result['execution_status']}; inspect {directory}")
            output = (directory / "stdout.jsonl").read_text(errors="replace") + (directory / "stderr.log").read_text(errors="replace")
            verdict = {"verdict": "pass" if result["execution_status"] == "completed" else "problem",
                       "code": result["exit_code"], "command": command, "seconds": result["seconds"],
                       "tail": "\n".join(output.splitlines()[-60:]), "log": str(directory), "reused": False}
            if tree == self.tree():
                self.test_records[key] = verdict
            atomic_json(self.private / "verified-tests.json", [{"code_tree": t, "command": c, "result": r}
                        for (t, c), r in self.test_records.items()])
            return verdict

    def spec(self):
        epic, num = parse_story(self.story)
        matches = [p for p in (self.root / ARTIFACTS).glob("spec-*.md") if is_story_spec(p.name, epic, num)]
        if len(matches) != 1 or matches[0].is_symlink() or not matches[0].resolve().is_relative_to(self.root):
            raise ValueError("story requires one unambiguous spec inside the worktree")
        return matches[0]

    def handle(self, envelope):
        if not isinstance(envelope, dict) or set(envelope) != {"action", "payload"}:
            raise ValueError("invalid broker envelope")
        action, payload = envelope.get("action"), envelope.get("payload")
        if action == "checkpoint":
            if self.blocked_reason:
                raise ValueError(self.blocked_reason)
            if payload is not None:
                raise ValueError("checkpoint takes no payload")
            if self.require_implementer and not any(r["pass"] == self.passno and r["round"] == self.round and
                    r["request"].get("role") == "implementer" and
                    r["result"].get("execution_status") == "completed" and
                    r["result"].get("result", {}).get("status") == "done" for r in self.records):
                raise ValueError("implementation did not complete through its delegated role")
            layers = {r["request"].get("layer_id") for r in self.records if r["pass"] == self.passno and r["round"] == self.round and
                      r["request"].get("role") in agent_dispatch.REVIEWERS and r.get("diff_hash") and r["review_base"] == self.base and
                      r["result"].get("execution_status") == "completed" and
                      r["result"].get("result", {}).get("status") == "done"}
            if not set(self.manifest["review_layers"]).issubset(layers):
                raise ValueError("required review layers have not all completed")
            tree = self.tree()
            command = self.session["test_command"]
            if command:
                proof = self.tests(command, self.session["test_timeout"])
                if proof["verdict"] != "pass" and self.baseline_test_verdict != "problem":
                    raise ValueError("configured verification did not pass")
                if self.tree() != tree:
                    raise ValueError("verification changed the code tree")
                atomic_json(self.private / f"verification-{self.passno}-{self.round}.json", {"code_tree": tree, "test": proof})
            result = {"execution_status": "completed", "code_tree": tree, "base_commit": self.base,
                      "head_commit": revision(self.root), "pass": self.passno}
            self.checkpoints.append(result)
            atomic_json(self.private / "checkpoints.json", self.checkpoints)
            return result
        if action == "rollback":
            if not isinstance(payload, dict) or payload.get("reason") not in ("intent_gap", "bad_spec") or set(payload) != {"reason"}:
                raise ValueError("rollback requires the engine route intent_gap or bad_spec")
            agent_dispatch.validate_manifest(self.manifest)
            if self.round >= {"fast": 1, "normal": 2, "deep": 3}[self.manifest["level"]]:
                raise ValueError("BMAD repair loop limit exhausted")
            owned = self.initial_owned_paths | {p for r in self.records for p in r["result"].get("changed_files", [])}
            tracked = agent_dispatch.git(str(self.root), "diff", "--name-only", "-z", self.base, "--", ".", ":(exclude)_bmad-output", ":(exclude).auto-bmad")
            fresh = agent_dispatch.git(str(self.root), "ls-files", "--others", "--exclude-standard", "-z", "--", ".", ":(exclude)_bmad-output", ":(exclude).auto-bmad")
            if tracked.returncode or fresh.returncode:
                raise ValueError("cannot inspect rollback paths")
            changed, new = set(filter(None, tracked.stdout.split("\0"))), set(filter(None, fresh.stdout.split("\0")))
            paths = changed | new
            if not paths.issubset(owned) or any((self.root / p).is_dir() or not (self.root / p).parent.resolve().is_relative_to(self.root) for p in paths):
                raise ValueError("rollback includes unowned paths or submodules; work is preserved")
            backup = subprocess.run(["git", "-C", str(self.root), "diff", "--binary", self.base, "--", ".", ":(exclude)_bmad-output", ":(exclude).auto-bmad"], capture_output=True)
            if backup.returncode:
                raise ValueError("cannot back up rollback")
            data = backup.stdout
            for rel in sorted(new):
                part = subprocess.run(["git", "-C", str(self.root), "diff", "--no-index", "--binary", "--", "/dev/null", rel], capture_output=True)
                if part.returncode not in (0, 1):
                    raise ValueError("cannot back up a new rollback file")
                data += part.stdout
            patch = self.root / ARTIFACTS / f"rollback-{self.id}-{self.passno}-{uuid.uuid4().hex}.patch"
            if not patch.parent.resolve().is_relative_to(self.root):
                raise ValueError("rollback backup escapes the worktree")
            patch.parent.mkdir(parents=True, exist_ok=True)
            patch.write_bytes(data)
            if changed:
                self.command(["git", "restore", "--source", self.base, "--worktree", "--",
                              *[":(literal)" + p for p in sorted(changed)]], "rollback")
            for rel in new:
                (self.root / rel).unlink()
            self.round += 1
            if payload["reason"] == "intent_gap":
                self.blocked_reason = "intent gap; resolve the saved questions before continuing"
            return {"execution_status": "completed", "patch": str(patch)}
        if action == "commit":
            agent_dispatch.validate_manifest(self.manifest)
            if not isinstance(payload, dict) or set(payload) != {"message"} or not isinstance(payload["message"], str) or not payload["message"].strip() or "\0" in payload["message"]:
                raise ValueError("commit requires a nonempty message")
            if not self.checkpoints or self.checkpoints[-1]["pass"] != self.passno or self.checkpoints[-1]["code_tree"] != self.tree():
                raise ValueError("code changed since the final verification checkpoint")
            path = self.spec()
            fields, _ = frontmatter(path)
            if fields.get("status") != "done" or fields.get("baseline_revision", fields.get("baseline_commit")) != self.base:
                raise ValueError("engine must finalize its spec and exact baseline before committing")
            dirty, error = uncommitted(str(self.root))
            if error:
                raise ValueError(error)
            if dirty:
                if any(p.startswith(".auto-bmad/") for p in dirty):
                    raise ValueError("runtime state must not be committed as story code")
                self.command(["git", "add", "-A", "--", *[":(literal)" + p for p in dirty]], "stage")
                self.command(["git", "commit", "-m", payload["message"]], "commit")
            record = {"pass": self.passno, "head_commit": revision(self.root), "code_tree": self.tree()}
            self.commits.append(record)
            atomic_json(self.private / "commits.json", self.commits)
            return {"execution_status": "completed", **record}
        if action == "execute":
            return self.handoff(payload)
        if action == "execute-batch":
            if not isinstance(payload, list) or not 1 <= len(payload) <= 8 or not all(
                    isinstance(p, dict) and p.get("role") in agent_dispatch.REVIEWERS for p in payload):
                raise ValueError("batch accepts 1..8 read-only reviewer handoffs")
            with ThreadPoolExecutor(max_workers=min(4, len(payload))) as pool:
                results = list(pool.map(self.handoff, payload))
            return {"execution_status": "completed" if all(r.get("execution_status") == "completed" and
                    r.get("result", {}).get("status") == "done" for r in results) else "failed", "results": results}
        raise ValueError("unknown broker action")

    def serve(self):
        inbox = self.state / "inbox"
        if inbox.is_symlink() or not inbox.resolve().is_relative_to(self.root):
            raise ValueError("broker inbox escaped the worktree")
        pending = [p for p in sorted(inbox.glob("*.json")) if not (self.private / "outbox" / p.name).exists()]
        if len(pending) > 1:
            raise ValueError("controller issued overlapping handoffs; use one read-only batch")
        for path in pending:
            if path.is_symlink() or len(path.stem) != 32 or any(c not in "0123456789abcdef" for c in path.stem):
                raise ValueError("invalid broker request path")
            answer = self.private / "outbox" / path.name
            if answer.exists():
                continue
            try:
                result = self.handle(json.loads(path.read_text()))
            except (OSError, ValueError, KeyError, TypeError) as e:
                result = {"execution_status": "failed", "error": str(e)}
            atomic_json(answer, result)

    def close(self, status):
        self.session.update(status=status, writer=None)
        self.save()
        self.pulse_done.set()
        self.pulse_thread.join()
