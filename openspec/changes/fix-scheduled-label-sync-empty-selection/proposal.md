## Why

The scheduled Codex review label synchronization run uses `--all-open`. When
the repository has no open pull requests, the script currently treats the
valid empty selection as an invalid invocation and exits with status 1. That
creates a false workflow failure during quiet periods.

## What Changes

- Treat an empty result from the open pull-request query as a successful
  no-op only for `--all-open` runs.
- Preserve the existing synchronization path for one or more open pull
  requests and the existing error handling for explicit selections and
  GitHub read, classification, or write failures.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `github-automation`: scheduled label synchronization succeeds when the
  open pull-request selection is empty.

## Impact

- **Code**: `.github/scripts/sync_codex_ok_labels.py`
- **Tests**: `tests/unit/test_sync_codex_ok_labels.py`
- **Specs**: `openspec/specs/github-automation/spec.md`
