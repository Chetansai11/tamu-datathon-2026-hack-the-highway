#!/usr/bin/env python3
"""Shared memory for every agent working on this challenge. Standard library only.

    python coord.py brief                         read this first, every session
    python coord.py claim --agent claude-1        take the top available task
    python coord.py search "mcts"                 has anyone tried this already?
    python coord.py tried "UCT rollouts" --outcome failed --why "too slow" --agent claude-1
    python coord.py done T3a1 --result "beats heuristic 71%" --agent claude-1

coord/events.jsonl is the source of truth: append-only, so history is never lost and
git can merge teammates' logs. coord/STATUS.md is rebuilt from it after every change.
Set COORD_AGENT to skip --agent. Works from any folder or git worktree of this repo.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

STALE_MINUTES = int(os.getenv("COORD_STALE_MINUTES", "45"))
OPEN, DOING, DONE, FAILED, BLOCKED = "todo", "doing", "done", "failed", "blocked"


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def local(ts: str) -> str:
    return parse_ts(ts).astimezone().strftime("%a %H:%M")


def age_minutes(ts: str) -> float:
    return (now() - parse_ts(ts)).total_seconds() / 60


def find_coord_dir() -> Path:
    """COORD_DIR, then the main checkout (so all worktrees share one board), then upward."""
    if os.getenv("COORD_DIR"):
        return Path(os.environ["COORD_DIR"])
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=10)
        if common.returncode == 0:
            candidate = Path(common.stdout.strip()).parent / "coord"
            if candidate.is_dir():
                return candidate
    except (OSError, subprocess.SubprocessError):
        pass
    for folder in [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parent]:
        if (folder / "coord").is_dir():
            return folder / "coord"
    raise SystemExit("No coord/ folder found. Run this inside a challenge folder.")


class Lock:
    """Cross-process lock. Exclusive file creation is atomic on Windows and Linux."""

    def __init__(self, folder: Path, timeout: float = 20, stale: float = 15):
        self.path, self.timeout, self.stale = folder / ".lock", timeout, stale

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except (FileExistsError, PermissionError):
                try:  # a process that died holding the lock must not freeze everyone
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise SystemExit("Board is locked. Try again in a moment.")
                time.sleep(0.02 + secrets.randbelow(30) / 1000)

    def __exit__(self, *exc):
        for _ in range(50):
            try:
                self.path.unlink(missing_ok=True)
                return
            except PermissionError:
                time.sleep(0.01)


def read_events(folder: Path) -> list[dict]:
    path = folder / "events.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a bad line must not take down the whole board
    seen, unique = set(), []
    for e in sorted(events, key=lambda x: (x["ts"], x["id"])):  # merges may interleave logs
        if e["id"] not in seen:
            seen.add(e["id"])
            unique.append(e)
    return unique


def replay(events: list[dict]) -> dict:
    s = dict(tasks={}, methods=[], decisions=[], scores=[], notes=[], activity=[])
    tasks = s["tasks"]
    for e in events:
        kind, who, ts = e["type"], e.get("agent", "?"), e["ts"]
        s["activity"].append(e)
        t = tasks.get(e.get("task"))
        if kind == "add":
            tasks[e["task"]] = dict(id=e["task"], title=e["title"], detail=e.get("detail", ""),
                                    priority=e.get("priority", 3), needs=e.get("needs", []),
                                    files=e.get("files", []), status=OPEN, owner=None, added_by=who,
                                    added=ts, beat=None, result=None, why=None, notes=[], history=[])
        elif t is None and kind in ("claim", "beat", "note", "done", "fail", "block", "release", "reopen"):
            continue
        elif kind == "claim":
            stale = t["status"] == DOING and age_at(t["beat"], ts) > STALE_MINUTES
            if t["status"] == OPEN or stale:  # first claim wins when logs merge
                if stale:
                    t["history"].append(f"taken from {t['owner']} after going stale")
                t.update(status=DOING, owner=who, beat=ts)
        elif kind == "beat" and t["owner"] == who:
            t["beat"] = ts
        elif kind == "note":
            t["notes"].append(dict(agent=who, ts=ts, text=e["text"]))
            if t["owner"] == who:
                t["beat"] = ts
        elif kind == "done":
            t.update(status=DONE, owner=who, result=e.get("result"), finished=ts)
        elif kind == "fail":
            t.update(status=FAILED, owner=who, why=e.get("why"), finished=ts)
        elif kind == "block":
            t.update(status=BLOCKED, why=e.get("why"))
        elif kind == "release":
            t.update(status=OPEN, owner=None, beat=None)
        elif kind == "reopen":
            t.update(status=OPEN, owner=None, beat=None, why=None)
        elif kind == "tried":
            s["methods"].append(dict(method=e["method"], outcome=e["outcome"], why=e.get("why", ""),
                                     score=e.get("score"), agent=who, ts=ts, task=e.get("task")))
        elif kind == "decide":
            s["decisions"].append(dict(title=e["title"], why=e.get("why", ""), agent=who, ts=ts))
        elif kind == "score":
            s["scores"].append(dict(name=e["name"], value=e["value"], metric=e.get("metric", ""),
                                    note=e.get("note", ""), agent=who, ts=ts))
    return s


def age_at(ts: str | None, reference: str) -> float:
    if not ts:
        return 0.0
    return (parse_ts(reference) - parse_ts(ts)).total_seconds() / 60


def is_stale(t: dict) -> bool:
    return t["status"] == DOING and t["beat"] and age_minutes(t["beat"]) > STALE_MINUTES


def overlaps(a: list[str], b: list[str]) -> bool:
    """File scopes clash if one is the same as, or inside, the other (src/ vs src/x.py)."""
    norm = lambda p: p.replace("\\", "/").rstrip("/")  # noqa: E731
    return any(x == y or x.startswith(y + "/") or y.startswith(x + "/")
               for x in map(norm, a) for y in map(norm, b))


def available(s: dict) -> list[dict]:
    tasks = s["tasks"]
    busy = [t for t in tasks.values() if t["status"] == DOING and not is_stale(t)]
    out = []
    for t in tasks.values():
        if not (t["status"] == OPEN or is_stale(t)):
            continue
        if any(tasks.get(n, {}).get("status") != DONE for n in t["needs"]):
            continue
        if any(overlaps(t["files"], b["files"]) for b in busy if b["id"] != t["id"]):
            continue
        out.append(t)
    return sorted(out, key=lambda t: (t["priority"], t["added"]))


# ---- STATUS.md ---------------------------------------------------------------

def goal_text(folder: Path) -> str:
    path = folder / "GOAL.md"
    return path.read_text(encoding="utf-8").strip() if path.exists() else "(GOAL.md is missing)"


def one_line(text) -> str:
    return " ".join(str(text or "").split()).replace("|", "/")


def render(s: dict, folder: Path) -> str:
    tasks = list(s["tasks"].values())
    by = lambda st: sorted((t for t in tasks if t["status"] == st), key=lambda t: (t["priority"], t["added"]))  # noqa: E731
    doing, todo, done, failed, blocked = by(DOING), by(OPEN), by(DONE), by(FAILED), by(BLOCKED)
    ready = {t["id"] for t in available(s)}
    bad = [m for m in s["methods"] if m["outcome"] == "failed"]
    good = [m for m in s["methods"] if m["outcome"] == "worked"]
    mixed = [m for m in s["methods"] if m["outcome"] not in ("failed", "worked")]
    o = ["<!-- Generated by coord.py. Don't edit: your changes are overwritten. Edit coord/GOAL.md for the goal. -->",
         "# Challenge status", "", f"Updated {now().astimezone().strftime('%a %H:%M')}. "
         f"**{len(done)} done, {len(doing)} in progress, {len(todo)} to do, {len(blocked)} blocked, {len(failed)} failed.**",
         "", "## Goal", "", goal_text(folder), "", "## In progress", ""]
    o += [f"- **{t['id']}** {t['title']} - {t['owner']}, active {local(t['beat'])}"
          + (" **STALE, can be taken over**" if is_stale(t) else "")
          + (f" (files: {', '.join(t['files'])})" if t["files"] else "") for t in doing] or ["- Nothing"]
    o += ["", "## What needs to be done", ""]
    for t in todo:
        state = "ready" if t["id"] in ready else "waiting"
        wait = f", needs {', '.join(t['needs'])}" if t["needs"] else ""
        o.append(f"- **{t['id']}** P{t['priority']} {t['title']} ({state}{wait})")
    if not todo:
        o.append("- Nothing queued")
    if blocked:
        o += ["", "## Blocked", ""] + [f"- **{t['id']}** {t['title']} - {one_line(t['why'])}" for t in blocked]
    o += ["", "## Done", ""]
    o += [f"- **{t['id']}** {t['title']} - {t['owner']}: {one_line(t['result'])}" for t in done] or ["- Nothing yet"]
    o += ["", "## Failed: don't repeat these without a new idea", ""]
    lines = [f"- {m['method']} - {one_line(m['why'])}" + (f" (score {m['score']})" if m["score"] is not None else "")
             + f" [{m['agent']}]" for m in bad]
    lines += [f"- Task {t['id']}: {t['title']} - {one_line(t['why'])} [{t['owner']}]" for t in failed]
    o += lines or ["- Nothing yet"]
    o += ["", "## Worked", ""]
    o += [f"- {m['method']} - {one_line(m['why'])}" + (f" (score {m['score']})" if m["score"] is not None else "")
          + f" [{m['agent']}]" for m in good] or ["- Nothing yet"]
    if mixed:
        o += ["", "## Unclear results", ""] + [f"- {m['method']} - {one_line(m['why'])} [{m['agent']}]" for m in mixed]
    o += ["", "## Decisions", ""]
    o += [f"- {d['title']} - {one_line(d['why'])} [{d['agent']}]" for d in s["decisions"]] or ["- None yet"]
    o += ["", "## Scoreboard", ""]
    if s["scores"]:
        o += ["| Name | Score | Metric | By | Note |", "|---|---|---|---|---|"]
        o += [f"| {one_line(r['name'])} | {r['value']} | {one_line(r['metric'])} | {r['agent']} | {one_line(r['note'])} |"
              for r in sorted(s["scores"], key=lambda r: r["ts"], reverse=True)[:25]]
    else:
        o.append("- No scores yet")
    return "\n".join(o) + "\n"


def write_status(s: dict, folder: Path) -> None:
    tmp = folder / f".status.{os.getpid()}.tmp"
    tmp.write_text(render(s, folder), encoding="utf-8")
    for _ in range(5):
        try:
            os.replace(tmp, folder / "STATUS.md")
            return
        except PermissionError:  # an editor may hold it open; the log is still correct
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)


def append(folder: Path, kind: str, agent: str, **fields) -> dict:
    """Call with the lock held."""
    event = dict(id=secrets.token_hex(5), ts=now().isoformat(timespec="milliseconds"),
                 type=kind, agent=agent, **fields)
    with (folder / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return event


def need_agent(args) -> str:
    agent = args.agent or os.getenv("COORD_AGENT")
    if not agent:
        raise SystemExit("Say who you are: --agent NAME, or set COORD_AGENT.")
    return agent


def get_task(s: dict, task_id: str) -> dict:
    t = s["tasks"].get(task_id)
    if t is None:
        raise SystemExit(f"No task {task_id}. See: python coord.py board")
    return t


def mutate(folder: Path, fn):
    with Lock(folder):
        s = replay(read_events(folder))
        result = fn(s)
        s = replay(read_events(folder))
        write_status(s, folder)
    return result


# ---- Commands ----------------------------------------------------------------

def show_task(t: dict) -> None:
    print(f"{t['id']} [P{t['priority']}] {t['title']}")
    if t["detail"]:
        print(f"  Detail: {t['detail']}")
    if t["files"]:
        print(f"  Only touch: {', '.join(t['files'])}")
    if t["needs"]:
        print(f"  Built on: {', '.join(t['needs'])}")
    for n in t["notes"][-4:]:
        print(f"  Note from {n['agent']}: {n['text']}")
    for h in t["history"]:
        print(f"  History: {h}")


def cmd_brief(args, folder):
    s = replay(read_events(folder))
    tasks = s["tasks"].values()
    print(goal_text(folder))
    print("\n--- IN PROGRESS (leave these alone) ---")
    for t in tasks:
        if t["status"] == DOING:
            flag = " [STALE]" if is_stale(t) else ""
            print(f"{t['id']} {t['title']} - {t['owner']}{flag}" + (f" files: {', '.join(t['files'])}" if t["files"] else ""))
    print("\n--- READY TO CLAIM ---")
    for t in available(s)[:10]:
        print(f"{t['id']} P{t['priority']} {t['title']}")
    print("\n--- DONE ---")
    for t in [x for x in tasks if x["status"] == DONE][-12:]:
        print(f"{t['id']} {t['title']}: {one_line(t['result'])}")
    print("\n--- FAILED (don't repeat without a new idea) ---")
    for m in [x for x in s["methods"] if x["outcome"] == "failed"][-15:]:
        print(f"{m['method']}: {one_line(m['why'])}")
    for t in [x for x in tasks if x["status"] == FAILED][-10:]:
        print(f"{t['id']} {t['title']}: {one_line(t['why'])}")
    print("\n--- WORKED ---")
    for m in [x for x in s["methods"] if x["outcome"] == "worked"][-10:]:
        print(f"{m['method']}: {one_line(m['why'])}")
    print("\n--- DECISIONS ---")
    for d in s["decisions"][-10:]:
        print(f"{d['title']}: {one_line(d['why'])}")
    if s["scores"]:
        print("\n--- LATEST SCORES ---")
        for r in s["scores"][-8:]:
            print(f"{r['name']}: {r['value']} {r['metric']}")


def cmd_board(args, folder):
    print(render(replay(read_events(folder)), folder))


def cmd_add(args, folder):
    agent = need_agent(args)

    def run(s):
        for n in args.needs:
            get_task(s, n)
        task = f"T{len(s['tasks']) + 1}{secrets.token_hex(1)}"  # stays unique across merged logs
        append(folder, "add", agent, task=task, title=args.title, detail=args.detail,
               priority=args.priority, needs=args.needs, files=args.files)
        return task
    print(f"Added {mutate(folder, run)}")


def cmd_claim(args, folder):
    agent = need_agent(args)

    def run(s):
        mine = [t for t in s["tasks"].values() if t["status"] == DOING and t["owner"] == agent and not is_stale(t)]
        if mine and not args.task:
            return mine[0], "already yours"
        if args.task:
            t = get_task(s, args.task)
            pool = available(s)
            if t["id"] not in {x["id"] for x in pool} and not args.force:
                reason = (f"{t['owner']} has it" if t["status"] == DOING else
                          f"it's {t['status']}" if t["status"] != OPEN else
                          "its dependencies aren't done, or its files are in use")
                raise SystemExit(f"Can't claim {t['id']}: {reason}.")
        else:
            pool = available(s)
            if not pool:
                return None, ""
            t = pool[0]
        append(folder, "claim", agent, task=t["id"])
        return t, "claimed"

    t, what = mutate(folder, run)
    if t is None:
        print("Nothing is available. Check `python coord.py brief`, then add what's most useful.")
        sys.exit(3)
    print(f"{agent}: {what}")
    show_task(t)


def task_event(kind):
    def cmd(args, folder):
        agent = need_agent(args)

        def run(s):
            t = get_task(s, args.task)
            if kind in ("beat", "release", "done", "fail") and t["status"] == DOING and t["owner"] != agent and not args.force:
                raise SystemExit(f"{t['id']} belongs to {t['owner']}. Use --force only if they've stopped.")
            if kind in ("done", "fail") and t["status"] in (DONE, FAILED):
                raise SystemExit(f"{t['id']} is already {t['status']}.")
            fields = {}
            if kind == "done":
                fields["result"] = args.result
            elif kind in ("fail", "block"):
                fields["why"] = args.why
            elif kind == "note":
                fields["text"] = args.text
            append(folder, kind, agent, task=t["id"], **fields)
            if kind == "fail":
                append(folder, "tried", agent, task=t["id"], method=args.method or t["title"],
                       outcome="failed", why=args.why)
        mutate(folder, run)
        print(f"{args.task}: {kind} recorded")
    return cmd


def cmd_tried(args, folder):
    agent = need_agent(args)
    mutate(folder, lambda s: append(folder, "tried", agent, method=args.method, outcome=args.outcome,
                                    why=args.why, score=args.score, task=args.task))
    print("Recorded")


def cmd_decide(args, folder):
    agent = need_agent(args)
    mutate(folder, lambda s: append(folder, "decide", agent, title=args.title, why=args.why))
    print("Recorded")


def cmd_score(args, folder):
    agent = need_agent(args)
    mutate(folder, lambda s: append(folder, "score", agent, name=args.name, value=args.value,
                                    metric=args.metric, note=args.note))
    print("Recorded")


def cmd_search(args, folder):
    q = args.query.lower()
    s = replay(read_events(folder))
    hits = [f"[{m['outcome']}] {m['method']}: {one_line(m['why'])}" for m in s["methods"]
            if q in f"{m['method']} {m['why']}".lower()]
    hits += [f"[task {t['status']}] {t['id']} {t['title']}: {one_line(t['result'] or t['why'])}"
             for t in s["tasks"].values() if q in f"{t['title']} {t['detail']} {t['why']} {t['result']}".lower()]
    hits += [f"[decision] {d['title']}: {one_line(d['why'])}" for d in s["decisions"]
             if q in f"{d['title']} {d['why']}".lower()]
    print("\n".join(hits) if hits else f"Nothing recorded about '{args.query}'. Go ahead.")


def cmd_log(args, folder):
    for e in read_events(folder)[-args.n:]:
        detail = e.get("title") or e.get("method") or e.get("result") or e.get("why") or e.get("text") or e.get("name") or ""
        print(f"{local(e['ts'])} {e['agent']:<14} {e['type']:<8} {e.get('task', ''):<7} {one_line(detail)[:90]}")


def cmd_worktree(args, folder):
    """A private checkout per agent, so agents can't overwrite each other's edits."""
    root = folder.parent
    target = root.parent / ".worktrees" / root.name / args.name
    branch = f"agent/{args.name}"
    if target.exists():
        print(target)
        return
    has_branch = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "-q", branch],
                                capture_output=True).returncode == 0
    cmd = ["git", "-C", str(root), "worktree", "add", str(target)] + ([branch] if has_branch else ["-b", branch])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr.strip() or "git worktree failed. Has the repo got a first commit?")
    print(target)


def main() -> None:
    ap = argparse.ArgumentParser(description="Shared task board for all agents.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *spec, agent=True):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        if agent:
            p.add_argument("--agent")
        for args_, kw in spec:
            p.add_argument(*args_, **kw)
        return p

    def a(*args_, **kw):
        return args_, kw

    force = a("--force", action="store_true")
    add("brief", cmd_brief, agent=False)
    add("board", cmd_board, agent=False)
    add("add", cmd_add, a("title"), a("--detail", default=""), a("--priority", type=int, default=3, help="1 is highest"),
        a("--needs", nargs="*", default=[]), a("--files", nargs="*", default=[]))
    add("claim", cmd_claim, a("task", nargs="?"), force)
    add("beat", task_event("beat"), a("task"), force)
    add("note", task_event("note"), a("task"), a("text"))
    add("done", task_event("done"), a("task"), a("--result", required=True), force)
    add("fail", task_event("fail"), a("task"), a("--why", required=True), a("--method"), force)
    add("block", task_event("block"), a("task"), a("--why", required=True))
    add("release", task_event("release"), a("task"), force)
    add("reopen", task_event("reopen"), a("task"))
    add("tried", cmd_tried, a("method"), a("--outcome", required=True, choices=["worked", "failed", "unclear"]),
        a("--why", required=True), a("--score"), a("--task"))
    add("decide", cmd_decide, a("title"), a("--why", required=True))
    add("score", cmd_score, a("name"), a("value"), a("--metric", default=""), a("--note", default=""))
    add("search", cmd_search, a("query"), agent=False)
    add("log", cmd_log, a("-n", type=int, default=30), agent=False)
    add("worktree", cmd_worktree, a("name"), agent=False)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args.fn(args, find_coord_dir())


if __name__ == "__main__":
    main()
