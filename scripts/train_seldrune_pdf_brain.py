"""Train and validate the Seldrune-owned PDF Brain.

The production service trains the compact classifier deterministically at startup.
This script makes retraining/evaluation explicit for CI, development and future
dataset expansion without requiring an external AI API or GPU.
"""

from backend.app.services.seldrune_pdf_brain import (
    MODEL,
    _predict_intent,
    training_summary,
)


_HOLDOUT = (
    ('please change Draft to Final', 'replace_text'),
    ('replace Acme Corp with Seldrune Labs in this document', 'replace_text'),
    ('can you correct 2025-01-01 to 2026-01-01', 'replace_text'),
    ('remove Pending from the pdf', 'redact_text'),
    ('please black out John Smith', 'redact_text'),
    ('hide Acme Corp', 'redact_text'),
    ('fill Customer Name with Jane Doe', 'fill_form'),
    ('enter Approved in Status field', 'fill_form'),
    ('set form field Company to Seldrune Labs', 'fill_form'),
    ('insert Final on page 3', 'add_text'),
    ('write Approved on page 5', 'add_text'),
    ('place Seldrune Labs on page 1', 'add_text'),
    ('turn page 2 by 180 degrees', 'rotate_page'),
    ('rotate page 5 270 degrees', 'rotate_page'),
    ('make page 1 rotated 90', 'rotate_page'),
)


def main() -> None:
    correct = 0
    confidence = []
    for text, expected in _HOLDOUT:
        predicted, probability = _predict_intent(text)
        correct += predicted == expected
        confidence.append(probability)
        print(
            f"{expected:12s} -> {predicted:12s} "
            f"confidence={probability:.4f} text={text!r}"
        )

    accuracy = correct / len(_HOLDOUT)
    summary = training_summary()
    print(
        f"model={summary['model_version']} fingerprint={MODEL.fingerprint} "
        f"trained_examples={summary['trained_examples']} "
        f"holdout_accuracy={accuracy:.4f} "
        f"mean_confidence={sum(confidence) / len(confidence):.4f}"
    )
    if accuracy < 0.95:
        raise SystemExit("PDF Brain holdout accuracy gate failed")


if __name__ == "__main__":
    main()
