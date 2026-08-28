# Data Models & Schemas

## 1. Firestore

### `jobs/{job_id}`
```
{
  job_id: string,
  created_at: timestamp,
  status: "created" | "discovering" | "report_ready" | "scope_confirmed"
        | "running" | "completed" | "failed" | "aborted",
  source_account: { secret_ref: string },   // Secret Manager reference, not the key itself
  dest_account:   { secret_ref: string },
  operator_email: string,
  expires_at: timestamp   // for Cloud Scheduler cleanup
}
```

### `jobs/{job_id}/inventory/{object_id}`
```
{
  object_id: string,          // source-account object ID
  object_type: "workspace" | "board" | "group" | "column" | "item"
             | "subitem" | "update" | "file" | "doc" | "article" | "user",
  parent_object_id: string | null,
  name: string,
  classification: "full" | "partial" | "manual_only",
  caveat: string | null,
  estimated_complexity_cost: number,
  included_in_scope: boolean   // set after operator confirms scope
}
```

### `jobs/{job_id}/id_map/{entity_type}_{source_id}`
```
{
  source_id: string,
  dest_id: string,
  entity_type: "workspace" | "board" | "group" | "column" | "item",
  created_at: timestamp
}
```
This table serves as the primary idempotency check. It is queried before any create mutation and populated immediately upon success.

### `jobs/{job_id}/state/complexity_bucket`
```
{
  remaining_tokens: number,
  last_reset: timestamp
}
```
Replaces the proposed in-memory rate limiter with a global, transactional Token Bucket in Firestore. It is actively decremented proactively by the Cloud Tasks workers (e.g. `consume_budget`) and reactively resynced with the exact metadata returned from the Monday.com GraphQL API.

### `jobs/{job_id}/dag_state/{stage}`
```
{
  total_tasks: number,
  completed_tasks: number,
  status: "pending" | "completed"
}
```
This schema gates the execution DAG. Initialized by the orchestration before execution, tasks increment `completed_tasks` transactionally. When the counter reaches `total_tasks`, the orchestration queues the subsequent stage.

## 2. BigQuery

### `inventory_events` (append-only, written during Discovery)
| column | type |
|---|---|
| job_id | STRING |
| object_id | STRING |
| object_type | STRING |
| classification | STRING |
| estimated_complexity_cost | INT64 |
| discovered_at | TIMESTAMP |

### `migration_events` (append-only, written during Execution)
| column | type |
|---|---|
| job_id | STRING |
| source_object_id | STRING |
| dest_object_id | STRING |
| object_type | STRING |
| attempt_number | INT64 |
| complexity_cost | INT64 |
| status | STRING |  -- success / retry / failed_transient / failed_permanent
| error_message | STRING |
| event_at | TIMESTAMP |

These two tables are what the report generator and the live dashboard
both query — pre-migration report reads `inventory_events`, live
progress and final report read `migration_events` joined back to
`inventory_events`.

## 3. Cloud Tasks payload shape

Each task represents exactly one object-copy operation:
```
{
  job_id: string,
  source_object_id: string,
  object_type: string,
  operation: "create_board" | "create_group" | "create_column"
           | "create_item" | "create_subitem" | "create_update"
           | "upload_file" | "create_doc" | "create_article"
           | "add_user_to_board" | ...,
  depends_on: [string]   // source_object_ids that must already have
                          // a dest_id in id_map before this can run
}
```
The task handler resolves `depends_on` IDs via the `id_map` table at
execution time (not baked in at enqueue time), since dependency
resolution may lag behind DAG construction in a long-running job.

## 4. Rate-limiter state (per job, per direction)

Kept in-memory in the handler (or Redis/Memorystore if you need it
shared across handler instances) rather than Firestore, since it needs
sub-second read/write performance:
```
{
  token: "source" | "dest",
  budget_per_minute: number,      // from account plan tier, checked at discovery time
  used_this_window: number,
  window_reset_at: timestamp
}
```
Updated from the `complexity { before after }` block on every real API
response — treat the live server value as ground truth over the local
estimate whenever they diverge.
