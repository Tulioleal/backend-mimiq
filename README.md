# PVC

PVC (Private Voice Clone) is a self-hosted voice cloning platform built around XTTS v2. It is designed to keep voice data inside infrastructure you control while still supporting high-quality synthesis, reusable voice samples, and real-time audio streaming.

The project is split into three main parts:

- `backend/`: FastAPI API layer on GCP for auth, voice storage, audio health checks, LLM preprocessing, and TTS worker coordination
- `xtts-vm/`: XTTS service image that runs on a RunPod pod and connects back as a worker
- `infra/`: OpenTofu configuration for the GCP backend VM, Cloud SQL, networking, and storage buckets

## Architecture

The runtime flow is:

1. The frontend sends a generation request to `backend/`
2. The backend validates the session and rewrites the text through the configured LLM API
3. If the TTS service is offline, the backend creates or reuses a RunPod pod through the RunPod REST API
4. RunPod starts the XTTS container from the configured image
5. The XTTS service connects to the backend worker WebSocket
6. The backend sends synthesize jobs over that socket and proxies streamed audio chunks back to the client
7. The XTTS service uploads the completed WAV back to the backend
8. Generated audio is stored in GCS and recorded in PostgreSQL

## Repository Layout

```text
foro-7/
├── backend/      FastAPI backend
├── frontend/     Frontend work and references
├── infra/        OpenTofu infrastructure
├── xtts-vm/      Vast.ai XTTS service and GitHub Actions workflows
└── PRD.md        Product requirements document
```

## Prerequisites

You will need:

- Python 3.11+ for `backend/`
- OpenTofu for `infra/`
- A GCP project with Cloud SQL and GCS access
- A RunPod API key for GPU pod lifecycle management
- A Docker Hub account if you plan to publish the XTTS image from GitHub Actions
- An LLM API endpoint for text preprocessing

## Setup Overview

Recommended order:

1. Configure GCP infrastructure in `infra/`
2. Configure and run the FastAPI backend in `backend/`
3. Build and publish the XTTS image
4. Point the backend at the image and RunPod API credentials used to start the XTTS service
5. Trigger generation and verify the XTTS service connects back to the backend worker WebSocket

## 1. Infrastructure Setup

See `infra/README.md` for the full details.

Bootstrap the remote state bucket:

```bash
cd infra/bootstrap
cp terraform.tfvars.example terraform.tfvars
tofu init
tofu apply
```

Deploy the production stack:

```bash
cd infra/environments/prod
cp tofu.tfvars.example tofu.tfvars
tofu init -backend-config="bucket=<your-state-bucket-name>"
tofu plan
tofu apply
```

This provisions:

- backend VM
- Cloud SQL PostgreSQL
- GCS buckets for voice samples and generated audio
- networking and firewall rules

## 2. Backend Setup

The backend is the control plane for the system.

### Environment

Create a local env file:

```bash
cd backend
cp .env.example .env
```

Important backend settings:

- `X_ADMIN_KEY`: admin login key used by the frontend
- `DATABASE_URL` or `DB_*`: PostgreSQL connection
- `GCS_SAMPLE_BUCKET`: bucket for uploaded voice samples
- `GCS_OUTPUT_BUCKET`: bucket for generated outputs
- `LLM_API_URL`: text rewrite endpoint
- `INTERNAL_SECRET`: shared secret used by `xtts-vm` when connecting to backend internal endpoints
- `BACKEND_PUBLIC_URL`: public URL the XTTS service can call back into
- `TTS_PROVIDER`: set to `runpod`
- `RUNPOD_API_KEY`: RunPod REST API key used only by the backend
- `RUNPOD_IMAGE_NAME`: XTTS worker image to run, for example `<dockerhub-user>/pvc-tts:latest`
- `RUNPOD_GPU_TYPE_IDS`: comma-separated RunPod GPU type preference list
- `RUNPOD_GPU_TYPE_PRIORITY`: usually `availability`
- `RUNPOD_SHUTDOWN_ACTION`: set to `delete` to remove idle pods
- `TTS_IDLE_TIMEOUT_SECONDS`: idle time before backend deletes the pod
- `BACKEND_URL`: public HTTP URL the XTTS worker can call back into
- `BACKEND_WS_URL`: public worker WebSocket URL, for example `wss://api.example.com/internal/tts-worker/ws`

### Install

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

If editable install is not available in your environment, use:

```bash
pip install .
```

### Database Migration

```bash
cd backend
alembic upgrade head
```

### Run the Backend

```bash
cd backend
uvicorn main:app --app-dir src --reload
```

The backend exposes:

- `GET /health`
- `POST /api/auth/login`
- `GET /api/status/gpu`
- voice CRUD endpoints under `/api/voices`
- generation history endpoints under `/api/generations`
- WebSocket generation stream at `/ws/generations/stream`
- internal worker WebSocket at `/internal/tts-worker/ws`
- internal job files at `/internal/jobs/{job_id}/speaker.wav` and `/internal/jobs/{job_id}/result`
- internal offline callback at `/internal/tts-offline`

### Run Backend Tests

```bash
cd backend
pytest
```

## 3. XTTS Service Setup

The XTTS service runs as a provider-neutral worker container. The backend creates a RunPod pod and passes only callback settings and worker identity into the container.

See `xtts-vm/README.md` for the detailed service-specific setup.

At a minimum:

1. Build and publish the Docker image
2. Configure backend RunPod settings
3. Ensure these values are available to the worker from the backend-created pod environment:

- `BACKEND_URL`
- `BACKEND_WS_URL`
- `INTERNAL_SECRET`
- `TTS_INSTANCE_ID`

The XTTS service should:

- connect to `WS /internal/tts-worker/ws` when it is available
- fetch `GET /internal/jobs/{job_id}/speaker.wav` for each synthesize job
- upload `POST /internal/jobs/{job_id}/result` when a final WAV is ready
- `POST /internal/tts-offline` when it shuts down or the watchdog terminates it

## 4. End-to-End Startup Flow

Once infrastructure and secrets are configured:

1. Start the backend
2. Authenticate with `X_ADMIN_KEY`
3. Upload a voice sample
4. Send a generation request through the backend WebSocket
5. Backend creates a RunPod pod if compute is offline
6. Wait for `booting` to transition to `ready`
7. Retry generation once the XTTS worker has connected

## Notes

- The backend owns RunPod pod create/delete lifecycle through the REST API.
- `RUNPOD_API_KEY` must not be passed into the XTTS worker container.
- The backend remains responsible for auth, persistence, GCS operations, LLM preprocessing, and proxying the TTS stream.
- The PRD for the system lives in `PRD.md`.
