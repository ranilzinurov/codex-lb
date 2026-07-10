## ADDED Requirements

### Requirement: Codex-native provider path supports image generation

The system SHALL expose `POST /backend-api/codex/images/generations` with the JSON Images generation contract used by Codex's built-in `image_gen` extension. The route MUST apply the same authentication, model validation, routing, usage accounting, request logging, response translation, and error behavior as `POST /v1/images/generations`.

#### Scenario: Native Codex generation returns an image envelope

- **WHEN** Codex sends `POST /backend-api/codex/images/generations` with `model=gpt-image-2` and a non-empty prompt
- **THEN** the system returns the same successful JSON image envelope that the equivalent `/v1/images/generations` request would return

#### Scenario: Native Codex generation still requires API-key authorization

- **WHEN** proxy API-key authentication is enabled and Codex sends `/backend-api/codex/images/generations` without a valid Bearer key
- **THEN** the system rejects the request under the standard proxy authentication policy regardless of any actor-authorization marker

### Requirement: Codex-native provider path supports JSON image edits

The system SHALL expose `POST /backend-api/codex/images/edits` and accept the JSON edit shape emitted by Codex's built-in `image_gen` extension: common Images edit fields plus a non-empty `images` array whose entries contain base64 `data:` URLs in `image_url`. The system MUST decode the data URLs and process the request through the same validation, routing, usage accounting, request logging, response translation, and error behavior as the public multipart `/v1/images/edits` route.

#### Scenario: Native Codex JSON edit is translated through the shared pipeline

- **WHEN** Codex sends `/backend-api/codex/images/edits` with a valid image data URL, `model=gpt-image-2`, and a non-empty prompt
- **THEN** the decoded image is forwarded as `input_image` content through the existing Images-to-Responses adapter and the system returns a JSON image envelope

#### Scenario: Invalid native image data URL is rejected

- **WHEN** a native Codex edit contains a non-data URL or malformed base64 in `images[*].image_url`
- **THEN** the system returns HTTP 400 with an OpenAI `invalid_request_error` identifying the `images` parameter and does not open an upstream request

### Requirement: Codex image-generation feature marker is not upstream authorization

The supported Codex API-key provider configuration SHALL include a non-empty `x-openai-actor-authorization` header so current Codex builds expose `image_gen.imagegen`. The proxy MUST remove this downstream feature marker before constructing upstream HTTP or websocket requests, and the marker MUST NOT replace Bearer API-key authentication.

#### Scenario: Actor marker is stripped before upstream forwarding

- **WHEN** a downstream Codex request includes `x-openai-actor-authorization`
- **THEN** the upstream request does not contain that header and uses the selected account's upstream authorization instead

#### Scenario: Experimental tool catalog remains untouched

- **WHEN** the proxy returns `/backend-api/codex/models`
- **THEN** it preserves the upstream `experimental_supported_tools` value instead of injecting an `image_gen` entry
