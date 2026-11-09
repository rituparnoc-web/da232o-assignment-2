# PLAN — HabitatVLM build plan

Companion to `SPEC.md` (v0.2). Work through the phases in order. Each phase ends with a **checkpoint** you can demonstrate before moving on. If something breaks, you then know which layer it is in.

**Total estimate:** about 5 weeks part-time (roughly 8–10 hours per week).
**Build order (revised 6 Nov 2026):** *pipe* (bridge) → *brain* (Kaggle VLM) → *eyes* (Unity camera → VLM) → *body* (robot skills) → full loop.
Reason: the riskiest, least familiar part, getting a GPU-hosted VLM to read images from Unity, is proven first. Robot skills are ordinary Unity work and come after.

**Python rule:** every package is installed **inside the venv `my_env`**. Never use the system Python.
```
# from the repo root
my_env\Scripts\python.exe -m pip install -r requirements.txt
```

---

## Phase 0 — Setup ✅ (mostly done)

- [x] Unity Hub + Unity 6 (6000.6.7f1), URP project in `Unity (VLM Project)/`.
- [x] Python 3.11 venv `my_env/`; bridge dependencies installed from `requirements.txt` (exact versions in `requirements.lock.txt`).
- [x] `.gitignore` created for the real folder names (Unity `Library/`, `Logs/`, `my_env/`, `.env`, `logs/` …).
- [ ] Kaggle account → **phone-verify** it (needed to turn on Internet in notebooks).
- [ ] Optional: Google AI Studio → Gemini API key (backup backend C).
- [ ] `git init` → first commit (check `git status` shows no `Library/`, `my_env/` or `.env`).

---

## Phase 1 — Habitat scene ✅ (done)

- [x] Room, furniture, cabinets with hinges, items and robot built by **HabitatVLM → Build Habitat Room**.
- [x] Materials, two point lights, NavMesh baked, `robot_cam` → `RobotCamRT` 512×512.
- [ ] Later polish (not blocking): move the scene to `Assets/Scenes/`, add it to Build Settings, remove/dim the default Directional Light.

---

## Phase 2 — Python bridge with the mock backend ✅ (done 6 Nov)

- [x] `bridge/main.py`: `GET /health`, `POST /episode/start`, `POST /step`, `POST /episode/end` (SPEC §7).
- [x] `settings.py`, `vlm.py` (all backends + `mock` script), `prompts.py`, `validator.py`, `logger.py`, `config.yaml`, `.env.example`.
- [x] `tools/fake_unity.py`: Unity stand-in that sends images through the bridge.
- [x] Tested: mock run of 7 steps, CSV logs and frames written; malformed replies, a dead backend and bad images never crash the bridge.

**Run it:**
```
cd bridge
..\my_env\Scripts\python.exe -m uvicorn main:app --port 8000          # terminal 1
..\my_env\Scripts\python.exe tools\fake_unity.py --steps 7            # terminal 2
```
To test without a model, first run `$env:VLM_BACKEND="mock"` (PowerShell) or `set VLM_BACKEND=mock` (cmd) in terminal 1.

**Checkpoint 2:** `fake_unity.py` with `VLM_BACKEND=mock` prints the 7 scripted actions; `bridge/logs/steps.csv` has 7 rows.

---

## Phase 3 — Kaggle VLM backend (B) ✅ (done 6 Nov)

- [ ] kaggle.com → *Create* → *New Notebook* → *File → Import Notebook* → `kaggle/ollama_server.ipynb`.
- [ ] Session options: **GPU T4 x2**, **Internet On** → *Run All*.
- [ ] Cell 4 (local image test) should list the red/purple objects. Note the 2nd-call latency.
- [ ] Copy the printed `KAGGLE_TUNNEL_URL=...` line into `bridge/.env` (copy `.env.example` → `.env` first).
- [ ] `config.yaml`: `active_backend: kaggle` → restart the bridge → `fake_unity.py`.
- [ ] Optional: `fake_unity.py --image <a screenshot of the scene>` to see how the model reads a real frame.
- [ ] **Stop the Kaggle session when finished** (Run → Stop session).

**Checkpoint 3:** `fake_unity.py` gets `valid=True` replies from `qwen3-vl:8b` on Kaggle, and the Kaggle monitor cell shows the requests arriving.

---

## Phase 4 — Unity image link: robot camera → bridge → Kaggle ✅ (done 9 Nov)

- [x] `CameraCapture` on `robot_cam`; `AgentManager` with `BridgeClient` + `BridgeImageTest`.
- [x] Play → SPACE: real robot-camera frame (9 KB JPEG) reached `qwen3-vl:8b-instruct` on Kaggle; reply `move_to(red_canister)`, valid, ~4.4 s. Saved frame matches the robot view.

**Checkpoint 4:** ✅ passed. (The robot does not move yet; that is Phase 5/6.)

---

## Phase 5 — Robot and skills, keyboard only ✅ (done 9 Nov)

- [x] `Interactable`, `Cabinet`, `RobotSkills`, `KeyboardDebug` + menu **HabitatVLM → Setup Interactables and Robot**.
- [x] Keyboard run 1→6 put the red canister in the left cabinet; out-of-reach and empty-gripper failures reported clearly.
- [x] Fix: the robot now stands at the middle of a furniture's open long side / in front of the item (was the nearest corner → "out of reach 1.2 m").

**Checkpoint 5:** ✅ passed.

---

## Phase 6 — Full agent loop with the VLM (Qwen drives the robot) ✅ (done 9 Nov)

- [x] `AgentLoop.cs` panel (task presets, Start/Stop/Reset) + `TaskSpec.cs` success checks + `Assets/Tasks/tasks_room01.json` (8 tasks). Object list read from the scene.
- [x] Mock run: T04 completed by the scripted sequence → SUCCESS (skills + loop verified without the model).
- [x] Kaggle, prompt v1: T01/T02 succeeded with wasted steps; T03 looped (pick/place), T04 took 13 steps → model did not know when to stop.
- [x] Prompt v2 (full history, item locations from Unity, "is the task complete?" check, never undo progress, repetition warning).
- [x] Kaggle, prompt v2: T03 in 3 steps, T04 in 6 steps (×2), 0 invalid replies, ~5 s/step.
- [x] Loop stops cleanly after 2 model-backend failures instead of spinning.

**Checkpoint 6:** ✅ passed: tasks succeed end-to-end on Kaggle with no keyboard input.

---

## Phase 7 — Second backend (Gemini) and robustness

Scope (9 Nov): Kaggle (B) + Gemini (C) only; no local model, no Groq.
- [x] `GEMINI_API_KEY` in `bridge/.env`; key verified (HTTP 200); `gemini-2.5-flash` available (newer Flash models also listed).
- [ ] Start bridge with `$env:VLM_BACKEND="gemini"` (or set `active_backend: gemini`) → run T01, T03, T04 → compare with Kaggle.
- [ ] Optionally try a newer Flash model (e.g. `gemini-3.5-flash`) if 2.5 struggles; watch the free-tier daily limit.
- [ ] Robustness: confirm Unity handles `look_around` fallbacks / `meta.valid=false` (bridge side already tested).
- [ ] Commit.

**Checkpoint 7:** The same tasks succeed on Kaggle and Gemini by changing only the backend setting.

---

## Phase 8 — Evaluation and documentation (Week 5, ~3–4 days)

- [ ] Write `tasks.json` with 24 tasks (8 Easy, 8 Medium, 8 Hard) and their success conditions (SPEC §11).
- [ ] `TaskRunner.cs`: reset the scene → run each task → move to the next.
- [ ] Run the full suite on **B** (Kaggle, primary) and on **C** (watch the daily rate limit; split across days if needed).
- [ ] `eval/analyze.py`: results table (success % by tier and backend, mean latency, invalid %) and one or two charts.
- [ ] Review the failures: categorise them (wrong object, wrong order, navigation, invalid JSON) and note 3 lessons.
- [ ] Record a 2–3 minute demo video (OBS Studio): split view of the robot camera, the scene, and the bridge log.
- [ ] Write `README.md`: what it is, architecture diagram, setup steps, how to switch backends, results, limitations.
- [ ] Check every acceptance criterion in SPEC §13. Final commit and tag `v1.0`.

**Checkpoint 8 (project done):** All of SPEC §13 is ticked.

---

## Phase 9 — Any room: generalisation + 5 new test rooms (added 9 Nov)

Goal (SPEC §5.6, option A): the same code works in any room built from the supported object types; only the scene changes.
- [ ] Room layout files `rooms/room_XX.json` (room size, objects: name, kind, primitive, position, rotation, size, colour, door direction) + a general **HabitatVLM → Build Room from Layout** editor tool. Rebuild the current room as `room_01` and confirm nothing changed.
- [ ] Objects describe themselves: `HabitatSetup` scans the scene for `Interactable`s instead of a fixed name list; remove `object_kinds` from `bridge/config.yaml` (Unity sends kinds).
- [ ] NavMesh rebuilt automatically at Play (`NavMeshSurface.BuildNavMesh`), so moved furniture needs no manual bake.
- [ ] Skills handle rotated furniture (object's own axes) and free-standing cabinets (door direction from the container).
- [ ] Generic keyboard debug (pick any object from a list) instead of fixed keys.
- [ ] Build **5 new rooms** (`room_02` … `room_06`, space-habitat themes: storage bay, lab, galley, crew cabin, airlock), each with its own scene and `Assets/Tasks/tasks_room0X.json`.
- [ ] Keyboard check in each new room, then the agent on 2–3 tasks per room (Kaggle).
- [ ] Add per-room success rates to the results table (`eval/analyze.py`).

**Checkpoint 9:** The unchanged code completes tasks in at least 4 of the 6 rooms; results reported per room.

---

## Phase 10 — Stretch goals (optional, pick any)


- [ ] Remove the object-name list from the prompt (the VLM must recognise objects from the image alone); measure the drop in success.
- [ ] Voice task input (speech-to-text → task).
- [ ] Randomise item positions per episode (seeded) for robustness testing.
- [ ] Add a bearer-token proxy in the Kaggle notebook so the tunnel is not open to anyone with the URL.
- [ ] Upgrade HTTP to WebSockets (NativeWebSocket package) for streaming status.
- [ ] Try a true VLA model on Kaggle for one skill and compare.
- [ ] Start **Project 2** (SAR Drone, SPEC §15), reusing the bridge.

---

## Weekly summary

| Week | Phases | Demo at end of week |
|---|---|---|
| 1 | 0, 1, 2 | Habitat room; bridge answering scripted commands ✅ |
| 2 | 3, 4 ✅ | Robot camera frame from Unity answered by the VLM on Kaggle ✅ |
| 3 | 5 ✅, 6 ✅ | Robot completes a task by keyboard, then driven by the VLM ✅ |
| 4 | 7 | Same tasks on Kaggle and Gemini; robust to bad output |
| 5 | 8 | Results table, demo video, README; v1.0 |
| 6 | 9 | Same code in 5 new rooms; per-room results |

---

## Working-session checklist (every time)

1. Close Teams, Outlook, Copilot and the extra browser → Memory ≤ 50%.
2. If using Kaggle: open the notebook → *Run All* → copy the new `KAGGLE_TUNNEL_URL` into `bridge/.env`.
3. Start the bridge: `cd bridge` → `..\my_env\Scripts\python.exe -m uvicorn main:app --port 8000` (restart it after editing `.env` or `config.yaml`).
4. Quick check: `..\my_env\Scripts\python.exe tools\fake_unity.py --steps 1`.
5. Open Unity → `Habitat.unity` → Play.
6. At the end: **stop the Kaggle session**, commit, and note what's next in the README's "Next" section.

---

## Risk log

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Kaggle weekly GPU quota runs out during evaluation | Medium | Medium | Stop sessions promptly; use Gemini (C) for part of the runs |
| Tunnel URL changes / tunnel drops mid-run | High | Low | Bridge retries 52x errors; monitor cell flags a dead tunnel; re-run step 5 and update `.env` |
| Tunnel is public while running | Medium | Low | Short sessions, URL never committed; stretch goal: token proxy |
| Free API daily limit reached (Gemini) | High | Medium | Kaggle is the primary backend; split runs across days |
| VLM confuses left/right cabinets | Medium | Medium | Distinct door colours (purple/orange); container states in the prompt |
| Laptop runs out of RAM | Medium | High | Session checklist step 1; never run local model + Unity + browsers together |
| Kaggle quota or policy changes | Low | Medium | Gemini (C) as fallback; Colab as a second GPU option |
| Time overrun | Medium | Medium | Phases are independent; ship after Phase 7 with a smaller task suite if needed |
