from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import csv
import io
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable

import pymupdf


@dataclass(frozen=True)
class OCRMatch:
    page: int
    bbox: list[float]
    text: str
    confidence: float


@dataclass(frozen=True)
class _OCRWord:
    text: str
    confidence: float
    left: float
    top: float
    right: float
    bottom: float


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _numeric_ratio(value: str) -> float:
    compact = re.sub(r"\s+", "", value)
    alnum = [char for char in compact if char.isalnum()]
    if not alnum:
        return 0.0
    return sum(char.isdigit() for char in alnum) / len(alnum)


def _numeric_key(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def _parse_tsv(tsv: str, *, width: int, height: int) -> list[_OCRWord]:
    words: list[_OCRWord] = []
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    for row in reader:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row.get("conf") or -1)
            left = float(row.get("left") or 0)
            top = float(row.get("top") or 0)
            box_width = float(row.get("width") or 0)
            box_height = float(row.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if confidence < 25 or box_width <= 0 or box_height <= 0:
            continue
        words.append(
            _OCRWord(
                text=text,
                confidence=confidence,
                left=max(0.0, min(float(width), left)),
                top=max(0.0, min(float(height), top)),
                right=max(0.0, min(float(width), left + box_width)),
                bottom=max(0.0, min(float(height), top + box_height)),
            )
        )
    return words


def _window_bbox(
    words: list[_OCRWord],
    start: int,
    end: int,
    *,
    width: int,
    height: int,
) -> list[float]:
    selected = words[start:end]
    left = min(word.left for word in selected)
    top = min(word.top for word in selected)
    right = max(word.right for word in selected)
    bottom = max(word.bottom for word in selected)
    return [
        round((left / max(1, width)) * 1000.0, 2),
        round((top / max(1, height)) * 1000.0, 2),
        round((right / max(1, width)) * 1000.0, 2),
        round((bottom / max(1, height)) * 1000.0, 2),
    ]


def _find_matches(
    words: list[_OCRWord],
    target: str,
    *,
    page: int,
    width: int,
    height: int,
) -> list[OCRMatch]:
    target_norm = _normalize(target)
    target_tokens = target_norm.split()
    if not target_tokens or not words:
        return []

    filtered_words = [
        word for word in words if _normalize(word.text)
    ]
    page_tokens = [_normalize(word.text) for word in filtered_words]
    if not page_tokens:
        return []

    target_len = len(target_tokens)
    min_size = max(1, target_len - 1)
    max_size = min(len(page_tokens), target_len + 2)
    numeric_target = _numeric_ratio(target_norm) >= 0.50
    target_numeric_key = _numeric_key(target) if numeric_target else ""
    allow_fuzzy = not numeric_target
    matches: list[tuple[float, int, int, str]] = []

    for start in range(len(page_tokens)):
        for size in range(min_size, max_size + 1):
            end = start + size
            if end > len(page_tokens):
                break
            candidate = " ".join(page_tokens[start:end])
            candidate_source = " ".join(
                word.text for word in filtered_words[start:end]
            )
            if candidate == target_norm:
                score = 1.0
            elif (
                numeric_target
                and target_numeric_key
                and _numeric_key(candidate_source) == target_numeric_key
            ):
                # Formatting punctuation in scanned amounts/dates is often read
                # differently by OCR. Matching the exact digit sequence preserves
                # numeric safety while tolerating commas, slashes and currency marks.
                score = 1.0
            elif allow_fuzzy:
                score = SequenceMatcher(None, target_norm, candidate).ratio()
                if score < 0.92:
                    continue
            else:
                continue
            matches.append((score, start, end, candidate))

    if not matches:
        return []
    matches.sort(key=lambda item: item[0], reverse=True)
    best_score = matches[0][0]
    accepted = [item for item in matches if item[0] >= best_score - 0.01]
    output: list[OCRMatch] = []
    seen: set[tuple[int, int]] = set()
    for score, start, end, candidate in accepted:
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        confidence_values = [
            word.confidence for word in filtered_words[start:end]
        ]
        ocr_confidence = (
            sum(confidence_values) / len(confidence_values)
            if confidence_values
            else 0.0
        )
        output.append(
            OCRMatch(
                page=page,
                bbox=_window_bbox(
                    filtered_words,
                    start,
                    end,
                    width=width,
                    height=height,
                ),
                text=candidate,
                confidence=min(score * 100.0, ocr_confidence),
            )
        )
    return output


def _page_numbers(
    page_count: int,
    requested: Iterable[int] | None,
) -> list[int]:
    if requested is None:
        return list(range(1, page_count + 1))
    return [
        number
        for number in dict.fromkeys(int(value) for value in requested)
        if 1 <= number <= page_count
    ]


def locate_text_with_ocr(
    pdf_bytes: bytes,
    target: str,
    *,
    password: str | None = None,
    page_numbers: Iterable[int] | None = None,
    dpi: int = 180,
    timeout_seconds: float = 25.0,
) -> list[OCRMatch]:
    if not tesseract_available():
        return []

    document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if document.needs_pass:
        if not password or not document.authenticate(password):
            document.close()
            return []

    matches: list[OCRMatch] = []
    scale = max(1.0, float(dpi) / 72.0)
    try:
        for page_number in _page_numbers(document.page_count, page_numbers):
            page = document[page_number - 1]
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(scale, scale),
                alpha=False,
            )
            width = pixmap.width
            height = pixmap.height
            page_matches: list[OCRMatch] = []
            with tempfile.NamedTemporaryFile(suffix=".png") as handle:
                handle.write(pixmap.tobytes("png"))
                handle.flush()
                for psm in ("6", "11"):
                    try:
                        result = subprocess.run(
                            [
                                "tesseract",
                                handle.name,
                                "stdout",
                                "--psm",
                                psm,
                                "tsv",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=timeout_seconds,
                            check=False,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        continue
                    if result.returncode != 0 or not result.stdout:
                        continue
                    words = _parse_tsv(result.stdout, width=width, height=height)
                    page_matches = _find_matches(
                        words,
                        target,
                        page=page_number,
                        width=width,
                        height=height,
                    )
                    if page_matches:
                        break
            matches.extend(page_matches)
    finally:
        document.close()

    return matches
