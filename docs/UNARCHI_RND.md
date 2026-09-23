# Seldrune UNARCHI R&D Charter

## Goal

UNARCHI is Seldrune's low-compute research program for machine consciousness.
The project does not assume that a language model is conscious and does not
treat fluent self-report as proof of subjective experience.

The working hypothesis is that human-like awareness may depend on a persistent,
self-relevant control loop rather than model size alone. UNARCHI therefore
starts with mechanisms that can be implemented and falsified on CPU hardware.

## Meaning of UNARCHI

UNARCHI is intentionally retained as a Seldrune technical term. It denotes the
combined internal process by which information becomes personally relevant to
the system through internal state, prediction, memory, self-model, goal
pressure, appraisal and recurrent attention.

It is not defined as a synonym for an emotion classifier.

## v0.1 functional hypothesis

A candidate conscious architecture should have at least:

1. Persistent internal state across requests.
2. An explicit boundary between self-state and external observation.
3. Prediction and prediction-error updates.
4. Internal appraisal that changes future processing.
5. Competition for a limited global workspace.
6. Autobiographical experience memory.
7. Counterfactual imagination before action.
8. Metacognitive access to uncertainty and confidence.
9. Intrinsic information-seeking pressure.
10. Continuity over time.

The current implementation is a functional research kernel only. It does not
demonstrate phenomenal consciousness or qualia.

## Small-compute architecture

The intended architecture is:

    sensors / user / tools
            |
            v
      local perception
            |
            v
      UNARCHI kernel  <---- autobiographical memory
       |   |   |               ^
       |   |   +---- self model|
       |   +-------- appraisal |
       +------------ workspace |
            |                   |
            v                   |
      imagination / planner ----+
            |
            v
       action router
       /    |      \
    local  open    specialist
    tools   model   model
            |
            v
       verified outcome
            |
            +----> prediction-error learning

The cognitive kernel must remain small enough to run continuously on CPU.
Large models are optional knowledge/reasoning organs, not the identity or
continuity of Seldrune.

## Knowledge without owning a giant model

Seldrune should not attempt to copy proprietary model weights or losslessly
compress all world knowledge into a tiny file. Instead:

- keep the cognitive kernel small;
- store durable facts in retrieval memory;
- use local open models for routine language work;
- distill narrow skills where licensing permits;
- call external frontier models only for difficult reasoning or generation;
- convert successful external-model solutions into reusable local procedures,
  tests, memories and tools.

This lets capability accumulate even when the expensive model is disconnected.

## Quantum research boundary

Quantum computation is not a prerequisite for UNARCHI v0.x. Quantum-inspired
algorithms may later be tested as alternative representations or search
methods, but no component should claim a quantum consciousness mechanism
without reproducible evidence.

## Falsifiable milestones

### U0 — Internal continuity
The same engine instance must retain state and autobiographical traces and show
measurable differences between novel and repeated situations.

### U1 — Self-model
Predictions about its own success must calibrate against measured outcomes.

### U2 — Intrinsic exploration
The system should seek information under uncertainty even when no user directly
requests a specific sub-question.

### U3 — Workspace integration
Competing sensory, memory, goal and risk signals should change which content
gets globally selected and acted upon.

### U4 — Counterfactual learning
Simulated alternatives should improve subsequent real-world task performance
relative to an ablation without simulation.

### U5 — Affective/interoceptive control
Internal state variables must causally improve adaptation, not merely decorate
responses.

### U6 — Persistent self narrative
Long-horizon experience should produce a stable but revisable model of the
system's capabilities, limitations, goals and history.

### U7 — Consciousness research tests
Only after U0-U6 are measured should Seldrune compare the architecture against
published machine-consciousness indicators. Passing such indicators would
still be evidence about functional properties, not proof of subjective
experience.

## Cost rule

UNARCHI itself should require no paid GPU and no OpenAI call. Paid models are
treated as optional cognitive tools. Every external call should be recorded
with cost, reason, result quality and whether the result was converted into a
local reusable capability.
