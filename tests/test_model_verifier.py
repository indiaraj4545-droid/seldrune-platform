from __future__ import annotations

import hashlib

import pytest

from backend.app.services.model_verifier import (
    ModelVerificationAttempt,
    ModelVerifierCandidate,
    evaluate_verification_attempts,
    plan_independent_verification,
)


def _candidates():
    return (
        ModelVerifierCandidate(
            verifier_id="cheap-structured-check",
            provider="openai_compatible",
            model="verifier-small",
            capabilities=("text", "structured_output"),
            estimated_cost_usd=0.01,
            confidence=0.82,
        ),
        ModelVerifierCandidate(
            verifier_id="premium-independent-check",
            provider="openai",
            model="verifier-large",
            capabilities=("text", "structured_output", "reasoning"),
            estimated_cost_usd=0.05,
            confidence=0.96,
        ),
        ModelVerifierCandidate(
            verifier_id="same-source-model",
            provider="openai",
            model="source-model",
            capabilities=("text", "structured_output", "reasoning"),
            estimated_cost_usd=0.0,
            confidence=1.0,
        ),
    )


def _plan():
    return plan_independent_verification(
        source_provider="openai",
        source_model="source-model",
        output_text='{"decision":"ship","confidence":0.8}',
        required_capabilities=("text", "structured_output"),
        candidates=_candidates(),
        max_total_cost_usd=0.10,
        minimum_confidence=0.75,
    )


def test_verifier_plan_is_independent_and_cheapest_first() -> None:
    plan = _plan()

    assert [item.verifier_id for item in plan.ordered_candidates] == [
        "cheap-structured-check",
        "premium-independent-check",
    ]
    assert plan.output_sha256 == hashlib.sha256(
        b'{"decision":"ship","confidence":0.8}'
    ).hexdigest()


def test_cheap_success_stops_escalation() -> None:
    plan = _plan()
    first = evaluate_verification_attempts(plan, attempts=())

    assert first.status == "needs_escalation"
    assert first.next_verifier_id == "cheap-structured-check"

    decision = evaluate_verification_attempts(
        plan,
        attempts=(
            ModelVerificationAttempt(
                verifier_id="cheap-structured-check",
                output_sha256=plan.output_sha256,
                verdict="pass",
                evidence_refs=("verifier-run:cheap:1", "receipt:cheap:1"),
                actual_cost_usd=0.008,
            ),
        ),
    )

    assert decision.status == "verified"
    assert decision.next_verifier_id is None
    assert decision.attempts_used == 1
    assert decision.terminal_verifier_id == "cheap-structured-check"
    assert decision.total_cost_usd == 0.008


def test_inconclusive_cheap_verifier_allows_expensive_fallback() -> None:
    plan = _plan()
    first_attempt = ModelVerificationAttempt(
        verifier_id="cheap-structured-check",
        output_sha256=plan.output_sha256,
        verdict="inconclusive",
        evidence_refs=("verifier-run:cheap:2",),
        actual_cost_usd=0.008,
    )
    interim = evaluate_verification_attempts(
        plan,
        attempts=(first_attempt,),
    )

    assert interim.status == "needs_escalation"
    assert interim.next_verifier_id == "premium-independent-check"

    final = evaluate_verification_attempts(
        plan,
        attempts=(
            first_attempt,
            ModelVerificationAttempt(
                verifier_id="premium-independent-check",
                output_sha256=plan.output_sha256,
                verdict="pass",
                evidence_refs=("verifier-run:premium:1", "receipt:premium:1"),
                actual_cost_usd=0.045,
            ),
        ),
    )

    assert final.status == "verified"
    assert final.attempts_used == 2
    assert final.total_cost_usd == 0.053
    assert final.terminal_verifier_id == "premium-independent-check"


def test_skipping_cheaper_verifier_fails_closed() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="skipped"):
        evaluate_verification_attempts(
            plan,
            attempts=(
                ModelVerificationAttempt(
                    verifier_id="premium-independent-check",
                    output_sha256=plan.output_sha256,
                    verdict="pass",
                    evidence_refs=("receipt:premium:skip",),
                    actual_cost_usd=0.045,
                ),
            ),
        )


def test_unproven_or_wrong_digest_attempt_fails_closed() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="provenance"):
        evaluate_verification_attempts(
            plan,
            attempts=(
                ModelVerificationAttempt(
                    verifier_id="cheap-structured-check",
                    output_sha256=plan.output_sha256,
                    verdict="pass",
                    evidence_refs=(),
                    actual_cost_usd=0.008,
                ),
            ),
        )

    with pytest.raises(ValueError, match="digest"):
        evaluate_verification_attempts(
            plan,
            attempts=(
                ModelVerificationAttempt(
                    verifier_id="cheap-structured-check",
                    output_sha256="0" * 64,
                    verdict="pass",
                    evidence_refs=("receipt:wrong-digest",),
                    actual_cost_usd=0.008,
                ),
            ),
        )


def test_exhausted_failure_is_rejected() -> None:
    plan = _plan()
    attempts = (
        ModelVerificationAttempt(
            verifier_id="cheap-structured-check",
            output_sha256=plan.output_sha256,
            verdict="fail",
            evidence_refs=("receipt:cheap:fail",),
            actual_cost_usd=0.008,
        ),
        ModelVerificationAttempt(
            verifier_id="premium-independent-check",
            output_sha256=plan.output_sha256,
            verdict="fail",
            evidence_refs=("receipt:premium:fail",),
            actual_cost_usd=0.045,
        ),
    )

    decision = evaluate_verification_attempts(plan, attempts=attempts)

    assert decision.status == "rejected"
    assert decision.next_verifier_id is None
    assert decision.attempts_used == 2
