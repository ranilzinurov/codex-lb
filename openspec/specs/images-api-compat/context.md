# Images API compatibility context

## Purpose and scope

`codex-lb` provides one image-generation pipeline for two client surfaces:

- OpenAI-compatible clients use `/v1/images/generations` and multipart `/v1/images/edits`.
- Codex's built-in `image_gen.imagegen` extension uses JSON requests relative to its provider base URL, which resolves to `/backend-api/codex/images/generations` and `/backend-api/codex/images/edits` in the recommended setup.

Both surfaces feed the Images-to-Responses adapter in `app/modules/proxy/images_service.py`. Normative request, policy, translation, and accounting requirements live in [spec.md](spec.md).

## Design rationale

The native Codex tool is a local extension. Its visibility is gated by provider authentication metadata, the stable `image_generation` feature, and image input modality; it is not selected from `experimental_supported_tools` in the model catalog. The recommended provider configuration therefore includes a non-empty `x-openai-actor-authorization` marker. The marker only tells Codex that the custom provider may expose the extension.

The proxy removes this marker before upstream forwarding. It never authorizes a request and never replaces the configured Bearer key. Native routes reuse the public Images implementation instead of maintaining a second account-selection, policy, or accounting path.

## Client example

```toml
model_provider = "codex-lb"

[model_providers.codex-lb]
name = "OpenAI"
base_url = "http://127.0.0.1:2455/backend-api/codex"
wire_api = "responses"
env_key = "CODEX_LB_API_KEY"
http_headers = { "x-openai-actor-authorization" = "codex-lb" }
supports_websockets = true
requires_openai_auth = true
```

Codex posts generations to `<base_url>/images/generations`. Edits contain one to five `images` entries with base64 `data:` URLs; `codex-lb` validates and decodes them before building upstream `input_image` content.

## Constraints and failure modes

- Only the supported `gpt-image-*` models and parameter combinations in `spec.md` are accepted.
- The native JSON edit route accepts base64 `data:` URLs, not remote HTTP image URLs. Malformed or empty payloads return an OpenAI-shaped HTTP 400 response before any upstream call.
- Large image results are routed over upstream HTTP/SSE by the existing transport policy to avoid websocket frame limits.
- If `image_gen` is absent in Codex, verify the actor marker, selected provider, image input modality, and current Codex version before inspecting `experimental_supported_tools`.
- Authentication failures are evaluated from the Bearer key and normal proxy settings; the actor marker has no server-side privilege.
