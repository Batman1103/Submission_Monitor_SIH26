import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .sih_scraper import fetch_problem_statements

DATABASE_URL = os.getenv("DATABASE_URL")
SYNC_MINUTES = int(os.getenv("SIH_SYNC_MINUTES", "5"))
SOURCE_URL = "https://www.sih.gov.in/sih2026PS"

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required. Create a Neon PostgreSQL database and set DATABASE_URL.")

app = FastAPI(title="SIH 2026 Submission Monitor", version="2.0.0")

allowed_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

sync_state = {
    "status": "starting",
    "last_success": None,
    "last_error": None,
    "source": SOURCE_URL,
}
sync_lock = threading.Lock()


def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15)


def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS problem_statements (
            ps_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            organization TEXT,
            department TEXT,
            category TEXT NOT NULL CHECK (category IN ('Software', 'Hardware')),
            theme TEXT,
            submitted INTEGER NOT NULL DEFAULT 0,
            capacity INTEGER NOT NULL DEFAULT 500,
            deadline TEXT,
            description TEXT,
            updated_at TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE IF NOT EXISTS submission_history (
            id BIGSERIAL PRIMARY KEY,
            ps_id TEXT NOT NULL REFERENCES problem_statements(ps_id) ON DELETE CASCADE,
            submitted INTEGER NOT NULL,
            capacity INTEGER NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_submission_history_ps_time
        ON submission_history(ps_id, captured_at);

        CREATE INDEX IF NOT EXISTS idx_problem_statements_category_submitted
        ON problem_statements(category, submitted, ps_id);
        """)


def sync_now():
    if not sync_lock.acquire(blocking=False):
        return {"status": "busy"}

    try:
        sync_state["status"] = "syncing"
        records = fetch_problem_statements()
        if not records:
            raise RuntimeError("No problem statements were parsed from the official SIH page.")

        # Safety validation: the official SIH 2026 page currently contains
        # separate Software and Hardware categories. Reject malformed data
        # rather than silently publishing bad rankings.
        ids = [r["ps_id"] for r in records]
        if len(ids) != len(set(ids)):
            raise RuntimeError("Duplicate PS numbers detected in source data.")
        if any(r["category"] not in ("Software", "Hardware") for r in records):
            raise RuntimeError("Unexpected problem statement category detected.")
        if any(r["submitted"] < 0 or r["capacity"] <= 0 or r["submitted"] > r["capacity"] for r in records):
            raise RuntimeError("Invalid submission/capacity value detected.")

        now = datetime.now(timezone.utc)

        with db() as conn:
            for r in records:
                previous = conn.execute(
                    "SELECT submitted, capacity FROM problem_statements WHERE ps_id=%s",
                    (r["ps_id"],),
                ).fetchone()

                conn.execute("""
                    INSERT INTO problem_statements
                    (ps_id,title,organization,department,category,theme,submitted,capacity,deadline,description,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(ps_id) DO UPDATE SET
                      title=EXCLUDED.title,
                      organization=EXCLUDED.organization,
                      department=EXCLUDED.department,
                      category=EXCLUDED.category,
                      theme=EXCLUDED.theme,
                      submitted=EXCLUDED.submitted,
                      capacity=EXCLUDED.capacity,
                      deadline=EXCLUDED.deadline,
                      description=EXCLUDED.description,
                      updated_at=EXCLUDED.updated_at
                """, (
                    r["ps_id"], r["title"], r["organization"], r["department"],
                    r["category"], r["theme"], r["submitted"], r["capacity"],
                    r["deadline"], r["description"], now,
                ))

                # Keep history only when the count changes. This prevents a
                # 5-minute polling interval from creating thousands of duplicate
                # observations with identical submission counts.
                if previous is None or previous["submitted"] != r["submitted"] or previous["capacity"] != r["capacity"]:
                    conn.execute(
                        "INSERT INTO submission_history(ps_id,submitted,capacity,captured_at) VALUES (%s,%s,%s,%s)",
                        (r["ps_id"], r["submitted"], r["capacity"], now),
                    )

        now_iso = now.isoformat()
        sync_state["status"] = "live"
        sync_state["last_success"] = now_iso
        sync_state["last_error"] = None
        return {"status": "ok", "count": len(records), "last_success": now_iso}

    except Exception as exc:
        sync_state["status"] = "stale"
        sync_state["last_error"] = str(exc)
        return {"status": "error", "error": str(exc)}
    finally:
        sync_lock.release()


def sync_loop():
    while True:
        try:
            sync_now()
        except Exception:
            pass
        time.sleep(max(60, SYNC_MINUTES * 60))


@app.on_event("startup")
def startup():
    init_db()
    threading.Thread(target=sync_loop, daemon=True, name="sih-sync").start()


@app.get("/api/health")
def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "error", "database": "unavailable", "error": str(exc)}


@app.get("/api/system/status")
def system_status():
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM problem_statements").fetchone()["count"]
    return {**sync_state, "records": count, "sync_minutes": SYNC_MINUTES}


@app.post("/api/sync")
def manual_sync():
    return sync_now()


@app.get("/api/problem-statements")
def problem_statements(
    category: Optional[str] = None,
    search: Optional[str] = None,
    theme: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    clauses, params = [], []

    if category and category.lower() in ("software", "hardware"):
        clauses.append("LOWER(category)=%s")
        params.append(category.lower())
    if search:
        clauses.append("(LOWER(ps_id) LIKE %s OR LOWER(title) LIKE %s OR LOWER(organization) LIKE %s)")
        q = f"%{search.lower()}%"
        params.extend([q, q, q])
    if theme:
        clauses.append("theme=%s")
        params.append(theme)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    with db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS count FROM problem_statements{where}", params
        ).fetchone()["count"]
        rows = conn.execute(
            f"SELECT * FROM problem_statements{where} ORDER BY submitted ASC, ps_id ASC LIMIT %s OFFSET %s",
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows]}


@app.get("/api/rankings/{category}/{direction}")
def rankings(category: str, direction: str, limit: int = Query(10, ge=1, le=100)):
    category = category.capitalize()
    if category not in ("Software", "Hardware") or direction not in ("least", "most"):
        return {"items": []}

    order = "ASC" if direction == "least" else "DESC"
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM problem_statements WHERE category=%s ORDER BY submitted {order}, ps_id ASC LIMIT %s",
            (category, limit),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.get("/api/analytics/overview")
def overview():
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) AS count FROM problem_statements").fetchone()["count"]
        total_submissions = conn.execute("SELECT COALESCE(SUM(submitted),0) AS total FROM problem_statements").fetchone()["total"]
        result = {"total": total, "total_submissions": total_submissions}

        for cat in ("Software", "Hardware"):
            row = conn.execute(
                "SELECT COUNT(*) AS count, COALESCE(SUM(submitted),0) AS submissions, "
                "COALESCE(AVG(submitted),0) AS average, COALESCE(MIN(submitted),0) AS minimum, "
                "COALESCE(MAX(submitted),0) AS maximum FROM problem_statements WHERE category=%s",
                (cat,),
            ).fetchone()
            result[cat.lower()] = dict(row)
    return result


@app.get("/api/problem-statements/{ps_id}")
def problem_statement(ps_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM problem_statements WHERE ps_id=%s", (ps_id,)).fetchone()
        history = conn.execute(
            "SELECT submitted, capacity, captured_at FROM submission_history WHERE ps_id=%s ORDER BY captured_at ASC",
            (ps_id,),
        ).fetchall()

    if not row:
        return {"error": "Problem Statement not found"}
    return {"item": dict(row), "history": [dict(r) for r in history]}
