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
- [ ] Optional: Ollama for Windows (backend A, Phase 7).

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

## Phase 3 — Kaggle VLM backend (B) (Week 1–2, ~1 day)

- [ ] kaggle.com → *Create* → *New Notebook* → *File → Import Notebook* → `kaggle/ollama_server.ipynb`.
- [ ] Session options: **GPU T4 x2**, **Internet On** → *Run All*.
- [ ] Cell 4 (local image test) should list the red/purple objects. Note the 2nd-call latency.
- [ ] Copy the printed `KAGGLE_TUNNEL_URL=...` line into `bridge/.env` (copy `.env.example` → `.env` first).
- [ ] `config.yaml`: `active_backend: kaggle` → restart the bridge → `fake_unity.py`.
- [ ] Optional: `fake_unity.py --image <a screenshot of the scene>` to see how the model reads a real frame.
- [ ] **Stop the Kaggle session when finished** (Run → Stop session).

**Checkpoint 3:** `fake_unity.py` gets `valid=True` replies from `qwen3-vl:8b` on Kaggle, and the Kaggle monitor cell shows the requests arriving.

---

## Phase 4 — Unity image link: robot camera → bridge → Kaggle (Week 2, ~½ day)

Scripts are written (`Assets/Scripts/Bridge/`). In the Unity editor:
- [ ] Open `Assets/Habitat.unity`. Wait for scripts to compile (Console must be free of errors).
- [ ] Select `robot_cam` → *Add Component* → **Camera Capture**. Check *Target Texture* = `RobotCamRT`.
- [ ] *GameObject → Create Empty* → name it `AgentManager` → *Add Component* **Bridge Client** and **Bridge Image Test**.
- [ ] Bridge running (Kaggle backend) → press **Play** → press **SPACE**.
- [ ] The Game view shows the robot's camera view (top left) and the model's reply below it.
- [ ] Check `bridge/logs/frames/<episode>/000.jpg` looks the same as the robot view (colours not too dark/washed out).
- [ ] Commit.

If the request is refused with an "insecure connection" error: *Project Settings → Player → Other Settings → Allow downloads over HTTP* → **Always allowed** (or *Development builds only*).

**Checkpoint 4:** Pressing SPACE in Play mode sends the real robot-camera frame to the VLM on Kaggle and shows a valid command and "thought" on screen.

---

## Phase 5 — Robot and skills, keyboard only (Week 2–3, ~4–5 days)

- [ ] Write `Interactable.cs`; add it to every item, surface and cabinet; set `kind` and `snapPoint` (the `snap_point` children already exist).
- [ ] Write `Cabinet.cs` with `Open()` and `Close()`, rotating `hinge` over about 1 s.
- [ ] Write `RobotSkills.cs` with `MoveTo`, `Pick`, `Place`, `Open`, `Close` and `LookAround`, each returning `SkillResult { success, reason }`.
  - [ ] `Pick` = check reach (≤ 1 m) and that the gripper is empty → parent the item to `gripper` and disable its physics.
  - [ ] `Place` = move the item to the location's `snapPoint` and un-parent it.
- [ ] Write `KeyboardDebug.cs` (Input System `Keyboard.current`): 1 = move to shelf, 2 = pick red, 3 = move to cabinet_left, 4 = open, 5 = place, 6 = close.
- [ ] Commit.

**Checkpoint 5:** Using only the keyboard, the robot completes "put the red canister in the left cabinet". Failure cases (out of reach, cabinet closed) log a clear reason in the Console.

---

## Phase 6 — Full agent loop with the VLM (Week 3, ~3–4 days)

- [ ] `AgentLoop.cs`: start episode → loop { capture → `/step` → execute skill → record `SkillResult` as `last_result` } until `done` or `max_steps` → success check → `/episode/end`.
- [ ] Build `robot_state` from the scene (holding, objects within ~1.5 m as `near`, cabinet states).
- [ ] First run with `VLM_BACKEND=mock`: the scripted sequence must complete the task (this tests the skills + loop without the model).
- [ ] Then with Kaggle: "Open the left cabinet", "Put the red canister in the left cabinet". Read the `thought` column in `steps.csv` to see why the model chose each action.
- [ ] Tune `prompts.py` if the model repeats failing actions (it gets the last result and last 3 actions).
- [ ] Commit.

**Checkpoint 6:** "Open the left cabinet" and "Put the red canister in the left cabinet" succeed end-to-end on Kaggle with no keyboard input.

---

## Phase 7 — Other backends and robustness (Week 4, ~2–3 days)

- [ ] **Backend C (Gemini):** put `GEMINI_API_KEY` in `.env`, check the current free-tier Flash model ID in AI Studio → update `config.yaml` → rerun the Easy tasks.
- [ ] **Backend A (local):** close heavy apps → `ollama pull qwen3-vl:4b` → `active_backend: local` → one Easy task, note the latency.
- [ ] Robustness: deliberately bad replies (already unit-tested in the bridge) → confirm Unity handles `look_around` fallbacks and `meta.valid=false`.
- [ ] Commit.

**Checkpoint 7:** The same Easy task succeeds on B, C and A by changing only `active_backend`. Invalid replies are logged, not fatal.

---

## Phase 8 — Evaluation and documentation (Week 5, ~3–4 days)

- [ ] Write `tasks.json` with 24 tasks (8 Easy, 8 Medium, 8 Hard) and their success conditions (SPEC §11).
- [ ] `TaskRunner.cs`: reset the scene → run each task → move to the next.
- [ ] Run the full suite on **B** (Kaggle, primary) and on **C** (watch the daily rate limit; split across days if needed).
- [ ] Run Easy + Medium only on **A**, since local is slow.
- [ ] `eval/analyze.py`: results table (success % by tier and backend, mean latency, invalid %) and one or two charts.
- [ ] Review the failures: categorise them (wrong object, wrong order, navigation, invalid JSON) and note 3 lessons.
- [ ] Record a 2–3 minute demo video (OBS Studio): split view of the robot camera, the scene, and the bridge log.
- [ ] Write `README.md`: what it is, architecture diagram, setup steps, how to switch backends, results, limitations.
- [ ] Check every acceptance criterion in SPEC §13. Final commit and tag `v1.0`.

**Checkpoint 8 (project done):** All of SPEC §13 is ticked.

---

## Phase 9 — Stretch goals (optional, pick any)

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
| 2 | 3, 4 | Robot camera frame from Unity answered by the VLM on Kaggle |
| 3 | 5, 6 | Robot completes a task by keyboard, then driven by the VLM |
| 4 | 7 | Same task on Kaggle, Gemini and local; robust to bad output |
| 5 | 8 | Results table, demo video, README; v1.0 |

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
| Local model too slow | High | Low | Use local only for a small subset; report its latency honestly |
| VLM confuses left/right cabinets | Medium | Medium | Distinct door colours (purple/orange); container states in the prompt |
| Laptop runs out of RAM | Medium | High | Session checklist step 1; never run local model + Unity + browsers together |
| Kaggle quota or policy changes | Low | Medium | Gemini (C) as fallback; Colab as a second GPU option |
| Time overrun | Medium | Medium | Phases are independent; ship after Phase 7 with a smaller task suite if needed |
