## 1. Transient API handling

- [x] 1.1 Retry read-only GitHub API calls for HTTP `502`, `503`, and `504`
  with a bounded delay schedule.
- [x] 1.2 Keep mutation calls non-retrying and preserve the final GitHub error
  after the read retry budget is exhausted.

## 2. Regression coverage

- [x] 2.1 Verify recovery after a transient `502`, `503`, or `504` response.
- [x] 2.2 Verify that persistent transient errors still fail after the bounded
  retry budget.

## 3. Documentation and validation

- [x] 3.1 Update the main `github-automation` specification and add this
  change-level delta.
- [x] 3.2 Run focused tests, formatting, linting, type checking, and the
  original scheduled synchronization command.
