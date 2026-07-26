# Desktop AI Video Identification MVP Design

Status: Approved for implementation on 2026-07-20

## 1. Purpose

Build a lightweight Chrome / Edge extension that identifies possible AI-generated content in Bilibili videos, reuses shared analysis results by BV number, and displays explainable labels on video pages and homepage recommendation cards.

The MVP uses a public Python analysis service. The extension stays lightweight; media acquisition, evidence extraction, scoring, caching, and task coordination run on the server.

## 2. Confirmed Product Decisions

- Chrome and Edge share one Chromium Manifest V3 codebase.
- Mobile, Firefox, and Safari are outside the MVP.
- Videos are identified by `bvid`; detail-page precision also includes `cid` for multi-part videos.
- Results are shared across all extension users.
- Homepage and recommendation cards only query existing results.
- Entering a visible video detail page automatically starts analysis when no valid result exists.
- Detection uses declarations, text evidence, metadata, sampled audio transcription, and 6–12 low-resolution frames.
- Scoring weights are text 50%, visual 40%, metadata 10%.
- The 0–100 score expresses AI evidence strength under finite sampling, not the time proportion of AI-generated content.
- Creator/platform AI declarations are an independent fact state.
- Long-term storage contains results and evidence descriptions only. Temporary media files are deleted after each task.
- PostgreSQL stores persistent shared results, durable analysis attempts, and a reliable queue outbox. Redis accelerates delivery, leases, and rate limiting.
- The server issues anonymous installation tokens and stores only token hashes.

## 3. Goals and Success Evidence

### Goals

1. Show an existing AI label beside the title within one second under normal network conditions.
2. Show cached labels on visible homepage recommendation cards through batched lookup.
3. Analyze each `bvid + cid + analysis_version` once and share the result with all users.
4. Explain each result through declaration, text, visual, and metadata evidence.
5. Keep the extension lightweight and avoid browser-side media processing or model execution.
6. Keep public-service resource use bounded through caching, single-flight execution, quotas, timeouts, and media cleanup.

### Success Evidence

- Two users opening the same uncached video create one server analysis task.
- A later user receives the completed result without media acquisition or model calls.
- Homepage scanning sends batched lookups and creates no analysis jobs.
- Missing subtitles trigger sampled-audio fallback without treating missing text as evidence of non-AI content.
- Low-evidence analyses return `证据不足` when confidence is below 0.4.
- Temporary media files are absent after successful, failed, timed-out, and cancelled tasks.

## 4. Non-goals

- Definitive forensic proof that a video is or is not AI-generated.
- Full-video frame-by-frame analysis.
- Automatic crawling or pre-analysis of the Bilibili catalogue.
- Training a proprietary multimodal model in the MVP.
- Retaining complete subtitles, audio, video, or raw frame images.
- User accounts, social features, comments, voting, or manual moderation workflows.
- Mobile clients or native desktop applications.

## 5. Product Flow

### 5.1 Homepage and recommendation feeds

1. Observe visible Bilibili video cards.
2. Extract at most 30 BV identifiers per batch.
3. Debounce card discovery for 300–500 ms.
4. Call one batch lookup endpoint.
5. Add a compact badge only when a completed result exists.
6. Keep unanalysed cards unchanged.
7. Never create analysis tasks from feed pages.

### 5.2 Video detail page

1. Extract the current `bvid` and `cid`.
2. Wait until the page is visible and identifiers remain stable for two seconds.
3. Query the shared analysis resource.
4. Display a completed result beside the title.
5. Display and poll a running result with bounded intervals.
6. Automatically create or reuse a task for a missing, stale, or expired result.
7. Stop local polling when navigation changes the current video part.

## 6. Architecture and Ownership

```text
Chrome / Edge Extension
  ├─ Video Page Adapter
  ├─ Recommendation Card Adapter
  ├─ API Client
  └─ Local UI Preferences
          │ HTTPS
          ▼
FastAPI Service
  ├─ Validation and Anonymous Token Authentication
  ├─ Rate Limiting
  ├─ Analysis Query / Creation API
  └─ Batch Lookup API
          │
          ├──────────────► PostgreSQL
          │                 persistent results, attempts, and queue outbox
          │
          └──────────────► Redis
                            transient delivery, lease, and rate-limit state
                                  │
                                  ▼
                           Analysis Worker
                            ├─ Bilibili metadata/declaration
                            ├─ Subtitle or sampled-audio transcription
                            ├─ Low-resolution frame sampling
                            ├─ Text / visual / metadata detectors
                            └─ Canonical score aggregator
```

- Extension owns DOM discovery, page integration, API calls, and presentation.
- FastAPI owns public contracts, validation, authentication, quotas, and result retrieval.
- Worker owns media acquisition and detector execution.
- Score aggregator owns final score, confidence, and label mapping.
- PostgreSQL is the persistent source of truth for shared results, durable attempts, default-part metadata, and queue recovery.
- Redis contains rebuildable delivery, lease, and rate-limit state only.

## 7. Extension Design

### Video Page Adapter

- Detect SPA navigation and current `bvid + cid`.
- Insert a compact status chip beside the video title.
- Open a detail panel containing score, confidence, declaration state, evidence, analysis time, and rule version.
- Stop polling when the tab becomes hidden or navigation changes the target.

### Recommendation Card Adapter

- Use `IntersectionObserver` to process visible cards.
- Extract BV identifiers from card links.
- Coalesce identifiers into batches of at most 30.
- Add a small badge only for completed shared results.
- Never request analysis from a feed page.

### Background Service Worker

- Own network requests and anonymous token storage.
- Deduplicate simultaneous extension requests.
- Restrict API access to the configured service origin.

## 8. Public API

### Register an installation

```http
POST /api/v1/installations
```

The server issues a high-entropy opaque token once. Registration is protected by strict IP limits and abuse monitoring. The extension stores the raw token locally; PostgreSQL stores only its hash. Token rotation replaces the prior token, and disabled or idle tokens can be revoked without affecting shared video results.

### Query one analysis

```http
GET /api/v1/analyses/{bvid}?cid={cid}
Authorization: Bearer <installation-token>
```

The query returns two independent lifecycles:

- `result_status`: `missing`, `current`, or `stale`
- `attempt_status`: `none`, `queued`, `fetching`, `analyzing`, or `failed`

A stale successful result and an active or failed replacement attempt can be returned together. Declaration freshness and deep-analysis freshness are returned separately.

### Create or reuse an analysis

```http
POST /api/v1/analyses
Authorization: Bearer <installation-token>
Content-Type: application/json

{
  "bvid": "BV...",
  "cid": 123456
}
```

- Return `200` with an existing completed result.
- Return `202` for a queued or active task.
- Use one active attempt for concurrent requests targeting the same `bvid + cid + analysis_version`.
- Return `400` for invalid identifiers, `429` for exhausted quota, and typed errors for unavailable videos.

### Batch lookup

```http
POST /api/v1/analyses/batch
Authorization: Bearer <installation-token>
Content-Type: application/json

{
  "bvids": ["BV1...", "BV2..."]
}
```

- Accept at most 30 unique BV identifiers.
- Return completed shared results only.
- Create no analysis tasks.
- Use the current canonical default CID resolved by the metadata acquisition layer. Return no badge when only a non-default part has a result.

### Input boundary

The public API accepts validated BV identifiers and numeric CIDs. The server constructs Bilibili request URLs itself. Arbitrary caller-supplied fetch URLs are outside the contract.

## 9. Persistent Data Model

### `analysis_target`

Stores the target-level write owner for one `(bvid, cid)`:

- `bvid`, `cid`
- `desired_analysis_version`
- `write_generation`
- `owner_attempt_id`
- `created_at`, `updated_at`

Creating a replacement attempt atomically updates the desired version, increments `write_generation`, and sets `owner_attempt_id`. This record is the canonical fencing owner across different analysis versions.

### `analysis_result`

Stores the last successful deep-analysis result for one `(bvid, cid)` target:

- `bvid`, `cid`
- `score`, `label`, `confidence`
- `evidence_json`
- `analysis_version`, `analyzed_at`, `analysis_expires_at`
- `created_at`, `updated_at`

The canonical uniqueness boundary is `(bvid, cid)`. Reanalysis never destroys the last successful result. While replacement work runs or fails, the API may return the previous result with `stale: true` and its original version.

### `video_declaration`

Stores creator/platform declaration state independently from deep analysis:

- `bvid`, `cid`
- `state`, `source`, `evidence`
- `checked_at`, `expires_at`

The metadata acquisition layer owns declaration refresh. A declaration can succeed while deep analysis fails, and either freshness lifecycle can expire without erasing the other.

### `analysis_attempt`

Stores durable execution state separately from successful results:

- `attempt_id`
- `bvid`, `cid`, `analysis_version`
- `generation` fencing number copied from `analysis_target.write_generation`
- `status`: queued/fetching/analyzing/completed/failed
- `dispatch_epoch`, `heartbeat_at`, `lease_expires_at`, `retry_after`
- `error_code`, `created_at`, `updated_at`

A partial unique constraint permits one active attempt per `(bvid, cid, analysis_version)`. Result completion uses one conditional transaction requiring matching `owner_attempt_id`, `desired_analysis_version`, `write_generation`, and an unexpired lease. A late worker from an older version or generation is rejected.

### `analysis_outbox`

Attempt creation and its outbox event commit in one PostgreSQL transaction. A dispatcher publishes events to Redis. A reconciliation loop scans queued attempts with no valid lease after the dispatch timeout, increments `dispatch_epoch`, and creates a replacement outbox event even when an older event was already marked delivered. Redis consumers are idempotent on `(attempt_id, generation, dispatch_epoch)`. PostgreSQL recovery also scans expired fetching/analyzing leases and requeues them with a higher generation.

### `video_metadata`

The metadata acquisition layer is the single owner of `default_cid`. It resolves the first current public part from Bilibili metadata, stores `default_cid` and `checked_at`, and refreshes the mapping when the platform part order changes. Homepage batch lookup returns a badge only for this canonical default CID.

### `installation_token`

The server registration endpoint issues the raw opaque token once. PostgreSQL stores the token hash, creation time, last use, revocation state, and quota references. Raw tokens, Bilibili identities, and browsing-history lists are excluded.

## 10. Analysis Pipeline

1. Validate `bvid + cid` and read the current `analysis_version`.
2. In one PostgreSQL transaction, create or reuse the active version-specific attempt, advance `analysis_target` ownership when required, and create its outbox event.
3. Dispatch the outbox event to Redis. PostgreSQL reconciliation restores queued intent after dispatcher failure, Redis loss, or delivery-key loss.
4. A worker claims the attempt using the target's current write generation and a renewable lease.
5. Load Bilibili metadata and refresh canonical default CID when required.
6. Refresh and persist `video_declaration`; expose an explicit AI declaration immediately through the independent declaration lifecycle.
7. Fetch platform subtitles when available.
8. When subtitles are unavailable, sample approximately 20–30 seconds from the beginning, middle, and end of low-bitrate audio and transcribe those samples.
9. Extract 6–12 frames from a low-resolution stream, targeting approximately 360p.
10. Run text, visual, and metadata detectors independently.
11. Aggregate available detector outputs into score, confidence, label, and concise evidence.
12. Commit `analysis_result` only when `analysis_target.owner_attempt_id`, desired version, write generation, and attempt lease all match in one conditional transaction.
13. Delete temporary video, audio, subtitle, and frame files in every terminal path.
14. Mark the attempt completed or failed. Reconciliation requeues queued work lost from Redis and expired worker leases with a higher generation.

## 11. Scoring Contract

### AI evidence-strength semantics and weights

The 0–100 score estimates the strength of evidence that the sampled video material contains AI-generated content. It does not estimate the percentage of the video's duration that was generated by AI.

- Text evidence: 50%
- Visual evidence: 40%
- Metadata evidence: 10%

The score normalizes weights over available detector outputs:

```text
score = sum(base_weight × detector_score for available detectors)
        / sum(base_weight for available detectors)
```

Confidence keeps missing-source penalties instead of renormalizing:

```text
confidence = sum(base_weight × detector_confidence for available detectors)
```

Examples: all perfect detectors yield confidence 1.0; text plus visual can yield at most 0.9; text alone can yield at most 0.5.

Detector contract:

- `detector_score` and `detector_confidence` are finite values in `[0,1]`; invalid or non-finite values reject that detector output with a typed error.
- Platform-subtitle text uses material factor 1.0; successful sampled ASR uses 0.7; title/description-only text uses 0.3; absent text or timeout is unavailable.
- Visual evidence uses material factor 1.0 for at least 6 valid frames, 0.6 for 3–5 frames, and is unavailable below 3 frames.
- Metadata uses material factor 1.0 when title, description, tags, and declaration lookup complete; partial metadata uses 0.5; lookup failure is unavailable.
- Effective detector confidence equals detector confidence multiplied by its material factor.
- Internal calculations retain four decimal places. API confidence is rounded to two decimals and score is rounded to the nearest integer.

Missing subtitles reduce text confidence through the material factor and never contribute a zero evidence score.

### Text evidence boundary

Strong evidence describes production method, such as an explicit statement that AI generation, AI voice, Sora, Veo, 可灵, 即梦, or a comparable tool produced the video.

Weak evidence only discusses AI as a topic, such as AI news, model reviews, or artificial-intelligence education. Topic-only references cannot create a high text score.

### Labels

| Score | Label |
| ---: | --- |
| 0–29 | 暂无明显 AI 迹象 |
| 30–59 | 轻度疑似 AI |
| 60–79 | 中度疑似 AI |
| 80–100 | 高度疑似 AI |

When total confidence is below `0.4`, the user-facing state is `证据不足`; the internal score remains available for diagnostics. `已声明 AI` is displayed as an independent source fact.

## 12. Cache and Re-analysis

- `video_declaration.expires_at` is initially 30 days; refresh failure preserves the prior declaration with `stale: true`.
- `analysis_result.analysis_expires_at` is initially 14 days; declaration refresh never forces deep reanalysis, and deep reanalysis never erases declaration state.
- Failed attempts use a 10-minute retry cooldown without overwriting the last successful result.
- A changed `analysis_version` starts one version-specific replacement attempt.
- The previous successful result remains readable with `stale: true` while replacement work runs or fails.
- One active attempt exists per `bvid + cid + analysis_version`.
- Homepage lookup never creates or refreshes work.
- Detail-page access may create or reuse work after the two-second visibility gate.

## 13. Authentication and Rate Limits

On first run, the extension calls the installation registration endpoint. The server issues a high-entropy opaque token and stores only its hash.

Initial limits:

- Token registration: strict IP-based burst and daily limits.
- Cached queries: 60 per minute per token.
- New analysis creation: 5 per hour and 20 per day per token.
- Reusing an active or completed resource consumes no new-analysis quota.
- IP-level limits supplement token limits and prevent repeated registration from resetting quotas.
- Token rotation revokes the previous token. Disabled or long-idle tokens may be deleted without affecting shared results.

## 14. Media, Privacy, and Security

- Long-term persistence contains scores, labels, confidence, declaration state, short evidence descriptions, timestamps, and rule version.
- Raw video, audio, subtitle files, and sampled frames are temporary.
- Cleanup runs for success, failure, cancellation, and timeout.
- User Bilibili cookies are not uploaded by the extension.
- A service-owned Bilibili session, when required, stays isolated on the server.
- Logs avoid raw tokens, complete transcripts, and private cookie values.
- API validation rejects arbitrary URLs and unexpected hosts.
- CORS and extension-origin allowlists reduce accidental browser access; token and rate-limit checks remain the authorization boundary.

## 15. Failure Handling

Stable failure classes:

- Video unavailable, private, deleted, or region restricted.
- Bilibili risk control or authentication failure.
- Subtitle unavailable.
- Audio unavailable or speech absent.
- Frame extraction failure.
- Text or visual detector timeout.
- Media command timeout.
- Per-task workspace byte limit exceeded.
- Evidence insufficient.
- Temporary storage cleanup failure.

A missing evidence source reduces confidence. A detector failure remains visible in evidence metadata and does not silently become a successful zero score. Temporary upstream failures use bounded retries and preserve a typed attempt error. Reanalysis failure leaves the last successful result readable with `stale: true`. Queue publication failure, worker crash, lease expiry, and late completion are recovered through the PostgreSQL attempt/outbox protocol and generation fencing.

## 16. Deployment Profile

MVP deployment uses one Docker Compose stack:

- FastAPI service
- Analysis worker
- PostgreSQL
- Redis
- TLS reverse proxy

Recommended public-beta VPS:

- 4 vCPU
- 8 GB RAM
- 80 GB NVMe
- 20–50 Mbps network
- 2–4 concurrent analysis workers, tuned after measurement

External text/vision APIs and BCut-style ASR avoid a GPU requirement. Server-local multimodal inference remains outside the MVP.

## 17. Acceptance Criteria

### Extension

- Chrome and Edge load the same MV3 package.
- A cached detail-page result renders beside the title.
- SPA navigation changes the current target without duplicate labels or stale polling.
- Visible homepage cards are queried in batches of at most 30.
- Homepage code never invokes the task-creation endpoint.
- Hidden or background detail tabs do not create tasks before becoming visible.

### API and persistence

- Invalid BV/CID input is rejected before upstream access.
- Concurrent task creation for one `(bvid, cid, analysis_version)` produces one active attempt.
- Attempt creation and queue intent commit in one PostgreSQL transaction.
- Undelivered outbox events are republished after dispatcher restart.
- A queued attempt whose event was marked delivered is republished after Redis restart or key loss when it has no valid lease past the dispatch timeout.
- Expired worker leases are reclaimed with a higher generation after worker or PostgreSQL restart.
- In the sequence `v1 claim → v2 claim → v2 complete → v1 complete`, the final result remains v2.
- Completed valid data returns without queueing work.
- Version-mismatched data starts one replacement attempt while preserving the prior result as stale.
- A failed replacement attempt leaves the prior successful result readable.
- Batch lookup returns completed existing results only for the canonical default CID.
- A successful declaration remains visible when deep analysis fails.
- Declaration expiry and deep-result expiry refresh independently.
- PostgreSQL remains the sole persistent result, declaration, target-fencing, and durable-attempt owner.

### Analysis

- Platform subtitles are preferred.
- Missing subtitles trigger sampled-audio transcription.
- Visual analysis uses 6–12 low-resolution frames.
- Text-topic mentions alone cannot create a high text score.
- The score expresses finite-sample AI evidence strength and never claims AI-duration proportion.
- Missing detector output causes score-weight normalization and a deterministic confidence penalty.
- Perfect text, visual, and metadata confidence yields 1.0; perfect text plus visual yields 0.9; perfect text alone yields 0.5.
- Subtitle, sampled-ASR, title-only, no-speech, detector-timeout, 3–5-frame, and 6+-frame fixtures produce the material factors defined in section 11.
- Non-finite and out-of-range detector values are rejected instead of clamped.
- Confidence below 0.4 produces `证据不足`.
- Temporary media is deleted after every terminal task path.

### Performance and resource control

Performance is measured on the recommended 4-vCPU / 8-GB single-host stack with PostgreSQL and Redis on the same host and 100,000 result rows. Single-query and 30-item batch tests run separately with 20 closed-loop concurrent connections, a 30-second warm-up, five minutes of measurement, and at least 1,000 successful samples. The API boundary starts when the TLS reverse proxy receives the request and ends when the full response body is sent.

- Cached single-result queries meet P95 below 500 ms.
- Batch lookup of 30 identifiers meets P95 below 500 ms.
- Each test records P50/P95/P99, throughput, and error rate; error rate remains below 1%.
- New-analysis quotas are enforced per installation token.
- Repeated requests for an active version-specific attempt reuse that attempt.
- Repeated token registration from one IP cannot reset analysis quotas.

## 18. Verification Strategy

- Unit tests: BV/CID validation, label thresholds, evidence-strength aggregation, deterministic confidence calculation, evidence classification, quota calculation.
- API tests: installation registration, query, idempotent creation, batch no-create guarantee, stale-version replacement, typed errors.
- Database tests: version-specific active uniqueness, result/attempt separation, transactional outbox creation, default-CID ownership, and concurrent creation behavior.
- Recovery tests: queue publication failure, outbox-delivered then Redis-flushed, Redis restart, dispatcher restart, worker crash, PostgreSQL restart during claim or result commit, lease expiry, and the ordered `v1 claim → v2 claim → v2 complete → v1 complete` fencing case.
- Worker tests: subtitle path, no-subtitle ASR path, visual path, partial detector failure, stale-write rejection, and cleanup on every exit.
- Extension tests: SPA navigation, title insertion, recommendation batching, visibility gate, polling cancellation.
- Integration test: two clients request one uncached target and receive one shared completed result.
- Performance test: run the fixed closed-loop protocol from section 17 and publish latency, throughput, and error-rate output.
- Smoke test: Docker Compose starts on a 4-vCPU / 8-GB host and analyzes a bounded public sample.

## 19. Risks and Follow-up Decisions

- Bilibili DOM changes may break page adapters; selectors require isolated tests and explicit unsupported-page states.
- Bilibili access and BCut endpoints may change or trigger risk control; failures require clear diagnostics.
- Detection quality requires a labeled evaluation set before thresholds can claim calibrated accuracy.
- External model provider selection affects cost and latency; provider adapters remain internal to detector components.
- Bilibili part reordering can change the canonical default CID; the metadata owner must refresh the mapping and batch lookup must avoid stale non-default badges.
- Public deployment needs monitoring for queue depth, task duration, cache hit rate, failure rate, and API spend.

## 20. Baseline and Complexity Notes

- Product baseline: this design and `CONTEXT.md`.
- Architecture baseline: the ownership boundaries in sections 6–9.
- New surfaces are limited to the extension, API service, worker, PostgreSQL target/result/declaration/attempt/outbox/metadata records, Redis transient coordination, and the score aggregator.
- The design avoids parallel scoring owners, plugin-side authoritative scores, retained raw-media stores, and automatic homepage analysis.
- Architecture review is required before implementation completion because this design establishes public API, persistence, source-of-truth, and cross-component ownership boundaries.

