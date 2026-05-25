## Why

Operators can see account-level 5h and weekly quota pressure, and they can see API-key request logs, but they cannot quickly tell which downstream API key is driving a shared account toward depletion. This is especially confusing when multiple API keys route through the same upstream ChatGPT account.

Upstream usage snapshots do not provide per-API-key attribution, so the dashboard must be explicit: the new breakdown is an estimate based on codex-lb request logs inside each account quota window.

## What Changes

- Add a per-API-key dashboard visibility flag, disabled by default, so operators explicitly opt keys into dashboard attribution.
- Add dashboard account-window attribution data derived from `request_logs` grouped by account, window, and dashboard-visible API key.
- Preserve compatibility by adding optional dashboard response fields only; existing clients can ignore them.
- Include an unattributed bucket when current upstream consumed credits are hidden, unknown, or not explained by local API-key logs.
- Render the attribution as a compact dashboard breakdown in the existing account/usage visual style.
- Keep API-key detail views aligned with the same attribution language where practical.

## Capabilities

### Modified Capabilities

- `api-keys`: API-key settings control dashboard visibility; accounting surfaces account-window attribution based on local request logs and labels it as estimated.
- `frontend-architecture`: Dashboard usage surfaces show opt-in per-API-key attribution for account 5h/weekly quota windows.

## Impact

- Backend: dashboard schemas/service/repository aggregation, request-log aggregation helpers, additive API-key visibility column
- Frontend: API-key visibility controls, dashboard schemas/components/tests
- Tests: dashboard overview contract coverage, attribution aggregation coverage, frontend rendering coverage
- Database: no destructive migration; use existing request-log columns and indexes unless verification shows a missing hot-path index
