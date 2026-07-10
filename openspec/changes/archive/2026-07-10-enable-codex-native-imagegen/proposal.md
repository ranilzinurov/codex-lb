## Why

Current Codex CLI/Desktop builds expose the built-in `image_gen.imagegen` tool only for providers that are marked as Codex/OpenAI-actor compatible. The documented `codex-lb` API-key configuration does not set that marker, and even after the tool is enabled it targets `<base_url>/images/generations` or `<base_url>/images/edits`, while `codex-lb` exposes Images compatibility only under `/v1/images/*`.

## What Changes

- Add Codex-native JSON aliases for image generation and image editing under `/backend-api/codex/images/*`.
- Accept the JSON data-URL edit shape emitted by Codex's built-in image-generation extension and reuse the existing Images-to-Responses translation, routing, policy, and accounting pipeline.
- Update the supported Codex provider configuration so Codex recognizes `codex-lb` as an image-generation-capable actor-backed provider while continuing to authenticate with `CODEX_LB_API_KEY`.
- Add regression coverage for both native image generation and JSON image editing without changing the public `/v1/images/*` contracts.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `images-api-compat`: extend the existing Images compatibility surface with the Codex-native paths and request shapes used by the built-in `image_gen` tool.

## Impact

- Affected code: `app/core/openai/images.py`, `app/modules/proxy/api.py`, and image compatibility tests.
- Affected API: new `POST /backend-api/codex/images/generations` and `POST /backend-api/codex/images/edits` routes.
- Affected client setup: the Codex provider example in `README.md` requires an actor-authorization marker and environment-key authentication.
- No database migration or new external dependency is required.
