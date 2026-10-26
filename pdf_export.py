
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Circle, Ellipse
from reportlab.platypus import Image
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    Image,
)

from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"

pdfmetrics.registerFont(
    TTFont(
        "THSarabun",
        str(FONT_DIR / "THSarabunNew.ttf")
    )
)

pdfmetrics.registerFont(
    TTFont(
        "THSarabun-Bold",
        str(FONT_DIR / "THSarabunNew Bold.ttf")
    )
)

pdfmetrics.registerFontFamily(
    "THSarabun",
    normal="THSarabun",
    bold="THSarabun-Bold",
    italic="THSarabun",
    boldItalic="THSarabun-Bold",
)


def generate_clinical_history_pdf(patient, review):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="CMUTitle",
        parent=styles["Title"],
        fontName="THSarabun-Bold",
        fontSize=20,
        leading=24,
        alignment=TA_CENTER,
        spaceAfter=3,
    ))

    styles.add(ParagraphStyle(
        name="CMUSubtitle",
        parent=styles["Normal"],
        fontName="THSarabun-Bold",
        fontSize=16,
        leading=20,
        alignment=TA_CENTER,
        spaceAfter=10,
    ))

    styles.add(ParagraphStyle(
        name="CMUSection",
        parent=styles["Heading2"],
        fontName="THSarabun-Bold",
        fontSize=16,
        leading=20,
        spaceBefore=6,
        spaceAfter=3,
    ))

    styles.add(ParagraphStyle(
        name="CMUBody",
        parent=styles["Normal"],
        fontName="THSarabun",
        fontSize=14,
        leading=17,
    ))

    story = []
    usable_width = A4[0] - 28 * mm

    def value(data, key):
        result = data.get(key)
        if result is None or str(result).strip() == "":
            return "-"
        return str(result)

    def cell(text):
        return Paragraph(
            escape(str(text)).replace("\n", "<br/>"),
            styles["CMUBody"]
        )

    def field_cell(label, data, key):
        return Paragraph(
            f"<b>{escape(label)}:</b> "
            f"{escape(value(data, key))}",
            styles["CMUBody"]
        )

    def section(title):
        story.append(
            Paragraph(title, styles["CMUSection"])
        )

    def styled_table(rows, widths, header=False):
        table = Table(
            rows,
            colWidths=widths,
            hAlign="LEFT",
            repeatRows=1 if header else 0,
        )

        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),           
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, -1), (-1, -1),
             0.4, colors.HexColor("#BBBBBB")),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1),
             [colors.white, colors.HexColor("#F5F6F8")]),
        ]

        if header:
            commands.append(
                ("BACKGROUND", (0, 0), (-1, 0),
                 colors.HexColor("#E6E9ED"))
            )

        table.setStyle(TableStyle(commands))
        return table

    # Header
    story.append(Paragraph(
        "CMU Colposcopy Registry",
        styles["CMUTitle"]
    ))

    story.append(Paragraph(
        "PRE-COLPOSCOPY CLINICAL HISTORY",
        styles["CMUSubtitle"]
    ))

    # Patient Information
    section("PATIENT INFORMATION")

    patient_rows = [
        [
            field_cell("HN", patient, "hn"),
            field_cell("Appointment Date", patient, "appointment_date"),
        ],
        [
            field_cell("Patient Name", patient, "patient_name"),
            cell(""),
        ],
    ]

    story.append(styled_table(
        patient_rows,
        [usable_width / 2, usable_width / 2]
    ))

    # Clinical History
    section("CLINICAL HISTORY")

    clinical_fields = [
        ("Age", "age"),
        ("Parity", "parity"),
        ("LMP", "lmp"),
        ("Menstrual Status", "menstrual_status"),
        ("First Intercourse Age", "first_intercourse_age"),
        ("Number of Sexual Partners", "number_of_partners"),
        ("HIV Status", "hiv_status"),
        ("History of STDs", "history_of_stds"),
        ("Smoking Status", "smoking_status"),
        ("Contraception", "contraception"),
        ("Menopause Duration", "menopause_duration"),
        ("HRT History", "hrt_history"),
    ]

    clinical_rows = []

    for i in range(0, len(clinical_fields), 2):
        left_label, left_key = clinical_fields[i]

        left = field_cell(
            left_label, review, left_key
        )

        if i + 1 < len(clinical_fields):
            right_label, right_key = clinical_fields[i + 1]
            right = field_cell(
                right_label, review, right_key
            )
        else:
            right = cell("")

        clinical_rows.append([left, right])

    story.append(styled_table(
        clinical_rows,
        [usable_width / 2, usable_width / 2]
    ))

    # Cervical Screening
    section("CERVICAL SCREENING HISTORY")

    screening_rows = [
        [cell("Investigation"), cell("Result / Details")],
        [cell("Pap Smear Result"),
         cell(value(review, "pap_smear_result"))],
        [cell("Pap Smear Date"),
         cell(value(review, "pap_smear_date"))],
        [cell("Pap Smear Location"),
         cell(value(review, "pap_smear_location"))], 
        [cell("Patho Number"),
        cell(value(review, "patho_number"))],
        [cell("HPV Result"),
         cell(value(review, "hpv_result"))],
        [cell("HPV Genotype"),
         cell(value(review, "hpv_genotype"))],
        [cell("HPV Vaccination"),
         cell(value(review, "hpv_vaccinated"))],
        [cell("HPV Vaccine Type"),
         cell(value(review, "hpv_vaccine_type"))],
        [cell("Vaccination Completion Date"),
         cell(value(review, "hpv_vaccine_completion_date"))],
    ]

    story.append(styled_table(
        screening_rows,
        [usable_width * 0.42, usable_width * 0.58],
        header=True
    ))

    # Additional Clinical History
    section("ADDITIONAL CLINICAL HISTORY")

    history = value(review, "previous_history")

    story.append(Paragraph(
    '<font name="THSarabun">'
    + escape(history).replace("\n", "<br/>")
    + '</font>',
    styles["CMUBody"]
    ))

    story.append(Spacer(1, 12 * mm))

    # Review and Signature
    signature_rows = [
        [
            field_cell("Reviewed By", review, "reviewed_by"),
            field_cell("Review Date", review, "review_date"),
        ]
    ]

    story.append(styled_table(
        signature_rows,
        [usable_width / 2, usable_width / 2]
    ))

    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph(
        "Signature: ______________________________",
        styles["CMUBody"]
    ))

    doc.build(story)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes

def generate_full_colposcopy_pdf(
    patient, review, record, specimens=None,
    pathology_review=None, pathology_specimens=None,
):
    """Export saved clinical history, colposcopy, and specimen collection.

    Pathology Review and Pathology Specimen Results are intentionally excluded.
    Optional pathology parameters remain for compatibility with older callers.
    No database writes occur here.
    """
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import Image as RLImage, CondPageBreak

    patient = patient or {}
    review = review or {}
    record = record or {}
    specimens = specimens or []
    pathology_review = pathology_review or {}
    pathology_specimens = pathology_specimens or []

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=12 * mm,
        title="CMU Colposcopy Registry - Colposcopy Record",
        author="CMU Colposcopy Registry",
    )
    usable_width = A4[0] - 24 * mm
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", fontName="THSarabun-Bold",
        fontSize=18, leading=20, alignment=TA_CENTER, spaceAfter=0,
    ))
    styles.add(ParagraphStyle(
        name="ReportSubtitle", fontName="THSarabun",
        fontSize=10.5, leading=12, alignment=TA_CENTER, spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        name="ReportSection", fontName="THSarabun-Bold",
        fontSize=14, leading=16, spaceBefore=5, spaceAfter=2,
        textColor=colors.HexColor("#1C344E"),
    ))
    styles.add(ParagraphStyle(
        name="ReportSubsection", fontName="THSarabun-Bold",
        fontSize=12.5, leading=14, spaceBefore=3, spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        name="ReportBody", fontName="THSarabun",
        fontSize=12, leading=14, spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        name="ReportSmall", fontName="THSarabun",
        fontSize=10.5, leading=12,
    ))
    story = []

    def text_value(value):
        if value is None or str(value).strip() == "":
            return "-"
        return str(value)

    def value(data, key):
        return text_value((data or {}).get(key))

    def safe_text(value):
        return escape(text_value(value)).replace("\r\n", "\n").replace("\n", "<br/>")

    def paragraph(text, style="ReportBody"):
        return Paragraph(safe_text(text), styles[style])

    def field(label, data, key, style="ReportBody"):
        return labeled(label, (data or {}).get(key), style)

    def labeled(label, val, style="ReportBody"):
        return Paragraph(
            f"<b>{escape(str(label))}:</b> {safe_text(val)}", styles[style]
        )

    def section(title):
        # Keep the VIA/Procedure block together; do not split its fields across pages.
        story.append(CondPageBreak((42 if title == "VIA AND PROCEDURE" else 17) * mm))
        story.append(Paragraph(escape(title), styles["ReportSection"]))

    def subsection(title):
        story.append(CondPageBreak(12 * mm))
        story.append(Paragraph(escape(title), styles["ReportSubsection"]))

    def two_col(rows):
        formatted = []
        for left, right in rows:
            formatted.append([
                labeled(*left) if left else Paragraph("&#160;", styles["ReportBody"]),
                labeled(*right) if right else Paragraph("&#160;", styles["ReportBody"]),
            ])
        table = Table(formatted, colWidths=[usable_width / 2] * 2,
                      hAlign="LEFT", splitByRow=1)
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        story.append(table)

    def pairs(data, fields):
        items = [(label, (data or {}).get(key)) for label, key in fields]
        rows = []
        for i in range(0, len(items), 2):
            rows.append((items[i], items[i + 1] if i + 1 < len(items) else None))
        two_col(rows)

    def coded(data, key, mapping):
        raw = (data or {}).get(key)
        if raw is None or str(raw).strip() == "":
            return "Not assessed"
        try:
            return mapping.get(int(raw), str(raw))
        except (ValueError, TypeError):
            return str(raw)

    def yes_no(data, key):
        return coded(data, key, {0: "No", 1: "Yes"})

    # Header and clinical information.
    story.append(Paragraph("CMU Colposcopy Registry", styles["ReportTitle"]))
    story.append(Paragraph(
        "CLINICAL HISTORY &amp; COLPOSCOPY RECORD",
        styles["ReportSubtitle"],
    ))

    section("PATIENT INFORMATION")
    two_col([
        (("HN", patient.get("hn")), ("Name", patient.get("patient_name"))),
        (("Appointment Date", patient.get("appointment_date")),
         ("Colposcopy Date", record.get("colposcopy_date"))),
    ])

    section("CLINICAL HISTORY")
    pairs(review, [
        ("Age", "age"), ("Parity", "parity"),
        ("LMP", "lmp"), ("Menstrual Status", "menstrual_status"),
        ("First Intercourse Age", "first_intercourse_age"),
        ("Number of Sexual Partners", "number_of_partners"),
        ("HIV Status", "hiv_status"), ("History of STDs", "history_of_stds"),
        ("Smoking Status", "smoking_status"), ("Contraception", "contraception"),
        ("Menopause Duration", "menopause_duration"), ("HRT History", "hrt_history"),
    ])

    section("CERVICAL SCREENING HISTORY")
    pairs(review, [
        ("Pap Smear Result", "pap_smear_result"),
        ("Pap Smear Date", "pap_smear_date"),
        ("Pap Smear Location", "pap_smear_location"),
        ("Pathology Number", "patho_number"),
        ("HPV Result", "hpv_result"),
        ("HPV Genotype", "hpv_genotype"),
        ("HPV Vaccinated", "hpv_vaccinated"),
        ("HPV Vaccine Type", "hpv_vaccine_type"),
        ("HPV Vaccination Completion", "hpv_vaccine_completion_date"),
    ])

    section("ADDITIONAL CLINICAL HISTORY")
    story.append(paragraph(value(review, "previous_history")))
    if review.get("reviewed_by") or review.get("review_date"):
        two_col([(("Clinical History Reviewed By", review.get("reviewed_by")),
                  ("Clinical History Review Date", review.get("review_date")))])

    section("COLPOSCOPIC FINDINGS")
    two_col([
        (("Colposcopy Satisfactory", coded(record, "colposcopy_satisfactory",
            {0: "Unsatisfactory", 1: "Satisfactory"})),
         ("Transformation Zone", coded(record, "tzone",
            {1: "Type 1", 2: "Type 2", 3: "Type 3"}))),
    ])
    if record.get("awe_other_selected"):
        awe_label = "Other"
    else:
        awe_label = coded(record, "awe", {
            0: "No acetowhite", 1: "Thin AWE", 2: "Dense AWE",
        })
    story.append(labeled("Acetowhite Epithelium (AWE)", awe_label))
    if awe_label in ("Thin AWE", "Dense AWE"):
        story.append(field("AWE Location / Clock Position", record, "awe_clock_position"))
    if record.get("awe_other_selected"):
        story.append(field("Specify Other AWE", record, "awe_other_text"))

    subsection("Additional Colposcopic Findings")
    finding_names = [
        ("Leukoplakia", "leukoplakia"),
        ("Condyloma", "condyloma"),
        ("Exophytic", "exophytic"),
        ("Ulcerative", "ulcerative"),
        ("Punctation", "punctation"),
        ("Mosaic", "mosaic"),
        ("Suspicious", "suspicious"),
    ]
    for label, key in finding_names:
        detail = record.get(f"{key}_detail")
        display = yes_no(record, key)
        if detail and str(detail).strip():
            display += " - " + str(detail).strip()
        story.append(labeled(label, display))

    subsection("Colposcopic Impression")
    story.append(labeled("Impression", coded(record, "colposcopy_ci", {
        0: "Normal", 1: "Unsatisfactory", 2: "Low grade",
        3: "High grade", 4: "Invasive",
    })))
    subsection("Colposcopic Description")
    story.append(paragraph(value(record, "colposcopy_description")))

    section("VIA AND PROCEDURE")
    story.append(field("VIA Result", record, "via_result"))
    story.append(field("Procedure", record, "procedure_type"))
    story.append(field("Biopsy Site / Clock Position", record, "biopsy_site"))
    story.append(field("Procedure Notes / Additional Details", record, "procedure_notes"))
    story.append(field("Performed By", record, "performed_by"))

    section("CERVICAL DIAGRAM")
    path_value = record.get("cervical_diagram_path")
    diagram = None
    if path_value:
        image_path = Path(path_value)
        if not image_path.is_absolute():
            image_path = Path(__file__).resolve().parent / image_path
        if image_path.is_file():
            try:
                from PIL import Image as PILImage
                with PILImage.open(image_path) as img:
                    iw, ih = img.size
                    img.verify()
                max_w, max_h = 110 * mm, 60 * mm
                scale = min(max_w / iw, max_h / ih)
                diagram = RLImage(str(image_path), width=iw * scale,
                                  height=ih * scale)
            except (OSError, ValueError):
                diagram = None
    if diagram is not None:
        story.append(diagram)
    else:
        story.append(paragraph("No saved cervical diagram available."))

    section("REMARK")
    story.append(paragraph(value(record, "colposcopy_remark")))

    section("SPECIMEN COLLECTION")
    if not specimens:
        story.append(paragraph("No specimen records saved."))
    for index, specimen in enumerate(specimens, 1):
        story.append(CondPageBreak(27 * mm))
        label = text_value(specimen.get("specimen_label"))
        subsection(f"Specimen {index} - {label}")
        two_col([
            (("Specimen ID", specimen.get("id")),
             ("Specimen Type", specimen.get("specimen_type"))),
            (("Biopsy Site / Clock Position", specimen.get("biopsy_site")),
             ("Collection Status", "Collected" if specimen.get("collection_date")
              else "Not collected")),
            (("Collection Date", specimen.get("collection_date")),
             ("Specimen Order", specimen.get("specimen_order"))),
        ])
        story.append(field("Specimen Remark", specimen, "specimen_remark"))

    story.append(Spacer(1, 2 * mm))
    story.append(paragraph("Signature: _____________________________________"))

    def draw_footer(canvas, document):
        canvas.saveState()
        canvas.setFont("THSarabun", 10)
        canvas.setFillColor(colors.HexColor("#666666"))
        hn = text_value(patient.get("hn"))
        canvas.drawString(12 * mm, 7 * mm, f"HN: {hn}")
        canvas.drawRightString(A4[0] - 12 * mm, 7 * mm,
                               f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
