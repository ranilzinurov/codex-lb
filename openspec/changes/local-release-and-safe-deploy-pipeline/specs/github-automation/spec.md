# github-automation Delta

## MODIFIED Requirements

### Requirement: CI required check contexts remain stable under path filtering

The CI workflow SHALL create every branch-protection-required check context for
pull requests, merge queue events, and pushes to `main` even when path filters
determine that the expensive implementation for a subsystem is unrelated to
the change. Path filtering SHALL apply to pushes to `main` as well as pull
requests. An explicit full-suite run and changes to dependencies, migrations,
Docker/runtime, shared contracts, or upstream synchronization SHALL run the
real complete implementations instead of placeholders.

#### Scenario: non-backend pull request still creates pytest matrix contexts

- **GIVEN** a pull request changes no backend paths
- **AND** the repository ruleset requires `Tests (pytest, unit)`, `Tests (pytest, integration-core)`, `Tests (pytest, integration-bridge)`, and `Tests (pytest, e2e)`
- **WHEN** the CI workflow runs
- **THEN** each required pytest matrix check context is created
- **AND** each context completes successfully via a placeholder step
- **AND** the real pytest setup and test commands are skipped for that non-backend change

#### Scenario: backend pull request runs the real pytest slices

- **GIVEN** a pull request changes backend paths
- **WHEN** the CI workflow runs
- **THEN** each required pytest matrix check context runs its corresponding `make test-*` target
- **AND** the placeholder step is skipped

#### Scenario: deploy-only push to main skips unrelated expensive suites

- **GIVEN** a push to `main` changes only single-host deploy code and its tests
- **WHEN** the CI workflow runs
- **THEN** all required check contexts are created
- **AND** deploy-related checks execute their real commands
- **AND** unrelated full frontend and backend commands use successful placeholders

#### Scenario: explicit full-suite run executes every implementation

- **GIVEN** an operator starts the CI workflow with the full-suite option
- **WHEN** change detection completes
- **THEN** every required test implementation runs for that exact SHA
- **AND** no expensive suite is replaced by a path-filter placeholder

#### Scenario: runtime change on main forces the full suite

- **GIVEN** a push to `main` changes Docker/runtime, dependencies, migrations, shared contracts, or upstream synchronization metadata
- **WHEN** the CI workflow runs
- **THEN** the complete required suite runs for the pushed SHA
