from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import random
import re
from typing import Any

from backend.app.services.pdf_editor import (
    PDFEditAssessment,
    PDFEditResult,
    PDFEditorError,
    apply_pdf_edit_plan,
    assess_pdf_edit_candidate,
    inspect_pdf,
    validate_pdf_edit_plan,
)

MODEL_VERSION = "seldrune-pdf-brain-v0.1"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_QUOTE = r'(?:"([^"]+)"|\'([^\']+)\'|“([^”]+)”|‘([^’]+)’)'
_PAGE_RE = re.compile(r"\bpage\s+(\d+)\b", re.IGNORECASE)
_OCCURRENCE_RE = re.compile(
    r"\b(?:occurrence|instance|match)\s+(\d+)\b", re.IGNORECASE
)

_TRAINING_TEMPLATES: dict[str, tuple[str, ...]] = {
    "replace_text": (
        "replace {a} with {b}",
        "change {a} to {b}",
        "update {a} to {b}",
        "edit {a} and make it {b}",
        "modify {a} into {b}",
        "correct {a} to {b}",
        "swap {a} for {b}",
        "set {a} as {b}",
        "make {a} read {b}",
        "in the pdf replace {a} with {b}",
        "change the value {a} into {b}",
    ),
    "redact_text": (
        "redact {a}",
        "remove {a}",
        "hide {a}",
        "black out {a}",
        "erase {a}",
        "delete the text {a}",
        "mask {a}",
        "cover {a}",
        "remove sensitive text {a}",
    ),
    "fill_form": (
        "fill field {a} with {b}",
        "set field {a} to {b}",
        "enter {b} in {a}",
        "put {b} in the {a} field",
        "complete {a} as {b}",
        "update form field {a} to {b}",
    ),
    "add_text": (
        "add text {b} on page {p}",
        "insert {b} on page {p}",
        "write {b} on page {p}",
        "add a note {b} to page {p}",
        "place {b} on page {p}",
        "append {b} on page {p}",
    ),
    "rotate_page": (
        "rotate page {p} {d} degrees",
        "turn page {p} by {d} degrees",
        "rotate the page {p} {d} degrees",
        "make page {p} rotated {d}",
    ),
}

_TRAINING_A = (
    "OLD",
    "2025-01-01",
    "450000",
    "John Smith",
    "Draft",
    "Acme Corp",
    "Pending",
    "0",
)
_TRAINING_B = (
    "NEW",
    "2026-01-01",
    "500000",
    "Jane Doe",
    "Final",
    "Seldrune Labs",
    "Approved",
    "1",
)
_TRAINING_PAGES = ("1", "2", "3", "5")
_TRAINING_DEGREES = ("90", "180", "270")


@dataclass(frozen=True)
class _NBClass:
    documents: int
    total_tokens: int
    token_counts: Counter[str]


@dataclass(frozen=True)
class PDFBrainModel:
    classes: dict[str, _NBClass]
    vocab: frozenset[str]
    documents: int
    fingerprint: str


@dataclass(frozen=True)
class PDFBrainPrediction:
    model_version: str
    model_fingerprint: str
    intent: str | None
    confidence: float
    plan: dict[str, Any] | None
    fallback_reason: str | None

    @property
    def usable(self) -> bool:
        return self.plan is not None and self.fallback_reason is None


@dataclass(frozen=True)
class LocalPDFEdit:
    prediction: PDFBrainPrediction
    result: PDFEditResult
    assessment: PDFEditAssessment


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())


def _training_examples() -> list[tuple[str, str]]:
    rng = random.Random(7)
    examples: list[tuple[str, str]] = []
    for label, templates in _TRAINING_TEMPLATES.items():
        for template in templates:
            for _ in range(15):
                examples.append(
                    (
                        template.format(
                            a=rng.choice(_TRAINING_A),
                            b=rng.choice(_TRAINING_B),
                            p=rng.choice(_TRAINING_PAGES),
                            d=rng.choice(_TRAINING_DEGREES),
                        ),
                        label,
                    )
                )
    return examples


def train_pdf_brain() -> PDFBrainModel:
    examples = _training_examples()
    counts: dict[str, Counter[str]] = {}
    class_documents: Counter[str] = Counter()
    class_total_tokens: Counter[str] = Counter()
    vocab: set[str] = set()

    for text, label in examples:
        tokens = _tokens(text)
        class_documents[label] += 1
        class_total_tokens[label] += len(tokens)
        counts.setdefault(label, Counter()).update(tokens)
        vocab.update(tokens)

    classes = {
        label: _NBClass(
            documents=class_documents[label],
            total_tokens=class_total_tokens[label],
            token_counts=counts[label],
        )
        for label in sorted(counts)
    }
    serializable = {
        "version": MODEL_VERSION,
        "documents": len(examples),
        "vocab": sorted(vocab),
        "classes": {
            label: {
                "documents": item.documents,
                "total_tokens": item.total_tokens,
                "token_counts": dict(sorted(item.token_counts.items())),
            }
            for label, item in classes.items()
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(serializable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return PDFBrainModel(
        classes=classes,
        vocab=frozenset(vocab),
        documents=len(examples),
        fingerprint=fingerprint,
    )


MODEL = train_pdf_brain()


def _predict_intent(instruction: str) -> tuple[str, float]:
    tokens = _tokens(instruction)
    vocabulary_size = max(1, len(MODEL.vocab))
    scores: dict[str, float] = {}
    for label, item in MODEL.classes.items():
        score = math.log(item.documents / MODEL.documents)
        denominator = item.total_tokens + vocabulary_size
        for token in tokens:
            score += math.log((item.token_counts.get(token, 0) + 1) / denominator)
        scores[label] = score

    maximum = max(scores.values())
    exponentials = {label: math.exp(value - maximum) for label, value in scores.items()}
    total = sum(exponentials.values())
    probabilities = {label: value / total for label, value in exponentials.items()}
    label = max(probabilities, key=probabilities.get)
    return label, probabilities[label]


def _clean_slot(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip('"\'“”‘’').strip()
    cleaned = re.sub(
        r"\s+(?:in|on)\s+(?:this|the)\s+(?:pdf|document)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or None


def _page(instruction: str) -> int | None:
    match = _PAGE_RE.search(instruction)
    return int(match.group(1)) if match else None


def _occurrence(instruction: str) -> int | None:
    match = _OCCURRENCE_RE.search(instruction)
    return int(match.group(1)) if match else None


def _empty_operation(action: str, *, page: int | None) -> dict[str, Any]:
    return {
        "action": action,
        "page": page,
        "target_text": None,
        "replacement_text": None,
        "text": None,
        "bbox": None,
        "occurrence": None,
        "field_name": None,
        "value": None,
        "degrees": None,
        "font_size": None,
        "font_family_hint": None,
        "font_weight": None,
        "font_style": None,
        "alignment": None,
        "text_color": None,
        "background_color": None,
    }


def _quoted_values(text: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(_QUOTE, text):
        for group in match.groups():
            if group is not None:
                values.append(group.strip())
                break
    return values


def _replace_operation(instruction: str) -> dict[str, Any] | None:
    quoted = _quoted_values(instruction)
    target: str | None = None
    replacement: str | None = None
    if len(quoted) >= 2:
        target, replacement = quoted[0], quoted[1]
    else:
        patterns = (
            r"\b(?:replace|change|update|correct)\s+(.+?)\s+(?:with|to|into)\s+(.+)$",
            r"\bswap\s+(.+?)\s+for\s+(.+)$",
            r"\bmake\s+(.+?)\s+read\s+(.+)$",
            r"\bedit\s+(.+?)\s+and\s+make\s+it\s+(.+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, instruction, re.IGNORECASE)
            if match:
                target = _clean_slot(match.group(1))
                replacement = _clean_slot(match.group(2))
                break
    target, replacement = _clean_slot(target), _clean_slot(replacement)
    if not target or replacement is None:
        return None
    operation = _empty_operation("replace_text", page=_page(instruction))
    operation["target_text"] = target
    operation["replacement_text"] = replacement
    operation["occurrence"] = _occurrence(instruction)
    return operation


def _redact_operation(instruction: str) -> dict[str, Any] | None:
    quoted = _quoted_values(instruction)
    target = quoted[0] if quoted else None
    if target is None:
        match = re.search(
            r"\b(?:redact|remove|hide|erase|mask|cover|delete(?:\s+the\s+text)?|black\s+out)"
            r"\s+(.+)$",
            instruction,
            re.IGNORECASE,
        )
        if match:
            target = _clean_slot(match.group(1))
    target = _clean_slot(target)
    if not target:
        return None
    operation = _empty_operation("redact_text", page=_page(instruction))
    operation["target_text"] = target
    operation["occurrence"] = _occurrence(instruction)
    return operation


def _fill_form_operation(instruction: str) -> dict[str, Any] | None:
    quoted = _quoted_values(instruction)
    field: str | None = None
    value: str | None = None
    if len(quoted) >= 2:
        field, value = quoted[0], quoted[1]
    else:
        patterns = (
            r"\b(?:fill|set|update)\s+(?:form\s+)?field\s+(.+?)\s+(?:with|to|as)\s+(.+)$",
            r"\benter\s+(.+?)\s+in\s+(?:the\s+)?(.+?)\s+field\b",
            r"\bput\s+(.+?)\s+in\s+(?:the\s+)?(.+?)\s+field\b",
        )
        for index, pattern in enumerate(patterns):
            match = re.search(pattern, instruction, re.IGNORECASE)
            if not match:
                continue
            if index == 0:
                field, value = match.group(1), match.group(2)
            else:
                value, field = match.group(1), match.group(2)
            break
    field, value = _clean_slot(field), _clean_slot(value)
    if not field or value is None:
        return None
    operation = _empty_operation("fill_form", page=_page(instruction))
    operation["field_name"] = field
    operation["value"] = value
    return operation


def _add_text_operation(instruction: str) -> dict[str, Any] | None:
    page = _page(instruction)
    if page is None:
        return None
    quoted = _quoted_values(instruction)
    value = quoted[0] if quoted else None
    if value is None:
        match = re.search(
            r"\b(?:add(?:\s+(?:text|a\s+note))?|insert|write|place|append)\s+(.+?)"
            r"\s+(?:on|to)\s+page\s+\d+\b",
            instruction,
            re.IGNORECASE,
        )
        if match:
            value = match.group(1)
    value = _clean_slot(value)
    if not value:
        return None
    operation = _empty_operation("add_text", page=page)
    operation["text"] = value
    return operation


def _rotate_operation(instruction: str) -> dict[str, Any] | None:
    page = _page(instruction)
    if page is None:
        return None
    degree_match = re.search(r"\b(0|90|180|270)\s*(?:degrees?)?\b", instruction)
    if not degree_match:
        return None
    operation = _empty_operation("rotate_page", page=page)
    operation["degrees"] = int(degree_match.group(1))
    return operation


_PARSERS = {
    "replace_text": _replace_operation,
    "redact_text": _redact_operation,
    "fill_form": _fill_form_operation,
    "add_text": _add_text_operation,
    "rotate_page": _rotate_operation,
}


def predict_pdf_plan(
    instruction: str,
    *,
    minimum_confidence: float = 0.78,
) -> PDFBrainPrediction:
    intent, confidence = _predict_intent(instruction)
    if confidence < minimum_confidence:
        return PDFBrainPrediction(
            model_version=MODEL_VERSION,
            model_fingerprint=MODEL.fingerprint,
            intent=intent,
            confidence=confidence,
            plan=None,
            fallback_reason="local intent confidence below threshold",
        )

    parser = _PARSERS.get(intent)
    operation = parser(instruction) if parser else None
    if operation is None:
        return PDFBrainPrediction(
            model_version=MODEL_VERSION,
            model_fingerprint=MODEL.fingerprint,
            intent=intent,
            confidence=confidence,
            plan=None,
            fallback_reason="local slot parser could not safely resolve the instruction",
        )

    return PDFBrainPrediction(
        model_version=MODEL_VERSION,
        model_fingerprint=MODEL.fingerprint,
        intent=intent,
        confidence=confidence,
        plan={
            "summary": f"Local {MODEL_VERSION} {intent} plan",
            "operations": [operation],
        },
        fallback_reason=None,
    )


def try_local_pdf_edit(
    pdf_bytes: bytes,
    instruction: str,
    *,
    password: str | None = None,
    minimum_confidence: float = 0.78,
) -> LocalPDFEdit | None:
    prediction = predict_pdf_plan(
        instruction,
        minimum_confidence=minimum_confidence,
    )
    if not prediction.usable or prediction.plan is None:
        return None

    inspection = inspect_pdf(pdf_bytes, password)
    if (
        prediction.intent in {"replace_text", "redact_text"}
        and inspection.native_text_pages == 0
    ):
        return None

    validation = validate_pdf_edit_plan(
        pdf_bytes,
        prediction.plan,
        password=password,
    )
    if not validation.valid:
        return None

    try:
        result = apply_pdf_edit_plan(
            pdf_bytes,
            prediction.plan,
            password=password,
        )
    except PDFEditorError:
        return None

    assessment = assess_pdf_edit_candidate(
        pdf_bytes,
        result.data,
        prediction.plan,
        password=password,
        visual_fidelity_score=result.visual_fidelity_score,
    )
    if not assessment.safe_to_return or result.verification_score < 100:
        return None
    return LocalPDFEdit(
        prediction=prediction,
        result=result,
        assessment=assessment,
    )


def training_summary() -> dict[str, Any]:
    return {
        "model_version": MODEL_VERSION,
        "algorithm": "multinomial-naive-bayes + deterministic slot parser",
        "trained_examples": MODEL.documents,
        "vocabulary_size": len(MODEL.vocab),
        "intents": sorted(MODEL.classes),
        "fingerprint": MODEL.fingerprint,
    }
