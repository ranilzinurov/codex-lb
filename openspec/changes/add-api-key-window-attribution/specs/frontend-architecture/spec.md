## ADDED Requirements

### Requirement: Dashboard shows per-API-key account-window attribution

The dashboard SHALL render account-window API-key attribution in the same visual language as account quota bars and API-key usage sections. The UI MUST make clear that rows are estimated from local request logs and MUST distinguish named API keys from unattributed usage.

#### Scenario: Account card exposes key attribution for quota windows
- **WHEN** an account has attribution rows for its 5h or weekly quota window
- **THEN** the dashboard shows a compact breakdown for that account using API key names and percentages
- **AND** the layout remains stable when both windows are present

#### Scenario: Unattributed usage is visible
- **WHEN** an account-window attribution payload contains an unattributed row
- **THEN** the dashboard renders it with an explicit unattributed label instead of hiding it

#### Scenario: Missing attribution data is safe
- **WHEN** the dashboard overview response omits attribution data or returns an empty array
- **THEN** the dashboard still renders the existing overview, usage donuts, account cards, and request logs without errors
