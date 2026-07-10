## Context

Codex implements `image_gen.imagegen` as a local extension, not as a value in a model's `experimental_supported_tools`. Current Codex source gates the extension on the `image_generation` feature, image input modality, and a provider that either uses Codex-backed authentication or declares a non-empty `x-openai-actor-authorization` header. The extension then sends ordinary Images API requests through the active provider: `POST <base_url>/images/generations` for generation and JSON `POST <base_url>/images/edits` for editing.

The documented `codex-lb` provider uses `/backend-api/codex` as its base URL and an `sk-clb-*` API key. API-key authentication is not considered Codex-backed by the client, so the tool remains hidden. If the client-side gate is enabled, the generated URLs still miss the existing `/v1/images/*` routes, and the Codex edit request is JSON rather than OpenAI's public multipart shape.

## Goals / Non-Goals

**Goals:**

- Make the native Codex `image_gen.imagegen` extension usable through the documented `codex-lb` provider.
- Reuse the existing Images-to-Responses adapter so account routing, API-key policy, reservations, request logs, and error mapping remain consistent.
- Keep public `/v1/images/generations` and multipart `/v1/images/edits` behavior unchanged.
- Keep the client-side actor marker local to `codex-lb` instead of forwarding it to the upstream ChatGPT backend.

**Non-Goals:**

- Populate `experimental_supported_tools`; current Codex does not use that field for `image_gen` visibility.
- Add a new image model registry or bypass the existing `gpt-image-*` validation.
- Change how normal backend Codex Responses requests handle ambient `image_generation` tool advertisements.

## Decisions

### Expose Images aliases on the Codex provider base URL

Register `POST /backend-api/codex/images/generations` against the existing generation handler and add a dedicated JSON edit handler at `POST /backend-api/codex/images/edits`. This matches the URL construction in Codex while preserving the public `/v1` endpoints.

Alternative: document `base_url = .../v1`. Rejected because it changes the Codex-native Responses/model-catalog surface and loses the intended `/backend-api/codex` compatibility contract.

### Convert Codex JSON edits into the existing typed edit pipeline

Add a typed request schema for `images: [{image_url}]` plus the common image-edit fields. The route decodes each base64 data URL with the existing validated decoder, maps it to `(bytes, mime_type)`, and calls `_proxy_images_edit_request` with no mask. This keeps validation and upstream translation in one place.

Alternative: duplicate the image-edit translation in the route. Rejected because it would create a second policy/accounting path.

### Use the actor header only as a downstream Codex feature marker

The documented provider will keep its existing authentication settings and add a non-empty `x-openai-actor-authorization` entry. For API-key setups, Codex resolves `env_key = "CODEX_LB_API_KEY"` before managed OpenAI auth, while the actor marker independently enables the image-generation provider gate. `codex-lb` will remove that header at its downstream trust boundary before upstream calls. The value is not a credential and grants no server-side authorization; the Bearer API key remains authoritative.

Alternative: rely on `requires_openai_auth = true` without the marker. Rejected because an API-key login resolves to Codex `AuthMode::ApiKey`, which the current client explicitly excludes from native image generation.

## Risks / Trade-offs

- [Codex changes its private feature gate or Images request shape] -> Keep compatibility isolated to typed Codex-native routes and cover the currently emitted contract with integration tests.
- [A caller mistakes the actor marker for authentication] -> Continue requiring the standard Bearer key and document that the marker is only a client feature signal.
- [Large JSON data URLs increase request memory] -> Reuse the existing request-size limits and decode only validated base64 data URLs; no additional copy is retained after translation.
- [The marker leaks to upstream and is misinterpreted] -> Add it to the inbound-header denylist before any upstream HTTP or websocket request is built.
