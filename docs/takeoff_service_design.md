# Takeoff Ingestion Service — Design (ADR-001)

**Status:** Agreed; building S0+S1 (walking skeleton).
**Date:** 2026-07-08
**Branch:** `refactor/takeoff-access-layer` (service lands under `service/`).
**Scope:** Wrap the takeoff artifact builder as a production async service. Takeoff FIRST;
validation + bid-structure services come later behind the same submission shape.

---

## 1. Context

The pipeline exposes three independent artifact builders. This service wraps exactly one:

- [`build_schedule_items(source, *, config=None, page_range=None) -> (report, manifest)`](../src/takeoff/build_schedule_items.py)
  — one **drawings** PDF in; a `schedule_items` report + a run manifest out.

Measured realities we design around:

- **~5-min, CPU/memory-heavy run** (the `schedules` pass dominates at ~298s). Async only;
  never inline in a request.
- **All takeoff quantities live in the drawings PDF.** The project manual is *not* a takeoff
  input — it feeds the future validation + bid-structure services.
- **Page discovery is signature-gated** ([`extract_schedule_items`](../src/takeoff/quantity_schedules.py)):
  a page is parsed only if its text matches a schedule's title signature.
- **Provenance + confidence are already on every record.** We preserve and expose them,
  never launder. Note: `ScheduleItem` carries **no numeric confidence** — its honesty is
  `quantity_basis` (`row_count`/`qty_column`/`unknown_plan_count`) + `shape`
  (`instance`/`catalog`). `RoomArea` and `CountResult` carry numeric `confidence`. We never
  fabricate a confidence value.
- **Offline default.** The pipeline runs deterministically with no network/credentials; the
  optional `anthropic` VLM path stays opt-in.

## 2. Decisions

1. **Stack:** FastAPI · RQ on Redis · PostgreSQL + Alembic · MinIO (S3) · docker-compose
   local. 12-factor: all config via environment; no secrets in code or images.
2. **Dependency boundary:** the pipeline is an invoked library. **Only `service/pipeline_adapter.py`
   imports `src.takeoff`.** The worker downloads the PDF to a scratch path, calls the builder,
   and takes the returned `(report, manifest)` — we never use the builder's `output/reports/`
   write path and never touch pure extraction functions.
3. **Storage split:** raw PDF + canonical `report` JSON blob + manifest → MinIO (lineage).
   Entities are **shredded into Postgres** as the query surface.
4. **Config exposed, defaults reproduce golden.** Submit may carry `TakeoffConfig` knobs
   (`render_dpi`, `spread_threshold`, `min_tags`, `page_range`); omitted = today's defaults.
   Resolved config folds into the dedupe/version key.
5. **Idempotency & dedupe:** client `Idempotency-Key` for request dedupe;
   `unique(content_sha256, config_hash)` for work dedupe (same bytes + same knobs = same job).
6. **Input tagged by `role`:** a submission carries files tagged `drawings` | `project_manual`.
   Takeoff v1 requires **exactly one `role=drawings` PDF**; a `project_manual`, if present, is
   stored but not consumed. (UI will collect drawings and manual as separate uploads.)
7. **Degrade, never 500 for messy input:** manifest `failures` + low-confidence records are
   returned with status. Only infrastructure faults are 5xx.

### Deferred (explicit)

- A drawings **set split across multiple files** (merge, or locator-assisted windowing) — v1
  requires one drawings PDF.
- The validation + bid-structure services (same submission shape, different builders).

## 3. Data model

`takeoff_jobs`
: `id` (uuid), `idempotency_key`, `content_sha256`, `config` (jsonb), `config_hash`,
  `status` (queued|running|succeeded|failed|dead), `attempts`, `error` (jsonb),
  `pdf_object_key`, `artifact_object_key`, `manifest` (jsonb: checksum/page_count/timing/
  failures/config), `entity_schema_version`, timestamps. Unique `(content_sha256, config_hash)`.

Shredded entity tables (S2), mirroring each record's `to_dict()`:

`schedule_items`
: `job_id`, `schedule`, `shape`, `mark`, `quantity`, `unit`, `quantity_basis`, `description`,
  `attributes` (jsonb), `src_file_id`, `src_page_index`.

`fixture_counts`
: `job_id`, `symbol_id`, `sheet_page`, `count`, `confidence`, `source`, `verified`,
  `boxes` (jsonb).

`room_areas`
: `job_id`, `room_number`, `area_sf`, `confidence`, `basis`, `src_file_id`, `src_page_index`.

## 4. API (v1, versioned path, single error envelope)

- `POST /v1/takeoff/ingestions` — multipart `drawings` PDF + optional config + `Idempotency-Key`
  → `202 {job_id, status}`.
- `GET /v1/takeoff/ingestions/{id}` — status + manifest summary (timing, failures, checksum, config).
- `GET /v1/takeoff/ingestions/{id}/items | /fixture-counts | /room-areas` — paginated, every
  record with provenance + confidence(-basis) + `entity_schema_version` (S2).
- `GET /v1/takeoff/ingestions/{id}/artifact` — stream the canonical blob.
- `GET /healthz` (liveness) · `GET /readyz` (db + redis + object store reachable).

Error envelope: `{"error": {"code", "message", "request_id"}}`.

## 5. Milestones (thin vertical first; tests green each step; STOP + discuss after each)

- **S0** — service scaffold + docker-compose (api/worker/postgres/redis/minio), health/ready,
  env config, Alembic + `takeoff_jobs` migration. No entity tables, no idempotency, no config.
- **S1 — walking skeleton** — submit one drawings PDF → MinIO + job row → RQ → worker runs the
  builder → store blob + manifest → `GET` status/artifact. Proves submit→process→fetch and the
  async/timeout path.
- **S2** — shred entities into Postgres + paginated query endpoints with provenance.
- **S3** — config knobs on submit, idempotency + dedupe, OpenAPI/pagination polish.
- **S4** — retries/backoff, `job_timeout`, dead-letter, graceful shutdown, structured logs keyed
  by `job_id`, OpenTelemetry, RED/USE metrics.
- **S5** — unit (adapter transform) + integration (small fixture PDF / `page_range` fast path) +
  contract tests; CI lint/type/test; offline determinism + golden intact.

## 6. Guardrails carried from the charter

Pipeline invoked, never modified. No extracted value persisted or served without provenance +
confidence(-basis). No hard dependency on the LLM/VLM path in the default run. Golden outputs
and the offline suite stay intact. No secrets or document contents in logs.
