"""Print-ready LEEP Day Note PDF from SAVED registry records only.

No database writes, no scans, and no claims of procedure completion.
The module imports pdf_export to reuse the application's existing TH Sarabun
font registration; keep the existing pdf_export.py and fonts/ unchanged.
"""
from io import BytesIO
from xml.sax.saxutils import escape

import pdf_export  # noqa: F401 - registers TH Sarabun family
from reportlab.graphics.shapes import Circle, Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, KeepInFrame, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

INK = colors.HexColor('#1B2C3B')
MUTED = colors.HexColor('#526273')
RULE = colors.HexColor('#CBD4DC')
LIGHT = colors.HexColor('#F3F6F9')
PROCEDURES = {'LEEP': 'LEEP', 'LEEP_ECC': 'LEEP + ECC', 'REPEAT_LEEP': 'Repeat LEEP'}
IMPRESSIONS = {0: 'Normal', 1: 'Unsatisfactory', 2: 'Low grade', 3: 'High grade', 4: 'Invasive'}


def _text(value):
    if value is None or not str(value).strip():
        return '-'
    return str(value).strip()


def _safe(value):
    return escape(_text(value)).replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br/>')


def _diagram():
    """Blank cervical clock diagram to annotate on the printed sheet."""
    w, h = 91 * mm, 42 * mm
    d = Drawing(w, h)
    cx, cy, r = w / 2, h / 2, 14 * mm
    d.add(Circle(cx, cy, r, strokeColor=INK, fillColor=None, strokeWidth=0.8))
    d.add(Circle(cx, cy, 3 * mm, strokeColor=RULE, fillColor=None, strokeWidth=0.7))
    # Clock points and generous handwriting lines for specimen orientation.
    for label, x, y in [
        ('12 O\'C', cx, cy + r + 3.3 * mm),
        ('6 O\'C', cx, cy - r - 4.7 * mm),
        ('9 O\'C', cx - r - 12 * mm, cy),
        ('3 O\'C', cx + r + 9 * mm, cy),
    ]:
        d.add(String(x, y, label, fontName='THSarabun', fontSize=10,
                     fillColor=MUTED, textAnchor='middle'))
    return d


def _writing_lines(count, width=86 * mm, line_gap=6.2 * mm):
    """Pale handwriting rules; these are never stored as clinical data."""
    h = count * line_gap + 1 * mm
    drawing = Drawing(width, h)
    for i in range(count):
        y = h - (i + 1) * line_gap
        drawing.add(Line(1 * mm, y, width - 1 * mm, y,
                         strokeColor=RULE, strokeWidth=0.65))
    return drawing


class _OnePageColumn(KeepInFrame):
    """Fit a column on one sheet, but refuse unreadably tiny text."""
    def wrap(self, availWidth, availHeight):
        size = super().wrap(availWidth, availHeight)
        # KeepInFrame._scale > 1 means rendered type is reduced by that factor.
        if getattr(self, '_scale', 1.0) > 1.35:
            raise ValueError(
                'LEEP Day Note content is too long for one readable A4 page. '
                'Please shorten the clinical history or additional notes and export again.'
            )
        return size


def generate_leep_day_note_pdf(*, patient, queue, clinical_history,
                               colposcopy_record, pathology_specimens, day_note):
    """Return print-ready PDF bytes for ONE saved LEEP queue entry.

    Caller must fetch saved rows. The note must have been saved (not an
    unsaved Streamlit widget value). This function is read-only.
    """
    if not patient or not queue or not day_note or not day_note.get('id'):
        raise ValueError('Saved patient, queue and LEEP Day Note are required')
    if int(queue['source_appointment_id']) != int(patient['id']):
        raise ValueError('Queue/source appointment mismatch')
    if int(day_note['leep_queue_id']) != int(queue['id']):
        raise ValueError('LEEP Day Note/queue mismatch')
    clinical_history = clinical_history or {}
    colposcopy_record = colposcopy_record or {}
    pathology_specimens = pathology_specimens or []

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=9 * mm, bottomMargin=12 * mm,
        title='CMU Colposcopy Registry - LEEP Day Note',
        author='CMU Colposcopy Registry',
    )
    width = A4[0] - 20 * mm
    col_width = (width - 5 * mm) / 2

    title = ParagraphStyle('LEEPTitle', fontName='THSarabun-Bold', fontSize=18,
                           leading=20, textColor=INK, alignment=TA_CENTER)
    subtitle = ParagraphStyle('LEEPSubtitle', fontName='THSarabun', fontSize=11,
                              leading=13, textColor=MUTED, alignment=TA_CENTER)
    heading = ParagraphStyle('LEEPHeading', fontName='THSarabun-Bold', fontSize=13,
                             leading=15, textColor=INK, spaceBefore=4, spaceAfter=2)
    body = ParagraphStyle('LEEPBody', fontName='THSarabun', fontSize=11.5,
                          leading=13.5, alignment=TA_LEFT, spaceAfter=2)
    small = ParagraphStyle('LEEPFoot', fontName='THSarabun', fontSize=9.5,
                           leading=11, textColor=MUTED, spaceAfter=1)
    warn = ParagraphStyle('LEEPWarn', fontName='THSarabun-Bold', fontSize=10,
                          leading=12, textColor=colors.HexColor('#8A3C35'),
                          alignment=TA_CENTER)

    def para(text, style=body):
        return Paragraph(_safe(text), style)

    def field(label, value):
        return Paragraph(f'<b>{escape(label)}:</b> {_safe(value)}', body)

    def section(target, label):
        target.append(Paragraph(escape(label), heading))
        target.append(HRFlowable(width='100%', thickness=0.45, color=RULE))
        target.append(Spacer(1, 1.2 * mm))

    left, right = [], []
    section(left, 'PATIENT INFORMATION')
    for label, value in [
        ('HN', patient.get('hn')),
        ('Patient', patient.get('patient_name')),
        ('Age', clinical_history.get('age')),
        ('Parity', clinical_history.get('parity')),
        ('LMP', clinical_history.get('lmp')),
        ('Contraception', clinical_history.get('contraception')),
        ('HPV vaccination', clinical_history.get('hpv_vaccinated')),
        ('HPV vaccine type', clinical_history.get('hpv_vaccine_type')),
        ('HIV status (prior record)', clinical_history.get('hiv_status')),
    ]:
        if _text(value) != '-':
            left.append(field(label, value))

    section(left, 'CLINICAL HISTORY & SCREENING')
    for label, value in [
        ('Pap smear', clinical_history.get('pap_smear_result')),
        ('Pap date', clinical_history.get('pap_smear_date')),
        ('HPV test', clinical_history.get('hpv_result')),
        ('HPV genotype', clinical_history.get('hpv_genotype')),
        ('Previous history', clinical_history.get('previous_history')),
    ]:
        if _text(value) != '-':
            left.append(field(label, value))

    section(left, 'PREVIOUS COLPOSCOPY')
    for label, value in [
        ('Colposcopy date', colposcopy_record.get('colposcopy_date')),
        ('TZ type', colposcopy_record.get('tzone')),
        ('Impression', IMPRESSIONS.get(colposcopy_record.get('colposcopy_ci'))),
        ('Findings', colposcopy_record.get('colposcopy_description')),
    ]:
        if _text(value) != '-':
            left.append(field(label, value))

    section(left, 'PREVIOUS PATHOLOGY')
    has_pathology = False
    for specimen in pathology_specimens:
        diagnosis = specimen.get('pathology_diagnosis')
        if not diagnosis or not str(diagnosis).strip():
            continue
        has_pathology = True
        site = specimen.get('biopsy_site') or specimen.get('specimen_type') or 'Specimen'
        accession = specimen.get('pathology_number')
        description = f'{site}: {diagnosis}'
        if accession:
            description += f' (Patho No. {accession})'
        left.append(para(description))
    if not has_pathology:
        left.append(para('No saved specimen diagnosis.'))

    section(left, 'ADDITIONAL HISTORY (HANDWRITTEN)')
    left.append(_writing_lines(4))

    section(right, 'TODAY\'S CLINICAL NOTE')
    right.append(para(day_note.get('clinical_note')))
    section(right, 'CERVICAL DIAGRAM (ANNOTATE ON PAPER)')
    right.append(_diagram())
    right.append(para("Specimen pins: 12 ____  3 ____  6 ____  9 ____", small))
    section(right, 'Mx / PLANNED PROCEDURE')
    right.append(para(day_note.get('management_note')))
    section(right, 'PLAN')
    right.append(para(day_note.get('plan_note')))
    section(right, 'HM / MEDICATION (DRAFT - VERIFY)')
    right.append(para(day_note.get('medication_note')))
    right.append(para('Medication template is not a verified prescription.', small))
    section(right, 'ADDITIONAL CLINICAL NOTE')
    if (day_note.get('additional_note') or '').strip():
        right.append(para(day_note['additional_note']))
        right.append(_writing_lines(3))
    else:
        right.append(_writing_lines(6))
    right.append(Spacer(1, 2 * mm))
    right.append(para('Operator: __________________  Time: __________', small))

    story = [
        Paragraph('CMU COLPOSCOPY REGISTRY - LEEP DAY NOTE', title),
        Paragraph('Pre-procedure preparation / print-and-annotate sheet', subtitle),
        Paragraph('DEMO ONLY - NOT FOR CLINICAL USE', warn),
        Spacer(1, 1.5 * mm),
        HRFlowable(width='100%', thickness=0.8, color=INK),
        Spacer(1, 2 * mm),
    ]
    meta = [
        [field('Queue ID', queue.get('id')),
         field('Source appointment ID', patient.get('id')),
         field('Procedure', PROCEDURES.get(queue.get('management_code'), queue.get('management_code')))],
        [field('Planned date', queue.get('planned_date')),
         field('Queue status', queue.get('status')),
         field('Performed date (queue)', queue.get('performed_date'))],
    ]
    meta_table = Table(meta, colWidths=[width / 3] * 3, hAlign='LEFT')
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.extend([meta_table, Spacer(1, 3 * mm)])

    # Each column is independently fitted to the available page height.
    # This prevents ReportLab from silently generating a second sheet.
    column_height = 229 * mm
    columns = Table([[
        _OnePageColumn(col_width - 5 * mm, column_height, left,
                       mode='shrink', vAlign='TOP', name='Clinical history'),
        _OnePageColumn(col_width - 5 * mm, column_height, right,
                       mode='shrink', vAlign='TOP', name='Procedure note'),
    ]], colWidths=[col_width, col_width],
                    hAlign='LEFT', splitByRow=0, splitInRow=0)
    columns.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBEFORE', (1, 0), (1, -1), 0.55, RULE),
        ('LEFTPADDING', (0, 0), (0, -1), 0),
        ('RIGHTPADDING', (0, 0), (0, -1), 5 * mm),
        ('LEFTPADDING', (1, 0), (1, -1), 5 * mm),
        ('RIGHTPADDING', (1, 0), (1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(columns)
    doc.build(story)
    return buffer.getvalue()
