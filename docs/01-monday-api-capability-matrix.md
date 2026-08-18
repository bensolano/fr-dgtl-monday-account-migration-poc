# monday.com API Capability Matrix

This matrix drives the classification engine used by the Report
Generator. Every discovered object must be tagged `full`, `partial`, or
`manual_only`, with a human-readable caveat string for `partial`/
`manual_only` items.

## 1. Fully migratable (tag: `full`)

| Object | Read | Write | Notes |
|---|---|---|---|
| Boards (structure) | `boards` query | `create_board` | Recreate schema (columns, groups) on destination; don't use `duplicate_board` — that only works within one account. |
| Groups | `groups` (nested in board) | `create_group` | Create before items so `group_id` is available. |
| Columns (native types) | `columns` (nested in board) | `create_column` | Map column type + settings; formula/mirror/connect-boards have ordering requirements, see below. |
| Items | `items_page` (paginated) | `create_item` | Standard object-copy path. |
| Subitems | `subitems` (nested in item) | `create_subitem` | **Must be its own explicit step** — `duplicate_item` does not carry subitems cross-board, so don't rely on any "duplicate" shortcut; always read-then-recreate. |
| Column values | `column_values` | passed in `create_item`/`change_column_value` | Batch where possible to reduce call count. |
| Docs (content) | `doc_blocks`/markdown export | `create_doc` + markdown/HTML import | `import_doc_from_html` and markdown block mutations both work. |
| Articles | `articles`, `article_blocks` | `create_article`, `publish_article` | Workspace-scoped; newer API surface, verify available on both accounts' plans. |
| Workspaces (shell) | `workspaces` | `create_workspace` | Structure only — placement of boards etc. handled separately via `update_board_hierarchy`. |
| Team/user membership (invite-based) | `users`, `teams` | `add_users_to_board`, `add_users_to_team`, `add_users_to_workspace` | Only works if the person already exists or is invited to the destination account — you cannot fabricate a new identical user. |
| **Connect-boards columns** | `columns` settings (`connection_board_ids`) | `create_column` (`column_type: connect_boards`, `defaults` specifying target board) + `change_multiple_column_values` per item to set the actual item-level links | **Corrected from earlier assessment** — this is creatable via API. Requires: (1) the connected board already exists in the destination with a known `dest_id` from the ID map, so it must run as a later DAG stage, after board creation; (2) item-level linking is a separate per-item step using the *new* item IDs, also resolved via the ID map, so it must run after both sides' items exist. |
| **Mirror columns** | `columns` settings (`relation_column`, `displayed_linked_columns`) | `create_column` (`column_type: mirror`, `defaults` referencing the relation column + target `board_id`/`column_ids`) | **Corrected from earlier assessment** — creatable via API, but depends on the corresponding connect-boards column already existing on the destination board (same ordering constraint as above). Mirror *values* are computed automatically once the connect-boards link is set — you never write to the mirror column directly, and can't. |

## 2. Partially migratable (tag: `partial`) — copy works but with caveats

| Object | Caveat to surface in report |
|---|---|
| Updates / comments | Recreated updates show the API token's user as author and "now" as the timestamp — original author/date is lost unless separately noted in the update body. |
| Files/attachments | Requires binary download from source + upload to destination; heavy on complexity budget; large libraries should be batched/throttled separately from item creation. |
| Formula columns | Formula definition can usually be recreated, but if it references a connect-boards/mirror column, it inherits that column's ordering dependency (see §1 — the connected board must exist first). |
| Checklists inside updates | Data is copyable, but "duplicated exactly as-is" behavior (e.g., completion state) needs to be handled item-by-item, not assumed automatic. |
| Cross-board connections where the **connected board is out of scope** (not being migrated in this job) | If the operator excludes the connected board from the migration, the connect-boards/mirror column can't be recreated meaningfully on the destination — no valid target board ID exists. Falls back to `manual_only` in this specific case only. |

## 3. Manual-only (tag: `manual_only`) — no general API path

| Object | Why |
|---|---|
| Automations / integration recipes | No API to read a recipe's logic as a portable object and no create-equivalent; even monday's own native "duplicate board" doesn't carry custom automations with integration blocks across — user must recreate by hand on the destination. |
| Dashboards (cross-board widget layer) | No general mutation to clone a dashboard's widget config. |
| Marketplace app installs / integrations | Account-level install/config, not exposed for programmatic write. |
| Permissions (board-level, column-level restrictions) | Mostly admin-console configuration, limited/no write API. |
| Custom views | Not portable via API. |
| Forms (public form settings: branding, logic, restricted columns) | Not fully exposed via mutation. |
| Account/workspace-level settings (branding, SSO/SCIM, tags library, custom field library) | Admin-console only. |
| User identity/profile creation | You can invite/add existing or new-by-email users to boards/teams/workspaces, but you cannot script an identical user account (auth, avatar, etc.) into existence. |

## 4. Column-type compatibility notes

Not every column type serializes/deserializes 1:1 through the API. Before
building the general "copy any column" path, verify per-type:

- Native types (text, numbers, status, date, people, dropdown, checkbox,
  timeline, etc.) — generally safe, `full`.
- Formula — safe to recreate the formula string; flag if it depends on a
  `partial` column.
- Mirror / Connect boards — `full`, but with a hard ordering dependency (see §1); treat as `manual_only` only if the connected board is excluded from the migration scope.
- Dependency column — verify write support per current API version; treat as `partial`/`manual_only` if no documented mutation exists yet.
- App-provided custom column types (from marketplace apps) — verify
  availability on destination account; may not have write support at
  all → treat as `manual_only` if no documented mutation exists for that
  column's value shape.

## 5. Rate limits (drives the throttling design in `02-architecture.md`)

- Complexity limit is **per account, not per user**, resetting on a
  sliding 60-second window.
- Standard accounts: up to **10,000,000 complexity points/minute**;
  trial/free/NGO/playground accounts have lower budgets — check both
  source and destination account tiers during discovery, since the
  destination's write budget may be the real bottleneck.
- A single call cannot exceed **5,000,000 points**.
- Always request `complexity { before after query }` (or
  `reset_in_x_seconds` on a `ComplexityException`) on every call and use
  it to pace dynamically — don't hardcode a fixed QPS.
- Prefer paginated queries (`items_page` with `limit`) over unbounded
  nested queries; nested queries grow complexity exponentially.
- Source and destination tokens have **independent** budgets since
  they're different accounts — reads and writes don't compete with each
  other, but each still needs its own throttle.
