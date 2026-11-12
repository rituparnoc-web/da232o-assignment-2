"""Show what the VLM told the robot, step by step, in readable form.

Usage (from the repo root, project venv):
    my_env\\Scripts\\python.exe eval\\show_episode.py              # the last episode
    my_env\\Scripts\\python.exe eval\\show_episode.py --last 5     # the last 5 episodes
    my_env\\Scripts\\python.exe eval\\show_episode.py --list 20    # one line per episode (last 20)
    my_env\\Scripts\\python.exe eval\\show_episode.py ep_20261112_171618

Reads bridge/logs/episodes.csv and steps.csv. The camera image the model saw at each step is in
bridge/logs/frames/<episode_id>/<step>.jpg.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "bridge" / "logs"


def read(name: str) -> list[dict]:
    p = LOGS / name
    if not p.exists():
        sys.exit(f"{p} not found - run an episode first")
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def call(s: dict) -> str:
    args = ", ".join(s[k] for k in ("target", "object", "location") if s.get(k))
    return f"{s['action']}({args})"


def show(ep: dict, steps: list[dict]) -> None:
    ok = ep["success"] == "True"
    print("=" * 100)
    print(f"{ep['episode_id']}   [{ep['task_id']}]   {ep['backend']} / {ep['model']}   prompt {ep.get('prompt') or '-'}")
    print(f"TASK:   {ep['task']}")
    print(f"RESULT: {'SUCCESS' if ok else 'FAILED'} in {ep['steps']} steps - {ep['reason']}")
    print("-" * 100)
    for s in steps:
        res = "" if s["action"] == "done" else ("OK   " if s["unity_success"] == "True" else "FAIL ")
        res += s.get("unity_reason", "")
        valid = "" if s.get("valid") != "False" else "  [INVALID reply -> fallback]"
        print(f"{int(s['step']) + 1:>2}. {call(s):<44} {s['latency_ms']:>6} ms{valid}")
        if s.get("thought"):
            print(f"      thought: {s['thought']}")
        if res:
            print(f"      robot:   {res}")
        if s.get("error"):
            print(f"      error:   {s['error']}")
    frames = LOGS / "frames" / ep["episode_id"]
    if frames.exists():
        print(f"frames: {frames}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", nargs="?", help="episode id (default: the last one)")
    ap.add_argument("--last", type=int, default=1, help="show the last N episodes")
    ap.add_argument("--list", type=int, metavar="N", help="list the last N episodes, one line each")
    a = ap.parse_args()

    episodes = read("episodes.csv")
    if a.list:
        for e in episodes[-a.list:]:
            print(f"{e['episode_id']}  {e['task_id']:<6} {'OK  ' if e['success'] == 'True' else 'FAIL'} "
                  f"{e['steps']:>2} steps  {e['task'][:70]}")
        return

    by_ep: dict[str, list[dict]] = {}
    for s in read("steps.csv"):
        by_ep.setdefault(s["episode_id"], []).append(s)

    chosen = [e for e in episodes if e["episode_id"] == a.episode] if a.episode else episodes[-a.last:]
    if not chosen:
        sys.exit(f"episode {a.episode} not found (use --list to see ids)")
    for e in chosen:
        show(e, sorted(by_ep.get(e["episode_id"], []), key=lambda s: int(s["step"])))


if __name__ == "__main__":
    main()
