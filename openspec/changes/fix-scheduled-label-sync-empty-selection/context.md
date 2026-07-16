# Context

## Purpose and scope

The scheduled `Codex review labels` workflow periodically evaluates all open
pull requests. A repository with no open pull requests is a valid maintenance
state and needs no per-PR synchronization work.

## Decision rationale

The empty-selection branch is successful only when `--all-open` is active. An
explicit invocation without `--pr` or `--all-open` remains invalid, so the
script does not hide caller mistakes. The existing per-PR loop is unchanged.

## Constraints and failure modes

An empty list returned by a successful GitHub query is different from a
failure while reading that list. The latter must still terminate the workflow
with an error. Classification failures, write failures, and the established
all-read-error guard retain their existing behavior.

## Operational note

The scheduled job can report a successful no-op on standard output, which
keeps the workflow log informative without emitting a failure diagnostic.
The normative behavior is defined in
`openspec/specs/github-automation/spec.md`.
