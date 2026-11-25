"""PDF overlays follow analysis offsets and the source page transform."""

import fitz

from engine.report.composer import _Composer


def test_source_overlay_marks_only_the_analyzed_occurrence(tmp_path):
    source_path = tmp_path / "source.pdf"
    phrase = "This measured result occurs twice."
    clean_text = f"{phrase}\n\n{phrase}"
    offsets = [
        {"page": 1, "start": 0, "end": len(phrase), "ocr": False},
        {"page": 2, "start": len(phrase) + 2, "end": len(clean_text), "ocr": False},
    ]
    segments = [
        {"text": phrase + "\n\n"},
        {"text": phrase, "bg": "#cceef5"},
    ]
    with fitz.open() as source:
        for width, height, rotation in [(612, 792, 0), (360, 540, 90)]:
            page = source.new_page(width=width, height=height)
            page.insert_text((72, 84), phrase)
            page.set_rotation(rotation)
        source.save(source_path)
    composer = _Composer()
    composer._page_roles = []
    with fitz.open() as output:
        composer._build_submission_from_pdf(
            output, "AI Writing Submission", source_path, clean_text, offsets, segments, True, {}
        )
        assert len(output) == 2
        assert not output[0].get_drawings()
        fills = output[1].get_drawings()
        assert len(fills) == 1
        word = output[1].get_text("words")[0]
        # MuPDF rounds text bounds and path operands independently.
        assert (fills[0]["rect"] + fitz.Rect(-0.2, -0.2, 0.2, 0.2)).contains(fitz.Rect(word[:4]))
        assert abs(fills[0]["fill_opacity"] - 0.4) < 0.0001
        assert any(
            item.get("blendmode") == "Multiply" for item in output[1].get_drawings(extended=True)
        )


def test_unmapped_ocr_highlight_keeps_source_without_guessing(tmp_path):
    source_path = tmp_path / "ocr.pdf"
    with fitz.open() as source:
        page = source.new_page(width=360, height=540)
        page.draw_rect(fitz.Rect(20, 30, 300, 400), color=(0, 0, 0))
        source.save(source_path)
    composer = _Composer()
    composer._page_roles = []
    with fitz.open() as output:
        composer._build_submission_from_pdf(
            output, "AI Writing Submission", source_path, "scanned text",
            [{"page": 1, "start": 0, "end": 12, "ocr": True}],
            [{"text": "scanned text", "bg": "#cceef5"}], True, {},
        )
        assert "Highlight positions unavailable" in output[0].get_text()
        assert all(path["fill"] is None for path in output[0].get_drawings())
