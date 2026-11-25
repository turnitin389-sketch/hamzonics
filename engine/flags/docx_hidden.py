"""DOCX text extraction that leaves out hidden text and reports it.

Works on the WordprocessingML directly so that run formatting can be resolved
through direct formatting -> character style -> paragraph style -> document defaults.
Hidden means: `w:vanish`, text colour with too little contrast against its
background (run shading, highlight, paragraph shading, page background), or a
font smaller than 4 pt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from engine.flags.colors import BLACK, RGB, WHITE, hex_to_rgb, is_invisible_on
from engine.flags.types import Finding

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
TINY_PT = 4.0


def q(tag: str) -> str:
    return f"{{{W}}}{tag}"


_THEME_COLORS = {"background1": WHITE, "light1": WHITE, "text1": BLACK, "dark1": BLACK}
_HIGHLIGHT = {
    "white": WHITE, "black": BLACK, "yellow": (1, 1, 0), "green": (0, 1, 0), "cyan": (0, 1, 1),
    "magenta": (1, 0, 1), "blue": (0, 0, 1), "red": (1, 0, 0), "darkBlue": (0, 0, 0.5),
    "darkCyan": (0, 0.5, 0.5), "darkGreen": (0, 0.5, 0), "darkMagenta": (0.5, 0, 0.5),
    "darkRed": (0.5, 0, 0), "darkYellow": (0.5, 0.5, 0), "darkGray": (0.5, 0.5, 0.5),
    "lightGray": (0.75, 0.75, 0.75),
}
_SKIP_ANCESTORS = {q("del"), q("moveFrom"), f"{{{MC}}}Fallback"}


@dataclass
class DocxResult:
    text: str
    findings: list[Finding] = field(default_factory=list)


class _Styles:
    """Resolves run properties through the style hierarchy."""

    def __init__(self, styles_root: etree._Element | None) -> None:
        self.rpr: dict[str, etree._Element | None] = {}
        self.based_on: dict[str, str] = {}
        self.ppr_shd: dict[str, str | None] = {}
        self.default_rpr: etree._Element | None = None
        self.default_pstyle: str | None = None
        if styles_root is None:
            return
        self.default_rpr = styles_root.find(f"{q('docDefaults')}/{q('rPrDefault')}/{q('rPr')}")
        for st in styles_root.iterfind(q("style")):
            sid = st.get(q("styleId"))
            if not sid:
                continue
            self.rpr[sid] = st.find(q("rPr"))
            base = st.find(q("basedOn"))
            if base is not None and base.get(q("val")):
                self.based_on[sid] = base.get(q("val"))  # type: ignore[assignment]
            shd = st.find(f"{q('pPr')}/{q('shd')}")
            self.ppr_shd[sid] = shd.get(q("fill")) if shd is not None else None
            if st.get(q("type")) == "paragraph" and st.get(q("default")) in ("1", "true"):
                self.default_pstyle = sid

    def chain(self, style_id: str | None) -> list[etree._Element]:
        out: list[etree._Element] = []
        seen: set[str] = set()
        while style_id and style_id not in seen:
            seen.add(style_id)
            rpr = self.rpr.get(style_id)
            if rpr is not None:
                out.append(rpr)
            style_id = self.based_on.get(style_id)
        return out

    def para_shading(self, style_id: str | None) -> str | None:
        seen: set[str] = set()
        while style_id and style_id not in seen:
            seen.add(style_id)
            if self.ppr_shd.get(style_id):
                return self.ppr_shd[style_id]
            style_id = self.based_on.get(style_id)
        return None


def _first(rprs: list[etree._Element], tag: str) -> etree._Element | None:
    for rpr in rprs:
        el = rpr.find(q(tag))
        if el is not None:
            return el
    return None


def _on(el: etree._Element | None) -> bool:
    return el is not None and el.get(q("val"), "true").lower() not in ("0", "false", "off")


def _run_text(r: etree._Element) -> str:
    parts: list[str] = []
    for el in r:
        tag = el.tag
        if tag == q("t"):  # w:delText (deleted text) is ignored on purpose
            parts.append(el.text or "")
        elif tag == q("tab"):
            parts.append("\t")
        elif tag in (q("br"), q("cr")):
            parts.append("\n")
        elif tag == q("noBreakHyphen"):
            parts.append("-")
    return "".join(parts)


def _skipped(r: etree._Element, stop: etree._Element) -> bool:
    for anc in r.iterancestors():
        if anc is stop:
            return False
        if anc.tag in _SKIP_ANCESTORS:
            return True
    return False


class _Extractor:
    def __init__(self, document_root: etree._Element, styles: _Styles) -> None:
        self.styles = styles
        bg = document_root.find(q("background"))
        self.page_bg = hex_to_rgb(bg.get(q("color"))) if bg is not None else None
        self.page_bg = self.page_bg or WHITE
        self.findings: list[Finding] = []
        self.para_index = 0

    def paragraph(self, p: etree._Element, cell_bg: RGB | None = None) -> str:
        self.para_index += 1
        ppr = p.find(q("pPr"))
        pstyle_el = ppr.find(q("pStyle")) if ppr is not None else None
        pstyle = pstyle_el.get(q("val")) if pstyle_el is not None else self.styles.default_pstyle
        pshd = ppr.find(q("shd")) if ppr is not None else None
        para_bg = hex_to_rgb(pshd.get(q("fill")) if pshd is not None else self.styles.para_shading(pstyle))

        kept: list[str] = []
        current: Finding | None = None
        for r in p.iter(q("r")):
            if _skipped(r, p):
                continue
            text = _run_text(r)
            if not text:
                continue
            reason = None if text.isspace() else self._hidden_reason(r, pstyle, para_bg or cell_bg)
            if reason is None:
                kept.append(text)
                current = None
                continue
            chars = sum(1 for c in text if not c.isspace())
            if current is not None and current.type == reason:
                current.count += chars
                current.text += text
            else:
                current = Finding(reason, chars, 1, text=text, detail=f"paragraph {self.para_index}")
                self.findings.append(current)
        return "".join(kept)

    def _hidden_reason(self, r: etree._Element, pstyle: str | None, block_bg: RGB | None) -> str | None:
        direct = r.find(q("rPr"))
        rstyle_el = direct.find(q("rStyle")) if direct is not None else None
        rprs = ([direct] if direct is not None else []) + self.styles.chain(
            rstyle_el.get(q("val")) if rstyle_el is not None else None
        ) + self.styles.chain(pstyle) + ([self.styles.default_rpr] if self.styles.default_rpr is not None else [])

        if _on(_first(rprs, "vanish")) or _on(_first(rprs, "specVanish")):
            return "hidden_text_vanish"

        fg = None
        color = _first(rprs, "color")
        if color is not None:
            theme = color.get(q("themeColor"))
            fg = _THEME_COLORS.get(theme) if theme else hex_to_rgb(color.get(q("val")))
        if fg is not None:
            bg: RGB | None = None
            shd = _first(rprs, "shd")
            if shd is not None:
                bg = hex_to_rgb(shd.get(q("fill")))
            hl = _first(rprs, "highlight")
            if bg is None and hl is not None:
                bg = _HIGHLIGHT.get(hl.get(q("val"), ""))
            bg = bg or block_bg or self.page_bg
            if is_invisible_on(fg, bg):
                return "hidden_text_color"

        size = _first(rprs, "sz")
        if size is not None:
            try:
                if int(size.get(q("val"), "0")) / 2 < TINY_PT:
                    return "hidden_text_tiny"
            except ValueError:
                pass
        return None

    def table(self, tbl: etree._Element) -> list[str]:
        lines: list[str] = []
        for tr in tbl.iterchildren(q("tr")):
            cells: list[str] = []
            for tc in tr.iterchildren(q("tc")):
                shd = tc.find(f"{q('tcPr')}/{q('shd')}")
                cell_bg = hex_to_rgb(shd.get(q("fill"))) if shd is not None else None
                cells.append(" ".join(t for t in (self.paragraph(p, cell_bg) for p in tc.iter(q("p"))) if t))
            lines.append("\t".join(cells))
        lines.append("")
        return lines


def extract_docx(path: Path) -> DocxResult:
    import zipfile

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        doc_root = etree.fromstring(zf.read("word/document.xml"))
        styles_root = etree.fromstring(zf.read("word/styles.xml")) if "word/styles.xml" in names else None

    ex = _Extractor(doc_root, _Styles(styles_root))
    body = doc_root.find(q("body"))
    parts: list[str] = []
    if body is not None:
        for child in body:
            if child.tag == q("p"):
                parts.append(ex.paragraph(child))
            elif child.tag == q("tbl"):
                parts.extend(ex.table(child))
            elif child.tag == q("sdt"):  # content controls wrap paragraphs
                for p in child.iter(q("p")):
                    parts.append(ex.paragraph(p))
    return DocxResult("\n".join(parts), ex.findings)
