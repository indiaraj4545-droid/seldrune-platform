# Unified model router

Seldrune's model gateway exposes one request/result contract across three
provider classes:

- `mock` for deterministic zero-cost test and fallback execution;
- `openai` for the native OpenAI Responses API, including files, images,
  reasoning controls, prompt caching, and token preflight; and
- `openai_compatible` for local or third-party OpenAI-compatible chat
  completion endpoints.

The router uses an explicit capability contract before choosing a provider.
Callers can provide ordered candidates plus required capabilities and an
optional provider allow-list. A candidate is selected only when it is both
allowed and capable. If no candidate qualifies, routing fails closed.

The compatible adapter is intentionally conservative. It supports text and
JSON-schema structured output. Image, file, and reasoning requests are rejected
before any network call so Seldrune does not silently downgrade a request onto
an endpoint whose compatibility is unknown.

Configure a compatible endpoint with:

- `SELDRUNE_MODEL_PROVIDER=openai_compatible`
- `SELDRUNE_MODEL_COMPATIBLE_BASE_URL=<endpoint>/v1`
- optional `SELDRUNE_MODEL_COMPATIBLE_API_KEY=<secret>`
- the existing model tier variables set to model identifiers available on that
  endpoint.

Agent provider policy remains authoritative because
`allowed_model_providers` is checked before invocation. Existing `mock` and
native `openai` requests keep their previous request and response contracts.
