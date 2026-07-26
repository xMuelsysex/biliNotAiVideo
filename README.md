# Bilibili AI Video Identification

Chrome / Edge Manifest V3 extension and FastAPI service for displaying shared,
explainable AI-content evidence labels on Bilibili videos.

The extension owns Bilibili page integration and presentation. FastAPI owns the
public API, anonymous installation authentication, validation, and quotas.
PostgreSQL is the durable authority for targets, attempts, results, declarations,
and the outbox. Redis provides rebuildable delivery, leases, and rate counters.

## Requirements

- Python 3.12
- Node.js 20 or newer and npm 10 or newer
- PostgreSQL 16 and Redis 7 for backend integration tests
- Docker Engine with Compose v2 for the deployment stack

## Backend Development

```bash
cd backend
uv python install 3.12
uv sync --locked --python 3.12 --extra dev
. .venv/bin/activate

ruff check .
mypy app
pytest -q
uvicorn app.main:app --reload
```

`GET http://127.0.0.1:8000/health` is a process liveness check. `GET /ready`
checks PostgreSQL and Redis and returns `503` while either dependency is
unavailable.

Integration and API tests require isolated services. The database name must end
with `_test` because the tests migrate and truncate it.

```bash
export BILI_AI_TEST_DATABASE_URL='postgresql+asyncpg://user:password@127.0.0.1:5432/bili_ai_test'
export BILI_AI_TEST_REDIS_URL='redis://127.0.0.1:6379/0'
cd backend && uv run pytest -q
```

## Configuration

Backend variables use the `BILI_AI_` prefix. Start from
[`deploy/.env.example`](deploy/.env.example). Required deployment values are:

- `BILI_AI_DATABASE_URL`: PostgreSQL async URL.
- `BILI_AI_REDIS_URL`: Redis URL; Redis remains disposable.
- `BILI_AI_ALLOWED_EXTENSION_ORIGINS`: JSON list of exact
  `chrome-extension://<id>` origins.
- `BILI_AI_BCUT_API_BASE`: absolute BCut-compatible ASR base URL.
- `BILI_AI_AI_API_BASE`, `BILI_AI_AI_API_KEY`, `BILI_AI_AI_MODEL`: external
  OpenAI-compatible detector configuration.
- `BILI_AI_MEDIA_WORKSPACE_MAX_BYTES`: maximum temporary bytes per analysis
  workspace, default 256 MiB.
- `BILI_AI_MEDIA_COMMAND_TIMEOUT_SECONDS`: timeout for each media subprocess,
  default 300 seconds.
- `BILI_AI_ANALYSIS_TASK_TIMEOUT_SECONDS`: whole worker-job timeout, default
  900 seconds.

Never commit filled `.env` files, installation tokens, model credentials,
Bilibili cookies, or TLS private keys.

## API

Register an anonymous installation and retain the returned raw token locally:

```bash
curl -sS -X POST https://localhost/api/v1/installations
```

The server persists only the SHA-256 token hash. Authenticated endpoints use
`Authorization: Bearer <token>`:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" \
  'https://localhost/api/v1/analyses/BV1Q541167Qg?cid=123'

curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"bvid":"BV1Q541167Qg","cid":123}' \
  https://localhost/api/v1/analyses

curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"bvids":["BV1Q541167Qg"]}' \
  https://localhost/api/v1/analyses/batch
```

The batch endpoint is read-only and returns current results for canonical
default CIDs. It never creates analysis work.

## Extension

```bash
cd extension
npm ci
npm run lint
npm run test -- --run
npm run build
npm run test:e2e
```

Build against the deployment origin:

```bash
VITE_API_ORIGIN=https://api.example.com npm run build
```

Open `chrome://extensions` or `edge://extensions`, enable Developer mode, choose
"Load unpacked", and select `extension/dist`. The package requests `storage`,
Bilibili page access, and the configured API origin. It does not request browser
history, Bilibili cookies, or arbitrary host access.

## Docker Compose

Create a local environment file and TLS certificate. The following certificate
is for local testing only; public deployments should use a trusted certificate.

```bash
cp deploy/.env.example deploy/.env
mkdir -p deploy/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 7 \
  -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost' \
  -keyout deploy/certs/localhost-key.pem \
  -out deploy/certs/localhost.pem
cp deploy/certs/localhost.pem deploy/certs/ca.pem
```

Fill every required value in `deploy/.env`. For localhost keep
`CADDY_SITE_ADDRESS=https://localhost`. For a public beta set it to the deployed
API origin, mount a trusted certificate through `TLS_CERT_PATH` and
`TLS_KEY_PATH`, and set `VITE_API_ORIGIN` to the same origin before building the
extension. Certificate renewal is external to the container; after replacing
the mounted files, validate and reload Caddy.

Render and start the stack:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml config
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs migrate
curl --fail --cacert deploy/certs/ca.pem https://localhost/health
curl --fail --cacert deploy/certs/ca.pem https://localhost/ready
```

The one-shot `migrate` service must exit with code 0 before API, dispatcher, and
worker start. PostgreSQL data uses the `postgres_data` volume. Redis has no
persistent volume. Worker media uses a 2 GiB tmpfs plus per-workspace and time
limits.

The default resource budget targets the recommended 4-vCPU/8-GiB host: two
worker replicas provide two concurrent analysis slots, and all steady-state
service limits total 3.75 CPUs and about 7 GiB RAM. Tune `WORKER_REPLICAS`
between 2 and 4 only after measuring queue depth, task duration, external API
spend, CPU, memory, and tmpfs pressure; adjust `WORKER_CPUS` and
`WORKER_MEMORY` with the host budget.

Validate and reload renewed TLS material with:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml \
  exec caddy caddy validate --config /etc/caddy/Caddyfile
docker compose --env-file deploy/.env -f deploy/docker-compose.yml \
  exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Build and export the extension through Compose with:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml \
  --profile extension run --rm extension-build
```

Stop the stack while retaining PostgreSQL data:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down
```

## Performance Protocol

Run performance checks only against an isolated database whose name ends with
`_perf`. Configure the performance stack with `POSTGRES_DB=bili_ai_perf`, a
matching `BILI_AI_DATABASE_URL`, a loopback-only `POSTGRES_HOST_PORT`, and
`BILI_AI_QUERY_PER_MINUTE_LIMIT=1000000`. The elevated query limit belongs only
to the isolated benchmark stack.

Seed exactly 100,000 current results before registering the benchmark token;
the seeder truncates the `_perf` database, including installation tokens.

```bash
export PERF_DATABASE_URL='postgresql+asyncpg://bili:password@127.0.0.1:55433/bili_ai_perf'
cd backend
uv run python ../scripts/seed_performance_data.py \
  --database-url "$PERF_DATABASE_URL" --rows 100000
cd ..

export PERF_INSTALLATION_TOKEN="$(
  curl -sS --cacert deploy/certs/ca.pem -X POST \
    https://localhost/api/v1/installations | jq -r .token
)"

backend/.venv/bin/python scripts/perf_cached_queries.py \
  --base-url https://localhost \
  --ca-cert deploy/certs/ca.pem \
  --database-url "$PERF_DATABASE_URL" \
  --expected-rows 100000
```

The fixed protocol checks at least 4 CPUs and 8 GiB RAM, uses 20 closed-loop
connections, warms each single/batch run for 30 seconds, measures each for five
minutes, and requires at least 1,000 successes. It fails when P95 reaches 500 ms
or the error rate reaches 1%. JSON reports are written to
`artifacts/performance/`.

## Privacy And Retention

Long-term storage contains scores, labels, confidence, declaration state,
concise evidence descriptions, timestamps, and analysis versions. Raw video,
audio, subtitles, and sampled frames remain in a unique worker workspace and
are removed after success, failure, timeout, or cancellation. User Bilibili
cookies never leave the browser; an optional service-owned cookie stays on the
backend.

Logs exclude raw installation tokens, full transcripts, model credentials, and
cookie values. Shared results are global to a target and remain independent of
installation-token lifecycle.

## Backup And Recovery

Back up PostgreSQL; Redis and temporary media are rebuildable:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml \
  exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > bili-ai.sql
```

Test restores against a separate database before production use. Schema
downgrades, destructive restores, and volume deletion require an explicit data
migration or recovery decision. After Redis loss, the dispatcher and
reconciler rebuild delivery intent from PostgreSQL.

## Upgrade And Rollback

Before an upgrade, capture and test a PostgreSQL backup, record current image
digests, and review pending Alembic revisions. Build the replacement images,
run the one-shot migration, then start API, dispatcher, and workers only after
migration exits successfully. Verify `/ready`, one authenticated cached query,
queue depth, and worker errors before replacing the extension artifact.

Application rollback uses the previously recorded image digests while retaining
PostgreSQL. Schema downgrade or restore can discard data and requires a separate
migration decision plus explicit approval. When a migration fails, keep API and
workers stopped, preserve logs and the database volume, then repair forward or
restore into a separate database before traffic resumes.

## Operations And Alerts

Collect structured service logs outside the containers with bounded retention.
Alert on `/ready` failure, growing Redis stream depth, old undelivered outbox
rows, attempts beyond the 900-second task limit, failure-rate spikes by
`error_code`, tmpfs pressure, PostgreSQL disk/connection saturation, external
AI/ASR spend, and TLS expiry. Review queue depth and P95 task duration before
raising `WORKER_REPLICAS`; each replica uses a unique hostname-derived Redis
consumer identity.

## Troubleshooting

- `migrate` failed: inspect `docker compose ... logs migrate` and verify the
  PostgreSQL URL, credentials, and schema permissions.
- `/ready` returns `503`: inspect API, PostgreSQL, and Redis health before
  restarting workers.
- Worker exits at startup: set `BILI_AI_BCUT_API_BASE` and the detector base,
  model, and credentials.
- Analysis remains queued: inspect dispatcher logs, Redis health, outbox rows,
  and reconciliation logs. PostgreSQL remains the lifecycle authority.
- Extension shows no badge: confirm its baked `VITE_API_ORIGIN`, exact extension
  origin allowlist, token registration, and current default-CID result.
- Local TLS fails: confirm the certificate includes `localhost` in subjectAltName
  and that the client trusts `PERF_CA_CERT`.
