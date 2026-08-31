# Implementation Roadmap

## Phase 0 — Foundations
- [ ] GCP project setup, IAM, Secret Manager, Firestore, BigQuery, Cloud
      Storage buckets provisioned.
- [ ] monday.com GraphQL client wrapper (auth header injection, complexity
      field auto-included on every query/mutation, structured error
      parsing for `ComplexityException` vs. validation errors).
- [ ] Job model: `job_id` creation, Secret Manager scoping, Firestore
      `jobs/{job_id}` root document.

## Phase 1 — Discovery (Done)
- [x] Paginated readers for: workspaces, boards, groups, columns, items
      (+ subitems), column values, updates, files, docs, articles,
      users/teams.
- [ ] Write inventory rows to Firestore + BigQuery as discovery proceeds
      (stream, don't wait for full completion, so a huge account doesn't
      block on a single job step).
- [ ] Complexity-cost estimator per object type (based on observed query
      complexity from `complexity.query` responses).

## Phase 2 — Classification & Report (Done)
- [x] Implement the capability matrix (`01-monday-api-capability-matrix.md`)
      as a rules engine: object type + column-type + relationship checks
      → `full` / `partial` / `manual_only` + caveat text.
- [x] Column-type compatibility check against destination account (some
      marketplace-app column types may not exist there at all).
- [x] Plan tier / rate-budget check on both accounts (trial/free vs.
      standard) — surfaced in the report as an expected-duration caveat.
- [x] Report renderer (PDF/XLSX) — grouped by bucket, with counts,
      estimated total complexity, estimated wall-clock time. (Markdown done)
- [x] Portal UI: scope selection tree (check/uncheck workspaces, boards,
      "include files" toggle, etc.), confirm action. (Scaffolded React+Vite app)

## Phase 2.5 — Backend API & Infrastructure Preparation (Done)
- [x] Setup FastAPI backend (`src/api/routes.py`).
- [x] Scaffold React + Vite frontend (`frontend/`).
- [x] Create Dockerfiles for API and Frontend.
- [x] Write Terraform definitions for Cloud Run and Secrets Manager (ADC Auth).
- [x] Deploy Portal UI and API.

## Phase 3 — Orchestration & Execution
- [x] DAG builder from confirmed scope, respecting dependency order:
      workspace → board → group → column → item → subitem → update →
      file → doc.
- [x] Cloud Tasks queue setup per stage/direction (source-read queue,
      dest-write queue), with `max_dispatches_per_second` /
      `max_concurrent_dispatches` as coarse limits.
- [x] Token-bucket rate limiter in the task handler, fed by live
      `complexity` response data.
- [x] Idempotency check (`source_id → dest_id` lookup in Firestore)
      before every create-mutation.
- [x] Pub/Sub stage-completion events to gate the next DAG stage.
- [x] Retry policy: transient vs. permanent error classification;
      `ComplexityException` → exact requeue delay from
      `reset_in_x_seconds`; dead-letter queue after N attempts.

## Phase 4 — Reporting & Ops
- [ ] BigQuery `migration_events` table + Looker Studio (or in-portal)
      live progress view.
- [ ] Final report generator (actuals vs. plan): migrated / failed /
      manual-only, in the same format as the pre-migration report.
- [ ] Cloud Scheduler job to purge expired secrets/state.

## Phase 5 — Hardening (items identified as commonly missed)
- [ ] **ID-mapping export** — make the `source_id → dest_id` table a
      first-class downloadable deliverable (CSV/JSON), not just internal
      state, so the operator can manually patch mirror/connect-board
      columns and any external systems referencing old monday IDs.
- [ ] **Dry-run mode** — compute the full task DAG and complexity cost
      without executing any write, so the operator can sanity-check
      before an irreversible bulk-create run.
- [ ] **Resume & rollback subsystem** — see `05-resume-and-rollback.md`.
      Build these together: both reconcile against `id_map`, just
      traversing the DAG in opposite directions (forward for resume,
      reverse for rollback), and both reuse the same Cloud Tasks +
      rate-limiter path as forward migration.
- [ ] **Explicit consent UI** — separate confirmation steps for read
      access (discovery) and write access (execution), since two
      different customers' credentials are involved.
- [ ] **Cost/time estimate shown before execution starts**, not just in
      the static report — recompute against current live rate-limit
      headroom right before the operator hits "go."
- [ ] **Author/timestamp disclosure** — every report must state plainly
      that recreated items/updates will show the API token's identity
      and current time, not the original author/date.

## Suggested build order for an implementing AI

1. Read `00-project-overview.md`, `01-monday-api-capability-matrix.md`,
   `02-architecture.md`, `04-data-models-and-schemas.md`, and
   `05-resume-and-rollback.md` in full first.
2. Build the GraphQL client wrapper + complexity-aware rate limiter as a
   standalone library — everything else depends on it.
3. Build Discovery + Classification + Report before touching write paths
   at all; this is independently useful and testable against a real
   monday.com sandbox account.
4. Build Orchestration + Execution against a throwaway destination
   account, with dry-run mode built in from the start (not bolted on
   later).
5. Add retry/dead-letter/rollback once the happy path works end-to-end.
