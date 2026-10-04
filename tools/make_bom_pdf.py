"""
Writes docs/Prototype_Shopping_List.pdf from docs/prototype_bom.csv and cad/prototype_cut_list.csv:
the 1:5 prototype's buying list, stage by stage, with tick boxes.

    pip install reportlab
    python3 tools/make_bom_pdf.py
"""
import csv
import os
import re
import time

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "Prototype_Shopping_List.pdf")
STAGES = {"1": "Stage 1 - Frame and bed", "2": "Stage 2 - Motion and controller", "3": "Stage 3 - Arms and tools",
          "4": "Stage 4 - Cameras (vision)", "5": "Stage 5 - Safety and enclosure", "6": "Stage 6 - Electrical",
          "7": "Consumables"}
ORANGE = colors.HexColor("#e8641b")
DARK = colors.HexColor("#1f2933")
LIGHT = colors.HexColor("#f4f6f8")


def qty_number(q):
    return float(re.match(r"[\d.]+", q).group())


def buy_link(url):
    """A clickable link: straight to the product where it was checked, else the shop's search."""
    if not url:
        return "<i>3D print / make it</i>"
    shop = url.split("/")[2].replace("www.", "").replace("uk.", "")
    search = any(k in url for k in ("search", "?s=", "/s?k=", "searchTerm", "?q="))
    text = f"Search {shop}" if search else "Open product page"
    return f'<a href="{url}" color="#1a5fb4"><u>{text}</u></a>'


def money(v):
    return f"£{v:,.2f}" if v < 10 and v != int(v) else f"£{v:,.0f}"


def main():
    with open(os.path.join(ROOT, "docs", "prototype_bom.csv")) as fh:
        rows = list(csv.DictReader(fh))
    with open(os.path.join(ROOT, "cad", "prototype_cut_list.csv")) as fh:
        cuts = list(csv.DictReader(fh))

    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica", fontSize=8.5, leading=10.5, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=9, textColor=colors.HexColor("#52606d"))
    head = ParagraphStyle("head", parent=body, fontName="Helvetica-Bold", textColor=colors.white)
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=TA_LEFT, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, textColor=DARK, spaceBefore=8, spaceAfter=4, keepWithNext=1)
    note = ParagraphStyle("note", parent=body, fontSize=9, leading=12)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#7b8794"))
        canvas.drawString(15 * mm, 9 * mm, "Steel Beam Cutting Cell - 1:5 prototype shopping list - Ravi Mahadeva")
        canvas.drawRightString(A4[1] - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(OUT, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm, topMargin=13 * mm,
                            bottomMargin=15 * mm, title="Prototype Shopping List", author="Ravi Mahadeva",
                            subject="Steel Beam Cutting Cell - 1:5 prototype")
    story = []
    totals = {s: sum(qty_number(r["qty"]) * float(r["approx_gbp_each"]) for r in rows if r["stage"] == s) for s in STAGES}
    grand = sum(totals.values())

    big = ParagraphStyle("big", parent=body, fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=colors.white)
    story.append(Paragraph("Prototype Shopping List", h1))
    story.append(Paragraph(f"<b>Steel Beam Cutting Cell - 1:5 desktop prototype</b> &nbsp;|&nbsp; Ravi Mahadeva &nbsp;|&nbsp; "
                           f"{time.strftime('%d %B %Y')}", body))
    story.append(Spacer(1, 6))
    box = Table([[Paragraph(f"TOTAL BUYING COST: about {money(round(grand, -1))}", big),
                  Paragraph(f"<font color='white'>incl. VAT where known, before postage &nbsp;|&nbsp; with 10% spare for postage "
                            f"and price changes: <b>about {money(round(grand * 1.1, -1))}</b> &nbsp;|&nbsp; "
                            f"to get moving first (stages 1-2): about {money(round(totals['1'] + totals['2'], -1))}</font>", body)]],
                colWidths=[95 * mm, 170 * mm])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ORANGE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                             ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    story.append(box)
    story.append(Spacer(1, 8))
    summary = [[Paragraph("<b>Stage</b>", head), Paragraph("<b>About</b>", head)]]
    summary += [[Paragraph(STAGES[s], body), Paragraph(money(round(totals[s], -1)), body)] for s in STAGES]
    summary.append([Paragraph("<b>Total</b>", body), Paragraph(f"<b>about {money(round(grand, -1))}</b>", body)])
    t = Table(summary, colWidths=[75 * mm, 30 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT]),
                           ("LINEABOVE", (0, -1), (-1, -1), 1, DARK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd2d9")), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    tips = Paragraph(
        "<b>Before you buy</b><br/>"
        "- Prices are approximate (GBP, October 2026) and change - check each one before ordering.<br/>"
        "- <b>Every item has a link</b> (blue): a product page where it was checked, otherwise that shop's search.<br/>"
        "- <b>Part numbers</b> (P01 ...) are the same as the balloons in docs/Prototype_Assembly.pdf, the Prototype "
        "tab in the app and the CAD - so you can see where each part goes.<br/>"
        "- You already have the <b>Jetson Orin Nano</b>; it is not in the total.<br/>"
        "- Order the aluminium <b>cut to size</b> (lengths on the last page) - it saves a lot of work.<br/>"
        "- Buy and wire the <b>safety parts (stage 5) before any motor moves</b>: the E-stop and safety "
        "relay must cut motor power. Have the mains wiring checked by a competent person.<br/>"
        "- Cheapest way to start: stages 1 and 2 first (frame and moving gantry, about "
        f"{money(round(totals['1'] + totals['2'], -1))}), then arms, cameras and the rest.<br/>"
        "- Save on the arms by buying the STS3215 servos and printing the SO-101 parts yourself "
        "(about £130 per arm instead of £240). A used Pilz PNOZ s3 is about £75.<br/>"
        "- No real cutting on the prototype: the Cutter holds a <b>pen</b> that marks the cut lines.", note)
    top = Table([[t, tips]], colWidths=[110 * mm, 155 * mm])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (1, 0), (1, 0), 10)]))
    story.append(top)

    widths = [10 * mm, 13 * mm, 50 * mm, 83 * mm, 17 * mm, 15 * mm, 18 * mm, 61 * mm]
    for s, title in STAGES.items():
        items = [r for r in rows if r["stage"] == s]
        data = [[Paragraph("<b>OK</b>", head)] + [Paragraph(f"<b>{h}</b>", head) for h in
                                                    ("Part", "Item", "What to look for", "Qty", "Each", "Line total", "Where to buy (click)")]]
        for r in items:
            line = qty_number(r["qty"]) * float(r["approx_gbp_each"])
            spec = r["specification / what to look for"] + (f"<br/><font size=7 color='#52606d'>{r['notes']}</font>" if r["notes"] else "")
            data.append(["", Paragraph(f"<b>{r['part_no']}</b>", body), Paragraph(f"<b>{r['item']}</b>", body), Paragraph(spec, body), Paragraph(r["qty"], body),
                         Paragraph(money(float(r["approx_gbp_each"])), body), Paragraph(money(line), body),
                         Paragraph(f'{r["where (UK)"]}<br/>{buy_link(r.get("link", ""))}', small)])
        data.append(["", "", "", Paragraph("<b>Stage total</b>", body), "", "", Paragraph(f"<b>{money(round(totals[s]))}</b>", body), ""])
        tbl = Table(data, colWidths=widths, repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), ORANGE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT]),
                 ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#d9e2ec")),
                 ("LINEABOVE", (0, -1), (-1, -1), 0.8, DARK), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd2d9")),
                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for i in range(1, len(data) - 1):                       # an empty tick box on every item
            style.append(("BOX", (0, i), (0, i), 0.8, DARK))
        tbl.setStyle(TableStyle(style))
        if len(items) < 9:                                       # small table: heading and table on one page
            story.append(KeepTogether([Paragraph(title, h2), tbl]))
        else:
            story += [Paragraph(title, h2), tbl]

    cut_title = Paragraph("Aluminium cut list (order cut to size)", h2)
    data = [[Paragraph(f"<b>{h}</b>", head) for h in ("OK", "Profile", "Length (mm)", "Quantity", "Used for")]]
    data += [["", Paragraph(c["profile"] + " V-slot", body), Paragraph(c["length_mm"], body), Paragraph(c["quantity"], body),
              Paragraph(c["use"], body)] for c in cuts]
    tbl = Table(data, colWidths=[11 * mm, 40 * mm, 30 * mm, 25 * mm, 60 * mm], repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), DARK), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
             ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd2d9")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    style += [("BOX", (0, i), (0, i), 0.8, DARK) for i in range(1, len(data))]
    tbl.setStyle(TableStyle(style))
    story.append(KeepTogether([cut_title, tbl, Spacer(1, 8), Paragraph(
        "The lengths come from the CAD model (cad/prototype_1to5.step). The build steps, the safety "
        "wiring and why each part was chosen are in docs/PROTOTYPE.md.", small)]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUT)


if __name__ == "__main__":
    main()
