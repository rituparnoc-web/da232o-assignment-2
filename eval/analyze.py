"""Turn the bridge logs into the results table and charts (PLAN Phase 8, SPEC 13 AC5).

Usage (from the repo root, project venv):
    my_env\\Scripts\\python.exe eval\\analyze.py                      # all suite episodes
    my_env\\Scripts\\python.exe eval\\analyze.py --since 2026-11-12   # only runs from that date
    my_env\\Scripts\\python.exe eval\\analyze.py --latest             # last attempt per backend+task

Reads   bridge/logs/episodes.csv, bridge/logs/steps.csv, Assets/Tasks/tasks_room*.json
Writes  eval/results.md, eval/charts/success_by_tier.png, eval/charts/steps_by_tier.png
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "bridge" / "logs"
TASK_DIR = ROOT / "Unity (VLM Project)" / "Assets" / "Tasks"
OUT = ROOT / "eval"
TIERS = ["easy", "medium", "hard"]
NON_SUITE = {"", "FAKE", "IMAGE_TEST", "FREE"}

# Chart styling (dataviz reference palette, light mode; validated for these 2 slots)
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]   # fixed order, never cycled


def load_tasks() -> dict[str, dict]:
    tasks = {}
    for f in sorted(TASK_DIR.glob("tasks_room*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for t in data["tasks"]:
            tasks[t["id"]] = {**t, "room": data.get("room", f.stem)}
    return tasks


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def classify_failure(ep: dict, steps: list[dict]) -> str:
    r = ep["reason"].lower()
    if "bridge error" in r or "model backend" in r:
        return "infrastructure (bridge/model unreachable)"
    if "stopped by user" in r:
        return "stopped by user"
    if "model said done" in r:
        return "said done too early / wrong result"
    if "step limit" in r:
        fails = [s for s in steps if s.get("unity_success") == "False"]
        invalid = [s for s in steps if s.get("valid") == "False"]
        if len(invalid) >= max(2, len(steps) // 3):
            return "step limit: invalid replies"
        if fails:
            return "step limit: repeated failing actions"
        return "step limit: no progress / looping"
    return "other"


def action_failure_kind(reason: str) -> str:
    r = reason.lower()
    for key, label in [("out of reach", "out of reach"), ("closed", "container closed"),
                       ("gripper", "gripper full/empty"), ("holding", "gripper full/empty"),
                       ("no object", "unknown object"), ("not reachable", "navigation"),
                       ("no path", "navigation"), ("timed out", "navigation"),
                       ("already", "already in that state"), ("cannot be", "wrong object type"),
                       ("not an item", "wrong object type"), ("not executed", "model backend error")]:
        if key in r:
            return label
    return "other"


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "–"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="only episodes started on/after this ISO date/time")
    ap.add_argument("--latest", action="store_true", help="keep only the last attempt per backend+prompt+task")
    ap.add_argument("--tier", choices=TIERS, help="only tasks of this tier")
    a = ap.parse_args()

    tasks = load_tasks()
    episodes = [e for e in read_csv(LOGS / "episodes.csv") if e["task_id"] not in NON_SUITE and e["task_id"] in tasks]
    if a.since:
        episodes = [e for e in episodes if e["started"] >= a.since]
    for e in episodes:
        # prompt version: logged since 12 Nov (v3); older rows are v2 from 9 Nov 18:45, v1 before
        pv = e.get("prompt") or ("v2" if e["started"] >= "2026-11-09T18:45" else "v1")
        e["backend"] = f"{e['backend']} · prompt {pv}"
    if a.tier:
        episodes = [e for e in episodes if tasks[e["task_id"]]["tier"] == a.tier]
    if a.latest:
        last = {}
        for e in sorted(episodes, key=lambda e: e["started"]):
            last[(e["backend"], e["task_id"])] = e
        episodes = list(last.values())
    if not episodes:
        print("No suite episodes found (task ids from the task files). Run the suite first.")
        return

    steps_by_ep = defaultdict(list)
    for s in read_csv(LOGS / "steps.csv"):
        steps_by_ep[s["episode_id"]].append(s)

    for e in episodes:
        e["tier"] = tasks[e["task_id"]]["tier"]
        e["ok"] = e["success"] == "True"
        e["n_steps"] = int(e["steps"] or 0)
        e["steps_rows"] = steps_by_ep.get(e["episode_id"], [])

    backends = sorted({e["backend"] for e in episodes}, key=lambda b: (not b.startswith("kaggle"), b))
    models = {e["backend"]: e["model"] for e in episodes}

    # ---------------------------------------------------------------- summary per backend
    lines = ["# HabitatVLM results", ""]
    lines.append(f"Episodes: {len(episodes)}  ·  tasks: {len({e['task_id'] for e in episodes})}  ·  "
                 f"filter: {'since ' + a.since if a.since else 'all'}{', latest attempt only' if a.latest else ''}")
    lines += ["", "## Summary by backend", "",
              "| Backend | Model | Episodes | Success | Easy | Medium | Hard | Avg steps (successes) | Avg model latency / step | Invalid replies |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    summary = {}
    for b in backends:
        eps = [e for e in episodes if e["backend"] == b]
        rows = [s for e in eps for s in e["steps_rows"]]
        lat = [int(s["latency_ms"]) for s in rows if s.get("latency_ms", "").isdigit()]
        inv = sum(1 for s in rows if s.get("valid") == "False")
        succ = [e for e in eps if e["ok"]]
        tier_cells, tier_pct, tier_steps = [], {}, {}
        for t in TIERS:
            te = [e for e in eps if e["tier"] == t]
            ts = [e for e in te if e["ok"]]
            tier_cells.append(f"{len(ts)}/{len(te)} ({pct(len(ts), len(te))})" if te else "–")
            tier_pct[t] = 100 * len(ts) / len(te) if te else None
            tier_steps[t] = sum(e["n_steps"] for e in ts) / len(ts) if ts else None
        summary[b] = (tier_pct, tier_steps)
        avg_steps = f"{sum(e['n_steps'] for e in succ) / len(succ):.1f}" if succ else "–"
        avg_lat = f"{sum(lat) / len(lat) / 1000:.1f} s" if lat else "–"
        lines.append(
            f"| {b} | {models[b]} | {len(eps)} | **{len(succ)}/{len(eps)} ({pct(len(succ), len(eps))})** | "
            f"{' | '.join(tier_cells)} | {avg_steps} | {avg_lat} | {pct(inv, len(rows))} ({inv}/{len(rows)}) |"
        )

    # ---------------------------------------------------------------- per task
    lines += ["", "## Per task", "", "| Task | Tier | Instruction | " + " | ".join(backends) + " |",
              "|---|---|---|" + "---|" * len(backends)]
    for tid, t in sorted(tasks.items(), key=lambda kv: (TIERS.index(kv[1]["tier"]), kv[0])):
        cells = []
        for b in backends:
            eps = [e for e in episodes if e["backend"] == b and e["task_id"] == tid]
            if not eps:
                cells.append("–")
                continue
            ok = sum(e["ok"] for e in eps)
            avg = sum(e["n_steps"] for e in eps) / len(eps)
            cells.append(f"{'✅' if ok == len(eps) else '❌' if ok == 0 else '◐'} {ok}/{len(eps)} · {avg:.0f} steps")
        if any(c != "–" for c in cells):
            lines.append(f"| {tid} | {t['tier']} | {t['task']} | " + " | ".join(cells) + " |")

    # ---------------------------------------------------------------- failures
    lines += ["", "## Failure analysis", ""]
    for b in backends:
        fails = [e for e in episodes if e["backend"] == b and not e["ok"]]
        lines.append(f"**{b}** — {len(fails)} failed episodes")
        for cat, n in Counter(classify_failure(e, e["steps_rows"]) for e in fails).most_common():
            lines.append(f"- {cat}: {n}")
        act = Counter(action_failure_kind(s.get("unity_reason", ""))
                      for e in episodes if e["backend"] == b
                      for s in e["steps_rows"] if s.get("unity_success") == "False")
        if act:
            lines.append("- failed robot actions (all episodes): " + ", ".join(f"{k} ×{v}" for k, v in act.most_common()))
        lines.append("")
    lines += ["### Failed episodes (for review)", "", "| Backend | Task | Steps | Reason |", "|---|---|---|---|"]
    for e in sorted((e for e in episodes if not e["ok"]), key=lambda e: (e["backend"], e["task_id"])):
        reason = re.sub(r"\s+", " ", e["reason"]).replace("|", "/")[:140]
        lines.append(f"| {e['backend']} | {e['task_id']} | {e['n_steps']} | {reason} |")

    lines += ["", "Charts: `charts/success_by_tier.png`, `charts/steps_by_tier.png`", ""]
    OUT.mkdir(exist_ok=True)
    (OUT / "results.md").write_text("\n".join(lines), encoding="utf-8")
    make_charts(backends, summary)
    print("\n".join(lines[:12 + len(backends)]))
    print(f"\nWrote {OUT / 'results.md'} and charts in {OUT / 'charts'}")


def make_charts(backends: list[str], summary: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    charts = OUT / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    specs = [
        ("success_by_tier.png", "Task success rate by difficulty", "Success rate (%)", 0, lambda v: f"{v:.0f}%", (0, 105), "not run"),
        ("steps_by_tier.png", "Average steps used on successful tasks", "Steps", 1, lambda v: f"{v:.1f}", None, "no successes"),
    ]
    for fname, title, ylabel, idx, fmt, ylim, empty in specs:
        fig, ax = plt.subplots(figsize=(7, 4), dpi=150)
        fig.patch.set_facecolor(SURFACE)
        ax.set_facecolor(SURFACE)
        n = len(backends)
        width = 0.7 / max(n, 1)
        for i, b in enumerate(backends):
            vals = [summary[b][idx][t] for t in TIERS]
            xs = [x + (i - (n - 1) / 2) * width for x in range(len(TIERS))]
            hs = [v if v is not None else 0 for v in vals]
            bars = ax.bar(xs, hs, width=width, color=SERIES[i], edgecolor=SURFACE, linewidth=2,
                          label=b, zorder=3)
            for bar, v in zip(bars, vals):
                ax.annotate(fmt(v) if v is not None else empty,
                            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            xytext=(0, 3), textcoords="offset points", ha="center",
                            fontsize=9, color=INK2)
        ax.set_xticks(range(len(TIERS)), [t.capitalize() for t in TIERS], color=INK)
        ax.set_ylabel(ylabel, color=INK2)
        ax.set_title(title if n >= 2 else f"{title} - {backends[0]}", color=INK, loc="left", fontsize=12, pad=12)
        if ylim:
            ax.set_ylim(*ylim)
        ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK2, length=0)
        if n >= 2:
            ax.legend(frameon=False, labelcolor=INK, loc="upper right", ncols=n)
        fig.tight_layout()
        fig.savefig(charts / fname, facecolor=SURFACE)
        plt.close(fig)


if __name__ == "__main__":
    main()
