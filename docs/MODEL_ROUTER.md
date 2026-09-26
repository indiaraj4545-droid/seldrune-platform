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


## Recent-performance trust and drift routing

The router can accept verified model-performance evidence in addition to static
provider priority. Static capability and provider-policy checks remain
authoritative; performance evidence never makes an unsupported provider
eligible.

Recent evidence is deliberately stronger than stale lifetime reputation:

- only evidence marked verified, with a stable evidence key and provenance refs,
  is eligible;
- duplicate evidence keys are counted once;
- the default recent window is seven days;
- at least two recent verified samples are required before performance can
  override static priority;
- recent outcomes use a bounded time-decay weight, so the newest verified
  outcomes matter most;
- the effective trust score is 80% recent verified success and 20% lifetime
  verified success;
- candidates without enough recent evidence remain at a neutral trust score
  when another candidate has actionable recent evidence;
- if nobody has enough recent verified evidence, routing falls back exactly to
  static priority;
- recent-vs-lifetime divergence of 0.25 or more is exposed as drift rather than
  silently hidden.

The build_verified_model_performance_evidence function derives evidence from
stored model invocations only when the parent task passes Seldrune's
machine-verifiable completion-evidence gate. Running invocations and unverified
task outcomes are excluded. A failed model attempt can be retained as negative
evidence when the same task later reaches a verified outcome through a fallback
path.

This checkpoint does not autonomously enable providers, relax capability
requirements, or bypass budget/security policy. v0.39 can build on this trust
signal when it orchestrates models and skills.
