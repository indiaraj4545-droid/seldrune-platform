from backend.app.services.unarchi_benchmark import run_unarchi_ablation_benchmark


def test_unarchi_ablation_benchmark_passes_all_scenarios() -> None:
    result = run_unarchi_ablation_benchmark()

    assert result["scenario_count"] == 3
    assert result["passed_scenarios"] == 3
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
