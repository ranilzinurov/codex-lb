## ADDED Requirements

### Requirement: Codex review label sync retries transient GitHub read failures

The Codex label synchronization script MUST retry read-only GitHub API calls
that fail with HTTP `502`, `503`, or `504` using a bounded retry budget and
delay schedule. It MUST preserve the original error when the retry budget is
exhausted, and it MUST NOT automatically retry mutation calls whose outcome
could be duplicated.

#### Scenario: Transient GitHub API failure recovers during the retry budget

- **GIVEN** a read-only GitHub API call returns HTTP `503`
- **WHEN** a subsequent retry returns successfully
- **THEN** the synchronization continues with the successful response
- **AND** the workflow does not fail because of the transient response

#### Scenario: Persistent GitHub API failure exhausts the retry budget

- **GIVEN** a read-only GitHub API call returns HTTP `502`, `503`, or `504` on every attempt
- **WHEN** the bounded retry budget is exhausted
- **THEN** the synchronization fails with the GitHub API error

#### Scenario: GitHub mutation failure is not replayed automatically

- **GIVEN** a label, comment, or workflow-run approval mutation returns HTTP `502`, `503`, or `504`
- **WHEN** the mutation call fails
- **THEN** the synchronization reports the error without replaying the mutation
