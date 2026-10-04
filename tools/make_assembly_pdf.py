"""
Writes docs/Prototype_Assembly.pdf: the 1:5 prototype's assembly drawing - views with part-number
balloons, an exploded view, every position, and the parts list with part numbers, positions and
buy links (the same numbers as docs/Prototype_Shopping_List.pdf and the CAD).

    ./start.sh --port 8099 &  then  node tools/assembly_views.mjs http://localhost:8099
    pip install reportlab
    python3 tools/make_assembly_pdf.py
"""
import csv
import json
import os
import time

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "Prototype_Assembly.pdf")
IMG = os.path.join(ROOT, "docs", "images")
PAGE = landscape(A3)
ORANGE, DARK, LIGHT = colors.HexColor("#e8641b"), colors.HexColor("#1f2933"), colors.HexColor("#f4f6f8")
SHEETS = {}


def main():
    with open(os.path.join(ROOT, "docs", "prototype_bom.csv")) as fh:
        bom = list(csv.DictReader(fh))
    with open(os.path.join(ROOT, "web", "models", "prototype_positions.json")) as fh:
        positions = json.load(fh)
    by_pn = {}
    for p in positions:
        by_pn.setdefault(p["pn"], []).append(p)

    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica", fontSize=8.5, leading=10.5)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9, textColor=colors.HexColor("#52606d"))
    head = ParagraphStyle("h", parent=body, fontName="Helvetica-Bold", textColor=colors.white)
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=18, leading=22, alignment=0, spaceAfter=4)

    def title_block(canvas, doc):
        canvas.saveState()
        w, h = PAGE
        x0, y0, bw, bh = w - 15 * mm - 150 * mm, 10 * mm, 150 * mm, 24 * mm
        canvas.setStrokeColor(DARK)
        canvas.setLineWidth(0.8)
        canvas.rect(10 * mm, 8 * mm, w - 20 * mm, h - 16 * mm)                     # drawing border
        canvas.rect(x0, y0, bw, bh)
        canvas.line(x0, y0 + 12 * mm, x0 + bw, y0 + 12 * mm)
        canvas.line(x0 + 95 * mm, y0, x0 + 95 * mm, y0 + bh)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(x0 + 3 * mm, y0 + 17 * mm, "Steel Beam Cutting Cell - 1:5 prototype")
        canvas.setFont("Helvetica", 8)
        canvas.drawString(x0 + 3 * mm, y0 + 13.5 * mm, SHEETS.get(doc.page, "Assembly drawing"))
        canvas.drawString(x0 + 3 * mm, y0 + 7 * mm, "Drawn: Ravi Mahadeva")
        canvas.drawString(x0 + 3 * mm, y0 + 3 * mm, f"Date: {time.strftime('%d %b %Y')}   Units: mm   Scale: not to scale")
        canvas.drawString(x0 + 98 * mm, y0 + 17 * mm, "Drawing: BC-P1-GA")
        canvas.drawString(x0 + 98 * mm, y0 + 7 * mm, f"Sheet {doc.page}")
        canvas.drawString(x0 + 98 * mm, y0 + 3 * mm, "CAD: cad/prototype_1to5.step")
        canvas.restoreState()

    doc = SimpleDocTemplate(OUT, pagesize=PAGE, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=38 * mm, title="Prototype Assembly", author="Ravi Mahadeva",
                            subject="Steel Beam Cutting Cell - 1:5 prototype assembly drawing")
    story = []
    shown = [b for b in bom if b["part_no"] in by_pn]

    def legend(rows):
        data = [[Paragraph("<b>Part</b>", head), Paragraph("<b>Name</b>", head), Paragraph("<b>No.</b>", head)]]
        data += [[Paragraph(f"<b>{b['part_no']}</b>", body), Paragraph(b["item"], body), Paragraph(str(len(by_pn[b['part_no']])), body)]
                 for b in rows]
        t = Table(data, colWidths=[13 * mm, 70 * mm, 10 * mm], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                               ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd2d9")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
        return t

    def view_page(title, img, note, sheet_name, with_legend=True):
        SHEETS[len(SHEETS) + 1] = sheet_name
        pic = Image(os.path.join(IMG, img), width=290 * mm, height=290 * mm * 1196 / 2000)
        right = legend(shown) if with_legend else Spacer(1, 1)
        story.append(Paragraph(title, h1))
        story.append(Paragraph(note, small))
        story.append(Spacer(1, 3))
        t = Table([[pic, right]], colWidths=[296 * mm, 96 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(t)
        story.append(PageBreak())

    view_page("General assembly", "assembly_iso.png",
              "Each balloon is a part number (P01 ...) - the same number as the shopping list and the CAD. "
              "The table lists every part in the model and how many there are.", "Sheet: general assembly")
    view_page("Exploded view - what goes where", "assembly_exploded.png",
              "The parts pulled apart from the middle so you can see how they fit together.", "Sheet: exploded view")
    SHEETS[len(SHEETS) + 1] = "Sheet: front and top views"
    story.append(Paragraph("Front view and top view", h1))
    w = 196 * mm
    t = Table([[Image(os.path.join(IMG, "assembly_front.png"), width=w, height=w * 1196 / 2000),
                Image(os.path.join(IMG, "assembly_top.png"), width=w, height=w * 1196 / 2000)],
               [Paragraph("<b>Front</b> - from the operator's side", small), Paragraph("<b>Top</b> - looking down", small)]],
              colWidths=[w, w])
    story.append(t)
    story.append(PageBreak())
    view_page("Every position", "assembly_positions.png",
              "Each balloon is a position: part number - copy (P11-2 = the second NEMA 17 motor). "
              "The list on the following sheets says what each position is and where it goes.",
              "Sheet: every position", with_legend=False)

    # parts list: part number, positions, quantity to buy, price, link
    SHEETS[len(SHEETS) + 1] = "Sheet: parts list"
    story.append(Paragraph("Parts list - part numbers, positions and where to buy", h1))
    data = [[Paragraph(f"<b>{h}</b>", head) for h in ("Part", "Name", "What to look for", "Positions in the model",
                                                     "Buy", "Each", "Where to buy")]]
    for b in bom:
        pos = ", ".join(p["tag"] for p in by_pn.get(b["part_no"], [])) or "<i>not drawn (wiring, inside the control box, tools)</i>"
        link = f'<a href="{b["link"]}" color="#1a5fb4"><u>{"search shop" if any(k in b["link"] for k in ("search", "?s=", "/s?k=", "?q=")) else "product page"}</u></a>' if b["link"] else "<i>make / print it</i>"
        each = float(b["approx_gbp_each"])
        data.append([Paragraph(f"<b>{b['part_no']}</b>", body), Paragraph(f"<b>{b['item']}</b>", body),
                     Paragraph(b["specification / what to look for"], small), Paragraph(pos, small),
                     Paragraph(b["qty"], body), Paragraph(f"£{each:.2f}" if each % 1 else f"£{each:.0f}", body),
                     Paragraph(f"{b['where (UK)']}<br/>{link}", small)])
    t = Table(data, colWidths=[13 * mm, 62 * mm, 100 * mm, 95 * mm, 18 * mm, 16 * mm, 66 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), ORANGE), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                           ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd2d9")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9e2ec"))]))
    story.append(t)
    story.append(PageBreak())

    # every position: what it is and where it goes
    SHEETS[len(SHEETS) + 1] = "Sheet: position list"
    story.append(Paragraph("Position list - what each position is and where it goes", h1))
    story.append(Paragraph("x is along the machine (infeed end = 0), y across (front, the operator's side, is negative), "
                           "z up from the table. Sizes in mm, centre of each part.", small))
    story.append(Spacer(1, 3))
    data = [[Paragraph(f"<b>{h}</b>", head) for h in ("Position", "Part", "What it is", "Where", "x", "y", "z")]]
    for p in positions:
        data.append([Paragraph(f"<b>{p['tag']}</b>", body), Paragraph(p["item"], small), Paragraph(p["label"], small),
                     Paragraph(p["where"], small), *(Paragraph(f"{v:.0f}", small) for v in p["centre"])])
    t = Table(data, colWidths=[20 * mm, 62 * mm, 160 * mm, 80 * mm, 16 * mm, 16 * mm, 16 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                           ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd2d9")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    story.append(t)

    def on_page(canvas, doc):
        if doc.page not in SHEETS:
            SHEETS[doc.page] = SHEETS.get(doc.page - 1, "Assembly drawing")
        title_block(canvas, doc)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(OUT)


if __name__ == "__main__":
    main()
