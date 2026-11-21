"""Minimalny plik .docx (WordprocessingML) z prostego tekstu, bez dodatkowych zależności.

Składnia: "# tekst" tytuł (pogrubiony, wyśrodkowany), "> tekst" wyrównanie do prawej,
"**tekst**" pogrubienie, pusta linia = nowy akapit, pojedynczy enter = nowa linia w akapicie.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Override PartName="/word/document.xml" '
       'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
       '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" '
         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
         'Target="word/document.xml"/></Relationships>')
_FONT = '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="23"/>'


def _runs(line: str, bold: bool = False) -> str:
    out = []
    for i, part in enumerate(re.split(r"\*\*", line)):
        if not part:
            continue
        b = "<w:b/>" if bold or i % 2 else ""
        out.append(f'<w:r><w:rPr>{_FONT}{b}</w:rPr><w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(out)


def _para(lines: list[str]) -> str:
    first = lines[0]
    jc, bold, space = "both", False, 160
    if first.startswith("# "):
        jc, bold, space = "center", True, 240
    elif first.startswith("> "):
        jc = "right"
    body = '<w:r><w:br/></w:r>'.join(_runs(re.sub(r"^(# |> )", "", ln), bold) for ln in lines)
    return (f'<w:p><w:pPr><w:jc w:val="{jc}"/><w:spacing w:after="{space}" w:line="276" w:lineRule="auto"/></w:pPr>'
            f'{body}</w:p>')


def build_docx(text: str) -> bytes:
    blocks, cur = [], []
    for ln in (text or "").replace("\r\n", "\n").split("\n"):
        if ln.strip():
            cur.append(ln.rstrip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    body = "".join(_para(b) for b in blocks) or "<w:p/>"
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           f'{body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
           '<w:pgMar w:top="1417" w:right="1417" w:bottom="1417" w:left="1417" w:header="708" w:footer="708" w:gutter="0"/>'
           '</w:sectPr></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CT)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("word/document.xml", doc)
    return buf.getvalue()
