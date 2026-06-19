## ADDED Requirements

### Requirement: Local Codex token-count logs can be uploaded

The repository SHALL provide a local operator script that reads Codex session JSONL files, extracts `token_count` events, aggregates `last_token_usage` by time bucket, model, and reasoning effort, and posts only aggregate token counts to codex-lb.

#### Scenario: Operator schedules recurring upload
- **GIVEN** the operator has a codex-lb URL, API key, account id, and source name
- **WHEN** the upload script runs periodically
- **THEN** it sends aggregate buckets without including conversation text, prompts, tool arguments, or encrypted response content
