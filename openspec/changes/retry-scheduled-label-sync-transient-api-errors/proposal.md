## Why

The scheduled `Codex review labels` workflow can fail while reading the open
pull-request list when GitHub temporarily returns HTTP `503`. The failure is
transient, but it still produces a workflow-failure email and obscures real
label synchronization problems.

## What Changes

- Retry read-only GitHub API calls that return HTTP `502`, `503`, or `504` with
  a small bounded delay schedule.
- Preserve failure after the retry budget is exhausted.
- Do not replay label, comment, or workflow-run approval mutations, because a
  response failure may occur after GitHub has already applied the mutation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `github-automation`: scheduled label synchronization tolerates transient
  GitHub read failures without hiding persistent errors.

## Impact

- **Code**: `.github/scripts/sync_codex_ok_labels.py`
- **Tests**: `tests/unit/test_sync_codex_ok_labels.py`
- **Specs**: `openspec/specs/github-automation/spec.md`
