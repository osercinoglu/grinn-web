# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A web service wrapper around the `gRINN` molecular-dynamics analysis tool. The app accepts trajectory uploads (or multi-model PDB ensembles), enqueues them, and launches per-job `grinn:gromacs-*` Docker containers on worker nodes. Results are served back through a per-job dashboard (also a Docker container, image `grinn-dashboard`).

The frontend is a single huge `dash` app (`frontend/app.py`, ~6.7k lines). The backend is Flask + Celery. The two computational entities (`gRINN` analysis containers, `grinn-dashboard` containers) live in separate repos — this repo just orchestrates them via the Docker socket.

## Layout

- `frontend/app.py` — Dash UI, all in one file. Routes are pathname-based via `dcc.Location`: `/`, `/queue`, `/monitor/<id>`, `/help`, `/tutorial`.
- `backend/api.py` — Flask REST API (~1.7k lines). All `/api/...` routes for jobs, workers, dashboards, storage, GROMACS versions, token usage. Also proxies dashboard traffic at `/api/dashboard/<job_id>/<subpath>`.
- `backend/tasks.py` — Celery tasks. `process_grinn_job` is the main one; `cleanup_old_jobs`, `cleanup_job_files`, `monitor_worker_health`, `cleanup_idle_dashboards` run on the embedded beat scheduler (started with `-B`).
- `backend/grinn_runner/executor.py` — wraps `docker run grinn:gromacs-<ver>` and parses output.
- `backend/dashboard_manager.py` — starts/stops `grinn-dashboard` containers per job, allocates ports in `DASHBOARD_PORT_START..END` (default 8100–8200), persists state in Redis.
- `shared/` — anything used by both backend and frontend.
  - `config.py` — single `Config` dataclass loaded from env vars. Loads `.env` from `<repo>/.env` regardless of CWD (Celery workers often have a different CWD).
  - `models.py` — Python dataclasses (`Job`, `JobParameters`, `JobStatus`, `FileType`). Note `JobStatus` is also redefined as a `str, Enum` in `database.py` — same string values, different class.
  - `database.py` — SQLAlchemy ORM (`JobModel`, `WorkerModel`, `ChatTokenUsageModel`) + `DatabaseManager`. SQLite for dev, Postgres for Docker.
  - `local_storage.py` — filesystem layout under `STORAGE_PATH/jobs/<job_id>/{input,output}/`. For multi-worker this directory must be on NFS.
  - `worker_registry.py` — Redis-backed registration/heartbeat tracker.
  - `pdb_validation.py` — pre-upload checks; rejects mmCIF.
  - `notifications.py` — SMTP-based email on job completion (no-op if `SMTP_HOST` blank).
- `scripts/inspect_sim.py` — standalone preflight checker users run on their own bundle *before* uploading. Linked from the UI at `/help#3.7-pre-flight-inspection-tool`; also served raw via Dash as a downloadable file. Don't add server-side imports.
- `standalone-worker.py` — alternative entry point for remote workers that don't want to run `docker-compose.worker.yml`. Discovers `grinn:gromacs-*` images on the local Docker daemon.
- `shared/migrations/*.sql` — applied by `DatabaseManager.init_db()` against Postgres. SQLite path uses `create_all()` only.

## Common commands

Local dev (no Docker). Each line runs in its own terminal:

```bash
conda env create -f environment.yml && conda activate grinn-web   # includes redis-server
redis-server --daemonize yes
python backend/api.py                                              # → :8050
python frontend/app.py                                             # → :8051
celery -A backend.tasks worker -B --loglevel=info                  # -B enables beat scheduler
```

Defaults from `.env.example`: `DATABASE_URL=sqlite:////tmp/grinn_dev.db`, `STORAGE_PATH=/data/grinn-jobs`. For dev you'll usually want `STORAGE_PATH=/tmp/grinn-jobs`.

Single-host Docker:

```bash
docker-compose up -d                                # webapp:8050 (api) + :8051 (dash), worker x2, postgres, redis (static grinn-dashboard:8052 is opt-in: --profile dashboard)
./build-docker.sh                                   # build webapp, worker, dashboard + all 18 GROMACS-versioned grinn images (slow, ~50 GB)
./build-docker.sh --skip-grinn                      # just webapp/worker — fast iteration
./build-docker.sh --no-cache                        # force full rebuild
```

Distributed:

```bash
./deploy-frontend.sh                                # uses docker-compose.frontend.yml
./deploy-worker.sh                                  # uses docker-compose.worker.yml; needs FRONTEND_HOST + WORKER_REGISTRATION_TOKEN
python standalone-worker.py --frontend-host <ip> --registration-token <tok> --storage-path /mnt/grinn-storage
```

There is no test suite. `pytest` is in `requirements.txt` but no `tests/` directory exists — don't claim to "run the tests" without first checking that something testable was actually added.

## Architecture notes worth knowing up front

**Job lifecycle.** Frontend `POST /api/create-job` → DB row in `PENDING` → frontend `POST /api/jobs/<id>/upload` (multipart, files land under `STORAGE_PATH/jobs/<id>/input/`) → `POST /api/jobs/<id>/start` enqueues `process_grinn_job` on the `grinn_jobs` Celery queue → worker picks it up, runs `docker run grinn:gromacs-<ver> ...` mounting the input dir, writes results to `output/`, updates DB status. The frontend polls `/api/jobs/<id>/status` every 3 s from `/monitor/<id>`.

**Two input modes.** `pair_filter_mode` in `JobParameters` and the trajectory-vs-ensemble distinction propagate from the UI all the way into the `grinn` container CLI. Ensemble mode runs an extra `gmx pdb2gmx` step inside the container using the user-selected force field.

**Docker socket is mounted in three services.** Webapp needs it to (a) enumerate `grinn:gromacs-*` images for the dropdown and (b) start `grinn-dashboard` containers. Worker needs it to spawn `grinn:gromacs-*` containers. `grinn-dashboard` itself needs it for its chatbot's DockerSandbox. All three run as `user: root` for this reason.

**Docker-in-Docker path translation.** When the worker (inside a container) starts a child gRINN container, the child needs the **host** path for its bind mount, not the worker's view. That's why `HOST_STORAGE_PATH` and `EXAMPLE_RESULTSn_HOST_PATH` exist alongside the in-container `STORAGE_PATH`/`EXAMPLE_RESULTSn_PATH`. The same applies to the dashboard manager. If you add a new mount, both env vars need wiring.

**Public URLs and reverse proxies.** Several env vars exist for the same reason: `PUBLIC_HOST`, `DASHBOARD_PUBLIC_HOST`, `BACKEND_PUBLIC_URL`, `DASHBOARD_PUBLIC_URL_TEMPLATE`, `FRONTEND_BASE_URL`. They override what gets baked into client-visible links (bookmarkable monitor URLs, dashboard URLs, download URLs). Don't hardcode `localhost` anywhere user-facing.

**Backend API auth.** The backend port is reachable from the internet, so a `before_request` gate (`shared/api_auth.py`) requires `X-Internal-Token` == `INTERNAL_API_TOKEN` on every route except an allowlist: `/api/health`, `GET /api/jobs/<id>/download`, `/api/dashboard/<job_id>/*`, and worker register/heartbeat. The Dash app sends the header through `backend_api` in `frontend/app.py`; use it (not bare `requests`) for any new backend call, and extend the allowlist only for routes that browsers, dashboards or remote workers call directly. It fails closed: no token set means protected routes return 401.

**Abandoned submissions.** Jobs left in `PENDING`/`UPLOADING` (aborted UI submits, scripts calling only `create-job`) are failed and their inputs deleted after `STALE_SUBMISSION_MINUTES` by the `expire_stale_submissions` beat task; the UI also calls `POST /api/jobs/<id>/abort` when a submit breaks off before `/start`.

**Worker auth.** `WORKER_REGISTRATION_TOKEN` must match between frontend `.env` and worker `.env.worker`. Workers register via `POST /api/workers/register`, then heartbeat. The registry lives in Redis (keys under `grinn:worker:*`), with periodic sync to the Postgres `workers` table for capacity tracking.

**GROMACS version dropdown.** The frontend fetches `/api/gromacs-versions` which calls `docker images` (via the mounted socket) and filters by tag prefix `grinn:gromacs-`. If a version isn't shown, the image isn't on that host — check the build script's `GROMACS_VERSIONS` array.

**Storage cleanup.** `cleanup_old_job_files` runs every 6 h via beat and deletes job folders older than `JOB_FILE_RETENTION_HOURS` (default 72). DB rows survive — only files are removed. `mark_jobs_as_expired` separately flips status to `EXPIRED`.

**Two `JobStatus` enums.** `shared.models.JobStatus` (plain `Enum`) and `shared.database.JobStatus` (`str, Enum`). They have identical string values. Code generally imports the model one for typing and the DB one when constructing queries — be explicit which you mean.

**Single-file Dash app.** `frontend/app.py` is monolithic and uses pathname routing via callbacks on `dcc.Location`. Many help/tutorial anchors rely on Dash's auto-slugging (lowercase, hyphens, no extras) — see commit `e7a16af` for a fix where a Pandoc-style `{#anchor}` attribute broke that.

## Skills and tooling

- The user has the `superpowers` skill suite enabled. For creative or multi-step work follow the relevant skill (`brainstorming` before designing, `test-driven-development` before implementation, `verification-before-completion` before claiming done, etc.). For small one-shot tweaks like this file or single-edit bug fixes, skill overhead isn't needed.
- The pre-flight checker `scripts/inspect_sim.py` is end-user facing — keep it dependency-light (stdlib + what gRINN containers already provide) and self-contained.

## Things not to do

- Don't introduce a second `.env` loader — `shared/config.py` already handles the "Celery has a weird CWD" case via `GRINN_WEB_DOTENV_PATH`.
- Don't hardcode the GROMACS version. Pull from `JobParameters` / the UI dropdown; the default lives in `Config.default_gromacs_version`.
- Don't write to `STORAGE_PATH` directly from frontend or backend — go through `LocalStorageManager` so permissions (`DIR_PERMISSIONS = 0o777`, required for cross-container writes) stay correct.
- Don't add `pytest` config or claim tests pass — there are no tests in the repo.
