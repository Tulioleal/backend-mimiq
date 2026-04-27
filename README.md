# PVC

PVC (Private Voice Clone) is a self-hosted voice cloning platform built around XTTS v2. It is designed to keep voice data inside infrastructure you control while still supporting high-quality synthesis, reusable voice samples, and real-time audio streaming.

The project is split into three main parts:

- `backend/`: FastAPI API layer on GCP for auth, voice storage, audio health checks, LLM preprocessing, and WebSocket proxying
- `xtts-vm/`: XTTS service that runs on Vast.ai and registers itself back to the backend when ready
- `infra/`: OpenTofu configuration for the GCP backend VM, Cloud SQL, networking, and storage buckets

## Architecture

The runtime flow is:

1. The frontend sends a generation request to `backend/`
2. The backend validates the session and rewrites the text through the configured LLM API
3. If the TTS service is offline, the backend dispatches the `xtts-vm` GitHub Actions startup workflow
4. GitHub Actions boots the Vast.ai instance and starts the XTTS service
5. The XTTS service calls the backend internal readiness endpoint
6. The backend opens a WebSocket connection to the TTS service and proxies audio chunks back to the client
7. Generated audio is stored in GCS and recorded in PostgreSQL

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
- A GitHub repository with Actions enabled for `xtts-vm/`
- A Vast.ai account and API key for `xtts-vm/`
- A Docker Hub account if you plan to publish the XTTS image from GitHub Actions
- An LLM API endpoint for text preprocessing

## Setup Overview

Recommended order:

1. Configure GCP infrastructure in `infra/`
2. Configure and run the FastAPI backend in `backend/`
3. Configure `xtts-vm/` GitHub Actions secrets and build the XTTS image
4. Point the backend at the GitHub workflow used to start the XTTS service
5. Trigger generation and verify the XTTS service registers back to the backend

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
- `INTERNAL_SECRET`: shared secret used by `xtts-vm` when calling backend internal endpoints
- `BACKEND_PUBLIC_URL`: public URL the XTTS service can call back into
- `GITHUB_TOKEN`: token used by backend to dispatch the XTTS startup workflow
- `GITHUB_OWNER`: owner of the `xtts-vm` repository
- `GITHUB_REPO`: repository name containing the workflow
- `GITHUB_START_WORKFLOW`: workflow filename, for example `start-tts.yml`
- `GITHUB_REF`: branch or tag to dispatch

Optional local override:

- `TTS_ENDPOINT`: bypass startup workflow dispatch and point backend directly at a running TTS service

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
- WebSocket generation proxy at `/ws/generations/stream`
- internal callbacks at `/internal/tts-ready` and `/internal/tts-offline`

### Run Backend Tests

```bash
cd backend
pytest
```

## 3. XTTS Service Setup

The XTTS service runs on Vast.ai and is controlled through GitHub Actions in `xtts-vm/`.

See `xtts-vm/README.md` for the detailed service-specific setup.

At a minimum:

1. Configure GitHub Actions secrets in the `xtts-vm` repository
2. Build and publish the Docker image
3. Ensure these secrets are present:

- `VAST_API_KEY`
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
- `BACKEND_URL`
- `INTERNAL_SECRET`

The startup workflow should boot the Vast.ai instance, start the XTTS service, and let the XTTS service call:

- `POST /internal/tts-ready` when it is available
- `POST /internal/tts-offline` when it shuts down or the watchdog terminates it

## 4. End-to-End Startup Flow

Once infrastructure and secrets are configured:

1. Start the backend
2. Authenticate with `X_ADMIN_KEY`
3. Upload a voice sample
4. Send a generation request through the backend WebSocket
5. Backend dispatches the GitHub Actions startup workflow if compute is offline
6. Wait for `booting` to transition to `ready`
7. Retry generation once the XTTS service has registered itself

## Notes

- The backend does not talk to Vast.ai directly.
- `xtts-vm/` is the only component that should own Vast.ai lifecycle logic.
- The backend remains responsible for auth, persistence, GCS operations, LLM preprocessing, and proxying the TTS stream.
- The PRD for the system lives in `PRD.md`.
