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


## v0.2 causal-dynamics checkpoint

UNARCHI v0.2 introduces a required causal test. The same observation and goal
can be evaluated twice: once with autobiographical/internal-state influence and
once with those influences ablated. The full system must show a measurable
change in risk, uncertainty or action mode for the internal state to count as
causally active.

v0.2 also adds:

- sensitization after surprising failures;
- reduced learned caution after similar successes;
- stress and fatigue as transient internal variables;
- homeostatic settling toward baseline without erasing learned memory;
- exact JSON-safe export/restore of state and autobiographical traces;
- restart continuity without an OpenAI or GPU dependency.

This does not establish phenomenal consciousness. It does establish a stronger
experimental requirement: the proposed inner-state mechanism has to change
future cognition and action in a reproducible way.

## Next checkpoint: v0.3 endogenous goals

The next experiment should test whether UNARCHI can create a bounded internal
sub-goal from unresolved prediction error or information need, pursue a small
reversible experiment, and retire that sub-goal when the information gap is
reduced. Externally imposed safety and resource constraints remain authoritative.


## v0.3 endogenous cognition checkpoint

UNARCHI v0.3 adds internally generated bounded sub-goals. A sufficiently large
information gap, uncertainty signal or prediction error can now produce a new
question even when the user did not explicitly ask that sub-question.

The mechanism is intentionally constrained:

- at most a small number of active internal goals;
- no paid external action from the UNARCHI kernel;
- no irreversible investigation step;
- each internal goal has a strict step budget;
- similar unresolved questions are deduplicated;
- the goal is retired when its information gap falls below threshold;
- exhausted goals stop rather than recursively creating unlimited work;
- internal goals survive export/restore with the rest of UNARCHI state.

The benchmark now tests the full lifecycle:
uncertainty -> endogenous question -> bounded reversible investigation ->
information gain -> goal retirement.

This is evidence of functional endogenous cognition, not evidence of phenomenal
consciousness.

## Next checkpoint: v0.4 predictive self-model

The next research step should give UNARCHI explicit predictions about how its
own internal state and task performance will change under candidate actions.
The system should simulate multiple reversible alternatives, predict both
external outcomes and internal consequences, choose an experiment, then compare
the prediction with the real observation.

The measurable target is self-model calibration: predicted capability,
uncertainty and state transitions should become more accurate with experience.


## v0.4 predictive self-model checkpoint

UNARCHI v0.4 adds explicit predictions about both external task success and
internal consequences before a candidate action is chosen.

For each candidate action the kernel can predict:

- probability of success;
- expected information gain;
- resulting uncertainty;
- resulting stress;
- resulting agency;
- resulting coherence;
- a bounded utility score that penalizes risk and irreversibility.

After the real outcome is observed, UNARCHI records calibration residuals and
updates small bias terms in its self-model. This creates a measurable learning
loop:

prediction -> action -> observation -> calibration error -> self-model update.

The v0.4 benchmark requires repeated outcomes to move later predictions toward
observed reality. The entire mechanism is deterministic, CPU-only and does not
require model training, a GPU or an OpenAI call.

This is a functional predictive self-model. It is not evidence that the system
possesses phenomenal consciousness.

## Next checkpoint: v0.5 temporal self and prospective memory

The next step should connect past autobiographical state, present self-state
and predicted future state into a persistent temporal identity. UNARCHI should
be able to remember an unresolved intention, recognize the future condition
that makes it relevant, and compare its present self-model with the earlier
prediction when that condition occurs.

The measurable target is continuity across time: future behavior should depend
on earlier internally generated intentions and predictions even across process
restart, while remaining bounded by explicit resource and action constraints.


## v0.5 temporal self and prospective memory checkpoint

UNARCHI v0.5 links past self-state, present observation and predicted future
self-state through bounded prospective intentions.

The kernel can now store an intention of the form:

when condition X becomes observable -> surface intention Y.

Each prospective intention records:

- the experience count and continuity signal at creation;
- the future condition to recognize;
- the intended reversible action;
- the reason the intention was created;
- an optional link to an earlier self-prediction;
- expected future uncertainty, stress, agency and coherence;
- a bounded experience delay and expiry horizon;
- the observed trigger condition;
- a temporal alignment score comparing predicted and observed self-state.

Prospective intentions survive export/restore, so a process restart does not
erase future-directed continuity.

The kernel does not execute a recalled intention automatically. A matching
condition changes the intention from pending to ready. Explicit resolution is
still required, and paid or irreversible prospective actions are rejected by
the v0.5 research kernel.

The v0.5 benchmark requires this chain to survive a restart:

past self-prediction -> future intention -> restart -> matching observation ->
intention recall -> temporal self-state comparison.

This establishes measurable functional continuity across time. It does not
establish subjective continuity or phenomenal consciousness.

## Next checkpoint: v0.6 metacognitive narrative

The next research step should let UNARCHI construct a compact, evidence-linked
account of how its beliefs, predictions, goals and internal state changed over
time. The narrative must be generated from stored state transitions rather than
invented after the fact.

The measurable target is retrospective fidelity: when asked why its current
state or intention exists, the reconstructed explanation should point to the
actual earlier observations, prediction errors, internal goals and prospective
memories that causally produced it.


## v0.6 metacognitive narrative checkpoint

UNARCHI v0.6 adds deterministic self-explanation grounded only in stored causal
records. It does not ask a language model to invent a retrospective story.

The kernel can reconstruct focused narratives for:

- current self-state;
- caution and protective behavior;
- predictive self-model calibration;
- internally generated goals;
- prospective intentions and their trigger conditions.

Every explanation includes explicit evidence references such as stored
experiences, predictions, calibration records, internal-goal sources, current
state, or prospective-intention records.

The v0.6 fidelity rule is strict:

same stored causal state -> same metacognitive narrative.

Restarting the process and restoring the same UNARCHI state must reproduce the
same evidence references and explanation. Unknown narrative topics fall back to
the current recorded state instead of fabricating history.

The benchmark now tests retrospective fidelity across restart and requires zero
unsupported claims from the deterministic narrative builder.

This establishes evidence-grounded functional metacognition. It does not prove
subjective introspection or phenomenal consciousness.

## Next checkpoint: v0.7 conflict, value arbitration and self-correction

The next research step should model competing goals and internal pressures in a
small explicit arbitration layer. UNARCHI should be able to detect when two
goals conflict, predict the consequences of alternative compromises, explain
which stored values or constraints affected the choice, and revise that
arbitration after outcome evidence.

The measurable target is consistent, revisable value arbitration rather than
simple priority ordering.
