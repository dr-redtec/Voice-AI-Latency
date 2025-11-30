# Voice-AI-Latency
Repo for Master Thesis
**Overview**
- **Project:**: Voice-AI-Latency — tooling and experiments for measuring and simulating latency in voice AI stacks (TTS / STT / telephony / tracing).
- **Location:**: `d:/Documents/GitHub/Voice-AI-Latency`

**Requirements**
- **Python:**: 3.9+ recommended. Create a virtual environment before installing packages.
- **Pip deps:**: install from `requirements.txt` if present, otherwise install the repo's runtime deps used by `app/`.
- **System:**: Docker & Docker Compose for local services (Redis, Jaeger). `ngrok` for exposing a websocket endpoint during development.

**CUDA / STT (Speech-to-Text)**
- **When needed:**: Some STT backends or local neural models require GPU acceleration. If you plan to run STT locally (or any model that uses CUDA), you must install NVIDIA drivers + CUDA toolkit compatible with your chosen backend.
- **Supported CUDA versions:**: Match the CUDA toolkit version to the framework (e.g., PyTorch or TensorFlow) versions you will install. Check the model/backend docs for required CUDA/CuDNN versions.
- **Install steps (high level):**
	- Install NVIDIA driver for your GPU (Windows: use the official NVIDIA installer).
	- Install CUDA Toolkit (see NVIDIA docs) that matches your Python ML libs.
	- Verify with: `nvidia-smi` and inside Python `import torch; torch.cuda.is_available()` (or equivalent for your framework).
- **Environment variables:**: set `CUDA_VISIBLE_DEVICES` if you want to control which GPU is used.

**Create a Python env from repo config**
- **Step 1 — create venv:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

- **Step 2 — install dependencies:**

```powershell
pip install -r requirements.txt
```

- **Step 3 — populate runtime config / env:**
	- The repo has configuration in `app/config/` (for example `app/config/config.py`). If the project expects environment variables, create a `.env` file in the repo root or set the variables in your shell.
	- Example `.env` (adjust values):

```
# .env example
REDIS_URL=redis://localhost:6379
JAEGER_AGENT_HOST=localhost
JAEGER_AGENT_PORT=6831
APP_ENV=development
```

- **Step 4 — run the app locally:**

```powershell
# from repo root
python -m app.main
```

**Docker (Redis + Jaeger)**
- **Purpose:**: Run Redis and Jaeger locally for development/tracing and as a backend for the app.
- **Quick Docker Compose:**

```yaml
version: '3.8'
services:
	redis:
		image: redis:7
		container_name: voiceai_redis
		ports:
			- "6379:6379"

	jaeger:
		image: jaegertracing/all-in-one:1.42
		container_name: voiceai_jaeger
		environment:
			COLLECTOR_ZIPKIN_HTTP_PORT: 9411
		ports:
			- "6831:6831/udp"   # Jaeger agent (UDP)
			- "16686:16686"     # Jaeger UI
			- "14268:14268"     # Collector HTTP

# Save as docker-compose.yml and run:
# docker compose up -d
```

- **Commands:**

```powershell
# start services
docker compose up -d
# stop services
docker compose down
```

**Expose a local websocket via ngrok**
- **Why:**: If your telephony or front-end test harness needs a publicly reachable websocket/ws endpoint (for callbacks or webhooks), `ngrok` is convenient.
- **Install:**: Download from https://ngrok.com and authenticate with your account token.
- **Expose HTTP/Websocket port (example port 8000):**

```powershell
# start local app (example):
python -m app.main
# in another terminal, expose
ngrok http 8000
```

- **Notes:**
	- Use the `Forwarding` URL from ngrok (wss:// or https://) and set that in your telephony/webhook provider.

**Development tips & troubleshooting**
- **Logging:**: Logging config lives under `app/config/logging_config.py` — adjust log levels as needed.
- **Tracing:**: If Jaeger traces are not showing, ensure `JAEGER_AGENT_HOST` and `JAEGER_AGENT_PORT` are set and that the app's tracer is enabled.
- **Redis connectivity:**: Check `redis-cli -h localhost -p 6379` or `Test-Connection` in PowerShell.

**Project layout (high level)**
- **App code:**: `app/` contains the main application, providers, services, pipelines, and processors.
- **Scripts:**: Top-level scripts such as `export_from_jaeger.py`, `count_calls.py`, and `start-services.sh` provide utilities and helpers used during experimentation.

