## 1. Contracts and regression coverage

- [x] 1.1 Add typed Codex JSON image-edit request models with a required non-empty image data-URL list
- [x] 1.2 Add failing integration coverage for `/backend-api/codex/images/generations` and JSON `/backend-api/codex/images/edits`
- [x] 1.3 Add unit coverage proving the downstream actor marker is removed from upstream headers

## 2. Codex-native Images implementation

- [x] 2.1 Register the Codex-native generation alias on the shared generation handler
- [x] 2.2 Decode Codex JSON edit images and route them through the existing image-edit pipeline
- [x] 2.3 Strip `x-openai-actor-authorization` at the downstream proxy boundary

## 3. Documentation and verification

- [x] 3.1 Update the Codex provider configuration and Images compatibility context with the native image-generation flow
- [x] 3.2 Run targeted unit and integration tests plus type/lint checks for touched code
- [x] 3.3 Validate OpenSpec artifacts and verify the implementation against the change
