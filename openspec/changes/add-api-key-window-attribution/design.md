## Context

ChatGPT account usage snapshots are account-level only. They report the current primary/secondary quota usage percentage, reset time, and window length, but they do not expose per-request or per-API-key credit deltas. codex-lb can therefore attribute usage only from its own `request_logs`.

## Design

### Additive API-key and dashboard contracts

API keys gain a `showOnDashboard` flag. The default is `false` for newly-created and existing keys so the dashboard does not suddenly expose every downstream key. Operators opt in only the keys that should appear in shared dashboard quota-attribution widgets.

The dashboard overview response keeps optional attribution data. Existing fields are unchanged, so a running deployment can update backend and frontend without coordinated client changes. The only database change is an additive boolean column with a false server default.

### Estimate credits from local logs

For each account/window pair:

1. Convert the latest upstream `used_percent` and local plan capacity into current consumed credits.
2. Query request logs for that account from `now - window_minutes` onward.
3. Group logs by API key and calculate request count, tokens, cached tokens, and cost.
4. Treat only `showOnDashboard = true` API keys as named rows.
5. Allocate consumed credits across the whole local-log denominator, then emit named rows for visible keys.
6. Add an unattributed row for any consumed credits belonging to hidden keys, unknown keys, traffic without an API key, logs outside the visible denominator, or windows with no logs.

This keeps the UI honest: named rows explain opted-in local traffic, while unattributed rows preserve upstream usage that came from hidden keys, disabled API-key auth, external account use, stale history, or logs outside the visible window.

### Compact UI

The dashboard attribution widget should be a compact usage breakdown, not a large reporting surface. It shows current quota windows (`5h` and `weekly`) as small bars/rows with percentages of already-consumed account quota, plus tokens/credits as secondary detail. Rolling dashboard timeframe labels remain for rolling metrics only; quota attribution labels remain tied to current quota windows.

## Risks

- Token share is a proxy for ChatGPT credits, not an upstream accounting source.
- Usage refresh can lag behind request logs, so short-lived differences are expected.
- Deleted API keys may have ids in historical logs but no current name or prefix.
- When API-key auth is disabled, request logs may have `api_key_id = null`; those rows are grouped into unattributed usage.
- Hidden API keys still contribute to the denominator and unattributed bucket, but their names are not displayed on the dashboard.
