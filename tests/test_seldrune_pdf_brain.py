import pymupdf

from backend.app.services.pdf_local_ocr import OCRMatch
from backend.app.services.seldrune_pdf_brain import (
    MODEL_VERSION,
    predict_pdf_plan,
    training_summary,
    try_local_pdf_edit,
)


def _text_pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    output = document.tobytes()
    document.close()
    return output


def test_pdf_brain_is_trained_deterministically() -> None:
    summary = training_summary()

    assert summary["model_version"] == MODEL_VERSION
    assert summary["trained_examples"] == 540
    assert summary["vocabulary_size"] > 50
    assert summary["intents"] == [
        "add_text",
        "fill_form",
        "redact_text",
        "replace_text",
        "rotate_page",
    ]
    assert len(summary["fingerprint"]) == 16


def test_pdf_brain_understands_native_replace_without_external_ai() -> None:
    prediction = predict_pdf_plan('replace "OLD" with "NEW"')

    assert prediction.usable is True
    assert prediction.intent == "replace_text"
    assert prediction.confidence >= 0.78
    assert prediction.plan is not None
    operation = prediction.plan["operations"][0]
    assert operation["target_text"] == "OLD"
    assert operation["replacement_text"] == "NEW"


def test_pdf_brain_applies_and_verifies_native_text_edit() -> None:
    local = try_local_pdf_edit(
        _text_pdf("Status: OLD"),
        'change "OLD" to "NEW"',
    )

    assert local is not None
    assert local.prediction.model_version == MODEL_VERSION
    assert local.result.verification_score == 100
    assert local.assessment.safe_to_return is True

    edited = pymupdf.open(stream=local.result.data, filetype="pdf")
    text = edited[0].get_text()
    edited.close()
    assert "NEW" in text
    assert "OLD" not in text


def test_pdf_brain_falls_back_for_scanned_target_replacement() -> None:
    document = pymupdf.open()
    page = document.new_page(width=400, height=300)
    page.draw_rect(
        pymupdf.Rect(40, 40, 360, 260),
        color=(0.8, 0.8, 0.8),
        fill=(0.96, 0.96, 0.96),
    )
    source = document.tobytes()
    document.close()

    local = try_local_pdf_edit(
        source,
        'replace "OLD" with "NEW"',
    )

    assert local is None


def test_pdf_brain_handles_zero_cost_rotation() -> None:
    source = _text_pdf("Rotate me")

    local = try_local_pdf_edit(source, "rotate page 1 90 degrees")

    assert local is not None
    assert local.result.verification_score == 100
    output = pymupdf.open(stream=local.result.data, filetype="pdf")
    assert output[0].rotation == 90
    output.close()


def test_deterministic_pdf_command_bypasses_classifier_threshold() -> None:
    prediction = predict_pdf_plan(
        'replace "OLD" with "NEW"',
        minimum_confidence=0.99,
    )

    assert prediction.usable is True
    assert prediction.intent == "replace_text"
    assert prediction.confidence == 1.0


def test_pdf_brain_uses_local_ocr_for_scanned_replacement(monkeypatch) -> None:
    document = pymupdf.open()
    page = document.new_page(width=400, height=300)
    page.draw_rect(
        pymupdf.Rect(40, 40, 360, 260),
        color=(0.8, 0.8, 0.8),
        fill=(0.96, 0.96, 0.96),
    )
    source = document.tobytes()
    document.close()

    monkeypatch.setattr(
        "backend.app.services.seldrune_pdf_brain.locate_text_with_ocr",
        lambda *args, **kwargs: [
            OCRMatch(
                page=1,
                bbox=[200.0, 300.0, 650.0, 420.0],
                text="old",
                confidence=98.0,
            )
        ],
    )

    local = try_local_pdf_edit(
        source,
        'replace "OLD" with "NEW"',
        allow_ocr=True,
    )

    assert local is not None
    assert local.ocr_used is True
    assert local.result.verification_score == 100
    assert local.assessment.safe_to_return is True
    output = pymupdf.open(stream=local.result.data, filetype="pdf")
    assert "NEW" in output[0].get_text()
    output.close()
