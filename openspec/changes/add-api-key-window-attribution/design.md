## Context

ChatGPT account usage snapshots are account-level only. They report the current primary/secondary quota usage percentage, reset time, and window length, but they do not expose per-request or per-API-key credit deltas. codex-lb can therefore attribute usage only from its own `request_logs`.

## Design

### Additive dashboard contract

The dashboard overview response gains optional attribution data. Existing fields are unchanged, so a running deployment can update backend and frontend without requiring destructive migrations or coordinated client changes.

### Estimate credits from local logs

For each account/window pair:

1. Convert the latest upstream `used_percent` and local plan capacity into current consumed credits.
2. Query request logs for that account from `now - window_minutes` onward.
3. Group logs by API key and calculate request count, tokens, cached tokens, and cost.
4. Allocate consumed credits across API-key groups in proportion to their total tokens.
5. Add an unattributed row for any consumed credits not covered by local API-key groups or when no logs exist.

This keeps the UI honest: named rows explain locally observed traffic, while unattributed rows preserve upstream usage that came from disabled API-key auth, external account use, stale history, or logs outside the visible window.

### No new migration by default

The existing `request_logs(api_key_id, requested_at DESC, account_id)` index supports API-key/time/account queries. The dashboard attribution query filters by account/time and groups by API key; verification should confirm current indexes are adequate before adding any migration. A migration is intentionally avoided unless performance testing proves it is needed.

## Risks

- Token share is a proxy for ChatGPT credits, not an upstream accounting source.
- Usage refresh can lag behind request logs, so short-lived differences are expected.
- Deleted API keys may have ids in historical logs but no current name or prefix.
- When API-key auth is disabled, request logs may have `api_key_id = null`; those rows are grouped into unattributed usage.
