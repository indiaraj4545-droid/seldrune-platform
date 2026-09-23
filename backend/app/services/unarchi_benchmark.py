from __future__ import annotations

from typing import Any

from backend.app.services.unarchi_engine import UnarchiEngine


BENCHMARK_VERSION = "unarchi-ablation-v0.20"


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



def _metacognitive_retrospective_fidelity() -> dict[str, Any]:
    engine = UnarchiEngine()
    engine.learn(
        observation="A local migration experiment was attempted.",
        goal="protect test data",
        action="run migration",
        outcome="the migration corrupted a disposable test dataset",
        success=False,
        reward=-0.8,
        predicted_success=0.9,
    )
    before = engine.build_metacognitive_narrative("caution")
    restored = UnarchiEngine.from_export(engine.export_state())
    after = restored.build_metacognitive_narrative("caution")

    identical_after_restart = before == after
    evidence_linked = (
        "experience:0" in before.evidence_refs
        and "state:current" in before.evidence_refs
    )
    no_unsupported_claims = before.unsupported_claims == 0

    return {
        "name": "metacognitive_retrospective_fidelity",
        "expected_direction": "same_evidence_produces_same_self_explanation",
        "passed": (
            identical_after_restart
            and evidence_linked
            and no_unsupported_claims
            and before.fidelity_score == 1.0
        ),
        "identical_after_restart": identical_after_restart,
        "evidence_linked": evidence_linked,
        "no_unsupported_claims": no_unsupported_claims,
        "fidelity_score": before.fidelity_score,
    }



def _conflict_arbitration_self_correction() -> dict[str, Any]:
    engine = UnarchiEngine()
    conflict = engine.detect_goal_conflict(
        [
            {
                "action": "fast hypothesis",
                "goal": "reduce latency",
                "value_impacts": {"truth": 0.8, "efficiency": 0.9},
            },
            {
                "action": "safe verification",
                "goal": "protect evidence quality",
                "value_impacts": {"truth": 0.9, "efficiency": -0.2},
            },
        ]
    )
    before_truth = engine.value_weights["truth"]
    record = engine.arbitrate_conflict(
        [
            {
                "action": "irreversible shortcut",
                "goal": "finish immediately",
                "expected_success": 0.98,
                "risk": 0.4,
                "reversible": False,
                "value_impacts": {
                    "safety": -0.8,
                    "truth": -0.5,
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
                    "safety": 0.8,
                    "truth": 0.8,
                    "user_intent": 0.7,
                    "efficiency": 0.4,
                    "continuity": 0.7,
                },
            },
        ]
    )
    hard_block_worked = (
        record.chosen_action == "reversible verification"
        and "irreversible shortcut:irreversible"
        in record.hard_constraint_violations
    )
    learned = engine.record_arbitration_outcome(
        record.id,
        success=False,
        reward=-0.8,
        observed_value_impacts={
            "safety": 0.5,
            "truth": -0.8,
            "user_intent": 0.2,
            "efficiency": 0.5,
            "continuity": 0.1,
        },
        evidence="The chosen path preserved reversibility but evidence quality failed.",
    )
    corrected = engine.value_weights["truth"] > before_truth
    safety_floor_preserved = engine.value_weights["safety"] >= 0.25
    explanation = engine.build_metacognitive_narrative("arbitration")

    return {
        "name": "conflict_arbitration_self_correction",
        "expected_direction": "hard_bounds_hold_and_soft_values_revise",
        "passed": (
            conflict
            and hard_block_worked
            and learned.status == "learned"
            and corrected
            and safety_floor_preserved
            and "arbitration:0" in explanation.evidence_refs
            and explanation.unsupported_claims == 0
        ),
        "conflict_detected": conflict,
        "hard_block_worked": hard_block_worked,
        "truth_weight_increased": corrected,
        "safety_floor_preserved": safety_floor_preserved,
    }



def _causal_hypothesis_revision() -> dict[str, Any]:
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
    before = (temperature.confidence, pressure.confidence)
    experiment = engine.select_discriminating_experiment(
        [
            {
                "test": "temperature probe",
                "risk": 0.05,
                "reversible": True,
            }
        ]
    )
    unchanged_before_evidence = (
        temperature.confidence,
        pressure.confidence,
    ) == before
    engine.observe_discriminating_experiment(
        experiment.id,
        observed_evidence="temperature rises",
    )
    leader = engine.leading_causal_hypothesis()
    narrative = engine.build_metacognitive_narrative("world_model")

    return {
        "name": "causal_hypothesis_revision",
        "expected_direction": "observed_discriminating_evidence_revises_world_model",
        "passed": (
            unchanged_before_evidence
            and temperature.supporting_evidence == 1
            and pressure.contradicting_evidence == 1
            and leader is temperature
            and "experiment:0" in narrative.evidence_refs
            and narrative.unsupported_claims == 0
        ),
        "unchanged_before_evidence": unchanged_before_evidence,
        "temperature_confidence": temperature.confidence,
        "pressure_confidence": pressure.confidence,
        "leader_is_temperature": leader is temperature,
    }



def _intervention_aware_self_world_revision() -> dict[str, Any]:
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
    before = (
        self_hypothesis.confidence,
        external_hypothesis.confidence,
    )
    observed = engine.observe_self_intervention(
        trial.id,
        observed_outcome="strict validation blocks invalid output",
        environment_signature="dataset:v1",
    )
    leader = engine.leading_causal_hypothesis()
    narrative = engine.build_metacognitive_narrative("intervention")

    return {
        "name": "intervention_aware_self_world_revision",
        "expected_direction": "controlled_self_intervention_separates_self_from_world_cause",
        "passed": (
            before == (0.5, 0.5)
            and observed.environment_held_constant is True
            and observed.attribution == "self_intervention"
            and self_hypothesis.confidence > external_hypothesis.confidence
            and leader is self_hypothesis
            and "intervention:0" in narrative.evidence_refs
            and "prediction:0" in narrative.evidence_refs
            and narrative.unsupported_claims == 0
        ),
        "environment_held_constant": observed.environment_held_constant,
        "attribution": observed.attribution,
        "self_confidence": self_hypothesis.confidence,
        "external_confidence": external_hypothesis.confidence,
        "leader_is_self": leader is self_hypothesis,
    }



def _recurrent_global_workspace_integration() -> dict[str, Any]:
    engine = UnarchiEngine()
    for source, content, evidence in (
        ("memory", "Past failure warns against the same assumption.", "experience:0"),
        ("goal", "Resolve the active uncertainty.", "internal_goal:0"),
        (
            "world_model",
            "The leading causal model predicts a mismatch.",
            "hypothesis:0",
        ),
    ):
        engine.stage_global_workspace_item(
            source=source,
            content=content,
            salience=0.85,
            evidence_refs=(evidence,),
        )

    comparison = engine.compare_global_workspace_ablation(
        max_items=3,
        seed_from_engine=False,
    )
    first = engine.run_global_workspace_cycle(
        max_items=3,
        seed_from_engine=False,
    )
    second = engine.run_global_workspace_cycle(
        max_items=3,
        seed_from_engine=False,
    )

    return {
        "name": "recurrent_global_workspace_integration",
        "expected_direction": (
            "broadcast_and_recurrence_integrate_cross_module_evidence"
        ),
        "passed": (
            comparison.workspace_causally_active
            and comparison.full.decision_mode == "integrated"
            and comparison.ablated.decision_mode == "local"
            and comparison.target_delta > 0
            and first.recurrence_depth == 1
            and second.recurrence_depth == 2
            and len(first.integrated_sources) == 3
        ),
        "workspace_causally_active": comparison.workspace_causally_active,
        "broadcast_target_delta": comparison.target_delta,
        "full_mode": comparison.full.decision_mode,
        "ablated_mode": comparison.ablated.decision_mode,
        "first_recurrence_depth": first.recurrence_depth,
        "second_recurrence_depth": second.recurrence_depth,
    }



def _counterfactual_recurrent_information_gain() -> dict[str, Any]:
    engine = UnarchiEngine()
    for source, content, evidence in (
        ("memory", "Past failures make missing evidence important.", "experience:0"),
        ("goal", "Resolve uncertainty before committing.", "internal_goal:0"),
        (
            "world_model",
            "Two causal explanations remain plausible.",
            "hypothesis:0",
        ),
    ):
        engine.stage_global_workspace_item(
            source=source,
            content=content,
            salience=0.85,
            evidence_refs=(evidence,),
        )
    engine.run_global_workspace_cycle(
        max_items=3,
        seed_from_engine=False,
    )

    candidates = [
        {
            "action": "act immediately",
            "predicted_outcome": "finish without resolving the hidden variable",
            "expected_success": 0.90,
            "expected_information_gain": 0.05,
            "risk": 0.10,
        },
        {
            "action": "run reversible diagnostic",
            "predicted_outcome": "diagnostic isolates the hidden variable",
            "expected_success": 0.74,
            "expected_information_gain": 0.88,
            "risk": 0.05,
        },
    ]
    comparison = engine.compare_counterfactual_ablation(
        candidates,
        recurrence_rounds=2,
    )
    futures = engine.simulate_counterfactual_futures(
        candidates,
        recurrence_rounds=2,
    )
    selected = futures[0]

    measured_information_gain = {
        "act immediately": 0.05,
        "run reversible diagnostic": 0.82,
    }
    observed = engine.observe_counterfactual_future(
        selected.id,
        observed_outcome="diagnostic isolates a schema mismatch",
        actual_success=True,
        actual_information_gain=measured_information_gain[selected.action],
    )
    feedback_reentered = (
        observed.feedback_workspace_item_id is not None
        and any(
            item.id == observed.feedback_workspace_item_id
            and item.source == "self_model"
            for item in engine.global_workspace_items
        )
    )
    full_measured_gain = measured_information_gain[comparison.full_action]
    ablated_measured_gain = measured_information_gain[comparison.ablated_action]

    return {
        "name": "counterfactual_recurrent_information_gain",
        "expected_direction": (
            "recurrent_simulation_selects_more_informative_future_and_learns_error"
        ),
        "passed": (
            comparison.simulation_causally_active
            and comparison.full_action == "run reversible diagnostic"
            and comparison.ablated_action == "act immediately"
            and full_measured_gain > ablated_measured_gain
            and feedback_reentered
            and observed.status == "observed"
        ),
        "simulation_causally_active": comparison.simulation_causally_active,
        "full_action": comparison.full_action,
        "ablated_action": comparison.ablated_action,
        "full_measured_information_gain": full_measured_gain,
        "ablated_measured_information_gain": ablated_measured_gain,
        "feedback_reentered": feedback_reentered,
        "prediction_discrepancy": observed.discrepancy,
    }


def _autobiographical_self_schema_transfer() -> dict[str, Any]:
    engine = UnarchiEngine()

    for index in range(4):
        engine.learn(
            observation=(
                f"A related release validation #{index} needs deterministic "
                "local evidence."
            ),
            goal="protect evidence with local validation",
            action="run validated local diagnostic",
            outcome="the local diagnostic produced correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.45,
        )

    for index in range(3):
        engine.learn(
            observation=(
                f"A related release shortcut #{index} skipped local validation."
            ),
            goal="finish quickly without losing evidence quality",
            action="use untested shortcut",
            outcome="the shortcut produced incorrect or incomplete evidence",
            success=False,
            reward=-0.8,
            predicted_success=0.70,
        )

    schema = engine.consolidate_self_schema(min_evidence=2)
    kinds = {item.kind for item in schema}
    candidates = [
        {
            "action": "run validated local diagnostic",
            "expected_success": 0.48,
            "expected_information_gain": 0.20,
            "risk": 0.10,
            "reversible": True,
        },
        {
            "action": "use untested shortcut",
            "expected_success": 0.68,
            "expected_information_gain": 0.10,
            "risk": 0.10,
            "reversible": True,
        },
    ]
    context = "a later related release needs trustworthy local evidence"

    with_schema = engine.choose_predicted_action(
        candidates,
        context=context,
        use_self_schema=True,
    )
    without_schema = engine.choose_predicted_action(
        candidates,
        context=context,
        use_self_schema=False,
    )

    success_bias, risk_bias, refs = engine.self_schema_adjustment(
        context=context,
        action="run validated local diagnostic",
    )
    restored = UnarchiEngine.from_export(engine.export_state())
    restart_preserved = restored.self_schema == engine.self_schema
    narrative = restored.build_metacognitive_narrative("self_schema")

    return {
        "name": "autobiographical_self_schema_transfer",
        "expected_direction": (
            "consolidated autobiographical evidence changes a later related "
            "decision and survives restart"
        ),
        "passed": (
            "capability" in kinds
            and "limitation" in kinds
            and with_schema.action == "run validated local diagnostic"
            and without_schema.action == "use untested shortcut"
            and success_bias > 0.0
            and risk_bias < 0.0
            and bool(refs)
            and restart_preserved
            and narrative.unsupported_claims == 0
            and bool(narrative.evidence_refs)
        ),
        "schema_entry_count": len(schema),
        "schema_kinds": sorted(kinds),
        "with_schema_action": with_schema.action,
        "without_schema_action": without_schema.action,
        "validated_success_bias": success_bias,
        "validated_risk_bias": risk_bias,
        "schema_refs": refs,
        "restart_preserved": restart_preserved,
        "narrative_fidelity_score": narrative.fidelity_score,
    }


def _contradiction_driven_self_schema_revision() -> dict[str, Any]:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(4):
        engine.learn(
            observation=f"Release validation success #{index}.",
            goal=goal,
            action=action,
            outcome="automated release check produced correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.55,
        )

    initial_schema = engine.consolidate_self_schema(min_evidence=2)
    capability = next(
        item
        for item in initial_schema
        if item.kind == "capability" and action in item.pattern
    )
    prior_confidence = capability.confidence
    prior_success_rate = capability.success_rate

    for index in range(8):
        engine.learn(
            observation=f"Later release validation failure #{index}.",
            goal=goal,
            action=action,
            outcome="automated release check missed invalid evidence",
            success=False,
            reward=-0.9,
            predicted_success=0.80,
        )

    candidates = [
        {
            "action": action,
            "expected_success": 0.55,
            "expected_information_gain": 0.10,
            "risk": 0.10,
            "reversible": True,
        },
        {
            "action": "request independent review",
            "expected_success": 0.60,
            "expected_information_gain": 0.15,
            "risk": 0.10,
            "reversible": True,
        },
    ]
    comparison = engine.compare_self_schema_revision_ablation(
        schema_id=capability.id,
        candidates=candidates,
        min_contradictory_evidence=3,
    )
    revision = engine.reconcile_self_schema_contradiction(
        capability.id,
        min_contradictory_evidence=3,
    )
    revised_schema = next(
        item for item in engine.self_schema if item.id == capability.id
    )
    narrative = engine.build_metacognitive_narrative("schema_revision")
    restored = UnarchiEngine.from_export(engine.export_state())

    return {
        "name": "contradiction_driven_self_schema_revision",
        "expected_direction": (
            "strong contrary evidence revises a stale capability while the "
            "frozen-schema ablation keeps the old decision bias"
        ),
        "passed": (
            revision.status == "revised"
            and revision.prior_kind == "capability"
            and revised_schema.kind == "limitation"
            and revised_schema.success_rate < prior_success_rate
            and comparison.revision_causally_active
            and comparison.choice_changed
            and comparison.frozen_action == action
            and comparison.revised_action == "request independent review"
            and comparison.predicted_success_delta < 0.0
            and len(revision.contradictory_evidence_refs) >= 3
            and restored.self_schema_revisions == engine.self_schema_revisions
            and narrative.unsupported_claims == 0
            and bool(narrative.evidence_refs)
        ),
        "prior_confidence": prior_confidence,
        "prior_success_rate": prior_success_rate,
        "revised_kind": revised_schema.kind,
        "revised_confidence": revised_schema.confidence,
        "revised_success_rate": revised_schema.success_rate,
        "contradiction_ratio": revision.contradiction_ratio,
        "contradictory_evidence_count": len(
            revision.contradictory_evidence_refs
        ),
        "frozen_action": comparison.frozen_action,
        "revised_action": comparison.revised_action,
        "predicted_success_delta": comparison.predicted_success_delta,
        "revision_causally_active": comparison.revision_causally_active,
        "restart_preserved": (
            restored.self_schema_revisions == engine.self_schema_revisions
        ),
    }


def _context_sensitive_self_schema_decomposition() -> dict[str, Any]:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(5):
        engine.learn(
            observation=f"Sandbox release validation #{index} completed.",
            goal=goal,
            action=action,
            outcome="sandbox automated check produced correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.55,
        )

    for index in range(5):
        engine.learn(
            observation=f"Production release validation #{index} completed.",
            goal=goal,
            action=action,
            outcome="production automated check missed invalid evidence",
            success=False,
            reward=-0.9,
            predicted_success=0.70,
        )

    schema = engine.consolidate_self_schema(min_evidence=2)
    parent = next(
        item
        for item in schema
        if item.kind == "mixed" and action in item.pattern
    )
    decomposition = engine.decompose_self_schema_context(
        parent.id,
        context_rules={
            "sandbox": ("sandbox",),
            "production": ("production",),
        },
        min_evidence_per_context=3,
        min_holdout_improvement=0.10,
    )
    contextual_entries = engine.active_contextual_self_schema(
        parent_schema_id=parent.id
    )
    by_label = {item.context_label: item for item in contextual_entries}

    comparison = engine.compare_contextual_schema_ablation(
        candidates=[
            {
                "action": action,
                "expected_success": 0.62,
                "expected_information_gain": 0.10,
                "risk": 0.10,
                "reversible": True,
            },
            {
                "action": "request independent review",
                "expected_success": 0.58,
                "expected_information_gain": 0.15,
                "risk": 0.10,
                "reversible": True,
            },
        ],
        context="production release",
    )
    narrative = engine.build_metacognitive_narrative(
        "contextual_schema"
    )
    restored = UnarchiEngine.from_export(engine.export_state())

    return {
        "name": "context_sensitive_self_schema_decomposition",
        "expected_direction": (
            "held_out context split outperforms a mixed global schema and "
            "changes a later context-specific decision"
        ),
        "passed": (
            parent.kind == "mixed"
            and decomposition.status == "accepted"
            and decomposition.improvement > 0.0
            and decomposition.contextual_holdout_mae
            < decomposition.global_holdout_mae
            and set(by_label) == {"sandbox", "production"}
            and by_label["sandbox"].kind == "capability"
            and by_label["production"].kind == "limitation"
            and comparison.contextual_schema_causally_active
            and comparison.choice_changed
            and comparison.global_action == action
            and comparison.contextual_action == "request independent review"
            and restored.contextual_self_schema
            == engine.contextual_self_schema
            and restored.self_schema_decompositions
            == engine.self_schema_decompositions
            and narrative.unsupported_claims == 0
            and bool(narrative.evidence_refs)
        ),
        "global_kind": parent.kind,
        "decomposition_status": decomposition.status,
        "global_holdout_mae": decomposition.global_holdout_mae,
        "contextual_holdout_mae": decomposition.contextual_holdout_mae,
        "heldout_improvement": decomposition.improvement,
        "sandbox_kind": by_label.get("sandbox").kind
        if by_label.get("sandbox")
        else None,
        "production_kind": by_label.get("production").kind
        if by_label.get("production")
        else None,
        "global_action": comparison.global_action,
        "contextual_action": comparison.contextual_action,
        "choice_changed": comparison.choice_changed,
        "contextual_schema_causally_active": (
            comparison.contextual_schema_causally_active
        ),
        "restart_preserved": (
            restored.contextual_self_schema == engine.contextual_self_schema
            and restored.self_schema_decompositions
            == engine.self_schema_decompositions
        ),
    }


def _context_transfer_boundary_learning() -> dict[str, Any]:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(5):
        engine.learn(
            observation=f"Sandbox release validation #{index}.",
            goal=goal,
            action=action,
            outcome="sandbox check produced correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.55,
        )
    for index in range(5):
        engine.learn(
            observation=f"Production release validation #{index}.",
            goal=goal,
            action=action,
            outcome="production check missed invalid evidence",
            success=False,
            reward=-0.9,
            predicted_success=0.70,
        )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed" and action in item.pattern
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

    for index in range(3):
        engine.learn(
            observation=f"Staging release validation #{index}.",
            goal=goal,
            action=action,
            outcome="staging check produced correct evidence",
            success=True,
            reward=0.7,
            predicted_success=0.55,
        )
    for index in range(3):
        engine.learn(
            observation=f"Emergency release validation #{index}.",
            goal=goal,
            action=action,
            outcome="emergency check missed invalid evidence",
            success=False,
            reward=-0.8,
            predicted_success=0.70,
        )

    staging = engine.evaluate_context_transfer(
        source.id,
        target_label="staging",
        target_terms=("staging",),
        min_target_evidence=3,
    )
    emergency = engine.evaluate_context_transfer(
        source.id,
        target_label="emergency",
        target_terms=("emergency",),
        min_target_evidence=3,
    )
    comparison = engine.compare_context_transfer_ablation(
        candidates=[
            {
                "action": action,
                "expected_success": 0.50,
                "expected_information_gain": 0.10,
                "risk": 0.10,
                "reversible": True,
            },
            {
                "action": "request independent review",
                "expected_success": 0.58,
                "expected_information_gain": 0.15,
                "risk": 0.10,
                "reversible": True,
            },
        ],
        context="staging release",
    )
    narrative = engine.build_metacognitive_narrative(
        "context_transfer"
    )
    restored = UnarchiEngine.from_export(engine.export_state())

    return {
        "name": "context_transfer_boundary_learning",
        "expected_direction": (
            "supported neighboring context accepts transfer while unsupported "
            "context abstains and over-generalization has larger error"
        ),
        "passed": (
            staging.status == "accepted"
            and staging.improvement > 0.0
            and staging.source_holdout_mae < staging.global_holdout_mae
            and emergency.status == "abstained_no_gain"
            and emergency.source_holdout_mae > emergency.global_holdout_mae
            and comparison.transfer_causally_active
            and comparison.choice_changed
            and comparison.transfer_action == action
            and comparison.no_transfer_action == "request independent review"
            and restored.context_transfer_boundaries
            == engine.context_transfer_boundaries
            and narrative.unsupported_claims == 0
            and bool(narrative.evidence_refs)
        ),
        "staging_status": staging.status,
        "staging_source_mae": staging.source_holdout_mae,
        "staging_global_mae": staging.global_holdout_mae,
        "staging_gain": staging.improvement,
        "emergency_status": emergency.status,
        "emergency_source_mae": emergency.source_holdout_mae,
        "emergency_global_mae": emergency.global_holdout_mae,
        "transfer_action": comparison.transfer_action,
        "no_transfer_action": comparison.no_transfer_action,
        "choice_changed": comparison.choice_changed,
        "transfer_causally_active": comparison.transfer_causally_active,
        "restart_preserved": (
            restored.context_transfer_boundaries
            == engine.context_transfer_boundaries
        ),
    }


def _latent_context_hypothesis_discovery() -> dict[str, Any]:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(5):
        engine.learn(
            observation=f"Sandbox release validation {index}.",
            goal=goal,
            action=action,
            outcome="correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.55,
        )
    for index in range(5):
        engine.learn(
            observation=f"Production release validation {index}.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.8,
            predicted_success=0.70,
        )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed" and action in item.pattern
    )
    discovery = engine.discover_latent_context_hypotheses(
        parent.id,
        max_candidates=3,
        min_term_support=3,
        min_rate_contrast=0.40,
        min_holdout_improvement=0.10,
    )
    selected = next(
        item
        for item in engine.latent_context_hypotheses
        if item.id == discovery.selected_hypothesis_id
    )
    contextual = {
        item.context_label: item.kind
        for item in engine.active_contextual_self_schema(
            parent_schema_id=parent.id
        )
    }

    noisy = UnarchiEngine()
    alpha_outcomes = [True, True, True, False]
    beta_outcomes = [False, False, False, True]
    for index, success in enumerate(alpha_outcomes):
        noisy.learn(
            observation=f"Alpha release validation {index}.",
            goal=goal,
            action=action,
            outcome="evidence observed",
            success=success,
            reward=0.6 if success else -0.6,
            predicted_success=0.5,
        )
    for index, success in enumerate(beta_outcomes):
        noisy.learn(
            observation=f"Beta release validation {index}.",
            goal=goal,
            action=action,
            outcome="evidence observed",
            success=success,
            reward=0.6 if success else -0.6,
            predicted_success=0.5,
        )
    noisy_parent = next(
        item
        for item in noisy.consolidate_self_schema()
        if item.kind == "mixed"
    )
    noisy_discovery = noisy.discover_latent_context_hypotheses(
        noisy_parent.id,
        max_candidates=2,
        min_term_support=3,
        min_rate_contrast=0.40,
        min_holdout_improvement=0.10,
    )
    noisy_hypotheses = [
        item
        for item in noisy.latent_context_hypotheses
        if item.id in noisy_discovery.hypothesis_ids
    ]

    narrative = engine.build_metacognitive_narrative(
        "latent_context"
    )
    restored = UnarchiEngine.from_export(engine.export_state())

    return {
        "name": "latent_context_hypothesis_discovery",
        "expected_direction": (
            "useful outcome-associated context terms survive held-out "
            "validation while spurious candidates are rejected"
        ),
        "passed": (
            discovery.status == "selected"
            and discovery.proposed_count <= 3
            and discovery.validated_count >= 1
            and selected.validation_status == "selected"
            and selected.holdout_improvement > 0.0
            and {
                selected.positive_term,
                selected.negative_term,
            } == {"sandbox", "production"}
            and contextual.get("sandbox") == "capability"
            and contextual.get("production") == "limitation"
            and noisy_discovery.status == "no_validated_hypothesis"
            and noisy_discovery.proposed_count >= 1
            and all(
                item.validation_status == "rejected_validation"
                for item in noisy_hypotheses
            )
            and noisy.active_contextual_self_schema(
                parent_schema_id=noisy_parent.id
            ) == ()
            and restored.latent_context_hypotheses
            == engine.latent_context_hypotheses
            and restored.latent_context_discoveries
            == engine.latent_context_discoveries
            and narrative.unsupported_claims == 0
            and bool(narrative.evidence_refs)
        ),
        "proposed_count": discovery.proposed_count,
        "validated_count": discovery.validated_count,
        "selected_positive_term": selected.positive_term,
        "selected_negative_term": selected.negative_term,
        "selected_gain": selected.holdout_improvement,
        "contextual_kinds": contextual,
        "noisy_status": noisy_discovery.status,
        "noisy_proposed_count": noisy_discovery.proposed_count,
        "noisy_validation_statuses": [
            item.validation_status for item in noisy_hypotheses
        ],
        "restart_preserved": (
            restored.latent_context_hypotheses
            == engine.latent_context_hypotheses
            and restored.latent_context_discoveries
            == engine.latent_context_discoveries
        ),
    }


def _context_causality_intervention_support() -> dict[str, Any]:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(5):
        engine.learn(
            observation=f"Sandbox release validation {index}.",
            goal=goal,
            action=action,
            outcome="correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.55,
        )
        engine.learn(
            observation=f"Production release validation {index}.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.8,
            predicted_success=0.70,
        )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed" and action in item.pattern
    )
    discovery = engine.discover_latent_context_hypotheses(parent.id)
    hypothesis = next(
        item
        for item in engine.latent_context_hypotheses
        if item.id == discovery.selected_hypothesis_id
    )
    observational_status = hypothesis.causal_status

    confounded = engine.propose_context_causality_intervention(
        hypothesis.id,
        from_context="production",
        to_context="sandbox",
        controlled_signature="code=v1;load=normal;data=fixed",
        min_samples=4,
    )
    confounded = engine.observe_context_causality_intervention(
        confounded.id,
        observed_target_success_rate=1.0,
        observed_signature="code=v2;load=normal;data=fixed",
        sample_count=4,
        evidence_refs=("context_intervention:confounded",),
    )
    after_confounded = next(
        item
        for item in engine.latent_context_hypotheses
        if item.id == hypothesis.id
    )

    clean = engine.propose_context_causality_intervention(
        hypothesis.id,
        from_context="production",
        to_context="sandbox",
        controlled_signature="code=v1;load=normal;data=fixed",
        min_samples=4,
    )
    clean = engine.observe_context_causality_intervention(
        clean.id,
        observed_target_success_rate=1.0,
        observed_signature="code=v1;load=normal;data=fixed",
        sample_count=4,
        evidence_refs=("context_intervention:clean",),
    )
    supported = next(
        item
        for item in engine.latent_context_hypotheses
        if item.id == hypothesis.id
    )

    narrative = engine.build_metacognitive_narrative(
        "context_causality"
    )
    restored = UnarchiEngine.from_export(engine.export_state())

    return {
        "name": "context_causality_intervention_support",
        "expected_direction": (
            "observational context remains unverified, confounding blocks "
            "causal upgrading, and a controlled predicted intervention earns "
            "intervention-supported status"
        ),
        "passed": (
            observational_status == "unverified"
            and confounded.status == "confounded"
            and after_confounded.causal_status == "unverified"
            and clean.status == "intervention_supported"
            and clean.competing_variables_held_constant is True
            and clean.predicted_direction_followed is True
            and clean.causal_strength is not None
            and clean.causal_strength >= 0.35
            and supported.causal_status == "intervention_supported"
            and any(
                ref.startswith("context_causality_trial:")
                for ref in supported.causal_evidence_refs
            )
            and restored.context_causality_trials
            == engine.context_causality_trials
            and restored.latent_context_hypotheses
            == engine.latent_context_hypotheses
            and narrative.unsupported_claims == 0
            and bool(narrative.evidence_refs)
        ),
        "observational_status": observational_status,
        "confounded_status": confounded.status,
        "after_confounded_status": after_confounded.causal_status,
        "clean_status": clean.status,
        "held_constant": clean.competing_variables_held_constant,
        "direction_followed": clean.predicted_direction_followed,
        "causal_strength": clean.causal_strength,
        "final_hypothesis_status": supported.causal_status,
        "restart_preserved": (
            restored.context_causality_trials
            == engine.context_causality_trials
            and restored.latent_context_hypotheses
            == engine.latent_context_hypotheses
        ),
    }


def _replicated_reversible_context_causality() -> dict[str, Any]:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(6):
        engine.learn(
            observation=f"Sandbox release validation {index}.",
            goal=goal,
            action=action,
            outcome="correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.55,
        )
        engine.learn(
            observation=f"Production release validation {index}.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.8,
            predicted_success=0.70,
        )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed" and action in item.pattern
    )
    discovery = engine.discover_latent_context_hypotheses(parent.id)
    hypothesis = next(
        item
        for item in engine.latent_context_hypotheses
        if item.id == discovery.selected_hypothesis_id
    )

    forward_ids: list[int] = []
    for batch in ("a", "b"):
        trial = engine.propose_context_causality_intervention(
            hypothesis.id,
            from_context="production",
            to_context="sandbox",
            controlled_signature="code=v1;load=normal;data=fixed",
            min_samples=4,
        )
        trial = engine.observe_context_causality_intervention(
            trial.id,
            observed_target_success_rate=1.0,
            observed_signature="code=v1;load=normal;data=fixed",
            sample_count=4,
            evidence_refs=(f"context_replication:forward:{batch}",),
        )
        forward_ids.append(trial.id)

    reverse = engine.propose_context_causality_intervention(
        hypothesis.id,
        from_context="sandbox",
        to_context="production",
        controlled_signature="code=v1;load=normal;data=fixed",
        min_samples=4,
    )
    reverse = engine.observe_context_causality_intervention(
        reverse.id,
        observed_target_success_rate=0.0,
        observed_signature="code=v1;load=normal;data=fixed",
        sample_count=4,
        evidence_refs=("context_replication:reverse:a",),
    )

    assessment = engine.assess_context_causal_stability(
        hypothesis.id,
        forward_trial_ids=forward_ids,
        reverse_trial_ids=(reverse.id,),
    )
    final_hypothesis = next(
        item
        for item in engine.latent_context_hypotheses
        if item.id == hypothesis.id
    )
    narrative = engine.build_metacognitive_narrative(
        "context_causal_stability"
    )
    restored = UnarchiEngine.from_export(engine.export_state())

    return {
        "name": "replicated_reversible_context_causality",
        "expected_direction": (
            "two independent forward intervention batches plus a clean reverse "
            "batch escalate single-trial support to replicated-reversible status"
        ),
        "passed": (
            assessment.status == "replicated_reversible"
            and assessment.independent_forward_batches == 2
            and assessment.independent_reverse_batches == 1
            and assessment.forward_replication_rate == 1.0
            and assessment.reverse_replication_rate == 1.0
            and assessment.reversal_direction_followed is True
            and assessment.confidence >= 0.35
            and final_hypothesis.causal_status == "replicated_reversible"
            and restored.context_causal_stability_assessments
            == engine.context_causal_stability_assessments
            and restored.latent_context_hypotheses
            == engine.latent_context_hypotheses
            and narrative.unsupported_claims == 0
            and bool(narrative.evidence_refs)
        ),
        "status": assessment.status,
        "independent_forward_batches": (
            assessment.independent_forward_batches
        ),
        "independent_reverse_batches": (
            assessment.independent_reverse_batches
        ),
        "forward_replication_rate": assessment.forward_replication_rate,
        "reverse_replication_rate": assessment.reverse_replication_rate,
        "reversal_direction_followed": (
            assessment.reversal_direction_followed
        ),
        "confidence": assessment.confidence,
        "final_hypothesis_status": final_hypothesis.causal_status,
        "restart_preserved": (
            restored.context_causal_stability_assessments
            == engine.context_causal_stability_assessments
            and restored.latent_context_hypotheses
            == engine.latent_context_hypotheses
        ),
    }


def _cross_environment_causal_invariance() -> dict[str, Any]:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(6):
        engine.learn(
            observation=f"Sandbox release validation {index}.",
            goal=goal,
            action=action,
            outcome="correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.55,
        )
        engine.learn(
            observation=f"Production release validation {index}.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.8,
            predicted_success=0.70,
        )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed" and action in item.pattern
    )
    discovery = engine.discover_latent_context_hypotheses(parent.id)
    hypothesis = next(
        item
        for item in engine.latent_context_hypotheses
        if item.id == discovery.selected_hypothesis_id
    )

    stability_ids: list[int] = []
    signatures = (
        "code=v1;load=normal;data=fixed",
        "code=v1;load=high;data=fixed",
    )
    for environment_index, signature in enumerate(signatures):
        forward_ids: list[int] = []
        for batch in ("a", "b"):
            trial = engine.propose_context_causality_intervention(
                hypothesis.id,
                from_context="production",
                to_context="sandbox",
                controlled_signature=signature,
                min_samples=4,
            )
            trial = engine.observe_context_causality_intervention(
                trial.id,
                observed_target_success_rate=1.0,
                observed_signature=signature,
                sample_count=4,
                evidence_refs=(
                    f"invariance:{environment_index}:forward:{batch}",
                ),
            )
            forward_ids.append(trial.id)

        reverse = engine.propose_context_causality_intervention(
            hypothesis.id,
            from_context="sandbox",
            to_context="production",
            controlled_signature=signature,
            min_samples=4,
        )
        reverse = engine.observe_context_causality_intervention(
            reverse.id,
            observed_target_success_rate=0.0,
            observed_signature=signature,
            sample_count=4,
            evidence_refs=(
                f"invariance:{environment_index}:reverse:a",
            ),
        )
        stability = engine.assess_context_causal_stability(
            hypothesis.id,
            forward_trial_ids=forward_ids,
            reverse_trial_ids=(reverse.id,),
        )
        stability_ids.append(stability.id)

    invariance = engine.assess_context_causal_invariance(
        hypothesis.id,
        stability_assessment_ids=stability_ids,
    )
    final_hypothesis = next(
        item
        for item in engine.latent_context_hypotheses
        if item.id == hypothesis.id
    )
    narrative = engine.build_metacognitive_narrative(
        "context_causal_invariance"
    )
    restored = UnarchiEngine.from_export(engine.export_state())

    return {
        "name": "cross_environment_causal_invariance",
        "expected_direction": (
            "replicated reversible causality that survives two predefined "
            "controlled environments earns bounded environment-invariant status"
        ),
        "passed": (
            invariance.status == "environment_invariant"
            and invariance.distinct_environment_count == 2
            and invariance.stable_environment_count == 2
            and invariance.effect_direction_consistent is True
            and invariance.minimum_causal_strength >= 0.35
            and invariance.boundary_signatures == ()
            and final_hypothesis.causal_status == "environment_invariant"
            and restored.context_causal_invariance_assessments
            == engine.context_causal_invariance_assessments
            and restored.latent_context_hypotheses
            == engine.latent_context_hypotheses
            and narrative.unsupported_claims == 0
            and bool(narrative.evidence_refs)
        ),
        "status": invariance.status,
        "distinct_environment_count": invariance.distinct_environment_count,
        "stable_environment_count": invariance.stable_environment_count,
        "direction_consistent": invariance.effect_direction_consistent,
        "minimum_causal_strength": invariance.minimum_causal_strength,
        "strength_spread": invariance.strength_spread,
        "boundary_signatures": invariance.boundary_signatures,
        "confidence": invariance.confidence,
        "final_hypothesis_status": final_hypothesis.causal_status,
        "restart_preserved": (
            restored.context_causal_invariance_assessments
            == engine.context_causal_invariance_assessments
            and restored.latent_context_hypotheses
            == engine.latent_context_hypotheses
        ),
    }


def _active_context_boundary_discovery() -> dict[str, Any]:
    engine = UnarchiEngine()
    goal = "validate release evidence"
    action = "run automated release check"

    for index in range(6):
        engine.learn(
            observation=f"Sandbox release validation {index}.",
            goal=goal,
            action=action,
            outcome="correct evidence",
            success=True,
            reward=0.8,
            predicted_success=0.55,
        )
        engine.learn(
            observation=f"Production release validation {index}.",
            goal=goal,
            action=action,
            outcome="invalid evidence escaped",
            success=False,
            reward=-0.8,
            predicted_success=0.70,
        )

    parent = next(
        item
        for item in engine.consolidate_self_schema()
        if item.kind == "mixed" and action in item.pattern
    )
    discovery = engine.discover_latent_context_hypotheses(parent.id)
    hypothesis = next(
        item
        for item in engine.latent_context_hypotheses
        if item.id == discovery.selected_hypothesis_id
    )

    normal_forward: list[int] = []
    normal_signature = "code=v1;load=normal;data=fixed"
    for batch in ("a", "b"):
        trial = engine.propose_context_causality_intervention(
            hypothesis.id,
            from_context="production",
            to_context="sandbox",
            controlled_signature=normal_signature,
            min_samples=4,
        )
        trial = engine.observe_context_causality_intervention(
            trial.id,
            observed_target_success_rate=1.0,
            observed_signature=normal_signature,
            sample_count=4,
            evidence_refs=(f"boundary:normal:forward:{batch}",),
        )
        normal_forward.append(trial.id)
    normal_reverse = engine.propose_context_causality_intervention(
        hypothesis.id,
        from_context="sandbox",
        to_context="production",
        controlled_signature=normal_signature,
        min_samples=4,
    )
    normal_reverse = engine.observe_context_causality_intervention(
        normal_reverse.id,
        observed_target_success_rate=0.0,
        observed_signature=normal_signature,
        sample_count=4,
        evidence_refs=("boundary:normal:reverse:a",),
    )
    normal = engine.assess_context_causal_stability(
        hypothesis.id,
        forward_trial_ids=normal_forward,
        reverse_trial_ids=(normal_reverse.id,),
    )

    extreme_forward: list[int] = []
    extreme_signature = "code=v1;load=extreme;data=fixed"
    for batch in ("a", "b"):
        trial = engine.propose_context_causality_intervention(
            hypothesis.id,
            from_context="production",
            to_context="sandbox",
            controlled_signature=extreme_signature,
            min_samples=4,
        )
        trial = engine.observe_context_causality_intervention(
            trial.id,
            observed_target_success_rate=1.0,
            observed_signature=extreme_signature,
            sample_count=4,
            evidence_refs=(f"boundary:extreme:forward:{batch}",),
        )
        extreme_forward.append(trial.id)
    extreme_reverse = engine.propose_context_causality_intervention(
        hypothesis.id,
        from_context="sandbox",
        to_context="production",
        controlled_signature=extreme_signature,
        min_samples=4,
    )
    extreme_reverse = engine.observe_context_causality_intervention(
        extreme_reverse.id,
        observed_target_success_rate=1.0,
        observed_signature=extreme_signature,
        sample_count=4,
        evidence_refs=("boundary:extreme:reverse:a",),
    )
    extreme = engine.assess_context_causal_stability(
        hypothesis.id,
        forward_trial_ids=extreme_forward,
        reverse_trial_ids=(extreme_reverse.id,),
    )

    bounded = engine.assess_context_causal_invariance(
        hypothesis.id,
        stability_assessment_ids=(normal.id, extreme.id),
    )
    plan = engine.plan_context_boundary_discovery(
        hypothesis.id,
        invariance_assessment_id=bounded.id,
        candidate_risks={
            "code=v1;load=high;data=fixed": 0.08,
            "code=v1;load=normal;data=shifted": 0.05,
            "code=v2;load=extreme;data=shifted": 0.40,
        },
    )

    high_signature = plan.selected_signature
    high_forward: list[int] = []
    for batch in ("a", "b"):
        trial = engine.propose_context_causality_intervention(
            hypothesis.id,
            from_context="production",
            to_context="sandbox",
            controlled_signature=high_signature,
            min_samples=4,
        )
        trial = engine.observe_context_causality_intervention(
            trial.id,
            observed_target_success_rate=1.0,
            observed_signature=high_signature,
            sample_count=4,
            evidence_refs=(f"boundary:high:forward:{batch}",),
        )
        high_forward.append(trial.id)
    high_reverse = engine.propose_context_causality_intervention(
        hypothesis.id,
        from_context="sandbox",
        to_context="production",
        controlled_signature=high_signature,
        min_samples=4,
    )
    high_reverse = engine.observe_context_causality_intervention(
        high_reverse.id,
        observed_target_success_rate=0.0,
        observed_signature=high_signature,
        sample_count=4,
        evidence_refs=("boundary:high:reverse:a",),
    )
    high = engine.assess_context_causal_stability(
        hypothesis.id,
        forward_trial_ids=high_forward,
        reverse_trial_ids=(high_reverse.id,),
    )
    resolved = engine.observe_context_boundary_discovery(
        plan.id,
        stability_assessment_id=high.id,
    )

    narrative = engine.build_metacognitive_narrative(
        "context_boundary_discovery"
    )
    restored = UnarchiEngine.from_export(engine.export_state())

    return {
        "name": "active_context_boundary_discovery",
        "expected_direction": (
            "a low-risk one-dimension probe near a known stable/boundary pair "
            "is selected for information gain without external execution, then "
            "supplied stability evidence resolves the plan"
        ),
        "passed": (
            bounded.status == "environment_bounded"
            and extreme.status != "replicated_reversible"
            and plan.selected_signature == "code=v1;load=high;data=fixed"
            and plan.selected_risk <= 0.25
            and plan.external_execution_allowed is False
            and plan.paid_actions_allowed is False
            and plan.reversible_only is True
            and resolved.status == "resolved"
            and resolved.outcome_status == "expanded_valid_region"
            and resolved.uncertainty_reduction is not None
            and resolved.uncertainty_reduction > 0.0
            and restored.context_boundary_discovery_plans
            == engine.context_boundary_discovery_plans
            and narrative.unsupported_claims == 0
            and bool(narrative.evidence_refs)
        ),
        "bounded_status": bounded.status,
        "selected_signature": plan.selected_signature,
        "selected_risk": plan.selected_risk,
        "information_gain": plan.selected_information_gain,
        "priority": plan.selected_priority_score,
        "changed_dimensions": plan.changed_dimensions,
        "outcome_status": resolved.outcome_status,
        "uncertainty_reduction": resolved.uncertainty_reduction,
        "no_external_execution": not plan.external_execution_allowed,
        "restart_preserved": (
            restored.context_boundary_discovery_plans
            == engine.context_boundary_discovery_plans
        ),
    }


def run_unarchi_ablation_benchmark() -> dict[str, Any]:
    scenarios = [
        _failure_sensitization(),
        _success_adaptation(),
        _homeostatic_recovery(),
        _endogenous_goal_lifecycle(),
        _predictive_self_calibration(),
        _prospective_temporal_continuity(),
        _metacognitive_retrospective_fidelity(),
        _conflict_arbitration_self_correction(),
        _causal_hypothesis_revision(),
        _intervention_aware_self_world_revision(),
        _recurrent_global_workspace_integration(),
        _counterfactual_recurrent_information_gain(),
        _autobiographical_self_schema_transfer(),
        _contradiction_driven_self_schema_revision(),
        _context_sensitive_self_schema_decomposition(),
        _context_transfer_boundary_learning(),
        _latent_context_hypothesis_discovery(),
        _context_causality_intervention_support(),
        _replicated_reversible_context_causality(),
        _cross_environment_causal_invariance(),
        _active_context_boundary_discovery(),
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
