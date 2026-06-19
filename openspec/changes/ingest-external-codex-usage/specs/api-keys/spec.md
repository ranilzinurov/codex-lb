## ADDED Requirements

### Requirement: External Codex usage can be attributed to an API key

The system SHALL accept authenticated external Codex token-count aggregates and persist them as synthetic request-log rows under the authenticated API key. The ingested rows MUST contain account id, model, reasoning effort, input tokens, cached input tokens, output tokens, reasoning tokens, request count, and computed cost where pricing is known.

#### Scenario: Authenticated key ingests local Codex buckets
- **GIVEN** a valid API key named `ranil` with dashboard visibility enabled
- **AND** an active account id exists
- **WHEN** the key posts external Codex usage buckets for that account
- **THEN** the system stores synthetic request-log rows with `apiKeyId` equal to that key
- **AND** dashboard attribution can include those rows as named usage for `ranil`

#### Scenario: Repeated sync is idempotent
- **GIVEN** a sync bucket was already ingested for a source, account, model, effort, and bucket start
- **WHEN** the same bucket is posted again with updated token counts
- **THEN** the previously stored synthetic row is replaced instead of duplicated
