#!/usr/bin/env python3
"""Generate the Phase 0 evaluation corpus (deterministic, synthetic study materials).

Creates, under study_rag/data/raw/:
  biology/cell_biology.pdf      - born-digital, 3 pages: prose, table, figures
  biology/field_notes_scanned.pdf - image-only pages (no text layer)
  physics/thermodynamics.md     - Markdown control

Run from study_rag/:  python eval/make_corpus.py
Requires: reportlab, pillow (eval-only dependencies, not runtime deps).
"""

from __future__ import annotations

from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw"


def draw_mito_figure(path: Path) -> None:
    """Raster diagram whose labels exist ONLY inside the image (no PDF text).

    Used to prove figure records carry evidence captions alone cannot provide.
    """
    from PIL import Image, ImageDraw, ImageFont

    try:
        font_title = ImageFont.load_default(size=64)
        font_label = ImageFont.load_default(size=44)
    except TypeError:  # very old Pillow
        font_title = ImageFont.load_default()
        font_label = ImageFont.load_default()

    W, H = 1400, 1000
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((80, 40), "Mitochondrion", fill="black", font=font_title)
    # Outer membrane (ellipse) + inner membrane (wavy folds).
    d.ellipse([120, 180, 880, 860], outline="black", width=6)
    import math

    inner = [(150 + x, 520 + int(150 * math.sin(x / 60)) - 140 * (x / 730)) for x in range(0, 731, 10)]
    inner += [(150 + x, 520 + int(150 * math.sin(x / 60)) + 140 * (x / 730)) for x in range(730, -1, -10)]
    d.line(inner, fill="black", width=4)
    # Leader lines + labels (right side).
    for y_img, label in [(300, "outer membrane"), (470, "inner membrane"), (640, "cristae"), (800, "matrix")]:
        y_anchor = {300: 260, 470: 470, 640: 620, 800: 760}[y_img]
        d.line([(880, y_anchor), (1050, y_img)], fill="black", width=3)
        d.text((1060, y_img - 25), label, fill="black", font=font_label)
    img.save(path)


def make_cell_biology(path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.pdfgen.canvas import Canvas

    styles = getSampleStyleSheet()
    story = [
        Paragraph("Protein Synthesis", styles["Heading1"]),
        Paragraph(
            "Protein synthesis has two stages. Transcription occurs in the nucleus, "
            "where the DNA sequence of a gene is copied into messenger RNA (mRNA). "
            "The mRNA then leaves the nucleus through a nuclear pore.",
            styles["BodyText"],
        ),
        Spacer(1, 0.4 * cm),
        Paragraph(
            "Translation takes place at the ribosome. Transfer RNA (tRNA) molecules "
            "deliver amino acids to the ribosome, where they are joined in the order "
            "specified by the mRNA codons to build a protein chain.",
            styles["BodyText"],
        ),
        PageBreak(),
        Paragraph("Cell Organelles", styles["Heading1"]),
        Paragraph("Table 1 lists the main organelles and their functions.", styles["BodyText"]),
        Spacer(1, 0.3 * cm),
        Table(
            [
                ["Organelle", "Function"],
                ["Nucleus", "Stores DNA and controls the cell"],
                ["Mitochondrion", "Produces ATP through cellular respiration"],
                ["Ribosome", "Builds proteins from amino acids"],
                ["Chloroplast", "Captures light for photosynthesis"],
                ["Cell membrane", "Controls what enters and leaves the cell"],
            ],
            colWidths=[5 * cm, 10 * cm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            ),
        ),
        PageBreak(),
        Paragraph("Cell Diagrams", styles["Heading1"]),
        Paragraph(
            "Figure 1: Animal cell diagram. Labeled parts: nucleus, mitochondria, "
            "ribosome, and cell membrane.",
            styles["BodyText"],
        ),
        Spacer(1, 0.4 * cm),
        Paragraph(
            "Figure 2: Stages of mitosis in order. The flowchart reads: "
            "Prophase, then Metaphase, then Anaphase, then Telophase.",
            styles["BodyText"],
        ),
        PageBreak(),
        Paragraph("Mitochondrion Figure", styles["Heading1"]),
        Paragraph(
            "Figure 3: Mitochondrion structure (see diagram).",
            styles["BodyText"],
        ),
        Spacer(1, 0.4 * cm),
    ]
    mito_png = Path("/tmp/phase0-mito.png")
    draw_mito_figure(mito_png)
    story.append(RLImage(str(mito_png), width=13 * cm, height=13 * 1000 / 1400 * cm))
    doc = SimpleDocTemplate(str(path), pagesize=A4)

    def draw_diagrams(canvas: Canvas, _doc) -> None:
        if canvas.getPageNumber() != 3:
            return
        # Figure 1: simple labeled cell (vector shapes, labels are NOT text objects)
        canvas.setStrokeColor(colors.black)
        canvas.circle(6 * cm, 17 * cm, 3.2 * cm, stroke=1, fill=0)  # membrane
        canvas.circle(6 * cm, 17 * cm, 1.1 * cm, stroke=1, fill=0)  # nucleus
        canvas.ellipse(8.2 * cm, 16 * cm, 10 * cm, 17 * cm, stroke=1, fill=0)  # mitochondria
        # Figure 2: mitosis flowchart boxes with arrows
        x, y, w, h, gap = 2 * cm, 9.5 * cm, 3 * cm, 1.2 * cm, 0.9 * cm
        for i in range(4):
            bx = x + i * (w + gap)
            canvas.rect(bx, y, w, h, stroke=1, fill=0)
            if i < 3:
                canvas.line(bx + w, y + h / 2, bx + w + gap, y + h / 2)
                canvas.line(bx + w + gap, y + h / 2, bx + w + gap - 4, y + h / 2 + 4)
                canvas.line(bx + w + gap, y + h / 2, bx + w + gap - 4, y + h / 2 - 4)

    doc.build(story, onLaterPages=draw_diagrams)


def make_scanned_notes(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font_title = ImageFont.load_default(size=44)
        font_body = ImageFont.load_default(size=30)
    except TypeError:  # very old Pillow
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()

    pages = [
        ("POND FIELD TRIP - 12 MAY", [
            "Sample A: pond water contained",
            "volvox colonies and duckweed.",
            "",
            "Sample B: soil smelled of clay,",
            "no visible organisms.",
        ]),
        ("POND FIELD TRIP - page 2", [
            "The volvox colonies were bright",
            "green spheres, about 1 mm wide.",
            "",
            "Remember: bring jars next time.",
        ]),
    ]
    images = []
    for title, lines in pages:
        img = Image.new("RGB", (1700, 2200), "white")
        d = ImageDraw.Draw(img)
        d.text((120, 120), title, fill="black", font=font_title)
        y = 260
        for line in lines:
            d.text((120, y), line, fill="black", font=font_body)
            y += 70
        images.append(img)
    images[0].save(path, save_all=True, append_images=images[1:])


def make_thermo_md(path: Path) -> None:
    path.write_text(
        "# Thermodynamics (Physics 201)\n\n"
        "The zeroth law of thermodynamics defines thermal equilibrium and "
        "temperature: if two systems are each in equilibrium with a third, "
        "they are in equilibrium with each other.\n\n"
        "The first law is conservation of energy: heat added to a system equals "
        "the change in internal energy plus the work done by the system.\n",
        encoding="utf-8",
    )


def main() -> None:
    (RAW / "biology").mkdir(parents=True, exist_ok=True)
    (RAW / "physics").mkdir(parents=True, exist_ok=True)
    make_cell_biology(RAW / "biology" / "cell_biology.pdf")
    make_scanned_notes(RAW / "biology" / "field_notes_scanned.pdf")
    make_thermo_md(RAW / "physics" / "thermodynamics.md")
    for f in sorted((RAW).rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(RAW)} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
