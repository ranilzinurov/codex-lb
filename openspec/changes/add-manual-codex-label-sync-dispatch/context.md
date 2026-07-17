# Context

## Purpose and scope

The `Codex review labels` workflow has a scheduled all-open path and event
handlers for individual pull requests. A manual dispatch is an operational
shortcut to the scheduled path: it evaluates all currently open pull requests
using the trusted default-branch script.

## Decision rationale

Manual runs intentionally reuse the existing `sync-after-ci` job and command
instead of introducing a second synchronization implementation. They do not
accept a PR number, so the `sync-pr` job remains excluded and cannot run with
an empty PR identifier.

## Constraints and failure modes

The workflow is dispatched from the default branch and uses the same token
chain, read-error tolerance, write-error tolerance, and empty-selection
behavior as scheduled runs. A manual run still fails for persistent read or
workflow errors; the trigger only changes how the run starts.

## Operational note

Run the workflow from GitHub Actions with the default branch selected, or use
`gh workflow run codex-review-labels.yml --ref main`. The run URL and job log
remain the source of truth for the result. The normative behavior is defined
in `openspec/specs/github-automation/spec.md`.
