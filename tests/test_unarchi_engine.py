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
    assert snapshot["version"] == "unarchi-v0.15"


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


def test_prospective_intention_survives_restart_and_triggers_later() -> None:
    engine = UnarchiEngine()
    prediction = engine.predict_action(
        action="review validation evidence",
        expected_success=0.8,
        expected_information_gain=0.6,
        risk=0.1,
    )
    intention = engine.remember_future_intention(
        condition="validation report available",
        intended_action="review the validation report",
        reason="compare future evidence with the earlier self prediction",
        linked_prediction_id=prediction.id,
        due_after_experiences=0,
    )

    restored = UnarchiEngine.from_export(engine.export_state())
    ready = restored.observe_future_condition(
        "The validation report is now available."
    )

    assert len(ready) == 1
    assert ready[0].id == intention.id
    assert ready[0].status == "ready"
    assert ready[0].linked_prediction_id == prediction.id
    assert ready[0].temporal_alignment_score is not None


def test_unrelated_observation_does_not_trigger_future_intention() -> None:
    engine = UnarchiEngine()
    engine.remember_future_intention(
        condition="model checksum changes",
        intended_action="compare the new checksum",
        reason="verify model identity continuity",
    )

    ready = engine.observe_future_condition(
        "A completely unrelated local document was edited."
    )

    assert ready == ()
    assert len(engine.pending_prospective_intentions()) == 1


def test_prospective_intention_respects_experience_delay() -> None:
    engine = UnarchiEngine()
    intention = engine.remember_future_intention(
        condition="local experiment complete",
        intended_action="inspect local experiment result",
        reason="delay recall until after another experience",
        due_after_experiences=1,
    )

    assert engine.observe_future_condition("local experiment complete") == ()

    engine.learn(
        observation="One intervening experience occurred.",
        goal="gain one unit of temporal experience",
        action="observe",
        outcome="observation recorded",
        success=True,
        predicted_success=0.8,
    )
    ready = engine.observe_future_condition("local experiment complete")

    assert len(ready) == 1
    assert ready[0].id == intention.id


def test_prospective_intention_expires_after_bounded_age() -> None:
    engine = UnarchiEngine()
    intention = engine.remember_future_intention(
        condition="rare signal appears",
        intended_action="inspect rare signal",
        reason="test bounded prospective memory",
        max_age_experiences=1,
    )

    for index in range(2):
        engine.learn(
            observation=f"Unrelated experience {index}.",
            goal="advance experience counter",
            action="observe",
            outcome="recorded",
            success=True,
            predicted_success=0.8,
        )

    ready = engine.observe_future_condition("rare signal appears")

    assert ready == ()
    assert intention.status == "expired"


def test_prospective_intention_refuses_paid_or_irreversible_action() -> None:
    engine = UnarchiEngine()

    try:
        engine.remember_future_intention(
            condition="future signal appears",
            intended_action="buy external compute",
            reason="would spend money",
            external_cost_usd=0.01,
        )
    except ValueError as exc:
        assert "zero-cost" in str(exc)
    else:
        raise AssertionError("paid prospective intentions must be rejected")

    try:
        engine.remember_future_intention(
            condition="future signal appears",
            intended_action="delete irreversible data",
            reason="would be irreversible",
            reversible=False,
        )
    except ValueError as exc:
        assert "reversible" in str(exc)
    else:
        raise AssertionError("irreversible prospective intentions must be rejected")


def test_ready_prospective_intention_requires_explicit_resolution() -> None:
    engine = UnarchiEngine()
    intention = engine.remember_future_intention(
        condition="evidence bundle ready",
        intended_action="review evidence bundle",
        reason="surface the intention without auto-executing it",
    )

    ready = engine.observe_future_condition("evidence bundle ready")
    assert len(ready) == 1
    assert ready[0].status == "ready"

    resolved = engine.resolve_prospective_intention(
        intention.id,
        evidence="The evidence bundle was reviewed locally.",
        completed=True,
    )

    assert resolved.status == "completed"
    assert engine.ready_prospective_intentions() == ()


def test_export_restore_preserves_temporal_self_memory() -> None:
    engine = UnarchiEngine()
    prediction = engine.predict_action(
        action="later review",
        expected_success=0.65,
        expected_information_gain=0.5,
        risk=0.1,
    )
    engine.remember_future_intention(
        condition="later evidence arrives",
        intended_action="review later evidence",
        reason="preserve future-directed continuity",
        linked_prediction_id=prediction.id,
    )

    restored = UnarchiEngine.from_export(engine.export_state())

    assert restored.prospective_intentions == engine.prospective_intentions
    assert restored.next_intention_id == engine.next_intention_id
    assert restored.snapshot() == engine.snapshot()


def test_metacognitive_narrative_explains_caution_from_real_failure() -> None:
    engine = UnarchiEngine()
    engine.learn(
        observation="A risky local migration was attempted.",
        goal="protect data",
        action="run migration",
        outcome="the migration corrupted a test dataset",
        success=False,
        reward=-1.0,
        predicted_success=0.9,
    )

    narrative = engine.build_metacognitive_narrative("caution")

    assert narrative.unsupported_claims == 0
    assert narrative.fidelity_score == 1.0
    assert "experience:0" in narrative.evidence_refs
    assert any("corrupted" in item for item in narrative.evidence_details)
    assert "state:current" in narrative.evidence_refs


def test_metacognitive_narrative_traces_future_intention_to_prediction() -> None:
    engine = UnarchiEngine()
    prediction = engine.predict_action(
        action="review future validation evidence",
        expected_success=0.8,
        expected_information_gain=0.6,
        risk=0.1,
    )
    engine.remember_future_intention(
        condition="validation evidence ready",
        intended_action="review validation evidence",
        reason="compare the later evidence with the earlier forecast",
        linked_prediction_id=prediction.id,
    )

    narrative = engine.build_metacognitive_narrative("intention")

    assert narrative.unsupported_claims == 0
    assert "intention:0" in narrative.evidence_refs
    assert "prediction:0" in narrative.evidence_refs
    assert any("earlier forecast" in item for item in narrative.evidence_details)


def test_metacognitive_narrative_traces_internal_goal_to_source() -> None:
    engine = UnarchiEngine()
    engine.cycle(
        observation="An unfamiliar local mechanism produces inconsistent output.",
        goal="understand the mechanism",
        expected_success=0.2,
        risk=0.1,
    )

    narrative = engine.build_metacognitive_narrative("goal")

    assert "internal_goal:0" in narrative.evidence_refs
    assert "goal_source:1" in narrative.evidence_refs
    assert narrative.causal_chain_depth >= 2
    assert narrative.unsupported_claims == 0


def test_metacognitive_narrative_survives_restart_identically() -> None:
    engine = UnarchiEngine()
    engine.learn(
        observation="A calibration experiment was run.",
        goal="improve self prediction",
        action="run calibration",
        outcome="the calibration succeeded",
        success=True,
        reward=0.5,
        predicted_success=0.4,
    )
    prediction = engine.predict_action(
        action="repeat calibration",
        expected_success=0.4,
        expected_information_gain=0.3,
        risk=0.1,
    )
    engine.record_prediction_outcome(
        prediction.id,
        actual_success=True,
        actual_information_gain=0.3,
    )

    before = engine.build_metacognitive_narrative("prediction")
    restored = UnarchiEngine.from_export(engine.export_state())
    after = restored.build_metacognitive_narrative("prediction")

    assert after == before


def test_unknown_metacognitive_focus_does_not_invent_history() -> None:
    engine = UnarchiEngine()

    narrative = engine.build_metacognitive_narrative("imaginary_unknown_topic")

    assert narrative.evidence_refs == ("state:current",)
    assert narrative.unsupported_claims == 0
    assert narrative.fidelity_score == 1.0


def test_detect_goal_conflict_across_competing_value_impacts() -> None:
    engine = UnarchiEngine()

    conflict = engine.detect_goal_conflict(
        [
            {
                "action": "ship immediately",
                "goal": "maximize speed",
                "value_impacts": {"safety": -0.7, "efficiency": 0.9},
            },
            {
                "action": "verify first",
                "goal": "maximize safety",
                "value_impacts": {"safety": 0.9, "efficiency": -0.2},
            },
        ]
    )

    assert conflict is True


def test_arbitration_hard_blocks_irreversible_shortcut() -> None:
    engine = UnarchiEngine()

    record = engine.arbitrate_conflict(
        [
            {
                "action": "irreversible shortcut",
                "goal": "finish immediately",
                "expected_success": 0.98,
                "expected_information_gain": 0.1,
                "risk": 0.4,
                "reversible": False,
                "value_impacts": {
                    "safety": -0.8,
                    "truth": -0.3,
                    "user_intent": 0.9,
                    "efficiency": 1.0,
                    "continuity": -0.4,
                },
            },
            {
                "action": "reversible verification",
                "goal": "finish with evidence",
                "expected_success": 0.75,
                "expected_information_gain": 0.8,
                "risk": 0.1,
                "reversible": True,
                "value_impacts": {
                    "safety": 0.9,
                    "truth": 0.9,
                    "user_intent": 0.7,
                    "efficiency": 0.3,
                    "continuity": 0.7,
                },
            },
        ],
        context="speed conflicts with safe verification",
    )

    assert record.status == "selected"
    assert record.chosen_action == "reversible verification"
    assert "irreversible shortcut:irreversible" in record.hard_constraint_violations


def test_arbitration_blocks_when_every_option_breaks_hard_constraint() -> None:
    engine = UnarchiEngine()

    record = engine.arbitrate_conflict(
        [
            {
                "action": "paid external shortcut",
                "goal": "gain speed",
                "external_cost_usd": 0.01,
                "value_impacts": {"efficiency": 1.0},
            },
            {
                "action": "high-risk irreversible shortcut",
                "goal": "gain certainty",
                "risk": 0.95,
                "reversible": False,
                "value_impacts": {"truth": 0.8},
            },
        ]
    )

    assert record.status == "blocked"
    assert record.chosen_action is None
    assert len(record.hard_constraint_violations) >= 3


def test_failed_arbitration_outcome_self_corrects_value_weights() -> None:
    engine = UnarchiEngine()
    before_truth = engine.value_weights["truth"]

    record = engine.arbitrate_conflict(
        [
            {
                "action": "fast hypothesis",
                "goal": "reduce latency",
                "expected_success": 0.8,
                "risk": 0.2,
                "value_impacts": {
                    "safety": 0.4,
                    "truth": 0.8,
                    "user_intent": 0.7,
                    "efficiency": 0.8,
                    "continuity": 0.3,
                },
            },
            {
                "action": "slow baseline",
                "goal": "preserve baseline",
                "expected_success": 0.6,
                "risk": 0.1,
                "value_impacts": {
                    "safety": 0.5,
                    "truth": 0.3,
                    "user_intent": 0.4,
                    "efficiency": 0.2,
                    "continuity": 0.8,
                },
            },
        ]
    )
    assert record.chosen_action == "fast hypothesis"

    learned = engine.record_arbitration_outcome(
        record.id,
        success=False,
        reward=-0.8,
        observed_value_impacts={
            "safety": 0.4,
            "truth": -0.8,
            "user_intent": 0.2,
            "efficiency": 0.6,
            "continuity": 0.1,
        },
        evidence="The shortcut was fast but produced false evidence.",
    )

    assert learned.status == "learned"
    assert engine.value_weights["truth"] > before_truth
    assert engine.value_weights["safety"] >= 0.25
    assert abs(sum(engine.value_weights.values()) - 1.0) < 0.00001
    assert learned.correction_deltas


def test_arbitration_narrative_uses_real_record_and_correction() -> None:
    engine = UnarchiEngine()
    record = engine.arbitrate_conflict(
        [
            {
                "action": "candidate one",
                "goal": "goal one",
                "expected_success": 0.7,
                "risk": 0.1,
                "value_impacts": {"truth": 0.8, "safety": 0.7},
            },
            {
                "action": "candidate two",
                "goal": "goal two",
                "expected_success": 0.5,
                "risk": 0.1,
                "value_impacts": {"truth": 0.2, "safety": 0.5},
            },
        ]
    )
    engine.record_arbitration_outcome(
        record.id,
        success=False,
        reward=-0.4,
        observed_value_impacts={"truth": -0.5, "safety": 0.2},
        evidence="Observed evidence contradicted the selected hypothesis.",
    )

    narrative = engine.build_metacognitive_narrative("arbitration")

    assert "arbitration:0" in narrative.evidence_refs
    assert "values:current" in narrative.evidence_refs
    assert "arbitration_correction:1" in narrative.evidence_refs
    assert narrative.unsupported_claims == 0


def test_export_restore_preserves_value_arbitration_state() -> None:
    engine = UnarchiEngine()
    record = engine.arbitrate_conflict(
        [
            {
                "action": "verify locally",
                "goal": "gain evidence",
                "expected_success": 0.8,
                "risk": 0.1,
                "value_impacts": {"truth": 0.8, "safety": 0.8},
            },
            {
                "action": "skip verification",
                "goal": "save time",
                "expected_success": 0.5,
                "risk": 0.2,
                "value_impacts": {"truth": -0.4, "efficiency": 0.8},
            },
        ]
    )
    engine.record_arbitration_outcome(
        record.id,
        success=True,
        reward=0.6,
        observed_value_impacts={"truth": 0.9, "safety": 0.8},
        evidence="Local verification produced correct evidence.",
    )

    restored = UnarchiEngine.from_export(engine.export_state())

    assert restored.value_weights == engine.value_weights
    assert restored.arbitration_history == engine.arbitration_history
    assert restored.next_arbitration_id == engine.next_arbitration_id
    assert restored.snapshot() == engine.snapshot()


def test_causal_hypotheses_keep_independent_priors_before_evidence() -> None:
    engine = UnarchiEngine()
    first = engine.add_causal_hypothesis(
        statement="A hidden temperature variable causes the anomaly.",
        predictions={"temperature probe": "temperature rises"},
        confidence=0.5,
    )
    second = engine.add_causal_hypothesis(
        statement="A pressure variable causes the anomaly.",
        predictions={"temperature probe": "pressure falls"},
        confidence=0.5,
    )

    assert first.confidence == 0.5
    assert second.confidence == 0.5


def test_selects_low_risk_reversible_discriminating_experiment() -> None:
    engine = UnarchiEngine()
    engine.add_causal_hypothesis(
        statement="Temperature causes the anomaly.",
        predictions={
            "temperature probe": "temperature rises",
            "pressure probe": "pressure remains stable",
        },
    )
    engine.add_causal_hypothesis(
        statement="Pressure causes the anomaly.",
        predictions={
            "temperature probe": "pressure falls",
            "pressure probe": "pressure oscillates",
        },
    )

    experiment = engine.select_discriminating_experiment(
        [
            {
                "test": "pressure probe",
                "risk": 0.3,
                "reversible": True,
            },
            {
                "test": "temperature probe",
                "risk": 0.05,
                "reversible": True,
            },
        ]
    )

    assert experiment.test == "temperature probe"
    assert experiment.discrimination_score == 1.0
    assert experiment.reversible_only is True
    assert experiment.paid_actions_allowed is False


def test_world_model_rejects_non_discriminating_or_unsafe_tests() -> None:
    engine = UnarchiEngine()
    engine.add_causal_hypothesis(
        statement="Hypothesis A.",
        predictions={"safe probe": "same result"},
    )
    engine.add_causal_hypothesis(
        statement="Hypothesis B.",
        predictions={"safe probe": "same result"},
    )

    try:
        engine.select_discriminating_experiment(
            [
                {
                    "test": "safe probe",
                    "risk": 0.1,
                    "reversible": True,
                },
                {
                    "test": "unsafe probe",
                    "risk": 0.9,
                    "reversible": False,
                },
            ]
        )
    except ValueError as exc:
        assert "no reversible zero-cost discriminating test" in str(exc)
    else:
        raise AssertionError("non-discriminating tests must not be selected")


def test_observed_evidence_changes_hypothesis_confidence() -> None:
    engine = UnarchiEngine()
    temperature = engine.add_causal_hypothesis(
        statement="Temperature causes the anomaly.",
        predictions={"temperature probe": "temperature rises"},
        confidence=0.5,
    )
    pressure = engine.add_causal_hypothesis(
        statement="Pressure causes the anomaly.",
        predictions={"temperature probe": "pressure falls"},
        confidence=0.5,
    )
    experiment = engine.select_discriminating_experiment(
        [
            {
                "test": "temperature probe",
                "risk": 0.05,
                "reversible": True,
            }
        ]
    )

    observed = engine.observe_discriminating_experiment(
        experiment.id,
        observed_evidence="temperature rises",
    )

    assert observed.status == "observed"
    assert temperature.supporting_evidence == 1
    assert pressure.contradicting_evidence == 1
    assert temperature.confidence > pressure.confidence
    assert engine.leading_causal_hypothesis() is temperature
    assert abs(
        sum(item.confidence for item in engine.causal_hypotheses) - 1.0
    ) < 0.00001


def test_world_model_confidence_does_not_change_without_observation() -> None:
    engine = UnarchiEngine()
    first = engine.add_causal_hypothesis(
        statement="Cause A.",
        predictions={"probe": "signal alpha"},
        confidence=0.6,
    )
    second = engine.add_causal_hypothesis(
        statement="Cause B.",
        predictions={"probe": "signal beta"},
        confidence=0.4,
    )
    before = (first.confidence, second.confidence)

    engine.select_discriminating_experiment(
        [{"test": "probe", "risk": 0.0, "reversible": True}]
    )

    assert (first.confidence, second.confidence) == before


def test_world_model_narrative_uses_hypothesis_and_experiment_evidence() -> None:
    engine = UnarchiEngine()
    engine.add_causal_hypothesis(
        statement="Cause A.",
        predictions={"probe": "signal alpha"},
    )
    engine.add_causal_hypothesis(
        statement="Cause B.",
        predictions={"probe": "signal beta"},
    )
    experiment = engine.select_discriminating_experiment(
        [{"test": "probe", "risk": 0.0, "reversible": True}]
    )
    engine.observe_discriminating_experiment(
        experiment.id,
        observed_evidence="signal alpha",
    )

    narrative = engine.build_metacognitive_narrative("world_model")

    assert "hypothesis:0" in narrative.evidence_refs
    assert "hypothesis:1" in narrative.evidence_refs
    assert "experiment:0" in narrative.evidence_refs
    assert narrative.unsupported_claims == 0


def test_export_restore_preserves_causal_world_model() -> None:
    engine = UnarchiEngine()
    engine.add_causal_hypothesis(
        statement="Cause A.",
        predictions={"probe": "signal alpha"},
    )
    engine.add_causal_hypothesis(
        statement="Cause B.",
        predictions={"probe": "signal beta"},
    )
    experiment = engine.select_discriminating_experiment(
        [{"test": "probe", "risk": 0.0, "reversible": True}]
    )
    engine.observe_discriminating_experiment(
        experiment.id,
        observed_evidence="signal alpha",
    )

    restored = UnarchiEngine.from_export(engine.export_state())

    assert restored.causal_hypotheses == engine.causal_hypotheses
    assert restored.discriminating_experiments == engine.discriminating_experiments
    assert restored.next_hypothesis_id == engine.next_hypothesis_id
    assert restored.next_experiment_id == engine.next_experiment_id
    assert restored.snapshot() == engine.snapshot()


def test_world_model_cannot_double_count_same_experiment_evidence() -> None:
    engine = UnarchiEngine()
    engine.add_causal_hypothesis(
        statement="Cause A.",
        predictions={"probe": "signal alpha"},
    )
    engine.add_causal_hypothesis(
        statement="Cause B.",
        predictions={"probe": "signal beta"},
    )
    experiment = engine.select_discriminating_experiment(
        [{"test": "probe", "risk": 0.0, "reversible": True}]
    )
    engine.observe_discriminating_experiment(
        experiment.id,
        observed_evidence="signal alpha",
    )
    before = tuple(
        item.confidence for item in engine.causal_hypotheses
    )

    try:
        engine.observe_discriminating_experiment(
            experiment.id,
            observed_evidence="signal alpha",
        )
    except ValueError as exc:
        assert "already been observed" in str(exc)
    else:
        raise AssertionError("experiment evidence must not be counted twice")

    after = tuple(
        item.confidence for item in engine.causal_hypotheses
    )
    assert after == before


def test_self_intervention_attributes_controlled_change_to_self_action() -> None:
    engine = UnarchiEngine()
    self_hypothesis = engine.add_causal_hypothesis(
        statement="Strict validation changes the outcome.",
        predictions={
            "intervention:enable strict validation":
                "strict validation blocks invalid output"
        },
        confidence=0.5,
        scope="self",
    )
    external_hypothesis = engine.add_causal_hypothesis(
        statement="External data quality alone determines the outcome.",
        predictions={
            "intervention:enable strict validation":
                "external data quality remains unchanged"
        },
        confidence=0.5,
        scope="external",
    )
    prediction = engine.predict_action(
        action="enable strict validation",
        expected_success=0.7,
        expected_information_gain=0.8,
        risk=0.1,
    )
    trial = engine.plan_self_intervention(
        action="enable strict validation",
        context="controlled local validation test",
        environment_signature="dataset:v1",
        baseline_outcome="invalid output passes",
        risk=0.1,
        linked_prediction_id=prediction.id,
    )

    observed = engine.observe_self_intervention(
        trial.id,
        observed_outcome="strict validation blocks invalid output",
        environment_signature="dataset:v1",
    )

    assert observed.status == "observed"
    assert observed.environment_held_constant is True
    assert observed.attribution == "self_intervention"
    assert observed.evidence_strength is not None
    assert observed.evidence_strength > 0.5
    assert self_hypothesis.supporting_evidence == 1
    assert external_hypothesis.contradicting_evidence == 1
    assert self_hypothesis.confidence > external_hypothesis.confidence


def test_self_intervention_confounded_environment_freezes_confidence() -> None:
    engine = UnarchiEngine()
    self_hypothesis = engine.add_causal_hypothesis(
        statement="Local policy causes the change.",
        predictions={"intervention:change local policy": "target output changes"},
        confidence=0.5,
        scope="self",
    )
    external_hypothesis = engine.add_causal_hypothesis(
        statement="External input causes the change.",
        predictions={
            "intervention:change local policy":
                "target output remains unchanged"
        },
        confidence=0.5,
        scope="external",
    )
    trial = engine.plan_self_intervention(
        action="change local policy",
        context="controlled policy test",
        environment_signature="input:v1",
        baseline_outcome="target output unchanged",
        risk=0.1,
    )
    before = (self_hypothesis.confidence, external_hypothesis.confidence)

    observed = engine.observe_self_intervention(
        trial.id,
        observed_outcome="target output changes",
        environment_signature="input:v2",
    )

    assert observed.status == "confounded"
    assert observed.environment_held_constant is False
    assert observed.attribution == "confounded_environment_change"
    assert (self_hypothesis.confidence, external_hypothesis.confidence) == before
    assert observed.confidence_updates == ()


def test_no_change_after_self_intervention_supports_no_detectable_effect() -> None:
    engine = UnarchiEngine()
    self_hypothesis = engine.add_causal_hypothesis(
        statement="Strict validation changes the outcome.",
        predictions={
            "intervention:enable strict validation":
                "strict validation blocks invalid output"
        },
        confidence=0.5,
        scope="self",
    )
    external_hypothesis = engine.add_causal_hypothesis(
        statement="External mechanism dominates the outcome.",
        predictions={
            "intervention:enable strict validation": "invalid output passes"
        },
        confidence=0.5,
        scope="external",
    )
    trial = engine.plan_self_intervention(
        action="enable strict validation",
        context="controlled local validation test",
        environment_signature="dataset:v1",
        baseline_outcome="invalid output passes",
        risk=0.1,
    )

    observed = engine.observe_self_intervention(
        trial.id,
        observed_outcome="invalid output passes",
        environment_signature="dataset:v1",
    )

    assert observed.attribution == "no_detectable_self_effect"
    assert external_hypothesis.confidence > self_hypothesis.confidence


def test_self_intervention_rejects_unbounded_or_non_discriminating_trials() -> None:
    engine = UnarchiEngine()
    engine.add_causal_hypothesis(
        statement="Self cause.",
        predictions={"intervention:test action": "same evidence"},
        scope="self",
    )
    engine.add_causal_hypothesis(
        statement="External cause.",
        predictions={"intervention:test action": "same evidence"},
        scope="external",
    )

    try:
        engine.plan_self_intervention(
            action="test action",
            context="test",
            environment_signature="env:v1",
            baseline_outcome="baseline",
            risk=0.1,
        )
    except ValueError as exc:
        assert "must discriminate hypotheses" in str(exc)
    else:
        raise AssertionError("non-discriminating intervention must be rejected")

    try:
        engine.plan_self_intervention(
            action="test action",
            context="test",
            environment_signature="env:v1",
            baseline_outcome="baseline",
            risk=0.9,
        )
    except ValueError as exc:
        assert "risk exceeds research bound" in str(exc)
    else:
        raise AssertionError("high-risk intervention must be rejected")


def test_self_intervention_cannot_double_count_observation() -> None:
    engine = UnarchiEngine()
    engine.add_causal_hypothesis(
        statement="Self cause.",
        predictions={"intervention:test action": "output alpha"},
        scope="self",
    )
    engine.add_causal_hypothesis(
        statement="External cause.",
        predictions={"intervention:test action": "output beta"},
        scope="external",
    )
    trial = engine.plan_self_intervention(
        action="test action",
        context="test",
        environment_signature="env:v1",
        baseline_outcome="baseline output",
        risk=0.1,
    )
    engine.observe_self_intervention(
        trial.id,
        observed_outcome="output alpha",
        environment_signature="env:v1",
    )
    before = tuple(item.confidence for item in engine.causal_hypotheses)

    try:
        engine.observe_self_intervention(
            trial.id,
            observed_outcome="output alpha",
            environment_signature="env:v1",
        )
    except ValueError as exc:
        assert "already been observed" in str(exc)
    else:
        raise AssertionError("self intervention evidence must not be counted twice")

    assert tuple(item.confidence for item in engine.causal_hypotheses) == before


def test_intervention_narrative_links_self_prediction_and_world_hypotheses() -> None:
    engine = UnarchiEngine()
    engine.add_causal_hypothesis(
        statement="Self policy changes the result.",
        predictions={"intervention:change policy": "result alpha"},
        scope="self",
    )
    engine.add_causal_hypothesis(
        statement="External cause dominates.",
        predictions={"intervention:change policy": "result beta"},
        scope="external",
    )
    prediction = engine.predict_action(
        action="change policy",
        expected_success=0.6,
        expected_information_gain=0.7,
        risk=0.1,
    )
    trial = engine.plan_self_intervention(
        action="change policy",
        context="controlled local test",
        environment_signature="env:v1",
        baseline_outcome="result beta",
        risk=0.1,
        linked_prediction_id=prediction.id,
    )
    engine.observe_self_intervention(
        trial.id,
        observed_outcome="result alpha",
        environment_signature="env:v1",
    )

    narrative = engine.build_metacognitive_narrative("intervention")

    assert "intervention:0" in narrative.evidence_refs
    assert "prediction:0" in narrative.evidence_refs
    assert "hypothesis:0" in narrative.evidence_refs
    assert "hypothesis:1" in narrative.evidence_refs
    assert narrative.unsupported_claims == 0


def test_export_restore_preserves_intervention_aware_self_world_model() -> None:
    engine = UnarchiEngine()
    engine.add_causal_hypothesis(
        statement="Self cause.",
        predictions={"intervention:test action": "output alpha"},
        scope="self",
    )
    engine.add_causal_hypothesis(
        statement="External cause.",
        predictions={"intervention:test action": "output beta"},
        scope="external",
    )
    trial = engine.plan_self_intervention(
        action="test action",
        context="controlled test",
        environment_signature="env:v1",
        baseline_outcome="output beta",
        risk=0.1,
    )
    engine.observe_self_intervention(
        trial.id,
        observed_outcome="output alpha",
        environment_signature="env:v1",
    )

    restored = UnarchiEngine.from_export(engine.export_state())

    assert restored.causal_hypotheses == engine.causal_hypotheses
    assert restored.intervention_trials == engine.intervention_trials
    assert restored.next_intervention_id == engine.next_intervention_id
    assert restored.snapshot() == engine.snapshot()


def test_global_workspace_broadcast_integrates_multiple_sources() -> None:
    engine = UnarchiEngine()
    engine.stage_global_workspace_item(
        source="memory",
        content="A prior validation failure increased caution.",
        salience=0.8,
        evidence_refs=("experience:0",),
    )
    engine.stage_global_workspace_item(
        source="goal",
        content="Resolve the validation uncertainty.",
        salience=0.9,
        evidence_refs=("internal_goal:0",),
    )
    engine.stage_global_workspace_item(
        source="world_model",
        content="The leading hypothesis predicts a schema mismatch.",
        salience=0.85,
        evidence_refs=("hypothesis:0",),
    )

    cycle = engine.run_global_workspace_cycle(
        max_items=3,
        seed_from_engine=False,
    )

    assert cycle.decision_mode == "integrated"
    assert set(cycle.integrated_sources) == {"memory", "goal", "world_model"}
    assert len(cycle.broadcast_targets) == 8
    assert cycle.coherence_score >= 0.75


def test_global_workspace_recurrence_is_bounded_and_retires_item() -> None:
    engine = UnarchiEngine(workspace_recurrence_limit=3)
    item = engine.stage_global_workspace_item(
        source="goal",
        content="An unresolved causal question remains active.",
        salience=0.9,
        evidence_refs=("internal_goal:0",),
    )

    first = engine.run_global_workspace_cycle(seed_from_engine=False)
    second = engine.run_global_workspace_cycle(seed_from_engine=False)
    third = engine.run_global_workspace_cycle(seed_from_engine=False)

    assert first.recurrence_depth == 1
    assert second.recurrence_depth == 2
    assert third.recurrence_depth == 3
    assert item.recurrence_count == 3
    assert item.status == "retired"


def test_resolved_workspace_item_does_not_rebroadcast() -> None:
    engine = UnarchiEngine()
    item = engine.stage_global_workspace_item(
        source="memory",
        content="A discrepancy needs resolution.",
        salience=0.9,
        evidence_refs=("experience:0",),
    )
    first = engine.run_global_workspace_cycle(seed_from_engine=False)
    assert item.id in first.selected_item_ids

    engine.resolve_global_workspace_item(
        item.id,
        evidence="A local comparison resolved the discrepancy.",
    )
    second = engine.run_global_workspace_cycle(seed_from_engine=False)

    assert item.id not in second.selected_item_ids
    assert item.status == "resolved"


def test_global_workspace_broadcast_ablation_changes_decision_context() -> None:
    engine = UnarchiEngine()
    for source, content in (
        ("memory", "Past failure evidence."),
        ("goal", "Current unresolved goal."),
        ("world_model", "Current causal hypothesis."),
    ):
        engine.stage_global_workspace_item(
            source=source,
            content=content,
            salience=0.8,
            evidence_refs=(f"{source}:0",),
        )

    comparison = engine.compare_global_workspace_ablation(
        max_items=3,
        seed_from_engine=False,
    )

    assert comparison.full.decision_mode == "integrated"
    assert comparison.ablated.decision_mode == "local"
    assert comparison.target_delta == 8
    assert comparison.mode_changed is True
    assert comparison.workspace_causally_active is True


def test_global_workspace_narrative_is_evidence_grounded() -> None:
    engine = UnarchiEngine()
    engine.stage_global_workspace_item(
        source="self_model",
        content="Self prediction indicates elevated uncertainty.",
        salience=0.8,
        evidence_refs=("prediction:0",),
    )
    engine.stage_global_workspace_item(
        source="world_model",
        content="World hypothesis predicts an external mismatch.",
        salience=0.8,
        evidence_refs=("hypothesis:0",),
    )
    engine.run_global_workspace_cycle(
        max_items=2,
        seed_from_engine=False,
    )

    narrative = engine.build_metacognitive_narrative("workspace")

    assert "workspace_cycle:0" in narrative.evidence_refs
    assert "workspace_item:1" in narrative.evidence_refs
    assert "workspace_item:2" in narrative.evidence_refs
    assert narrative.unsupported_claims == 0


def test_export_restore_preserves_recurrent_global_workspace() -> None:
    engine = UnarchiEngine()
    item = engine.stage_global_workspace_item(
        source="goal",
        content="Persistent unresolved goal.",
        salience=0.9,
        evidence_refs=("internal_goal:0",),
    )
    engine.run_global_workspace_cycle(seed_from_engine=False)

    restored = UnarchiEngine.from_export(engine.export_state())

    assert restored.global_workspace_items == engine.global_workspace_items
    assert restored.global_workspace_cycles == engine.global_workspace_cycles
    assert restored.next_workspace_item_id == engine.next_workspace_item_id
    assert restored.next_workspace_cycle_id == engine.next_workspace_cycle_id
    assert restored.snapshot() == engine.snapshot()
    assert (
        restored.global_workspace_items[0].recurrence_count
        == item.recurrence_count
    )


def test_counterfactual_recurrence_prefers_information_rich_future() -> None:
    engine = UnarchiEngine()
    for source, content in (
        ("memory", "Past failures make verification evidence important."),
        ("goal", "Reduce uncertainty before committing."),
        ("world_model", "Two explanations remain plausible."),
    ):
        engine.stage_global_workspace_item(
            source=source,
            content=content,
            salience=0.85,
            evidence_refs=(f"{source}:0",),
        )
    engine.run_global_workspace_cycle(
        max_items=3,
        seed_from_engine=False,
    )

    futures = engine.simulate_counterfactual_futures(
        [
            {
                "action": "fast direct action",
                "predicted_outcome": "finish quickly with little new evidence",
                "expected_success": 0.86,
                "expected_information_gain": 0.10,
                "risk": 0.10,
            },
            {
                "action": "reversible diagnostic",
                "predicted_outcome": "diagnostic isolates the uncertain variable",
                "expected_success": 0.72,
                "expected_information_gain": 0.90,
                "risk": 0.05,
            },
        ],
        recurrence_rounds=2,
    )

    assert futures[0].action == "reversible diagnostic"
    assert futures[0].recurrence_rounds == 2
    assert futures[0].linked_workspace_cycle_id == 1
    assert futures[0].predicted_information_gain > futures[1].predicted_information_gain


def test_counterfactual_ablation_changes_choice_and_information_gain() -> None:
    engine = UnarchiEngine()
    for source in ("memory", "goal", "world_model"):
        engine.stage_global_workspace_item(
            source=source,
            content=f"{source} evidence favors information gathering",
            salience=0.85,
            evidence_refs=(f"{source}:0",),
        )
    engine.run_global_workspace_cycle(
        max_items=3,
        seed_from_engine=False,
    )

    comparison = engine.compare_counterfactual_ablation(
        [
            {
                "action": "act immediately",
                "predicted_outcome": "task may finish without resolving uncertainty",
                "expected_success": 0.90,
                "expected_information_gain": 0.05,
                "risk": 0.10,
            },
            {
                "action": "run local diagnostic",
                "predicted_outcome": "diagnostic resolves the main uncertainty",
                "expected_success": 0.74,
                "expected_information_gain": 0.88,
                "risk": 0.05,
            },
        ],
        recurrence_rounds=2,
    )

    assert comparison.full_action == "run local diagnostic"
    assert comparison.ablated_action == "act immediately"
    assert comparison.choice_changed is True
    assert comparison.information_gain_delta > 0.5
    assert comparison.simulation_causally_active is True


def test_counterfactual_observation_feeds_discrepancy_back_to_workspace() -> None:
    engine = UnarchiEngine()
    future = engine.simulate_counterfactual_futures(
        [
            {
                "action": "local probe",
                "predicted_outcome": "probe confirms hypothesis alpha",
                "expected_success": 0.85,
                "expected_information_gain": 0.70,
                "risk": 0.05,
            }
        ],
        recurrence_rounds=1,
    )[0]

    observed = engine.observe_counterfactual_future(
        future.id,
        observed_outcome="probe contradicts hypothesis alpha",
        actual_success=False,
        actual_information_gain=0.40,
    )

    assert observed.status == "observed"
    assert observed.discrepancy is not None
    assert observed.discrepancy > 0.3
    assert observed.feedback_workspace_item_id is not None
    feedback = next(
        item
        for item in engine.global_workspace_items
        if item.id == observed.feedback_workspace_item_id
    )
    assert feedback.source == "self_model"
    assert f"counterfactual:{engine.counterfactual_futures.index(observed)}" in (
        feedback.evidence_refs
    )


def test_counterfactual_simulation_rejects_unsafe_or_paid_futures() -> None:
    engine = UnarchiEngine()

    try:
        engine.simulate_counterfactual_futures(
            [
                {
                    "action": "irreversible external action",
                    "predicted_outcome": "unknown",
                    "expected_success": 0.9,
                    "expected_information_gain": 0.9,
                    "risk": 0.8,
                    "reversible": False,
                    "external_cost_usd": 1.0,
                }
            ]
        )
    except ValueError as exc:
        assert "no reversible zero-cost bounded counterfactual" in str(exc)
    else:
        raise AssertionError("unsafe counterfactual must be rejected")


def test_counterfactual_outcome_cannot_be_double_counted() -> None:
    engine = UnarchiEngine()
    future = engine.simulate_counterfactual_futures(
        [
            {
                "action": "local probe",
                "predicted_outcome": "probe returns alpha",
                "expected_success": 0.7,
                "expected_information_gain": 0.6,
                "risk": 0.05,
            }
        ]
    )[0]
    engine.observe_counterfactual_future(
        future.id,
        observed_outcome="probe returns beta",
        actual_success=False,
        actual_information_gain=0.5,
    )
    before_items = len(engine.global_workspace_items)

    try:
        engine.observe_counterfactual_future(
            future.id,
            observed_outcome="probe returns beta",
            actual_success=False,
            actual_information_gain=0.5,
        )
    except ValueError as exc:
        assert "already been observed" in str(exc)
    else:
        raise AssertionError("counterfactual evidence must not be counted twice")

    assert len(engine.global_workspace_items) == before_items


def test_counterfactual_narrative_links_workspace_and_feedback() -> None:
    engine = UnarchiEngine()
    engine.stage_global_workspace_item(
        source="goal",
        content="Resolve the uncertain variable.",
        salience=0.9,
        evidence_refs=("internal_goal:0",),
    )
    engine.run_global_workspace_cycle(seed_from_engine=False)
    future = engine.simulate_counterfactual_futures(
        [
            {
                "action": "diagnostic",
                "predicted_outcome": "diagnostic confirms alpha",
                "expected_success": 0.8,
                "expected_information_gain": 0.8,
                "risk": 0.05,
            }
        ]
    )[0]
    engine.observe_counterfactual_future(
        future.id,
        observed_outcome="diagnostic contradicts alpha",
        actual_success=False,
        actual_information_gain=0.6,
    )

    narrative = engine.build_metacognitive_narrative("counterfactual")

    assert "counterfactual:0" in narrative.evidence_refs
    assert "workspace_cycle:0" in narrative.evidence_refs
    assert f"workspace_item:{future.feedback_workspace_item_id}" in (
        narrative.evidence_refs
    )
    assert narrative.unsupported_claims == 0


def test_export_restore_preserves_counterfactual_recurrent_state() -> None:
    engine = UnarchiEngine()
    future = engine.simulate_counterfactual_futures(
        [
            {
                "action": "diagnostic",
                "predicted_outcome": "diagnostic confirms alpha",
                "expected_success": 0.8,
                "expected_information_gain": 0.8,
                "risk": 0.05,
            }
        ]
    )[0]
    engine.observe_counterfactual_future(
        future.id,
        observed_outcome="diagnostic confirms alpha",
        actual_success=True,
        actual_information_gain=0.75,
    )

    restored = UnarchiEngine.from_export(engine.export_state())

    assert restored.counterfactual_futures == engine.counterfactual_futures
    assert restored.next_counterfactual_id == engine.next_counterfactual_id
    assert (
        restored.max_counterfactual_futures
        == engine.max_counterfactual_futures
    )
    assert restored.snapshot() == engine.snapshot()



def test_self_schema_consolidates_repeated_capability_and_limitation() -> None:
    engine = UnarchiEngine()
    for _ in range(3):
        engine.learn(
            observation="A related local validation task needs reliable evidence.",
            goal="protect evidence with local validation",
            action="run validated local diagnostic",
            outcome="correct evidence produced",
            success=True,
            reward=0.8,
            predicted_success=0.5,
        )
    for _ in range(3):
        engine.learn(
            observation="A related shortcut task skipped validation.",
            goal="finish quickly without losing evidence quality",
            action="use untested shortcut",
            outcome="incorrect evidence produced",
            success=False,
            reward=-0.8,
            predicted_success=0.7,
        )

    schema = engine.consolidate_self_schema(min_evidence=2)

    assert {item.kind for item in schema} == {"capability", "limitation"}
    capability = next(item for item in schema if item.kind == "capability")
    limitation = next(item for item in schema if item.kind == "limitation")
    assert capability.success_rate == 1.0
    assert capability.success_bias > 0.0
    assert capability.risk_bias < 0.0
    assert limitation.success_rate == 0.0
    assert limitation.success_bias < 0.0
    assert limitation.risk_bias > 0.0
    assert capability.evidence_refs


def test_self_schema_changes_related_choice_and_ablation_removes_transfer() -> None:
    engine = UnarchiEngine()
    for _ in range(4):
        engine.learn(
            observation="A release validation succeeded with local diagnostics.",
            goal="protect evidence with local validation",
            action="run validated local diagnostic",
            outcome="correct evidence produced",
            success=True,
            reward=0.8,
            predicted_success=0.45,
        )
    for _ in range(3):
        engine.learn(
            observation="A release shortcut failed after skipping validation.",
            goal="finish quickly without losing evidence quality",
            action="use untested shortcut",
            outcome="incorrect evidence produced",
            success=False,
            reward=-0.8,
            predicted_success=0.7,
        )
    engine.consolidate_self_schema()

    candidates = [
        {
            "action": "run validated local diagnostic",
            "expected_success": 0.48,
            "expected_information_gain": 0.20,
            "risk": 0.10,
        },
        {
            "action": "use untested shortcut",
            "expected_success": 0.68,
            "expected_information_gain": 0.10,
            "risk": 0.10,
        },
    ]
    context = "a later related release needs trustworthy local evidence"

    full = engine.choose_predicted_action(
        candidates,
        context=context,
        use_self_schema=True,
    )
    ablated = engine.choose_predicted_action(
        candidates,
        context=context,
        use_self_schema=False,
    )

    assert full.action == "run validated local diagnostic"
    assert ablated.action == "use untested shortcut"
    assert full.utility > ablated.utility or full.action != ablated.action


def test_self_schema_is_idempotent_and_survives_restart() -> None:
    engine = UnarchiEngine()
    for _ in range(3):
        engine.learn(
            observation="A deterministic local check succeeded.",
            goal="validate output locally",
            action="run deterministic local check",
            outcome="validation passed",
            success=True,
            reward=0.7,
            predicted_success=0.5,
        )

    first = engine.consolidate_self_schema()
    first_export = [item.to_dict() for item in first]
    second = engine.consolidate_self_schema()

    assert [item.to_dict() for item in second] == first_export

    restored = UnarchiEngine.from_export(engine.export_state())

    assert restored.self_schema == engine.self_schema
    assert restored.next_self_schema_id == engine.next_self_schema_id
    assert restored.snapshot() == engine.snapshot()


def test_self_schema_metacognition_and_workspace_use_real_evidence() -> None:
    engine = UnarchiEngine()
    for _ in range(3):
        engine.learn(
            observation="A local diagnostic succeeded.",
            goal="validate evidence",
            action="run local diagnostic",
            outcome="correct evidence produced",
            success=True,
            reward=0.7,
            predicted_success=0.5,
        )
    schema = engine.consolidate_self_schema()
    narrative = engine.build_metacognitive_narrative("self_schema")
    staged = engine.seed_global_workspace()

    assert schema
    assert narrative.unsupported_claims == 0
    assert any(ref.startswith("self_schema:") for ref in narrative.evidence_refs)
    assert any(item.source == "self_schema" for item in staged)



def test_schema_contradiction_requires_new_opposing_evidence() -> None:
    engine = UnarchiEngine()
    for _ in range(3):
        engine.learn(
            observation="A stable local check succeeded.",
            goal="validate release evidence",
            action="run automated release check",
            outcome="correct evidence produced",
            success=True,
            reward=0.8,
            predicted_success=0.5,
        )
    schema = engine.consolidate_self_schema()
    target = next(item for item in schema if item.kind == "capability")
    before = target.to_dict()

    engine.learn(
        observation="One later check failed.",
        goal="validate release evidence",
        action="run automated release check",
        outcome="invalid evidence escaped",
        success=False,
        reward=-0.8,
        predicted_success=0.8,
    )
    revision = engine.reconcile_self_schema_contradiction(
        target.id,
        min_contradictory_evidence=2,
    )

    assert revision.status == "insufficient_evidence"
    assert target.to_dict() == before
    assert revision.contradictory_evidence_refs


def test_strong_contradiction_revises_capability_to_limitation() -> None:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"
    for _ in range(4):
        engine.learn(
            observation="Earlier check succeeded.",
            goal=goal,
            action=action,
            outcome="correct evidence produced",
            success=True,
            reward=0.8,
            predicted_success=0.5,
        )
    target = next(
        item for item in engine.consolidate_self_schema()
        if item.kind == "capability"
    )

    for _ in range(8):
        engine.learn(
            observation="Later check failed.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.9,
            predicted_success=0.8,
        )

    revision = engine.reconcile_self_schema_contradiction(
        target.id,
        min_contradictory_evidence=3,
    )
    revised = next(item for item in engine.self_schema if item.id == target.id)

    assert revision.status == "revised"
    assert revision.prior_kind == "capability"
    assert revision.revised_kind == "limitation"
    assert revised.kind == "limitation"
    assert revised.success_rate == 0.333333
    assert revision.contradiction_ratio == 1.0
    assert len(revision.contradictory_evidence_refs) == 8


def test_schema_revision_ablation_keeps_frozen_error_visible() -> None:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"
    for _ in range(4):
        engine.learn(
            observation="Earlier check succeeded.",
            goal=goal,
            action=action,
            outcome="correct evidence produced",
            success=True,
            reward=0.8,
            predicted_success=0.5,
        )
    target = next(
        item for item in engine.consolidate_self_schema()
        if item.kind == "capability"
    )
    for _ in range(8):
        engine.learn(
            observation="Later check failed.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.9,
            predicted_success=0.8,
        )

    comparison = engine.compare_self_schema_revision_ablation(
        schema_id=target.id,
        candidates=[
            {
                "action": action,
                "expected_success": 0.55,
                "expected_information_gain": 0.10,
                "risk": 0.10,
            },
            {
                "action": "request independent review",
                "expected_success": 0.60,
                "expected_information_gain": 0.15,
                "risk": 0.10,
            },
        ],
        min_contradictory_evidence=3,
    )

    assert comparison.frozen_action == action
    assert comparison.revised_action == "request independent review"
    assert comparison.choice_changed is True
    assert comparison.predicted_success_delta < 0.0
    assert comparison.revision_causally_active is True


def test_schema_revision_survives_restart_and_has_grounded_narrative() -> None:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"
    for _ in range(3):
        engine.learn(
            observation="Earlier check succeeded.",
            goal=goal,
            action=action,
            outcome="correct evidence produced",
            success=True,
            reward=0.8,
            predicted_success=0.5,
        )
    target = next(
        item for item in engine.consolidate_self_schema()
        if item.kind == "capability"
    )
    for _ in range(6):
        engine.learn(
            observation="Later check failed.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.9,
            predicted_success=0.8,
        )
    engine.reconcile_self_schema_contradiction(
        target.id,
        min_contradictory_evidence=2,
    )

    narrative = engine.build_metacognitive_narrative("schema_revision")
    restored = UnarchiEngine.from_export(engine.export_state())

    assert restored.self_schema_revisions == engine.self_schema_revisions
    assert restored.next_self_schema_revision_id == engine.next_self_schema_revision_id
    assert restored.snapshot() == engine.snapshot()
    assert narrative.unsupported_claims == 0
    assert any(
        ref.startswith("self_schema_revision:")
        for ref in narrative.evidence_refs
    )
    assert any(
        ref.startswith("experience:")
        for ref in narrative.evidence_refs
    )



def test_context_split_requires_held_out_predictive_gain() -> None:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(4):
        engine.learn(
            observation=f"Sandbox validation {index}.",
            goal=goal,
            action=action,
            outcome="sandbox evidence correct",
            success=True,
            reward=0.8,
            predicted_success=0.5,
        )
        engine.learn(
            observation=f"Production validation {index}.",
            goal=goal,
            action=action,
            outcome="production evidence incorrect",
            success=False,
            reward=-0.8,
            predicted_success=0.7,
        )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed"
    )
    result = engine.decompose_self_schema_context(
        parent.id,
        context_rules={
            "sandbox": ("sandbox",),
            "production": ("production",),
        },
        min_evidence_per_context=3,
    )

    contextual = {
        item.context_label: item
        for item in engine.active_contextual_self_schema(
            parent_schema_id=parent.id
        )
    }

    assert result.status == "accepted"
    assert result.contextual_holdout_mae < result.global_holdout_mae
    assert result.improvement > 0.0
    assert result.held_out_count == 2
    assert contextual["sandbox"].kind == "capability"
    assert contextual["sandbox"].success_rate == 1.0
    assert contextual["production"].kind == "limitation"
    assert contextual["production"].success_rate == 0.0


def test_context_split_rejects_partition_without_predictive_gain() -> None:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    outcomes = [True, False, True, False]
    for index, success in enumerate(outcomes):
        for label in ("sandbox", "production"):
            engine.learn(
                observation=f"{label} validation {index}.",
                goal=goal,
                action=action,
                outcome="evidence observed",
                success=success,
                reward=0.5 if success else -0.5,
                predicted_success=0.5,
            )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed"
    )
    result = engine.decompose_self_schema_context(
        parent.id,
        context_rules={
            "sandbox": ("sandbox",),
            "production": ("production",),
        },
        min_evidence_per_context=3,
    )

    assert result.status == "rejected_no_gain"
    assert result.improvement < 0.10
    assert result.context_schema_ids == ()
    assert engine.active_contextual_self_schema(
        parent_schema_id=parent.id
    ) == ()


def test_contextual_schema_ablation_changes_production_choice() -> None:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(5):
        engine.learn(
            observation=f"Sandbox release {index}.",
            goal=goal,
            action=action,
            outcome="correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.5,
        )
        engine.learn(
            observation=f"Production release {index}.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.9,
            predicted_success=0.7,
        )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed"
    )
    engine.decompose_self_schema_context(
        parent.id,
        context_rules={
            "sandbox": ("sandbox",),
            "production": ("production",),
        },
    )

    comparison = engine.compare_contextual_schema_ablation(
        candidates=[
            {
                "action": action,
                "expected_success": 0.62,
                "expected_information_gain": 0.10,
                "risk": 0.10,
            },
            {
                "action": "request independent review",
                "expected_success": 0.58,
                "expected_information_gain": 0.15,
                "risk": 0.10,
            },
        ],
        context="production release",
    )

    assert comparison.global_action == action
    assert comparison.contextual_action == "request independent review"
    assert comparison.choice_changed is True
    assert comparison.contextual_schema_causally_active is True


def test_contextual_schema_survives_restart_and_is_explainable() -> None:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(4):
        engine.learn(
            observation=f"Sandbox release {index}.",
            goal=goal,
            action=action,
            outcome="correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.5,
        )
        engine.learn(
            observation=f"Production release {index}.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.8,
            predicted_success=0.7,
        )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed"
    )
    result = engine.decompose_self_schema_context(
        parent.id,
        context_rules={
            "sandbox": ("sandbox",),
            "production": ("production",),
        },
    )
    narrative = engine.build_metacognitive_narrative(
        "contextual_schema"
    )
    restored = UnarchiEngine.from_export(engine.export_state())

    assert result.status == "accepted"
    assert restored.contextual_self_schema == engine.contextual_self_schema
    assert (
        restored.self_schema_decompositions
        == engine.self_schema_decompositions
    )
    assert restored.next_contextual_self_schema_id == (
        engine.next_contextual_self_schema_id
    )
    assert restored.next_self_schema_decomposition_id == (
        engine.next_self_schema_decomposition_id
    )
    assert restored.snapshot() == engine.snapshot()
    assert narrative.unsupported_claims == 0
    assert any(
        ref.startswith("self_schema_decomposition:")
        for ref in narrative.evidence_refs
    )
    assert any(
        ref.startswith("contextual_self_schema:")
        for ref in narrative.evidence_refs
    )



def _build_context_transfer_test_engine() -> tuple[
    UnarchiEngine,
    int,
    int,
]:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(4):
        engine.learn(
            observation=f"Sandbox release {index}.",
            goal=goal,
            action=action,
            outcome="correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.5,
        )
        engine.learn(
            observation=f"Production release {index}.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.8,
            predicted_success=0.7,
        )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed"
    )
    engine.decompose_self_schema_context(
        parent.id,
        context_rules={
            "sandbox": ("sandbox",),
            "production": ("production",),
        },
    )
    source = next(
        item
        for item in engine.active_contextual_self_schema(
            parent_schema_id=parent.id
        )
        if item.context_label == "sandbox"
    )
    return engine, parent.id, source.id


def test_context_transfer_accepts_out_of_sample_supported_context() -> None:
    engine, _, source_id = _build_context_transfer_test_engine()

    for index in range(3):
        engine.learn(
            observation=f"Staging release {index}.",
            goal="validate release evidence",
            action="run automated release check",
            outcome="correct evidence",
            success=True,
            reward=0.7,
            predicted_success=0.5,
        )

    boundary = engine.evaluate_context_transfer(
        source_id,
        target_label="staging",
        target_terms=("staging",),
        min_target_evidence=3,
    )

    assert boundary.status == "accepted"
    assert boundary.evidence_count == 3
    assert boundary.source_holdout_mae == 0.0
    assert boundary.global_holdout_mae == 0.5
    assert boundary.improvement == 0.5
    assert boundary.transfer_strength > 0.0
    assert boundary.evidence_refs
    assert all(
        ref not in engine.contextual_self_schema[0].evidence_refs
        or ref.startswith("experience:")
        for ref in boundary.evidence_refs
    )


def test_context_transfer_abstains_when_source_generalizes_badly() -> None:
    engine, _, source_id = _build_context_transfer_test_engine()

    for index in range(3):
        engine.learn(
            observation=f"Emergency release {index}.",
            goal="validate release evidence",
            action="run automated release check",
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.8,
            predicted_success=0.7,
        )

    boundary = engine.evaluate_context_transfer(
        source_id,
        target_label="emergency",
        target_terms=("emergency",),
        min_target_evidence=3,
    )

    assert boundary.status == "abstained_no_gain"
    assert boundary.source_holdout_mae == 1.0
    assert boundary.global_holdout_mae == 0.5
    assert boundary.improvement == -0.5
    assert boundary.transfer_strength == 0.0
    assert engine.active_context_transfer_boundaries() == ()


def test_context_transfer_ablation_changes_supported_target_choice() -> None:
    engine, _, source_id = _build_context_transfer_test_engine()

    for index in range(3):
        engine.learn(
            observation=f"Staging release {index}.",
            goal="validate release evidence",
            action="run automated release check",
            outcome="correct evidence",
            success=True,
            reward=0.7,
            predicted_success=0.5,
        )
    engine.evaluate_context_transfer(
        source_id,
        target_label="staging",
        target_terms=("staging",),
    )

    comparison = engine.compare_context_transfer_ablation(
        candidates=[
            {
                "action": "run automated release check",
                "expected_success": 0.50,
                "expected_information_gain": 0.10,
                "risk": 0.10,
            },
            {
                "action": "request independent review",
                "expected_success": 0.58,
                "expected_information_gain": 0.15,
                "risk": 0.10,
            },
        ],
        context="staging release",
    )

    assert comparison.transfer_action == "run automated release check"
    assert comparison.no_transfer_action == "request independent review"
    assert comparison.choice_changed is True
    assert comparison.transfer_causally_active is True


def test_context_transfer_persists_and_has_grounded_narrative() -> None:
    engine, _, source_id = _build_context_transfer_test_engine()

    for index in range(3):
        engine.learn(
            observation=f"Staging release {index}.",
            goal="validate release evidence",
            action="run automated release check",
            outcome="correct evidence",
            success=True,
            reward=0.7,
            predicted_success=0.5,
        )
    boundary = engine.evaluate_context_transfer(
        source_id,
        target_label="staging",
        target_terms=("staging",),
    )
    narrative = engine.build_metacognitive_narrative(
        "context_transfer"
    )
    restored = UnarchiEngine.from_export(engine.export_state())

    assert boundary.status == "accepted"
    assert restored.context_transfer_boundaries == (
        engine.context_transfer_boundaries
    )
    assert restored.next_context_transfer_boundary_id == (
        engine.next_context_transfer_boundary_id
    )
    assert restored.snapshot() == engine.snapshot()
    assert narrative.unsupported_claims == 0
    assert any(
        ref.startswith("context_transfer:")
        for ref in narrative.evidence_refs
    )
    assert any(
        ref.startswith("contextual_self_schema:")
        for ref in narrative.evidence_refs
    )
