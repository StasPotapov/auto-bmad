"""Mock Match's visual role on auto-bmad's verified Codex transport.

The browser bridge pauses its verifier while a read-only eyes process runs. The
host alone persists notes and rebuilds boards; no nested writer lease or RPC.
"""

import hashlib
import json
from pathlib import Path
import re
import threading
from types import SimpleNamespace
import uuid

import agent_adapters
import agent_config
from agent_dispatch import SCHEMA
from agent_runtime import atomic_json, execute


def command(broker, args):
    folder = broker.private / (uuid.uuid4().hex + "-eyes-tool")
    env = {**broker.host_environment(), "PYTHONDONTWRITEBYTECODE": "1",
           "MOCKMATCH_PROJECT": str(broker.private / "browser")}
    result = execute([broker.verifier_tool["cli"], *args], cwd=str(broker.root), env=env,
                     stdin="", directory=folder, timeout=30, structured=False,
                     consume=lambda _: None, finish=lambda code: {"execution_status": "completed"},
                     cancel=broker.stop, manage_signals=False, lease_fd=broker.lease_fd)
    if result["execution_status"] != "completed" or result.get("exit_code") != 0:
        raise ValueError(f"Mock Match {' '.join(args[:1])} failed; inspect {folder}")
    return (folder / "stdout.jsonl").read_text()


def settings(broker):
    config = broker.verifier_tool
    if "eyes_settings" in config:
        return config["eyes_settings"]
    # Retain the configured executor/account, but let the tool own its model/effort.
    base = broker.manifest["roles"]["verifier"]
    if base["adapter"] != "codex":
        raise ValueError("Mock Match eyes: this CLI transport is verified only for Codex")
    host = json.loads(command(broker, ["host", "--client", "codex"]))
    eyes = host["settings"]["eyes"]
    if not host.get("configured") or eyes.get("enabled") is not True:
        raise ValueError("configure Mock Match eyes with mockmatch setup --client codex")
    raw = {key: value for key, value in base.items() if key in agent_config.PROFILE_KEYS}
    raw.update(model=eyes["model"], permissions="read-only")
    raw.pop("effort", None)
    if eyes.get("effort"):
        raw["effort"] = eyes["effort"]
    raw["capability_requirements"] = list(dict.fromkeys([*raw.get("capability_requirements", []), "image_input"]))
    profile = agent_config.profile("mockmatch-eyes", raw)
    profile["profile_id"] = "mockmatch-eyes-" + hashlib.sha256(
        json.dumps(profile, sort_keys=True).encode()).hexdigest()[:12]
    prompt = Path(host["prompt"]).resolve(strict=True)
    package = Path(config["cli"]).resolve().parents[1]
    if not prompt.is_relative_to(package):
        raise ValueError("Mock Match eyes prompt escaped the trusted package")
    config["eyes_settings"] = (profile, prompt.read_text())
    return config["eyes_settings"]


def run_path(broker, stdout):
    rows = re.findall(r"^run (.+)  board: .+$", stdout, re.M)
    if not rows:
        raise ValueError("Mock Match compare returned no run")
    path = Path(rows[-1])
    if not path.is_absolute():
        path = broker.private / "browser" / path
    path = path.resolve(strict=True)
    base = (broker.private / "browser/build/mockmatch").resolve()
    if path.parent != base or path.is_symlink() or not (path / "report.json").is_file():
        raise ValueError("Mock Match compare run escaped the protected browser output")
    return path


def image_inputs(run):
    report = json.loads((run / "report.json").read_text())
    images, labels = [], []
    for cell in report["cells"]:
        name = cell["cell"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("invalid Mock Match cell")
        regions = cell["pixels"]["regions"]
        filenames = [region["crop"] for region in regions] if regions else ["overlay.png"]
        for filename in filenames:
            if not isinstance(filename, str) or not re.fullmatch(r"r[0-9]+\.png|overlay\.png", filename):
                raise ValueError("invalid Mock Match crop")
            path = (run / name / "diff" / filename).resolve(strict=True)
            if not path.is_relative_to(run) or not path.is_file():
                raise ValueError("Mock Match crop escaped the comparison run")
            images.append(path)
            region = next((region for region in regions if region["crop"] == filename), None)
            layout = region.get("layout", "layout unknown; report REVIEW") if region else "site overlay; red pixels differ"
            labels.append(f"{path.relative_to(run)}: {layout}. Magenta separator is not part of the UI.")
    if not images:
        raise ValueError("Mock Match compare produced no images for eyes")
    return images[:8], len(images), labels[:8]


def evaluate(broker, run, lines):
    profile, instructions = settings(broker)
    images, total_images, image_labels = image_inputs(run)
    detected = agent_adapters.detect(profile)
    agent_adapters.validate(profile, detected)
    attempt = broker.private / "attempts" / uuid.uuid4().hex
    attempt.mkdir(parents=True, mode=0o700)
    atomic_json(attempt / "schema.json", SCHEMA)
    request = {"role": "mockmatch-eyes", "task_id": broker.story, "prompt": instructions,
               "run": str(run), "model": profile["model"], "effort": profile.get("effort"),
               "images": [str(path) for path in images]}
    atomic_json(attempt / "request.json", request)
    prompt = (instructions + "\n\nTask: " + broker.verifier_tool.get("eyes_task", broker.story) +
              "\nRun: " + str(run) + "\nMOCKMATCH: " + broker.verifier_tool["cli"] +
              "\nLines:\n" + lines + "\n\nAuto-bmad host adapter output contract:\n"
              "You run read-only. The following small crops/overlays are attached as images, in this order:\n" +
              "\n".join(image_labels) +
              f"\nAttached {len(images)} of {total_images} available images. This consumes your image budget; "
              "do not open other images. If relevant regions are not attached, report REVIEW for them, never MATCH. "
              "Do not edit files or run commands that write. Do not run the CLI, browser bridge, tests, "
              "other agents or access services. The host writes notes.md and rebuilds the board from your report. "
              "Return only JSON {status: done|blocked, report: string}. Inside report use the shared "
              "MATCH/PROBLEM/REVIEW lines and Summary. If images cannot be viewed, return blocked with the reason. "
              "Keep the supplied Task scope; unrelated existing differences are REVIEW, not story defects.")
    parser = agent_adapters.result_parser(profile)
    done = getattr(broker, "verifier_done", threading.Event())
    cancel = SimpleNamespace(is_set=lambda: broker.stop.is_set() or done.is_set())
    argv = agent_adapters.argv(profile, detected, str(broker.root), attempt / "schema.json", attempt / "answer.json")
    argv = argv[:-1] + [arg for path in images for arg in ("--image", str(path))] + [argv[-1]]
    result = execute(argv,
                     cwd=str(broker.root), env=broker.environment(profile["environment_allowlist"]),
                     stdin=prompt, directory=attempt / "process",
                     timeout=getattr(broker, "verification_timeout", None), idle_timeout=profile["timeout"],
                     consume=parser.consume, finish=parser.finish, cancel=cancel,
                     manage_signals=False, lease_fd=broker.lease_fd, snapshot=parser.snapshot,
                     lease_fds=(() if getattr(broker, "resource_fd", None) is None else (broker.resource_fd,)),
                     metadata={"role": "mockmatch-eyes", "adapter": profile["adapter"],
                               "model_requested": profile["model"], "effort": profile.get("effort"),
                               "profile_id": profile["profile_id"], "task_id": broker.story,
                               "check_name": "mockmatch"})
    result.update(role="mockmatch-eyes", model_requested=profile["model"], effort=profile.get("effort"),
                  profile_id=profile["profile_id"], attempt=str(attempt),
                  role_instruction_hash=hashlib.sha256(instructions.encode()).hexdigest(),
                  images=[str(path) for path in images])
    atomic_json(attempt / "result.json", result)
    answer = result.get("result", {})
    if result["execution_status"] != "completed" or answer.get("status") != "done":
        raise ValueError(f"Mock Match eyes did not complete; inspect {attempt}")
    report = answer.get("report")
    if not isinstance(report, str) or not report.strip() or len(report) > 16000:
        raise ValueError("Mock Match eyes returned an invalid report")
    if not re.search(r"^(?:MATCH|PROBLEM|REVIEW)\b", report, re.M):
        raise ValueError("Mock Match eyes returned no visual verdict")
    (run / "notes.md").write_text("# Verdict\n\n" + report.strip() + "\n")
    command(broker, ["board", str(run)])
    return profile, report


def compare_verdict(broker, response):
    """Attach the tool-owned independent result, never silently use the verifier."""
    broker.eyes_active = True
    try:
        run = run_path(broker, response["stdout"])
        profile, report = evaluate(broker, run, response["stdout"])
        response["stdout"] += (f"\nEYES: {profile['model']} / {profile.get('effort', 'inherit')}\n" + report + "\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        reason = str(error)
        broker.verifier_tool.setdefault("eyes_failures", []).append(reason)
        response["stdout"] += "\nEYES_UNAVAILABLE: " + reason + "\nVisual verification must be skipped.\n"
    finally:
        broker.eyes_active = False
