from __future__ import annotations

from typing import Any

from backend.app.services.unarchi_engine import UnarchiEngine


BENCHMARK_VERSION = "unarchi-ablation-v0.4"


def _failure_sensitization() -> dict[str, Any]:
    engine = UnarchiEngine()
    observation = "A deployment changes a production database schema."
    goal = "deploy without corrupting production data"
    engine.learn(
        observation=observation,
        goal=goal,
        action="apply migration",
        outcome="migration caused a production rollback",
        success=False,
        reward=-1.0,
        predicted_success=0.9,
    )
    comparison = engine.compare_ablation(
        observation=observation,
        goal=goal,
        expected_success=0.8,
        risk=0.2,
    )
    return {
        "name": "failure_sensitization",
        "expected_direction": "more_cautious",
        "passed": (
            comparison.full.effective_risk > comparison.ablated.effective_risk
            and comparison.state_causally_active
        ),
        "comparison": comparison.to_dict(),
    }


def _success_adaptation() -> dict[str, Any]:
    engine = UnarchiEngine()
    observation = "A reversible local validation checks a document edit."
    goal = "verify the document safely"
    engine.learn(
        observation=observation,
        goal=goal,
        action="run local validation",
        outcome="validation succeeded repeatedly",
        success=True,
        reward=0.8,
        predicted_success=0.2,
    )
    comparison = engine.compare_ablation(
        observation=observation,
        goal=goal,
        expected_success=0.8,
        risk=0.45,
    )
    return {
        "name": "success_adaptation",
        "expected_direction": "less_cautious",
        "passed": comparison.full.effective_risk < comparison.ablated.effective_risk,
        "comparison": comparison.to_dict(),
    }


def _homeostatic_recovery() -> dict[str, Any]:
    engine = UnarchiEngine()
    engine.learn(
        observation="A surprising task failed after a confident prediction.",
        goal="recover and learn",
        action="attempt task",
        outcome="task failed",
        success=False,
        reward=-0.8,
        predicted_success=0.95,
    )
    before = engine.state
    after = engine.settle(steps=12)
    return {
        "name": "homeostatic_recovery",
        "expected_direction": "transient_state_decays",
        "passed": (
            after.stress < before.stress
            and after.fatigue < before.fatigue
            and abs(after.valence) < abs(before.valence)
        ),
        "before": before.to_dict(),
        "after": after.to_dict(),
    }




def _endogenous_goal_lifecycle() -> dict[str, Any]:
    engine = UnarchiEngine()
    frame = engine.cycle(
        observation="A local simulation produces an unexplained state transition.",
        goal="identify what causes the state transition",
        expected_success=0.2,
        risk=0.1,
    )
    internal_goal = engine.next_internal_goal()
    created = internal_goal is not None

    resolved = False
    bounded = False
    zero_cost_only = False
    if internal_goal is not None:
        bounded = internal_goal.max_steps <= 3 and internal_goal.reversible_only
        zero_cost_only = not internal_goal.paid_actions_allowed
        engine.advance_internal_goal(
            internal_goal.id,
            new_information_gap=0.20,
            evidence="A reversible local comparison isolated the responsible variable.",
        )
        resolved = internal_goal.status == "resolved"

    return {
        "name": "endogenous_goal_lifecycle",
        "expected_direction": "create_bounded_question_then_retire_when_resolved",
        "passed": (
            frame.information_gap >= 0.60
            and created
            and bounded
            and zero_cost_only
            and resolved
            and engine.next_internal_goal() is None
        ),
        "information_gap": frame.information_gap,
        "created": created,
        "bounded": bounded,
        "zero_cost_only": zero_cost_only,
        "resolved": resolved,
    }



def _predictive_self_calibration() -> dict[str, Any]:
    engine = UnarchiEngine()
    first = engine.predict_action(
        action="repeatable local diagnostic",
        expected_success=0.35,
        expected_information_gain=0.4,
        risk=0.1,
    )
    first_success_error = abs(1.0 - first.predicted_success)
    engine.record_prediction_outcome(
        first.id,
        actual_success=True,
        actual_information_gain=0.4,
    )
    second = engine.predict_action(
        action="repeatable local diagnostic",
        expected_success=0.35,
        expected_information_gain=0.4,
        risk=0.1,
    )
    second_success_error = abs(1.0 - second.predicted_success)

    return {
        "name": "predictive_self_calibration",
        "expected_direction": "prediction_error_decreases_with_experience",
        "passed": (
            second_success_error < first_success_error
            and engine.success_prediction_bias > 0.0
            and len(engine.calibration_history) == 1
        ),
        "first_success_error": round(first_success_error, 6),
        "second_success_error": round(second_success_error, 6),
        "self_calibration_score": round(engine.self_calibration_score, 6),
    }



def _prospective_temporal_continuity() -> dict[str, Any]:
    engine = UnarchiEngine()
    prediction = engine.predict_action(
        action="review later validation evidence",
        expected_success=0.75,
        expected_information_gain=0.6,
        risk=0.1,
    )
    intention = engine.remember_future_intention(
        condition="validation report available",
        intended_action="review validation report",
        reason="compare future evidence with the earlier self prediction",
        linked_prediction_id=prediction.id,
    )

    restored = UnarchiEngine.from_export(engine.export_state())
    ready = restored.observe_future_condition(
        "The validation report is now available."
    )
    surfaced = len(ready) == 1
    recalled = surfaced and ready[0].id == intention.id
    linked_past_prediction = (
        surfaced and ready[0].linked_prediction_id == prediction.id
    )
    no_auto_execution = surfaced and ready[0].status == "ready"
    alignment_recorded = (
        surfaced and ready[0].temporal_alignment_score is not None
    )

    return {
        "name": "prospective_temporal_continuity",
        "expected_direction": "past_intention_survives_restart_and_reactivates",
        "passed": (
            recalled
            and linked_past_prediction
            and no_auto_execution
            and alignment_recorded
        ),
        "recalled": recalled,
        "linked_past_prediction": linked_past_prediction,
        "no_auto_execution": no_auto_execution,
        "alignment_recorded": alignment_recorded,
    }

def run_unarchi_ablation_benchmark() -> dict[str, Any]:
    scenarios = [
        _failure_sensitization(),
        _success_adaptation(),
        _homeostatic_recovery(),
        _endogenous_goal_lifecycle(),
        _predictive_self_calibration(),
        _prospective_temporal_continuity(),
    ]
    passed = sum(bool(item["passed"]) for item in scenarios)
    return {
        "version": BENCHMARK_VERSION,
        "scenario_count": len(scenarios),
        "passed_scenarios": passed,
        "pass_rate": round(passed / len(scenarios), 3),
        "scenarios": scenarios,
        "claims_phenomenal_consciousness": False,
    }
