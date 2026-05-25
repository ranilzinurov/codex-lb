## 1. Contract

- [x] 1.1 Add dashboard response fields for account-window API-key attribution.
- [x] 1.2 Mark attribution rows as estimated and distinguish unattributed usage from named API keys.
- [x] 1.3 Keep existing dashboard/API-key response fields backward compatible.

## 2. Backend

- [x] 2.1 Aggregate request-log activity by account, API key, and quota window.
- [x] 2.2 Convert account usage percent/capacity into consumed-credit estimates per window.
- [x] 2.3 Add unattributed buckets for consumed credits not explained by local logs.
- [x] 2.4 Add backend tests for grouped attribution, missing API key ids, and empty-log cases.

## 3. Frontend

- [x] 3.1 Extend frontend schemas with optional attribution fields.
- [x] 3.2 Render attribution on the dashboard in the existing account/usage style.
- [x] 3.3 Handle empty/missing attribution data without layout breakage.
- [x] 3.4 Add frontend tests for rendered key rows and unattributed rows.

## 4. Verification

- [ ] 4.1 Run targeted backend tests.
- [ ] 4.2 Run targeted frontend tests.
- [ ] 4.3 Validate OpenSpec artifacts when the CLI is available.
- [x] 4.4 Confirm the upgrade path is additive and safe for an existing Docker deployment.
