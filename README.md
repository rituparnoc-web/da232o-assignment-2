# DA232O Assignment 2

## Browser 3D Prototype

The project now uses a browser-based Three.js habitat rather than installing a local game engine. The rover can navigate around obstacles, pick up containers, place them on a delivery platform, and be controlled manually or through a real Qwen2.5-VL request. The browser captures the live WebGL canvas and sends it to the Python API.

The assignment text names Unity or Unreal. This browser-engine alternative needs instructor acceptance before submission.

### Prerequisites

- Python 3.12+
- Node.js 20.19+ and npm
- Ollama with `qwen2.5vl:3b` available locally
- A browser with WebGL enabled

### Install and Test

From the repository root in PowerShell:

```powershell
python -m venv .venv
Push-Location backend
..\.venv\Scripts\python.exe -m pip install -e ".[test]"
..\.venv\Scripts\python.exe -m pytest
Pop-Location

Push-Location web
npm install
npm run build
Pop-Location
```

### Run the Application

After installing, use three separate PowerShell terminals. First, make sure the vision model is installed:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen2.5vl:3b
```

In **Terminal 1**, start Ollama if the desktop app is not already serving requests. If `ollama` is on PATH, use `ollama serve`; otherwise run:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
```

In **Terminal 2**, start the backend:

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In **Terminal 3**, start the browser app:

```powershell
Push-Location web
npm run dev -- --port 5173
```

Open <http://127.0.0.1:5173/>. Check API/model readiness from another PowerShell terminal with:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

The result should show `model_ready: true`. `POST /step` accepts the strict image-bearing observation contract. Set `VITE_API_BASE_URL` to change the browser API address. The backend only allows the two localhost Vite origins by default.

The **Ask VLM** action captures the current scene and sends it with the instruction, visible IDs/categories, interaction-range flags, carry state, and previous result. A validated `pick_up` proposal selects the target; the browser controller then performs a bounded approach/pickup/delivery sequence and independently verifies the scene. The **Manual dispatch** buttons and rover steering provide a deterministic control path for testing.

To require a particular table route while carrying a container to the platform, include `north side of the table`, `south side of the table`, `east side of the table`, or `west side of the table` in the instruction. North is negative Z, south is positive Z, east is positive X, and west is negative X. The route uses the scene's fixed table and obstacle layout.

### Verification

- 22 backend tests pass.
- `npm run build` succeeds.
- Desktop and 375 px mobile layouts render without horizontal overflow.
- A real browser-to-Ollama run selected `object_01`, moved the rover, delivered the blue tote, and reached `VERIFIED`.

Qwen2.5-VL 3B is the verified model. A cold response has ranged from about 29 to 106 seconds on this machine. Llama 3.2 Vision is installed but incompatible with the local Ollama runner (`unknown model architecture: mllama`). The browser scene uses generated geometry and labels; Unity/Unreal assignment acceptance remains unconfirmed.

### Troubleshooting

- If the header reports `API OFFLINE`, confirm the backend is listening at `127.0.0.1:8000` and check `GET /health`.
- If the model is not ready, start Ollama and confirm `ollama list` includes `qwen2.5vl:3b`.
- If Qwen returns an empty action and Ollama logs `Unexpected empty grammar stack` or repeated tokens, stop Ollama and try CPU-only inference. On the tested Windows NVIDIA system, start Ollama in a new PowerShell terminal with:
	```powershell
	$env:OLLAMA_VULKAN = "0"
	$env:CUDA_VISIBLE_DEVICES = "-1"
	ollama serve
	```
	CPU inference may be slower. These settings apply to that terminal session only.
- If a model request times out, allow additional time for cold inference or set `VLM_TIMEOUT_SECONDS` before starting the backend.
- If the 3D view is blank, use a browser with WebGL and hardware acceleration enabled.