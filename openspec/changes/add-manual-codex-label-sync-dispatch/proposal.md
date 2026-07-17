## Why

The scheduled `Codex review labels` workflow runs every 15 minutes, but a
maintainer cannot immediately verify a fix or resynchronize labels after an
operational incident. The workflow needs a safe on-demand entry point for the
same all-open synchronization path.

## What Changes

- Add a `workflow_dispatch` trigger to the `Codex review labels` workflow.
- Route manual runs to the all-open synchronization job while keeping the
  per-PR event job skipped.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `github-automation`: label synchronization can be started on demand from the
  default branch.

## Impact

- **Workflow**: `.github/workflows/codex-review-labels.yml`
- **Tests**: `tests/unit/test_sync_codex_ok_labels.py`
- **Specs**: `openspec/specs/github-automation/spec.md`
