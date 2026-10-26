
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "colposcopy.db"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection



def init_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_date TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                patient_name TEXT NOT NULL,
                hn TEXT NOT NULL,
                phone TEXT,
                indication TEXT NOT NULL,
                registered_by TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Scheduled',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        columns = [
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(appointments)"
            ).fetchall()
        ]

        if "status" not in columns:
            conn.execute("""
                ALTER TABLE appointments
                ADD COLUMN status TEXT NOT NULL
                DEFAULT 'Scheduled'
            """)


    # Step 5.2.2 - Colposcopy Records
    conn.execute("""
        CREATE TABLE IF NOT EXISTS colposcopy_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL UNIQUE,

            colposcopy_date TEXT,
            via_result TEXT,

            colposcopy_satisfactory INTEGER
                CHECK (colposcopy_satisfactory IN (0, 1)),

            tzone INTEGER
                CHECK (tzone IN (1, 2, 3)),

            awe INTEGER
                CHECK (awe IN (0, 1, 2)),

            leukoplakia INTEGER
                CHECK (leukoplakia IN (0, 1)),

            condyloma INTEGER
                CHECK (condyloma IN (0, 1)),

            exophytic INTEGER
                CHECK (exophytic IN (0, 1)),

            ulcerative INTEGER
                CHECK (ulcerative IN (0, 1)),

            punctation INTEGER
                CHECK (punctation IN (0, 1)),

            mosaic INTEGER
                CHECK (mosaic IN (0, 1)),

            suspicious INTEGER
                CHECK (suspicious IN (0, 1)),

            colposcopy_ci INTEGER
                CHECK (colposcopy_ci IN (0, 1, 2, 3, 4)),

            colposcopy_description TEXT,
            procedure_type TEXT,
            biopsy_site TEXT,
            procedure_notes TEXT,

            performed_by TEXT,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (appointment_id)
                REFERENCES appointments(id)
        )
    """)

    # Colposcopic Findings v2: additive migration only.
    # Preserve existing AWE coding (0/1/2) and all saved records.
    new_colposcopy_columns = {
        "awe_clock_position": "TEXT",
        "awe_other_selected": "INTEGER DEFAULT 0",
        "awe_other_text": "TEXT",
        "leukoplakia_detail": "TEXT",
        "condyloma_detail": "TEXT",
        "exophytic_detail": "TEXT",
        "ulcerative_detail": "TEXT",
        "punctation_detail": "TEXT",
        "mosaic_detail": "TEXT",
        "suspicious_detail": "TEXT",
        "colposcopy_generated_summary": "TEXT",
        # Existing UI fields missing from some older database schemas.
        "cervical_diagram_path": "TEXT",
        "colposcopy_remark": "TEXT",
    }
    with get_connection() as conn:
        current_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(colposcopy_records)"
            ).fetchall()
        }
        for column_name, column_type in new_colposcopy_columns.items():
            if column_name not in current_columns:
                conn.execute(
                    f"ALTER TABLE colposcopy_records "
                    f"ADD COLUMN {column_name} {column_type}"
                )


    # Step 6.7D.3.6.2 - additive management schema migration.
    # This runs after the existing appointment/colposcopy initialization.
    init_management_tables()

    # Step 6.7D.3.6.4.1 - Internal LEEP Queue (schema only).
    init_leep_queue_tables()

    # LEEP Day Note drafts, keyed by the stable LEEP Queue ID.
    init_leep_day_note_tables()

    # Step 6.7D.3.6.5.1 - Repeat Colposcopy appointment linkage.
    init_repeat_colposcopy_tables()


def add_appointment(
    booking_date,
    appointment_date,
    patient_name,
    hn,
    phone,
    indication,
    registered_by
):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO appointments (
                booking_date,
                appointment_date,
                patient_name,
                hn,
                phone,
                indication,
                registered_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            str(booking_date),
            str(appointment_date),
            patient_name,
            hn,
            phone,
            indication,
            registered_by
        ))


def get_appointments(appointment_date):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM appointments
            WHERE appointment_date = ?
            ORDER BY id ASC
        """, (str(appointment_date),)).fetchall()

        return [dict(row) for row in rows]


def search_appointments(keyword):
    keyword = keyword.strip()

    if not keyword:
        return []

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM appointments
            WHERE hn LIKE ? OR patient_name LIKE ?
            ORDER BY appointment_date DESC, id DESC
        """, (
            f"%{keyword}%",
            f"%{keyword}%"
        )).fetchall()

        return [dict(row) for row in rows]

def get_appointment_by_id(appointment_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT *
            FROM appointments
            WHERE id = ?
        """, (appointment_id,)).fetchone()

        return dict(row) if row else None


def update_appointment(
    appointment_id,
    appointment_date,
    phone,
    indication,
    status
):
    allowed_statuses = {
        "Scheduled",
        "Completed",
        "Cancelled",
        "No-show"
    }

    if status not in allowed_statuses:
        raise ValueError("Invalid appointment status")

    with get_connection() as conn:
        conn.execute("""
            UPDATE appointments
            SET appointment_date = ?,
                phone = ?,
                indication = ?,
                status = ?
            WHERE id = ?
        """, (
            str(appointment_date),
            phone,
            indication,
            status,
            appointment_id
        ))


def check_duplicate_appointment(hn, appointment_date):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS total
            FROM appointments
            WHERE hn = ?
              AND appointment_date = ?
              AND status != 'Cancelled'
        """, (hn, str(appointment_date))).fetchone()

        return row["total"] > 0

def init_pre_colposcopy_database():
    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pre_colposcopy_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL UNIQUE,

                age INTEGER,
                parity TEXT,
                lmp TEXT,

                first_intercourse_age INTEGER,
                number_of_partners INTEGER,
                hiv_status TEXT,
                history_of_stds TEXT,
                smoking_status TEXT,

                menstrual_status TEXT,
                contraception TEXT,
                menopause_duration TEXT,
                hrt_history TEXT,

                pap_smear_result TEXT,
                pap_smear_date TEXT,
                pap_smear_location TEXT,

                hpv_result TEXT,
                hpv_genotype TEXT,

                hpv_vaccinated TEXT,
                hpv_vaccine_type TEXT,
                hpv_vaccine_completion_date TEXT,

                symptoms TEXT,
                previous_history TEXT,

                reviewed_by TEXT,
                review_date TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (appointment_id)
                    REFERENCES appointments(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS clinical_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL,

                document_type TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                mime_type TEXT,

                uploaded_by TEXT,
                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (appointment_id)
                    REFERENCES appointments(id)
            )
        """)

def save_pre_colposcopy_review(appointment_id, data):

    allowed_fields = {
        "age", "parity", "lmp",
        "first_intercourse_age", "number_of_partners",
        "hiv_status", "history_of_stds", "smoking_status",
        "menstrual_status", "contraception",
        "menopause_duration", "hrt_history",
        "pap_smear_result", "pap_smear_date",
        "pap_smear_location", "patho_number", "hpv_result", "hpv_genotype",
        "hpv_vaccinated", "hpv_vaccine_type",
        "hpv_vaccine_completion_date",
        "symptoms", "previous_history",
        "reviewed_by", "review_date"
    }

    fields = {k: v for k, v in data.items()
              if k in allowed_fields}

    if not fields:
        raise ValueError("No valid review fields supplied")

    columns = ["appointment_id"] + list(fields.keys())
    values = [appointment_id] + list(fields.values())

    placeholders = ", ".join(["?"] * len(columns))
    column_names = ", ".join(columns)

    updates = ", ".join(
        f"{key} = excluded.{key}" for key in fields
    )

    with get_connection() as conn:
        conn.execute(f"""
            INSERT INTO pre_colposcopy_reviews
                ({column_names})
            VALUES ({placeholders})
            ON CONFLICT(appointment_id)
            DO UPDATE SET
                {updates},
                updated_at = CURRENT_TIMESTAMP
        """, values)


def get_pre_colposcopy_review(appointment_id):

    with get_connection() as conn:
        row = conn.execute("""
            SELECT *
            FROM pre_colposcopy_reviews
            WHERE appointment_id = ?
        """, (appointment_id,)).fetchone()

        return dict(row) if row else None

def save_clinical_document(
    appointment_id,
    document_type,
    file_name,
    file_path,
    mime_type,
    uploaded_by
):
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO clinical_documents (
                appointment_id,
                document_type,
                file_name,
                file_path,
                mime_type,
                uploaded_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                appointment_id,
                document_type,
                file_name,
                file_path,
                mime_type,
                uploaded_by
            )
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_clinical_documents(appointment_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM clinical_documents
            WHERE appointment_id = ?
            ORDER BY uploaded_at DESC, id DESC
            """,
            (appointment_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# Step 5.2.3 - Save / Load Colposcopy Record

COLPOSCOPY_FIELDS = [
    "colposcopy_date",
    "via_result",
    "colposcopy_satisfactory",
    "tzone",
    "awe",
    "awe_clock_position",
    "awe_other_selected",
    "awe_other_text",
    "leukoplakia",
    "condyloma",
    "exophytic",
    "ulcerative",
    "punctation",
    "mosaic",
    "suspicious",
    "leukoplakia_detail",
    "condyloma_detail",
    "exophytic_detail",
    "ulcerative_detail",
    "punctation_detail",
    "mosaic_detail",
    "suspicious_detail",
    "colposcopy_ci",
    "colposcopy_description",
    "colposcopy_generated_summary",
    "procedure_type",
    "biopsy_site",
    "procedure_notes",
    "performed_by",
    "cervical_diagram_path",
    "colposcopy_remark",
]


def save_colposcopy_record(appointment_id, data):
    """
    Insert or update a colposcopy record.
    One record per appointment.
    """

    columns = ["appointment_id"] + COLPOSCOPY_FIELDS

    column_names = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))

    values = [appointment_id] + [
        data.get(field) for field in COLPOSCOPY_FIELDS
    ]

    updated = ", ".join(
        f"{field} = excluded.{field}"
        for field in COLPOSCOPY_FIELDS
    )

    with get_connection() as conn:
        conn.execute(
            f"""
            INSERT INTO colposcopy_records
                ({column_names})
            VALUES ({placeholders})
            ON CONFLICT(appointment_id)
            DO UPDATE SET
                {updated},
                updated_at = CURRENT_TIMESTAMP
            """,
            values
        )


def get_colposcopy_record(appointment_id):
    """
    Return saved colposcopy record or None.
    """

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM colposcopy_records
            WHERE appointment_id = ?
            """,
            (appointment_id,)
        ).fetchone()

    return dict(row) if row is not None else None

# Step 6 - Pathology Review Database

def init_pathology_tables():
    """Create pathology review and specimen tables."""

    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pathology_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL UNIQUE,

                review_date TEXT,
                hiv_status TEXT,
                hiv_not_done_reason TEXT,
                review_note TEXT,

                cytology_result TEXT,
                colposcopy_adequacy TEXT,
                colposcopy_impression TEXT,

                endocervical_sampling TEXT,
                endocervical_result TEXT,

                correlation TEXT,
                management TEXT,
                management_date TEXT,
                additional_note TEXT,
                reviewed_by TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (appointment_id)
                    REFERENCES appointments(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pathology_specimens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pathology_review_id INTEGER NOT NULL,
                specimen_order INTEGER NOT NULL,

                specimen_type TEXT NOT NULL,
                biopsy_site TEXT,
                pathology_number TEXT,
                pathology_diagnosis TEXT,
                cancer_subtype TEXT,

                invasion_depth_mm REAL,
                invasion_width_mm REAL,
                lvsi TEXT,
                specimen_remark TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (pathology_review_id)
                    REFERENCES pathology_reviews(id)
                    ON DELETE CASCADE
            )
        """)

        # Step 6.7D.3.6.5.17: separate pathology accession number from diagnosis.
        # Additive, idempotent migration; existing diagnoses are untouched.
        specimen_columns = {
            row["name"] for row in conn.execute(
                "PRAGMA table_info(pathology_specimens)"
            ).fetchall()
        }
        if "pathology_number" not in specimen_columns:
            conn.execute(
                "ALTER TABLE pathology_specimens ADD COLUMN pathology_number TEXT"
            )

        conn.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_pathology_specimens_review
            ON pathology_specimens(pathology_review_id)
        """)

# Step 6.7D.3.6.2 - Correlation and Multiple Management schema
# Schema only: UI and queue creation will be added in later steps.
# Existing pathology_reviews.correlation / management / management_date
# remain untouched for compatibility with older records.

MANAGEMENT_CODES = (
    "LEEP",
    "LEEP_ECC",
    "CKC",
    "REPEAT_COLPOSCOPY",
    "REPEAT_LEEP",
    "FOLLOW_UP",
    "OTHER",
)

FOLLOWUP_TEST_CODES = (
    "PAP_SMEAR",
    "COTEST",
    "PRIMARY_HPV",
)


def init_management_tables():
    """Idempotent, additive migration for future pathology management UI.

    No queue records are created, and existing clinical data are not modified.
    """
    # Safe on existing and fresh databases; creates pathology_reviews if absent.
    init_pathology_tables()

    with get_connection() as conn:
        review_columns = {
            row["name"] for row in conn.execute(
                "PRAGMA table_info(pathology_reviews)"
            ).fetchall()
        }
        if "management_comment" not in review_columns:
            conn.execute(
                "ALTER TABLE pathology_reviews ADD COLUMN management_comment TEXT"
            )

        # One record per selected management action, per appointment.
        # Keeping appointment_id on the plan allows it to exist before a
        # pathology review is saved. It must refer to an existing appointment.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pathology_management_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL,
                management_code TEXT NOT NULL CHECK (
                    management_code IN (
                        'LEEP', 'LEEP_ECC', 'CKC',
                        'REPEAT_COLPOSCOPY', 'REPEAT_LEEP',
                        'FOLLOW_UP', 'OTHER'
                    )
                ),
                planned_date TEXT,
                followup_interval_months INTEGER CHECK (
                    followup_interval_months IS NULL
                    OR followup_interval_months > 0
                ),
                other_detail TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (appointment_id) REFERENCES appointments(id),
                UNIQUE (appointment_id, management_code)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_management_plans_appointment
            ON pathology_management_plans(appointment_id)
        """)

        # Multiple follow-up methods may be selected together.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pathology_management_followup_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                management_plan_id INTEGER NOT NULL,
                test_code TEXT NOT NULL CHECK (
                    test_code IN ('PAP_SMEAR', 'COTEST', 'PRIMARY_HPV')
                ),
                FOREIGN KEY (management_plan_id)
                    REFERENCES pathology_management_plans(id)
                    ON DELETE CASCADE,
                UNIQUE (management_plan_id, test_code)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_management_followup_plan
            ON pathology_management_followup_tests(management_plan_id)
        """)


# Step 6.3 - Save / Load Pathology Review

PATHOLOGY_REVIEW_FIELDS = [
    "review_date",
    "hiv_status",
    "hiv_not_done_reason",
    "review_note",
    "cytology_result",
    "colposcopy_adequacy",
    "colposcopy_impression",
    "endocervical_sampling",
    "endocervical_result",
    "correlation",
    "management",
    "management_date",
    "management_comment",
    "additional_note",
    "reviewed_by",
]


def save_pathology_review(appointment_id, data):
    """Insert or update one pathology review per appointment."""

    fields = {
        key: data[key]
        for key in PATHOLOGY_REVIEW_FIELDS
        if key in data
    }

    if not fields:
        raise ValueError("No pathology review fields supplied")

    columns = ["appointment_id"] + list(fields.keys())
    values = [appointment_id] + list(fields.values())

    column_names = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))

    updates = ", ".join(
        f"{field} = excluded.{field}"
        for field in fields
    )

    with get_connection() as conn:
        conn.execute(
            f"""
            INSERT INTO pathology_reviews ({column_names})
            VALUES ({placeholders})
            ON CONFLICT(appointment_id)
            DO UPDATE SET
                {updates},
                updated_at = CURRENT_TIMESTAMP
            """,
            values,
        )


def get_pathology_review(appointment_id):
    """Return saved pathology review or None."""

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM pathology_reviews
            WHERE appointment_id = ?
            """,
            (appointment_id,),
        ).fetchone()

    return dict(row) if row is not None else None

# Step 6.4 - Save / Load Pathology Specimens

PATHOLOGY_SPECIMEN_FIELDS = [
    "specimen_type",
    "biopsy_site",
    "pathology_number",
    "pathology_diagnosis",
    "cancer_subtype",
    "invasion_depth_mm",
    "invasion_width_mm",
    "lvsi",
    "specimen_remark",
]



def save_pathology_specimens(appointment_id, specimens):
    """
    Insert or update pathology results using the stable
    colposcopy_specimen_id.

    Omitted specimens are NOT deleted.
    """

    if not isinstance(specimens, list):
        raise ValueError("Specimens must be a list")

    with get_connection() as conn:
        review = conn.execute(
            """
            SELECT id
            FROM pathology_reviews
            WHERE appointment_id = ?
            """,
            (appointment_id,),
        ).fetchone()

        if review is None:
            raise ValueError(
                "Save Pathology Review before saving specimens"
            )

        review_id = review["id"]
        seen_ids = set()

        # Validate all specimens before modifying data.
        for specimen in specimens:
            if not isinstance(specimen, dict):
                raise ValueError(
                    "Each specimen must be a dictionary"
                )

            if not str(
                specimen.get("specimen_type") or ""
            ).strip():
                raise ValueError("Specimen type is required")

            source_id = specimen.get("colposcopy_specimen_id")

            if (
                not isinstance(source_id, int)
                or isinstance(source_id, bool)
            ):
                raise ValueError(
                    "Valid Colposcopy Specimen ID is required"
                )

            if source_id in seen_ids:
                raise ValueError(
                    "Duplicate Colposcopy Specimen ID"
                )

            seen_ids.add(source_id)

            source = conn.execute(
                """
                SELECT id
                FROM colposcopy_specimens
                WHERE id = ?
                  AND appointment_id = ?
                  AND collection_date IS NOT NULL
                  AND TRIM(collection_date) != ''
                """,
                (source_id, appointment_id),
            ).fetchone()

            if source is None:
                raise ValueError(
                    "Specimen must be collected and belong "
                    f"to this appointment. ID: {source_id}"
                )

            existing = conn.execute(
                """
                SELECT ps.id
                FROM pathology_specimens ps
                JOIN pathology_reviews pr
                    ON pr.id = ps.pathology_review_id
                WHERE ps.colposcopy_specimen_id = ?
                  AND pr.appointment_id != ?
                """,
                (source_id, appointment_id),
            ).fetchone()

            if existing is not None:
                raise ValueError(
                    "Pathology Specimen is linked "
                    "to another appointment."
                )

        for order, specimen in enumerate(specimens, start=1):
            source_id = specimen["colposcopy_specimen_id"]

            conn.execute(
                """
                INSERT INTO pathology_specimens (
                    pathology_review_id,
                    specimen_order,
                    colposcopy_specimen_id,
                    specimen_type,
                    biopsy_site,
                    pathology_number,
                    pathology_diagnosis,
                    cancer_subtype,
                    invasion_depth_mm,
                    invasion_width_mm,
                    lvsi,
                    specimen_remark
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

                ON CONFLICT(colposcopy_specimen_id)
                DO UPDATE SET
                    specimen_order = excluded.specimen_order,
                    specimen_type = excluded.specimen_type,
                    biopsy_site = excluded.biopsy_site,
                    pathology_number = excluded.pathology_number,
                    pathology_diagnosis = excluded.pathology_diagnosis,
                    cancer_subtype = excluded.cancer_subtype,
                    invasion_depth_mm = excluded.invasion_depth_mm,
                    invasion_width_mm = excluded.invasion_width_mm,
                    lvsi = excluded.lvsi,
                    specimen_remark = excluded.specimen_remark
                """,
                (
                    review_id,
                    order,
                    source_id,
                    specimen.get("specimen_type"),
                    specimen.get("biopsy_site"),
                    specimen.get("pathology_number"),
                    specimen.get("pathology_diagnosis"),
                    specimen.get("cancer_subtype"),
                    specimen.get("invasion_depth_mm"),
                    specimen.get("invasion_width_mm"),
                    specimen.get("lvsi"),
                    specimen.get("specimen_remark"),
                ),
            )



def get_pathology_specimens(appointment_id):
    """Return all specimens ordered by specimen_order."""

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT s.*
            FROM pathology_specimens AS s
            JOIN pathology_reviews AS r
                ON s.pathology_review_id = r.id
            WHERE r.appointment_id = ?
            ORDER BY s.specimen_order, s.id
            """,
            (appointment_id,),
        ).fetchall()

    return [dict(row) for row in rows]


# Step 6.7A - Colposcopy Specimen Tracking

def init_colposcopy_specimen_tables():
    """
    Create source specimens collected during colposcopy
    and link pathology results to those specimens.
    """

    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS colposcopy_specimens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL,

                specimen_order INTEGER NOT NULL,
                specimen_label TEXT,
                specimen_type TEXT NOT NULL,
                biopsy_site TEXT,
                collection_date TEXT,
                specimen_remark TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (appointment_id)
                    REFERENCES appointments(id)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_colposcopy_specimens_appointment
            ON colposcopy_specimens(appointment_id)
        """)

        # Add linkage to existing pathology_specimens table.
        existing_columns = [
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(pathology_specimens)"
            ).fetchall()
        ]

        if "colposcopy_specimen_id" not in existing_columns:
            conn.execute("""
                ALTER TABLE pathology_specimens
                ADD COLUMN colposcopy_specimen_id INTEGER
                    REFERENCES colposcopy_specimens(id)
            """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_pathology_specimen_source
            ON pathology_specimens(colposcopy_specimen_id)
        """)

# Step 6.7B - Save / Load Colposcopy Specimens

COLPOSCOPY_SPECIMEN_FIELDS = [
    "specimen_label",
    "specimen_type",
    "biopsy_site",
    "collection_date",
    "specimen_remark",
]


def get_colposcopy_specimens(appointment_id):
    """Return specimens collected for one appointment."""

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM colposcopy_specimens
            WHERE appointment_id = ?
            ORDER BY specimen_order, id
            """,
            (appointment_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def save_colposcopy_specimens(appointment_id, specimens):
    """
    Synchronize specimens for one appointment.

    Existing specimen IDs are preserved.
    New specimens receive new IDs.
    Missing specimens are deleted only when safe.
    """

    if not isinstance(specimens, list):
        raise ValueError("Specimens must be a list")

    with get_connection() as conn:

        appointment = conn.execute(
            "SELECT id FROM appointments WHERE id = ?",
            (appointment_id,),
        ).fetchone()

        if appointment is None:
            raise ValueError("Appointment not found")

        existing_rows = conn.execute(
            """
            SELECT id
            FROM colposcopy_specimens
            WHERE appointment_id = ?
            """,
            (appointment_id,),
        ).fetchall()

        existing_ids = {row["id"] for row in existing_rows}
        retained_ids = set()

        # Validate all input before modifying records.
        seen_ids = set()

        for specimen in specimens:
            if not isinstance(specimen, dict):
                raise ValueError(
                    "Each specimen must be a dictionary"
                )

            if not str(
                specimen.get("specimen_type") or ""
            ).strip():
                raise ValueError("Specimen type is required")

            specimen_id = specimen.get("id")

            if specimen_id is not None:
                if (
                    not isinstance(specimen_id, int)
                    or isinstance(specimen_id, bool)
                    or specimen_id not in existing_ids
                ):
                    raise ValueError(
                        "Invalid specimen ID for this appointment"
                    )

                if specimen_id in seen_ids:
                    raise ValueError(
                        "Duplicate specimen ID"
                    )

                seen_ids.add(specimen_id)

        for order, specimen in enumerate(
            specimens, start=1
        ):
            specimen_id = specimen.get("id")

            values = [
                specimen.get(field)
                for field in COLPOSCOPY_SPECIMEN_FIELDS
            ]

            
            if specimen_id is not None:
                # Preserve the existing collection date
                # unless a new date is explicitly provided.
                existing_specimen = conn.execute(
                    """
                    SELECT collection_date
                    FROM colposcopy_specimens
                    WHERE id = ? AND appointment_id = ?
                    """,
                    (specimen_id, appointment_id),
                ).fetchone()

                incoming_date = specimen.get(
                    "collection_date"
                )

                if "collection_date" in specimen:
                    collection_date_value = specimen["collection_date"]
                else:
                    collection_date_value = existing_specimen["collection_date"]

                
                # Prevent clearing collection date when
                # a pathology result is already linked.
                if (
                    existing_specimen["collection_date"]
                    and not collection_date_value
                ):
                    linked_pathology = conn.execute(
                        """
                        SELECT id
                        FROM pathology_specimens
                        WHERE colposcopy_specimen_id = ?
                          AND pathology_diagnosis IS NOT NULL
                          AND TRIM(pathology_diagnosis) != ''
                          AND LOWER(
                              TRIM(pathology_diagnosis)
                          ) != 'not assessed'
                        LIMIT 1
                        """,
                        (specimen_id,),
                    ).fetchone()

                    if linked_pathology is not None:
                        raise ValueError(
                            "Cannot clear Collection Date for "
                            "a specimen with a reported "
                            "pathology result. "
                            f"Specimen ID: {specimen_id}"
                        )

                conn.execute(
                    """
                    UPDATE colposcopy_specimens
                    SET specimen_order = ?,
                        specimen_label = ?,
                        specimen_type = ?,
                        biopsy_site = ?,
                        collection_date = ?,
                        specimen_remark = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND appointment_id = ?
                    """,
                    (
                        order,
                        specimen.get("specimen_label"),
                        specimen.get("specimen_type"),
                        specimen.get("biopsy_site"),
                        collection_date_value,
                        specimen.get("specimen_remark"),
                        specimen_id,
                        appointment_id,
                    ),
                )

                retained_ids.add(specimen_id)

            else:
                cursor = conn.execute(
                    """
                    INSERT INTO colposcopy_specimens (
                        appointment_id,
                        specimen_order,
                        specimen_label,
                        specimen_type,
                        biopsy_site,
                        collection_date,
                        specimen_remark
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        appointment_id,
                        order,
                        specimen.get("specimen_label"),
                        specimen.get("specimen_type"),
                        specimen.get("biopsy_site"),
                        specimen.get("collection_date"),
                        specimen.get("specimen_remark"),
                    ),
                )

                retained_ids.add(cursor.lastrowid)


        # Remove omitted specimens only if they have
        # no linked pathology record.
        removed_ids = existing_ids - retained_ids

        for specimen_id in removed_ids:
            linked = conn.execute(
                """
                SELECT id
                FROM pathology_specimens
                WHERE colposcopy_specimen_id = ?
                """,
                (specimen_id,),
            ).fetchone()

            if linked is not None:
                raise ValueError(
                    "Cannot remove specimen with pathology result. "
                    f"Specimen ID: {specimen_id}"
                )

            conn.execute(
                """
                DELETE FROM colposcopy_specimens
                WHERE id = ? AND appointment_id = ?
                """,
                (specimen_id, appointment_id),
            )

# Step 6.7D.1 - Pathology Worklist

def get_pathology_worklist(
    colposcopy_date=None,
    search_text=None,
    status=None,
):
    """
    Return patients with collected specimens.

    Status:
        Pending       = 0 reported specimens
        Partial       = some specimens reported
        Full reported = all specimens reported
    """

    query = """
        WITH specimen_summary AS (
            SELECT
                cs.appointment_id,

                COUNT(cs.id) AS total_specimens,

                SUM(
                    CASE
                        WHEN ps.pathology_diagnosis IS NOT NULL
                         AND TRIM(ps.pathology_diagnosis) != ''
                         AND LOWER(
                             TRIM(ps.pathology_diagnosis)
                         ) != 'not assessed'
                        THEN 1
                        ELSE 0
                    END
                ) AS reported_specimens,

                GROUP_CONCAT(
                    cs.specimen_type ||
                    CASE
                        WHEN cs.biopsy_site IS NOT NULL
                         AND TRIM(cs.biopsy_site) != ''
                        THEN ' (' || cs.biopsy_site || ')'
                        ELSE ''
                    END,
                    ', '
                ) AS specimen_list

            FROM colposcopy_specimens cs

            LEFT JOIN pathology_specimens ps
                ON ps.colposcopy_specimen_id = cs.id
                
                WHERE cs.collection_date IS NOT NULL
                AND TRIM(cs.collection_date) != ''

                GROUP BY cs.appointment_id
                        )

        SELECT
            a.id AS appointment_id,
            a.hn,
            a.patient_name,
            a.appointment_date,
            cr.colposcopy_date,

            ss.total_specimens,
            ss.reported_specimens,
            ss.specimen_list,

            CASE
                WHEN ss.reported_specimens = 0
                    THEN 'Pending'

                WHEN ss.reported_specimens < ss.total_specimens
                    THEN 'Partial'

                ELSE 'Full reported'
            END AS pathology_status

        FROM specimen_summary ss

        JOIN appointments a
            ON a.id = ss.appointment_id

        LEFT JOIN colposcopy_records cr
            ON cr.appointment_id = a.id

        WHERE 1 = 1
    """

    params = []

    if colposcopy_date:
        query += """
            AND COALESCE(
                cr.colposcopy_date,
                (
                    SELECT MIN(cs2.collection_date)
                        FROM colposcopy_specimens cs2
                        WHERE cs2.appointment_id = a.id
                        AND cs2.collection_date IS NOT NULL
                        AND TRIM(cs2.collection_date) != ''
                )
            ) = ?
        """
        params.append(str(colposcopy_date))

    if search_text:
        query += """
            AND (
                a.hn LIKE ?
                OR a.patient_name LIKE ?
            )
        """
        search_pattern = f"%{search_text.strip()}%"
        params.extend([search_pattern, search_pattern])

    query += """
        ORDER BY
            COALESCE(
                cr.colposcopy_date,
                a.appointment_date
            ) DESC,
            a.hn
    """

    with get_connection() as conn:
        rows = conn.execute(
            query,
            params
        ).fetchall()

    results = [dict(row) for row in rows]

    if status and status != "All":
        results = [
            row for row in results
            if row["pathology_status"] == status
        ]

    return results


# Step 6.7D.3.6.4.2 - Save/load Correlation and Multiple Management.
# Save also synchronizes internal LEEP queues in the SAME SQLite transaction.
# Repeat Colposcopy booking integration is a separate future step.

def get_pathology_management_plans(appointment_id):
    """Return saved plans keyed by management code, including follow-up tests."""
    with get_connection() as conn:
        plans = conn.execute(
            """
            SELECT * FROM pathology_management_plans
            WHERE appointment_id = ? ORDER BY id
            """,
            (appointment_id,),
        ).fetchall()
        result = {}
        for row in plans:
            plan = dict(row)
            tests = conn.execute(
                """
                SELECT test_code FROM pathology_management_followup_tests
                WHERE management_plan_id = ? ORDER BY id
                """,
                (plan["id"],),
            ).fetchall()
            plan["followup_tests"] = [test["test_code"] for test in tests]
            result[plan["management_code"]] = plan
    return result


def save_pathology_management(
    appointment_id, *, correlation, management_comment, plans
):
    """Atomically save review, management plans and internal LEEP queues.

    Selected LEEP/LEEP_ECC/REPEAT_LEEP plans create one queue row per code.
    Saving again preserves queue IDs, notes and completed/cancelled history.
    Removing a selected plan cancels active queue items rather than deleting.
    Repeat Colposcopy appointments are synchronized in the same transaction.
    """
    from datetime import date

    if correlation not in (None, "Agreement", "Discordant"):
        raise ValueError("Invalid correlation selection")
    if not isinstance(plans, list):
        raise ValueError("Management plans must be a list")
    if not isinstance(management_comment, str):
        raise ValueError("Management Comment must be text")

    cleaned = []
    seen = set()
    for plan in plans:
        if not isinstance(plan, dict):
            raise ValueError("Invalid management plan")
        code = plan.get("management_code")
        if code not in MANAGEMENT_CODES or code in seen:
            raise ValueError(f"Invalid or duplicate management: {code}")
        seen.add(code)

        planned_date = plan.get("planned_date") or None
        if planned_date is not None:
            try:
                date.fromisoformat(planned_date)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid planned date for {code}")
        if code not in (
            "LEEP", "LEEP_ECC", "REPEAT_COLPOSCOPY", "REPEAT_LEEP"
        ) and planned_date is not None:
            raise ValueError(f"Unexpected planned date for {code}")

        months = plan.get("followup_interval_months")
        tests = plan.get("followup_tests") or []
        if not isinstance(tests, list):
            raise ValueError("Follow-up tests must be a list")
        if code == "FOLLOW_UP":
            if not isinstance(months, int) or isinstance(months, bool) or months <= 0:
                raise ValueError("Follow-up interval must be a positive month count")
            if not tests:
                raise ValueError("Select at least one Follow-up Test")
            if len(set(tests)) != len(tests) or any(
                test not in FOLLOWUP_TEST_CODES for test in tests
            ):
                raise ValueError("Invalid or duplicate Follow-up Test")
        elif months is not None or tests:
            raise ValueError(f"Unexpected follow-up fields for {code}")

        other_detail = (plan.get("other_detail") or "").strip()
        if code == "OTHER" and not other_detail:
            raise ValueError("Specify Other Management before saving")
        if code != "OTHER" and other_detail:
            raise ValueError(f"Unexpected Other detail for {code}")

        cleaned.append((code, planned_date, months, other_detail or None, tests))

    with get_connection() as conn:
        appointment = conn.execute(
            "SELECT id FROM appointments WHERE id = ?", (appointment_id,)
        ).fetchone()
        if appointment is None:
            raise ValueError("Appointment not found")

        # Update only these two fields; never overwrite existing review details.
        conn.execute(
            """
            INSERT INTO pathology_reviews (
                appointment_id, correlation, management_comment
            ) VALUES (?, ?, ?)
            ON CONFLICT(appointment_id) DO UPDATE SET
                correlation = excluded.correlation,
                management_comment = excluded.management_comment,
                updated_at = CURRENT_TIMESTAMP
            """,
            (appointment_id, correlation, management_comment),
        )

        # Delete removed plans and their dependent tests explicitly because
        # older installations may not enable SQLite foreign key enforcement.
        saved_rows = conn.execute(
            "SELECT id, management_code FROM pathology_management_plans "
            "WHERE appointment_id = ?", (appointment_id,)
        ).fetchall()
        expedited_codes = {
            row["management_code"] for row in conn.execute("""
                SELECT management_code FROM leep_queue
                WHERE source_appointment_id = ?
                  AND creation_source IN ('EXPEDITED_COLPOSCOPY', 'DIRECT_COLPOSCOPY')
            """, (appointment_id,)).fetchall()
        }
        for saved in saved_rows:
            if (saved["management_code"] not in seen
                    and saved["management_code"] not in expedited_codes):
                conn.execute(
                    "DELETE FROM pathology_management_followup_tests "
                    "WHERE management_plan_id = ?", (saved["id"],)
                )
                conn.execute(
                    "DELETE FROM pathology_management_plans WHERE id = ?",
                    (saved["id"],),
                )

        for code, planned_date, months, other_detail, tests in cleaned:
            conn.execute(
                """
                INSERT INTO pathology_management_plans (
                    appointment_id, management_code, planned_date,
                    followup_interval_months, other_detail
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(appointment_id, management_code) DO UPDATE SET
                    planned_date = excluded.planned_date,
                    followup_interval_months = excluded.followup_interval_months,
                    other_detail = excluded.other_detail,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (appointment_id, code, planned_date, months, other_detail),
            )
            plan_id = conn.execute(
                """
                SELECT id FROM pathology_management_plans
                WHERE appointment_id = ? AND management_code = ?
                """,
                (appointment_id, code),
            ).fetchone()["id"]
            conn.execute(
                "DELETE FROM pathology_management_followup_tests "
                "WHERE management_plan_id = ?", (plan_id,)
            )
            for test in tests:
                conn.execute(
                    """
                    INSERT INTO pathology_management_followup_tests (
                        management_plan_id, test_code
                    ) VALUES (?, ?)
                    """,
                    (plan_id, test),
                )

        # Synchronize LEEP queue within the SAME transaction as the plan save.
        # This prevents partial writes if validation/SQLite errors occur.
        queue_plans = {
            code: planned_date for code, planned_date, *_ in cleaned
            if code in LEEP_QUEUE_CODES
        }
        current_queue = conn.execute(
            "SELECT * FROM leep_queue WHERE source_appointment_id = ?",
            (appointment_id,),
        ).fetchall()
        current_by_code = {row["management_code"]: row for row in current_queue}

        for code, planned_date in queue_plans.items():
            previous = current_by_code.get(code)
            if previous is None:
                conn.execute("""
                    INSERT INTO leep_queue (
                        source_appointment_id, management_code, planned_date, status
                    ) VALUES (?, ?, ?, ?)
                """, (
                    appointment_id, code, planned_date,
                    "Scheduled" if planned_date else "Pending",
                ))
            elif previous["status"] not in ("Cancelled", "Completed"):
                # Preserve notes and performed date. Keep date/status consistent.
                new_status = previous["status"]
                if not planned_date and new_status == "Scheduled":
                    new_status = "Pending"
                elif (planned_date and not previous["planned_date"]
                      and new_status == "Pending"):
                    new_status = "Scheduled"
                conn.execute("""
                    UPDATE leep_queue
                    SET planned_date = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (planned_date, new_status, previous["id"]))
            # Completed/Cancelled rows remain unchanged for audit/history.
            # To reactivate a cancelled plan, use the LEEP Queue page.

        for code, previous in current_by_code.items():
            if (code not in queue_plans
                    and previous["creation_source"] not in ("EXPEDITED_COLPOSCOPY", "DIRECT_COLPOSCOPY")
                    and previous["status"] in ("Pending", "Scheduled")):
                conn.execute("""
                    UPDATE leep_queue
                    SET status = 'Cancelled', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (previous["id"],))

        # Step 6.7D.3.6.5.2 - Book/update Repeat Colposcopy in the SAME
        # transaction as Management and LEEP Queue. A conflict rolls back all.
        repeat_plan = next(
            (item for item in cleaned if item[0] == "REPEAT_COLPOSCOPY"), None
        )
        sync_repeat_colposcopy_appointment(
            appointment_id,
            selected=repeat_plan is not None,
            planned_date=repeat_plan[1] if repeat_plan else None,
            _connection=conn,
        )


# Step 6.7D.3.6.4.1 - Internal LEEP Queue backend.
# No queue is created merely by starting the application.
# Linking queue creation to Save Management and the queue UI comes next.
LEEP_QUEUE_CODES = ("LEEP", "LEEP_ECC", "REPEAT_LEEP")
LEEP_QUEUE_STATUSES = ("Pending", "Scheduled", "Completed", "Cancelled")


def init_leep_queue_tables():
    """Add an internal procedure queue without altering existing records."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leep_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_appointment_id INTEGER NOT NULL,
                management_code TEXT NOT NULL CHECK (
                    management_code IN ('LEEP', 'LEEP_ECC', 'REPEAT_LEEP')
                ),
                planned_date TEXT,
                status TEXT NOT NULL DEFAULT 'Pending' CHECK (
                    status IN ('Pending', 'Scheduled', 'Completed', 'Cancelled')
                ),
                performed_date TEXT,
                queue_note TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_appointment_id) REFERENCES appointments(id),
                UNIQUE (source_appointment_id, management_code)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_leep_queue_date_status
            ON leep_queue(planned_date, status)
        """)
        # Additive origin marker; existing queue rows remain PATHOLOGY_REVIEW.
        queue_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(leep_queue)")
        }
        if "creation_source" not in queue_columns:
            conn.execute("""
                ALTER TABLE leep_queue ADD COLUMN creation_source TEXT NOT NULL
                DEFAULT 'PATHOLOGY_REVIEW'
            """)
        # Structured indication is distinct from the LEEP/LEEP+ECC procedure.
        # Older direct queue rows remain NULL until reviewed and categorized.
        if "direct_leep_indication" not in queue_columns:
            conn.execute("""
                ALTER TABLE leep_queue ADD COLUMN direct_leep_indication TEXT
            """)


# Step LEEP Day Note 1 — editable preparation note (no PDF or scan yet).
LEEP_DAY_NOTE_FIELDS = (
    "clinical_note", "management_note", "plan_note",
    "medication_note", "additional_note",
)


def init_leep_day_note_tables():
    """Additive, idempotent schema. One draft per LEEP queue entry."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leep_day_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                leep_queue_id INTEGER NOT NULL UNIQUE,
                clinical_note TEXT NOT NULL DEFAULT '',
                management_note TEXT NOT NULL DEFAULT '',
                plan_note TEXT NOT NULL DEFAULT '',
                medication_note TEXT NOT NULL DEFAULT '',
                additional_note TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (leep_queue_id) REFERENCES leep_queue(id)
            )
        """)


def get_leep_day_note(queue_id):
    """Return the saved draft, if any; never create a row on read."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM leep_day_notes WHERE leep_queue_id = ?",
            (queue_id,),
        ).fetchone()
        return dict(row) if row else None


def save_leep_day_note(queue_id, data):
    """Save text-only preparation fields, preserving the linked queue ID.

    Refuse new edits for a cancelled queue or cancelled source appointment.
    Existing records and the rest of the registry are left untouched.
    """
    if not isinstance(data, dict) or set(data) != set(LEEP_DAY_NOTE_FIELDS):
        raise ValueError("All five LEEP Day Note fields are required")
    for field in LEEP_DAY_NOTE_FIELDS:
        if not isinstance(data[field], str):
            raise ValueError(f"{field} must be text")
        if len(data[field]) > 20000:
            raise ValueError(f"{field} exceeds 20,000 characters")

    with get_connection() as conn:
        queue = conn.execute("""
            SELECT q.status AS queue_status, a.status AS appointment_status
            FROM leep_queue AS q
            JOIN appointments AS a ON a.id = q.source_appointment_id
            WHERE q.id = ?
        """, (queue_id,)).fetchone()
        if queue is None:
            raise ValueError("LEEP queue entry not found")
        if queue["queue_status"] == "Cancelled":
            raise ValueError("Cancelled LEEP queue entries are read-only")
        if queue["appointment_status"] == "Cancelled":
            raise ValueError("Source appointment is Cancelled; note is read-only")

        fields = ", ".join(LEEP_DAY_NOTE_FIELDS)
        placeholders = ", ".join("?" for _ in LEEP_DAY_NOTE_FIELDS)
        updates = ", ".join(
            f"{field} = excluded.{field}" for field in LEEP_DAY_NOTE_FIELDS
        )
        conn.execute(f"""
            INSERT INTO leep_day_notes (leep_queue_id, {fields})
            VALUES (?, {placeholders})
            ON CONFLICT(leep_queue_id) DO UPDATE SET
                {updates}, updated_at = CURRENT_TIMESTAMP
        """, (queue_id, *(data[field] for field in LEEP_DAY_NOTE_FIELDS)))


def get_leep_queue(*, status=None, planned_date=None):
    """Read queue entries with patient identifiers for the registry view."""
    if status is not None and status not in LEEP_QUEUE_STATUSES:
        raise ValueError("Invalid LEEP queue status")
    if planned_date is not None:
        from datetime import date
        try:
            planned_date = date.fromisoformat(str(planned_date)).isoformat()
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid LEEP queue date") from error

    query = """
        SELECT q.*, a.hn, a.patient_name, a.appointment_date AS source_appointment_date
        FROM leep_queue AS q
        JOIN appointments AS a ON a.id = q.source_appointment_id
        WHERE 1 = 1
    """
    params = []
    if status is not None:
        query += " AND q.status = ?"
        params.append(status)
    if planned_date is not None:
        query += " AND q.planned_date = ?"
        params.append(planned_date)
    query += " ORDER BY q.planned_date IS NULL, q.planned_date, q.id"
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_leep_queue_for_appointment(appointment_id):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM leep_queue WHERE source_appointment_id = ?
            ORDER BY id
        """, (appointment_id,)).fetchall()
        return [dict(row) for row in rows]


def save_leep_queue_entry(
    source_appointment_id, management_code, *, planned_date=None,
    status=None, performed_date=None, queue_note=None,
):
    """Upsert a single queue item, preserving its stable ID.

    Explicit function for later UI integration; this is NOT automatically
    called when saving a management plan in this step.
    """
    from datetime import date
    if management_code not in LEEP_QUEUE_CODES:
        raise ValueError("Invalid LEEP procedure type")
    if planned_date is not None:
        try:
            planned_date = date.fromisoformat(str(planned_date)).isoformat()
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid planned LEEP date") from error
    if performed_date is not None:
        try:
            performed_date = date.fromisoformat(str(performed_date)).isoformat()
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid performed date") from error
    if status is None:
        status = "Scheduled" if planned_date else "Pending"
    if status not in LEEP_QUEUE_STATUSES:
        raise ValueError("Invalid LEEP queue status")
    if status == "Scheduled" and planned_date is None:
        raise ValueError("Scheduled queue requires a planned date")
    if status == "Completed" and performed_date is None:
        raise ValueError("Completed queue requires a performed date")
    if status != "Completed" and performed_date is not None:
        raise ValueError("Performed date is only allowed for Completed status")

    with get_connection() as conn:
        if conn.execute(
            "SELECT 1 FROM appointments WHERE id = ?", (source_appointment_id,)
        ).fetchone() is None:
            raise ValueError("Source appointment not found")
        conn.execute("""
            INSERT INTO leep_queue (
                source_appointment_id, management_code, planned_date,
                status, performed_date, queue_note
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_appointment_id, management_code) DO UPDATE SET
                planned_date = excluded.planned_date,
                status = excluded.status,
                performed_date = excluded.performed_date,
                queue_note = excluded.queue_note,
                updated_at = CURRENT_TIMESTAMP
        """, (
            source_appointment_id, management_code, planned_date,
            status, performed_date, queue_note,
        ))
        return conn.execute("""
            SELECT id FROM leep_queue
            WHERE source_appointment_id = ? AND management_code = ?
        """, (source_appointment_id, management_code)).fetchone()["id"]


# Step 4 — Direct LEEP planning from saved Colposcopy Record.
# Indication (diagnostic/expedited/other) is separate from the procedure type.
# No pathology result or pathology review is created by this action.
DIRECT_LEEP_INDICATIONS = {
    "DIAGNOSTIC": "Diagnostic LEEP",
    "EXPEDITED": "Expedited treatment",
    "OTHER": "Other indication",
}
DIRECT_LEEP_SOURCES = ("DIRECT_COLPOSCOPY", "EXPEDITED_COLPOSCOPY")
DIRECT_LEEP_NOTE_PREFIX = "Direct LEEP (from Colposcopy Record): "
LEGACY_EXPEDITED_NOTE_PREFIX = "Expedited treatment (from Colposcopy Record): "


def create_direct_leep_queue(
    appointment_id, *, management_code, indication_code,
    clinical_reason, planned_date=None,
):
    """Save an explicitly planned LEEP and retain stable queue IDs.

    Existing Step 3 expedited rows are updatable without reclassification
    until the user chooses the indication; original source code is preserved.
    """
    from datetime import date

    if management_code not in ("LEEP", "LEEP_ECC"):
        raise ValueError("Planned procedure must be LEEP or LEEP + ECC")
    if indication_code not in DIRECT_LEEP_INDICATIONS:
        raise ValueError("Select an indication for LEEP")
    if not isinstance(clinical_reason, str) or not clinical_reason.strip():
        raise ValueError("Clinical reason is required")
    clinical_reason = clinical_reason.strip()
    if len(clinical_reason) > 1000:
        raise ValueError("Clinical reason too long (maximum 1000 characters)")
    if planned_date is not None:
        try:
            planned_date = date.fromisoformat(str(planned_date)).isoformat()
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid planned procedure date") from error

    with get_connection() as conn:
        appointment = conn.execute(
            "SELECT status FROM appointments WHERE id = ?", (appointment_id,)
        ).fetchone()
        if appointment is None:
            raise ValueError("Appointment not found")
        if appointment["status"] == "Cancelled":
            raise ValueError("Cancelled appointment is read-only")
        colposcopy = conn.execute(
            "SELECT colposcopy_date FROM colposcopy_records WHERE appointment_id = ?",
            (appointment_id,),
        ).fetchone()
        if colposcopy is None or not colposcopy["colposcopy_date"]:
            raise ValueError("Save and confirm the Colposcopy Record first")

        conflicting = conn.execute("""
            SELECT id, management_code FROM leep_queue
            WHERE source_appointment_id = ? AND management_code IN ('LEEP','LEEP_ECC')
              AND management_code != ? AND status != 'Cancelled'
            LIMIT 1
        """, (appointment_id, management_code)).fetchone()
        if conflicting is not None:
            raise ValueError(
                f"Existing LEEP Queue ID {conflicting['id']} uses "
                f"{conflicting['management_code']}; edit that queue instead"
            )

        previous = conn.execute("""
            SELECT * FROM leep_queue
            WHERE source_appointment_id = ? AND management_code = ?
        """, (appointment_id, management_code)).fetchone()
        if previous is not None:
            if previous["status"] in ("Completed", "Cancelled"):
                raise ValueError("Completed/Cancelled queue cannot be overwritten")
            if previous["creation_source"] not in DIRECT_LEEP_SOURCES:
                raise ValueError(
                    "A Pathology Review queue already exists; edit it in LEEP Queue"
                )

        # The existing queue editor requires a matching management plan.
        # This is a scheduling plan, NOT a pathology review or pathology result.
        conn.execute("""
            INSERT INTO pathology_management_plans
                (appointment_id, management_code, planned_date)
            VALUES (?, ?, ?)
            ON CONFLICT(appointment_id, management_code) DO UPDATE SET
                planned_date = excluded.planned_date,
                updated_at = CURRENT_TIMESTAMP
        """, (appointment_id, management_code, planned_date))

        note_line = (
            DIRECT_LEEP_NOTE_PREFIX
            + DIRECT_LEEP_INDICATIONS[indication_code]
            + " — " + clinical_reason
        )
        if previous is None:
            conn.execute("""
                INSERT INTO leep_queue
                    (source_appointment_id, management_code, planned_date,
                     status, queue_note, creation_source, direct_leep_indication)
                VALUES (?, ?, ?, ?, ?, 'DIRECT_COLPOSCOPY', ?)
            """, (
                appointment_id, management_code, planned_date,
                "Scheduled" if planned_date else "Pending", note_line,
                indication_code,
            ))
        else:
            kept_lines = [
                line for line in (previous["queue_note"] or "").splitlines()
                if not line.startswith((DIRECT_LEEP_NOTE_PREFIX, LEGACY_EXPEDITED_NOTE_PREFIX))
            ]
            note = "\n".join([*kept_lines, note_line]).strip()
            conn.execute("""
                UPDATE leep_queue SET planned_date = ?, status = ?,
                    queue_note = ?, direct_leep_indication = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                planned_date, "Scheduled" if planned_date else "Pending",
                note, indication_code, previous["id"],
            ))

        queue = conn.execute("""
            SELECT id FROM leep_queue
            WHERE source_appointment_id = ? AND management_code = ?
        """, (appointment_id, management_code)).fetchone()
        return queue["id"]


# Step 6.7D.3.6.4.2 - Queue editor, using the stable queue ID.
def update_leep_queue_entry(
    queue_id, *, status, planned_date=None, performed_date=None, queue_note=""
):
    """Edit a queue item without changing its source appointment/procedure.

    Completed cases retain their history; cancelled cases may be reactivated
    only when the corresponding management plan remains selected.
    """
    from datetime import date

    if status not in LEEP_QUEUE_STATUSES:
        raise ValueError("Invalid LEEP queue status")
    for label, value in (
        ("planned", planned_date), ("performed", performed_date)
    ):
        if value is not None:
            try:
                date.fromisoformat(str(value))
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid {label} LEEP date") from error
    if status == "Scheduled" and planned_date is None:
        raise ValueError("Scheduled requires a planned procedure date")
    if status == "Completed" and performed_date is None:
        raise ValueError("Completed requires an actual performed date")
    if status != "Completed" and performed_date is not None:
        raise ValueError("Performed date is only valid for Completed status")
    if not isinstance(queue_note, str):
        raise ValueError("Queue note must be text")

    with get_connection() as conn:
        previous = conn.execute(
            "SELECT * FROM leep_queue WHERE id = ?", (queue_id,)
        ).fetchone()
        if previous is None:
            raise ValueError("LEEP queue entry not found")
        if previous["status"] == "Completed" and status != "Completed":
            raise ValueError(
                "A completed procedure cannot be reverted from this screen"
            )
        if status in ("Pending", "Scheduled", "Completed"):
            active_plan = conn.execute("""
                SELECT 1 FROM pathology_management_plans
                WHERE appointment_id = ? AND management_code = ?
            """, (
                previous["source_appointment_id"], previous["management_code"]
            )).fetchone()
            if active_plan is None:
                raise ValueError(
                    "Re-select this procedure in Management before scheduling"
                )
        conn.execute("""
            UPDATE leep_queue
            SET status = ?, planned_date = ?, performed_date = ?,
                queue_note = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            status, str(planned_date) if planned_date else None,
            str(performed_date) if performed_date else None,
            queue_note.strip() or None, queue_id,
        ))
        # Keep the Management date in sync with manual queue rescheduling.
        # Cancelled queues retain their historical plan date unchanged.
        if status != "Cancelled":
            conn.execute("""
                UPDATE pathology_management_plans
                SET planned_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE appointment_id = ? AND management_code = ?
            """, (
                str(planned_date) if planned_date else None,
                previous["source_appointment_id"], previous["management_code"],
            ))


# Step 6.7D.3.6.5.1 - Repeat Colposcopy appointment backend.
# Helpers are also used by Save Management in Step 6.7D.3.6.5.2.

def init_repeat_colposcopy_tables():
    """Create one durable source -> repeat appointment link per source case."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS repeat_colposcopy_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_appointment_id INTEGER NOT NULL UNIQUE,
                repeat_appointment_id INTEGER NOT NULL UNIQUE,
                last_synced_date TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_appointment_id) REFERENCES appointments(id),
                FOREIGN KEY (repeat_appointment_id) REFERENCES appointments(id),
                CHECK (source_appointment_id != repeat_appointment_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_repeat_colpo_repeat_id
            ON repeat_colposcopy_links(repeat_appointment_id)
        """)


def get_repeat_colposcopy_appointment(source_appointment_id):
    """Return the linked repeat appointment, or None if not booked."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT a.*, l.source_appointment_id, l.last_synced_date,
                   l.id AS repeat_link_id
            FROM repeat_colposcopy_links AS l
            JOIN appointments AS a ON a.id = l.repeat_appointment_id
            WHERE l.source_appointment_id = ?
        """, (source_appointment_id,)).fetchone()
        return dict(row) if row else None


def sync_repeat_colposcopy_appointment(
    source_appointment_id, *, selected, planned_date=None, _connection=None
):
    """Sync one Repeat Colposcopy plan to the appointment queue.

    Returns an action and the linked appointment (if any). Never deletes
    appointments or automatically reactivates Cancelled/Completed/No-show.
    Duplicate patient/date appointments are rejected before any write.
    _connection is an internal optional connection to keep plan and booking
    in one atomic transaction. Without it, this helper commits independently.
    """
    from datetime import date

    if not isinstance(selected, bool):
        raise ValueError("selected must be True or False")
    if planned_date is not None:
        if not isinstance(planned_date, str):
            raise ValueError("Repeat Colposcopy date must be YYYY-MM-DD")
        try:
            parsed = date.fromisoformat(planned_date)
        except ValueError as error:
            raise ValueError("Invalid Repeat Colposcopy date") from error
        if parsed.isoformat() != planned_date:
            raise ValueError("Repeat Colposcopy date must be YYYY-MM-DD")
    if not selected and planned_date is not None:
        raise ValueError("A deselected Repeat Colposcopy cannot have a date")

    from contextlib import nullcontext

    connection_scope = (
        nullcontext(_connection) if _connection is not None
        else get_connection()
    )
    with connection_scope as conn:
        source = conn.execute(
            "SELECT * FROM appointments WHERE id = ?", (source_appointment_id,)
        ).fetchone()
        if source is None:
            raise ValueError("Source Colposcopy appointment not found")

        linked = conn.execute("""
            SELECT l.*, a.appointment_date, a.status, a.hn
            FROM repeat_colposcopy_links AS l
            JOIN appointments AS a ON a.id = l.repeat_appointment_id
            WHERE l.source_appointment_id = ?
        """, (source_appointment_id,)).fetchone()

        # Unselected or date removed: cancel only an active linked appointment.
        # Preserve all historical records and the source-to-repeat link.
        if not selected or planned_date is None:
            if linked is None:
                return {"action": "no_booking", "repeat_appointment_id": None}
            if linked["status"] == "Scheduled":
                conn.execute("""
                    UPDATE appointments SET status = 'Cancelled'
                    WHERE id = ? AND status = 'Scheduled'
                """, (linked["repeat_appointment_id"],))
                return {
                    "action": "cancelled",
                    "repeat_appointment_id": linked["repeat_appointment_id"],
                }
            return {
                "action": "preserved_" + linked["status"].lower(),
                "repeat_appointment_id": linked["repeat_appointment_id"],
            }

        if linked is not None:
            repeat_id = linked["repeat_appointment_id"]
            if linked["status"] != "Scheduled":
                return {
                    "action": "preserved_" + linked["status"].lower(),
                    "repeat_appointment_id": repeat_id,
                }
            # A user may have rescheduled this appointment on the Booking page.
            # Do not silently overwrite that independent change.
            if linked["appointment_date"] != linked["last_synced_date"]:
                if linked["appointment_date"] == planned_date:
                    # Reconcile when the plan already matches the manual date.
                    conn.execute("""
                        UPDATE repeat_colposcopy_links
                        SET last_synced_date = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (planned_date, linked["id"]))
                    return {"action": "reconciled", "repeat_appointment_id": repeat_id}
                raise ValueError(
                    "Repeat appointment date was changed manually. "
                    "Review the existing appointment before syncing Management."
                )
            if linked["appointment_date"] == planned_date:
                return {"action": "unchanged", "repeat_appointment_id": repeat_id}

            duplicate = conn.execute("""
                SELECT id FROM appointments
                WHERE hn = ? AND appointment_date = ?
                  AND status != 'Cancelled' AND id != ?
                LIMIT 1
            """, (source["hn"], planned_date, repeat_id)).fetchone()
            if duplicate:
                raise ValueError(
                    "Patient already has an active appointment on this date "
                    f"(Appointment ID {duplicate['id']})"
                )
            conn.execute("""
                UPDATE appointments SET appointment_date = ? WHERE id = ?
            """, (planned_date, repeat_id))
            conn.execute("""
                UPDATE repeat_colposcopy_links
                SET last_synced_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (planned_date, linked["id"]))
            return {"action": "rescheduled", "repeat_appointment_id": repeat_id}

        duplicate = conn.execute("""
            SELECT id FROM appointments
            WHERE hn = ? AND appointment_date = ? AND status != 'Cancelled'
            LIMIT 1
        """, (source["hn"], planned_date)).fetchone()
        if duplicate:
            raise ValueError(
                "Patient already has an active appointment on this date "
                f"(Appointment ID {duplicate['id']})"
            )

        cursor = conn.execute("""
            INSERT INTO appointments (
                booking_date, appointment_date, patient_name, hn, phone,
                indication, registered_by, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Scheduled')
        """, (
            date.today().isoformat(), planned_date, source["patient_name"],
            source["hn"], source["phone"],
            f"Repeat colposcopy — from Appointment ID {source_appointment_id}",
            "Registry / Pathology Review",
        ))
        repeat_id = cursor.lastrowid
        conn.execute("""
            INSERT INTO repeat_colposcopy_links (
                source_appointment_id, repeat_appointment_id, last_synced_date
            ) VALUES (?, ?, ?)
        """, (source_appointment_id, repeat_id, planned_date))
        return {"action": "created", "repeat_appointment_id": repeat_id}
