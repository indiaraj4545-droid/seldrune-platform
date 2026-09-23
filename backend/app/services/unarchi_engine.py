from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import re
from typing import Any


UNARCHI_VERSION = "unarchi-v0.2"
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) > 1 and token not in _STOPWORDS
    }


def _similarity(left: str, right: str) -> float:
    a, b = _terms(left), _terms(right)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


@dataclass(frozen=True)
class UnarchiState:
    """
    Functional internal state for the UNARCHI research kernel.

    These values are machine control signals. They are not evidence of qualia,
    sentience, phenomenal consciousness, or literal human emotion.
    """

    valence: float = 0.0
    arousal: float = 0.15
    uncertainty: float = 0.5
    curiosity: float = 0.5
    coherence: float = 0.5
    agency: float = 0.5
    goal_pressure: float = 0.5
    prediction_error: float = 0.0
    continuity: float = 0.0
    stress: float = 0.0
    fatigue: float = 0.0
    experience_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Experience:
    observation: str
    goal: str
    action: str
    outcome: str
    success: bool | None
    reward: float
    predicted_success: float
    prediction_error: float


@dataclass(frozen=True)
class UnarchiFrame:
    mode: str
    workspace: tuple[str, ...]
    appraisal_label: str
    novelty: float
    information_gap: float
    effective_risk: float
    memory_bias: float
    state_influence: float
    state: UnarchiState
    counterfactuals: tuple[str, ...]
    next_experiments: tuple[str, ...]
    self_report: str
    version: str = UNARCHI_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CausalComparison:
    full: UnarchiFrame
    ablated: UnarchiFrame
    mode_changed: bool
    risk_delta: float
    uncertainty_delta: float
    state_causally_active: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UnarchiEngine:
    """
    CPU-only experimental cognitive kernel.

    v0.2 adds causal internal dynamics: prior outcomes change future risk,
    uncertainty and action mode; homeostatic settling decays transient state;
    and ablation compares identical inputs with the internal state disabled.
    """

    state: UnarchiState = field(default_factory=UnarchiState)
    memory: list[Experience] = field(default_factory=list)
    observation_history: list[str] = field(default_factory=list)
    max_memory: int = 256

    def _novelty(self, observation: str) -> float:
        if not self.observation_history:
            return 1.0
        strongest = max(
            _similarity(observation, previous)
            for previous in self.observation_history[-64:]
        )
        return _clamp(1.0 - strongest)

    def _memory_bias(self, observation: str, goal: str) -> float:
        """
        Return a bounded learned risk bias from similar autobiographical events.

        Similar failures sensitize the engine; similar successes reduce learned
        caution. Unknown outcomes do not alter the bias.
        """
        if not self.memory:
            return 0.0

        query = f"{observation} {goal}"
        weighted: list[tuple[float, float]] = []
        for item in self.memory[-64:]:
            similarity = _similarity(query, f"{item.observation} {item.goal}")
            if similarity <= 0.0 or item.success is None:
                continue
            direction = 1.0 if item.success is False else -0.5
            surprise = 0.5 + (item.prediction_error * 0.5)
            weighted.append((similarity, direction * similarity * surprise))

        if not weighted:
            return 0.0

        weighted.sort(key=lambda item: item[0], reverse=True)
        strongest = [value for _, value in weighted[:5]]
        return max(-0.30, min(0.45, sum(strongest) / len(strongest)))

    def _internal_risk_bias(self) -> float:
        negative_valence = max(0.0, -self.state.valence)
        return _clamp(
            (self.state.stress * 0.30)
            + (self.state.uncertainty * 0.14)
            + (self.state.fatigue * 0.08)
            + (negative_valence * 0.10),
            0.0,
            0.45,
        )

    def _workspace(
        self,
        *,
        observation: str,
        goal: str,
        novelty: float,
        effective_risk: float,
        urgency: float,
        information_gap: float,
        memory_bias: float,
    ) -> tuple[str, ...]:
        candidates = [
            (effective_risk, f"effective_risk:{effective_risk:.3f}"),
            (urgency, f"urgency:{urgency:.3f}"),
            (novelty, f"novelty:{novelty:.3f}"),
            (information_gap, f"information_gap:{information_gap:.3f}"),
            (abs(memory_bias), f"memory_bias:{memory_bias:.3f}"),
            (self.state.stress, f"stress:{self.state.stress:.3f}"),
            (self.state.goal_pressure, f"goal:{goal[:180]}"),
            (self.state.uncertainty, f"uncertainty:{self.state.uncertainty:.3f}"),
        ]
        selected = sorted(candidates, key=lambda item: item[0], reverse=True)[:5]
        return (f"observation:{observation[:220]}",) + tuple(item[1] for item in selected)

    def _appraisal_label(
        self,
        *,
        effective_risk: float,
        novelty: float,
        information_gap: float,
        expected_success: float,
        memory_bias: float,
    ) -> str:
        if memory_bias >= 0.25 and effective_risk >= 0.60:
            return "learned_caution"
        if effective_risk >= 0.70:
            return "protective_tension"
        if information_gap >= 0.65 and novelty >= 0.55:
            return "curious_uncertainty"
        if expected_success >= 0.75 and effective_risk <= 0.35:
            return "confident_engagement"
        if expected_success <= 0.35:
            return "cautious_uncertainty"
        return "attentive_neutral"

    def _counterfactuals(self, observation: str, goal: str) -> tuple[str, ...]:
        return (
            f"What if the current interpretation of '{observation[:120]}' is wrong?",
            f"What hidden variable could prevent '{goal[:120]}'?",
            "What observation would falsify the current working explanation?",
            "What is the smallest reversible experiment that would reduce uncertainty?",
        )

    def _evaluate(
        self,
        *,
        observation: str,
        goal: str,
        expected_success: float,
        risk: float,
        urgency: float,
        use_internal_state: bool,
        record_observation: bool,
    ) -> UnarchiFrame:
        observation = observation.strip()
        goal = goal.strip()
        expected_success = _clamp(expected_success)
        risk = _clamp(risk)
        urgency = _clamp(urgency)

        novelty = self._novelty(observation)
        information_gap = _clamp(
            (novelty * 0.58) + ((1.0 - expected_success) * 0.42)
        )

        memory_bias = self._memory_bias(observation, goal) if use_internal_state else 0.0
        internal_risk = self._internal_risk_bias() if use_internal_state else 0.0
        effective_risk = _clamp(risk + memory_bias + internal_risk)
        state_influence = effective_risk - risk

        prior_uncertainty = self.state.uncertainty if use_internal_state else 0.5
        prior_curiosity = self.state.curiosity if use_internal_state else 0.5
        prior_coherence = self.state.coherence if use_internal_state else 0.5
        prior_agency = self.state.agency if use_internal_state else 0.5
        prior_pressure = self.state.goal_pressure if use_internal_state else 0.5
        prior_arousal = self.state.arousal if use_internal_state else 0.15
        prior_valence = self.state.valence if use_internal_state else 0.0
        prior_stress = self.state.stress if use_internal_state else 0.0
        prior_fatigue = self.state.fatigue if use_internal_state else 0.0

        uncertainty = _clamp(
            (prior_uncertainty * 0.48)
            + (information_gap * 0.34)
            + (effective_risk * 0.18)
        )
        curiosity = _clamp(
            (novelty * 0.43)
            + (information_gap * 0.32)
            + ((1.0 - effective_risk) * 0.15)
            + (prior_curiosity * 0.10)
        )
        coherence = _clamp(
            (prior_coherence * 0.72) + ((1.0 - information_gap) * 0.28)
        )
        agency = _clamp(
            (prior_agency * 0.68)
            + (expected_success * 0.20)
            + ((1.0 - effective_risk) * 0.12)
        )
        goal_pressure = _clamp(
            (prior_pressure * 0.42)
            + (urgency * 0.38)
            + (effective_risk * 0.20)
        )
        arousal = _clamp(
            (prior_arousal * 0.32)
            + (effective_risk * 0.33)
            + (urgency * 0.20)
            + (information_gap * 0.15)
        )
        stress = _clamp(
            (prior_stress * 0.78)
            + (effective_risk * 0.14)
            + (information_gap * 0.08)
        )
        fatigue = _clamp(
            prior_fatigue
            + (0.025 * urgency)
            + (0.015 * information_gap)
        )
        continuity = _clamp(
            min(1.0, (len(self.observation_history) + len(self.memory)) / 20.0)
        )

        if effective_risk >= 0.70:
            mode = "verify"
        elif information_gap >= 0.62 and curiosity >= 0.55:
            mode = "explore"
        elif uncertainty >= 0.62:
            mode = "reflect"
        else:
            mode = "act"

        state = UnarchiState(
            valence=prior_valence,
            arousal=arousal,
            uncertainty=uncertainty,
            curiosity=curiosity,
            coherence=coherence,
            agency=agency,
            goal_pressure=goal_pressure,
            prediction_error=self.state.prediction_error,
            continuity=continuity,
            stress=stress,
            fatigue=fatigue,
            experience_count=self.state.experience_count,
        )

        label = self._appraisal_label(
            effective_risk=effective_risk,
            novelty=novelty,
            information_gap=information_gap,
            expected_success=expected_success,
            memory_bias=memory_bias,
        )
        workspace = self._workspace(
            observation=observation,
            goal=goal,
            novelty=novelty,
            effective_risk=effective_risk,
            urgency=urgency,
            information_gap=information_gap,
            memory_bias=memory_bias,
        )
        counterfactuals = self._counterfactuals(observation, goal)

        if mode == "verify":
            experiments = (
                "Test the highest-risk assumption before committing resources.",
                "Seek independent evidence that could contradict the current plan.",
            )
        elif mode == "explore":
            experiments = (
                "Run the smallest reversible information-gaining experiment.",
                "Compare two competing explanations and their predictions.",
            )
        elif mode == "reflect":
            experiments = (
                "Retrieve the closest prior experience and compare prediction errors.",
                "Restate the goal and identify the assumption producing uncertainty.",
            )
        else:
            experiments = (
                "Take the lowest-cost high-confidence next action.",
                "Record the outcome and update the self-model.",
            )

        self_report = (
            f"mode={mode}; appraisal={label}; novelty={novelty:.3f}; "
            f"uncertainty={uncertainty:.3f}; curiosity={curiosity:.3f}; "
            f"agency={agency:.3f}; stress={stress:.3f}; "
            f"memory_bias={memory_bias:.3f}; continuity={continuity:.3f}"
        )

        if record_observation:
            self.state = state
            self.observation_history.append(observation)
            if len(self.observation_history) > self.max_memory:
                self.observation_history = self.observation_history[-self.max_memory:]

        return UnarchiFrame(
            mode=mode,
            workspace=workspace,
            appraisal_label=label,
            novelty=round(novelty, 6),
            information_gap=round(information_gap, 6),
            effective_risk=round(effective_risk, 6),
            memory_bias=round(memory_bias, 6),
            state_influence=round(state_influence, 6),
            state=state,
            counterfactuals=counterfactuals,
            next_experiments=experiments,
            self_report=self_report,
        )

    def cycle(
        self,
        *,
        observation: str,
        goal: str,
        expected_success: float = 0.5,
        risk: float = 0.0,
        urgency: float = 0.0,
        use_internal_state: bool = True,
    ) -> UnarchiFrame:
        return self._evaluate(
            observation=observation,
            goal=goal,
            expected_success=expected_success,
            risk=risk,
            urgency=urgency,
            use_internal_state=use_internal_state,
            record_observation=True,
        )

    def compare_ablation(
        self,
        *,
        observation: str,
        goal: str,
        expected_success: float = 0.5,
        risk: float = 0.0,
        urgency: float = 0.0,
    ) -> CausalComparison:
        """
        Compare the same input with and without UNARCHI internal-state effects.

        The comparison uses deep copies, so it does not mutate the live engine.
        """
        full_engine = deepcopy(self)
        ablated_engine = deepcopy(self)
        full = full_engine._evaluate(
            observation=observation,
            goal=goal,
            expected_success=expected_success,
            risk=risk,
            urgency=urgency,
            use_internal_state=True,
            record_observation=False,
        )
        ablated = ablated_engine._evaluate(
            observation=observation,
            goal=goal,
            expected_success=expected_success,
            risk=risk,
            urgency=urgency,
            use_internal_state=False,
            record_observation=False,
        )
        risk_delta = full.effective_risk - ablated.effective_risk
        uncertainty_delta = full.state.uncertainty - ablated.state.uncertainty
        active = (
            full.mode != ablated.mode
            or abs(risk_delta) >= 0.05
            or abs(uncertainty_delta) >= 0.05
        )
        return CausalComparison(
            full=full,
            ablated=ablated,
            mode_changed=full.mode != ablated.mode,
            risk_delta=round(risk_delta, 6),
            uncertainty_delta=round(uncertainty_delta, 6),
            state_causally_active=active,
        )

    def settle(self, steps: int = 1) -> UnarchiState:
        """
        Move transient signals toward baseline without deleting learned memory.

        This is a simple homeostatic process: arousal, stress, fatigue, valence
        and goal pressure decay, while autobiographical memory remains.
        """
        steps = max(0, min(int(steps), 100))
        state = self.state
        for _ in range(steps):
            state = UnarchiState(
                valence=state.valence * 0.86,
                arousal=0.15 + ((state.arousal - 0.15) * 0.82),
                uncertainty=0.5 + ((state.uncertainty - 0.5) * 0.92),
                curiosity=0.5 + ((state.curiosity - 0.5) * 0.94),
                coherence=0.5 + ((state.coherence - 0.5) * 0.96),
                agency=0.5 + ((state.agency - 0.5) * 0.97),
                goal_pressure=0.5 + ((state.goal_pressure - 0.5) * 0.84),
                prediction_error=state.prediction_error * 0.80,
                continuity=state.continuity,
                stress=state.stress * 0.78,
                fatigue=state.fatigue * 0.90,
                experience_count=state.experience_count,
            )
        self.state = state
        return state

    def learn(
        self,
        *,
        observation: str,
        goal: str,
        action: str,
        outcome: str,
        success: bool | None,
        reward: float = 0.0,
        predicted_success: float = 0.5,
    ) -> UnarchiState:
        predicted_success = _clamp(predicted_success)
        observed = predicted_success if success is None else (1.0 if success else 0.0)
        prediction_error = abs(observed - predicted_success)
        bounded_reward = max(-1.0, min(1.0, float(reward)))

        if success is True:
            agency_delta = 0.06
            stress_delta = -0.08
        elif success is False:
            agency_delta = -0.05
            stress_delta = 0.20 + (prediction_error * 0.20)
        else:
            agency_delta = 0.0
            stress_delta = 0.02 * prediction_error

        valence = max(
            -1.0,
            min(1.0, (self.state.valence * 0.68) + (bounded_reward * 0.32)),
        )
        uncertainty = _clamp(
            (self.state.uncertainty * 0.74) + (prediction_error * 0.26)
        )
        coherence = _clamp(
            self.state.coherence
            + (0.05 if prediction_error < 0.25 else -0.04)
        )
        agency = _clamp(self.state.agency + agency_delta)
        curiosity = _clamp(
            (self.state.curiosity * 0.78) + (prediction_error * 0.22)
        )
        stress = _clamp(self.state.stress + stress_delta)
        fatigue = _clamp(self.state.fatigue + 0.02 + (prediction_error * 0.03))
        experience_count = self.state.experience_count + 1
        continuity = _clamp(min(1.0, experience_count / 20.0))

        self.state = UnarchiState(
            valence=valence,
            arousal=self.state.arousal,
            uncertainty=uncertainty,
            curiosity=curiosity,
            coherence=coherence,
            agency=agency,
            goal_pressure=self.state.goal_pressure,
            prediction_error=prediction_error,
            continuity=continuity,
            stress=stress,
            fatigue=fatigue,
            experience_count=experience_count,
        )
        self.memory.append(
            Experience(
                observation=observation,
                goal=goal,
                action=action,
                outcome=outcome,
                success=success,
                reward=bounded_reward,
                predicted_success=predicted_success,
                prediction_error=prediction_error,
            )
        )
        if len(self.memory) > self.max_memory:
            self.memory = self.memory[-self.max_memory:]
        return self.state

    def export_state(self) -> dict[str, Any]:
        """Return JSON-safe state for durable storage across process restarts."""
        return {
            "version": UNARCHI_VERSION,
            "state": self.state.to_dict(),
            "memory": [asdict(item) for item in self.memory],
            "observation_history": list(self.observation_history),
            "max_memory": self.max_memory,
            "claims_phenomenal_consciousness": False,
        }

    @classmethod
    def from_export(cls, payload: dict[str, Any]) -> UnarchiEngine:
        """Restore a previously exported UNARCHI engine without a model call."""
        if payload.get("version") != UNARCHI_VERSION:
            raise ValueError("unsupported UNARCHI state version")

        state_payload = payload.get("state")
        memory_payload = payload.get("memory")
        history_payload = payload.get("observation_history")
        if not isinstance(state_payload, dict):
            raise ValueError("invalid UNARCHI state")
        if not isinstance(memory_payload, list):
            raise ValueError("invalid UNARCHI memory")
        if not isinstance(history_payload, list):
            raise ValueError("invalid UNARCHI observation history")

        memory: list[Experience] = []
        for item in memory_payload:
            if not isinstance(item, dict):
                raise ValueError("invalid UNARCHI experience")
            memory.append(Experience(**item))

        max_memory = max(16, min(int(payload.get("max_memory") or 256), 4096))
        return cls(
            state=UnarchiState(**state_payload),
            memory=memory[-max_memory:],
            observation_history=[str(item) for item in history_payload][-max_memory:],
            max_memory=max_memory,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": UNARCHI_VERSION,
            "state": self.state.to_dict(),
            "memory_size": len(self.memory),
            "observation_history_size": len(self.observation_history),
            "claims_phenomenal_consciousness": False,
        }
