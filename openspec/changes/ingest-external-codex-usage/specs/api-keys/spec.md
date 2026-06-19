## ADDED Requirements

### Requirement: External Codex usage can be attributed to an API key

The system SHALL accept authenticated external Codex token-count aggregates and persist them as synthetic request-log rows under the authenticated API key. The ingested rows MUST contain account id, model, reasoning effort, input tokens, cached input tokens, output tokens, reasoning tokens, request count, and computed cost where pricing is known.

#### Scenario: Authenticated key ingests local Codex buckets
- **GIVEN** a valid API key named `ranil` with dashboard visibility enabled
- **AND** an active account id exists
- **WHEN** the key posts external Codex usage buckets for that account
- **THEN** the system stores synthetic request-log rows with `apiKeyId` equal to that key
- **AND** dashboard attribution can include those rows as named usage for `ranil`

#### Scenario: External Codex usage only contributes to weekly attribution
- **GIVEN** a visible API key has synthetic external Codex usage rows in the current quota period
- **WHEN** the dashboard builds 5-hour and weekly API-key attribution
- **THEN** weekly attribution includes the external Codex rows under that API key
- **AND** 5-hour attribution excludes those external Codex rows

#### Scenario: Attribution uses the current quota reset window
- **GIVEN** a latest usage row has a reset timestamp and window length
- **WHEN** dashboard attribution aggregates request logs for that account
- **THEN** only request logs at or after `reset_at - window_length` contribute to that attribution window
- **AND** older request logs do not appear as named or unattributed usage for the current window

#### Scenario: Repeated sync is idempotent
- **GIVEN** a sync bucket was already ingested for a source, account, model, effort, and bucket start
- **WHEN** the same bucket is posted again with updated token counts
- **THEN** the previously stored synthetic row is replaced instead of duplicated
