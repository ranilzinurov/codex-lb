## MODIFIED Requirements

### Requirement: Scheduled Codex review label synchronization handles an empty selection

The scheduled Codex review label synchronization run MUST treat a successful
empty open pull-request selection from `--all-open` as a successful no-op. It
MUST preserve the existing all-open synchronization behavior when one or more
open pull requests are selected, and MUST NOT convert GitHub read, PR
classification, or write failures into a successful empty selection.

#### Scenario: Scheduled run has no open pull requests

- **GIVEN** the scheduled synchronization runs with `--all-open`
- **WHEN** the open pull-request query succeeds and returns no pull requests
- **THEN** the run exits successfully without classifying or mutating a pull request
- **AND** it emits no failure diagnostic for the empty selection
