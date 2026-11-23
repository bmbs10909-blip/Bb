"""표준 라이브러리만으로 .docx 파일을 만드는 최소 작성기 (외부 라이브러리 불필요)."""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
WP = 'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
PAGE_WIDTH = 9638  # A4에서 좌우 여백 2cm를 뺀 폭 (1/20 pt)
FONT = "맑은 고딕"


def run(text, bold=False, color=None, size=None) -> str:
    """글자 조각. size는 pt."""
    props = ("<w:b/>" if bold else "") + (f'<w:color w:val="{color}"/>' if color else "")
    if size:
        props += f'<w:sz w:val="{int(size * 2)}"/><w:szCs w:val="{int(size * 2)}"/>'
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{escape(str(text))}</w:t></w:r>'


def para(content: str, align="left", before=0, after=80, keep_next=False) -> str:
    keep = "<w:keepNext/>" if keep_next else ""  # 다음 문단과 같은 쪽에 두기 (제목이 쪽 끝에 홀로 남지 않게)
    return (f'<w:p><w:pPr>{keep}<w:spacing w:before="{before}" w:after="{after}"/><w:jc w:val="{align}"/></w:pPr>'
            f'{content}</w:p>')


class Document:
    def __init__(self):
        self.body: list[str] = []
        self.images: list[bytes] = []

    def title(self, text: str, sub: str = ""):
        self.body.append(para(run(text, bold=True, size=20, color="1F3864"), after=40))
        if sub:
            self.body.append(para(run(sub, size=10, color="7F7F7F"), after=160))

    def heading(self, text: str):
        self.body.append(para(run(text, bold=True, size=13, color="1F3864"), before=280, after=100, keep_next=True))

    def text(self, text: str, **kw):
        self.body.append(para(run(text, **kw)))

    def table(self, headers: list[str], rows: list[list], aligns: list[str] | None = None,
              widths: list[float] | None = None, header_fill="1F3864", size=10):
        """rows의 각 칸은 문자열 또는 (문자열, 색) 또는 (문자열, 색, 굵게)."""
        n = len(headers)
        aligns = aligns or ["left"] * n
        widths = widths or [1.0] * n
        cols = [int(PAGE_WIDTH * w / sum(widths)) for w in widths]

        def cell(i, content, fill=None):
            shade = f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>' if fill else ""
            return (f'<w:tc><w:tcPr><w:tcW w:w="{cols[i]}" w:type="dxa"/>{shade}<w:vAlign w:val="center"/></w:tcPr>'
                    f'{content}</w:tc>')

        out = ['<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>'
               + "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
                         for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
               + '</w:tblBorders><w:tblCellMar><w:top w:w="60" w:type="dxa"/><w:left w:w="100" w:type="dxa"/>'
                 '<w:bottom w:w="60" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr>'
               + "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{c}"/>' for c in cols) + "</w:tblGrid>"]
        out.append("<w:tr><w:trPr><w:tblHeader/></w:trPr>" + "".join(
            cell(i, para(run(h, bold=True, color="FFFFFF", size=size), "center", after=0), header_fill)
            for i, h in enumerate(headers)) + "</w:tr>")
        for k, row in enumerate(rows):
            cells = []
            for i, v in enumerate(row):
                text, color, bold = (v + (None, False))[:3] if isinstance(v, tuple) else (v, None, False)
                cells.append(cell(i, para(run(text, bold=bold, color=color, size=size), aligns[i], after=0),
                                  "F2F2F2" if k % 2 else None))
            out.append("<w:tr>" + "".join(cells) + "</w:tr>")
        self.body.append("".join(out) + "</w:tbl>" + para("", after=0))

    def cards(self, items: list[tuple[str, str, str | None]]):
        """큰 숫자 카드 한 줄. 각 항목은 (제목, 값, 값 색)."""
        width = PAGE_WIDTH // len(items)
        cells = "".join(
            f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="EEF3FA"/>'
            f'<w:vAlign w:val="center"/></w:tcPr>'
            + para(run(label, size=9, color="595959"), "center", before=80, after=20)
            + para(run(value, bold=True, size=16, color=color or "1F3864"), "center", after=80) + "</w:tc>"
            for label, value, color in items)
        borders = "".join(f'<w:{s} w:val="single" w:sz="12" w:space="0" w:color="FFFFFF"/>'
                          for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
        self.body.append(f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{borders}</w:tblBorders>'
                         f'</w:tblPr><w:tblGrid>' + f'<w:gridCol w:w="{width}"/>' * len(items)
                         + f"</w:tblGrid><w:tr>{cells}</w:tr></w:tbl>" + para("", after=0))

    def image(self, png: bytes, width_cm: float, height_cm: float):
        self.images.append(png)
        n, cx, cy = len(self.images), int(width_cm * 360000), int(height_cm * 360000)
        a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        pic = 'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
        self.body.append(para(
            f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{n}" name="image{n}"/><a:graphic {a}>'
            f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic {pic}>'
            f'<pic:nvPicPr><pic:cNvPr id="{n}" name="image{n}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="rId{n}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            f'</wp:inline></w:drawing></w:r>', "center"))

    def save(self, path: Path):
        head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        rel_ns = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
        office = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        document = (f'{head}<w:document {W} {R} {WP}><w:body>{"".join(self.body)}'
                    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" '
                    'w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
                    '</w:body></w:document>')
        styles = (f'{head}<w:styles {W}><w:docDefaults><w:rPrDefault><w:rPr>'
                  f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:eastAsia="{FONT}" w:cs="{FONT}"/>'
                  '<w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="ko-KR" w:eastAsia="ko-KR"/>'
                  '</w:rPr></w:rPrDefault></w:docDefaults>'
                  '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
                  '</w:styles>')
        types = (f'{head}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Default Extension="png" ContentType="image/png"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
                 'officedocument.wordprocessingml.document.main+xml"/>'
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-'
                 'officedocument.wordprocessingml.styles+xml"/></Types>')
        root_rels = (f'{head}<Relationships {rel_ns}><Relationship Id="rId1" Type="{office}/officeDocument" '
                     'Target="word/document.xml"/></Relationships>')
        doc_rels = (f'{head}<Relationships {rel_ns}>'
                    + "".join(f'<Relationship Id="rId{i}" Type="{office}/image" Target="media/image{i}.png"/>'
                              for i in range(1, len(self.images) + 1))
                    + f'<Relationship Id="rId{len(self.images) + 1}" Type="{office}/styles" Target="styles.xml"/>'
                      '</Relationships>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", types)
            z.writestr("_rels/.rels", root_rels)
            z.writestr("word/document.xml", document)
            z.writestr("word/styles.xml", styles)
            z.writestr("word/_rels/document.xml.rels", doc_rels)
            for i, png in enumerate(self.images, start=1):
                z.writestr(f"word/media/image{i}.png", png)
