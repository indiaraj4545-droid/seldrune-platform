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
    assert snapshot["version"] == "unarchi-v0.2"


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
