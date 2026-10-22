# Categories

Code: `cloudstore/sync_categories.py`. Trigger: **Sync Category Tree** button
(`api.sync.trigger_categories_sync`) or the scheduler.

## Run

`run(trigger)`:

1. Creates a Cloudstore Sync Log (`sync_type=categories`, `status=running`).
2. Ensures the root Item Group `All Item Groups` exists.
3. Calls `GET /categories/tree` (`client.categories.tree()`).
4. `_sync_tree(tree, "All Item Groups", ...)` walks the tree recursively.
5. Writes `items_processed`, `items_created`, `items_updated`, `items_failed`
   and sets `status=success`. An exception sets `status=failed` and
   `error_message`.

## Per node

Cloudstore sends `{id: {$oid}, name, level, children[]}` per node.

| Cloudstore | Item Group field |
|---|---|
| `id.$oid` | `supplier_id` (custom field) |
| `level` | `supplier_cat_level` (custom field) |
| `name` | `item_group_name` (made unique, see below) |
| parent node | `parent_item_group` |
| has children | `is_group` = 1, else 0 |

A node with no `id` or no `name` is counted in `items_failed` and skipped.

Matching: an existing Item Group is found only by `supplier_id`. Names are never
used for matching, because the same name can appear under different parents.

Name collisions: Item Group names are unique in ERPNext. When the node name is
taken by another group, `_unique_item_group_name` uses `"<name> (<last 6 chars
of id>)"`, and adds `-2`, `-3`, ... if that is taken too. A group that already
holds the name keeps it.

Commits happen every 10 nodes. Progress counts are saved to the log every 20
nodes. A failing node is logged (`ERROR node <id> (<name>)`), counted in
`items_failed`, and the walk continues with the next node. Its children are
skipped.

## Not done

Item Groups that no longer exist in Cloudstore are not deleted or changed.

## Used by items

`_resolve_item_group` takes the first id in an item's `cats[]` and returns the
Item Group with that `supplier_id`, or an empty string. Run the category sync
before the item sync, otherwise items fall back to `All Item Groups`.
