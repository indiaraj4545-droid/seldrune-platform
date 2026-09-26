from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Literal


VerificationVerdict = Literal["pass", "fail", "inconclusive"]
VerificationStatus = Literal[
    "verified",
    "rejected",
    "needs_escalation",
    "unverified_exhausted",
]


@dataclass(frozen=True)
class ModelVerifierCandidate:
    verifier_id: str
    provider: str
    model: str
    capabilities: tuple[str, ...]
    estimated_cost_usd: float
    confidence: float
    allowed: bool = True


@dataclass(frozen=True)
class ModelVerificationPlan:
    source_provider: str
    source_model: str
    output_sha256: str
    required_capabilities: tuple[str, ...]
    max_total_cost_usd: float
    ordered_candidates: tuple[ModelVerifierCandidate, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ModelVerificationAttempt:
    verifier_id: str
    output_sha256: str
    verdict: VerificationVerdict
    evidence_refs: tuple[str, ...]
    actual_cost_usd: float = 0.0


@dataclass(frozen=True)
class ModelVerificationDecision:
    status: VerificationStatus
    output_sha256: str
    attempts_used: int
    total_cost_usd: float
    next_verifier_id: str | None
    evidence_refs: tuple[str, ...]
    terminal_verifier_id: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalize_capabilities(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value.strip().lower().replace("-", "_")
            for value in values
            if value.strip()
        )
    )


def _output_digest(output_text: str) -> str:
    payload = output_text.strip()
    if not payload:
        raise ValueError("model output cannot be empty")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def plan_independent_verification(
    *,
    source_provider: str,
    source_model: str,
    output_text: str,
    required_capabilities: tuple[str, ...],
    candidates: tuple[ModelVerifierCandidate, ...],
    max_total_cost_usd: float,
    minimum_confidence: float = 0.50,
) -> ModelVerificationPlan:
    """
    Build a cheapest-first independent verifier plan.

    This function never executes a model. It only determines which verifier
    candidates are eligible and the order in which an external caller may try
    them.
    """
    if max_total_cost_usd < 0:
        raise ValueError("max_total_cost_usd cannot be negative")
    if not 0.0 <= minimum_confidence <= 1.0:
        raise ValueError("minimum_confidence must be within 0..1")

    source_provider = source_provider.strip()
    source_model = source_model.strip()
    if not source_provider or not source_model:
        raise ValueError("source provider and model are required")

    required = _normalize_capabilities(required_capabilities)
    if not required:
        raise ValueError("at least one verifier capability is required")

    eligible: list[ModelVerifierCandidate] = []
    required_set = set(required)
    for candidate in candidates:
        verifier_id = candidate.verifier_id.strip()
        provider = candidate.provider.strip()
        model = candidate.model.strip()
        if not candidate.allowed or not verifier_id or not provider or not model:
            continue
        if (
            provider.casefold() == source_provider.casefold()
            and model.casefold() == source_model.casefold()
        ):
            continue
        if candidate.estimated_cost_usd < 0:
            raise ValueError("verifier estimated cost cannot be negative")
        if candidate.estimated_cost_usd > max_total_cost_usd:
            continue
        if not 0.0 <= candidate.confidence <= 1.0:
            raise ValueError("verifier confidence must be within 0..1")
        if candidate.confidence < minimum_confidence:
            continue
        available = set(_normalize_capabilities(candidate.capabilities))
        if not required_set.issubset(available):
            continue
        eligible.append(candidate)

    eligible.sort(
        key=lambda item: (
            item.estimated_cost_usd,
            -item.confidence,
            item.verifier_id,
        )
    )
    if not eligible:
        raise ValueError(
            "no independent verifier satisfies capability, confidence, and "
            "budget constraints"
        )

    return ModelVerificationPlan(
        source_provider=source_provider,
        source_model=source_model,
        output_sha256=_output_digest(output_text),
        required_capabilities=required,
        max_total_cost_usd=float(max_total_cost_usd),
        ordered_candidates=tuple(eligible),
    )


def evaluate_verification_attempts(
    plan: ModelVerificationPlan,
    *,
    attempts: tuple[ModelVerificationAttempt, ...],
) -> ModelVerificationDecision:
    """
    Evaluate verifier attempts while enforcing cheapest-first escalation.

    Every attempt must carry provenance evidence and match the source-output
    digest. A later verifier cannot be used until every cheaper earlier verifier
    has produced a terminal fail or inconclusive result.
    """
    if not attempts:
        return ModelVerificationDecision(
            status="needs_escalation",
            output_sha256=plan.output_sha256,
            attempts_used=0,
            total_cost_usd=0.0,
            next_verifier_id=plan.ordered_candidates[0].verifier_id,
            evidence_refs=(),
            terminal_verifier_id=None,
        )

    if len(attempts) > len(plan.ordered_candidates):
        raise ValueError("verification attempt count exceeds planned candidates")

    total_cost = 0.0
    refs: list[str] = []
    last_verdict: VerificationVerdict | None = None
    last_verifier: str | None = None

    for index, attempt in enumerate(attempts):
        expected = plan.ordered_candidates[index]
        if attempt.verifier_id != expected.verifier_id:
            raise ValueError(
                "verification escalation skipped a cheaper or earlier verifier"
            )
        if attempt.output_sha256 != plan.output_sha256:
            raise ValueError("verification attempt output digest mismatch")
        if attempt.verdict not in {"pass", "fail", "inconclusive"}:
            raise ValueError("unsupported verification verdict")
        attempt_refs = tuple(
            dict.fromkeys(ref.strip() for ref in attempt.evidence_refs if ref.strip())
        )
        if not attempt_refs:
            raise ValueError("verification attempt requires provenance evidence")
        if attempt.actual_cost_usd < 0:
            raise ValueError("verification attempt cost cannot be negative")

        total_cost += attempt.actual_cost_usd
        if total_cost > plan.max_total_cost_usd + 1e-12:
            raise ValueError("verification attempts exceeded total cost budget")
        refs.extend(attempt_refs)
        last_verdict = attempt.verdict
        last_verifier = attempt.verifier_id

        if attempt.verdict == "pass":
            return ModelVerificationDecision(
                status="verified",
                output_sha256=plan.output_sha256,
                attempts_used=index + 1,
                total_cost_usd=round(total_cost, 8),
                next_verifier_id=None,
                evidence_refs=tuple(dict.fromkeys(refs)),
                terminal_verifier_id=attempt.verifier_id,
            )

    used = len(attempts)
    if used < len(plan.ordered_candidates):
        next_candidate = plan.ordered_candidates[used]
        if total_cost + next_candidate.estimated_cost_usd <= (
            plan.max_total_cost_usd + 1e-12
        ):
            return ModelVerificationDecision(
                status="needs_escalation",
                output_sha256=plan.output_sha256,
                attempts_used=used,
                total_cost_usd=round(total_cost, 8),
                next_verifier_id=next_candidate.verifier_id,
                evidence_refs=tuple(dict.fromkeys(refs)),
                terminal_verifier_id=last_verifier,
            )

    return ModelVerificationDecision(
        status=(
            "rejected"
            if last_verdict == "fail"
            else "unverified_exhausted"
        ),
        output_sha256=plan.output_sha256,
        attempts_used=used,
        total_cost_usd=round(total_cost, 8),
        next_verifier_id=None,
        evidence_refs=tuple(dict.fromkeys(refs)),
        terminal_verifier_id=last_verifier,
    )
