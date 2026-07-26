# Desktop AI Video Identification MVP Execution - Evidence

## EvidenceBundleDraft

- Artifact key: task1-backend-gates
- Type: command
- Source: backend: uv lock --check; ruff check .; mypy app; pytest -q
- Summary: Python 3.12 locked environment passed Ruff, strict mypy, import smoke, and 3 tests.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task1-extension-gates
- Type: command
- Source: extension: npm ci --dry-run; npm run lint; npm run test -- --run; npm run build; manifest assertion
- Summary: Locked Node dependencies passed lint, 4 tests, build, and exact MV3 permission/host checks.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task1-reviews
- Type: review
- Source: independent spec and quality reviewer outputs
- Summary: Task 1 spec review and final quality review approved after dependency-lock fixes.
- Verifier: independent subagents

## EvidenceBundleDraft

- Artifact key: task2-scoring-gates
- Type: command
- Source: backend: ruff, mypy, pytest; task2 scoring suite
- Summary: Canonical scoring contracts passed 56 focused tests and 59 full backend tests with Ruff/mypy.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task2-reviews
- Type: review
- Source: independent Task 2 spec and multi-round quality reviews
- Summary: Spec approved; quality approved after strict validation and bounded diagnostic hardening.
- Verifier: independent subagents

## EvidenceBundleDraft

- Artifact key: task3-schema-gates
- Type: command
- Source: PostgreSQL 16.14 container: schema integration tests, Alembic cycle/check; backend regression gates
- Summary: PostgreSQL 16.14 passed 5 schema integration tests, Alembic upgrade/downgrade/upgrade, and zero-drift alembic check; full backend passed 65 tests with Ruff and strict mypy.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task3-review
- Type: review
- Source: main-agent line-by-line schema/spec review; independent reviewer attempt blocked by worktree path isolation
- Summary: ORM and migration match the approved seven-table schema, fencing owner, partial active-attempt uniqueness, outbox idempotency, JSONB and check constraints. PostgreSQL execution covers cyclic FK creation and downgrade order.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task4-state-machine-gates
- Type: command
- Source: PostgreSQL 16.14 and Redis 7 integration suite; backend full gates
- Summary: Repository, outbox, and reconciliation passed 13 focused integration tests and 78 full backend tests; Ruff, strict mypy, and Alembic zero-drift check passed.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task4-fault-injection
- Type: command
- Source: Docker Redis restart and PostgreSQL completion-transaction disconnect fault injection
- Summary: Redis restart erased the stream and reconciliation republished generation 1 at dispatch epoch 1. PostgreSQL shutdown during a blocked completion raised DBAPIError; after restart the attempt remained fetching and analysis_result remained empty, proving atomic rollback.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task5-auth-quota-gates
- Type: command
- Source: PostgreSQL 16.14 and Redis 7 API/unit suite; backend full gates
- Summary: Installation registration, SHA-256-only persistence, authentication, bounded last-used writes, idle rejection, atomic rotation, registration/query/analysis fixed-window limits, and exact extension-origin CORS passed 13 focused tests and 89 full backend tests; Ruff, strict mypy, and Alembic zero-drift check passed.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task13-deployment-performance-gates
- Type: command
- Source: Docker image builds; Compose migration/health/TLS smoke; 100k-row fixed performance protocol
- Summary: Backend and extension images built from bounded contexts; isolated Compose stack migrated and stayed healthy; cached single P95 199.98 ms and batch-30 P95 229.14 ms with 0 errors across 50,447 and 40,379 successes. Per-workspace byte, media-command timeout, and whole-job timeout gates passed.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task14-e2e-recovery-gates
- Type: command
- Source: Backend shared-result/cleanup/fencing E2E; Docker test-service restart recovery; extension production build and Playwright
- Summary: Two installations observed one completed shared result; reuse created no active work; timeout and worker cancellation removed media; PostgreSQL/Redis restart recovery passed 10 tests; stale fencing held; browser observed queued, analyzing, completed and feed read-only states.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task7-media-gates
- Type: command
- Source: Metadata/material-loader/media integration and cleanup tests
- Summary: Claimed cid maps to the current Bilibili part page; declaration persists before deep acquisition; subtitle/audio/frame URLs target that page; command timeout, live workspace size monitoring, process-group termination, and cleanup failure are covered.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task6-api-gates
- Type: command
- Source: PostgreSQL/Redis API suites and OpenAPI import
- Summary: Typed GET/POST/batch analysis routes passed idempotent creation, quota-under-lock, version replacement, stale filtering, public error_code, and read-only batch contracts; final backend suite reached 139 passed.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task9-runtime-gates
- Type: command
- Source: Worker runner, repository, recovery, and container restart tests
- Summary: Workers use hostname-unique consumers, durable typed failure/cooldown plus ACK, cancellation leaves messages for lease recovery, heartbeats/fencing hold, Redis/PostgreSQL restart recovery passed, and stale completions cannot overwrite.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task10-extension-core-gates
- Type: command
- Source: Extension token/API/identifier/route unit tests and real MV3 Chromium
- Summary: 401 clears and re-registers once, runtime messages are typed, native fetch is correctly bound in WorkerGlobalScope, page DOM initial-state parsing maps URL part to cid, token remains in chrome.storage.local, and service worker owns API calls.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task13-final-resource-performance-gates
- Type: command
- Source: 2026-07-26 UTC, base SHA 4c65990 with recorded dirty worktree: docker inspect HostConfig limits; seed_performance_data.py --rows 100000; perf_cached_queries.py --base-url https://localhost:54444 --expected-rows 100000; exit 0
- Summary: Seven steady containers including two workers were limited to 3.75 CPU and 7.0 GiB. With exactly 100,000 result/metadata rows and 20 connections, cached single P95 was 292.33 ms over 36,487 successes and batch-30 P95 was 319.37 ms over 29,232 successes; both had zero failures. Performance artifact SHA-256 a76af7facd960b16fe662bf5c9f94e9fe007ae188e1b2c4470aa9e3c697fcf36; runtime-limit artifact SHA-256 63e06f179a622f99149f34fd1c9dc91dd5cd43024a2ef7b63a4ca9a68d17327c.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task12-feed-gates
- Type: command
- Source: Visibility/card-reuse unit tests and unpacked-extension feed Playwright flow
- Summary: IntersectionObserver gates requests to visible cards, 31 identifiers split at 30, BVs deduplicate, reused cards drop stale badges, absent results remain unchanged, and only batchLookup crosses the runtime channel.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task11-detail-ui-gates
- Type: command
- Source: Detail controller/UI unit tests and unpacked-extension Playwright flow
- Summary: Real MV3 content script and service worker traverse missing, queued, analyzing, and completed states; declaration, label, confidence, analyzed time, and rule version render; polling uses a bounded sequence plus an absolute 900-second deadline.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task8-pipeline-gates
- Type: command
- Source: Detector and pipeline unit/E2E suites
- Summary: Pipeline saves declarations independently, enters fenced analyzing state, degrades detector-specific failures visibly, cleans media before completed transition, aggregates canonical scores, and rejects stale writes.
- Verifier: main agent

## EvidenceBundleDraft

- Artifact key: task14-release-gates
- Type: command
- Source: 2026-07-26 UTC final full gates over base SHA 4c65990 with recorded dirty worktree: backend ruff/mypy/pytest/alembic check; extension lint, unit, production build, MV3 content-script syntax check, Playwright; compose config; aegis workspace check; git diff --check with secret scan; performance artifact sha256sum
- Summary: After the final precision fixes (yt-dlp locked to worstvideo[height<=360]/worst[height<=360] with no higher-resolution fallback, real-tool media smoke driving MediaAcquirer.sample_frames with real ffmpeg-generated local source, detail-page poll rechecking the absolute deadline after each sleep), backend passed Ruff, strict mypy on 38 files, 141 tests, and Alembic zero-drift check; extension passed ESLint, 23 unit tests in 8 files, tsc+Vite production build with node --check on the emitted MV3 content script, and 2 real-MV3 Playwright E2E tests; Compose rendered exactly 7 services; Aegis workspace check passed; git diff --check and the private-key/token secret scan were clean; performance artifact SHA-256 a76af7facd960b16fe662bf5c9f94e9fe007ae188e1b2c4470aa9e3c697fcf36 and runtime-limit artifact SHA-256 63e06f179a622f99149f34fd1c9dc91dd5cd43024a2ef7b63a4ca9a68d17327c remained unchanged, so the recorded performance evidence still matches the released artifacts.
- Verifier: main agent
