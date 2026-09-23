from backend.app.services.pdf_local_ocr import _find_matches, _parse_tsv


def test_local_ocr_parser_finds_phrase_and_normalized_bbox() -> None:
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
        "left\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t100\t200\t80\t40\t96\tJohn\n"
        "5\t1\t1\t1\t1\t2\t190\t200\t100\t40\t97\tSmith\n"
    )
    words = _parse_tsv(tsv, width=1000, height=1000)

    matches = _find_matches(
        words,
        "John Smith",
        page=1,
        width=1000,
        height=1000,
    )

    assert len(matches) == 1
    assert matches[0].page == 1
    assert matches[0].bbox == [100.0, 200.0, 290.0, 240.0]
    assert matches[0].confidence >= 96.0


def test_local_ocr_does_not_fuzzy_match_numeric_values() -> None:
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
        "left\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t100\t200\t100\t40\t96\t450000.00\n"
    )
    words = _parse_tsv(tsv, width=1000, height=1000)

    assert _find_matches(
        words,
        "450001.00",
        page=1,
        width=1000,
        height=1000,
    ) == []
