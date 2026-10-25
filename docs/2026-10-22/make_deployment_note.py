"""Needs python-docx. Builds the deployment recommendation for Tata (Hasan's and
Akshay's action from the 21 Oct sync): review-comments/10-22-2026/Tech Radar -
deployment recommendation.docx. The diagram is deployment.html, rendered to
deployment.png. Measured figures are from the live radar on 22 Oct."""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

HERE = Path(__file__).parent
OUT = HERE.parents[2] / "review-comments/10-22-2026/Tech Radar - deployment recommendation.docx"
NAVY = RGBColor(0x04, 0x1A, 0x4A)
MUTED = RGBColor(0x49, 0x4A, 0x52)
WIDTH = 6.9


def shade(cell, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def table(doc, header, rows, widths):
    tb = doc.add_table(rows=1, cols=len(header))
    tb.style = "Table Grid"; tb.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = tb.rows[0].cells[i]; c.text = ""
        r = c.paragraphs[0].add_run(h); r.bold = True; r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        shade(c, "041A4A")
    for row in rows:
        cells = tb.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(v)
            if i == 0: run.bold = True
    layout = OxmlElement("w:tblLayout"); layout.set(qn("w:type"), "fixed"); tb._tbl.tblPr.append(layout)
    for i, w in enumerate(widths):
        for cell in tb.columns[i].cells: cell.width = Inches(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def bullets(doc, items, style="List Bullet"):
    for it in items:
        p = doc.add_paragraph(style=style)
        if isinstance(it, tuple):
            p.add_run(it[0]).bold = True; p.add_run(it[1])
        else:
            p.add_run(it)


def main():
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10)
    st.paragraph_format.space_after = Pt(4)
    for s in ("Heading 1", "Heading 2", "Title"):
        doc.styles[s].font.color.rgb = NAVY
    doc.styles["Heading 1"].font.size = Pt(13)
    doc.styles["Heading 1"].paragraph_format.space_before = Pt(10)
    sec = doc.sections[0]
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"): setattr(sec, side, Inches(0.8))

    doc.add_paragraph("Tech Radar: deployment recommendation", style="Title")
    p = doc.add_paragraph("Tata Communications × Wharton Mack Institute · 22 October 2026 · for Abhishek and Shashank")
    p.runs[0].font.color.rgb = MUTED

    p = doc.add_paragraph()
    p.add_run("We recommend one Linux server on Tata's AWS account (4 processors, 16 GB of memory, 100 GB of disk) running "
              "the whole radar, its database included, reachable only from Tata's network over HTTPS. ").bold = True
    p.add_run("With the instance by 30 October, we deploy in the week of 2 November and hand over before 24 November, "
              "when Akshay is away.")

    doc.add_picture(str(HERE / "deployment.png"), width=Inches(WIDTH))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph("People reach two addresses on one server; only the radar's API talks to the outside, and the "
                          "database is copied to a bucket in Tata's account every night.")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in p.runs: r.italic = True; r.font.size = Pt(9); r.font.color.rgb = MUTED

    doc.add_heading("The server", level=1)
    doc.add_paragraph("Sized from the radar as it runs today, with room for 25–50 users.")
    table(doc, ["", "Recommendation", "Why"], [
        ("Instance", "m7i.xlarge (4 processors, 16 GB) or a similar xlarge",
         "It uses 1.5 GB idle. Collections run a hidden browser and assessments run model calls in parallel; "
         "16 GB leaves room for both while people use it."),
        ("Operating system", "Ubuntu Server 24.04 LTS",
         "The radar runs in Docker, native on Linux. Everyone uses it in a browser, so no Windows licence or "
         "remote desktop is needed."),
        ("Disk", "100 GB (gp3)", "The program takes 5 GB and the data 122 MB today, growing about 22 MB with each "
                                  "publish to leaders."),
        ("Address", "One fixed address (Elastic IP) and a Tata web address, e.g. techradar.tatacommunications.com",
         "The network rules and the HTTPS certificate need both."),
    ], [1.2, 2.5, 3.2])

    doc.add_heading("Access and security", level=1)
    doc.add_paragraph("The radar has no sign-in yet, so at first the network is the lock: only Tata's network reaches it.")
    bullets(doc, [
        ("Open to Tata only: ", "HTTPS (port 443), from Tata's office and VPN address ranges, set in the server's "
                                "security group. Nothing else is open."),
        ("Closed: ", "the radar's API and database listen only inside the server. Administration goes through AWS "
                     "Session Manager, so no SSH port is open."),
        ("Keys: ", "the model provider's key and the data services' keys sit in one settings file only the "
                   "administrator can read."),
        ("What leaves Tata: ", "to assess and write, the radar sends page text, the catalog and what Tata's people type "
                               "into Tata's plan to the model provider (Anthropic). Tata should confirm this is acceptable."),
        ("Sign-in, next: ", "with Tata's own accounts (single sign-on), one role for the innovation team and one for "
                            "leaders. It also gives the history of choices its 'who', and counts which leaders read "
                            "which Point of View. We propose it as the first change after deployment."),
    ])

    doc.add_heading("The database", level=1)
    doc.add_paragraph("We recommend MongoDB on the same server for testing, in place of the Atlas free tier agreed on "
                      "21 October, then the move to Tata's licensed instance.")
    table(doc, ["", "On the server (recommended)", "Atlas free tier"], [
        ("Room", "The server's disk (100 GB)", "512 MB: today's 122 MB plus about 22 MB a publish fills it after "
                                               "15–18 publishes"),
        ("Where the data sits", "In Tata's AWS account", "In MongoDB's cloud, outside Tata's account"),
        ("Set-up", "Already part of the radar's package", "A second account and network rule"),
    ], [1.4, 2.5, 3.0])
    bullets(doc, [
        ("Backups: ", "a copy every night to an S3 bucket in Tata's account, kept 30 days; we test a restore during "
                      "deployment week."),
        ("Move to the licensed instance: ", "copy the data out and in, and change one setting: about an hour with the "
                                            "radar paused."),
    ])

    doc.add_heading("Costs and upkeep", level=1)
    doc.add_paragraph("Approximate, from AWS's public on-demand prices; Tata's region and discounts change them.")
    table(doc, ["Item", "About, a month"], [
        ("Server (m7i.xlarge, running all the time)", "US$150"),
        ("Disk (100 GB), fixed address, backups", "US$15"),
        ("Model use, billed by Anthropic, not AWS", "Depends on how often collections and assessments run; we'll "
                                                     "estimate a month once the schedule is agreed"),
    ], [3.4, 3.5])
    doc.add_paragraph("Upkeep is about 30–60 minutes a week:")
    bullets(doc, [
        "Check Operations: did the week's collection and assessment finish? Any failure says why.",
        "Check that last night's backup arrived.",
        "Apply an update when we send one: one command, a few minutes' pause.",
        "Once a month: the operating system's security updates and a restart.",
    ])

    doc.add_heading("Timeline", level=1)
    bullets(doc, [
        ("By 30 Oct: ", "Tata provides the instance, access and the answers below."),
        ("2–6 Nov, deployment week: ", "install, HTTPS and network rules, today's data loaded, nightly backups and a "
                                       "restore test, one full run end to end."),
        ("9–20 Nov: ", "Tata's team uses it; we fix what they find; sign-in, if agreed."),
        ("By 23 Nov: ", "handover: a runbook, a walk-through for the administrator and the upkeep checklist."),
    ], style="List Number")

    doc.add_heading("What we need from Tata", level=1)
    bullets(doc, [
        "The instance as above by 30 October, with access for Akshay through Session Manager.",
        "A web address for the team and one for leaders, with Tata's certificate or approval to use a free one.",
        "Tata's office and VPN address ranges, to let in.",
        "Outbound internet from the server: to Anthropic, to the source websites and to the data services.",
        "Who holds the Anthropic account and its key, for testing and after.",
        "Approval for what leaves Tata (above), and an S3 bucket for the backups.",
        "Who looks after the server after handover.",
        "Your choice on the database: on the server for testing, or the Atlas free tier as agreed.",
    ])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
