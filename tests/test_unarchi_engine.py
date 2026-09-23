from backend.app.services.unarchi_engine import UnarchiEngine


def test_first_novel_observation_prefers_exploration() -> None:
    engine = UnarchiEngine()

    frame = engine.cycle(
        observation="A new mechanism behaves differently from every stored example.",
        goal="discover the mechanism",
        expected_success=0.35,
        risk=0.1,
    )

    assert frame.novelty == 1.0
    assert frame.mode == "explore"
    assert frame.appraisal_label == "curious_uncertainty"
    assert frame.counterfactuals
    assert frame.workspace[0].startswith("observation:")


def test_repeated_observation_reduces_novelty() -> None:
    engine = UnarchiEngine()
    text = "The same sensor pattern repeats with no meaningful change."

    first = engine.cycle(observation=text, goal="understand the pattern")
    second = engine.cycle(observation=text, goal="understand the pattern")

    assert first.novelty == 1.0
    assert second.novelty == 0.0


def test_high_risk_forces_verification_mode() -> None:
    engine = UnarchiEngine()

    frame = engine.cycle(
        observation="A proposed action can irreversibly delete important data.",
        goal="complete the task safely",
        expected_success=0.95,
        risk=0.95,
        urgency=0.8,
    )

    assert frame.mode == "verify"
    assert frame.effective_risk >= 0.70
    assert "highest-risk" in frame.next_experiments[0]


def test_learning_updates_prediction_error_and_continuity() -> None:
    engine = UnarchiEngine()
    before = engine.state

    after = engine.learn(
        observation="A low-cost experiment was attempted.",
        goal="learn whether the hypothesis holds",
        action="run experiment",
        outcome="experiment succeeded",
        success=True,
        reward=0.8,
        predicted_success=0.4,
    )

    assert after.experience_count == before.experience_count + 1
    assert after.prediction_error == 0.6
    assert after.valence > before.valence
    assert after.agency > before.agency
    assert after.continuity > before.continuity
    assert len(engine.memory) == 1


def test_similar_failure_sensitizes_future_decision() -> None:
    engine = UnarchiEngine()
    observation = "A database migration may overwrite customer records."
    goal = "migrate the database safely"

    engine.learn(
        observation=observation,
        goal=goal,
        action="run migration",
        outcome="records were corrupted",
        success=False,
        reward=-1.0,
        predicted_success=0.9,
    )

    frame = engine.cycle(
        observation=observation,
        goal=goal,
        expected_success=0.8,
        risk=0.2,
    )

    assert frame.memory_bias > 0.25
    assert frame.state.stress > 0.0
    assert frame.effective_risk >= 0.70
    assert frame.mode == "verify"
    assert frame.appraisal_label == "learned_caution"


def test_ablation_proves_internal_state_can_change_mode() -> None:
    engine = UnarchiEngine()
    observation = "A database migration may overwrite customer records."
    goal = "migrate the database safely"

    engine.learn(
        observation=observation,
        goal=goal,
        action="run migration",
        outcome="records were corrupted",
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

    assert comparison.full.mode == "verify"
    assert comparison.ablated.mode != "verify"
    assert comparison.mode_changed is True
    assert comparison.risk_delta >= 0.30
    assert comparison.state_causally_active is True


def test_homeostatic_settling_reduces_transient_stress() -> None:
    engine = UnarchiEngine()
    engine.learn(
        observation="An unexpected deployment failure occurred.",
        goal="restore service",
        action="deploy",
        outcome="deployment failed",
        success=False,
        reward=-0.8,
        predicted_success=0.95,
    )
    before = engine.state

    after = engine.settle(steps=8)

    assert after.stress < before.stress
    assert after.fatigue < before.fatigue
    assert abs(after.valence) < abs(before.valence)
    assert after.experience_count == before.experience_count
    assert len(engine.memory) == 1


def test_ablation_comparison_does_not_mutate_live_engine() -> None:
    engine = UnarchiEngine()
    before = engine.snapshot()

    engine.compare_ablation(
        observation="A novel observation appears.",
        goal="understand it",
        expected_success=0.4,
        risk=0.1,
    )

    assert engine.snapshot() == before


def test_snapshot_never_claims_phenomenal_consciousness() -> None:
    engine = UnarchiEngine()

    snapshot = engine.snapshot()

    assert snapshot["claims_phenomenal_consciousness"] is False
    assert snapshot["version"] == "unarchi-v0.4"


def test_export_restore_preserves_identity_state_and_memory() -> None:
    engine = UnarchiEngine()
    engine.cycle(
        observation="A new research hypothesis appears.",
        goal="test the hypothesis cheaply",
        expected_success=0.45,
        risk=0.2,
    )
    engine.learn(
        observation="A new research hypothesis appears.",
        goal="test the hypothesis cheaply",
        action="run reversible test",
        outcome="the test produced useful evidence",
        success=True,
        reward=0.7,
        predicted_success=0.45,
    )

    exported = engine.export_state()
    restored = UnarchiEngine.from_export(exported)

    assert restored.snapshot() == engine.snapshot()
    assert restored.memory == engine.memory
    assert restored.observation_history == engine.observation_history

    original_next = engine.compare_ablation(
        observation="A new research hypothesis appears.",
        goal="test the hypothesis cheaply",
        expected_success=0.45,
        risk=0.2,
    )
    restored_next = restored.compare_ablation(
        observation="A new research hypothesis appears.",
        goal="test the hypothesis cheaply",
        expected_success=0.45,
        risk=0.2,
    )

    assert restored_next == original_next


def test_restore_rejects_unknown_state_version() -> None:
    engine = UnarchiEngine()
    exported = engine.export_state()
    exported["version"] = "future-incompatible-version"

    try:
        UnarchiEngine.from_export(exported)
    except ValueError as exc:
        assert "unsupported UNARCHI state version" in str(exc)
    else:
        raise AssertionError("unknown state versions must not be restored")


def test_information_gap_creates_bounded_internal_goal() -> None:
    engine = UnarchiEngine()

    frame = engine.cycle(
        observation="An unfamiliar mechanism produces inconsistent results.",
        goal="understand why the mechanism behaves differently",
        expected_success=0.25,
        risk=0.1,
    )

    internal_goal = engine.next_internal_goal()

    assert frame.information_gap >= 0.60
    assert internal_goal is not None
    assert internal_goal.status == "active"
    assert internal_goal.trigger in {"information_gap", "uncertainty"}
    assert internal_goal.max_steps == 3
    assert internal_goal.reversible_only is True
    assert internal_goal.paid_actions_allowed is False


def test_repeated_same_uncertainty_does_not_duplicate_internal_goal() -> None:
    engine = UnarchiEngine()
    kwargs = {
        "observation": "An unfamiliar mechanism produces inconsistent results.",
        "goal": "understand why the mechanism behaves differently",
        "expected_success": 0.25,
        "risk": 0.1,
    }

    engine.cycle(**kwargs)
    engine.cycle(**kwargs)

    assert len(engine.active_internal_goals()) == 1


def test_internal_goal_resolves_when_information_gap_falls() -> None:
    engine = UnarchiEngine()
    engine.cycle(
        observation="A new sensor output has no known explanation.",
        goal="determine what causes the sensor output",
        expected_success=0.2,
        risk=0.1,
    )
    internal_goal = engine.next_internal_goal()
    assert internal_goal is not None

    updated = engine.advance_internal_goal(
        internal_goal.id,
        new_information_gap=0.22,
        evidence="A reversible local test isolated the responsible input.",
    )

    assert updated.status == "resolved"
    assert engine.next_internal_goal() is None


def test_internal_goal_exhausts_after_bounded_steps() -> None:
    engine = UnarchiEngine()
    engine.cycle(
        observation="A new pattern remains unexplained.",
        goal="find the cause of the pattern",
        expected_success=0.2,
        risk=0.1,
    )
    internal_goal = engine.next_internal_goal()
    assert internal_goal is not None

    for step in range(internal_goal.max_steps):
        engine.advance_internal_goal(
            internal_goal.id,
            new_information_gap=0.8,
            evidence=f"Reversible test {step + 1} did not resolve the question.",
        )

    assert internal_goal.status == "exhausted"
    assert engine.next_internal_goal() is None


def test_internal_goal_refuses_paid_or_irreversible_steps() -> None:
    engine = UnarchiEngine()
    engine.cycle(
        observation="A new low-risk question is unresolved.",
        goal="understand the question",
        expected_success=0.2,
        risk=0.1,
    )
    internal_goal = engine.next_internal_goal()
    assert internal_goal is not None

    try:
        engine.advance_internal_goal(
            internal_goal.id,
            new_information_gap=0.5,
            evidence="Would require a paid external service.",
            external_cost_usd=0.01,
        )
    except ValueError as exc:
        assert "zero-cost" in str(exc)
    else:
        raise AssertionError("paid endogenous investigations must be rejected")

    try:
        engine.advance_internal_goal(
            internal_goal.id,
            new_information_gap=0.5,
            evidence="Would require an irreversible action.",
            reversible=False,
        )
    except ValueError as exc:
        assert "reversible" in str(exc)
    else:
        raise AssertionError("irreversible endogenous investigations must be rejected")


def test_export_restore_preserves_endogenous_goal_queue() -> None:
    engine = UnarchiEngine()
    engine.cycle(
        observation="An unresolved anomaly appears in a local simulation.",
        goal="explain the anomaly",
        expected_success=0.2,
        risk=0.1,
    )

    restored = UnarchiEngine.from_export(engine.export_state())

    assert restored.internal_goals == engine.internal_goals
    assert restored.next_internal_goal_id == engine.next_internal_goal_id
    assert restored.snapshot() == engine.snapshot()


def test_predict_action_forecasts_internal_consequences() -> None:
    engine = UnarchiEngine()

    prediction = engine.predict_action(
        action="run reversible local experiment",
        expected_success=0.7,
        expected_information_gain=0.8,
        risk=0.1,
        reversible=True,
    )

    assert prediction.predicted_success == 0.7
    assert prediction.predicted_information_gain == 0.8
    assert prediction.predicted_uncertainty < engine.state.uncertainty
    assert prediction.reversible is True
    assert prediction.utility > 0.0


def test_predictive_self_model_prefers_reversible_high_information_action() -> None:
    engine = UnarchiEngine()

    selected = engine.choose_predicted_action(
        [
            {
                "action": "irreversible production experiment",
                "expected_success": 0.9,
                "expected_information_gain": 0.7,
                "risk": 0.4,
                "reversible": False,
            },
            {
                "action": "reversible local simulation",
                "expected_success": 0.72,
                "expected_information_gain": 0.8,
                "risk": 0.1,
                "reversible": True,
            },
        ]
    )

    assert selected.action == "reversible local simulation"
    assert selected.reversible is True


def test_self_prediction_calibrates_after_repeated_outcomes() -> None:
    engine = UnarchiEngine()

    first = engine.predict_action(
        action="run known-safe local check",
        expected_success=0.4,
        expected_information_gain=0.3,
        risk=0.1,
    )
    first_error = abs(1.0 - first.predicted_success)
    engine.record_prediction_outcome(
        first.id,
        actual_success=True,
        actual_information_gain=0.3,
    )

    second = engine.predict_action(
        action="run known-safe local check",
        expected_success=0.4,
        expected_information_gain=0.3,
        risk=0.1,
    )
    second_error = abs(1.0 - second.predicted_success)

    assert second.predicted_success > first.predicted_success
    assert second_error < first_error
    assert engine.success_prediction_bias > 0.0
    assert len(engine.calibration_history) == 1


def test_calibration_record_measures_prediction_error() -> None:
    engine = UnarchiEngine()
    prediction = engine.predict_action(
        action="probe uncertain mechanism",
        expected_success=0.8,
        expected_information_gain=0.6,
        risk=0.2,
    )

    record = engine.record_prediction_outcome(
        prediction.id,
        actual_success=False,
        actual_information_gain=0.2,
    )

    assert record.success_error == 0.8
    assert record.information_gain_error == 0.4
    assert 0.0 <= record.calibration_score <= 1.0
    assert engine.success_prediction_bias < 0.0


def test_export_restore_preserves_predictive_self_model() -> None:
    engine = UnarchiEngine()
    prediction = engine.predict_action(
        action="reversible self-model test",
        expected_success=0.5,
        expected_information_gain=0.4,
        risk=0.1,
    )
    engine.record_prediction_outcome(
        prediction.id,
        actual_success=True,
        actual_information_gain=0.5,
    )

    restored = UnarchiEngine.from_export(engine.export_state())

    assert restored.predictions == engine.predictions
    assert restored.calibration_history == engine.calibration_history
    assert restored.next_prediction_id == engine.next_prediction_id
    assert restored.success_prediction_bias == engine.success_prediction_bias
    assert restored.self_calibration_score == engine.self_calibration_score
    assert restored.snapshot() == engine.snapshot()
