"""Read-only PDF report for one saved Pathology Review appointment.

Uses the TH Sarabun fonts registered by the existing pdf_export.py module.
No database access or mutation occurs in this module.
"""

from io import BytesIO
from xml.sax.saxutils import escape

# Importing pdf_export also registers the existing TH Sarabun font family.
import pdf_export  # noqa: F401
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#18334C")
GRAY = colors.HexColor("#637283")
PALE = colors.HexColor("#F0F4F8")
LINE = colors.HexColor("#D7E0E8")

MANAGEMENT_LABELS = {
    "LEEP": "LEEP",
    "LEEP_ECC": "LEEP + ECC",
    "CKC": "CKC",
    "REPEAT_COLPOSCOPY": "Repeat colposcopy",
    "REPEAT_LEEP": "Repeat LEEP",
    "FOLLOW_UP": "Follow-up",
    "OTHER": "Other",
}
FOLLOWUP_LABELS = {
    "PAP_SMEAR": "Pap smear",
    "COTEST": "Co-testing",
    "PRIMARY_HPV": "Primary HPV testing",
}
COLPOSCOPY_IMPRESSIONS = {
    0: "Normal",
    1: "Unsatisfactory",
    2: "Low grade",
    3: "High grade",
    4: "Invasive",
}


def generate_pathology_review_pdf(
    patient,
    clinical_history,
    colposcopy_record,
    pathology_review,
    collected_specimens,
    pathology_specimens,
    management_plans,
    leep_queue=None,
):
    """Return PDF bytes for ONE appointment, using only supplied saved records.

    Never includes pathology results from other appointments. Empty fields are
    printed as '-' rather than inferred. PDF is NOT an issued lab report.
    """
    patient = patient or {}
    clinical_history = clinical_history or {}
    colposcopy_record = colposcopy_record or {}
    pathology_review = pathology_review or {}
    collected_specimens = collected_specimens or []
    pathology_specimens = pathology_specimens or []
    management_plans = management_plans or {}
    leep_queue = leep_queue or []
    # This is the saved procedure queue for the selected appointment only.
    # Management plans describe intent; queue status describes execution.
    queue_by_code = {item.get("management_code"): item for item in leep_queue}

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=11 * mm,
        bottomMargin=16 * mm,
        title="CMU Colposcopy Registry - Pathology Review",
        author="CMU Colposcopy Registry",
    )
    page_width = A4[0] - 24 * mm
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="PRTitle", fontName="THSarabun-Bold", fontSize=19,
        leading=21, alignment=TA_CENTER, textColor=NAVY, spaceAfter=0,
    ))
    styles.add(ParagraphStyle(
        name="PRSubtitle", fontName="THSarabun", fontSize=11,
        leading=13, alignment=TA_CENTER, textColor=GRAY, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="PRSection", fontName="THSarabun-Bold", fontSize=14,
        leading=16, textColor=NAVY, spaceBefore=6, spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name="PRBody", fontName="THSarabun", fontSize=12,
        leading=14.5, spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        name="PRSmall", fontName="THSarabun", fontSize=11,
        leading=13, spaceAfter=0,
    ))
    styles.add(ParagraphStyle(
        name="PRSpecimen", fontName="THSarabun-Bold", fontSize=12.5,
        leading=15, textColor=NAVY, spaceBefore=4, spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        name="PRAlert", fontName="THSarabun-Bold", fontSize=11,
        leading=13, alignment=TA_CENTER, textColor=colors.HexColor("#9A332E"),
        spaceAfter=4,
    ))

    def val(value):
        if value is None or not str(value).strip():
            return "-"
        return str(value)

    def safe(value):
        return escape(val(value)).replace("\r\n", "\n").replace("\n", "<br/>")

    def body(text, small=False):
        return Paragraph(safe(text), styles["PRSmall" if small else "PRBody"])

    def field(label, value, small=False):
        return Paragraph(
            f"<b>{escape(label)}:</b> {safe(value)}",
            styles["PRSmall" if small else "PRBody"],
        )

    def section(label):
        story.append(CondPageBreak(20 * mm))
        story.append(Paragraph(escape(label), styles["PRSection"]))

    def two_columns(rows):
        cells = [[field(*left), field(*right)] for left, right in rows]
        t = Table(cells, colWidths=[page_width * 0.50] * 2, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        story.append(t)

    story = [
        Paragraph("CMU COLPOSCOPY REGISTRY", styles["PRTitle"]),
        Paragraph("PATHOLOGY REVIEW REPORT", styles["PRSubtitle"]),
        Paragraph("DEMO ONLY - NOT FOR CLINICAL USE", styles["PRAlert"]),
        HRFlowable(width="100%", thickness=0.8, color=NAVY),
        Spacer(1, 3 * mm),
    ]

    section("PATIENT AND REVIEW INFORMATION")
    two_columns([
        (("HN", patient.get("hn")), ("Patient", patient.get("patient_name"))),
        (("Age (years)", clinical_history.get("age")),
         ("Appointment ID", patient.get("id"))),
        (("Appointment date", patient.get("appointment_date")),
         ("Appointment status", patient.get("status"))),
        (("Review date", pathology_review.get("review_date")),
         ("Reviewed by", pathology_review.get("reviewed_by"))),
    ])

    section("PREVIOUS SCREENING AND COLPOSCOPY")
    ci = pathology_review.get("colposcopy_impression")
    if not ci or ci == "Not assessed":
        ci = COLPOSCOPY_IMPRESSIONS.get(
            colposcopy_record.get("colposcopy_ci"), "Not assessed"
        )
    adequacy = pathology_review.get("colposcopy_adequacy")
    if not adequacy or adequacy == "Not assessed":
        satisfactory = colposcopy_record.get("colposcopy_satisfactory")
        adequacy = {0: "Unsatisfactory", 1: "Satisfactory"}.get(
            satisfactory, "Not assessed"
        )
    two_columns([
        (("Previous Pap smear", clinical_history.get("pap_smear_result")),
         ("Review cytology", pathology_review.get("cytology_result"))),
        (("HIV status", clinical_history.get("hiv_status")),
         ("Colposcopy adequacy", adequacy)),
        (("Colposcopic impression", ci),
         ("Endocervical sampling", pathology_review.get("endocervical_sampling"))),
        (("Endocervical result", pathology_review.get("endocervical_result")),
         ("Colposcopy date", colposcopy_record.get("colposcopy_date"))),
    ])

    section("PATHOLOGY SPECIMEN RESULTS")
    collected = [s for s in collected_specimens if s.get("collection_date")]
    result_by_source = {
        p.get("colposcopy_specimen_id"): p
        for p in pathology_specimens
        if p.get("colposcopy_specimen_id") is not None
    }
    reported = sum(
        bool(str(result_by_source.get(s.get("id"), {}).get("pathology_diagnosis") or "").strip())
        for s in collected
    )
    total = len(collected)
    status = (
        "Full reported" if total and reported == total else
        "Partial reported" if reported else "Pending"
    )
    story.append(field(
        "Reporting status",
        f"{reported}/{total} collected specimens reported ({status})",
    ))

    if not collected:
        story.append(body("No collected specimens for this appointment."))
    else:
        for source in collected:
            result = result_by_source.get(source.get("id"), {})
            diagnosis = result.get("pathology_diagnosis")
            is_reported = bool(str(diagnosis or "").strip())
            label = source.get("specimen_label") or source.get("id")
            story.append(CondPageBreak(24 * mm))
            story.append(Paragraph(
                escape(f"Specimen {label} (ID {source.get('id')}) - "
                       f"{'Reported' if is_reported else 'Pending'}"),
                styles["PRSpecimen"],
            ))
            two_columns([
                (("Specimen type", source.get("specimen_type")),
                 ("Biopsy site", source.get("biopsy_site"))),
                (("Collection date", source.get("collection_date")),
                 ("Pathology number", result.get("pathology_number"))),
            ])
            story.append(field("Pathology diagnosis", diagnosis))
            if any(result.get(k) not in (None, "", "Not assessed") for k in (
                "cancer_subtype", "invasion_depth_mm", "invasion_width_mm", "lvsi"
            )):
                two_columns([
                    (("Cancer subtype", result.get("cancer_subtype")),
                     ("LVSI", result.get("lvsi"))),
                    (("Invasion depth (mm)", result.get("invasion_depth_mm")),
                     ("Invasion width (mm)", result.get("invasion_width_mm"))),
                ])
            if result.get("specimen_remark"):
                story.append(field("Pathology remark", result["specimen_remark"]))
            story.append(Spacer(1, 1 * mm))

    # Legacy records without a source specimen ID should not silently disappear.
    legacy = [p for p in pathology_specimens
              if p.get("colposcopy_specimen_id") is None]
    if legacy:
        story.append(Paragraph("Unlinked historical pathology results", styles["PRSpecimen"]))
        for result in legacy:
            story.append(field("Specimen", result.get("specimen_type")))
            story.append(field("Site", result.get("biopsy_site")))
            story.append(field("Pathology number", result.get("pathology_number")))
            story.append(field("Diagnosis", result.get("pathology_diagnosis")))

    section("CORRELATION AND MANAGEMENT")
    story.append(field("Colposcopy-pathology correlation", pathology_review.get("correlation") or "Not assessed"))
    if management_plans:
        for code, plan in management_plans.items():
            label = MANAGEMENT_LABELS.get(code, code)
            details = []
            if plan.get("planned_date"):
                details.append("Planned date: " + str(plan["planned_date"]))
            if code in ("LEEP", "LEEP_ECC", "REPEAT_LEEP"):
                queue_item = queue_by_code.get(code)
                if queue_item:
                    details.append("Queue status: " + val(queue_item.get("status")))
                    if queue_item.get("performed_date"):
                        details.append("Performed date: " + str(queue_item["performed_date"]))
                else:
                    details.append("Queue status: Not recorded")
            if code == "FOLLOW_UP":
                tests = [FOLLOWUP_LABELS.get(t, t) for t in plan.get("followup_tests", [])]
                if tests:
                    details.append("Tests: " + ", ".join(tests))
                if plan.get("followup_interval_months"):
                    details.append(
                        f"First follow-up: {plan['followup_interval_months']} month(s)"
                    )
            if plan.get("other_detail"):
                details.append(str(plan["other_detail"]))
            story.append(field(label, "; ".join(details) if details else "Selected"))
    else:
        story.append(body("No management plan saved."))

    # Include historical queue entries even when their corresponding management
    # plan has been removed. Otherwise cancelled/completed work could disappear.
    orphan_queue = [item for item in leep_queue
                    if item.get("management_code") not in management_plans]
    if orphan_queue:
        story.append(Paragraph("Historical LEEP Queue entries", styles["PRSpecimen"]))
        for item in orphan_queue:
            code = item.get("management_code")
            details = ["Queue status: " + val(item.get("status"))]
            if item.get("planned_date"):
                details.append("Planned date: " + str(item["planned_date"]))
            if item.get("performed_date"):
                details.append("Performed date: " + str(item["performed_date"]))
            story.append(field(MANAGEMENT_LABELS.get(code, val(code)), "; ".join(details)))
    if pathology_review.get("management_comment"):
        story.append(field("Management comment", pathology_review["management_comment"]))

    notes = [
        ("Review note", pathology_review.get("review_note")),
        ("Additional note", pathology_review.get("additional_note")),
    ]
    if any(text for _, text in notes):
        section("REVIEW NOTES")
        for label, note in notes:
            if note:
                story.append(field(label, note))

    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=LINE))
    story.append(Paragraph(
        "Management plan dates indicate intent; queue status reflects the saved "
        "procedure workflow. This is not an issued pathology laboratory report.",
        styles["PRSmall"]
    ))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(12 * mm, 12 * mm, A4[0] - 12 * mm, 12 * mm)
        canvas.setFont("THSarabun", 9.5)
        canvas.setFillColor(GRAY)
        canvas.drawString(12 * mm, 8 * mm, "CMU Colposcopy Registry | Pathology Review")
        canvas.drawRightString(A4[0] - 12 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
