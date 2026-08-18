# Monday.com Account-to-Account Migration Tool — Project Overview

## 1. Goal

Build a reusable, hosted tool that copies data from one monday.com account
("source") to another monday.com account ("destination"), using each
account's API key for auth. The tool must:

1. **Discover** everything available in the source account.
2. **Classify** each object as fully migratable, partially migratable
   (with caveats), or manual-only (not possible via API).
3. **Report** this to the user as a downloadable document *before* any
   write happens, so they know what will be copied automatically and what
   they'll have to do by hand.
4. **Execute** the migration for whatever the user confirms, respecting
   monday.com's API rate limits, with retries and full audit logging.
5. Be **reusable**: the same deployed system should work for any pair of
   accounts, not just one specific migration.

This is not a one-way sync or a live mirror. It is a one-time (or
on-demand, repeatable) bulk copy job with a human-reviewed plan step in
the middle.

## 2. Actors

- **Operator** — the person running the tool (you). Has access to the
  portal, enters both API keys, reviews the report, confirms scope,
  monitors progress.
- **Source account** — read-heavy API usage. Its API key only needs read
  scopes.
- **Destination account** — write-heavy API usage. Its API key needs
  write scopes for boards, items, users, docs, etc.

## 3. High-level flow

```
[Portal: enter source+dest API keys]
        │
        ▼
[Discovery Job] ──> reads source account inventory ──> [Inventory store]
        │
        ▼
[Report Generator] ──> classifies each object, estimates cost/time
        │
        ▼
[Downloadable report] ──> operator reviews, selects scope
        │
        ▼
[Orchestrator] ──> builds dependency-ordered task DAG for confirmed scope
        │
        ▼
[Cloud Tasks queues] ──> rate-limited execution against destination API
        │
        ▼
[State store: ID mapping, status per object]
        │
        ▼
[Final report: what migrated, what failed, what needs manual work]
```

## 4. Non-goals (explicitly out of scope for v1)

- Live/continuous two-way sync.
- Preserving original authorship or timestamps on recreated
  items/updates/comments (API-created objects will show the API token's
  identity and current time — call this out clearly in every report).
- Migrating automations, dashboards (widget layout), account-level
  settings, SSO/SCIM config, marketplace app installs, or form
  configuration — these are manual-only (see
  `01-monday-api-capability-matrix.md`).

## 5. Companion documents

- `01-monday-api-capability-matrix.md` — what monday's API can and can't
  duplicate, used to drive the classification engine.
- `02-architecture.md` — GCP services, data flow, rate-limiting design.
- `03-implementation-roadmap.md` — phased build plan, including the gaps
  identified during planning (idempotency, rollback, dry-run, etc.).
- `04-data-models-and-schemas.md` — Firestore/BigQuery schemas, task
  payload shapes, ID-mapping table structure.
- `05-resume-and-rollback.md` — shared resume/rollback subsystem built
  on the ID-mapping state store.

An implementing AI/engineer should read all four before writing code —
the capability matrix and data models directly shape the orchestrator
and task-handler logic.
