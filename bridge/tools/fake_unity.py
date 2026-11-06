"""Stand-in for Unity: sends images through the bridge exactly like Unity will.

Use it to test the whole image path (bridge -> Kaggle/Gemini/local) before the
Unity side exists.

    # terminal 1 (from bridge/):  ..\\my_env\\Scripts\\python.exe -m uvicorn main:app --port 8000
    # terminal 2 (from bridge/):  ..\\my_env\\Scripts\\python.exe tools\\fake_unity.py
    #   options: --image path.jpg   use a real screenshot instead of the synthetic test image
    #            --steps 3          how many /step calls
    #            --task "Open the left cabinet"

The synthetic image is a crude drawing of the habitat (shelf with red/blue
canisters, purple and orange cabinets). It is only meant to prove the pipe works;
the model's choices on it are not meaningful.
"""
from __future__ import annotations

import argparse
import base64
import io
import sys
import time

import requests
from PIL import Image, ImageDraw

OBJECTS = ["red_canister", "blue_canister", "green_canister", "toolbox",
           "shelf_a", "table", "cabinet_left", "cabinet_right"]


def synthetic_image(size: int = 512) -> bytes:
    img = Image.new("RGB", (size, size), (215, 220, 228))           # wall
    d = ImageDraw.Draw(img)
    d.rectangle([0, 360, size, size], fill=(64, 69, 77))               # floor
    d.rectangle([40, 250, 230, 360], fill=(140, 145, 153))             # shelf_a
    d.rectangle([75, 190, 105, 250], fill=(217, 26, 26))               # red canister
    d.rectangle([160, 190, 190, 250], fill=(26, 77, 230))              # blue canister
    d.rectangle([290, 160, 390, 360], fill=(128, 51, 179))             # cabinet_left (purple door)
    d.rectangle([400, 160, 500, 360], fill=(242, 128, 26))             # cabinet_right (orange door)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--image", help="JPEG/PNG to send instead of the synthetic image")
    ap.add_argument("--steps", type=int, default=3)
    ap.add_argument("--task", default="Put the red canister in the left cabinet")
    a = ap.parse_args()

    if a.image:
        img = Image.open(a.image).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        jpeg = buf.getvalue()
    else:
        jpeg = synthetic_image()
    b64 = base64.b64encode(jpeg).decode("ascii")

    try:
        h = requests.get(f"{a.url}/health", timeout=5).json()
    except requests.RequestException as e:
        print(f"Bridge not reachable at {a.url}: {e}\nStart it first (see top of this file).")
        return 1
    print(f"Bridge OK -> backend={h['backend']} model={h['model']}")

    ep = requests.post(f"{a.url}/episode/start", json={
        "task": a.task, "scene_objects": OBJECTS, "max_steps": a.steps, "task_id": "FAKE",
    }, timeout=10).json()["episode_id"]
    print(f"Episode {ep}: {a.task!r}")

    # Mimic Unity's JsonUtility output: "" instead of null, list instead of dict
    state = {"holding": "", "near": [],
             "containers": [{"name": "cabinet_left", "state": "closed"},
                            {"name": "cabinet_right", "state": "closed"}]}
    last = {"action": "", "target": "", "object": "", "location": "", "success": False, "reason": ""}

    for i in range(a.steps):
        t0 = time.perf_counter()
        r = requests.post(f"{a.url}/step", json={
            "episode_id": ep, "step": i, "image_b64": b64,
            "robot_state": state, "last_result": last,
        }, timeout=180)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            print(f"  step {i}: HTTP {r.status_code} {r.text}")
            return 1
        c = r.json()
        args = ", ".join(f"{k}={c[k]}" for k in ("target", "object", "location") if c.get(k))
        print(f"  step {i}: {c['action']}({args})  valid={c['meta']['valid']} "
              f"model={c['meta']['latency_ms']} ms round-trip={dt:.0f} ms")
        print(f"          thought: {c['thought']}")
        if c["meta"].get("error"):
            print(f"          error:   {c['meta']['error']}")
        # pretend every action succeeded
        last = {"action": c["action"], "target": c.get("target") or "", "object": c.get("object") or "",
                "location": c.get("location") or "", "success": True, "reason": ""}
        if c["action"] == "pick":
            state["holding"] = c["object"]
        elif c["action"] == "place":
            state["holding"] = ""
        elif c["action"] == "move_to":
            state["near"] = [c["target"]]
        elif c["action"] in ("open", "close"):
            for cont in state["containers"]:
                if cont["name"] == c["target"]:
                    cont["state"] = "open" if c["action"] == "open" else "closed"
        if c["action"] == "done":
            break

    requests.post(f"{a.url}/episode/end", json={
        "episode_id": ep, "success": False, "steps": i + 1, "reason": "fake_unity test run",
        "last_result": last,
    }, timeout=10)
    print("Episode ended. See bridge/logs/steps.csv and bridge/logs/frames/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
