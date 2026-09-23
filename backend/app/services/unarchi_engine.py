from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


UNARCHI_VERSION = "unarchi-v0.1"
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "with",
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
    Internal machine-state signals used by the UNARCHI research kernel.

    These variables are functional signals, not evidence that the software has
    phenomenal consciousness, qualia or literal human emotions.
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
    state: UnarchiState
    counterfactuals: tuple[str, ...]
    next_experiments: tuple[str, ...]
    self_report: str
    version: str = UNARCHI_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UnarchiEngine:
    """
    CPU-only experimental cognitive kernel.

    The loop models five functional properties that can be tested cheaply:
    persistent internal state, self-relevance appraisal, global-workspace-like
    competition, counterfactual imagination and prediction-error learning.
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

    def _workspace(
        self,
        *,
        observation: str,
        goal: str,
        novelty: float,
        risk: float,
        urgency: float,
        information_gap: float,
    ) -> tuple[str, ...]:
        candidates = [
            (risk, f"risk:{risk:.3f}"),
            (urgency, f"urgency:{urgency:.3f}"),
            (novelty, f"novelty:{novelty:.3f}"),
            (information_gap, f"information_gap:{information_gap:.3f}"),
            (self.state.goal_pressure, f"goal:{goal[:180]}"),
            (self.state.uncertainty, f"uncertainty:{self.state.uncertainty:.3f}"),
        ]
        selected = sorted(candidates, key=lambda item: item[0], reverse=True)[:4]
        return (f"observation:{observation[:220]}",) + tuple(item[1] for item in selected)

    def _appraisal_label(
        self,
        *,
        risk: float,
        novelty: float,
        information_gap: float,
        expected_success: float,
    ) -> str:
        if risk >= 0.70:
            return "protective_tension"
        if information_gap >= 0.65 and novelty >= 0.55:
            return "curious_uncertainty"
        if expected_success >= 0.75 and risk <= 0.35:
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

    def cycle(
        self,
        *,
        observation: str,
        goal: str,
        expected_success: float = 0.5,
        risk: float = 0.0,
        urgency: float = 0.0,
    ) -> UnarchiFrame:
        observation = observation.strip()
        goal = goal.strip()
        expected_success = _clamp(expected_success)
        risk = _clamp(risk)
        urgency = _clamp(urgency)
        novelty = self._novelty(observation)
        information_gap = _clamp((novelty * 0.58) + ((1.0 - expected_success) * 0.42))

        uncertainty = _clamp(
            (self.state.uncertainty * 0.48)
            + (information_gap * 0.42)
            + (risk * 0.10)
        )
        curiosity = _clamp(
            (novelty * 0.48)
            + (information_gap * 0.37)
            + ((1.0 - risk) * 0.15)
        )
        coherence = _clamp(
            (self.state.coherence * 0.72)
            + ((1.0 - information_gap) * 0.28)
        )
        agency = _clamp(
            (self.state.agency * 0.70)
            + (expected_success * 0.20)
            + ((1.0 - risk) * 0.10)
        )
        goal_pressure = _clamp(
            (self.state.goal_pressure * 0.42)
            + (urgency * 0.43)
            + (risk * 0.15)
        )
        arousal = _clamp(
            (self.state.arousal * 0.35)
            + (risk * 0.30)
            + (urgency * 0.20)
            + (information_gap * 0.15)
        )
        continuity = _clamp(
            min(1.0, (len(self.observation_history) + len(self.memory)) / 20.0)
        )

        if risk >= 0.70:
            mode = "verify"
        elif information_gap >= 0.62 and curiosity >= 0.58:
            mode = "explore"
        elif uncertainty >= 0.62:
            mode = "reflect"
        else:
            mode = "act"

        state = UnarchiState(
            valence=self.state.valence,
            arousal=arousal,
            uncertainty=uncertainty,
            curiosity=curiosity,
            coherence=coherence,
            agency=agency,
            goal_pressure=goal_pressure,
            prediction_error=self.state.prediction_error,
            continuity=continuity,
            experience_count=self.state.experience_count,
        )
        self.state = state
        self.observation_history.append(observation)
        if len(self.observation_history) > self.max_memory:
            self.observation_history = self.observation_history[-self.max_memory:]

        label = self._appraisal_label(
            risk=risk,
            novelty=novelty,
            information_gap=information_gap,
            expected_success=expected_success,
        )
        workspace = self._workspace(
            observation=observation,
            goal=goal,
            novelty=novelty,
            risk=risk,
            urgency=urgency,
            information_gap=information_gap,
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
            f"agency={agency:.3f}; continuity={continuity:.3f}"
        )
        return UnarchiFrame(
            mode=mode,
            workspace=workspace,
            appraisal_label=label,
            novelty=round(novelty, 6),
            information_gap=round(information_gap, 6),
            state=state,
            counterfactuals=counterfactuals,
            next_experiments=experiments,
            self_report=self_report,
        )

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
        elif success is False:
            agency_delta = -0.05
        else:
            agency_delta = 0.0

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

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": UNARCHI_VERSION,
            "state": self.state.to_dict(),
            "memory_size": len(self.memory),
            "observation_history_size": len(self.observation_history),
            "claims_phenomenal_consciousness": False,
        }
