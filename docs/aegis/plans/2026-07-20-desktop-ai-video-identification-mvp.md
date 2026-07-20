# Desktop AI Video Identification MVP Implementation Plan

## Goal

Implement the approved Chrome / Edge extension and public Python analysis service defined in `docs/aegis/specs/2026-07-20-desktop-ai-video-identification-design.md`.

The delivered MVP must display shared AI-evidence labels on Bilibili video pages and cached recommendation cards, create one recoverable versioned analysis attempt per target, and keep raw media temporary.

## Architecture

- Chromium Manifest V3 extension owns Bilibili DOM integration and presentation.
- FastAPI owns public API contracts, server-issued installation tokens, validation, and quotas.
- PostgreSQL owns target fencing, last successful result, declaration state, durable attempts, outbox events, default-CID metadata, and token hashes.
- Redis owns rebuildable queue delivery, worker leases, and rate-limit counters.
- Python workers own Bilibili acquisition, sampled ASR/frames, detector execution, scoring, and cleanup.
- A single score aggregator owns score, confidence, and label mapping.

## Tech Stack

- Python 3.12
- FastAPI, Uvicorn
- SQLAlchemy 2.x async, asyncpg, Alembic
- redis-py asyncio
- httpx
- pydantic-settings
- yt-dlp, imageio-ffmpeg
- OpenAI-compatible multimodal HTTP API for text/visual evidence
- pytest, pytest-asyncio, respx, Ruff, mypy
- TypeScript 5, Vite, `@crxjs/vite-plugin`
- Vitest, jsdom, Playwright
- PostgreSQL 16, Redis 7, Docker Compose, Caddy

## Baseline / Authority Refs

- `CONTEXT.md`
- `docs/aegis/BASELINE-GOVERNANCE.md`
- `docs/aegis/specs/2026-07-20-desktop-ai-video-identification-design.md`
- Reference implementation: `storyAura/astrbot_plugin_biliVideo` at commit `a0a7bef0ecf5c8b698f8ea3837da839d0632a295`

## Compatibility Boundary

- Chrome and Edge only, Manifest V3.
- Bilibili video detail pages and homepage/recommendation cards only.
- Public API stays under `/api/v1`.
- PostgreSQL is required for persistent execution correctness; SQLite is outside the implementation path.
- Redis loss must be recoverable from PostgreSQL.
- User Bilibili cookies never leave the browser.
- Mobile, Firefox, Safari, raw-media retention, local multimodal inference, and account systems remain outside scope.

## TDD Route

- Mode: off
- Decision: skipped
- Strict authority: not applicable
- Test posture: post-change regression
- Reason: the user approved an implementation plan but did not request strict/test-first TDD.
- Verification: each task adds the minimum implementation and immediately runs focused unit, integration, type, build, or smoke checks.

## Verification

Backend target commands:

```bash
cd backend
python -m pip install -e '.[dev]'
ruff check .
mypy app
pytest -q
```

Extension target commands:

```bash
cd extension
npm ci
npm run lint
npm run test -- --run
npm run build
npm run test:e2e
```

Deployment target commands:

```bash
docker compose -f deploy/docker-compose.yml config
docker compose -f deploy/docker-compose.yml up -d --build
curl --fail http://localhost:8000/health
```

## Aegis Visibility

Planning is required because this work creates a public API, persistent schema, versioned task ownership, browser distribution surface, and cross-process recovery contract. The plan keeps each owner singular and makes recovery and verification executable before source files exist.

## Plan Basis

- Fact: the project currently contains design/context documents and no source implementation.
- Fact: the project directory is not currently a Git repository.
- Fact: the approved design fixes scoring semantics, shared results, database ownership, token issuance, default CID ownership, fencing, and Redis-loss recovery.
- Assumption: one public beta deployment uses a 4-vCPU / 8-GB host.
- Unknown: the production external multimodal provider; the implementation uses one OpenAI-compatible provider configured through environment variables.

## BaselineUsageDraft

- Required baseline refs: `CONTEXT.md`, approved design spec, baseline governance.
- Delivered context refs: approved decisions recorded in the design spec.
- Acknowledged before plan refs: all required refs above.
- Cited in plan refs: domain scoring terms, API/persistence ownership, acceptance criteria.
- Missing refs: no existing code or deployment baseline exists.
- Decision: continue.

## Requirement Ready Check

- Requirement source refs: approved design spec and `CONTEXT.md`.
- Goals and scope refs: design sections 1–5.
- User / scenario refs: detail-page automatic analysis, homepage cached badges, missing subtitles, shared results.
- Requirement item refs: design sections 6–16.
- Acceptance / verification criteria refs: design sections 17–18.
- Open blocker questions: none for implementation planning; provider credentials remain deployment configuration.
- Decision: ready.

## Change Necessity

- User-visible need: display shared AI evidence labels and analyze uncached videos.
- No-change / non-code option: documentation alone cannot inspect Bilibili pages, acquire materials, coordinate analysis, or persist results.
- Why code change is necessary: the project has no runtime implementation.
- Minimum change boundary: one extension, one API/worker backend, PostgreSQL persistence, Redis transient coordination, and deployment configuration.
- Decision: code-change.

## Existence Check

- Proposed new surfaces: extension, API, worker, score aggregator, PostgreSQL records, Redis coordination, deployment stack.
- Existing owner / reuse candidate: no project source owner exists; the reference repository provides acquisition patterns only.
- Why existing surface is insufficient: AstrBot message handlers cannot provide browser integration or the approved public API/persistence contract.
- Creation proof: every surface maps to an approved canonical owner in the design spec.
- Entropy / retirement impact: no parallel implementation, storage fallback, provider registry, or plugin-side score owner is added.
- Decision: add-with-proof.

## Architecture Integrity Lens

- Invariant: one target-level writer owns each `(bvid, cid)` result generation.
- Canonical owner / contract: PostgreSQL target/result/declaration/attempt/outbox records and `/api/v1`.
- Responsibility overlap: Redis never becomes persistent task authority; the extension never computes authoritative scores.
- Higher-level simplification: one worker pipeline and one OpenAI-compatible evidence client serve both text and visual evidence.
- Retirement / falsifier: any second result store, caller-side score fallback, or unrecoverable Redis-only queue violates the design.
- Verdict: proceed.

## Plan Pressure Test

- Owner / contract / retirement: owners are explicit; no legacy runtime exists.
- Architecture integrity / higher-level path: target fencing and outbox recovery stay in the backend repository layer.
- Verification scope: unit, database concurrency, recovery, extension DOM, E2E, and performance.
- Task executability: tasks below name exact files and commands.
- Pressure result: proceed.

## Plan-Time Complexity Check

- Artifact class: greenfield service and browser extension.
- Current pressure: no source files.
- Projected pressure: repository state machine and acquisition pipeline are the largest owners.
- Budget result: within-budget when state transitions, acquisition, detectors, and UI adapters remain separate modules.
- Planned governance: target files under roughly 300 lines; split by canonical owner before exceeding that boundary.
- Recommendation: add owner files with narrow interfaces; avoid registries and compatibility adapters.

## Execution Readiness View

- Intent Lock: implement the approved desktop MVP only.
- Scope Fence: Chrome/Edge, Bilibili, public service, shared results.
- Baseline Lock: `CONTEXT.md` and the approved design spec.
- Approved Behavior: detail-page auto analysis, homepage read-only badges, four labels, independent declaration/confidence.
- Owner / Contract Constraints: PostgreSQL persistent authority; Redis transient; server-issued token; score aggregator canonical.
- Compatibility Boundary: `/api/v1`, MV3, Postgres 16, Redis 7.
- Retirement Boundary: no temporary mock storage or Redis-only task owner survives completion.
- Task Batches: foundation; persistence/API; acquisition/worker; extension; deployment/E2E.
- Test Obligations: focused regression after each task plus final full verification.
- Review Gates: schema/state machine review before worker integration; API contract review before extension integration.
- Drift / Rewind Rules: return to the design spec when a task adds a new owner, storage path, public field, or fallback.
- Evidence Required Before Completion: full checks, recovery tests, cleanup tests, extension build/E2E, compose smoke, fixed performance protocol.
- Advisory Boundary: method-pack execution guidance only; not completion authority.

## File Map

```text
backend/
  pyproject.toml
  alembic.ini
  app/
    main.py
    config.py
    api/{deps.py,schemas.py,installations.py,analyses.py}
    domain/{types.py,scoring.py,errors.py}
    db/{session.py,models.py,repository.py}
    services/{tokens.py,rate_limits.py,freshness.py,outbox.py,reconciliation.py}
    integrations/bilibili/{client.py,metadata.py,media.py,bcut.py}
    detectors/{openai_compatible.py,prompts.py}
    workers/{pipeline.py,runner.py}
  migrations/versions/0001_initial.py
  tests/
extension/
  package.json
  manifest.config.ts
  vite.config.ts
  tsconfig.json
  src/background/{service-worker.ts,api-client.ts,token-store.ts}
  src/content/{entry.ts,route-observer.ts,bilibili-id.ts,video-page.ts,recommendation-feed.ts}
  src/ui/{badge.ts,detail-panel.ts,styles.css}
  tests/
deploy/
  docker-compose.yml
  Caddyfile
  backend.Dockerfile
  extension.Dockerfile
  .env.example
scripts/
  seed_performance_data.py
  perf_cached_queries.py
README.md
.gitignore
```

## Task 1: Scaffold backend, extension, and quality gates

**Files**

- Create: `.gitignore`, `README.md`
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/main.py`, `backend/app/config.py`
- Create: `extension/package.json`, `extension/tsconfig.json`, `extension/vite.config.ts`, `extension/manifest.config.ts`
- Create: initial directories from the File Map

**Why**

Create the minimum executable project boundaries and repeatable validation commands before adding behavior.

**Change Necessity**

The project has no source implementation. Backend and extension scaffolds are the minimum runtime boundary.

**Impact / Compatibility**

No public behavior exists yet. Use Python 3.12 and Node 20+ as explicit toolchain floors.

**Steps**

1. Add Python runtime dependencies: `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `redis`, `httpx`, `pydantic-settings`, `yt-dlp`, `imageio-ffmpeg`.
2. Add Python dev dependencies: `pytest`, `pytest-asyncio`, `respx`, `ruff`, `mypy`.
3. Configure Ruff line length 100, Python target 3.12, and mypy strict mode for `app`.
4. Implement `backend/app/main.py` with `create_app()` and `GET /health` returning `{"status":"ok"}`.
5. Add extension dependencies: Vite, TypeScript, `@crxjs/vite-plugin`, Vitest, jsdom, ESLint, Playwright.
6. Configure package scripts: `lint`, `test`, `build`, `test:e2e`.
7. Define MV3 permissions: `storage`; host permissions for `https://www.bilibili.com/*` and the configured API origin. Do not request browsing-history or cookie permissions.
8. Add root README commands for backend, extension, and Docker development.
9. Add `.gitignore` entries for Python, Node, build output, `.env`, temporary media, and Playwright artifacts.

**Verification**

```bash
cd backend
python -m pip install -e '.[dev]'
ruff check .
mypy app
pytest -q

cd ../extension
npm install
npm run lint
npm run test -- --run
npm run build
```

Expected: health-app import succeeds, no test collection errors, and `extension/dist/` contains an MV3 package.

## Task 2: Implement canonical domain and scoring contracts

**Files**

- Create: `backend/app/domain/types.py`
- Create: `backend/app/domain/scoring.py`
- Create: `backend/app/domain/errors.py`
- Create: `backend/tests/unit/test_scoring.py`

**Why**

Give every detector and API response one typed contract and keep score/label logic in one owner.

**Change Necessity**

The approved score, confidence, and label semantics require executable rules; prompt text and API handlers cannot own parallel calculations.

**Impact / Compatibility**

Use the canonical terms from `CONTEXT.md`. Public score is 0–100; detector internals use finite `[0,1]` values.

**Steps**

1. Define enums `DetectorKind(TEXT, VISUAL, METADATA)`, `DeclarationState(DECLARED_AI, NOT_DECLARED, UNKNOWN)`, and label keys.
2. Define immutable dataclasses/Pydantic models:

```python
class DetectorOutput(BaseModel):
    kind: DetectorKind
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    material_factor: float = Field(ge=0.0, le=1.0)
    evidence: tuple[EvidenceItem, ...] = ()

class ScoreResult(BaseModel):
    score: int
    confidence: float
    label: LabelKey | None
    evidence_status: Literal["sufficient", "insufficient"]
```

3. Reject NaN and infinite values with a typed `InvalidDetectorOutput` before aggregation.
4. Implement base weights `{TEXT: 0.5, VISUAL: 0.4, METADATA: 0.1}`.
5. Implement score as normalized weighted evidence and confidence as unnormalized weighted effective confidence (`confidence × material_factor`).
6. Round score to nearest integer and API confidence to two decimals; keep four-decimal internal arithmetic.
7. Implement labels exactly: 0–29, 30–59, 60–79, 80–100; confidence below 0.4 produces no degree label and `insufficient`.
8. Add table-driven tests for all thresholds, missing detectors, all-perfect 1.0, text+visual 0.9, text-only 0.5, material factors, NaN, infinity, and out-of-range values.

**Verification**

```bash
cd backend
pytest -q tests/unit/test_scoring.py
ruff check app/domain tests/unit/test_scoring.py
mypy app/domain
```

Expected: all threshold and confidence fixtures pass with deterministic outputs.

## Task 3: Create PostgreSQL schema and Alembic migration

**Files**

- Create: `backend/app/db/session.py`
- Create: `backend/app/db/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0001_initial.py`
- Create: `backend/tests/integration/test_schema.py`

**Why**

Encode persistent ownership, fencing, independent result/declaration lifecycles, durable attempts, reliable outbox, metadata, and token hashes.

**Change Necessity**

Redis-only coordination cannot satisfy crash recovery. PostgreSQL constraints are required by the approved architecture.

**Impact / Compatibility**

PostgreSQL 16 is the supported persistent store. The migration is the initial schema and contains no destructive data operation.

**Steps**

1. Configure SQLAlchemy async engine/session from `DATABASE_URL`.
2. Define `analysis_target` with composite primary key `(bvid, cid)`, `desired_analysis_version`, `write_generation`, and nullable `owner_attempt_id`.
3. Define `analysis_result` with composite primary key `(bvid, cid)`, score fields, JSONB evidence, `analysis_version`, `analyzed_at`, and `analysis_expires_at`. The public `rule_version` field is the presentation name of this canonical `analysis_version`; do not persist a duplicate version owner.
4. Define `video_declaration` with composite primary key `(bvid, cid)`, state/source/evidence, `checked_at`, and `expires_at`.
5. Define `analysis_attempt` with UUID `attempt_id`, target/version, generation, status, `dispatch_epoch`, heartbeat/lease/retry fields, and typed error.
6. Add a partial unique index that permits one active attempt for `(bvid, cid, analysis_version)` where status is queued/fetching/analyzing.
7. Define `analysis_outbox` with UUID event ID, attempt ID, generation, dispatch epoch, created/delivered timestamps, and uniqueness on `(attempt_id, generation, dispatch_epoch)`.
8. Define `video_metadata` with `bvid` primary key, `default_cid`, and `checked_at`.
9. Define `installation_token` with token hash uniqueness, creation/last-use/revocation timestamps.
10. Add check constraints for score 0–100, confidence 0–1, positive generations, and known statuses.
11. Generate and review `0001_initial.py`; keep downgrade limited to dropping the newly-created tables and indexes.
12. Add integration tests that migrate an empty PostgreSQL database to head and inspect required constraints/indexes.

**Verification**

```bash
cd backend
alembic upgrade head
pytest -q tests/integration/test_schema.py
alembic downgrade base
alembic upgrade head
```

Expected: clean upgrade/downgrade/upgrade cycle and all required constraints present.

## Task 4: Implement durable repository state machine and recovery

**Files**

- Create: `backend/app/db/repository.py`
- Create: `backend/app/services/outbox.py`
- Create: `backend/app/services/reconciliation.py`
- Create: `backend/tests/integration/test_attempt_state_machine.py`
- Create: `backend/tests/integration/test_recovery.py`

**Why**

Prevent duplicate work, preserve the last successful result, recover Redis loss, and reject late workers.

**Change Necessity**

Generic ORM updates cannot safely express version/generation ownership. One repository must own transitions and conditional writes.

**Impact / Compatibility**

All worker and API state changes must call this repository. No direct model updates outside migrations/tests.

**Steps**

1. Implement repository methods with explicit transactions:

```python
async def create_or_reuse_attempt(target: TargetKey, version: str, now: datetime) -> CreateDecision: ...
async def claim_attempt(
    attempt_id: UUID,
    generation: int,
    dispatch_epoch: int,
    lease_seconds: int,
) -> ClaimedAttempt | None: ...
async def heartbeat(attempt_id: UUID, generation: int, lease_seconds: int) -> bool: ...
async def complete_attempt(claim: ClaimedAttempt, result: AnalysisResultWrite) -> bool: ...
async def fail_attempt(claim: ClaimedAttempt, error_code: str, retry_after: datetime) -> None: ...
async def save_declaration(target: TargetKey, declaration: DeclarationWrite) -> None: ...
```

2. In `create_or_reuse_attempt`, lock `analysis_target`; return the active same-version attempt when present; return the latest failed attempt while `retry_after > now`; otherwise increment `write_generation`, set desired version/owner, create attempt, and create outbox event in one transaction.
3. In `claim_attempt`, use one conditional update requiring queued status, matching target owner, matching target and attempt generation, matching `dispatch_epoch`, and no live lease. A delayed or duplicate old Redis message returns `None`.
4. In `complete_attempt`, perform one conditional write requiring matching target owner, desired version, generation, and unexpired lease; return `False` for stale writers.
5. Preserve `analysis_result` when replacement attempts fail.
6. Implement outbox dispatch with Redis idempotency key `(attempt_id, generation, dispatch_epoch)`.
7. Implement reconciliation scans:
   - queued attempt past dispatch timeout with no lease → increment dispatch epoch and enqueue a new outbox event;
   - fetching/analyzing attempt with expired lease → increment target/attempt generation and requeue;
   - completed/failed attempt → never requeue.
8. Add concurrency tests for 20 simultaneous creates yielding one active attempt.
9. Add cooldown tests proving calls before `retry_after` reuse the failed state, create no attempt, and consume no creation quota.
10. Add old-message tests proving stale generation or dispatch epoch cannot claim a requeued attempt.
11. Add ordered fencing test: `v1 claim → v2 claim → v2 complete → v1 complete`; assert result remains v2.
12. Add recovery tests for undelivered outbox, delivered-then-Redis-flushed, dispatcher restart, Redis restart, worker crash, PostgreSQL disconnect during completion, and lease expiry.

**Verification**

```bash
cd backend
pytest -q tests/integration/test_attempt_state_machine.py tests/integration/test_recovery.py
ruff check app/db app/services tests/integration
mypy app/db app/services
```

Expected: one active attempt, recoverable queue intent, stale-write rejection, and preserved last success.

## Task 5: Implement installation registration, authentication, and quotas

**Files**

- Modify: `backend/app/config.py`
- Create: `backend/app/services/tokens.py`
- Create: `backend/app/services/rate_limits.py`
- Create: `backend/app/api/deps.py`
- Create: `backend/app/api/installations.py`
- Create: `backend/tests/api/test_installations.py`
- Create: `backend/tests/unit/test_rate_limits.py`
- Create: `backend/tests/api/test_cors.py`

**Why**

Allow anonymous use while preventing unlimited token regeneration and analysis abuse.

**Change Necessity**

A public service needs a server-issued credential and separate cheap-query/expensive-analysis budgets.

**Impact / Compatibility**

No user account or Bilibili identity is introduced. Raw tokens are returned once and stored only by the extension.

**Steps**

1. Add settings for token byte length, registration IP limits, query limits, analysis hourly/daily limits, token idle-retention days, and an exact `ALLOWED_EXTENSION_ORIGINS` list.
2. Implement `issue_token()` with `secrets.token_urlsafe(32)` and SHA-256 hash storage.
3. Implement `POST /api/v1/installations` returning `{token, created_at}`.
4. Apply strict Redis IP counters to registration before issuing a token.
5. Implement Bearer-token dependency that hashes the presented token, loads the active record, and updates `last_seen_at` with bounded write frequency.
6. Implement Redis fixed-window counters for cached queries, hourly analysis creation, and daily analysis creation.
7. Ensure reuse of a completed or active resource bypasses new-analysis quota consumption.
8. Implement token rotation as create-new-and-revoke-old under authenticated `POST /api/v1/installations/rotate`.
9. Configure FastAPI CORS from the exact extension-origin allowlist; accept approved `chrome-extension://<id>` origins and reject ordinary web origins and unlisted extension IDs.
10. Add tests for raw-token non-persistence, invalid/revoked tokens, IP registration limits, hourly/daily quotas, rotation, repeated registration abuse, CORS preflight, approved origin, and rejected origin.

**Verification**

```bash
cd backend
pytest -q tests/api/test_installations.py tests/api/test_cors.py tests/unit/test_rate_limits.py
```

Expected: the API issues one opaque token, stores only its hash, and enforces all budgets deterministically.

## Task 6: Implement analysis query, creation, and batch API

**Files**

- Create: `backend/app/api/schemas.py`
- Create: `backend/app/api/analyses.py`
- Create: `backend/app/services/freshness.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_freshness.py`
- Create: `backend/tests/api/test_analyses.py`
- Create: `backend/tests/api/test_batch_lookup.py`

**Why**

Expose the approved `/api/v1` resource contract to the extension without leaking persistence internals.

**Change Necessity**

The extension needs stable typed endpoints for result/attempt state, idempotent creation, and homepage batch lookup.

**Impact / Compatibility**

Keep response fields versioned under `/api/v1`. Return result and attempt lifecycles independently.

**Steps**

1. Define strict BV validation and positive CID validation.
2. Define response fields:

```json
{
  "bvid": "BV...",
  "cid": 123,
  "result_status": "missing|current|stale",
  "attempt_status": "none|queued|fetching|analyzing|failed",
  "declaration": {"state":"declared_ai|not_declared|unknown","stale":false},
  "result": {"score":72,"label":"medium","confidence":0.84,"stale":false},
  "evidence": [],
  "analyzed_at": "2026-07-20T12:00:00Z",
  "rule_version": "...",
  "retry_after": null
}
```

3. Implement one freshness owner with defaults: declaration 30 days, deep result 14 days, failed-attempt cooldown 10 minutes, and metadata/default-CID TTL 24 hours. It alone classifies `current`, `stale`, and cooldown boundaries.
4. Implement `GET /api/v1/analyses/{bvid}?cid=` by composing target, last result, declaration, and current attempt through the freshness owner. Preserve a previous declaration when refresh fails and mark it stale.
5. Implement `POST /api/v1/analyses`: read first; return valid result, active attempt, or failed attempt still inside `retry_after`; only a true creation path consumes new-analysis quota and calls `create_or_reuse_attempt`.
6. Implement `POST /api/v1/analyses/batch` with 30 unique BV limit and one SQL query joining `video_metadata.default_cid` to current completed results. Return no badge when metadata/default-CID mapping is stale.
7. Ensure batch endpoint never invokes repository creation or metadata-refresh methods.
8. Add typed error codes for invalid input, unavailable/private video, risk control, quota, and temporary upstream failure.
9. Register routers and OpenAPI metadata in `create_app()`.
10. Add OpenAPI contract tests for snake_case fields, `analyzed_at`, and public `rule_version` mapped from canonical `analysis_version`.
11. Add freshness boundary tests at exact expiry instants, declaration-refresh failure tests, cooldown quota-order tests, all state combinations, stale result plus active attempt, declaration-only response, idempotent POST, batch limit, stale-default-CID omission, and batch no-create guarantee.

**Verification**

```bash
cd backend
pytest -q tests/unit/test_freshness.py tests/api/test_analyses.py tests/api/test_batch_lookup.py
python -c 'from app.main import create_app; print(create_app().openapi()["info"]["title"])'
```

Expected: API state composition matches the design and batch reads create no work.

## Task 7: Implement Bilibili metadata, subtitle, audio, and frame acquisition

**Files**

- Create: `backend/app/integrations/bilibili/client.py`
- Create: `backend/app/integrations/bilibili/metadata.py`
- Create: `backend/app/integrations/bilibili/media.py`
- Create: `backend/app/integrations/bilibili/bcut.py`
- Create: `backend/tests/integrations/test_bilibili_metadata.py`
- Create: `backend/tests/integrations/test_media_acquisition.py`
- Create: `backend/tests/integrations/test_bcut.py`

**Why**

Acquire the minimum materials required by the approved evidence pipeline while keeping media temporary.

**Change Necessity**

Metadata and media cannot be derived by the extension or database. One backend integration boundary is required.

**Impact / Compatibility**

Follow the reference repository's shared HTTP client, subtitle-first, low-bitrate audio, cancellation, and cleanup patterns. Use a service-owned cookie jar only when configured.

**Steps**

1. Implement a shared `httpx.AsyncClient` with Bilibili user-agent/referer, timeouts, bounded retries, and typed risk-control errors.
2. Implement metadata loading for title, description, tags, parts, current/default CID, duration, and available declaration text.
3. Persist canonical `default_cid` only through the metadata owner and refresh it whenever detail-page analysis fetches metadata.
4. Treat mappings older than the configured 24-hour metadata TTL as stale; homepage batch lookup omits them until a later detail analysis refreshes the metadata.
5. Wrap `yt-dlp` subtitle extraction with preferred languages and automatic-subtitle support; parse segments into typed transcript objects.
6. Implement low-bitrate audio acquisition and sample extraction for beginning/middle/end windows.
7. Implement ffmpeg frame sampling for 6–12 approximately 360p frames without retaining a full output video.
8. Port the BCut upload/task/poll flow behind one `transcribe_samples()` function with cancellation and timeout.
9. Place every task's temporary files under a unique directory and expose one cleanup context manager that deletes the directory on every exit.
10. Add fixtures for metadata, multi-part order changes, metadata TTL expiry, subtitle hit, no subtitle, no speech, ffmpeg failure, BCut timeout, cancellation, and cleanup.

**Verification**

```bash
cd backend
pytest -q tests/integrations/test_bilibili_metadata.py tests/integrations/test_media_acquisition.py tests/integrations/test_bcut.py
```

Expected: default CID is deterministic, subtitle-first works, sampled fallback works, and no fixture leaves temporary files.

## Task 8: Implement evidence detectors and worker pipeline

**Files**

- Create: `backend/app/detectors/prompts.py`
- Create: `backend/app/detectors/openai_compatible.py`
- Create: `backend/app/workers/pipeline.py`
- Create: `backend/tests/unit/test_detector_contract.py`
- Create: `backend/tests/workers/test_pipeline.py`

**Why**

Turn acquired materials into structured evidence and one canonical score.

**Change Necessity**

The approved product needs text/visual evidence; a single configurable OpenAI-compatible client avoids vendor-specific parallel implementations.

**Impact / Compatibility**

The model returns detector evidence only. It cannot set final labels or bypass the score aggregator.

**Steps**

1. Add settings `AI_API_BASE`, `AI_API_KEY`, `AI_MODEL`, request timeout, and maximum evidence items.
2. Implement one client that submits text material and sampled frames and requires JSON output matching the `DetectorOutput` contract.
3. Use separate prompt functions for text and visual evidence; both demand concrete evidence, timestamps/frame indices, and a distinction between AI-topic discussion and AI production method.
4. Reject malformed, non-finite, or out-of-range model output with typed detector errors; do not clamp values or synthesize success.
5. Implement metadata detector as deterministic local rules over declaration, title, description, and tags.
6. Implement material factors exactly from the design: subtitle 1.0, sampled ASR 0.7, title/description only 0.3; visual 6+ frames 1.0, 3–5 frames 0.6, fewer than 3 unavailable; full/partial metadata 1.0/0.5.
7. Implement `run_analysis(claim)` to refresh declaration, acquire materials, execute independent detectors, aggregate score, and call conditional repository completion.
8. Always execute temporary-directory cleanup and record detector-specific failures in evidence metadata.
9. Add tests for explicit declaration plus deep failure, topic-only text, partial detector failure, confidence below 0.4, stale-write rejection, timeout, and cleanup.

**Verification**

```bash
cd backend
pytest -q tests/unit/test_detector_contract.py tests/workers/test_pipeline.py
ruff check app/detectors app/workers
mypy app/detectors app/workers
```

Expected: structured evidence produces deterministic score/label results and malformed model output fails visibly.

## Task 9: Implement worker runner and recovery loops

**Files**

- Create: `backend/app/workers/runner.py`
- Modify: `backend/app/services/outbox.py`
- Modify: `backend/app/services/reconciliation.py`
- Create: `backend/tests/workers/test_runner.py`
- Create: `backend/tests/integration/test_runtime_recovery.py`

**Why**

Connect durable PostgreSQL intent to Redis delivery and worker execution while preserving PostgreSQL authority.

**Change Necessity**

Repository methods alone do not run dispatch, lease renewal, reconciliation, or analysis jobs.

**Impact / Compatibility**

Use one worker protocol. Do not add a second retry system or queue-owned lifecycle.

**Steps**

1. Implement an outbox dispatcher loop using `FOR UPDATE SKIP LOCKED`; publish `(attempt_id, generation, dispatch_epoch)` and mark the event delivered.
2. Implement a Redis consumer that passes the full `(attempt_id, generation, dispatch_epoch)` message to the atomic claim method; discard stale, duplicate, or mismatched messages before starting analysis.
3. Start a heartbeat coroutine during analysis and stop it before the terminal transition.
4. Run reconciliation for queued attempts past dispatch timeout and running attempts with expired leases.
5. Make all loops cancellation-safe and close HTTP, Redis, and database resources during shutdown.
6. Expose last-dispatch, last-reconciliation, active-job, and queue-depth health fields.
7. Test graceful shutdown, duplicate delivery, Redis flush after delivered outbox, PostgreSQL reconnect, worker crash, and lease reclaim.

**Verification**

```bash
cd backend
pytest -q tests/workers/test_runner.py tests/integration/test_runtime_recovery.py
```

Expected: every queued PostgreSQL attempt eventually runs or reaches a typed terminal failure after simulated transient loss.

## Task 10: Implement extension token, API, routing, and identifier owners

**Files**

- Create: `extension/src/background/token-store.ts`
- Create: `extension/src/background/api-client.ts`
- Create: `extension/src/background/service-worker.ts`
- Create: `extension/src/content/bilibili-id.ts`
- Create: `extension/src/content/route-observer.ts`
- Create: `extension/src/content/entry.ts`
- Create: `extension/tests/token-store.test.ts`
- Create: `extension/tests/bilibili-id.test.ts`
- Create: `extension/tests/route-observer.test.ts`
- Create: `extension/tests/api-client.test.ts`

**Why**

Create one browser-side owner for identity, API calls, SPA navigation, and BV/CID extraction before page UI code.

**Change Necessity**

Content scripts need a secure way to call the API and react to Bilibili SPA route changes.

**Impact / Compatibility**

Store the installation token in `chrome.storage.local`. Never request Bilibili cookies or browsing history.

**Steps**

1. Implement token bootstrap: load local token; when absent call `POST /api/v1/installations`; persist the returned token.
2. Implement typed API methods `getAnalysis`, `createAnalysis`, and `batchLookup` in the background worker.
3. Add one in-flight Promise map keyed by HTTP method plus canonical target/batch key so concurrent content-script requests share a request; remove entries on success, failure, and cancellation.
4. Route content-script requests through `chrome.runtime.sendMessage`; do not expose the token to page JavaScript.
5. Parse BV from canonical video links and CID from page state/API response with strict numeric validation.
6. Implement a route observer using History API hooks plus a bounded MutationObserver fallback; emit only when `(bvid,cid)` changes.
7. Add unit tests for first registration, token reuse, revoked-token recovery, API errors, same-target request deduplication, distinct-target isolation, rejected-request cleanup, BV variants, invalid CID, and route deduplication.

**Verification**

```bash
cd extension
npm run test -- --run tests/token-store.test.ts tests/api-client.test.ts tests/bilibili-id.test.ts tests/route-observer.test.ts
npm run build
```

Expected: the built service worker owns the token and route events are deduplicated.

## Task 11: Implement video-detail automatic analysis and UI

**Files**

- Create: `extension/src/content/video-page.ts`
- Create: `extension/src/ui/badge.ts`
- Create: `extension/src/ui/detail-panel.ts`
- Create: `extension/src/ui/styles.css`
- Create: `extension/tests/video-page.test.ts`
- Create: `extension/tests/detail-panel.test.ts`
- Create: `extension/tests/e2e/video-page.spec.ts`

**Why**

Deliver the primary flow: immediate shared-result display and automatic analysis for an unseen visible video.

**Change Necessity**

The approved product requires a title-adjacent label and state/evidence detail on Bilibili's SPA page.

**Impact / Compatibility**

DOM selectors stay in the page adapter. UI rendering consumes API fields and never recomputes authoritative labels.

**Steps**

1. Wait for a visible document and a stable `(bvid,cid)` for two seconds.
2. Query the shared resource; render declaration, result label, confidence, stale state, `analyzed_at`, and public `rule_version` when present.
3. For a missing or expired resource, call create-or-reuse once and start bounded polling.
4. Poll at 2, 4, 8, and then 15-second intervals with jitter; stop on completion, terminal failure, hidden tab, or route change.
5. Render the approved Chinese labels and independent `已声明 AI` state beside the title.
6. Render `证据不足` when confidence is below 0.4 and keep evidence source availability visible.
7. Make injection idempotent and restore the panel when Bilibili replaces the title DOM.
8. Add DOM fixture tests for current, stale, queued, analyzing, failed, declaration-only, analysis-time/rule-version display, and route-change states.
9. Add Playwright coverage using a local Bilibili-shaped fixture page and mocked API responses.

**Verification**

```bash
cd extension
npm run test -- --run tests/video-page.test.ts tests/detail-panel.test.ts
npm run test:e2e -- tests/e2e/video-page.spec.ts
```

Expected: one detail badge/panel follows SPA navigation and polling stops at every defined boundary.

## Task 12: Implement homepage and recommendation-card batch badges

**Files**

- Create: `extension/src/content/recommendation-feed.ts`
- Create: `extension/tests/recommendation-feed.test.ts`
- Create: `extension/tests/e2e/recommendation-feed.spec.ts`

**Why**

Show existing shared labels on visible recommendation cards without creating analysis work.

**Change Necessity**

Feed pages have dynamic cards and require visibility tracking, batching, and DOM lifecycle handling separate from detail pages.

**Impact / Compatibility**

The adapter calls only the batch lookup endpoint. Unanalysed cards remain unchanged.

**Steps**

1. Observe visible recommendation cards with `IntersectionObserver`.
2. Extract and deduplicate BV identifiers from card links.
3. Debounce discoveries for 400 ms and split requests into batches of at most 30.
4. Render a compact badge only for returned canonical-default-CID results.
5. Cache batch responses in memory for the current page session and invalidate when a card's BV changes.
6. Re-scan added cards through a bounded MutationObserver and prevent duplicate badges.
7. Add tests proving invisible cards are skipped, 31 identifiers create two batches, duplicate BV values collapse, absent results create no badge, and no create-analysis message is emitted.
8. Add Playwright coverage for infinite-scroll card replacement.

**Verification**

```bash
cd extension
npm run test -- --run tests/recommendation-feed.test.ts
npm run test:e2e -- tests/e2e/recommendation-feed.spec.ts
```

Expected: visible cards receive cached badges through read-only batches and never trigger analysis creation.

## Task 13: Add container deployment, health, cleanup, and performance tooling

**Files**

- Create: `deploy/backend.Dockerfile`
- Create: `deploy/extension.Dockerfile`
- Create: `deploy/docker-compose.yml`
- Create: `deploy/Caddyfile`
- Create: `deploy/.env.example`
- Create: `scripts/seed_performance_data.py`
- Create: `scripts/perf_cached_queries.py`
- Create: `backend/tests/smoke/test_compose_contract.py`

**Why**

Make the public beta reproducible on the approved 4-vCPU / 8-GB host and provide measurable service boundaries.

**Change Necessity**

Local modules alone do not define process commands, durable volumes, health checks, TLS routing, or the acceptance benchmark.

**Impact / Compatibility**

Persist only PostgreSQL data. Redis and task media directories remain rebuildable/ephemeral.

**Steps**

1. Build one backend image and run it with separate API, dispatcher/reconciler, and worker commands.
2. Define PostgreSQL 16 and Redis 7 services with health checks; give only PostgreSQL a durable data volume.
3. Mount a bounded temporary-media volume or tmpfs for workers and configure per-task size/time limits.
4. Configure Caddy to expose `/api/` over HTTPS and forward health requests; the performance test must traverse this TLS reverse-proxy boundary.
5. Document all required variables in `.env.example`; include no secrets or default production credentials.
6. Add structured JSON logging fields: request ID, target, attempt ID, generation, stage, duration, error code.
7. Add `/health` liveness and `/ready` readiness checks covering database and Redis reachability while preserving PostgreSQL authority.
8. Implement `scripts/seed_performance_data.py` to deterministically load exactly 100,000 current result rows plus matching default-CID metadata and print/assert the final row counts.
9. Implement `scripts/perf_cached_queries.py` with environment preflight for 4 vCPU / 8 GB RAM, HTTPS URL enforcement, database row-count verification, 20 closed-loop connections, 30-second warm-up, five-minute measurement, at least 1,000 successes, separate single/batch runs, and P50/P95/P99/throughput/error JSON output under `artifacts/performance/`.
10. Add a static compose-contract test for service commands, health checks, volume ownership, TLS benchmark routing, and secret-free defaults.

**Verification**

```bash
docker compose -f deploy/docker-compose.yml config
cd backend && pytest -q tests/smoke/test_compose_contract.py
cd ..
docker compose -f deploy/docker-compose.yml up -d --build
curl --fail --cacert "$PERF_CA_CERT" https://localhost/health
python scripts/seed_performance_data.py --database-url "$DATABASE_URL" --rows 100000
python scripts/perf_cached_queries.py --base-url https://localhost --ca-cert "$PERF_CA_CERT" --database-url "$DATABASE_URL" --expected-rows 100000 --token "$TEST_INSTALLATION_TOKEN"
```

Expected: compose is healthy, cached single/batch P95 is below 500 ms, and each run has under 1% errors.

## Task 14: Complete end-to-end verification and durable documentation

**Files**

- Modify: `README.md`
- Create: `backend/tests/e2e/test_shared_analysis.py`
- Create: `backend/tests/e2e/test_media_cleanup.py`
- Create: `backend/tests/e2e/test_fencing_recovery.py`
- Create: `docs/aegis/adr/2026-07-20-shared-analysis-ownership.md`
- Modify: `docs/aegis/INDEX.md`

**Why**

Prove the system-level invariants and record the durable architecture decision after implementation matches the approved design.

**Change Necessity**

Unit/module checks cannot prove shared execution, cleanup, process recovery, or cross-client behavior.

**Impact / Compatibility**

The ADR records existing approved ownership; it does not introduce a second design source. `CONTEXT.md` remains the domain-language authority.

**Steps**

1. Add an E2E scenario where two installation tokens request one uncached `(bvid,cid,version)` and assert one attempt plus one completed shared result.
2. Add a result-reuse scenario proving a later client causes no media acquisition or model request.
3. Add cleanup scenarios for success, detector failure, timeout, cancellation, and worker termination.
4. Add the exact fencing sequence `v1 claim → v2 claim → v2 complete → v1 complete` and assert v2 remains authoritative.
5. Add Redis-flush and PostgreSQL-restart recovery scenarios using Docker Compose process controls.
6. Add a browser E2E flow that loads the fixture detail page, observes queued→analyzing→completed UI, then loads a feed fixture and sees the cached badge.
7. Update README with setup, configuration, privacy/data retention, API usage, extension sideloading, operations, backup, and troubleshooting.
8. Record the ADR for PostgreSQL authority, target-level fencing, independent declaration/result records, Redis rebuildability, and rejected alternatives.
9. Append the ADR to the Aegis index and run the workspace checker.

**Verification**

```bash
cd backend
ruff check .
mypy app
pytest -q

cd ../extension
npm run lint
npm run test -- --run
npm run build
npm run test:e2e

cd ..
docker compose -f deploy/docker-compose.yml config
python /home/muelsyse/.pi/agent/git/github.com/GanyuanRan/Aegis/scripts/aegis-workspace.py check --root .
```

Expected: all checks pass; raw media is absent; one target/version has one active attempt; stale workers cannot overwrite newer results.

## Task Batches and Review Gates

1. **Foundation gate — Tasks 1–4**: review score semantics, schema constraints, target fencing, and recovery before exposing APIs.
2. **Backend behavior gate — Tasks 5–9**: review authentication, quotas, public contracts, acquisition cleanup, and worker recovery.
3. **Extension gate — Tasks 10–12**: review requested permissions, SPA behavior, batch-only homepage flow, and UI wording.
4. **Release gate — Tasks 13–14**: run full verification, smoke, recovery, cleanup, browser E2E, and performance protocol.

Tasks 1–4 are sequential. Tasks 5 and 7 can proceed after Task 4; Tasks 6, 8, and 9 follow their named dependencies. Extension Task 10 can begin after Task 6 freezes API schemas. Tasks 11 and 12 can run in parallel after Task 10. Deployment follows stable process commands from Tasks 6–9.

## Risks

- Bilibili API or DOM changes: isolate selectors/endpoints and fail with typed diagnostics.
- Bilibili risk control: bound retries, preserve last result, and expose retry timing.
- BCut availability: mark text unavailable and reduce confidence; do not fabricate transcription.
- External multimodal model variability: enforce structured schemas and deterministic local aggregation.
- Public abuse/cost: server-issued tokens, separate quotas, global result reuse, and bounded sampling.
- Multi-process race conditions: database locks, target ownership, generation fencing, leases, and reconciliation tests.

## Retirement and Rollback

- No legacy runtime path exists.
- Remove any execution-time in-memory repository, SQLite fallback, mock-success detector, or Redis-only state path before completion.
- Keep the last successful database result during replacement failures.
- Roll back deployment by stopping API/worker processes and restoring the previous image; retain PostgreSQL data and apply Alembic downgrade only after explicit destructive-operation approval.
- Temporary media directories expire through task cleanup and host-level age/size safeguards; they never become a backup source.

## Plan Self-Review

- Spec coverage: every design acceptance area maps to Tasks 2–14.
- Placeholder scan: the plan contains no deferred implementation markers.
- Type consistency: detector, score, result, attempt, declaration, and API contracts have one owner each.
- Compatibility: MV3, `/api/v1`, PostgreSQL authority, Redis rebuildability, and default CID are explicit.
- Change necessity: every source task states the required runtime boundary.
- Existence check: all new surfaces map to approved architecture owners.
- Complexity: repository, acquisition, detector, worker, and DOM adapters remain separate.
- Verification: every task includes exact focused commands and the final gate runs the full stack.
- ADR/baseline signal: final documentation records durable ownership and keeps `CONTEXT.md` authoritative.

