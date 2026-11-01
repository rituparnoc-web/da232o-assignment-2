# da232o-assignment-2

## Backend (Initial Implementation)

The first implementation slice is the Python service boundary. It validates image-bearing observations, calls an Ollama vision model, parses exactly one action from the permitted schema, and checks the action target against the current visible-target allowlist. It does not yet include a Unity project or a real-model end-to-end demo.

### Prerequisites

- Python 3.12 or newer
- Ollama with an image-capable model available locally; the default model tag is `llama3.2-vision:11b`

### Install and Test

From the repository root in PowerShell:

```powershell
python -m venv .venv
Push-Location backend
..\.venv\Scripts\python.exe -m pip install -e ".[test]"
..\.venv\Scripts\python.exe -m pytest
Pop-Location
```

### Run the API

Start Ollama and make sure the configured vision model is available. The backend defaults to `http://127.0.0.1:11434` and `llama3.2-vision:11b`; configure `OLLAMA_URL`, `VLM_MODEL`, or `VLM_TIMEOUT_SECONDS` in the environment when needed.

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`GET http://127.0.0.1:8000/health` reports API health separately from model readiness. `POST http://127.0.0.1:8000/step` accepts the strict observation contract in `backend/app/schemas.py`. Model or validation failures return structured errors and never a fallback action.