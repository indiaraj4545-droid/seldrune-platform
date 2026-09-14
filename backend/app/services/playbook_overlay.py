def merge_playbook(adaptive: dict, playbook: dict) -> dict:
    if not playbook.get("applied"):
        return adaptive
    result = dict(adaptive)
    actions = set(playbook.get("actions") or [])
    recommendations = list(result.get("recommendations") or [])
    if "ensure_research_step" in actions:
        recommendations.append("preserve_research_preflight_for_similar_work")
    if "ensure_validation_step" in actions:
        recommendations.append("review_failed_capabilities_before_repeating_similar_work")
    result["recommendations"] = list(dict.fromkeys(recommendations))[:6]
    result["advisories"] = list(
        dict.fromkeys(list(result.get("advisories") or []) + list(playbook.get("advice") or []))
    )[:6]
    result["applied"] = True
    return result
