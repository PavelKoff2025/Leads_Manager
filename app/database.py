import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Literal, Optional

from app.models import Lead, LeadCreate, LeadStatus, LeadUpdate

SearchBy = Literal["name", "phone", "source"]
SEARCH_COLUMNS: dict[SearchBy, str] = {
    "name": "name",
    "phone": "contact",
    "source": "source",
}

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "leads.db"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    contact TEXT NOT NULL,
    source TEXT,
    comment TEXT,
    email TEXT UNIQUE,
    phone TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    notes TEXT,
    updated_at TEXT NOT NULL
);
"""


def _migrate_schema(conn: sqlite3.Connection) -> None:
    columns = {
        row[1]: row for row in conn.execute("PRAGMA table_info(leads)").fetchall()
    }
    if not columns:
        return

    if "contact" not in columns:
        conn.execute("ALTER TABLE leads ADD COLUMN contact TEXT")
    if "comment" not in columns:
        conn.execute("ALTER TABLE leads ADD COLUMN comment TEXT")

    conn.execute(
        """
        UPDATE leads
        SET contact = COALESCE(NULLIF(contact, ''), phone, email, '')
        WHERE contact IS NULL OR contact = ''
        """
    )
    conn.execute(
        """
        UPDATE leads
        SET comment = COALESCE(comment, notes, '')
        WHERE comment IS NULL
        """
    )

    email_col = columns.get("email")
    if email_col and email_col[3] == 1:
        conn.executescript(
            """
            CREATE TABLE leads_migrated (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                name TEXT NOT NULL,
                contact TEXT NOT NULL,
                source TEXT,
                comment TEXT,
                email TEXT UNIQUE,
                phone TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                notes TEXT,
                updated_at TEXT NOT NULL
            );
            INSERT INTO leads_migrated (
                id, created_at, name, contact, source, comment,
                email, phone, status, notes, updated_at
            )
            SELECT
                id, created_at, name,
                COALESCE(contact, phone, email, ''),
                source,
                COALESCE(comment, notes, ''),
                email, phone, status, notes, updated_at
            FROM leads;
            DROP TABLE leads;
            ALTER TABLE leads_migrated RENAME TO leads;
            """
        )

    conn.execute(
        """
        UPDATE leads
        SET email = NULL
        WHERE email LIKE '%@import.example.com'
           OR email LIKE '%@phone.import'
           OR email LIKE '%@import.local'
        """
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_lead(row: sqlite3.Row) -> Lead:
    contact = row["contact"] if row["contact"] else (row["phone"] or row["email"] or "")
    comment = row["comment"] if row["comment"] is not None else (row["notes"] or "")
    return Lead(
        id=row["id"],
        name=row["name"],
        contact=contact,
        source=row["source"],
        comment=comment or "",
        email=row["email"],
        phone=row["phone"],
        status=LeadStatus(row["status"]),
        notes=row["notes"],
        created_at=_parse_datetime(row["created_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
    )


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(CREATE_TABLE_SQL)
        _migrate_schema(conn)


def check_db_connection() -> None:
    """Проверяет доступность БД. Выбрасывает исключение при ошибке."""
    with get_connection() as conn:
        conn.execute("SELECT 1")


def create_lead(data: LeadCreate) -> Lead:
    now = _now_iso()
    contact = data.resolved_contact()
    comment = data.resolved_comment()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO leads (
                created_at, name, contact, source, comment,
                email, phone, status, notes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                data.name,
                contact,
                data.source,
                comment,
                data.email,
                data.phone,
                LeadStatus.NEW.value,
                data.notes if data.notes is not None else comment,
                now,
            ),
        )
        lead_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return _row_to_lead(row)


def get_lead(lead_id: int) -> Optional[Lead]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return _row_to_lead(row) if row else None


def get_all_leads(
    status: Optional[LeadStatus] = None,
    search: Optional[str] = None,
    search_by: SearchBy = "name",
    limit: int = 100,
    offset: int = 0,
) -> list[Lead]:
    query = "SELECT * FROM leads"
    params: list = []
    conditions: list[str] = []

    if status:
        conditions.append("status = ?")
        params.append(status.value)

    if search:
        column = SEARCH_COLUMNS[search_by]
        if search_by == "phone":
            digits = "".join(ch for ch in search if ch.isdigit())
            if digits:
                normalized_contact = (
                    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(contact, '+', ''), ' ', ''), '-', ''), '(', ''), ')', '')"
                )
                conditions.append(f"{normalized_contact} LIKE ? ESCAPE '\\'")
                params.append(f"%{digits}%")
            else:
                conditions.append("contact LIKE ? ESCAPE '\\' COLLATE NOCASE")
                escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                params.append(f"%{escaped}%")
        else:
            conditions.append(f"{column} LIKE ? ESCAPE '\\' COLLATE NOCASE")
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_lead(row) for row in rows]


def update_lead(lead_id: int, data: LeadUpdate) -> Optional[Lead]:
    existing = get_lead(lead_id)
    if not existing:
        return None

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        return existing

    if "status" in updates and updates["status"] is not None:
        updates["status"] = updates["status"].value

    if "phone" in updates or "email" in updates:
        phone = updates.get("phone", existing.phone)
        email = updates.get("email", existing.email)
        updates["contact"] = phone or email or existing.contact

    if "notes" in updates:
        updates["comment"] = updates["notes"] or ""

    updates["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [lead_id]

    with get_connection() as conn:
        conn.execute(f"UPDATE leads SET {set_clause} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return _row_to_lead(row)


def delete_lead(lead_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    return cursor.rowcount > 0


STATUS_LABELS = {
    "new": "Новый",
    "contacted": "Связались",
    "qualified": "Квалифицирован",
    "lost": "Потерян",
}


def get_dashboard_data() -> dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

        by_date_rows = conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
            FROM leads
            GROUP BY day
            ORDER BY day DESC
            LIMIT 30
            """
        ).fetchall()

        by_source_rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(source), ''), 'Не указан') AS source, COUNT(*) AS count
            FROM leads
            GROUP BY source
            ORDER BY count DESC, source ASC
            LIMIT 20
            """
        ).fetchall()

        by_status_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM leads
            GROUP BY status
            """
        ).fetchall()

    status_counts = {row["status"]: row["count"] for row in by_status_rows}

    return {
        "total": total,
        "by_date": [
            {
                "label": _format_dashboard_date(row["day"]),
                "count": row["count"],
            }
            for row in reversed(by_date_rows)
        ],
        "by_source": [
            {"label": row["source"], "count": row["count"]}
            for row in by_source_rows
        ],
        "by_status": [
            {
                "label": STATUS_LABELS[status],
                "count": status_counts.get(status, 0),
            }
            for status in ("new", "contacted", "qualified", "lost")
        ],
    }


def _format_dashboard_date(iso_day: str) -> str:
    year, month, day = iso_day.split("-")
    return f"{day}.{month}.{year}"
