from backend.app.services.unarchi_benchmark import run_unarchi_ablation_benchmark


def test_unarchi_ablation_benchmark_passes_all_scenarios() -> None:
    result = run_unarchi_ablation_benchmark()

    assert result["scenario_count"] == 5
    assert result["passed_scenarios"] == 5
    assert result["pass_rate"] == 1.0
    assert result["claims_phenomenal_consciousness"] is False


def test_unarchi_benchmark_contains_causal_comparisons() -> None:
    result = run_unarchi_ablation_benchmark()
    scenarios = {item["name"]: item for item in result["scenarios"]}

    failure = scenarios["failure_sensitization"]
    success = scenarios["success_adaptation"]

    assert failure["comparison"]["state_causally_active"] is True
    assert failure["comparison"]["risk_delta"] > 0
    assert success["comparison"]["risk_delta"] < 0


def test_unarchi_benchmark_covers_endogenous_goal_lifecycle() -> None:
    result = run_unarchi_ablation_benchmark()
    scenarios = {item["name"]: item for item in result["scenarios"]}

    endogenous = scenarios["endogenous_goal_lifecycle"]

    assert endogenous["created"] is True
    assert endogenous["bounded"] is True
    assert endogenous["zero_cost_only"] is True
    assert endogenous["resolved"] is True
    assert endogenous["passed"] is True


def test_unarchi_benchmark_covers_predictive_self_calibration() -> None:
    result = run_unarchi_ablation_benchmark()
    scenarios = {item["name"]: item for item in result["scenarios"]}

    calibration = scenarios["predictive_self_calibration"]

    assert calibration["passed"] is True
    assert (
        calibration["second_success_error"]
        < calibration["first_success_error"]
    )
    assert 0.0 <= calibration["self_calibration_score"] <= 1.0
