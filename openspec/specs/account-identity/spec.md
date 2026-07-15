# account-identity Specification

## Purpose
Define how imported and OAuth-completed credentials map to stable local account
rows without collapsing distinct email or workspace slots.
## Requirements
### Requirement: Shared upstream workspace identities preserve account slots

The account import and OAuth add-account flows MUST preserve separate local account slots for different real email addresses even when the upstream token reports the same ChatGPT account id, with or without a workspace id.

Dashboard account summaries MUST expose and render the upstream ChatGPT account id as the primary workspace/account-slot context before falling back to optional workspace metadata or a generic unknown-workspace label.

#### Scenario: Shared workspace account ids preserve separate emails
- **GIVEN** two account credentials have different real email addresses
- **AND** both credentials report the same upstream ChatGPT account id
- **WHEN** the operator imports or adds both accounts through OAuth
- **THEN** the system persists separate local account slots for each email
- **AND** the second account does not overwrite the first account's stored email or tokens

#### Scenario: Workspace context uses ChatGPT account id
- **GIVEN** an account has a ChatGPT account id
- **WHEN** the dashboard renders the account workspace context
- **THEN** it displays the ChatGPT account id
- **AND** it does not display the generic unknown-workspace label

### Requirement: Re-import preserves an existing credential slot

Account import and OAuth completion MUST update the existing local row when the
incoming credential has the same ChatGPT account id, real email, and workspace
slot. This identity rule applies when import-without-overwrite mode is enabled,
so repeated authentication does not detach request logs, usage history, API-key
attribution, or external Codex usage from the active account.

Different real emails or different workspace ids/labels MUST remain separate
local account slots even when their upstream ChatGPT account id is shared.

#### Scenario: Same credential slot is imported again

- **GIVEN** import-without-overwrite mode is enabled
- **AND** an existing account has a ChatGPT account id, email, and workspace slot
- **WHEN** a credential with the same identity tuple is imported again
- **THEN** the service updates the existing local account row and its tokens
- **AND** it does not create an `__copy` row

#### Scenario: Shared upstream identity has different workspace slots

- **GIVEN** two credentials share a ChatGPT account id and email
- **AND** their workspace ids or workspace labels differ
- **WHEN** both credentials are imported
- **THEN** the service preserves two local account rows
