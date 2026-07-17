## 1. Manual workflow entry point

- [x] 1.1 Add the `workflow_dispatch` trigger.
- [x] 1.2 Include manual runs in the all-open synchronization job condition.
- [x] 1.3 Keep the per-PR job restricted to events that identify one PR.

## 2. Regression coverage

- [x] 2.1 Assert that the workflow exposes the manual trigger and routes it to
  the all-open job.

## 3. Documentation and validation

- [x] 3.1 Update the main `github-automation` specification and add this
  change-level delta.
- [x] 3.2 Run the focused workflow tests and inspect the resulting workflow
  definition before dispatching it.
