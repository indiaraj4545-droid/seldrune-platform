# LiveShell privacy and isolation boundary

The LiveShell face/voice media runtime is intentionally isolated from Seldrune's
GPT, prompt-orchestration, model-gateway, knowledge-memory, and outcome-memory
subsystems.

## Allowed state

The live transport may keep only the minimum short-lived state required to
maintain an authenticated media session, such as an opaque session identifier,
the authenticated user identifier, worker assignment, timestamps, bounded
quality-window measurements, and authorized profile references.

Uploaded video-job media is handled by the dedicated GPU worker and is subject
to the worker TTL and explicit deletion path. Live profile media is read from
the configured private profile volume; it is not copied into the GPT or
knowledge-memory systems.

## Prohibited coupling

The LiveShell media path must not:

- write prompts, chat history, transcripts, or media payloads into Seldrune GPT;
- import the model gateway or cognitive/knowledge-memory services;
- use prompt history as an input to face or voice transformation;
- persist raw live video/audio frames in the application database.

The regression test `tests/test_live_media_privacy_boundary.py` enforces the
core dependency boundary.

## Disclosure and consent

Privacy isolation does not disable the consent checks or the participant-facing
synthetic-media disclosure applied to transformed outbound video.
