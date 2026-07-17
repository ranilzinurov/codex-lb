# Context

## Purpose and scope

The scheduled `Codex review labels` workflow reads GitHub pull-request,
checks, review, and workflow-run state before applying labels. A temporary
GitHub API gateway or service-unavailable response during one of those reads
must not immediately turn a healthy scheduled no-op into a failure alert.

## Decision rationale

The retry budget is deliberately small and fixed: the synchronizer makes the
initial call and at most two retries with increasing short delays. This covers
brief GitHub API interruptions while keeping a genuinely unavailable API
visible to the workflow. Mutation calls are excluded because retrying a request
whose response was lost can duplicate a comment or another non-idempotent
operation.

## Constraints and failure modes

Only HTTP `502`, `503`, and `504` are transient for this behavior. Rate-limit
fallback remains a separate token-switch path. Authentication, permission,
malformed-response, timeout, and other API errors retain their existing
failure behavior. A persistent transient response still raises `GhError` after
the retry budget is exhausted.

## Operational note

Each retry emits a warning with the delay and GitHub error so the workflow log
shows why the call was repeated. The scheduled workflow remains the source of
the user-visible alert; a successful retry produces no failure notification.
The normative contract is defined in
`openspec/specs/github-automation/spec.md`.
