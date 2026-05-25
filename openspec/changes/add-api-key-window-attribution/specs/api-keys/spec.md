## ADDED Requirements

### Requirement: Account quota-window usage is attributable to API keys by local request logs

The system SHALL expose dashboard account-window attribution rows that estimate which API keys contributed to an account's current primary and secondary quota-window consumption. Attribution MUST be derived from local `request_logs` rows grouped by `account_id`, `api_key_id`, and the relevant quota window. The response MUST label attribution as estimated because upstream account usage snapshots do not provide per-API-key credit deltas.

Each attribution row SHALL include the account id, window key, API key id/name/prefix when available, request count, total tokens, cached input tokens, total cost, attributed credits, share percent, and flags for estimated/unattributed rows.

#### Scenario: API key activity contributes to a window attribution row
- **GIVEN** an account has current primary-window usage
- **AND** request logs inside that account's primary window include rows for API key `aidar`
- **WHEN** the dashboard overview is loaded
- **THEN** the response includes a primary-window attribution row for `aidar`
- **AND** the row includes request, token, cost, attributed credit, and share-percent values
- **AND** the row has `estimated = true`

#### Scenario: Unattributed consumed credits are preserved
- **GIVEN** an account's upstream usage snapshot reports consumed credits
- **AND** local request logs explain only part of that consumption
- **WHEN** the dashboard overview is loaded
- **THEN** the response includes an unattributed row for the unexplained consumed credits
- **AND** that row has `apiKeyId = null`, `unattributed = true`, and `estimated = true`

#### Scenario: Empty request logs do not hide account consumption
- **GIVEN** an account has non-zero current usage
- **AND** there are no request logs inside the quota window
- **WHEN** the dashboard overview is loaded
- **THEN** the response includes only an unattributed row for that account window

#### Scenario: Attribution remains additive to existing API contracts
- **WHEN** clients load existing API key or dashboard endpoints
- **THEN** all previously existing response fields remain present and keep their existing meaning
