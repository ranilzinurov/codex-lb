## Why

Dashboard API-key attribution currently sees only traffic that passed through codex-lb. Local Codex usage on a user's machine consumes the same upstream ChatGPT account quota but is invisible to the attribution denominator, so a single visible codex-lb API key can appear to explain 100% of account usage.

## What Changes

- Add an authenticated ingestion endpoint for external Codex token-count aggregates.
- Store ingested aggregates as synthetic `request_logs` rows under the authenticated API key, so existing dashboard attribution, usage summaries, and request-log filters can include the external source without a separate reporting path.
- Add a local uploader script that reads Codex `token_count` events from `$CODEX_HOME` JSONL session logs, aggregates input/cached/output/reasoning tokens into time buckets, and posts them to codex-lb.

## Impact

- `api-keys`: visible API keys can represent external/local Codex usage in dashboard attribution.
- `frontend-architecture`: no UI contract change; existing attribution widgets consume the synthetic request logs.
- `compatibility-tooling`: local operators get a repeatable sync script suitable for launchd/cron.
