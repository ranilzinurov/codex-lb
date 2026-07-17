## ADDED Requirements

### Requirement: Codex review label sync supports manual all-open dispatch

The `Codex review labels` workflow MUST expose a `workflow_dispatch` trigger
from the default branch. A manually dispatched run MUST execute the existing
all-open synchronization job with `--all-open` and MUST NOT execute the
per-PR synchronization job without an identified pull request.

#### Scenario: Maintainer starts a manual synchronization

- **WHEN** the workflow is manually dispatched from the default branch
- **THEN** the all-open synchronization job runs
- **AND** the per-PR synchronization job is skipped
