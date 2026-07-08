# Takeoff Scaling & Large-Set Handling — Design (ADR-002)

**Status:** Proposed (not built). Evidence-backed by the scaling experiment below.
**Date:** 2026-07-08
**Depends on:** ADR-001 (`docs/takeoff_service_design.md`) — the S0/S1 walking skeleton.
**Scope:** How the takeoff service processes *large* drawing sets (hundreds→1000+ pages)
without OOM or timeout. Extends the service; does **not** modify pipeline extraction.

---

## 1. Terminology (read first)

**Shard** in this document = a **page-range unit of work** — an ephemeral slice of one PDF
extraction, created for one job and discarded after the results are merged. This is **task
parallelism** (MapReduce input-splits / Spark partitions), **not database sharding**: there
is no stored partition, no shard key/hash, no routing table, no rebalancing. The only place
*database* sharding could ever apply here is the Postgres entity store, which is out of
scope and not needed at our scale.

The pattern is **partition → map → reduce** (scatter-gather / fan-out-fan-in).

---

## 2. Context — the measured problem

The S1 architecture is one job = one process = one `Document` over the whole PDF. Measured
scaling (probe over the real UCCS 133p and Pinney 525p sets; calls the same memoized
Document/Page methods the drivers use):

- **Per-page (linear) terms are trivial:** text-gate 0.018 s/page + words 0.017 s/page ≈
  **0.035 s/page** (→ 35 s at 1000 pages).
- **pdfplumber `.tables()` is the entire cost, and it scales with *candidate* pages:**
  UCCS 133p = 74 candidates × 6.6 s = **487 s** (this *is* the ~520 s `schedules` phase).
- **Candidate density is document-dependent:** UCCS (real drawings) **0.56 candidates/page**;
  Pinney (mostly manual pages) **0.11/page**. Candidates grow ~linearly with pages — they do
  **not** stay flat.
- **Memory is the real cliff:** peak RSS 29 candidates → **2.4 GB**, 74 candidates →
  **6.7 GB**, i.e. **~96 MB per extracted candidate page** (pdfplumber retains parsed
  layout; `.tables()` memoization holds it). Faithful to the real build.

**Projection (UCCS-dense, the design-to case):**

| pages | candidates | time | memory |
|---|---|---|---|
| 133 | 74 | ~8 min | 6.7 GB |
| 525 | ~290 | ~32 min | ~28 GB |
| **1000** | **~556** | **~62 min** | **~53 GB** |

Even the sparse (Pinney-like) case at 1000p is ~12 min / ~10 GB. **Both document types OOM
before 1000 pages, and memory hits the wall before the 20-min timeout.** "Raise the timeout
+ bigger workers" was never viable — 53 GB doesn't fit a commodity worker.

---

## 3. Decisions

- **D1 — Scatter-gather on the existing fleet.** Partition the extraction into page-range
  shards, process them as independent RQ jobs (map), and combine with a merge job (reduce).
  No new framework (no Spark/Hadoop): RQ + Redis + Postgres already give partitioning,
  fan-in (job dependencies), retries, and coordination. The pipeline's `page_range` seam
  already exists, so this is a **service-layer** change.

- **D2 — Shard size is set by a MEMORY budget, not a fixed page count.** Because memory ≈
  `96 MB × candidates`, a shard must cap its candidate count:
  `candidates_per_shard ≈ memory_budget / 96 MB`. At a 3 GB budget → ~30 candidates/shard
  (≈ 50 UCCS-dense pages, ≈ 270 Pinney-sparse pages). Time per shard follows
  (~30 × 6.6 s ≈ 3 min) — comfortably under the job timeout.

- **D3 — Balance shards by CANDIDATES, via a cheap planner pass.** Candidates cluster
  unevenly, so splitting raw page ranges risks one hot shard (Amdahl). The planner runs the
  text-gate over the whole doc **once** (0.018 s/page → ~18 s at 1000p, no pdfplumber),
  locates candidate pages, and **bin-packs them into shards of ~equal candidate count**,
  each ≤ the memory budget. Cheap global pass → balanced shards.

- **D4 — Two-wave DAG, but start with Wave 1 only.** Area harvest is filtered by the global
  finish-room set, which only exists after all schedule shards merge. The correct DAG is
  `schedule shards → merge(items + finish_rooms) → area/count shards → assemble`. **But**
  the per-page passes (words 0.017 s/page → 17 s at 1000p; counts negligible) are cheap, so
  **Wave 2 stays serial after the merge** until measurement shows it needs sharding. v1
  parallelizes only the dominant `schedules` phase.

- **D5 — Reduce must be byte-identical to the serial golden.** Merge = union + dedup by
  `(schedule, mark)` in **ascending page order** (reproducing `for i in sorted(candidates)`
  and first-wins dedup). This is the hard guardrail: the merged artifact is diffed against
  the serial golden before the fan-out path is trusted. If it diverges, we stop.

- **D6 — Small sets keep the single-job fast path.** Below a threshold (≈ memory-budget's
  worth of candidates, e.g. < ~150 pages) the coordinator overhead isn't worth it — run the
  S1 monolith. Fan-out engages only for large sets. One decision point at submit.

- **D7 — Checkpointing is shard-level, split across two stores.** State lives where it
  belongs (the ADR-001 split): **Postgres = coordination** (the `takeoff_shards` row is the
  checkpoint record — `status`, `attempts`, `partial_object_key`); **MinIO = the partial
  payload** (`jobs/{job_id}/shards/{shard_index}.json`, a blob, not DB columns). A shard
  finishes → writes its partial to MinIO → flips its row to `succeeded`. A killed shard
  restarts *alone* (~30 candidate pages, ~3 min); every already-`succeeded` shard's partial
  is durable and untouched — a crash costs one shard, not the 62-min job. Granularity is the
  **shard** (shards are already small — no per-page checkpoint). Retry is idempotent: the
  pipeline is deterministic, so a re-run overwrites the same key with identical bytes;
  `shard_index` is the partial's idempotency key, and ADR-001's content-hash dedup guards at
  the job level. *Alternative on the table:* since S2 shreds items into Postgres anyway,
  shard partials could land directly in the entity tables tagged by shard, merging
  checkpoint + storage; v1 keeps blob-partials because they make the D5 byte-identical proof
  simpler.

- **D8 — DAG management: RQ primitives + a completion counter; NO workflow engine.** Our
  "DAG" is a fixed two-level scatter-gather (fan-out N shards → one reduce, + optional
  Wave 2), not a general graph — so **no Dagster/Airflow/Prefect/Temporal.** RQ gives the
  fan-in barrier (`enqueue(reduce, depends_on=[shard_1…N])`), but `depends_on` is awkward
  when a shard *fails* (we still reduce on partial results — degrade-and-flag), so v1 uses a
  **completion counter**: each shard atomically bumps `takeoff_jobs.completed_shards` (or a
  Redis counter), and the transition-to-complete — a **compare-and-set, so exactly one
  firing** — enqueues the reduce; a sweeper handles a shard that never reports. The parent
  job row is the source of truth. This is a deliberate trade: write a little coordination
  code rather than take a heavyweight dependency to run a 2-node graph. **Revisit when**
  takeoff + validation + bid-structure are orchestrated together per package, or we need
  durable cross-stage retries / human-in-the-loop — that (not now) is when Temporal or
  Dagster earns its place; the signal is the coordination code getting hairy.

- **D9 (pipeline, separate approval) — optional memory relief.** pdfplumber retains page
  caches; releasing them after `.tables()` (or not memoizing tables) is **memory-only,
  output-identical**. It would raise the per-shard page ceiling but does **not** remove the
  62-min time wall, so sharding is required regardless. Propose to pipeline owners as an
  independent, golden-safe change; not a dependency of this ADR.

---

## 4. Data model additions

- `takeoff_jobs` gains `mode` (`single` | `sharded`), `shard_count`, and lifecycle states
  `planning → mapping → reducing → succeeded|failed`.
- New `takeoff_shards`: `job_id` (FK), `shard_index`, `page_ranges` (jsonb — the packed
  candidate pages), `status`, `attempts`, `partial_object_key`, `error`, timings. The reduce
  reads all shard partials for a job.

---

## 5. Lifecycle

```
submit → validate → [plan] text-gate whole doc, bin-pack candidates into K shards
      → mapping:   K shard jobs, each extract_schedule_items(page_range=shard) -> partial
      → reducing:  merge partials (union + dedup, page order) -> artifact + manifest
      → succeeded  (partial-failure: a dead shard flags the artifact incomplete, never
                    silently drops — degrade-and-flag)
```

Observability: per-shard timing / peak memory / candidate count in the manifest; the parent
aggregates. Answers "which shard was slow/hot" at scale.

### Reduce vs. assemble (they are two steps, not one)

This is MapReduce's *shape*, but the reduce is a **light merge**, not a keyed group-by with a
shuffle:

1. **reduce** — read all shard partials, **concatenate in ascending page order**, and apply
   **first-wins dedup on `(schedule, mark)`**. Data is hundreds of items (no shuffle, no
   aggregation math); in MapReduce terms it's a degenerate reduce (key `(schedule, mark)`,
   combiner "keep first"). Crucially it is **order-sensitive** — it must reproduce the serial
   builder's `for i in sorted(candidates)` + `seen`-set order, which is exactly why D5
   (byte-identical) is the delicate part. Output: the global `items` list + `finish_rooms`.
2. **Wave 2 (serial)** — area harvest + fixture counts run on `finish_rooms` (cheap:
   words ~0.017 s/page, counts negligible), not sharded in v1.
3. **assemble** — call the pipeline's *existing* pure
   `assemble(items, room_areas, finish_rooms, fixture_counts)` **once** to produce the final
   artifact (summary + records). We do not reimplement it; we feed it the merged inputs.

---

## 6. Alternatives considered (and rejected)

- **Bigger workers + longer timeout** — 53 GB / 62 min doesn't fit commodity hardware;
  wasteful and still single-machine-bounded. Rejected.
- **Process pool on one box** — bounded by one machine's RAM/cores; still OOMs a huge set.
  A stepping stone at best. Rejected as the target.
- **Swap pdfplumber for pymupdf `find_tables`** (faster, lighter) — changes extraction
  outputs → breaks the golden. Off-limits per the guardrails. Rejected.
- **Spark / a distributed compute framework** — massive over-engineering for one 45 MB file
  on the fleet we already run; violates the operational-simplicity bar. Rejected.
- **Single streaming pass with cache release** (D9 alone) — helps memory but leaves the
  ~62-min time wall and no parallelism. Necessary-adjacent, not sufficient.

---

## 7. Proposed milestones (thin vertical, golden-diffed each step; STOP + discuss)

- **SC0 — planner + schema.** `takeoff_shards`, the text-gate planner, candidate bin-packing;
  no execution yet (unit-test the packing).
- **SC1 — single-shard map.** A shard worker runs `extract_schedule_items(page_range=…)` and
  persists a partial. Prove one shard's partial equals the serial slice.
- **SC2 — reduce + golden proof.** Merge partials; assert the merged artifact is
  **byte-identical** to the serial golden on UCCS. This is the gate for the whole approach.
- **SC3 — fan-out orchestration.** Parent job, K shards, completion-triggered reduce, the
  small-set threshold (D6).
- **SC4 — checkpointing / retry / dead-letter** per shard; partial-failure flagging.
- **SC5 — memory-budget shard sizing** (D2/D3) + per-shard memory in the manifest; validate
  peak stays under budget on a synthesized large set.

De-risk order: **SC2 (byte-identical reduce) is the make-or-break** — do it before building
the orchestration around it.

---

## 8. Open questions (measure next)

- Real candidate-density distribution across more firms (UCCS 0.56 vs Pinney 0.11 is a wide
  band; it sets the shard-size default).
- Is D9 (cache release) acceptable to the pipeline owners, and how much does it move memory?
- Fan-out coordinator overhead vs. shard count — where the small-set threshold (D6) actually
  sits.
