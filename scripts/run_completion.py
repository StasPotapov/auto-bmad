"""Local epic landing and durable final reports. Editorial questions never gate landing."""

from contextlib import nullcontext
import json
from pathlib import Path

from common import git, commit_paths, questions_file, QUESTIONS_MARKER, SPRINT_REL, key_story
from execution_state import canonical, lease, revision
import ext
import plan_run
import worktree
import testrun


def token_summary(repo, session):
    from stats import load
    from cli_stats import read
    identity = Path(session).parent.name
    groups, seen = {}, set()
    labels = {"story-runner": "StoryRunner", "implementer": "Implementer", "compiler-lite": "Compiler",
              "reviewer": "Reviewer", "reviewer-mid": "Reviewer", "reviewer-lite": "Reviewer",
              "triager": "Triager", "verifier": "Verifier"}
    for row in load(str(repo)):
        if row.get("queue_id") != identity and row.get("session") != "cli:" + identity:
            continue
        child = row.get("session", "").removeprefix("cli:")
        directory = Path(session).parent.parent / child
        manifest = read(directory / "manifest.json") if directory.resolve().parent == Path(session).resolve().parent.parent else {}
        for call in row.get("calls", []):
            if call["id"] in seen:
                continue
            seen.add(call["id"])
            name = call.get("model_observed") or call.get("model_requested") or "unavailable"
            raw_role = call.get("role", "unavailable")
            role = labels.get(raw_role, raw_role)
            profile = manifest.get("roles", {}).get(raw_role, {})
            effort = profile.get("effort", "unavailable") if profile.get("profile_id") and profile["profile_id"] == call.get("profile_id") else "unavailable"
            model = groups.setdefault((role, name, effort), {"role": role, "model": name, "effort": effort,
                                      "total": 0, "cached": 0, "calls": 0, "incomplete": 0,
                                      "measured": 0, "cache_measured": 0})
            usage = call.get("usage", {})
            model["calls"] += 1
            model["incomplete"] += int(call.get("usage_status") != "complete")
            model["measured"] += int(any(usage.get(key) is not None for key in ("input_tokens", "output_tokens")))
            model["cache_measured"] += int(usage.get("cached_input_tokens") is not None)
            model["total"] += sum(usage.get(key) or 0 for key in ("input_tokens", "output_tokens"))
            model["cached"] += usage.get("cached_input_tokens") or 0
    order = ["StoryRunner", "Implementer", "Compiler", "Reviewer", "Triager", "Verifier"]
    return sorted(groups.values(), key=lambda row: (order.index(row["role"]) if row["role"] in order else len(order),
                                                    row["role"], row["model"], row["effort"]))


def russian(language):
    return str(language or "").casefold() in ("ru", "ru-ru", "russian", "русский")


def token_table(rows, language=None):
    ru = russian(language)
    if not rows:
        return "Учёт токенов недоступен." if ru else "Token accounting unavailable."
    def number(value):
        if value >= 1_000_000:
            text = f"{value / 1_000_000:.2f}".rstrip("0").rstrip(".")
            return text.replace(".", ",") + " млн" if ru else text + "M"
        return f"{value / 1000:.0f}" + (" тыс." if ru else "k") if value >= 1000 else str(value)
    unknown = "нет данных" if ru else "unavailable"
    lines = ["| Роль (модель, effort) | Всего токенов | Из них кэш |" if ru else
             "| Role (model, effort) | Total tokens | Of which cached |", "|---|---:|---:|"]
    labels = {"gpt-6.1-sol": "GPT-6.1 Sol", "gpt-6-astra": "GPT-6 Astra", "gpt-6-luna": "GPT-6 Luna"}
    for row in rows:
        marker = "*" if row["incomplete"] else ""
        total = number(row['total']) + marker if row['measured'] else unknown
        cached = number(row['cached']) + marker if row['cache_measured'] else unknown
        lines.append(f"| {row['role']} ({labels.get(row['model'], row['model'])}, {row['effort']}) | {total} | {cached} |")
    incomplete = sum(row["incomplete"] for row in rows)
    marker = "*" if incomplete else ""
    total = number(sum(row['total'] for row in rows)) + marker if any(row['measured'] for row in rows) else unknown
    cached = number(sum(row['cached'] for row in rows)) + marker if any(row['cache_measured'] for row in rows) else unknown
    lines.append(f"| **{'Итого' if ru else 'Total'}** | **{total}** | **{cached}** |")
    lines.append("\nВсего: вход и выход; кэш уже включён. Модель и effort взяты из журнала вызова и сохранённого профиля." if ru else
                 "\nTotal includes input and output; cache is already included. Model and effort come from call records and saved profiles.")
    if incomplete:
        lines.append(f"*Учтена только измеренная часть: у {incomplete} вызовов неполные или отсутствующие данные." if ru else
                     f"*Measured subtotals only: {incomplete} calls have partial or unavailable usage.")
    return "\n".join(lines)


def clean(root):
    result = git(str(root), "status", "--porcelain", "--untracked-files=all")
    return result.returncode == 0 and not result.stdout.strip()


def target_snapshot(source):
    """Pin the checked-out main without switching the user's branch."""
    matches = [row for row in worktree.worktree_items(str(source)) if row.get("branch") == "main"]
    if len(matches) != 1:
        return {"error": "main must be checked out in exactly one local worktree"}
    root = Path(matches[0]["path"]).resolve()
    return {"path": str(root), "head": revision(root)}


def deferred_questions(out, hooks):
    questions = []
    for event in hooks:
        for result in event.get("results", []):
            if result.get("ask"):
                questions.append({"hook": result.get("name"), **result["ask"]})
    for story in out.get("stories", []):
        questions.extend(story.get("finish", {}).get("deferred_questions", []))
    for wave in out.get("waves", []):
        questions.extend(wave.get("finish", {}).get("deferred_questions", []))
    return questions


def save_questions(root, epic, session_id, questions):
    root = Path(root).resolve()
    if not questions:
        return None
    relative = questions_file(epic)
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("open questions path escapes the run worktree")
    marker = QUESTIONS_MARKER.format(epic=epic)
    text = path.read_text() if path.exists() else f"# Epic {epic} — open questions\n\n{marker}\n"
    if marker not in text:
        raise ValueError("open questions file is human-owned; hook questions retained in result.json")
    pending = git(str(root), "status", "--porcelain", "--", relative)
    if pending.returncode or pending.stdout.strip():
        raise ValueError("open questions file has pending edits; hook questions retained in result.json")
    heading = f"<!-- run-questions:{session_id} -->"
    if heading not in text:
        lines = [f"- {row.get('hook', 'hook')}: {row.get('question', json.dumps(row, ensure_ascii=False))}"
                 + ("\n  " + json.dumps(row["options"], ensure_ascii=False) if row.get("options") else "")
                 for row in questions]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + f"\n\n{heading}\n## Deferred hook questions\n\n" + "\n".join(lines) + "\n")
        _, error = commit_paths(str(root), [relative], f"docs: deferred questions for epic {epic}")
        if error:
            raise ValueError(error)
    return str(path)


def land(source, root, snapshot, out, verify_merge=None, cancelled=lambda: False):
    source, root = Path(source).resolve(), Path(root).resolve()
    if snapshot.get("error"):
        raise ValueError(snapshot["error"])
    if not out.get("run_completed") or out.get("remaining") or out.get("execution_status") != "completed":
        raise ValueError("epic did not complete; changes preserved")
    stories = out.get("stories", [])
    if not stories or not all(s.get("story_completed") for s in stories):
        raise ValueError("epic has unfinished stories")
    for story in stories:
        verification = story.get("verification", {})
        checks = verification.get("checks", {})
        if (story.get("skipped_checks") or verification.get("status") != "pass"
                or not checks or any(value != "pass" for value in checks.values())):
            raise ValueError(f"story {story['story']} has missing, skipped or failed checks")
        finish = story.get("finish", {})
        if not finish.get("ok") or finish.get("failed"):
            raise ValueError(f"story {story['story']} finalization did not complete")
    for wave in out.get("waves", []):
        verification = wave.get("verification", {})
        if len(wave["stories"]) > 1 and (verification.get("verdict") != "pass" or verification.get("skipped")):
            raise ValueError("merged wave has missing, skipped or failed checks")
    entries, error = plan_run.read_status(str(root / SPRINT_REL))
    epic_stories = [(key, state) for key, state in entries if key_story(key) and key_story(key)[0] == out["epic"]]
    if error or not epic_stories or any(state != "done" for _, state in epic_stories):
        raise ValueError("sprint tracking still has unfinished epic stories")
    target = Path(snapshot["path"])
    if canonical(source)[1] != canonical(target)[1]:
        raise ValueError("main worktree belongs to another repository")
    with (nullcontext() if target == source else lease(target)), lease(root):
        if git(str(target), "symbolic-ref", "--quiet", "HEAD").stdout.strip() != "refs/heads/main":
            raise ValueError("target worktree no longer has main checked out")
        target_head = revision(target)
        if revision(root) != out["head_commit"] or not clean(root) or not clean(target):
            raise ValueError("run or main worktree changed or has pending edits; changes preserved")
        head = out["head_commit"]
        if git(str(target), "merge-base", "--is-ancestor", target_head, head).returncode:
            before = testrun.tree_hash(str(root))
            merged = git(str(root), "merge-tree", "--write-tree", "--name-only", "--no-messages", head, target_head)
            if merged.returncode or not merged.stdout.splitlines():
                raise ValueError("merge conflict with main; branches preserved: " + merged.stdout[:500])
            commit = git(str(root), "commit-tree", merged.stdout.splitlines()[0], "-p", head, "-p", target_head,
                         "-m", f"merge: main into epic {out['epic']} before landing")
            if commit.returncode:
                raise ValueError("cannot create integration commit: " + commit.stderr[:500])
            advanced = git(str(root), "merge", "--ff-only", "--no-edit", commit.stdout.strip())
            if advanced.returncode:
                raise ValueError("cannot prepare integration worktree: " + advanced.stderr[:500])
            head = revision(root)
            out["head_commit"] = head
            after = testrun.tree_hash(str(root))
            if not before or not after:
                raise ValueError("cannot identify verified code tree")
            if before != after:
                if verify_merge is None:
                    raise ValueError("main changed product files; integration checks are required")
                checked = verify_merge(root, out["base_commit"])
                out["integration_verification"] = checked
                if checked.get("verdict") != "pass" or checked.get("skipped"):
                    raise ValueError("integration checks failed or were skipped; main preserved")
                if revision(root) != head or testrun.tree_hash(str(root)) != after or not clean(root):
                    raise ValueError("integration checks changed the verified tree; main preserved")
        if cancelled():
            raise ValueError("run cancelled before merge; main preserved")
        if revision(target) != target_head or not clean(target):
            raise ValueError("main changed during integration checks; main preserved")
        result = git(str(target), "merge", "--ff-only", "--no-edit", head)
        if result.returncode:
            raise ValueError("merge into main failed: " + (result.stderr or result.stdout).strip()[:500])
        if revision(target) != head or not clean(target):
            raise ValueError("main changed during merge; inspect preserved worktrees")
        return {"status": "merged", "branch": "main", "commit": head, "worktree": str(target)}


def finalize(source, root, snapshot, out, verify_merge=None, cancelled=lambda: False):
    out["merge"] = {"status": "not_requested"}
    if out.get("merge_policy") != "auto-main" or out.get("mode") != "epic":
        return
    if not out.get("run_completed"):
        out["merge"] = {"status": "not_merged", "reason": out.get("error") or out.get("reason") or "epic did not complete"}
        return
    try:
        out["merge"] = land(source, root, snapshot, out, verify_merge, cancelled)
    except (OSError, ValueError, KeyError, TypeError) as error:
        out["merge"] = {"status": "not_merged", "reason": str(error)}
        out.update(execution_status="needs_attention", run_completed=False, error=str(error))


def report(out):
    merge = out.get("merge", {})
    ru = russian(out.get("language"))
    status = {"completed": "завершён", "needs_attention": "нужна проверка", "blocked": "заблокирован",
              "cancelled": "отменён", "timed_out": "истёк срок", "failed": "ошибка", "window": "окно завершено",
              "stopped": "остановлен по команде"}.get(out["execution_status"], out["execution_status"])
    merged = {"merged": "влит в main", "not_merged": "не выполнено", "not_requested": "не запрошено"}.get(merge.get("status"), "не запрошено")
    message = (f"Эпик {out.get('epic')}: {status}. Готово историй: {out.get('done', 0)}; осталось: {out.get('left', 0)}. "
               f"Слияние: {merged}." if ru else
               f"Epic {out.get('epic')}: {out['execution_status']}. "
               f"Stories done: {out.get('done', 0)}; remaining: {out.get('left', 0)}. "
               f"Merge: {merge.get('status', 'not_requested')}.")
    lines = [message]
    if merge.get("commit"):
        lines.append(f"main: {merge['commit']}")
    if out.get("error") or out.get("reason"):
        lines.append(str(out.get("error") or out["reason"]))
    for story in out.get("stories", []):
        if story.get("questions"):
            lines.append(f"{story['story']}: {story['questions']}")
        for warning in story.get("finish", {}).get("warnings", []):
            lines.append(str(warning))
    for question in out.get("questions", []):
        lines.append(str(question.get("question", question)))
    for event in out.get("hooks", []):
        for hook in event.get("results", []):
            if hook.get("error") or not hook.get("ok", True):
                lines.append(f"Hook {hook.get('name')}: {hook.get('error') or hook.get('message') or 'failed'}")
    for key in ("questions_file", "worktree", "branch"):
        if out.get(key):
            label = {"questions_file": "Вопросы", "worktree": "Рабочая копия", "branch": "Ветка"}.get(key, key) if ru else key
            lines.append(f"{label}: {out[key]}")
    if "token_summary" in out:
        lines.append(token_table(out["token_summary"], out.get("language")))
    if out.get("statistics", {}).get("error"):
        lines.append("Token accounting error: " + out["statistics"]["error"])
    if out.get("notification_error"):
        lines.append(("Ошибка уведомления: " if ru else "Notification error: ") + out["notification_error"])
    return "\n\n".join(lines) + "\n"


def publish(private, out, cfg, root):
    """Notify only configured hooks, after the actual merge decision; never answer asks."""
    path = private / "report.md"
    out["report_file"] = str(path)
    out["message"] = report(out)
    path.write_text(out["message"])
    payload = ext.payload("run-result", str(root), {"message": out["message"], "session": out["session"],
                          "merge": out["merge"], "report_file": str(path)},
                          epic=out.get("epic"), status=out["execution_status"])
    results = [ext.run_hook(hook, payload, str(root)) for hook in cfg.get("hook", [])
               if "run-result" in hook.get("events", [])]
    ext.log_event(str(root), payload, results)
    if results:
        out["hooks"].append({"event": "run-result", "results": results})
        out["message"] = report(out)
        path.write_text(out["message"])
