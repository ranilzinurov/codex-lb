## Why

Re-importing or completing OAuth for the same ChatGPT account can happen after
the browser session is refreshed. When `importWithoutOverwrite` is enabled, the
service must not treat the same upstream `chatgpt_account_id` as a new local
account copy because that detaches request logs and usage attribution from the
active account.

## What Changes

- Preserve the existing local account row whenever an import/OAuth completion
  carries a `chatgpt_account_id` that is already known.
- Keep `importWithoutOverwrite` behavior for genuinely different upstream
  accounts that share an email address.

## Impact

- Account re-login remains stable for request logs, usage history, dashboard
  attribution, and local external Codex usage uploads.
- Operators can still intentionally keep separate records for different
  ChatGPT accounts using the same email.
