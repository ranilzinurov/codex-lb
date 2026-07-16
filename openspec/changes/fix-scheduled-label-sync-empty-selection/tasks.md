## 1. Empty selection handling

- [x] 1.1 Treat a valid empty `--all-open` pull-request selection as a
  successful no-op.
- [x] 1.2 Keep explicit-selection and GitHub error paths failing as before.

## 2. Regression coverage

- [x] 2.1 Add a regression test for a scheduled-style `--all-open` run with no
  open pull requests.
- [x] 2.2 Preserve coverage for partial classification errors, all-read-error
  runs, and write failures.

## 3. Documentation and validation

- [x] 3.1 Update the main `github-automation` specification with the empty
  selection scenario.
- [x] 3.2 Run the focused tests, `ruff`, `ty`, and the full Python test suite.
