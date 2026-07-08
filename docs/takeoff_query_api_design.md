# Takeoff Query API — Design (ADR-003)

**Status:** Proposed. Building QA0 (shred + schema).
**Date:** 2026-07-08
**Depends on:** ADR-001 (service skeleton, storage split), ADR-002 (sharded orchestration).
**Scope:** Serve the extracted takeoff data to downstream consumers as a versioned, paginated
contract carrying provenance + confidence on every record. Completes responsibility #4
(Query API) — the submit → process → **query** loop.

---

## 1. Context — the consumer is an agent, so the API is a *grounding layer*

The primary consumer is an agent answering a natural-language request ("complete the takeoff
for these documents and return the key information"). The agent's job is to report what was
found *honestly*; the API's job is to be the source of truth it quotes. So the API serves
only **grounded** data — nothing a model could hallucinate, nothing interpretive.

The service stays a typed data contract. It does **not** run the LLM or compose prose; the
agent lives outside. This keeps the deterministic, offline, no-credentials core intact.

## 2. The grounding rule (the load-bearing decision)

Every field the Query API returns is exactly one of:

1. **Extracted** — a value a pipeline record holds (`mark`, `quantity`, `count`, `area_sf`,
   `symbol_id`, …), always carried with its provenance (`source` file + page) and its
   confidence / `quantity_basis` / `verified` status.
2. **Exact rollup** — a deterministic count or sum over those records (`total`, `by_schedule`,
   `coverage`, `unverified` count).

Nothing else. No quality score, no estimate, no narrative, no heuristic — the pipeline does
not ground those, so we do not serve them. `ScheduleItem` has **no numeric confidence**; its
honesty is `quantity_basis` (`row_count` / `qty_column` / `unknown_plan_count`) + `shape`.
`RoomArea` / `CountResult` carry numeric `confidence`. We never fabricate one.

**Self-consistency invariant (testable):** the summary's aggregates equal the counts returned
by the detail endpoints — `summary.items.total == len(GET …/items)`,
`by_schedule["door"] == count(items where schedule=door)`, etc. The summary is a faithful
projection of the rows, not a parallel computation that can drift. A contract test asserts it.

## 3. Rebuildable projection

The MinIO artifact blob stays **canonical**; the Postgres entity tables are a **projection of
it**, always reconstructable from the blob. Shredding is idempotent (delete-then-insert per
`job_id`), so a re-run or backfill is safe.

## 4. Data model (migration 0003)

Three `job_id`-scoped tables; `ordinal` preserves the artifact's order so paginated reads
match the golden ordering. Columns mirror each record's `to_dict()`.

`schedule_items`
: job_id, ordinal, schedule, shape, mark, quantity, unit, quantity_basis, description,
  attributes (JSONB), src_file_id, src_page_index. Index `(job_id, schedule)`, `(job_id, ordinal)`.

`room_areas`
: job_id, ordinal, room_number, area_sf, confidence, basis, src_file_id, src_page_index.
  Index `(job_id, ordinal)`.

`fixture_counts`
: job_id, ordinal, symbol_id, sheet_page, count, confidence, source, verified, boxes (JSONB).
  Index `(job_id, symbol_id)`, `(job_id, ordinal)`. (Provenance here is `sheet_page`.)

## 5. Shredding (QA0)

- `project(report) -> {schedule_items, room_areas, fixture_counts}` — pure, unit-testable
  transform from the report dict to row dicts (adds `ordinal`).
- `shred_entities(session, job_id, report)` — idempotent delete-then-insert. Called from
  **both** `orchestrator.reduce_job` (sharded) and `worker.process_job` (single), so every
  completed job populates identical rows.

## 6. Endpoints (QA1, v1 — filtered slices are the priority)

Consumer pattern is **filtered slices** ("all door items", "plumbing fixture counts",
"low-confidence rooms to review"), so filters + their indexes are first-class.

- `GET …/{id}/summary` — the grounded "key information" bundle: the pipeline's own
  `summary` / `area_coverage` / `fixture_count_summary` + exact-rollup flags
  (`count_pending` = items with `quantity_basis=unknown_plan_count`, `unverified` fixture
  counts, `rooms_without_area`, `incomplete` / `failed_shards`). Only extracted values +
  exact rollups.
- `GET …/{id}/items` — filter: `schedule`, `mark`, `quantity_basis`, `shape`.
- `GET …/{id}/fixture-counts` — filter: `symbol_id`, `verified`, `min_confidence`.
- `GET …/{id}/room-areas` — filter: `room_number`, `min_confidence`.
- (existing `…/artifact` — canonical blob — stays.)

Paginated envelope (offset/limit; cardinality is hundreds per job):
```json
{ "data": [...], "pagination": {"page","page_size","total","total_pages"},
  "job_id": "...", "entity_schema_version": "1.0.0", "incomplete": false }
```

State gating: entity queries on a non-terminal job → `409`; every record carries `source` +
confidence/basis so any claim is citable back to a source page.

## 7. Milestones (thin vertical; STOP + discuss each)

- **QA0 — projection:** migration 0003, the three tables, `project` + `shred_entities`, wired
  into both terminal paths. Verified by shredding the golden report (memory-light).
- **QA1 — endpoints:** the grounded `summary` + three filtered detail endpoints, pagination,
  state gating, and the summary↔details self-consistency contract test.

## 8. Guardrails carried forward

Pipeline invoked, never modified. No value served without provenance + confidence/basis.
No LLM dependency in the service. Golden outputs + offline suite intact.
