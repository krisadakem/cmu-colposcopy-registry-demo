


import streamlit as st
from pdf_export import (
    generate_clinical_history_pdf,
    generate_full_colposcopy_pdf,
)
from pathology_pdf_export import generate_pathology_review_pdf
from leep_day_note_pdf_export import generate_leep_day_note_pdf
from datetime import date
from pathlib import Path
from uuid import uuid4
from io import BytesIO
from PIL import Image, UnidentifiedImageError

from database import (
    init_database,
    add_appointment,
    get_appointments,
    search_appointments,
    get_appointment_by_id,
    update_appointment,
    check_duplicate_appointment,
    save_pre_colposcopy_review,
    get_pre_colposcopy_review,
    save_clinical_document,
    get_clinical_documents,
    save_colposcopy_record,
    get_colposcopy_record,
    get_colposcopy_specimens,
    save_colposcopy_specimens,
    COLPOSCOPY_FIELDS,
    get_pathology_worklist,
    get_pathology_review,
    save_pathology_review,
    get_pathology_specimens,
    save_pathology_specimens,
    get_pathology_management_plans,
    save_pathology_management,
    get_repeat_colposcopy_appointment,
    get_leep_queue,
    get_leep_queue_for_appointment,
    create_direct_leep_queue,
    DIRECT_LEEP_INDICATIONS,
    DIRECT_LEEP_NOTE_PREFIX,
    LEGACY_EXPEDITED_NOTE_PREFIX,
    update_leep_queue_entry,
    get_leep_day_note,
    save_leep_day_note,
    LEEP_QUEUE_STATUSES,

)





def build_leep_day_note_source_summary(patient, history, colpo, pathology):
    """Read-only summary of saved source data; never claim missing facts."""
    lines = [
        f"HN: {patient['hn']} | Patient: {patient['patient_name']}",
        f"Source Appointment ID: {patient['id']} | Date: {patient['appointment_date']}",
    ]

    def add(label, value):
        if value is not None and str(value).strip() and str(value).strip() not in (
            "Unknown", "Not documented", "Not assessed"
        ):
            lines.append(f"{label}: {value}")

    add("Age", history.get("age"))
    add("Parity", history.get("parity"))
    add("LMP", history.get("lmp"))
    add("Contraception", history.get("contraception"))
    add("HIV status (saved history)", history.get("hiv_status"))
    add("HPV vaccination", history.get("hpv_vaccinated"))
    add("HPV vaccine type", history.get("hpv_vaccine_type"))
    add("Pap smear", history.get("pap_smear_result"))
    add("Pap smear date", history.get("pap_smear_date"))
    add("HPV test", history.get("hpv_result"))
    add("HPV genotype", history.get("hpv_genotype"))
    add("Previous clinical history", history.get("previous_history"))

    if colpo:
        lines.append("\nPrevious Colposcopy")
        add("Colposcopy date", colpo.get("colposcopy_date"))
        add("TZ type", colpo.get("tzone"))
        add("Colposcopic impression", {
            0: "Normal", 1: "Unsatisfactory", 2: "Low grade",
            3: "High grade", 4: "Invasive",
        }.get(colpo.get("colposcopy_ci")))
        add("Findings", colpo.get("colposcopy_description"))

    if pathology:
        lines.append("\nPrevious Pathology (saved specimens)")
        for specimen in pathology:
            diagnosis = specimen.get("pathology_diagnosis")
            if diagnosis and str(diagnosis).strip():
                site = specimen.get("biopsy_site") or specimen.get("specimen_type") or "Specimen"
                accession = specimen.get("pathology_number")
                lines.append(
                    f"- {site}: {diagnosis}"
                    + (f" (Patho No. {accession})" if accession else "")
                )

    return "\n".join(lines)


def default_leep_day_note_text(queue):
    """Editable PRE-procedure draft. Do not assert a procedure was performed."""
    code = queue["management_code"]
    procedure = {
        "LEEP": "LEEP", "LEEP_ECC": "LEEP + ECC",
        "REPEAT_LEEP": "Repeat LEEP",
    }.get(code, "LEEP")
    planned_date = queue.get("planned_date") or "__________"
    clinical = (
        f"นัดมาทำ {procedure} วันที่ {planned_date}\n"
        "อาการปัจจุบัน: __________\n"
        "Anti-HIV (date/result): __________\n"
        "V/S: __________"
    )
    management = (
        f"- Planned procedure: {procedure}\n"
        "- Loop No.: __________\n"
        "- Number of attempts: __________  Performed by: __________\n"
        + ("- ECC: __________\n" if code == "LEEP_ECC" else "")
        + "- Immediate complications: __________"
    )
    plan = (
        "- F/U pathology: __________\n"
        "- แนะนำอาการผิดปกติที่ต้องกลับมาโรงพยาบาล"
    )
    # User-provided template only, not an authorized prescription.
    medication = (
        "- Paracetamol (500 mg) 1 tab PO PRN q4–6 hr #20\n"
        "- Doxycycline (100 mg) 1 tab PO BID PC #14"
    )
    return {
        "clinical_note": clinical,
        "management_note": management,
        "plan_note": plan,
        "medication_note": medication,
        "additional_note": "",
    }


def build_colposcopy_summary(
    satisfactory, tzone, awe, awe_clock_position, awe_other_text,
    finding_fields, finding_values, finding_details,
):
    """Create an editable, clinical-style summary without UI delimiters."""
    sentences = []
    if satisfactory == "Satisfactory":
        sentences.append("Satisfactory colposcopy.")
    elif satisfactory == "Unsatisfactory":
        sentences.append("Unsatisfactory colposcopy.")

    if tzone != "Not assessed":
        sentences.append(f"Transformation zone {tzone.lower()}.")

    if awe == "No AWE":
        sentences.append("No acetowhite epithelium.")
    elif awe in ("Thin AWE", "Dense AWE"):
        descriptor = "Thin" if awe == "Thin AWE" else "Dense"
        location = awe_clock_position.strip()
        sentence = f"{descriptor} acetowhite epithelium"
        if location:
            sentence += f" at {location}"
        sentences.append(sentence.rstrip(". ") + ".")
    elif awe == "Other":
        description = awe_other_text.strip()
        sentences.append(
            "Other acetowhite finding: " + description.rstrip(". ") + "."
            if description else "Other acetowhite finding (not specified)."
        )

    for field, label in finding_fields.items():
        if finding_values.get(field) == 1:
            detail = (finding_details.get(field) or "").strip()
            sentence = f"{label}: {detail}" if detail else f"{label} present"
            sentences.append(sentence.rstrip(". ") + ".")

    return " ".join(sentences) if sentences else "No findings entered."


def clean_legacy_colposcopy_description(text):
    """Remove visible delimiters used by the earlier version, retaining text."""
    text = text or ""
    start_marker = "[Findings summary]"
    end_marker = "[/Findings summary]"
    if (start_marker not in text or end_marker not in text
            or text.index(start_marker) >= text.index(end_marker)):
        return text, ""
    before, remainder = text.split(start_marker, 1)
    summary, after = remainder.split(end_marker, 1)
    summary = summary.strip()
    parts = [part.strip() for part in (before, summary, after) if part.strip()]
    return "\n\n".join(parts), summary


def refresh_colposcopy_description(text, old_generated, new_generated):
    """Replace only known generated text; never delete unmatched manual notes."""
    text = text or ""
    old_generated = old_generated or ""
    if old_generated and old_generated in text:
        return text.replace(old_generated, new_generated, 1)
    return new_generated + ("\n\n" + text if text.strip() else "")

def infer_legacy_generated_summary(text):
    """Identify an older machine-generated first paragraph, if recognizable.

    Existing manually entered text after a blank line remains untouched.
    Unrecognized descriptions are never removed automatically.
    """
    first_paragraph = (text or "").strip().split("\n\n", 1)[0].strip()
    starts_generated = first_paragraph.startswith((
        "Satisfactory colposcopy.",
        "Unsatisfactory colposcopy.",
        "Transformation zone ",
        "No acetowhite epithelium.",
        "Thin acetowhite epithelium",
        "Dense acetowhite epithelium",
        "Other acetowhite finding",
    ))
    if starts_generated and (
        "acetowhite" in first_paragraph.lower()
        or "transformation zone" in first_paragraph.lower()
    ):
        return first_paragraph
    return ""



def show_pathology_pdf_download(appointment_id, *, key_suffix="active"):
    """Offer a PDF made from SAVED rows only, never unsaved widget values."""
    patient = get_appointment_by_id(appointment_id)
    if not patient:
        st.error("Appointment not found. PDF cannot be generated.")
        return

    saved_review = get_pathology_review(appointment_id) or {}
    saved_results = get_pathology_specimens(appointment_id)
    saved_plans = get_pathology_management_plans(appointment_id)

    st.subheader("Export Pathology Review PDF")
    if not (saved_review or saved_results or saved_plans):
        st.info("Save a Pathology Review, specimen result, or management plan before exporting.")
        return

    try:
        pdf_bytes = generate_pathology_review_pdf(
            patient=patient,
            clinical_history=get_pre_colposcopy_review(appointment_id) or {},
            colposcopy_record=get_colposcopy_record(appointment_id) or {},
            pathology_review=saved_review,
            collected_specimens=get_colposcopy_specimens(appointment_id),
            pathology_specimens=saved_results,
            management_plans=saved_plans,
            leep_queue=get_leep_queue_for_appointment(appointment_id),
        )
        st.download_button(
            "Download Pathology Review PDF",
            data=pdf_bytes,
            file_name=f"Pathology_Review_{patient['hn']}_Appointment_{appointment_id}.pdf",
            mime="application/pdf",
            key=f"pathology_review_pdf_{key_suffix}_{appointment_id}",
        )
        st.caption("Exports saved data only. Unsaved edits are not included. "
                   "Separate report from the Colposcopy Record PDF.")
    except Exception as error:
        st.error(f"Pathology Review PDF generation failed: {error}")


# Step 6.7D.3.6.5.10 — Cancelled appointments are read-only.
# This check is deliberately repeated at each Save action to catch status
# changes made in Appointment Booking after the form was opened.
def require_non_cancelled_appointment(appointment_id):
    current = get_appointment_by_id(appointment_id)
    if current is None:
        st.error("Appointment no longer exists. Nothing was saved.")
        st.stop()
    if current["status"] == "Cancelled":
        st.error(
            f"Appointment ID {appointment_id} is Cancelled. "
            "Clinical records cannot be created or modified. Nothing was saved."
        )
        st.stop()


def show_cancelled_appointment_readonly(appointment_id, section):
    """Show existing records but never render clinical edit/save widgets."""
    current = get_appointment_by_id(appointment_id)
    if current is None or current["status"] != "Cancelled":
        return

    st.warning(
        f"Appointment ID {appointment_id} is Cancelled "
        f"({current['appointment_date']}). READ-ONLY: "
        "clinical editing and saving are disabled. "
        "To document a performed procedure, use an appropriate "
        "non-cancelled appointment."
    )
    st.caption(
        f"HN: {current['hn']} | Patient: {current['patient_name']} | "
        f"Indication: {current['indication']}"
    )

    if section == "pre":
        history = get_pre_colposcopy_review(appointment_id)
        st.subheader("Saved Clinical History (read-only)")
        if history:
            st.json(history, expanded=False)
        else:
            st.info("No Clinical History saved for this appointment.")

    elif section == "colposcopy":
        record = get_colposcopy_record(appointment_id)
        specimens = get_colposcopy_specimens(appointment_id)
        st.subheader("Saved Colposcopy Record (read-only)")
        if record:
            st.json(
                {k: v for k, v in record.items()
                 if k != "cervical_diagram_path"},
                expanded=False,
            )
            # Keep export available in read-only mode.
            try:
                pdf_bytes = generate_full_colposcopy_pdf(
                    current,
                    get_pre_colposcopy_review(appointment_id) or {},
                    record,
                    specimens=specimens,
                )
                st.download_button(
                    "Download Colposcopy Record PDF",
                    data=pdf_bytes,
                    file_name=f"Colposcopy_Record_{appointment_id}.pdf",
                    mime="application/pdf",
                    key=f"cancelled_colpo_pdf_{appointment_id}",
                )
            except Exception as error:
                st.error(f"PDF generation failed: {error}")
        else:
            st.info("No Colposcopy Record saved for this appointment.")
        st.subheader("Saved Specimens (read-only)")
        if specimens:
            st.dataframe(specimens, use_container_width=True, hide_index=True)
        else:
            st.info("No specimens saved for this appointment.")

    elif section == "pathology":
        review = get_pathology_review(appointment_id)
        specimens = get_pathology_specimens(appointment_id)
        plans = get_pathology_management_plans(appointment_id)
        st.subheader("Saved Pathology Review (read-only)")
        if review:
            st.json(review, expanded=False)
        else:
            st.info("No Pathology Review saved for this appointment.")
        st.subheader("Saved Pathology Specimens (read-only)")
        if specimens:
            st.dataframe(specimens, use_container_width=True, hide_index=True)
        else:
            st.info("No Pathology Specimen results saved.")
        st.subheader("Saved Management Plans (read-only)")
        if plans:
            st.json(plans, expanded=False)
        else:
            st.info("No Management Plan saved for this appointment.")
        queue = get_leep_queue_for_appointment(appointment_id)
        if queue:
            st.subheader("Linked LEEP Queue (read-only)")
            st.dataframe(queue, use_container_width=True, hide_index=True)
        st.divider()
        show_pathology_pdf_download(appointment_id, key_suffix="cancelled")

    # Stop processing this page: no form, button, or save action is rendered.
    st.stop()


st.set_page_config(
    page_title="CMU Colposcopy Registry",
    page_icon="🏥",
    layout="wide"
)

# Initialize SQLite database
init_database()

st.title("CMU Colposcopy Registry")
st.caption("Colposcopy Clinic Management System | Prototype V1")
st.warning("DEMO ONLY — Use fictional patient data.")

menu = st.sidebar.radio(
    "Navigation",
    [
        "Appointments",
        "Pre-colposcopy Review",
        "Colposcopy Record",
        "Pathology Worklist",
        "Pathology Review",
        "LEEP Queue",
        "Excel Export"
    ]
)

if menu == "Appointments":
    st.header("Daily Appointment List")

    selected_date = st.date_input(
        "Appointment Date",
        value=date.today()
    )

    appointments = get_appointments(selected_date)

    st.subheader(f"Appointments: {len(appointments)}")

    if appointments:
        st.dataframe(
            [
                {
                    "HN": a["hn"],
                    "Patient Name": a["patient_name"],
                    "Phone": a["phone"],
                    "Indication": a["indication"],
                   "Registered By": a["registered_by"],
"Status": a["status"]
                }
                for a in appointments
            ],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No appointments registered for this date.")

    st.subheader("Search Patient Appointments")

    keyword = st.text_input(
        "Search by HN or Patient Name",
        placeholder="Enter HN or patient name"
    )

    if keyword.strip():
        results = search_appointments(keyword)

        if results:
            st.dataframe(
                [
                    {
                        "Appointment ID": a["id"],
                        "Date": a["appointment_date"],
                        "HN": a["hn"],
                        "Patient Name": a["patient_name"],
                        "Indication": a["indication"],
                        "Status": a["status"]
                    }
                    for a in results
                ],
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No matching appointments found.")


    st.divider()
    st.subheader("Edit Appointment")

    edit_keyword = st.text_input(
        "Search HN or Name to Edit",
        key="edit_search"
    )

    if edit_keyword.strip():
        edit_results = search_appointments(edit_keyword)

        if edit_results:
            options = {
                f"{a['id']} | {a['hn']} | {a['patient_name']} | {a['appointment_date']}": a["id"]
                for a in edit_results
            }

            selected_label = st.selectbox(
                "Select Appointment",
                options=list(options.keys())
            )

            appointment_id = options[selected_label]
            appointment = get_appointment_by_id(appointment_id)

            if appointment:
                with st.form(
                    "edit_appointment_form",
                    clear_on_submit=False
                ):
                    new_date = st.date_input(
                        "Appointment Date",
                        value=date.fromisoformat(
                            appointment["appointment_date"]
                        )
                    )

                    new_phone = st.text_input(
                        "Phone Number",
                        value=appointment["phone"] or ""
                    )

                    new_indication = st.text_input(
                        "Indication",
                        value=appointment["indication"]
                    )

                    statuses = [
                        "Scheduled",
                        "Completed",
                        "Cancelled",
                        "No-show"
                    ]

                    current_status = appointment["status"]

                    new_status = st.selectbox(
                        "Appointment Status",
                        statuses,
                        index=statuses.index(current_status)
                    )

                    save_changes = st.form_submit_button(
                        "Save Changes"
                    )

                    if save_changes:
                        update_appointment(
                            appointment_id,
                            new_date,
                            new_phone,
                            new_indication,
                            new_status
                        )

                    
                        st.rerun()
        else:
            st.info("No matching appointments found.")

    st.divider()
    st.subheader("Add New Appointment")

    with st.form("appointment_form", clear_on_submit=True):

        col1, col2 = st.columns(2)

        with col1:
            booking_date = st.date_input(
                "Booking Date",
                value=date.today()
            )
    
            appointment_date = st.date_input(
                "Colposcopy Appointment Date",
                value=date.today()
            )

            patient_name = st.text_input("Patient Name")

            hn = st.text_input("HN")

        with col2:
            phone = st.text_input("Phone Number")

            indication = st.selectbox(
                "Indication",
                [
                    "HPV 16 positive",
                    "HPV 18 positive",
                    "Other hrHPV positive",
                    "ASC-US",
                    "ASC-H",
                    "LSIL",
                    "HSIL",
                    "AGC",
                    "Abnormal cervix",
                    "Other"
                ]
            )

            registered_by = st.text_input(
                "Registered By"
            )

        submitted = st.form_submit_button(
            "Save Appointment",
            type="primary"
        )

        
    if submitted:
        if check_duplicate_appointment(hn, appointment_date):
            st.error(
                "Duplicate appointment detected! "
                "This HN already has an appointment "
                "on the selected date."
            )
        else:
            add_appointment(
                booking_date,
                appointment_date,
                patient_name,
                hn,
                phone,
                indication,
                registered_by
            )

            st.success("Appointment registered successfully.")
            st.rerun()



elif menu == "Pre-colposcopy Review":

    st.header("Pre-colposcopy Review")
    st.subheader("Step 1: Patient Selection")

    search_keyword = st.text_input(
        "Search by HN or Patient Name",
        placeholder="Enter HN or patient name",
        key="pre_colpo_search"
    )

    if search_keyword.strip():

        results = search_appointments(search_keyword)

        if results:

            patient_options = {
                f"{row['hn']} | {row['patient_name']} | "
                f"{row['appointment_date']} | ID: {row['id']}": row["id"]
                for row in results
            }

            selected_patient = st.selectbox(
                "Select Appointment",
                options=list(patient_options.keys()),
                key="pre_colpo_patient"
            )

            appointment_id = patient_options[selected_patient]

            patient = get_appointment_by_id(appointment_id)

            if patient:
                show_cancelled_appointment_readonly(appointment_id, "pre")

                st.success("Patient selected successfully")

                st.subheader("Patient Information")

                col1, col2 = st.columns(2)

                with col1:
                    st.text_input(
                        "HN",
                        value=patient["hn"],
                        disabled=True
                    )

                    st.text_input(
                        "Patient Name",
                        value=patient["patient_name"],
                        disabled=True
                    )

                with col2:
                    st.text_input(
                        "Appointment Date",
                        value=str(patient["appointment_date"]),
                        disabled=True
                    )

                    st.text_input(
                        "Indication",
                        value=patient["indication"],
                        disabled=True
                    )

                st.session_state["selected_appointment_id"] = appointment_id

                
                # Step 4.2.2: Clinical History
                review = get_pre_colposcopy_review(appointment_id) or {}

                def saved(field, default=""):
                    value = review.get(field)
                    return default if value is None else value

                st.divider()
                st.subheader("Step 2: Clinical History")
                
                if st.session_state.get("review_save_success") == appointment_id:
                    st.success("Clinical history saved successfully!")
                    del st.session_state["review_save_success"]


                with st.form(f"clinical_review_{appointment_id}"):

                    col1, col2 = st.columns(2)

                    with col1:
                        age = st.number_input(
                            "Age (years)",
                            min_value=0,
                            max_value=120,
                            value=int(saved("age", 0))
                        )

                        parity = st.text_input(
                            "Parity (G/P)",
                            value=saved("parity"),
                            placeholder="e.g. G2P1011"
                        )

                        lmp = st.text_input(
                            "Last Menstrual Period",
                            value=saved("lmp"),
                            placeholder="YYYY-MM-DD or Unknown"
                        )

                        first_intercourse_age = st.number_input(
                            "Age at First Intercourse",
                            min_value=0,
                            max_value=100,
                            value=int(saved("first_intercourse_age", 0))
                        )

                    with col2:
                        number_of_partners = st.number_input(
                            "Number of Sexual Partners",
                            min_value=0,
                            value=int(saved("number_of_partners", 0))
                        )

                        hiv_options = [
                            "Unknown",
                            "Negative",
                            "Positive",
                            "Not tested",
                            "Not documented",
                        ]

                        hiv_saved = saved("hiv_status", "Unknown")

                        hiv_status = st.selectbox(
                            "HIV Status",
                            hiv_options,
                            index=(
                                hiv_options.index(hiv_saved)
                                if hiv_saved in hiv_options else 0
                            )
                        )


                        history_of_stds = st.text_input(
                            "History of STDs",
                            value=saved("history_of_stds")
                        )

                        smoking_options = [
                            "Unknown", "Never", "Former", "Current"
                        ]
                        smoking_status = st.selectbox(
                            "Smoking Status",
                            smoking_options,
                            index=smoking_options.index(
                                saved("smoking_status", "Unknown")
                            ) if saved("smoking_status", "Unknown")
                            in smoking_options else 0
                        )

                    st.markdown("#### Menstrual and Gynecologic History")

                    menstrual_status = st.selectbox(
                        "Menstrual Status",
                        ["Unknown", "Premenopausal", "Postmenopausal"],
                        index=(
                            ["Unknown", "Premenopausal", "Postmenopausal"]
                            .index(saved("menstrual_status", "Unknown"))
                            if saved("menstrual_status", "Unknown")
                            in ["Unknown", "Premenopausal", "Postmenopausal"]
                            else 0
                        )
                    )

                    contraception = st.text_input(
                        "Contraception",
                        value=saved("contraception")
                    )

                    menopause_duration = st.text_input(
                        "Menopause Duration",
                        value=saved("menopause_duration")
                    )

                    hrt_history = st.text_input(
                        "HRT History",
                        value=saved("hrt_history")
                    )
                        
                    st.divider()
                    st.subheader("Cervical Screening History")
                    st.markdown("#### Pap Smear")

                    pap_options = [
                        "Not documented",
                        "NILM", "ASC-US", "ASC-H",
                        "LSIL", "HSIL", "AGC",
                        "AIS", "Squamous cell carcinoma",
                        "Adenocarcinoma", "Other"
                    ]

                    pap_saved = saved(
                        "pap_smear_result", "Not documented"
                    )

                    pap_smear_result = st.selectbox(
                        "Pap Smear Result",
                        pap_options,
                        index=(
                            pap_options.index(pap_saved)
                            if pap_saved in pap_options else 0
                        )
                    )

                    pap_smear_date = st.text_input(
                        "Pap Smear Date",
                        value=saved("pap_smear_date"),
                        placeholder="YYYY-MM-DD"
                    )

                    pap_smear_location = st.text_input(
                        "Pap Smear Location",
                        value=saved("pap_smear_location"),
                        placeholder="Hospital / Clinic"
                    )
                    
                    patho_number = st.text_input(
                        "Patho Number",
                        value=saved("patho_number"),
                        placeholder="e.g. TH2602573",
                        help="Pathology reference number from previous cervical screening"
                    )

                    st.markdown("#### HPV Testing")

                    hpv_options = [
                        "Not documented", "Positive",
                        "Negative", "Invalid"
                    ]

                    hpv_saved = saved(
                        "hpv_result", "Not documented"
                    )

                    hpv_result = st.selectbox(
                        "HPV Test Result",
                        hpv_options,
                        index=(
                            hpv_options.index(hpv_saved)
                            if hpv_saved in hpv_options else 0
                        )
                    )

                    hpv_genotype = st.text_input(
                        "HPV Genotype",
                        value=saved("hpv_genotype"),
                        placeholder="e.g. HPV 16, 18, Other HR-HPV"
                    )

                    st.markdown("#### HPV Vaccination")

                    vaccination_options = [
                        "Unknown", "No", "Yes"
                    ]

                    vaccination_saved = saved(
                        "hpv_vaccinated", "Unknown"
                    )

                    hpv_vaccinated = st.selectbox(
                        "HPV Vaccination Status",
                        vaccination_options,
                        index=(
                            vaccination_options.index(vaccination_saved)
                            if vaccination_saved in vaccination_options
                            else 0
                        )
                    )

                    hpv_vaccine_type = st.text_input(
                        "HPV Vaccine Type",
                        value=saved("hpv_vaccine_type"),
                        placeholder="e.g. Bivalent / Quadrivalent / 9-valent"
                    )

                    hpv_vaccine_completion_date = st.text_input(
                        "Vaccination Completion Date",
                        value=saved("hpv_vaccine_completion_date"),
                        placeholder="YYYY-MM-DD or Unknown"
                    )
                    st.divider()
                    st.subheader("Additional Clinical History")

                    previous_history = st.text_area(
                        "Clinical History / Additional Notes",
                        value=saved("previous_history"),
                        height=250,
                        placeholder=(
                            "Reason for referral:\n"
                            "Present illness:\n"
                            "Previous cervical screening / treatment:\n"
                            "Other relevant clinical history:"
                        )
                    )
                    reviewed_by = st.text_input(
    "Reviewed By",
    value=saved("reviewed_by")
)

                    review_date = st.date_input(
                        "Review Date",
                        value=date.today()
                    )

                    submitted = st.form_submit_button(
                        "Save Clinical History",
                        type="primary"
                    )

                    if submitted:
                        require_non_cancelled_appointment(appointment_id)
                        data = {
                            "age": age if age > 0 else None,
                            "parity": parity,
                            "lmp": lmp,
                            "first_intercourse_age": (
                                first_intercourse_age
                                if first_intercourse_age > 0 else None
                            ),
                            "number_of_partners": number_of_partners,
                            "hiv_status": hiv_status,
                            "history_of_stds": history_of_stds,
                            "smoking_status": smoking_status,
                            "menstrual_status": menstrual_status,
                            "contraception": contraception,
                            "menopause_duration": menopause_duration,
                            "hrt_history": hrt_history,
                            
                            "pap_smear_result": pap_smear_result,
                            "pap_smear_date": pap_smear_date,
                            "pap_smear_location": pap_smear_location,
                            "patho_number": patho_number,
                            "hpv_result": hpv_result,
                            "hpv_genotype": hpv_genotype,
                            "hpv_vaccinated": hpv_vaccinated,
                            "hpv_vaccine_type": hpv_vaccine_type,
                            "hpv_vaccine_completion_date": hpv_vaccine_completion_date,
                            "previous_history": previous_history,
                            "reviewed_by": reviewed_by,
                            "review_date": str(review_date)
                        }

                        save_pre_colposcopy_review(
                            appointment_id, data
                        )
                        
                        st.session_state["review_save_success"] = appointment_id
                        st.rerun()
            
            # Step 4.3.3.5 - Export Clinical History PDF
            st.divider()
            st.subheader("Export Clinical History")

            patient = get_appointment_by_id(appointment_id)
            review = get_pre_colposcopy_review(appointment_id)

            if patient and review:
                pdf_bytes = generate_clinical_history_pdf(
                    dict(patient),
                    dict(review)
                )

                st.download_button(
                    label="Download Clinical History PDF",
                    data=pdf_bytes,
                    file_name=f"Clinical_History_{patient['hn']}.pdf",
                    mime="application/pdf",
                    type="primary",
                    key=f"download_clinical_history_{appointment_id}"
                )
            else:
                st.info(
                    "Please save Clinical History before exporting PDF."
                )
                    

        else:
            st.warning("No matching appointments found.")

    else:
        st.info("Enter HN or patient name to search.")



elif menu == "Colposcopy Record":
    st.header("Colposcopy Record")

    st.subheader("Patient Selection")

    colposcopy_search = st.text_input(
        "Search by HN or Patient Name",
        key="colposcopy_search"
    )

    if colposcopy_search.strip():
        appointments = search_appointments(
            colposcopy_search.strip()
        )

        if appointments:
            appointment_options = {
                f"{a['hn']} | {a['patient_name']} | "
                f"{a['appointment_date']} | ID {a['id']}": a["id"]
                for a in appointments
            }

            selected_label = st.selectbox(
                "Select Appointment",
                list(appointment_options.keys()),
                key="colposcopy_selected_appointment"
            )

            appointment_id = appointment_options[selected_label]

            patient = get_appointment_by_id(appointment_id)

            if patient:
                show_cancelled_appointment_readonly(appointment_id, "colposcopy")

                st.success(
                    f"Selected: {patient['hn']} - "
                    f"{patient['patient_name']}"
                )

                st.write(
                    "Appointment Date:",
                    patient["appointment_date"]
                )

                existing_record = get_colposcopy_record(
                    appointment_id
                )

                if existing_record:
                    st.info(
                        "An existing Colposcopy Record was found."
                    )
                else:
                    st.info(
                        "No Colposcopy Record yet. "
                        "A new record can be created."
                    )
                
                # Step 5.2.4.4 - Colposcopic Findings
                st.divider()
                st.subheader("Colposcopic Findings")

                def colpo_saved(field, default=None):
                    if existing_record:
                        result = existing_record.get(field)
                        return result if result is not None else default
                    return default
                
                submitted_colposcopy = False
                
                with st.container():

                    # Colposcopy Date - use appointment date as default.
                    saved_colposcopy_date = colpo_saved("colposcopy_date")
                    try:
                        appointment_date_value = date.fromisoformat(
                            str(patient["appointment_date"])
                        )
                    except (ValueError, TypeError):
                        appointment_date_value = date.today()

                    try:
                        default_colposcopy_date = (
                            date.fromisoformat(str(saved_colposcopy_date))
                            if saved_colposcopy_date
                            else appointment_date_value
                        )
                    except (ValueError, TypeError):
                        default_colposcopy_date = appointment_date_value

                    colposcopy_date = st.date_input(
                        "Colposcopy Date",
                        value=default_colposcopy_date,
                        key=f"colpo_date_{appointment_id}",
                    )

                    satisfactory_options = {
                        "Not assessed": None,
                        "Unsatisfactory": 0,
                        "Satisfactory": 1,
                    }

                    satisfactory_labels = list(
                        satisfactory_options.keys()
                    )

                    satisfactory_saved = colpo_saved(
                        "colposcopy_satisfactory"
                    )

                    satisfactory_default = next(
                        (
                            label for label, code
                            in satisfactory_options.items()
                            if code == satisfactory_saved
                        ),
                        "Not assessed"
                    )

                    satisfactory = st.selectbox(
                        "Colposcopy Satisfactory",
                        satisfactory_labels,
                        index=satisfactory_labels.index(
                            satisfactory_default
                        )
                    )

                    tzone_options = {
                        "Not assessed": None,
                        "Type 1": 1,
                        "Type 2": 2,
                        "Type 3": 3,
                    }

                    tzone_labels = list(tzone_options.keys())

                    tzone_saved = colpo_saved("tzone")

                    tzone_default = next(
                        (
                            label for label, code
                            in tzone_options.items()
                            if code == tzone_saved
                        ),
                        "Not assessed"
                    )

                    tzone = st.selectbox(
                        "Transformation Zone Type",
                        tzone_labels,
                        index=tzone_labels.index(tzone_default)
                    )

                    awe_options = {
                        "Not assessed": None,
                        "No AWE": 0,
                        "Thin AWE": 1,
                        "Dense AWE": 2,
                        "Other": None,
                    }
                    awe_saved = colpo_saved("awe")
                    if colpo_saved("awe_other_selected", 0):
                        awe_default = "Other"
                    else:
                        awe_default = next(
                            (label for label, code in awe_options.items()
                             if label != "Other" and code == awe_saved),
                            "Not assessed",
                        )
                    awe = st.selectbox(
                        "Acetowhite Epithelium (AWE)",
                        list(awe_options.keys()),
                        index=list(awe_options.keys()).index(awe_default),
                        key=f"colpo_awe_{appointment_id}",
                    )
                    awe_clock_position = ""
                    awe_other_text = ""
                    if awe in ("Thin AWE", "Dense AWE"):
                        awe_clock_position = st.text_input(
                            "AWE Location / Clock Position",
                            value=colpo_saved("awe_clock_position", ""),
                            placeholder="e.g. 3-6 o'clock",
                            key=f"colpo_awe_clock_{appointment_id}",
                        )
                    elif awe == "Other":
                        awe_other_text = st.text_area(
                            "Specify Other AWE",
                            value=colpo_saved("awe_other_text", ""),
                            placeholder="Describe other acetowhite findings...",
                            key=f"colpo_awe_other_{appointment_id}",
                            height=80,
                        )

                    st.divider()
                    st.markdown("#### Additional Colposcopic Findings")
                    finding_fields = {
                        "leukoplakia": "Leukoplakia",
                        "condyloma": "Condyloma",
                        "exophytic": "Exophytic",
                        "ulcerative": "Ulcerative",
                        "punctation": "Punctation",
                        "mosaic": "Mosaic",
                        "suspicious": "Suspicious",
                    }
                    finding_values = {}
                    finding_details = {}
                    col1, col2 = st.columns(2)
                    for i, (field, label) in enumerate(finding_fields.items()):
                        saved_code = colpo_saved(field, 0)
                        default_label = "Yes" if saved_code == 1 else "No"
                        with (col1 if i % 2 == 0 else col2):
                            selected = st.selectbox(
                                label,
                                ["No", "Yes"],
                                index=["No", "Yes"].index(default_label),
                                key=f"colpo_{field}_{appointment_id}",
                            )
                            finding_values[field] = 1 if selected == "Yes" else 0
                            if selected == "Yes":
                                finding_details[field] = st.text_area(
                                    f"{label} - Description / Location",
                                    value=colpo_saved(f"{field}_detail", ""),
                                    placeholder="Describe finding and clock position...",
                                    height=80,
                                    key=f"colpo_{field}_detail_{appointment_id}",
                                )
                            else:
                                finding_details[field] = None

                    st.divider()
                    st.markdown("#### Colposcopic Description")
                    description_key = f"colpo_description_{appointment_id}"
                    generated_key = f"colpo_generated_summary_{appointment_id}"
                    pending_description_key = f"colpo_description_pending_{appointment_id}"

                    # Apply saved description before the text_area widget is created.
                    # Streamlit forbids writing to a widget key after instantiation.
                    if pending_description_key in st.session_state:
                        st.session_state[description_key] = st.session_state.pop(
                            pending_description_key
                        )

                    if description_key not in st.session_state:
                        st.session_state[description_key] = (
                            colpo_saved("colposcopy_description", "") or ""
                        )
                    if generated_key not in st.session_state:
                        stored_summary = (
                            colpo_saved("colposcopy_generated_summary", "") or ""
                        )
                        st.session_state[generated_key] = (
                            stored_summary
                            or infer_legacy_generated_summary(
                                st.session_state[description_key]
                            )
                        )

                    # Convert older saved descriptions to marker-free text.
                    clean_text, legacy_generated = (
                        clean_legacy_colposcopy_description(
                            st.session_state[description_key]
                        )
                    )
                    if legacy_generated:
                        st.session_state[description_key] = clean_text
                        if not st.session_state[generated_key]:
                            st.session_state[generated_key] = legacy_generated

                    generated_summary = build_colposcopy_summary(
                        satisfactory, tzone, awe, awe_clock_position,
                        awe_other_text, finding_fields, finding_values,
                        finding_details,
                    )

                    if st.button(
                        "Generate / Refresh Description from Findings",
                        key=f"colpo_generate_description_{appointment_id}",
                        help="Refresh generated findings without deleting manual notes.",
                    ):
                        st.session_state[description_key] = (
                            refresh_colposcopy_description(
                                st.session_state[description_key],
                                st.session_state[generated_key],
                                generated_summary,
                            )
                        )
                        st.session_state[generated_key] = generated_summary

                    colposcopy_description = st.text_area(
                        "Description / Additional Findings",
                        height=180,
                        placeholder="Generate from findings or enter a free-text description...",
                        key=description_key,
                    )

                    # Step 5.2.4.6 - Colposcopic Impression
                    st.divider()
                    st.markdown("#### Colposcopic Impression")

                    impression_options = {
                        "Not assessed": None,
                        "Normal": 0,
                        "Unsatisfactory": 1,
                        "Low grade": 2,
                        "High grade": 3,
                        "Invasive": 4,
                    }

                    saved_impression = colpo_saved(
                        "colposcopy_ci"
                    )

                    impression_default = next(
                        (
                            label
                            for label, code in impression_options.items()
                            if code == saved_impression
                        ),
                        "Not assessed"
                    )

                    impression = st.selectbox(
                        "Colposcopic Impression",
                        list(impression_options.keys()),
                        index=list(impression_options.keys()).index(
                            impression_default
                        ),
                        key=f"colpo_impression_{appointment_id}"
                    )

                    
                    # Step 5.2.4.7 - VIA and Procedure
                    st.divider()
                    st.markdown("#### VIA and Procedure")

                    via_options = [
                        "Not done",
                        "Negative",
                        "Positive",
                    ]

                    saved_via = colpo_saved(
                        "via_result", "Not done"
                    )

                    via_result = st.selectbox(
                        "VIA Result",
                        via_options,
                        index=(
                            via_options.index(saved_via)
                            if saved_via in via_options else 0
                        )
                    )

                    
                    procedure_options = [
                        "CDB",
                        "ECB",
                        "LEEP with ECC",
                        "F&C",
                        "Others",
                    ]

                    saved_procedure = colpo_saved(
                        "procedure_type", ""
                    )

                    saved_procedures = [
                        item.strip()
                        for item in saved_procedure.split(";")
                        if item.strip() in procedure_options
                    ]

                    selected_procedures = st.multiselect(
                        "Procedure",
                        procedure_options,
                        default=saved_procedures,
                        help=(
                            "Select all procedures performed. "
                            "Leave empty if no procedure was done."
                        )
                    )

                    procedure_type = (
                        "; ".join(selected_procedures)
                        if selected_procedures
                        else "None"
                    )

                    

                    biopsy_site = st.text_input(
                        "Biopsy Site / Clock Position",
                        value=colpo_saved("biopsy_site", ""),
                        placeholder="e.g. 12 o'clock"
                    )

                    procedure_notes = st.text_area(
                        "Procedure Notes / Additional Details",
                        value=colpo_saved("procedure_notes", ""),
                        height=100
                    )

                    procedure_performed = st.checkbox(
                        "Confirm Colposcopy Performed",
                        value=bool(saved_colposcopy_date),
                        help=(
                            "Check only when colposcopy has "
                            "actually been performed."
                        ),
                        key=f"colpo_performed_{appointment_id}"
                    )

                    performed_by = st.text_input(
                        "Performed By",
                        value=colpo_saved("performed_by", "")
                    )

                    # Step 5.2.5.2 - Cervical Diagram
                    st.divider()
                    st.markdown("#### Cervical Diagram")

                    existing_diagram_path = colpo_saved(
                        "cervical_diagram_path"
                    )

                    if existing_diagram_path:
                        diagram_file = Path(existing_diagram_path)
                        if diagram_file.is_file():
                            st.image(
                                str(diagram_file),
                                caption="Saved Cervical Diagram",
                                width=350
                            )

                    uploaded_diagram = st.file_uploader(
                        "Upload Cervical Diagram (JPG / PNG)",
                        type=["jpg", "jpeg", "png"],
                        key=f"cervical_diagram_{appointment_id}",
                        help="Maximum file size: 10 MB"
                    )

                    if uploaded_diagram is not None:
                        st.image(
                            uploaded_diagram,
                            caption="New Cervical Diagram Preview",
                            width=350
                        )

                    
                    remove_diagram = st.checkbox(
                        "Remove saved Cervical Diagram",
                        value=False,
                        disabled=not bool(existing_diagram_path),
                        help="Remove the saved diagram when clicking Save."
                    )

                    
                    st.markdown("#### Remark")

                    colposcopy_remark = st.text_area(
                        "Additional Remark",
                        value=colpo_saved(
                            "colposcopy_remark",
                            default=""
                        ),
                        height=90,
                        key=f"colposcopy_remark_{appointment_id}"
                    )

                    submitted_colposcopy = st.button(
                        "Save Colposcopic Findings",
                        type="primary"
                    )


                    
                    
                if submitted_colposcopy:
                    require_non_cancelled_appointment(appointment_id)
                    # Rebuild description from the actual current UI selections.
                    # This also removes outdated generated findings when changed
                    # after the user last clicked Generate / Refresh.
                    updated_description = refresh_colposcopy_description(
                        st.session_state.get(description_key, ""),
                        st.session_state.get(generated_key, ""),
                        generated_summary,
                    )
                    record_data = {
                        field: colpo_saved(field)
                        for field in COLPOSCOPY_FIELDS
                    }

                    
                    record_data.update({
                        "colposcopy_satisfactory":
                            satisfactory_options[satisfactory],
                        "tzone": tzone_options[tzone],
                        "awe": awe_options[awe],
                        "awe_clock_position": (
                            awe_clock_position.strip()
                            if awe in ("Thin AWE", "Dense AWE") else None
                        ),
                        "awe_other_selected": 1 if awe == "Other" else 0,
                        "awe_other_text": (
                            awe_other_text.strip() if awe == "Other" else None
                        ),
                        "colposcopy_ci":
                            impression_options[impression],
                    })

                    record_data.update(finding_values)
                    record_data.update({
                        f"{field}_detail": finding_details[field]
                        for field in finding_fields
                    })

                    
                    record_data.update({
                        "via_result": via_result,
                        "procedure_type": procedure_type,
                        "biopsy_site": biopsy_site,
                        "procedure_notes": procedure_notes,
                        "colposcopy_description": updated_description,
                        "colposcopy_generated_summary": generated_summary,
                        "colposcopy_date": (
                            str(colposcopy_date)
                            if procedure_performed
                            else None
                        ),
                        "performed_by": performed_by,
                        "colposcopy_remark": colposcopy_remark,
                    })

                 # Preserve the previously saved diagram
                    record_data["cervical_diagram_path"] = (
                        existing_diagram_path
                    )
                    if remove_diagram:
                        record_data["cervical_diagram_path"] = None

                    if uploaded_diagram is not None and not remove_diagram:
                        raw_image = uploaded_diagram.getvalue()

                        if len(raw_image) > 10 * 1024 * 1024:
                            st.error(
                                "Image must be 10 MB or smaller."
                            )
                            st.stop()

                        try:
                            with Image.open(BytesIO(raw_image)) as img:
                                if img.format not in ("PNG", "JPEG"):
                                    raise ValueError(
                                        "Unsupported image format"
                                    )

                                img.load()

                                # Re-encode to remove unnecessary metadata
                                clean_image = img.convert("RGB")

                        except (
                            UnidentifiedImageError,
                            ValueError,
                            OSError
                        ):
                            st.error("Invalid image file.")
                            st.stop()

                        diagram_dir = (
                            Path("uploads")
                            / "cervical_diagrams"
                            / f"appointment_{appointment_id}"
                        )
                        diagram_dir.mkdir(
                            parents=True,
                            exist_ok=True
                        )

                        diagram_path = (
                            diagram_dir
                            / f"{uuid4().hex}.png"
                        )

                        clean_image.save(
                            diagram_path,
                            format="PNG"
                        )

                        record_data["cervical_diagram_path"] = (
                            str(diagram_path)
                        )

                    save_colposcopy_record(
                        appointment_id,
                        record_data
                    )

                    # Defer updating the text_area widget key until the next run.
                    st.session_state[pending_description_key] = updated_description
                    st.session_state[generated_key] = generated_summary
                    st.toast("Colposcopic Findings saved successfully!", icon="✅")
                    st.rerun()

                
                # Step 4 — Direct LEEP planning; separate from performed procedures.
                st.divider()
                st.subheader("Direct LEEP Management")
                st.caption(
                    "ส่งผู้ป่วยเข้า LEEP Queue โดยตรง เช่น Diagnostic LEEP หรือ "
                    "Expedited Treatment โดยไม่จำเป็นต้องมี CDB ก่อนทำ LEEP. "
                    "หลังทำ LEEP ยังต้อง Review ผล Pathology ตามปกติ"
                )
                st.caption(
                    "The Procedure field above records procedures already performed. "
                    "Use this section to plan a future LEEP."
                )
                saved_for_direct = get_colposcopy_record(appointment_id) or {}
                if not saved_for_direct.get("colposcopy_date"):
                    st.info("Save the Colposcopy Record before adding a LEEP Queue entry.")
                else:
                    direct_plans = get_pathology_management_plans(appointment_id)
                    direct_queue = {
                        row["management_code"]: row
                        for row in get_leep_queue_for_appointment(appointment_id)
                    }
                    direct_labels = {"LEEP_ECC": "LEEP + ECC", "LEEP": "LEEP"}
                    selected_direct = st.selectbox(
                        "Planned Procedure",
                        options=list(direct_labels),
                        format_func=lambda code: direct_labels[code],
                        key=f"direct_leep_code_{appointment_id}",
                    )
                    prior_queue = direct_queue.get(selected_direct)
                    prior_plan = direct_plans.get(selected_direct, {})
                    if prior_queue:
                        st.info(
                            f"Existing LEEP Queue ID {prior_queue['id']} — "
                            f"Status: {prior_queue['status']}. "
                            "The same Queue ID will be retained."
                        )
                    saved_note = (prior_queue or {}).get("queue_note") or ""
                    prior_reason = ""
                    for line in saved_note.splitlines():
                        if line.startswith(DIRECT_LEEP_NOTE_PREFIX):
                            detail = line[len(DIRECT_LEEP_NOTE_PREFIX):]
                            prior_reason = detail.split(" — ", 1)[-1]
                            break
                        if line.startswith(LEGACY_EXPEDITED_NOTE_PREFIX):
                            prior_reason = line[len(LEGACY_EXPEDITED_NOTE_PREFIX):]
                            break
                    saved_indication = (prior_queue or {}).get("direct_leep_indication")
                    indication_options = list(DIRECT_LEEP_INDICATIONS)
                    # Old Step 3 rows have no indication category: require review
                    # rather than assuming all are expedited treatment.
                    if saved_indication not in indication_options:
                        indication_options = ["UNSPECIFIED", *indication_options]
                    indication_labels = {
                        "UNSPECIFIED": "Select indication (legacy queue not categorized)",
                        **DIRECT_LEEP_INDICATIONS,
                    }
                    saved_date = (
                        (prior_queue or {}).get("planned_date")
                        or prior_plan.get("planned_date")
                    )
                    with st.form(f"direct_leep_form_{appointment_id}"):
                        direct_indication = st.selectbox(
                            "Indication for LEEP",
                            options=indication_options,
                            index=(indication_options.index(saved_indication)
                                   if saved_indication in indication_options else 0),
                            format_func=lambda code: indication_labels[code],
                        )
                        direct_date = st.date_input(
                            "Planned LEEP Date (optional — blank means Pending)",
                            value=date.fromisoformat(saved_date) if saved_date else None,
                        )
                        direct_reason = st.text_area(
                            "Clinical Reason / Additional Details (required)",
                            value=prior_reason,
                            height=90,
                            placeholder="e.g. HSIL cytology, diagnostic excision, discordant findings",
                        )
                        direct_confirm = st.checkbox(
                            "Confirm sending this patient to LEEP Queue"
                        )
                        direct_submit = st.form_submit_button(
                            "Save to LEEP Queue",
                            type="primary",
                            disabled=bool(
                                prior_queue and (
                                    prior_queue["status"] in ("Completed", "Cancelled")
                                    or prior_queue.get("creation_source") not in
                                    ("EXPEDITED_COLPOSCOPY", "DIRECT_COLPOSCOPY")
                                )
                            ),
                        )
                    if direct_submit:
                        require_non_cancelled_appointment(appointment_id)
                        if not direct_confirm:
                            st.error("Confirm sending this patient to LEEP Queue first.")
                        elif direct_indication not in DIRECT_LEEP_INDICATIONS:
                            st.error("Select an indication for LEEP first.")
                        else:
                            try:
                                new_queue_id = create_direct_leep_queue(
                                    appointment_id,
                                    management_code=selected_direct,
                                    indication_code=direct_indication,
                                    clinical_reason=direct_reason,
                                    planned_date=str(direct_date) if direct_date else None,
                                )
                                st.session_state["direct_leep_success"] = (
                                    appointment_id, new_queue_id
                                )
                                st.rerun()
                            except ValueError as error:
                                st.error(str(error))
                    if st.session_state.get("direct_leep_success", (None,))[0] == appointment_id:
                        _, created_queue_id = st.session_state.pop("direct_leep_success")
                        st.success(
                            f"Direct LEEP saved to Queue ID {created_queue_id}. "
                            "Open LEEP Queue to prepare the Day Note."
                        )

                # Step 6.7C.5 - Stable Specimen Row Identity

                def make_specimen_row(specimen=None):
                    """Create a UI row with a stable identity."""
                    specimen = specimen or {}

                    specimen_id = specimen.get("id")

                    return {
                        "row_key": (
                            f"saved_{specimen_id}"
                            if specimen_id is not None
                            else f"new_{uuid4().hex}"
                        ),
                        "id": specimen_id,
                        "specimen_label": (
                            specimen.get("specimen_label") or ""
                        ),
                        "specimen_type": (
                            specimen.get("specimen_type") or "CDB"
                        ),
                        "biopsy_site": (
                            specimen.get("biopsy_site") or ""
                        ),
                        "specimen_remark": (
                            specimen.get("specimen_remark") or ""
                        ),
                        "collection_date": (
                            specimen.get("collection_date")
                            if specimen else None
                        ),
                    }
                
                def sync_specimen_draft(appointment_id, rows):
                    """Preserve submitted specimen form values."""

                    for row in rows:
                        prefix = (
                            f"{appointment_id}_{row['row_key']}"
                        )

                        field_keys = {
                            "specimen_label": f"spec_label_{prefix}",
                            "specimen_type": f"spec_type_{prefix}",
                            "biopsy_site": f"spec_site_{prefix}",
                            "specimen_remark": f"spec_remark_{prefix}",
                        }

                        for field, widget_key in field_keys.items():
                            if widget_key in st.session_state:
                                row[field] = (
                                    st.session_state[widget_key]
                                )

                        # Preserve collection status and date
                        collected_key = f"spec_collected_{prefix}"
                        date_key = f"spec_date_{prefix}"

                        if collected_key in st.session_state:
                            collected = bool(
                                st.session_state[collected_key]
                            )

                            row["collection_date"] = (
                                str(st.session_state[date_key])
                                if collected
                                and date_key in st.session_state
                                else None
                            )

                # Step 6.7C - Specimen Collection
                st.divider()
                st.subheader("Specimen Collection")

                saved_colpo_specimens = get_colposcopy_specimens(
                    appointment_id
                )

                
                
                # Stable specimen rows for this appointment
                specimen_rows_key = (
                    f"colpo_specimen_rows_{appointment_id}"
                )

                # Initialize rows from database once per appointment
                if specimen_rows_key not in st.session_state:
                    st.session_state[specimen_rows_key] = [
                        make_specimen_row(specimen)
                        for specimen in saved_colpo_specimens
                    ]

                specimen_rows = st.session_state[
                    specimen_rows_key
                ]

                st.caption(
                    f"Specimens: {len(specimen_rows)}"
                )



                specimen_types = [
                    "CDB",
                    "ECB",
                    "ECC",
                    "LEEP",
                    "CKC",
                    "F/C",
                    "Other",
                ]
                
                # Refresh widget state before form creation
                refresh_key = (
                    f"colpo_specimen_refresh_{appointment_id}"
                )

                if st.session_state.pop(refresh_key, False):

                    for specimen_row in specimen_rows:
                        row_key = specimen_row["row_key"]

                        prefix = (
                            f"{appointment_id}_{row_key}"
                        )

                        for field in [
                            "label",
                            "type",
                            "site",
                            "remark",
                            "collected",
                            "date",
                        ]:
                            widget_key = (
                                f"spec_{field}_{prefix}"
                            )

                            st.session_state.pop(
                                widget_key,
                                None
                            )

                
                                # Remove selection - outside Streamlit form
                specimen_options = {
                    (
                        f"{i + 1}. "
                        f"{row['specimen_label'] or row['specimen_type']}"
                    ): row["row_key"]
                    for i, row in enumerate(specimen_rows)
                }

                linked_pathology_specimens = get_pathology_specimens(
                    appointment_id
                )

                protected_specimen_ids = {
                    result["colposcopy_specimen_id"]
                    for result in linked_pathology_specimens
                    if result.get("colposcopy_specimen_id") is not None
                }

                selected_remove = st.selectbox(
                    "Select Specimen to Remove",
                    options=list(specimen_options.keys()),
                    key=f"spec_remove_select_{appointment_id}",
                    disabled=not specimen_rows
                )

                selected_remove_key = specimen_options.get(
                    selected_remove
                )

                selected_remove_row = next(
                    (
                        row for row in specimen_rows
                        if row["row_key"] == selected_remove_key
                    ),
                    None
                )

                remove_is_protected = (
                    selected_remove_row is not None
                    and selected_remove_row.get("id")
                    in protected_specimen_ids
                )

                if remove_is_protected:
                    st.caption(
                        "This specimen has a linked Pathology "
                        "Record and cannot be removed."
                    )

            

                
                specimen_data = []

                with st.container():
                    
                    
                    for i, specimen_row in enumerate(
                        specimen_rows
                    ):
                        row_key = specimen_row["row_key"]
                        widget_prefix = (
                            f"{appointment_id}_{row_key}"
                        )

                        st.markdown(
                            f"#### Specimen {i + 1}"
                        )

                        # Initialize widget values only once
                        widget_defaults = {
                            f"spec_label_{widget_prefix}":
                                specimen_row["specimen_label"],
                            f"spec_type_{widget_prefix}":
                                specimen_row["specimen_type"],
                            f"spec_site_{widget_prefix}":
                                specimen_row["biopsy_site"],
                            f"spec_remark_{widget_prefix}":
                                specimen_row["specimen_remark"],
                            f"spec_collected_{widget_prefix}":
                                 bool(specimen_row.get("collection_date")),
                            f"spec_date_{widget_prefix}":
                                (
                                    date.fromisoformat(str(specimen_row["collection_date"]))
                                    if specimen_row.get("collection_date")
                                    else colposcopy_date
                                ),
                        }

                        
                        for key, default_value in widget_defaults.items():
                            if key not in st.session_state:
                                st.session_state[key] = default_value


                        specimen_label = st.text_input(
                            "Specimen Label",
                            key=f"spec_label_{widget_prefix}"
                        )

                        specimen_type = st.selectbox(
                            "Specimen Type",
                            specimen_types,
                            key=f"spec_type_{widget_prefix}"
                        )

                        biopsy_site_value = st.text_input(
                            "Biopsy Site / Clock Position",
                            placeholder="e.g. 3 o'clock",
                            key=f"spec_site_{widget_prefix}"
                        )

                        specimen_remark = st.text_area(
                            "Specimen Remark",
                            key=f"spec_remark_{widget_prefix}"
                        )
                        specimen_collected = st.checkbox(
                            "Collected",
                            key=f"spec_collected_{widget_prefix}",
                            help="Check only when this specimen has actually been collected."
                        )

                        specimen_collection_date = st.date_input(
                            "Collection Date",
                            key=f"spec_date_{widget_prefix}"
                        )
                        specimen_data.append({
                            "id": specimen_row["id"],
                            "specimen_label": specimen_label,
                            "specimen_type": specimen_type,
                            "biopsy_site": biopsy_site_value,
                            "collection_date": (
                                str(specimen_collection_date)
                                if specimen_collected
                                else None
                            ),
                            "specimen_remark": specimen_remark,
                        })

                    
                    st.divider()



                    add_col, remove_col, save_col = st.columns(3)

                    with add_col:
                        add_specimen_clicked = st.button(
                            "Add Specimen"
                        )

                    with remove_col:
                        remove_specimen_clicked = st.button(
                            "Remove Specimen",
                            disabled=(
                                not specimen_rows
                                or remove_is_protected
                            )
                        )

                    with save_col:
                        save_specimens_clicked = st.button(
                            "Save Specimens",
                            type="primary"
                        )



                
                # Handle Add / Remove submissions
                if add_specimen_clicked or remove_specimen_clicked:

                    sync_specimen_draft(
                        appointment_id,
                        specimen_rows
                    )

                    if add_specimen_clicked:
                        specimen_rows.append(
                            make_specimen_row()
                        )
                        st.rerun()

                    if remove_specimen_clicked:
                        selected_row_key = specimen_options[
                            selected_remove
                        ]

                        st.session_state[
                            f"spec_remove_pending_{appointment_id}"
                        ] = selected_row_key

                        st.rerun()
                
            
                if save_specimens_clicked:
                    require_non_cancelled_appointment(appointment_id)
                    try:
                        # Validate specimen collection dates
                        collected_specimens = [
                            specimen
                            for specimen in specimen_data
                            if specimen.get("collection_date")
                        ]

                        if collected_specimens:
                            saved_colpo_record = get_colposcopy_record(
                                appointment_id
                            )

                            confirmed_colposcopy_date = (
                                saved_colpo_record["colposcopy_date"]
                                if saved_colpo_record
                                else None
                            )

                            if not confirmed_colposcopy_date:
                                raise ValueError(
                                    "Colposcopy has not been confirmed "
                                    "as performed. Please confirm and "
                                    "save the actual Colposcopy Date "
                                    "before recording collected specimens."
                                )

                        save_colposcopy_specimens(
                            appointment_id,
                            specimen_data
                        )

                        saved_after_save = get_colposcopy_specimens(
                            appointment_id
                        )

                        st.session_state[specimen_rows_key] = [
                            make_specimen_row(specimen)
                            for specimen in saved_after_save
                        ]

                        st.session_state[
                            f"colpo_specimen_refresh_{appointment_id}"
                        ] = True

                        st.toast(
                            "Specimens saved successfully.",
                            icon="✅"
                        )

                        st.rerun()

                    except ValueError as error:
                        st.error(str(error))



                
                pending_remove_key = (
                    f"spec_remove_pending_{appointment_id}"
                )

                pending_remove = st.session_state.get(
                    pending_remove_key
                )

                if pending_remove:
                    pending_row = next(
                        (
                            row for row in specimen_rows
                            if row["row_key"] == pending_remove
                        ),
                        None
                    )

                    pending_is_protected = (
                        pending_row is not None
                        and pending_row.get("id")
                        in protected_specimen_ids
                    )

                    if pending_row is None or pending_is_protected:
                        st.warning(
                            "Pending removal is no longer valid "
                            "or this specimen has a linked "
                            "Pathology Record."
                        )

                        if st.button(
                            "Clear Pending Remove",
                            key=f"spec_clear_pending_{appointment_id}"
                        ):
                            st.session_state[pending_remove_key] = None
                            st.rerun()

                    else:
                        pending_label = (
                            pending_row.get("specimen_label")
                            or pending_row.get("specimen_type")
                            or "Unnamed"
                        )

                        pending_id = pending_row.get("id")

                        pending_description = (
                            f"{pending_label} (ID {pending_id})"
                            if pending_id is not None
                            else f"{pending_label} (Unsaved)"
                        )

                        st.warning(
                            "Are you sure you want to remove "
                            f"Specimen {pending_description}?"
                        )

                        confirm_col, cancel_col = st.columns(2)

                        with confirm_col:
                            if st.button(
                                "Confirm Remove",
                                key=f"spec_confirm_{appointment_id}"
                            ):
                                st.session_state[specimen_rows_key] = [
                                    row for row in specimen_rows
                                    if row["row_key"] != pending_remove
                                ]

                                st.session_state[pending_remove_key] = None
                                st.rerun()

                        with cancel_col:
                            if st.button(
                                "Cancel",
                                key=f"spec_cancel_{appointment_id}"
                            ):
                                st.session_state[pending_remove_key] = None
                                st.rerun()

                # Download Colposcopy Record PDF (without Pathology Review)
                st.divider()
                st.markdown("#### Colposcopy Record PDF")

                pdf_patient = get_appointment_by_id(
                    appointment_id
                )

                pdf_review = get_pre_colposcopy_review(
                    appointment_id
                )

                pdf_record = get_colposcopy_record(
                    appointment_id
                )

                
                if pdf_patient and pdf_record:
                    try:

                        full_pdf_bytes = generate_full_colposcopy_pdf(
                            pdf_patient,
                            pdf_review or {},
                            pdf_record,
                            specimens=get_colposcopy_specimens(appointment_id),

                        )



                        st.download_button(
                            label="Download Colposcopy Record PDF",
                            data=full_pdf_bytes,
                            file_name=(
                                f"Colposcopy_Record_{appointment_id}.pdf"
                            ),
                            mime="application/pdf",
                            key=f"full_colposcopy_pdf_{appointment_id}"
                        )

                    except Exception as e:
                        st.error(
                            f"PDF generation failed: {e}"
                        )
                else:
                    st.info(
                        "Save Colposcopic Findings before "
                        "downloading the PDF."
                    )

                


        else:
            st.warning("No matching appointments found.")

    else:
        st.info("Enter HN or patient name to search.")


elif menu == "Pathology Worklist":
    st.header("Pathology Worklist")

    st.caption(
        "Track collected specimens and histopathology reporting."
    )

    # Filters
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        worklist_date = st.date_input(
            "Colposcopy Date",
            value=None,
            key="pathology_worklist_date",
            help="Leave blank to show all dates."
        )

    with filter_col2:
        worklist_status = st.selectbox(
            "Reporting Status",
            [
                "All",
                "Pending",
                "Partial",
                "Full reported",
            ],
            key="pathology_worklist_status"
        )

    with filter_col3:
        worklist_search = st.text_input(
            "Search HN / Patient Name",
            key="pathology_worklist_search"
        )

    # Retrieve worklist
    worklist_rows = get_pathology_worklist(
        colposcopy_date=worklist_date,
        search_text=worklist_search,
        status=worklist_status,
    )

    st.divider()

    # Summary
    total_patients = len(worklist_rows)

    pending_count = sum(
        row["pathology_status"] == "Pending"
        for row in worklist_rows
    )

    partial_count = sum(
        row["pathology_status"] == "Partial"
        for row in worklist_rows
    )

    full_count = sum(
        row["pathology_status"] == "Full reported"
        for row in worklist_rows
    )

    metric_cols = st.columns(4)

    metric_cols[0].metric(
        "Patients",
        total_patients
    )

    metric_cols[1].metric(
        "Pending",
        pending_count
    )

    metric_cols[2].metric(
        "Partial",
        partial_count
    )

    metric_cols[3].metric(
        "Full reported",
        full_count
    )

    st.divider()

    if not worklist_rows:
        st.info(
            "No patients with collected specimens "
            "match the selected filters."
        )

    else:
        display_rows = []

        for row in worklist_rows:
            display_rows.append({
                "HN": row["hn"],
                "Patient Name": row["patient_name"],
                "Appointment Date": row["appointment_date"] or "",
                "Colposcopy Date": (
                    row["colposcopy_date"] or ""
                ),
                "Specimens": row["specimen_list"],
                "Reported": (
                    f"{row['reported_specimens']}/"
                    f"{row['total_specimens']}"
                ),
                "Status": row["pathology_status"],
            })

        st.dataframe(
            display_rows,
            use_container_width=True,
            hide_index=True
        )

        st.caption(
            "Pending = no pathology results; "
            "Partial = some specimens reported; "
            "Full reported = all specimens reported."
        )


elif menu == "Pathology Review":
    st.title("Pathology Review")
    st.caption("CMU Colposcopy Registry")

    st.markdown("### Patient Selection")

    pathology_search = st.text_input(
        "Search by HN or Patient Name",
        key="pathology_search"
    )

    if pathology_search.strip():
        pathology_matches = search_appointments(
            pathology_search
        )

        if pathology_matches:
            # Step 6.7D.3.6.5.4 — Stable appointment selection.
            # Repeat appointments have separate clinical/pathology records.
            # Keep the selected appointment ID, not its changing list index.
            pathology_by_id = {p["id"]: p for p in pathology_matches}
            pathology_ids = list(pathology_by_id)
            original_ids = set()
            repeat_to_original = {}
            original_to_repeat = {}
            for candidate_id in pathology_ids:
                linked = get_repeat_colposcopy_appointment(candidate_id)
                if linked:
                    original_ids.add(candidate_id)
                    repeat_to_original[linked["id"]] = candidate_id
                    original_to_repeat[candidate_id] = linked["id"]

            def pathology_appointment_label(appointment_id):
                appointment = pathology_by_id[appointment_id]
                if appointment_id in repeat_to_original:
                    role = (
                        "Repeat Colposcopy (from ID "
                        f"{repeat_to_original[appointment_id]})"
                    )
                elif appointment_id in original_ids:
                    role = "Original Appointment"
                else:
                    role = "Appointment"
                return (
                    f"{role} | ID {appointment_id} | "
                    f"{appointment['appointment_date']} | "
                    f"{appointment['hn']} | {appointment['patient_name']}"
                )

            widget_key = "pathology_selected_appointment_id_v2"
            remembered_key = "pathology_remembered_appointment_id"
            requested_id = st.session_state.pop(
                "pathology_requested_appointment_id", None
            )
            if requested_id in pathology_by_id:
                st.session_state[widget_key] = requested_id
            elif (
                widget_key in st.session_state
                and st.session_state[widget_key] not in pathology_by_id
            ):
                # The search may now refer to another patient.
                del st.session_state[widget_key]

            if widget_key not in st.session_state:
                remembered_id = st.session_state.get(remembered_key)
                if remembered_id in pathology_by_id:
                    initial_id = remembered_id
                else:
                    # Default to an original appointment, not the newest
                    # automatically generated repeat appointment.
                    initial_id = next(
                        (i for i in pathology_ids if i in original_ids),
                        pathology_ids[0],
                    )
                st.session_state[widget_key] = initial_id

            pathology_appointment_id = st.selectbox(
                "Select Appointment",
                options=pathology_ids,
                format_func=pathology_appointment_label,
                key=widget_key,
            )
            st.session_state[remembered_key] = pathology_appointment_id

            if pathology_appointment_id in repeat_to_original:
                source_id = repeat_to_original[pathology_appointment_id]
                st.info(
                    "This is a NEW Repeat Colposcopy appointment with "
                    "its own records. Previous pathology is saved under "
                    f"Original Appointment ID {source_id}."
                )
                if st.button(
                    f"Open Original Appointment (ID {source_id})",
                    key="pathology_open_original_appointment",
                ):
                    # Set a request for the next rerun; do not mutate an
                    # already instantiated Streamlit selectbox widget.
                    st.session_state[
                        "pathology_requested_appointment_id"
                    ] = source_id
                    st.rerun()
            elif pathology_appointment_id in original_to_repeat:
                repeat_id = original_to_repeat[pathology_appointment_id]
                st.caption(
                    f"Original Appointment ID {pathology_appointment_id} "
                    f"— linked Repeat Colposcopy Appointment ID {repeat_id}"
                )
                if repeat_id in pathology_by_id and st.button(
                    f"Open Repeat Colposcopy (ID {repeat_id})",
                    key="pathology_open_repeat_appointment",
                ):
                    st.session_state[
                        "pathology_requested_appointment_id"
                    ] = repeat_id
                    st.rerun()

            pathology_patient = get_appointment_by_id(
                pathology_appointment_id
            )
            show_cancelled_appointment_readonly(
                pathology_appointment_id, "pathology"
            )

            pathology_clinical = (
                get_pre_colposcopy_review(
                    pathology_appointment_id
                ) or {}
            )

            pathology_colposcopy = (
                get_colposcopy_record(
                    pathology_appointment_id
                ) or {}
            )

            pathology_saved = (
                get_pathology_review(
                    pathology_appointment_id
                ) or {}
            )

            # Load specimens actually collected during colposcopy
            pathology_source_specimens = [
                specimen
                for specimen in get_colposcopy_specimens(
                    pathology_appointment_id
                )
                if specimen.get("collection_date")
            ]

            st.caption(
                f"Collected specimens available for pathology: "
                f"{len(pathology_source_specimens)}"
            )



                        # Load previously saved pathology results
            saved_pathology_specimens = get_pathology_specimens(
                pathology_appointment_id
            )

            # Match results to stable Colposcopy Specimen IDs
            pathology_results_by_source = {
                specimen["colposcopy_specimen_id"]: specimen
                for specimen in saved_pathology_specimens
                if specimen.get("colposcopy_specimen_id") is not None
            }

            st.markdown("### Patient Information")

            st.write(
                "**HN:**",
                pathology_patient.get("hn", "-")
            )

            st.write(
                "**Name:**",
                pathology_patient.get("patient_name", "-")
            )

            st.write(
                "**Age:**",
                pathology_clinical.get("age", "-")
            )

            st.write(
                "**HIV Status:**",
                pathology_clinical.get("hiv_status", "-")
            )

            st.markdown("### Previous Clinical Results")

            st.write(
                "**Pap Smear:**",
                pathology_clinical.get(
                    "pap_smear_result", "-"
                )
            )

            st.write(
                "**Colposcopic Impression:**",
                {
                    0: "Normal",
                    1: "Unsatisfactory",
                    2: "Low grade",
                    3: "High grade",
                    4: "Invasive"
                }.get(
                    pathology_colposcopy.get("colposcopy_ci"),
                    "Not assessed"
                )
            )

            st.markdown("### Pathology Review")
            
            # Step 6.6 - Pathology Review Form
            from datetime import date

            with st.form("pathology_review_form"):

                st.markdown("#### Review Information")

                saved_review_date = pathology_saved.get("review_date")

                review_date = st.date_input(
                    "Review Date",
                    value=(
                        date.fromisoformat(saved_review_date)
                        if saved_review_date
                        else date.today()
                    )
                )

                # Non-blocking date check: show a warning, never change saved data.
                # This uses the performed Colposcopy Date, not the appointment date.
                recorded_colposcopy_date = pathology_colposcopy.get(
                    "colposcopy_date"
                )
                if recorded_colposcopy_date:
                    try:
                        performed_colposcopy_date = date.fromisoformat(
                            str(recorded_colposcopy_date)[:10]
                        )
                    except (TypeError, ValueError):
                        performed_colposcopy_date = None
                    if (
                        performed_colposcopy_date is not None
                        and review_date < performed_colposcopy_date
                    ):
                        st.warning(
                            f"Review Date ({review_date.isoformat()}) is earlier "
                            f"than Colposcopy Date "
                            f"({performed_colposcopy_date.isoformat()}). "
                            "Please verify the dates. Saving remains allowed."
                        )

                reviewed_by = st.text_input(
                    "Reviewed By",
                    value=pathology_saved.get("reviewed_by") or ""
                )

                review_note = st.text_area(
                    "Review Note",
                    value=pathology_saved.get("review_note") or ""
                )

                st.markdown("#### Cytology")

                cytology_options = [
                    "Not assessed",
                    "ASC-US",
                    "ASC-H",
                    "LSIL",
                    "HSIL",
                    "SCCA",
                    "Adenocarcinoma",
                    "AGC-NOS",
                    "AGC-FN",
                    "AIS",
                    "Other"
                ]

                saved_cytology = pathology_saved.get(
                    "cytology_result"
                )

                cytology_result = st.selectbox(
                    "Cytology Result",
                    cytology_options,
                    index=(
                        cytology_options.index(saved_cytology)
                        if saved_cytology in cytology_options
                        else 0
                    )
                )

                st.markdown("#### Colposcopy")

                adequacy_options = [
                    "Not assessed",
                    "Satisfactory",
                    "Unsatisfactory",
                    "Other"
                ]

                saved_adequacy = pathology_saved.get(
                    "colposcopy_adequacy"
                )

                colposcopy_adequacy = st.selectbox(
                    "Colposcopy Adequacy",
                    adequacy_options,
                    index=(
                        adequacy_options.index(saved_adequacy)
                        if saved_adequacy in adequacy_options
                        else 0
                    )
                )

                impression_options = [
                    "Not assessed",
                    "Normal",
                    "Low grade",
                    "High grade",
                    "Cancer",
                    "Other"
                ]

                saved_impression = pathology_saved.get(
                    "colposcopy_impression"
                )

                colposcopy_impression = st.selectbox(
                    "Colposcopic Impression",
                    impression_options,
                    index=(
                        impression_options.index(saved_impression)
                        if saved_impression in impression_options
                        else 0
                    )
                )

                st.markdown("#### Endocervical Sampling")

                sampling_options = [
                    "No",
                    "ECB",
                    "ECC"
                ]

                saved_sampling = pathology_saved.get(
                    "endocervical_sampling"
                )

                endocervical_sampling = st.selectbox(
                    "Endocervical Sampling",
                    sampling_options,
                    index=(
                        sampling_options.index(saved_sampling)
                        if saved_sampling in sampling_options
                        else 0
                    )
                )

                result_options = [
                    "Not applicable",
                    "Inadequate",
                    "Negative",
                    "Positive"
                ]

                saved_result = pathology_saved.get(
                    "endocervical_result"
                )

                endocervical_result = st.selectbox(
                    "Endocervical Sampling Result",
                    result_options,
                    index=(
                        result_options.index(saved_result)
                        if saved_result in result_options
                        else 0
                    )
                )

                st.markdown("#### Additional Information")

                additional_note = st.text_area(
                    "Additional Note",
                    value=pathology_saved.get("additional_note") or ""
                )

                submitted_pathology = st.form_submit_button(
                    "Save Pathology Review",
                    type="primary"
                )

            if submitted_pathology:
                require_non_cancelled_appointment(pathology_appointment_id)
                pathology_data = {
                    "review_date": str(review_date),
                    "reviewed_by": reviewed_by,
                    "review_note": review_note,
                    "cytology_result": cytology_result,
                    "colposcopy_adequacy": colposcopy_adequacy,
                    "colposcopy_impression": colposcopy_impression,
                    "endocervical_sampling": endocervical_sampling,
                    "endocervical_result": endocervical_result,
                    "additional_note": additional_note,
                    
                }

                save_pathology_review(
                    pathology_appointment_id,
                    pathology_data
                )

                st.success(
                    "Pathology Review saved successfully."
                )

                
            # Step 6.7D.3.4.5 - Pathology Specimen Results
            st.divider()
            st.subheader("Pathology Specimen Results")

            total_specimens = len(pathology_source_specimens)

            reported_specimens = sum(
                1
                for source in pathology_source_specimens
                if str(
                    pathology_results_by_source.get(
                        source["id"], {}
                    ).get("pathology_diagnosis") or ""
                ).strip()
            )

            if total_specimens > 0:
                if reported_specimens == total_specimens:
                    reporting_status = "Full reported"
                elif reported_specimens > 0:
                    reporting_status = "Partial reported"
                else:
                    reporting_status = "Pending"

                st.progress(
                    reported_specimens / total_specimens,
                    text=(
                        f"Pathology Reporting: "
                        f"{reported_specimens}/{total_specimens} "
                        f"specimens reported — {reporting_status}"
                    )
                )

            if not pathology_source_specimens:
                st.info(
                    "No collected specimens available. "
                    "Confirm specimen collection in "
                    "Colposcopy Record first."
                )

            else:
                with st.form(
                    f"pathology_specimens_form_{pathology_appointment_id}"
                ):
                    pathology_specimen_data = []

                    for source in pathology_source_specimens:
                        st.markdown("---")
                        source_id = source["id"]

                        saved_result = (
                            pathology_results_by_source.get(
                                source_id, {}
                            )
                        )

                        saved_diagnosis = str(
                            saved_result.get("pathology_diagnosis") or ""
                        ).strip()

                        pathology_status = (
                            "Reported" if saved_diagnosis else "Pending"
                        )

                        st.markdown(
                            f"#### Specimen "
                            f"{source.get('specimen_label') or source_id}"
                            f" — {pathology_status}"
                        )

                        st.caption(
                            f"Specimen ID: {source_id}  |  "
                            f"Type: {source['specimen_type']}"
                        )

                        st.caption(
                            f"Biopsy Site: {source.get('biopsy_site') or '-'}  |  "
                            f"Collection Date: {source['collection_date']}"
                        )

                        pathology_number = st.text_input(
                            "Pathology Number",
                            value=(
                                saved_result.get("pathology_number") or ""
                            ),
                            placeholder="e.g. TEST-PATH-002",
                            help="Accession / laboratory report number for this specimen",
                            key=f"path_number_{pathology_appointment_id}_{source_id}",
                        )

                        diagnosis = st.text_area(
                            "Pathology Diagnosis",
                            value=(
                                saved_result.get(
                                    "pathology_diagnosis"
                                ) or ""
                            ),
                            key=f"path_diag_{pathology_appointment_id}_{source_id}"
                        )

                        cancer_subtype = st.text_input(
                            "Cancer Subtype",
                            value=(
                                saved_result.get(
                                    "cancer_subtype"
                                ) or ""
                            ),
                            key=f"path_subtype_{pathology_appointment_id}_{source_id}"
                        )

                        pathology_remark = st.text_area(
                            "Pathology Remark",
                            value=(
                                saved_result.get(
                                    "specimen_remark"
                                ) or ""
                            ),
                            key=f"path_remark_{pathology_appointment_id}_{source_id}"
                        )

                        
                        
                        # Histopathology invasion parameters
                        st.markdown("**Invasion Assessment**")
                        depth_col, width_col = st.columns(2)
                        saved_depth = saved_result.get("invasion_depth_mm")
                        saved_width = saved_result.get("invasion_width_mm")

                        with depth_col:
                            depth_assessed = st.checkbox(
                                "Invasion Depth assessed",
                                value=saved_depth is not None,
                                key=f"path_depth_assessed_{pathology_appointment_id}_{source_id}"
                            )

                            invasion_depth = None

                            if depth_assessed:
                                invasion_depth = st.number_input(
                                    "Invasion Depth (mm)",
                                    min_value=0.0,
                                    step=0.1,
                                    value=(
                                        float(saved_depth)
                                        if saved_depth is not None
                                        else 0.0
                                    ),
                                    key=f"path_depth_{pathology_appointment_id}_{source_id}"
                                )

                        with width_col:
                            width_assessed = st.checkbox(
                                "Invasion Width assessed",
                                value=saved_width is not None,
                                key=f"path_width_assessed_{pathology_appointment_id}_{source_id}"
                            )

                            invasion_width = None

                            if width_assessed:
                                invasion_width = st.number_input(
                                    "Invasion Width (mm)",
                                    min_value=0.0,
                                    step=0.1,
                                    value=(
                                        float(saved_width)
                                        if saved_width is not None
                                        else 0.0
                                    ),
                                    key=f"path_width_{pathology_appointment_id}_{source_id}"
                                )

                        st.markdown("**Lymphovascular Space Invasion (LVSI)**")

                        lvsi_options = [
                            "Not assessed",
                            "Absent",
                            "Present"
                        ]

                        saved_lvsi = saved_result.get("lvsi")

                        lvsi = st.selectbox(
                            "LVSI",
                            lvsi_options,
                            index=(
                                lvsi_options.index(saved_lvsi)
                                if saved_lvsi in lvsi_options
                                else 0
                            ),
                            key=f"path_lvsi_{pathology_appointment_id}_{source_id}",
                            label_visibility="collapsed"
                        )


                        pathology_specimen_data.append({
                            "colposcopy_specimen_id": source_id,
                            "specimen_type": source["specimen_type"],
                            "biopsy_site": source.get("biopsy_site"),
                            "pathology_number": pathology_number.strip(),
                            "pathology_diagnosis": diagnosis,
                            "cancer_subtype": cancer_subtype,
                            "invasion_depth_mm": invasion_depth,
                            "invasion_width_mm": invasion_width,
                            "lvsi": lvsi,
                            "specimen_remark": pathology_remark,
                        })


                    submitted_pathology_specimens = (
                        st.form_submit_button(
                            "Save Pathology Specimens",
                            type="primary"
                        )
                    )

                    
                if submitted_pathology_specimens:
                    require_non_cancelled_appointment(pathology_appointment_id)
                    try:
                        specimens_to_save = []

                        for specimen in pathology_specimen_data:
                            source_id = specimen["colposcopy_specimen_id"]

                            existing_result = (
                                pathology_results_by_source.get(
                                    source_id
                                )
                            )

                            diagnosis = str(
                                specimen.get("pathology_diagnosis") or ""
                            ).strip()

                            # Preserve an existing result unless
                            # the user explicitly provides a diagnosis.
                            if not diagnosis:
                                if existing_result:
                                    raise ValueError(
                                        "Diagnosis cannot be cleared for "
                                        f"Specimen ID {source_id}. "
                                        "Please enter the diagnosis."
                                    )

                                # No diagnosis and no previous result:
                                # do not create an empty pathology record.
                                continue

                            specimens_to_save.append(specimen)

                        if not specimens_to_save:
                            raise ValueError(
                                "No pathology diagnosis entered. "
                                "Nothing was saved."
                            )

                        save_pathology_specimens(
                            pathology_appointment_id,
                            specimens_to_save
                        )

                        st.toast(
                            "Pathology specimens saved successfully.",
                            icon="✅"
                        )

                        st.rerun()

                    except ValueError as error:
                        st.error(str(error))



        

            # Step 6.7D.3.6.4.2 - Management and internal LEEP Queue sync.
            st.divider()
            st.subheader("Correlation & Management After Pathology Review")

            saved_management = get_pathology_management_plans(
                pathology_appointment_id
            )
            management_labels = {
                "LEEP": "LEEP",
                "LEEP_ECC": "LEEP + ECC",
                "CKC": "CKC",
                "REPEAT_COLPOSCOPY": "Repeat colposcopy",
                "REPEAT_LEEP": "Repeat LEEP",
                "FOLLOW_UP": "Follow-up",
                "OTHER": "Other",
            }
            saved_correlation = (
                pathology_saved.get("correlation") or ""
            ).strip().lower()
            correlation_options = ["Not assessed", "Agreement", "Discordant"]
            correlation_index = {
                "agreement": 1,
                "discordant": 2,
            }.get(saved_correlation, 0)
            correlation_choice = st.selectbox(
                "Colposcopy–Pathology Correlation",
                correlation_options,
                index=correlation_index,
                key=f"management_correlation_{pathology_appointment_id}",
            )

            st.markdown("#### Management Plan")
            st.caption(
                "Select more than one option if needed. "
                "Saving LEEP, LEEP + ECC or Repeat LEEP creates/updates "
                "the internal LEEP Queue. Repeat colposcopy with a date "
                "creates/updates an appointment in the Booking queue."
            )
            management_selection = {}
            management_dates = {}
            followup_codes = []
            followup_months = None
            other_management_detail = ""

            for management_code, management_label in management_labels.items():
                saved_plan = saved_management.get(management_code, {})
                management_selection[management_code] = st.checkbox(
                    management_label,
                    value=bool(saved_plan),
                    key=(
                        f"management_selected_{pathology_appointment_id}_"
                        f"{management_code}"
                    ),
                )
                if not management_selection[management_code]:
                    continue

                if management_code in (
                    "LEEP", "LEEP_ECC", "REPEAT_COLPOSCOPY", "REPEAT_LEEP"
                ):
                    date_labels = {
                        "LEEP": "LEEP Date",
                        "LEEP_ECC": "LEEP + ECC Date",
                        "REPEAT_COLPOSCOPY": "Repeat Colposcopy Date",
                        "REPEAT_LEEP": "Repeat LEEP Date",
                    }
                    previous_date = saved_plan.get("planned_date")
                    management_dates[management_code] = st.date_input(
                        date_labels[management_code],
                        value=(
                            date.fromisoformat(previous_date)
                            if previous_date else None
                        ),
                        key=(
                            f"management_date_{pathology_appointment_id}_"
                            f"{management_code}"
                        ),
                    )
                    if management_code in ("LEEP", "LEEP_ECC", "REPEAT_LEEP"):
                        st.caption("Internal LEEP Queue: created/updated on Save")
                    else:
                        st.caption(
                            "Repeat Colposcopy: create/update Booking appointment "
                            "on Save (registry only)"
                        )

                elif management_code == "FOLLOW_UP":
                    test_options = {
                        "PAP_SMEAR": "Pap smear",
                        "COTEST": "Cotest (Pap + HPV)",
                        "PRIMARY_HPV": "Primary HPV",
                    }
                    followup_codes = st.multiselect(
                        "Follow-up Tests",
                        options=list(test_options.keys()),
                        default=saved_plan.get("followup_tests", []),
                        format_func=lambda code: test_options[code],
                        key=f"management_followup_tests_{pathology_appointment_id}",
                    )
                    followup_months = st.number_input(
                        "First Follow-up Interval (months)",
                        min_value=1,
                        max_value=240,
                        value=saved_plan.get("followup_interval_months") or 6,
                        step=1,
                        key=f"management_followup_months_{pathology_appointment_id}",
                    )

                elif management_code == "OTHER":
                    other_management_detail = st.text_area(
                        "Specify Other Management",
                        value=saved_plan.get("other_detail") or "",
                        key=f"management_other_{pathology_appointment_id}",
                        height=100,
                    )

            management_comment = st.text_area(
                "Management Comment",
                value=pathology_saved.get("management_comment") or "",
                key=f"management_comment_{pathology_appointment_id}",
                height=120,
            )

            if st.button(
                "Save Correlation & Management",
                type="primary",
                key=f"save_management_{pathology_appointment_id}",
            ):
                require_non_cancelled_appointment(pathology_appointment_id)
                try:
                    plans_to_save = []
                    for code, selected in management_selection.items():
                        if not selected:
                            continue
                        planned_date = management_dates.get(code)
                        plans_to_save.append({
                            "management_code": code,
                            "planned_date": (
                                str(planned_date) if planned_date else None
                            ),
                            "followup_interval_months": (
                                int(followup_months)
                                if code == "FOLLOW_UP" else None
                            ),
                            "followup_tests": (
                                followup_codes if code == "FOLLOW_UP" else []
                            ),
                            "other_detail": (
                                other_management_detail if code == "OTHER" else None
                            ),
                        })

                    save_pathology_management(
                        pathology_appointment_id,
                        correlation=(
                            None if correlation_choice == "Not assessed"
                            else correlation_choice
                        ),
                        management_comment=management_comment,
                        plans=plans_to_save,
                    )
                    st.toast(
                        "Management, LEEP Queue and Repeat Colposcopy saved.",
                        icon="✅",
                    )
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))

            # Read-only status of the repeat appointment, including history.
            linked_repeat = get_repeat_colposcopy_appointment(
                pathology_appointment_id
            )
            if linked_repeat:
                st.markdown("#### Linked Repeat Colposcopy Appointment")
                st.info(
                    f"Appointment ID {linked_repeat['id']} | "
                    f"Date: {linked_repeat['appointment_date']} | "
                    f"Status: {linked_repeat['status']}"
                )
                if linked_repeat["status"] in ("Cancelled", "Completed"):
                    st.caption(
                        "This historical appointment is not automatically "
                        "reactivated by saving Management again."
                    )

            # Read-only summary of the linked queue, including historical rows.
            linked_leep_queue = get_leep_queue_for_appointment(
                pathology_appointment_id
            )
            if linked_leep_queue:
                st.markdown("#### Linked LEEP Queue")
                st.dataframe([
                    {
                        "Queue ID": row["id"],
                        "Procedure": {
                            "LEEP": "LEEP", "LEEP_ECC": "LEEP + ECC",
                            "REPEAT_LEEP": "Repeat LEEP",
                        }.get(row["management_code"], row["management_code"]),
                        "Planned Date": row["planned_date"] or "-",
                        "Status": row["status"],
                        "Performed Date": row["performed_date"] or "-",
                    }
                    for row in linked_leep_queue
                ], use_container_width=True, hide_index=True)

            # Step 6.7D.3.6.5.22 — separate saved Pathology Review PDF.
            st.divider()
            show_pathology_pdf_download(pathology_appointment_id)

        else:
            st.warning("No matching appointments found.")

    else:
        st.info("Enter HN or patient name to search.")


elif menu == "LEEP Queue":
    st.header("Internal LEEP Queue")
    st.caption(
        "Registry-only scheduling. This does not book a hospital procedure. "
        "Queue entries can originate from Pathology Review or Direct LEEP Management."
    )

    queue_status_filter = st.selectbox(
        "Queue Status", ["All", *LEEP_QUEUE_STATUSES],
        key="leep_queue_filter_status",
    )
    use_queue_date_filter = st.checkbox(
        "Filter by planned date", value=False, key="leep_queue_filter_by_date"
    )
    queue_filter_date = (
        st.date_input("Planned Date", value=date.today(), key="leep_queue_filter_date")
        if use_queue_date_filter else None
    )
    all_queue = get_leep_queue()
    queue_rows = get_leep_queue(
        status=None if queue_status_filter == "All" else queue_status_filter,
        planned_date=str(queue_filter_date) if queue_filter_date else None,
    )
    st.caption(f"{len(queue_rows)} of {len(all_queue)} queue entries")

    queue_type_labels = {
        "LEEP": "LEEP", "LEEP_ECC": "LEEP + ECC",
        "REPEAT_LEEP": "Repeat LEEP",
    }
    if queue_rows:
        st.dataframe([
            {
                "Queue ID": row["id"],
                "HN": row["hn"],
                "Patient": row["patient_name"],
                "Procedure": queue_type_labels.get(
                    row["management_code"], row["management_code"]
                ),
                "Planned Date": row["planned_date"] or "-",
                "Source": (
                    "Direct LEEP (Colposcopy)" if row.get("creation_source")
                    in ("EXPEDITED_COLPOSCOPY", "DIRECT_COLPOSCOPY") else "Pathology Review"
                ),
                "Indication": DIRECT_LEEP_INDICATIONS.get(
                    row.get("direct_leep_indication"), "-"
                ),
                "Status": row["status"],
                "Performed Date": row["performed_date"] or "-",
                "Source Appointment": row["source_appointment_date"],
            }
            for row in queue_rows
        ], use_container_width=True, hide_index=True)
    else:
        st.info("No LEEP queue entries match these filters.")

    # The editor uses all entries so filtered-out entries remain editable.
    if all_queue:
        st.subheader("Edit LEEP Queue Entry")
        queue_by_id = {row["id"]: row for row in all_queue}
        selected_queue_id = st.selectbox(
            "Select Queue Entry", options=list(queue_by_id),
            format_func=lambda queue_id: (
                f"#{queue_id} — {queue_by_id[queue_id]['hn']} — "
                f"{queue_type_labels.get(queue_by_id[queue_id]['management_code'], queue_by_id[queue_id]['management_code'])} "
                f"({queue_by_id[queue_id]['status']})"
            ),
            key="leep_queue_edit_id",
        )
        selected_queue = queue_by_id[selected_queue_id]
        # Status must be outside st.form so selecting Completed immediately
        # displays the Actual Performed Date input.
        queue_status = st.selectbox(
            "Status", list(LEEP_QUEUE_STATUSES),
            index=LEEP_QUEUE_STATUSES.index(selected_queue["status"]),
            key=f"leep_queue_status_{selected_queue_id}",
        )
        with st.form(f"leep_queue_edit_{selected_queue_id}"):
            planned_value = selected_queue.get("planned_date")
            planned_edit = st.date_input(
                "Planned Procedure Date",
                value=date.fromisoformat(planned_value) if planned_value else None,
            )
            performed_edit = None
            if queue_status == "Completed":
                actual_value = selected_queue.get("performed_date")
                performed_edit = st.date_input(
                    "Actual Performed Date",
                    value=date.fromisoformat(actual_value) if actual_value else date.today(),
                )
            queue_note = st.text_area(
                "Queue Note", value=selected_queue.get("queue_note") or "",
                height=100,
            )
            save_queue_clicked = st.form_submit_button(
                "Save LEEP Queue Entry", type="primary"
            )
        if save_queue_clicked:
            try:
                update_leep_queue_entry(
                    selected_queue_id,
                    status=queue_status,
                    planned_date=str(planned_edit) if planned_edit else None,
                    performed_date=str(performed_edit) if performed_edit else None,
                    queue_note=queue_note,
                )
                st.toast("LEEP Queue updated.", icon="✅")
                st.rerun()
            except ValueError as error:
                st.error(str(error))


        # LEEP Day Note preparation: one saved draft per stable queue ID.
        st.divider()
        st.subheader("Prepare LEEP Day Note")
        st.caption(
            "Prepare and save the LEEP Day Note, then download a print-ready PDF. "
            "Handwritten additions are scanned into the hospital system (not this registry)."
        )
        source_appointment_id = selected_queue["source_appointment_id"]
        source_patient = get_appointment_by_id(source_appointment_id)
        source_history = get_pre_colposcopy_review(source_appointment_id) or {}
        source_colposcopy = get_colposcopy_record(source_appointment_id) or {}
        source_pathology = get_pathology_specimens(source_appointment_id)
        saved_day_note = get_leep_day_note(selected_queue_id)
        note_defaults = (
            saved_day_note if saved_day_note is not None
            else default_leep_day_note_text(selected_queue)
        )

        st.write(
            f"**Queue ID:** {selected_queue_id} | "
            f"**HN:** {selected_queue['hn']} | "
            f"**Patient:** {selected_queue['patient_name']}"
        )
        st.write(
            f"**Procedure:** {queue_type_labels.get(selected_queue['management_code'])} | "
            f"**Planned Date:** {selected_queue.get('planned_date') or '-'} | "
            f"**Queue Status:** {selected_queue['status']}"
        )
        if saved_day_note:
            st.success("Saved LEEP Day Note found. You can review and edit it.")
            st.caption(f"Last updated: {saved_day_note['updated_at']}")
        else:
            st.info("No saved LEEP Day Note yet. Standard draft is pre-filled.")

        if source_patient:
            with st.expander("Auto-filled Clinical History & Previous Results", expanded=True):
                st.text_area(
                    "Saved source data (read-only)",
                    value=build_leep_day_note_source_summary(
                        source_patient, source_history,
                        source_colposcopy, source_pathology,
                    ),
                    height=250,
                    disabled=True,
                    key=f"leep_day_note_source_{selected_queue_id}",
                )
                st.caption(
                    "Only saved records are shown. This summary is not an "
                    "independent clinical verification."
                )

        day_note_readonly = (
            selected_queue["status"] == "Cancelled"
            or not source_patient
            or source_patient["status"] == "Cancelled"
        )
        if day_note_readonly:
            st.warning(
                "This LEEP queue or source appointment is Cancelled. "
                "The saved note is read-only."
            )

        with st.form(f"leep_day_note_form_{selected_queue_id}"):
            clinical_note = st.text_area(
                "Today's Clinical Note",
                value=note_defaults["clinical_note"],
                height=140,
                disabled=day_note_readonly,
            )
            management_note = st.text_area(
                "Mx / Planned Procedure",
                value=note_defaults["management_note"],
                height=150,
                disabled=day_note_readonly,
            )
            plan_note = st.text_area(
                "Plan",
                value=note_defaults["plan_note"],
                height=100,
                disabled=day_note_readonly,
            )
            medication_note = st.text_area(
                "HM / Medication — editable draft",
                value=note_defaults["medication_note"],
                height=110,
                disabled=day_note_readonly,
            )
            st.caption(
                "Medication lines are user-provided template text only, "
                "NOT verified prescriptions. Review indication, allergies, "
                "dose and local protocol before clinical use."
            )
            additional_note = st.text_area(
                "Additional Clinical Note",
                value=note_defaults["additional_note"],
                height=150,
                placeholder="Additional history, examination, assessment or notes...",
                disabled=day_note_readonly,
            )
            save_day_note_clicked = st.form_submit_button(
                "Save LEEP Day Note", type="primary", disabled=day_note_readonly,
            )
        if save_day_note_clicked:
            try:
                save_leep_day_note(selected_queue_id, {
                    "clinical_note": clinical_note,
                    "management_note": management_note,
                    "plan_note": plan_note,
                    "medication_note": medication_note,
                    "additional_note": additional_note,
                })
                st.toast("LEEP Day Note saved.", icon="✅")
                st.rerun()
            except ValueError as error:
                st.error(str(error))

        # Step 2: PDF from SAVED data only. Never export unsaved form edits.
        st.divider()
        st.subheader("Export LEEP Day Note PDF")
        if saved_day_note and source_patient:
            try:
                leep_pdf_bytes = generate_leep_day_note_pdf(
                    patient=source_patient,
                    queue=selected_queue,
                    clinical_history=source_history,
                    colposcopy_record=source_colposcopy,
                    pathology_specimens=source_pathology,
                    day_note=saved_day_note,
                )
                st.download_button(
                    "Download LEEP Day Note PDF",
                    data=leep_pdf_bytes,
                    file_name=(
                        f"LEEP_Day_Note_{source_patient['hn']}_"
                        f"Queue_{selected_queue_id}.pdf"
                    ),
                    mime="application/pdf",
                    key=f"leep_day_note_pdf_{selected_queue_id}",
                )
                st.caption(
                    "Uses SAVED data only. Save any edits before downloading. "
                    "Print and annotate by hand; scan into the hospital system. "
                    "Medication text requires clinical verification."
                )
            except Exception as error:
                st.error(f"LEEP Day Note PDF generation failed: {error}")
        else:
            st.info("Save the LEEP Day Note before exporting its PDF.")


elif menu == "Excel Export":
    st.header("Research Data Export")
    st.info("Excel export based on DATA.xlsx — Coming soon")
