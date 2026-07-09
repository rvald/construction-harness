# Takeoff Service Hardening — Idempotency, Config & Observability (ADR-004)

**Status:** Proposed (agreed decisions below). Building A1 first.
**Date:** 2026-07-09
**Depends on:** ADR-001 (skeleton), ADR-002 (sharding), ADR-003 (query API).
**Scope:** Two hardening tracks on the now-functional service — no new product capability.
All milestones verify **light** (mocks + Postgres, no pdfplumber / no 9-min runs).

---

## Track A — Idempotency + config knobs

### A1 — Config knobs on submit
- Accept an optional `config` JSON form-field on `POST …/ingestions`, validated by a
  service-side `TakeoffConfigIn` mirroring `TakeoffConfig`'s constraints (`render_dpi≥1`,
  `spread_threshold 0–1`, `min_tags≥1`, `page_range start<end`). Omitted = golden defaults.
- Thread the resolved config through both paths:
  - **Single**: `build_schedule_items` already takes `config` + `page_range` — pass them.
  - **Sharded**: the planner restricts candidates to a user `page_range`; the schedule map
    is config-agnostic (those knobs don't affect schedule extraction); **`assemble_report`
    opens one config-carrying `Document`** for Wave 2 (`count_fixtures` reads
    `spread_threshold`/`min_tags`) — also collapses its two doc-opens into one.
- Default config reproduces the golden (already proven). Config is stored and folds into
  `config_hash`.
- **Verify**: unit-test parse/validate/store/hash + assert the resolved config reaches the
  adapter (spy). No pipeline run.

### A2 — Dedup enforcement — **decision: return the existing job**
- **Work dedup** on `(content_sha256, config_hash)`: a **partial unique index**
  `WHERE status NOT IN ('failed','dead')`. Identical resubmission returns the existing job
  (HTTP 200, not a new 202) — no ~9-min re-run — while a failed/dead job can be superseded
  by a fresh submit. App does select-or-create with an `IntegrityError → fetch` fallback for
  the concurrent-submit race.
- **Request dedup** on `idempotency_key` (unique when present): same key + same content →
  return the original job; same key + *different* content → `409 idempotency_key_conflict`.
- **Verify** (Postgres): duplicate → same `job_id`; race fallback; key-conflict 409;
  failed-job re-run supersedes.

---

## Track B — Observability — **decision: logs + status + metrics (defer OTel)**

### B1 — Surface the sharded manifest in `GET …/{id}`
Unify the status response to always expose `mode`, `shard_count`, `incomplete`,
`failed_shards` (the gap seen in manual testing). Quick, high-value.

### B2 — Structured JSON logging + correlation
A JSON log formatter; propagate the API's `request_id` into the enqueued job so every
`plan/shard/reduce` line carries `job_id` + `request_id` + `shard_index`. Env-configurable
(level, json on/off). No document contents in logs (guardrail).

### B3 — Metrics (`/metrics`, `prometheus_client`)
RED/USE: request rate/errors/latency (histogram), jobs by terminal status (counter), shard
duration + retries/deaths. One new dep, one endpoint.

### Deferred — B4 OpenTelemetry tracing
Little payoff without a collector; revisit when there's somewhere to send spans.

---

## Sequencing
`A1 → A2 → B1 → B2 → B3`, each a stop-and-discuss milestone. Track A first (completes the
submit contract; dedup saves the expensive re-runs); B1 opens Track B as a fast fix.

## Guardrails carried forward
Pipeline invoked, never modified; default config stays byte-identical to the golden;
no secrets or document contents in logs; no LLM dependency; offline suite intact.
