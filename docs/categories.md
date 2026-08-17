# Categories

Cloudstore's category tree syncs one-way into ERPNext Item Groups. Code:
`cloudstore/sync_categories.py`, triggered by `sync_jobs.check_and_enqueue`
(scheduled) or `api.sync.trigger_categories_sync` (manual button).

---

## Cloudstore field → Alaiy OS field

| Cloudstore (`/categories/tree` node) | Alaiy OS (Item Group) |
|---|---|
| `id.$oid` | `supplier_id` (custom field) — the match key, never the name |
| `name` | `item_group_name` (disambiguated with a `(oid suffix)` on collision, since names repeat across branches) |
| `level` | `supplier_cat_level` (custom field) |
| `children` (non-empty) | `is_group = 1`; empty → `is_group = 0` |
| tree position | `parent_item_group`, built recursively starting from `All Item Groups` |

## Behavior notes

- The root `All Item Groups` Item Group is created if missing before the
  sync starts.
- Recursion order matters: a node is upserted, then its children are synced
  with the just-upserted group as their parent — so partial trees resolve
  correctly even mid-run.
- Progress is committed to the DB every 10 nodes and persisted to the log
  every 20 nodes, so a mid-run crash doesn't lose everything already
  processed (though it does leave the log's `status` at `running`, which the
  items-sync side treats as orphaned after 2 hours — the category sync has
  no equivalent stale-run guard of its own).
- A node missing an `id.$oid` or a `name` is skipped and counted as failed;
  it does not raise or abort the run.
- No deletes: a category removed on the Cloudstore side is never removed or
  disabled in ERPNext — it just stops being touched by future syncs.
