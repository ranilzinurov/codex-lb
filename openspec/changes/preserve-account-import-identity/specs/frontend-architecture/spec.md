### Requirement: Account Import Preserves Upstream Identity

Account import and OAuth completion MUST update an existing local account when
the incoming auth payload has the same `chatgpt_account_id`, real email, and
workspace slot as a stored row, even when import-without-overwrite mode is
enabled. Different workspace slots remain separate rows.

#### Scenario: Same upstream account re-import does not create a local copy

- **GIVEN** import-without-overwrite mode is enabled
- **AND** an existing account has `chatgpt_account_id=acc_same`, the same real email, and the same workspace slot
- **WHEN** an auth payload for that credential slot is imported again
- **THEN** the import response references the existing local account id
- **AND** no `__copy` account is created for that upstream account

#### Scenario: Different upstream accounts with one email stay separate

- **GIVEN** import-without-overwrite mode is enabled
- **AND** an existing account has email `shared@example.com` and `chatgpt_account_id=acc_a`
- **WHEN** an auth payload for email `shared@example.com` and `chatgpt_account_id=acc_b` is imported
- **THEN** the service creates a separate local account for `acc_b`
