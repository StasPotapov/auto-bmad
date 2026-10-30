"""Scoped browser RPC: model sandboxes delegate tools, never arbitrary host commands."""

import json
from pathlib import Path
import re
import shutil
import shlex
import sys
import uuid
from urllib.parse import urlsplit

from agent_runtime import execute

COMMANDS = {"open", "goto", "ui", "click", "tap", "type", "key", "hover", "scroll", "back", "reload",
            "wait", "assert", "batch", "view", "tabs", "log", "style", "eval", "look", "shot", "close",
            "frames", "pull", "import", "compare", "board", "thumb", "status"}
OPTIONS = {"--size", "--theme", "--locale", "--max", "--quiet", "--all", "--find", "--href", "--expect",
           "--timeout", "--into", "--enter", "--keep-going", "--ui", "--switch", "--errors", "--grep",
           "--since", "--clear", "--props", "--max-chars", "--full", "--crop", "--width", "--viewport",
           "--out", "--name", "--project", "--file", "--artifact", "--version", "--all-html", "--lines",
           "--design", "--frame", "--site", "--site-frame", "--tol", "--color-tol", "--help"}


def prepare(broker, item):
    from verify import cli_skill
    from setup import web_app
    skill = cli_skill("mockmatch", str(broker.root), include_project=False)
    cli = Path(skill).parent / "bin/mockmatch" if skill else None
    if not cli or not cli.is_file() or cli.resolve().is_relative_to(broker.root):
        return None
    # The model may write a project-local skill; execute a protected snapshot of the CLI.
    snapshot = broker.private / (uuid.uuid4().hex + "-mockmatch")
    shutil.copyfile(cli, snapshot)
    snapshot.chmod(0o700)
    fields = dict(item["fields"])
    if not fields.get("serve") or not fields.get("url"):
        detected = web_app(str(broker.root)) or {}
        for name in ("serve", "url"):
            if not fields.get(name) and detected.get(name):
                fields[name] = detected[name]
    broker.verifier_tool = {"cli": str(snapshot), "fields": fields}
    path = broker.state / "mockmatch-tool"
    args = [str(broker.session_path), str(broker.manifest_path)]
    script = Path(__file__).resolve()
    path.write_text("#!" + sys.executable + "\nimport os,sys\nos.execv(" + repr(sys.executable) +
                    ", " + repr([sys.executable, str(script), *args]) + " + sys.argv[1:])\n")
    path.chmod(0o700)
    return path


def local_path(broker, value, *, artifacts=False):
    path = Path(value)
    protected = broker.private / "browser"
    relative = path
    if path.is_absolute() and path.is_relative_to(broker.root):
        relative = path.relative_to(broker.root)
    if not relative.is_absolute():
        candidates = [protected / relative]
        if relative.is_relative_to(".auto-bmad"):
            candidates.insert(0, protected / "exports" / relative.relative_to(".auto-bmad"))
        path = next((p for p in candidates if p.exists()), path)
    if not path.is_absolute():
        path = broker.root / path
    path = path.resolve()
    allowed = [broker.root / ".auto-bmad"] if artifacts else [broker.root]
    allowed.append(broker.private / "browser")
    if not any(path.is_relative_to(base) for base in allowed):
        raise ValueError("browser file path escapes the allowed project/artifact directory")
    return str(path)


def design(broker, value):
    if urlsplit(value).scheme in ("http", "https"):
        return value
    return local_path(broker, value)


def output_path(broker, value):
    path = Path(local_path(broker, value, artifacts=True))
    protected = broker.private / "browser"
    if path.is_relative_to(protected):
        return str(path)
    return str(protected / "exports" / path.relative_to(broker.root / ".auto-bmad"))


def argv(broker, arguments):
    config = broker.verifier_tool
    if not broker.verifying or not config or broker.session.get("writer") != "verifier":
        raise ValueError("browser tool is available only to the active verifier")
    if (not isinstance(arguments, list) or not 1 <= len(arguments) <= 128 or
            any(not isinstance(v, str) or "\0" in v for v in arguments) or
            sum(map(len, arguments)) > 256 * 1024):
        raise ValueError("invalid browser tool arguments")
    args = list(arguments)
    command = args[0]
    if command == "serve":
        from cli_verifier import SERVE
        if args[1:] == ["stop"]:
            return [sys.executable, str(SERVE), "stop"]
        # Only a project-configured server command crosses this boundary.
        fields = config["fields"]
        expected = {"--serve": fields.get("serve"), "--url": fields.get("url")}
        if len(args) not in (6, 8) or args[1] != "start":
            raise ValueError("serve requires start --serve COMMAND --url URL [--wait SECONDS]")
        options = dict(zip(args[2::2], args[3::2]))
        if (len(options) != (len(args) - 2) // 2 or set(options) - {*expected, "--wait"} or
                any(not value or options.get(key) != value for key, value in expected.items())):
            raise ValueError("browser server must match the configured serve and url fields")
        if "--wait" in options and (not options["--wait"].isdigit() or not 1 <= int(options["--wait"]) <= 90):
            raise ValueError("serve wait must be 1..90 seconds")
        return [sys.executable, str(SERVE), *args[1:]]
    if command not in COMMANDS or any(v.startswith("--") and v not in OPTIONS for v in args):
        raise ValueError("unsupported browser operation or option")
    if command in ("open", "goto", "pull") and (len(args) < 2 or urlsplit(args[1]).scheme not in ("http", "https")):
        raise ValueError("browser navigation requires an HTTP(S) URL")
    if "--site" in args:
        if args.count("--site") != 1:
            raise ValueError("duplicate browser site option")
        index = args.index("--site") + 1
        if index >= len(args) or urlsplit(args[index]).scheme not in ("http", "https"):
            raise ValueError("browser site requires an HTTP(S) URL")
    if command == "batch":
        index = 1
        while index < len(args):
            if args[index] in ("--ui", "--keep-going"):
                index += 1
                continue
            if args[index] == "--max":
                index += 2
                continue
            step = shlex.split(args[index])
            if not step or step[0] not in {"click", "tap", "type", "fill", "key", "scroll", "goto", "wait", "assert", "hover", "ui", "sleep"}:
                raise ValueError("unsupported browser batch step")
            if step[0] == "goto" and (len(step) < 2 or urlsplit(step[1]).scheme not in ("http", "https")):
                raise ValueError("browser batch navigation requires an HTTP(S) URL")
            index += 1
    if command == "frames" and len(args) > 1:
        args[1] = design(broker, args[1])
    if command in ("import", "thumb") and len(args) > 1:
        args[1] = local_path(broker, args[1])
    if command == "board" and len(args) > 1 and not args[1].startswith("--"):
        candidate = broker.private / "browser/build/mockmatch" / args[1]
        if re.fullmatch(r"[\w.-]+", args[1]) and candidate.is_dir():
            args[1] = str(candidate)
        args[1] = local_path(broker, args[1], artifacts=True)
    for flag in ("--out", "--design", "--name"):
        if args.count(flag) > 1:
            raise ValueError("duplicate browser path option")
        if flag in args:
            index = args.index(flag) + 1
            if index >= len(args):
                raise ValueError("missing browser path option value")
            if flag == "--out":
                args[index] = output_path(broker, args[index])
            elif flag == "--design":
                args[index] = design(broker, args[index])
            elif not re.fullmatch(r"[\w.-]+", args[index]) or ".." in args[index]:
                raise ValueError("browser artifact name must be a basename")
    if command == "shot" and (len(args) < 2 or not re.fullmatch(r"[\w.-]+", args[1]) or ".." in args[1]):
        raise ValueError("screenshot name must be a basename")
    if command in ("pull", "import") and "--out" not in args:
        args += ["--out", str(broker.private / "browser/design")]
    return [config["cli"], *args]


def run(broker, arguments):
    command = argv(broker, arguments)
    directory = broker.private / (uuid.uuid4().hex + "-browser-tool")
    env = {**broker.host_environment(), "MOCKMATCH_PROJECT": str(broker.private / "browser"),
           "AUTO_BMAD_MOCKMATCH_STATE_DIR": str(broker.private / "browser-server")}
    result = execute(command, cwd=str(broker.root), env=env, stdin="", directory=directory, timeout=120,
                     structured=False, consume=lambda _: None, finish=lambda code: {"execution_status": "completed"},
                     cancel=broker.stop, manage_signals=False, lease_fd=broker.lease_fd,
                     cleanup_session=broker.session_path, cleanup_on_exit=False)
    return {"execution_status": result["execution_status"], "code": result.get("exit_code"),
            "stdout": (directory / "stdout.jsonl").read_text(errors="replace"),
            "stderr": (directory / "stderr.log").read_text(errors="replace")}


def main():
    from story_broker import client
    session, manifest = sys.argv[1:3]
    # Request files live in writable runtime state; executable and policy stay on the host.
    info = json.loads(Path(session).read_text())
    path = Path(info["repo"]) / info["state_rel"] / (uuid.uuid4().hex + ".tool.json")
    path.write_text(json.dumps(sys.argv[3:]))
    try:
        result = client(session, manifest, "verify-tool", path)
    finally:
        path.unlink(missing_ok=True)
    if result.get("execution_status") != "completed":
        print(result.get("error", "browser tool did not complete"), file=sys.stderr)
        return 2
    print(result["stdout"], end="")
    print(result["stderr"], end="", file=sys.stderr)
    return result["code"] if type(result.get("code")) is int and 0 <= result["code"] <= 255 else 2


if __name__ == "__main__":
    sys.exit(main())
