## ADDED Requirements

### Requirement: Usage refresh ignores non-primary long primary windows

The system MUST NOT persist upstream `primary_window` quota rows whose reported limit window is longer than the weekly quota window. Latest primary usage selection MUST prefer semantic primary rows whose window length is absent, 5 hours, or the known weekly fallback over newer non-semantic long-window rows.

#### Scenario: Long primary window is ignored during refresh
- **GIVEN** upstream usage refresh returns a `primary_window` longer than seven days
- **AND** the payload also contains a weekly `secondary_window`
- **WHEN** usage refresh stores quota history
- **THEN** the long primary window is not written as primary usage
- **AND** the weekly secondary window is still written

#### Scenario: Latest primary usage ignores a newer long-window row
- **GIVEN** an account has an older 5-hour primary usage row
- **AND** a newer primary usage row with a long non-semantic window length
- **WHEN** the system reads latest primary usage for dashboard capacity
- **THEN** it uses the 5-hour primary row

### Requirement: Usage refresh preserves paid plans on free payload downgrades

The system MUST preserve an existing paid account plan when a usage refresh payload reports `plan_type: free`, because usage payloads can report free while the quota windows still represent a paid ChatGPT account.

#### Scenario: Paid plan survives free usage payload
- **GIVEN** an account is stored with a paid plan type
- **WHEN** usage refresh receives a successful payload whose plan type is `free`
- **THEN** the stored paid plan type is not downgraded
- **AND** quota rows from the successful payload may still be stored
