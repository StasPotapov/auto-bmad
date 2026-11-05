"""Project-defined test components selected from the complete story diff."""

import fnmatch
import hashlib
import json
from pathlib import Path
import re
import shlex
import time

from common import git
from agent_runtime import atomic_json


def settings(cfg):
    value = cfg.get("project_tests", {})
    if not isinstance(value, dict) or set(value) - {"scopes", "ignore", "baseline", "fallback", "development", "build", "full_paths", "full_patterns", "full_on_multiple"}:
        raise ValueError("unknown project_tests fields")
    for field in ("full_paths", "full_patterns"):
        patterns = value.get(field, [])
        if not isinstance(patterns, list) or not all(isinstance(p, str) and p for p in patterns):
            raise ValueError(f"project_tests.{field} must contain patterns")
    for pattern in value.get("full_patterns", []):
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValueError("invalid project_tests.full_patterns regex") from e
    if type(value.get("full_on_multiple", False)) is not bool:
        raise ValueError("project_tests.full_on_multiple must be boolean")
    scopes = value.get("scopes", {})
    if not isinstance(scopes, dict):
        raise ValueError("project_tests.scopes must be a table")
    ignored = value.get("ignore", [])
    if not isinstance(ignored, list) or not all(isinstance(p, str) and p for p in ignored):
        raise ValueError("project_tests.ignore must contain path patterns")
    if type(value.get("baseline", True)) is not bool:
        raise ValueError("project_tests.baseline must be boolean")
    if "fallback" in value:
        fallback = value["fallback"]
        if (not isinstance(fallback, dict) or set(fallback) - {"command", "timeout"}
                or not isinstance(fallback.get("command"), str) or not fallback["command"].strip()
                or "\0" in fallback["command"]
                or type(fallback.get("timeout", 1800)) is not int or fallback.get("timeout", 1800) <= 0):
            raise ValueError("project_tests.fallback requires a command and optional positive timeout")
    for name, item in scopes.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name) or not isinstance(item, dict):
            raise ValueError("invalid project test scope")
        if set(item) - {"paths", "command", "timeout"}:
            raise ValueError(f"unknown project test scope fields: {name}")
        paths = item.get("paths")
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p and not p.startswith("/") and ".." not in p.split("/") for p in paths):
            raise ValueError(f"{name}: paths must be nonempty repository-relative patterns")
        if not isinstance(item.get("command"), str) or not item["command"].strip() or "\0" in item["command"]:
            raise ValueError(f"{name}: a test command is required")
        if type(item.get("timeout", 1800)) is not int or item.get("timeout", 1800) <= 0:
            raise ValueError(f"{name}: timeout must be a positive integer")
    builds = value.get("build", {})
    if not isinstance(builds, dict):
        raise ValueError("project_tests.build must be a table")
    for name, item in builds.items():
        if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name) or not isinstance(item, dict)
                or set(item) - {"command", "timeout"} or not isinstance(item.get("command"), str)
                or not item["command"].strip() or "\0" in item["command"]
                or type(item.get("timeout", 1800)) is not int or item.get("timeout", 1800) <= 0):
            raise ValueError("build checks require a registered command and positive timeout")
    development = value.get("development", {})
    if not isinstance(development, dict):
        raise ValueError("project_tests.development must be a table")
    for name, item in development.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name) or not isinstance(item, dict):
            raise ValueError("invalid development test check")
        if set(item) - {"command", "targets", "timeout"}:
            raise ValueError(f"unknown development test fields: {name}")
        if not isinstance(item.get("command"), str) or not item["command"].strip() or "\0" in item["command"]:
            raise ValueError(f"{name}: a development test command is required")
        targets = item.get("targets")
        if (not isinstance(targets, list) or not targets or not all(isinstance(p, str) and p
                and not p.startswith(("/", "-")) and ".." not in p.split("/") for p in targets)):
            raise ValueError(f"{name}: targets must be repository-relative file patterns")
        if type(item.get("timeout", 1800)) is not int or item.get("timeout", 1800) <= 0:
            raise ValueError(f"{name}: timeout must be a positive integer")
    return value


def development_command(repo, item, targets):
    """Only file/node selectors can extend a registered host command, never options or shell code."""
    if not isinstance(targets, list) or not targets or len(targets) > 100:
        raise ValueError("development checks require 1–100 --target file or node selectors")
    root = Path(repo).resolve()
    for target in targets:
        if not isinstance(target, str) or any(c in target for c in "\0\n\r"):
            raise ValueError("invalid test target")
        rel = target.split("::", 1)[0]
        path = root / rel
        if (not rel or rel.startswith(("/", "-")) or ".." in rel.split("/")
                or not matches(rel, item["targets"]) or not path.is_file()
                or not path.resolve().is_relative_to(root) or path.is_symlink()):
            raise ValueError("test target must be an existing allowed file inside the project")
    return item["command"] + " " + shlex.join(targets)


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def enabled(cfg):
    return bool(settings(cfg).get("scopes")) and any(
        c.get("name") == "project-tests" and c.get("kind") == "command"
        and c.get("enabled", True) is not False for c in cfg.get("verify", []))


def ignored(path, cfg):
    if matches(path, cfg.get("full_paths", [])):
        return False
    return path.startswith(("_bmad-output/", ".auto-bmad/")) or matches(path, cfg.get("ignore", []))


def files(repo, base):
    proc = git(str(repo), "diff", "--no-renames", "--name-only", "-z", base, "--")
    other = git(str(repo), "ls-files", "--others", "--exclude-standard", "-z")
    if proc.returncode or other.returncode:
        raise ValueError("cannot determine the complete test scope diff")
    return sorted(set(filter(None, (proc.stdout + other.stdout).split("\0"))))


def select(cfg, changed):
    scopes = cfg.get("scopes", {})
    chosen = set()
    for path in changed:
        if matches(path, cfg.get("full_paths", [])):
            return full_selection(cfg)
        if ignored(path, cfg):
            continue
        owners = {name for name, item in scopes.items() if matches(path, item["paths"])}
        if not owners:
            return full_selection(cfg)
        chosen.update(owners)
    if len(chosen) > 1 and cfg.get("full_on_multiple"):
        return full_selection(cfg)
    return [name for name in scopes if name in chosen]


def full_selection(cfg):
    return ["@all"] if cfg.get("fallback") else list(cfg.get("scopes", {}))


def shared_content(data, cfg):
    return any(re.search(pattern, data) for pattern in cfg.get("full_patterns", []))


def selection(repo, base, cfg):
    changed = files(repo, base)
    chosen = select(cfg, changed)
    if not cfg.get("full_patterns"):
        return chosen
    for rel in changed:
        if ignored(rel, cfg):
            continue
        diff = git(str(repo), "diff", "--no-ext-diff", "--no-textconv", "--unified=0", base, "--", rel)
        if diff.returncode:
            return full_selection(cfg)
        lines = "\n".join(line[1:] for line in diff.stdout.splitlines()
                          if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
        # Untracked files have no git diff; include them without following symlinks.
        tracked = git(str(repo), "ls-files", "--error-unmatch", "--", rel)
        path = Path(repo) / rel
        if tracked.returncode and path.is_file() and not path.is_symlink():
            lines += path.read_text(errors="replace")
        if shared_content(lines, cfg):
            return full_selection(cfg)
    return chosen


def fingerprint(repo, cfg, scope):
    proc = git(str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if proc.returncode:
        raise ValueError("cannot fingerprint test component inputs")
    digest = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode())
    for rel in sorted(set(filter(None, proc.stdout.split("\0")))):
        if ignored(rel, cfg):
            continue
        owners = {name for name, item in cfg["scopes"].items() if matches(rel, item["paths"])}
        path = Path(repo) / rel
        shared = matches(rel, cfg.get("full_paths", []))
        if owners and scope != "@all" and scope not in owners and not shared:
            if not (path.is_file() and not path.is_symlink()
                    and shared_content(path.read_text(errors="replace"), cfg)):
                continue
        digest.update(rel.encode() + b"\0")
        if path.is_symlink():
            digest.update(str(path.readlink()).encode())
        elif path.is_file():
            digest.update(str(path.stat().st_mode).encode())
            digest.update(path.read_bytes())
        elif not path.exists():
            digest.update(b"deleted")
        else:
            from execution_state import fingerprint as complete_fingerprint
            digest.update(complete_fingerprint(Path(repo)).encode())
    return digest.hexdigest()


def signature(result, root):
    text = result.get("tail", "").replace(str(root), "<project>")
    lines = []
    for line in text.splitlines():
        if re.search(r"\b\d+ (?:failed|passed|skipped|errors?|warnings?)\b", line):
            line = re.sub(r"\bin \d+(?:\.\d+)?s\b", "in <duration>s", line)
        line = re.sub(r"^(Ran \d+ tests? in )\d+(?:\.\d+)?s$", r"\1<duration>s", line)
        lines.append(line)
    return result.get("code"), "\n".join(lines)


def completed(result):
    return type(result.get("code")) is int and result["code"] >= 0


def classify_baseline(result, before, baseline_root, root):
    if (before and completed(before) and before.get("verdict") == result.get("verdict") == "problem"
            and signature(before, baseline_root) == signature(result, root)):
        return {**result, "verdict": "skipped", "baseline_equivalent": True,
                "reason": "same failure on the exact pre-story baseline"}
    return result


class Runner:
    def __init__(self, repo, base, cfg, private, execute):
        self.repo = Path(repo)
        commit = git(str(repo), "rev-parse", "--verify", "--end-of-options", str(base) + "^{commit}")
        if commit.returncode:
            raise ValueError("scoped tests require an exact existing baseline commit")
        self.base = commit.stdout.strip()
        self.cfg, self.private, self.execute = settings(cfg), Path(private), execute
        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.baselines = {}
        self.baseline_root = self.private / "baseline-code"
        receipt = self.private / "baselines.json"
        if receipt.exists():
            stored = json.loads(receipt.read_text())
            if stored.get("base") == self.base and stored.get("config") == self.cfg:
                self.baselines = {name: result for name, result in stored["results"].items() if completed(result)}

    def baseline(self, name):
        if name in self.baselines:
            return self.baselines[name]
        if not self.baseline_root.exists():
            proc = git(str(self.repo), "worktree", "add", "--detach", str(self.baseline_root), self.base)
            if proc.returncode:
                raise ValueError(proc.stderr.strip() or "cannot prepare exact-base scoped tests")
        status = git(str(self.baseline_root), "status", "--porcelain")
        head = git(str(self.baseline_root), "rev-parse", "HEAD")
        if status.returncode or head.returncode or head.stdout.strip() != self.base or status.stdout.strip():
            raise ValueError("scoped test baseline has changes; it is preserved for inspection")
        item = self.cfg["fallback"] if name == "@all" else self.cfg["scopes"][name]
        result = self.execute(item["command"], item.get("timeout", 1800), self.baseline_root, name)
        status = git(str(self.baseline_root), "status", "--porcelain")
        head = git(str(self.baseline_root), "rev-parse", "HEAD")
        if status.returncode or head.returncode or head.stdout.strip() != self.base or status.stdout.strip():
            raise ValueError("baseline tests changed source files")
        if completed(result):
            self.baselines[name] = result
        atomic_json(self.private / "baselines.json", {"base": self.base, "config": self.cfg, "results": self.baselines})
        return result

    def run(self, force_full=False):
        started = time.monotonic()
        chosen = full_selection(self.cfg) if force_full else selection(self.repo, self.base, self.cfg)
        rows = {}
        for name in chosen:
            item = self.cfg["fallback"] if name == "@all" else self.cfg["scopes"][name]
            before = self.baseline(name) if self.cfg.get("baseline", True) else None
            result = self.execute(item["command"], item.get("timeout", 1800), self.repo, name)
            result = classify_baseline(result, before, self.baseline_root, self.repo)
            rows[name] = result
        verdict = "problem" if any(r["verdict"] == "problem" for r in rows.values()) else "pass" if any(r["verdict"] == "pass" for r in rows.values()) else "skipped"
        skipped = [{"scope": name, "reason": r.get("reason", "preexisting baseline failure")} for name, r in rows.items() if r["verdict"] == "skipped"]
        return {"verdict": verdict, "scopes": chosen, "checks": rows, "skipped": skipped,
                "seconds": round(time.monotonic() - started, 3), "reused": bool(rows) and all(r.get("reused") for r in rows.values()),
                "tail": "\n".join(f"{name}: {r.get('tail', '')}" for name, r in rows.items() if r["verdict"] == "problem"),
                "reason": "no affected product files" if not rows else "; ".join(r["scope"] + ": " + r["reason"] for r in skipped) or None}
