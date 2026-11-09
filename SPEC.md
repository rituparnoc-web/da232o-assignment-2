# SPEC — VLM-Controlled Robot in a Unity Space Habitat

**Project codename:** HabitatVLM
**Owner:** Supratim
**Version:** 0.2 (6 Nov 2026)
**Status:** Phases 0–5 verified (9 Nov): bridge, Kaggle backend, image link, robot skills. Phase 6 (agent loop) in progress; Phase 9 (any room + 5 new rooms) planned

**Changes in 0.2**
- Build order changed: **bridge → Kaggle backend → Unity image link → robot skills** (see PLAN).
- **Backend B (Kaggle)** is the primary development backend; Gemini (C) is the backup.
- Added a `mock` backend (scripted replies) for testing without any model.
- Interface (§7) adapted to Unity's `JsonUtility`: `""` means null, and dictionaries are sent as `{name, …}` arrays.
- The Kaggle setup is described in a new §9. The real repo layout is in §14: Unity folder `Unity (VLM Project)/`, venv `my_env/`.

---

## 1. Summary

A robot inside a small 3D space-habitat module (built in Unity) receives a task in plain English, e.g. *"Put the red canister into the left cabinet"*. At each step:

1. Unity captures an image from the robot's camera.
2. A Python bridge sends that image and the task to a **vision-language model (VLM)**.
3. The VLM replies with **one structured command** (JSON) chosen from a fixed list of actions.
4. The bridge validates the command and sends it back to Unity.
5. Unity executes it with a pre-written skill (move, pick, place, open, close).
6. The loop repeats until the task is done or a step limit is reached.

**Design principle:** *The VLM decides **what** to do. Unity decides **how** to do it.* The VLM never outputs coordinates, angles or motor values.

---

## 2. Goals and non-goals

### Goals
- G1. End-to-end loop: camera image → VLM → validated command → robot action, fully automatic.
- G2. Swappable model backends, switched only through config (`active_backend`):
  - **B** Ollama on a Kaggle GPU notebook, reached through a Cloudflare tunnel. **Primary for development.**
  - **C** Gemini (free tier, OpenAI-compatible endpoint). Second backend for the comparison. Key verified 9 Nov.
  - *Out of scope (decided 9 Nov):* **A** local Ollama and Groq/OpenRouter. The code still supports them (config only), but they are not run or reported.
  - `mock`: scripted replies, no model. Used to test the pipe.
- G3. Reliable on a low-spec laptop (16 GB RAM, integrated AMD GPU).
- G4. Measurable results: success rate, latency and invalid-output rate per backend.
- G5. Uses free resources only.

### Non-goals
- Real physics-based grasping (grasp is simulated by parenting the object to the gripper).
- Training or fine-tuning any model.
- Real robot hardware.
- Photorealistic graphics.
- Using a true VLA model (stretch goal only).

---

## 3. Constraints

| Constraint | Detail | Consequence |
|---|---|---|
| Laptop CPU | AMD, 4 cores / 8 threads, 2.8 GHz | Local VLM inference is slow → Kaggle is the main backend |
| Laptop RAM | 15.3 GB; ~73% used at idle with Teams/Outlook/Copilot/browsers open | Close heavy apps while working; local model ≤ 4B parameters |
| Laptop GPU | AMD Radeon integrated (shared RAM) | Unity only (not Unreal); low-poly scene; shadows off |
| Budget | ₹0 | Kaggle free GPU (~30 h/week, 12 h sessions), Gemini free tier, Unity Personal |
| Free-tier rate limits | Requests per minute and per day are capped | Retry with back-off on HTTP 429; can switch backend |
| Kaggle tunnel | URL changes every session; public and unauthenticated while running | URL lives in `bridge/.env`; stop the session after use |
| Python | 3.11 in the project venv `my_env/` | All packages installed only inside `my_env` |

---

## 4. System architecture

```
┌──────────────────────── LAPTOP ────────────────────────┐
│                                                        │
│  ┌──────────────────┐   HTTP POST /step   ┌──────────────────────┐
│  │  UNITY (C#)      │ ──────────────────▶ │  PYTHON BRIDGE       │
│  │  - Habitat scene │   JPEG (base64) +   │  (FastAPI, :8000)    │
│  │  - Robot + skills│   task + state      │  - prompt builder    │
│  │  - Camera capture│ ◀────────────────── │  - ask_vlm()         │
│  │  - Agent loop    │   command JSON      │  - validator         │
│  └──────────────────┘                     │  - CSV logger        │
│                                           └──────────┬───────────┘
└──────────────────────────────────────────────────────┼──────────────┘
                                                       │ OpenAI-compatible chat API (one of)
              ┌────────────────────────────────────────┼────────────────────────┐
              ▼                                        ▼                        ▼
   B) Ollama on Kaggle GPU (primary)       C) Cloud vision API          A) Local Ollama
   https://<x>.trycloudflare.com/v1        Gemini / Groq / OpenRouter   localhost:11434/v1
   qwen3-vl:8b-instruct on T4              (API key)                    qwen3-vl:4b-instruct
```

### 4.1 Responsibilities

| Component | Language | Owns | Does NOT own |
|---|---|---|---|
| Unity scene | C# | World, physics, rendering, skills, camera, the episode loop timing, success check | Prompting, model calls, deciding actions |
| Python bridge | Python | Prompts, model calls, validation, name/kind checks, logging, metrics | Moving anything in the scene |
| VLM backend | — | Choosing the next action from image + text | Coordinates, path planning, grasp mechanics |

---

## 5. Scene specification (Unity)

### 5.1 Units and axes
- 1 Unity unit = 1 metre. Y is up. Floor top surface at Y = 0.

### 5.2 Room: `HabitatModule` (8 m × 6 m × 3 m)

Built automatically by the editor menu **HabitatVLM → Build Habitat Room** (`Assets/Scripts/Editor/HabitatBuilder.cs`).

| Object name | Primitive | Position (x, y, z) | Scale (x, y, z) | Notes |
|---|---|---|---|---|
| `floor` | Cube | (0, -0.05, 0) | (8, 0.1, 6) | NavMesh surface |
| `wall_back` | Cube | (0, 1.5, 3) | (8, 3, 0.2) | |
| `wall_front` | Cube | (0, 1.5, -3) | (8, 3, 0.2) | Renderer hidden for the overhead view |
| `wall_left` | Cube | (-4, 1.5, 0) | (0.2, 3, 6) | |
| `wall_right` | Cube | (4, 1.5, 0) | (0.2, 3, 6) | |
| `shelf_a` | Empty + `body` cube | (-3, 0, 2.5) | body (1.5, 1, 0.6) | `snap_point` on top |
| `table` | Empty + `body` cube | (-3, 0, -2) | body (1.2, 0.8, 0.8) | `snap_point` on top |
| `cabinet_left` | 5 panels + hinged door | (2.2, 0, 2.6) | 1 × 1.5 × 0.6 | **Purple** door, child of `cabinet_left/hinge` |
| `cabinet_right` | 5 panels + hinged door | (3.4, 0, 2.6) | 1 × 1.5 × 0.6 | **Orange** door, child of `cabinet_right/hinge` |
| `red_canister` | Cylinder | on `shelf_a` | (0.2, 0.2, 0.2) | Red material |
| `blue_canister` | Cylinder | on `shelf_a` | (0.2, 0.2, 0.2) | Blue material |
| `green_canister` | Cylinder | on `table` | (0.2, 0.2, 0.2) | Green material |
| `toolbox` | Cube | on `table` | (0.4, 0.2, 0.25) | Yellow material |
| `robot` | Capsule + NavMeshAgent | (3, 0, -2) | — | Spawn point; children `gripper`, `robot_cam` |

### 5.3 Naming rules
- Every interactable object has a **unique, lowercase, snake_case** name.
- Names in the Unity Hierarchy are **exactly** the names sent to the VLM and accepted by the validator.
- Each interactable has a component `Interactable` with fields: `kind` (`item` / `container` / `surface`), `snapPoint` (Transform for placing), `isOpen` (containers only).
- The bridge also has a default name → kind table in `bridge/config.yaml` (`object_kinds`). Kinds that Unity sends in `/episode/start` take priority.

### 5.4 Visual rules
- Interactable items use clearly distinct, saturated colours. Walls and floor are neutral grey/white. Cabinet doors use different colours (purple/orange) to reduce left/right confusion.
- Lighting: 2–3 point lights, shadows off or hard. Target ≥ 30 FPS on the laptop.

### 5.5 Robot
- Base: capsule with `NavMeshAgent` (speed 1.5 m/s, stopping distance 0.6 m).
- Gripper: empty Transform `gripper` at the front, about 1 m high.
- Camera: `robot_cam`, forward-facing, FOV 70°, renders to `Assets/Textures/RobotCamRT` (512×512).
- Reach: pick/place/open/close need the target within **1.0 m horizontally** of `gripper` (height is ignored, so shelf tops and cabinet floors are both reachable).
- Navigation: `move_to` drives to the NavMesh point nearest the object (cabinets: straight in front of the door, so the swinging door misses the robot), then turns to face it. Agent stopping distance is 0.05 m because the stand-point is computed by the skill.
- `near` (sent to the bridge) = objects within 1.3 m horizontally of the robot.

### 5.6 Design rule: any room (decided 9 Nov, option A)
- **The Unity scene is the single source of truth.** Every interactable object describes itself with an `Interactable` component (kind, snap point; containers also their door). At Play, Unity discovers the objects in the loaded room and sends their names and kinds to the bridge in `/episode/start`.
- No script may name a specific object or position. Exceptions, clearly marked as test/demo tools: `HabitatBuilder` (builds room 01), the bridge `mock` script, `KeyboardDebug` presets, and per-room task files.
- Supported object types: **item**, **surface**, **container** (hinged door), plus static **obstacles**. New interaction types (drawers, buttons…) need a new skill. That is by design: the VLM decides *what*, Unity decides *how*.
- Generalisation is shown by testing the unchanged code in 5 additional rooms (PLAN Phase 9). Removing object names from the prompt (pure image grounding, "option B") stays a stretch goal.

---

## 6. Action vocabulary

The VLM may return **only** these actions.

| Action | Required fields | Preconditions (checked in Unity) | Effect |
|---|---|---|---|
| `move_to` | `target` (any named object) | Target exists and is reachable on the NavMesh | Robot drives to near the target |
| `pick` | `object` (item) | Gripper empty; item within reach; if the item is in a container, that container is open | Item parented to `gripper` |
| `place` | `object` (item), `location` (surface/container) | Robot holds `object`; within reach of `location`; container open | Item moved to the location's `snapPoint` and released |
| `open` | `target` (container) | Within reach; currently closed | Door rotates to 100° |
| `close` | `target` (container) | Within reach; currently open; nothing blocking | Door rotates to 0° |
| `look_around` | — | — | Robot rotates 90° in place |
| `done` | — | — | Episode ends; Unity checks the success condition |

Every skill returns `{ "success": bool, "reason": string }`.

---

## 7. Interface contract (Unity ↔ Bridge)

Transport: HTTP/JSON on `http://127.0.0.1:8000`. Use `127.0.0.1`, not `localhost`: on Windows, `localhost` added about 2 s per request. Unity uses `UnityWebRequest` inside coroutines (`BridgeClient.cs`).

**JsonUtility conventions:** Unity cannot send `null` or dictionaries.
- An empty string `""` means *none/null* (e.g. `"holding": ""`).
- Dictionaries are sent as arrays of pairs: `containers: [{"name": "cabinet_left", "state": "closed"}]`, `object_kinds: [{"name": "red_canister", "kind": "item"}]`.
- The bridge also accepts the plain-JSON forms (`null`, `{"cabinet_left": "closed"}`).

### 7.1 `GET /health`
Response `200`: `{ "status": "ok", "backend": "kaggle", "model": "qwen3-vl:8b-instruct" }`

### 7.2 `POST /episode/start`
```json
{
  "task": "Put the red canister into the left cabinet",
  "scene_objects": ["red_canister", "blue_canister", "green_canister", "toolbox",
                    "shelf_a", "table", "cabinet_left", "cabinet_right"],
  "object_kinds": [{"name": "red_canister", "kind": "item"}, "..."],
  "max_steps": 15,
  "task_id": "T05"
}
```
`object_kinds` and `task_id` are optional. If an object's kind is unknown, the bridge returns `400`.
Response: `{ "episode_id": "ep_20261030_141500" }`

### 7.3 `POST /step`
Request:
```json
{
  "episode_id": "ep_20261030_141500",
  "step": 3,
  "image_b64": "<base64 JPEG; resized to 512x512 by the bridge>",
  "robot_state": {
    "holding": "",
    "near": ["shelf_a", "red_canister"],
    "containers": [{"name": "cabinet_left", "state": "closed"}, {"name": "cabinet_right", "state": "closed"}],
    "items": [{"name": "red_canister", "state": "on shelf_a"}, {"name": "blue_canister", "state": "held by robot"}]
  },
  "last_result": { "action": "move_to", "target": "shelf_a", "object": "", "location": "", "success": true, "reason": "" }
}
```
Response:
```json
{
  "action": "pick",
  "target": null,
  "object": "red_canister",
  "location": null,
  "thought": "Red canister is on the shelf in front of me and my gripper is empty.",
  "meta": { "backend": "kaggle", "model": "qwen3-vl:8b", "latency_ms": 1840, "valid": true, "retries": 0, "error": "" }
}
```
If the model's reply fails validation after the re-ask, or the backend is unreachable, the bridge returns `"action": "look_around"` with `"meta.valid": false` and the reason in `meta.error`. Unity can always execute the reply.

### 7.4 `POST /episode/end`
Request: `{ "episode_id": "...", "success": true, "steps": 6, "reason": "red_canister inside cabinet_left", "last_result": { ... } }`
`last_result` (optional) records the outcome of the final action in the step log.
Response: `{ "logged": true }`

---

## 8. Bridge specification (Python, `bridge/`)

Runs from the project venv: `..\my_env\Scripts\python.exe -m uvicorn main:app --port 8000`.

| File | Purpose |
|---|---|
| `main.py` | FastAPI app and endpoints, episode state, retry/fallback logic |
| `settings.py` | Loads `config.yaml` + `.env`, resolves the active backend |
| `vlm.py` | `VLMClient.ask()` = `ask_vlm` for every backend, back-off, mock script |
| `prompts.py` | System prompt + per-step user prompt |
| `validator.py` | JSON extraction, vocabulary/field/name/kind rules |
| `logger.py` | `steps.csv`, `episodes.csv`, saved frames |
| `tools/fake_unity.py` | Unity stand-in: sends images through the bridge for testing |

### 8.1 Model access
```python
def ask(self, image_jpeg: bytes, system_prompt: str, user_prompt: str, *, step: int = 0) -> str:
    """Return the raw text reply from the configured backend."""
```
- One OpenAI-compatible client for all real backends (Ollama local/Kaggle, Groq, OpenRouter, Gemini's OpenAI endpoint). The image is sent as a `data:image/jpeg;base64` URL.
- Requests JSON output (`response_format: json_object`). If a backend rejects it, the bridge turns it off automatically.
- Timeout per backend in config (60 s for local/Kaggle, 30 s for cloud).
- HTTP 408/429/5xx/Cloudflare 52x and connection errors: back-off and retry, 3 attempts (2 s, 4 s, 8 s).

### 8.2 Configuration
`bridge/config.yaml` (committed; no secrets) holds `active_backend`, per-backend `base_url`/`model`/`timeout_s`, sampling settings (`temperature 0.2`, `max_tokens 300`), `image_size 512`, `max_steps 15`, `max_retries_invalid 1`, `history_len 3`, logging options and the `object_kinds` table.
- `VLM_BACKEND` environment variable overrides `active_backend` (no file edit needed).
- For `local`/`kaggle`, `/v1` is added to the base URL automatically.

`bridge/.env` (**never committed**; template `bridge/.env.example`): `GEMINI_API_KEY`, `GROQ_API_KEY`, `KAGGLE_TUNNEL_URL`.
Model IDs must be checked against each provider's current model list before use.

### 8.3 Prompt template (v2, 9 Nov)
The system prompt is fixed (see `prompts.py`). It lists the 7 actions and their fields, a decision procedure (**first check whether the task is already complete → `done`**, otherwise one action that makes progress), and rules: use only listed names, do exactly the task and nothing more, **never undo progress**, move_to before acting, open containers first, fix the cause of a failed action. Reply schema JSON, "thought" < 25 words.
The per-step user prompt contains: the task, valid object names grouped by kind, robot state (holding, near, container states), **item locations** (`on X` / `in X` / `held by robot`, sent by Unity), **all actions of this episode with their results**, the last result with its reason, an optional **repetition warning** (same action twice, or an A-B-A-B pattern), and the validation error on a re-ask.
*Why v2:* with v1 (last 3 actions, "STEP n of 15", no item locations) Qwen completed tasks but did not stop: it put items back, invented new goals and looped pick/place (T03 never finished, T04 took 13 steps). Replaying those exact frames with v2 gave `done` in 6/6 cases and correct progress actions in 4/4 mid-task cases.

### 8.4 Validation rules
1. Reply parses as JSON. `<think>` blocks, code fences and text around the JSON are stripped; a JSON list → its first element.
2. `action` is in the vocabulary.
3. Required fields for that action are present (Section 6).
4. All referenced names are in `scene_objects` (case/space-normalised: `"Red Canister"` → `red_canister`).
5. Type rules: `pick`/`place` `object` must be an item; `open`/`close` `target` must be a container; `place` `location` must be a surface or container.
6. Safe repairs before checking: e.g. `pick` with `target` instead of `object` → moved to `object`. Fields the action doesn't use are cleared.
7. On failure: re-ask once with the error appended ("Your last reply was invalid because ..."). On a second failure, fall back to `look_around`.

Preconditions such as reach and gripper state are checked **in Unity** (the source of truth), which reports failures through `last_result`.

### 8.5 Logging (`bridge/logs/`, git-ignored)
`steps.csv`, one row per step. Unity's outcome is filled in when the next `/step` or `/episode/end` arrives:
`timestamp, episode_id, step, backend, model, task, action, target, object, location, valid, retries, latency_ms, unity_success, unity_reason, thought, error`

`episodes.csv`, one row per episode:
`episode_id, task_id, backend, model, task, success, steps, total_latency_ms, invalid_count, reason, started, ended`

Frames: `logs/frames/<episode_id>/<step>.jpg` (exactly what the model saw).

---

## 9. Kaggle backend (B) specification (`kaggle/ollama_server.ipynb`)

| Item | Value |
|---|---|
| Accelerator | GPU T4 ×2 (or P100), Internet **On** |
| Server | Ollama (official install script; needs `zstd`), `OLLAMA_HOST=0.0.0.0:11434`, `OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_CONTEXT_LENGTH=8192` |
| Model | `qwen3-vl:8b-instruct` (fallback `qwen3-vl:4b-instruct`). Use the **instruct** tags: plain `qwen3-vl:8b` always "thinks" first (7–9 s per step vs 4–5 s) |
| Tunnel | `cloudflared tunnel --url http://127.0.0.1:11434 --http-host-header localhost:11434` (quick tunnel, no account) |
| Endpoint used by the bridge | `https://<random>.trycloudflare.com/v1` (OpenAI-compatible) |
| Notebook cells | install → start server → pull model → local image test (warm-up) → tunnel + print URL → tunnel check → request monitor |
| Session hygiene | Stop the session after use; the URL changes every session and goes into `bridge/.env` |

---

## 10. Unity scripts

| Script | Folder | Attached to | Responsibility | Status |
|---|---|---|---|---|
| `HabitatBuilder.cs` | `Scripts/Editor` | — (menu) | Builds room, materials, robot, camera (then runs HabitatSetup) | Done |
| `HabitatSetup.cs` | `Scripts/Editor` | — (menu) | **HabitatVLM → Setup Interactables and Robot**: adds the components below with kinds/snap points/hinges | Done |
| `BridgeDtos.cs` | `Scripts/Bridge` | — | Serializable request/response classes (§7) | Done |
| `BridgeClient.cs` | `Scripts/Bridge` | `AgentManager` | HTTP calls: health, start, step, end | Done |
| `CameraCapture.cs` | `Scripts/Bridge` | `robot_cam` | RenderTexture → JPEG bytes | Done |
| `BridgeImageTest.cs` | `Scripts/Bridge` | `AgentManager` | Image-link checkpoint: SPACE sends one frame, shows the reply | Done |
| `Interactable.cs` | `Scripts/Robot` | Every interactable | Kind, snap point, open state, current location of items, name registry | Written |
| `Cabinet.cs` | `Scripts/Robot` | Each cabinet | Open/close by rotating the hinge (coroutine, about 1 s) | Written |
| `RobotSkills.cs` | `Scripts/Robot` | Robot | `MoveTo`, `Pick`, `Place`, `Open`, `Close`, `LookAround` → `SkillResult`; `Execute(action,…)`; `GetState()` → robot_state | Written |
| `KeyboardDebug.cs` | `Scripts/Robot` | Robot (dev only) | Keys 1–0 run skills, R resets the scene, on-screen state/log | Written |
| `AgentLoop.cs` | `Scripts/Agent` | `AgentManager` | Episode loop: capture → step → execute → repeat; step limit; success check; on-screen panel (task presets, Start/Stop/Reset) | Written |
| `TaskSpec.cs` | `Scripts/Agent` | — | Task file format + `SuccessChecker` (`item_in`, `item_on`, `container_state`, `holding`, `all`) | Written |
| `TaskRunner.cs` | `Scripts/Agent` | `AgentManager` | Loads `tasks.json`, runs episodes in sequence for evaluation | To do |

All network callbacks run inside coroutines on Unity's main thread. Keyboard input uses the Input System (`Keyboard.current`). The project's Active Input Handling is set to *Both*.

---

## 11. Task suite and success conditions

Tasks are defined per room in `Assets/Tasks/tasks_roomXX.json` (`{ "room": ..., "tasks": [...] }`; room 01 has 8 tasks). Condition types: `item_in`, `item_on`, `container_state`, `holding`, `all`. A free-form task typed in the panel has no condition and is logged as *unverified*. Example:
```json
[
  { "id": "T01", "task": "Open the left cabinet", "success": { "type": "container_state", "target": "cabinet_left", "state": "open" } },
  { "id": "T05", "task": "Put the red canister in the left cabinet", "success": { "type": "item_in", "object": "red_canister", "location": "cabinet_left" } },
  { "id": "T12", "task": "Put the red and blue canisters in the right cabinet and close it",
    "success": { "type": "all", "conditions": [ ... ] } }
]
```
Difficulty tiers: **Easy** (1 action), **Medium** (2–4 actions), **Hard** (5+ actions, multiple objects). Target: 24 tasks, 8 per tier.

Unity, not the VLM, decides success at `done` or when the step limit is reached.

---

## 12. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| N1 | Unity frame rate on the laptop | ≥ 30 FPS |
| N2 | Laptop RAM during backend B/C runs | ≤ 85% |
| N3 | Bridge overhead (excluding the model) | < 200 ms per step |
| N4 | Secrets | No keys or tunnel URLs in Git history |
| N5 | Reproducibility | Fixed scene layout + `tasks.json`; random seed for any randomisation |
| N6 | Backend switch | Change `active_backend` (or `VLM_BACKEND`) only; no code edits |
| N7 | Environment | Python packages only inside `my_env`; pinned in `requirements.txt` / `requirements.lock.txt` |

---

## 13. Acceptance criteria (MVP)

- [ ] AC1. Robot completes all **Easy** tasks with backend B (Kaggle) at ≥ 80% success.
- [ ] AC2. At least one **Medium** task succeeds end-to-end on each of B (Kaggle) and C (Gemini).
- [ ] AC3. Invalid VLM output never crashes Unity or the bridge. *(bridge side verified with malformed replies and a dead backend)*
- [ ] AC4. `steps.csv` and `episodes.csv` are produced for every run.
- [ ] AC5. A results table compares the backends: success %, mean latency, invalid-output %.
- [ ] AC6. The README explains setup from a fresh clone in ≤ 15 steps, with an architecture diagram and a demo video link.

---

## 14. Repository layout (actual)

```
Final Project - Unity (VLM)/          # repo root
├── README.md                         # (to do)
├── SPEC.md
├── PLAN.md
├── .gitignore                        # Library/, Temp/, Logs/, my_env/, .env, logs/ ...
├── requirements.txt                  # bridge dependencies (install into my_env)
├── requirements.lock.txt             # exact versions from pip freeze
├── tasks.json                        # (to do)
├── my_env/                           # Python 3.11 venv (git-ignored)
├── Unity (VLM Project)/              # Unity 6 (6000.6.7f1) URP project
│   └── Assets/
│       ├── Habitat.unity             # main scene
│       ├── Scripts/Editor/HabitatBuilder.cs
│       ├── Scripts/Bridge/           # BridgeDtos, BridgeClient, CameraCapture, BridgeImageTest
│       ├── Scripts/Robot/            # Interactable, Cabinet, RobotSkills, KeyboardDebug
│       ├── Scripts/Agent/            # AgentLoop, TaskSpec; (to do) TaskRunner
│       ├── Tasks/tasks_room01.json   # task presets + success conditions (one file per room)
│       ├── Materials/  Textures/RobotCamRT.renderTexture
├── bridge/
│   ├── main.py  settings.py  vlm.py  prompts.py  validator.py  logger.py
│   ├── config.yaml
│   ├── .env.example                  # copy to .env (git-ignored)
│   ├── tools/fake_unity.py
│   └── logs/                         # run output (git-ignored)
├── kaggle/
│   └── ollama_server.ipynb
├── eval/
│   └── analyze.py                    # (to do)
└── docs/
    └── architecture.png              # (to do)
```

---

## 15. Future extension (Project 2): Search-and-Rescue Drone

Reuses the bridge, `ask_vlm`, validation, logging and backend switching. Adds:
- Outdoor terrain with a labelled grid (A1–F6), hidden survivors and decoys.
- Drone actions: `fly_to(cell)`, `set_altitude(low|medium|high)`, `scan`, `mark_survivor(cell, description)`, `return_home`, `done`.
- Mission memory (visited cells, finds, battery %) sent with each prompt.
- A battery model and a forced return-home rule enforced by the bridge.
- Metrics: survivors found (recall), false alarms (precision), coverage %, safe return.

A separate SPEC will be written when Project 1 meets its acceptance criteria.
