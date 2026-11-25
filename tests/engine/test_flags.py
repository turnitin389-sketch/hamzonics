"""Phase 2 acceptance: Cyrillic swaps, zero-width characters, white text and 1 pt text are
each flagged with the correct count, and the cleaned text equals the original Latin text."""

from __future__ import annotations

from pathlib import Path

from engine.extract import FileKind, extract_document, normalize_text
from engine.extract.normalize import words
from engine.flags import clean_characters
from tests import fixtures as fx

ORIGINAL = fx.SENTENCES[0] + " " + fx.SENTENCES[1]
# "Climate change is one of the most serious problems facing farmers in Pakistan today.
#  Rising temperatures reduce wheat yields across Punjab and Sindh every year."

# 4 Cyrillic lookalikes: Climаte, оne, thе, рroblems
CYRILLIC = (
    ORIGINAL.replace("Climate", "Climаte")
    .replace("one", "оne", 1)
    .replace("the most", "thе most")
    .replace("problems", "рroblems")
)
# 3 zero-width characters: far<ZWSP>mers, Paki<ZWSP><ZWJ>stan
ZERO_WIDTH = ORIGINAL.replace("farmers", "far​mers").replace("Pakistan", "Paki​‍stan")


def _flag(doc, name):  # type: ignore[no-untyped-def]
    return next((f for f in doc.flags if f.type == name), None)


# ------------------------------------------------------------------ character level


def test_cyrillic_swaps_counted_and_cleaned() -> None:
    res = clean_characters(CYRILLIC)
    assert res.text == ORIGINAL
    lookalikes = [f for f in res.findings if f.type == "lookalike_characters"]
    assert sum(f.count for f in lookalikes) == 4
    assert {f.detail for f in lookalikes} == {"Climate", "one", "the", "problems"}


def test_zero_width_counted_and_cleaned() -> None:
    res = clean_characters(ZERO_WIDTH)
    assert res.text == ORIGINAL
    assert sum(f.count for f in res.findings if f.type == "invisible_characters") == 3
    # Offsets point at the cleaned text.
    first = res.findings[0]
    assert res.text[first.start - 3 : first.start + 4] == "farmers"


def test_whole_word_swap_in_english_text() -> None:
    # Every letter of "case" replaced by Cyrillic twins (с а ѕ е) inside English prose.
    res = clean_characters(ORIGINAL + " This саѕе is important.")
    assert res.text.endswith("This case is important.")
    assert sum(f.count for f in res.findings) == 4


def test_real_russian_and_greek_text_untouched() -> None:
    russian = "Привет, это обычный русский текст о погоде."
    assert clean_characters(russian).findings == []
    assert clean_characters(russian).text == russian
    greek = "Η Ελλάδα είναι μια όμορφη χώρα."
    assert clean_characters(greek).text == greek


def test_urdu_zwnj_and_rlm_are_kept() -> None:
    urdu = "میں نے آپ‌کے لیے ‏لکھا"
    res = clean_characters(urdu)
    assert res.text == urdu
    assert res.findings == []


def test_fullwidth_and_math_letters_folded() -> None:
    res = clean_characters("The ｐｌａｎ and \U0001d42c\U0001d42d\U0001d42e\U0001d41d\U0001d432 are ready.")
    assert res.text == "The plan and study are ready."
    assert sum(f.count for f in res.findings) == 9


def test_double_space_not_left_behind() -> None:
    assert clean_characters("one ​ two").text == "one two"


# ------------------------------------------------------------------ DOCX


def _tampered_docx(path: Path) -> Path:
    import docx
    from docx.shared import Pt, RGBColor

    d = docx.Document()
    p = d.add_paragraph()
    # Visible text with Cyrillic swaps and zero-width chars mixed in.
    first, second = CYRILLIC.split(". ", 1)
    p.add_run(first + ". ")
    white = p.add_run("secret white words ")  # 16 chars
    white.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    tiny = p.add_run("tiny text ")  # 8 chars
    tiny.font.size = Pt(1)
    vanish = p.add_run("hidden attribute ")  # 15 chars
    vanish.font.hidden = True
    p.add_run(second.replace("Punjab", "Pun​jab"))
    # Coloured text on a dark highlight is visible and must NOT be flagged.
    p2 = d.add_paragraph()
    r = p2.add_run("Visible note.")
    r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    r.font.highlight_color = 1  # WD_COLOR_INDEX.BLACK
    d.save(str(path))
    return path


def test_docx_all_flags_and_clean_text(tmp_path: Path) -> None:
    doc = extract_document(_tampered_docx(tmp_path / "t.docx"), FileKind.DOCX)
    assert _flag(doc, "lookalike_characters").count == 4
    assert _flag(doc, "invisible_characters").count == 1
    assert _flag(doc, "hidden_text_color").count == 16
    assert _flag(doc, "hidden_text_tiny").count == 8
    assert _flag(doc, "hidden_text_vanish").count == 15
    assert doc.text == normalize_text(ORIGINAL + "\nVisible note.")
    assert _flag(doc, "hidden_text_color").locations[0]["text"].strip() == "secret white words"


def test_docx_white_text_via_style(tmp_path: Path) -> None:
    import docx
    from docx.shared import RGBColor

    d = docx.Document()
    style = d.styles.add_style("Sneaky", 2)  # WD_STYLE_TYPE.CHARACTER
    style.font.color.rgb = RGBColor(0xFE, 0xFE, 0xFE)
    p = d.add_paragraph("Normal text here. ")
    p.add_run("styled hidden", style="Sneaky")
    path = tmp_path / "s.docx"
    d.save(str(path))
    doc = extract_document(path, FileKind.DOCX)
    assert doc.text == "Normal text here."
    assert _flag(doc, "hidden_text_color").count == 12


def test_clean_docx_has_no_flags(tmp_path: Path) -> None:
    doc = extract_document(fx.make_docx(tmp_path / "c.docx", fx.essay(2).split("\n\n")), FileKind.DOCX)
    assert doc.flags == []


# ------------------------------------------------------------------ PDF


def _tampered_pdf(path: Path) -> Path:
    import fitz

    d = fitz.open()
    page = d.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(56, 56, 539, 300), ORIGINAL, fontsize=11, fontname="helv")
    page.insert_text((56, 400), "secret white words", fontsize=11, color=(1, 1, 1))  # 16
    page.insert_text((56, 450), "tiny text", fontsize=1)  # 8
    page.insert_text((-400, 500), "outside words", fontsize=11)  # 12
    page.insert_text((56, 550), "pale grey", fontsize=11, color=(0.97, 0.97, 0.97))  # 8
    # White text on a black box is readable: not hidden.
    page.draw_rect(fitz.Rect(50, 600, 300, 640), color=(0, 0, 0), fill=(0, 0, 0))
    page.insert_text((56, 625), "Boxed note", fontsize=11, color=(1, 1, 1))
    d.save(path)
    d.close()
    return path


def test_pdf_hidden_text_flags_and_clean_text(tmp_path: Path) -> None:
    doc = extract_document(_tampered_pdf(tmp_path / "t.pdf"), FileKind.PDF)
    assert _flag(doc, "hidden_text_color").count == 16 + 8
    assert _flag(doc, "hidden_text_tiny").count == 8
    assert _flag(doc, "text_outside_page").count == 12
    assert words(doc.text) == words(ORIGINAL + " Boxed note")
    texts = [loc["text"] for loc in _flag(doc, "hidden_text_color").locations]
    assert "secret white words" in texts and "pale grey" in texts
    assert all(loc["page"] == 1 for loc in _flag(doc, "text_outside_page").locations)


def test_clean_pdf_has_no_flags(tmp_path: Path) -> None:
    doc = extract_document(fx.make_pdf(tmp_path / "c.pdf", [fx.essay(2)]), FileKind.PDF)
    assert doc.flags == []
