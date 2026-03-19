from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DATABASE_URL_ENV_KEYS = ("DATABASE_URL", "SHORTMAKER_DATABASE_URL")
PLACEHOLDER_DB_MARKERS = {"replace_me", "example", "example.com", "localhost/dbname"}


def _is_placeholder_database_url(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False

    lowered = normalized.lower()
    if any(marker in lowered for marker in PLACEHOLDER_DB_MARKERS):
        return True

    parsed = urlparse(normalized)
    host = (parsed.hostname or "").strip().lower()
    if host in {"replace_me", "example", "example.com"}:
        return True

    return False


def get_database_url() -> str:
    for key in DATABASE_URL_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            if _is_placeholder_database_url(value):
                logger.warning(
                    "%s is set to a placeholder value. Running without shared Postgres persistence.",
                    key,
                )
                continue
            return value
    return ""


def database_enabled() -> bool:
    return bool(get_database_url())


def _require_psycopg():
    try:
        import psycopg  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Database support requires psycopg. Install dependencies from requirements.txt."
        ) from exc
    return psycopg


@contextmanager
def get_connection() -> Iterator[Any]:
    psycopg = _require_psycopg()
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")

    connection = psycopg.connect(database_url)
    try:
        yield connection
    finally:
        connection.close()


def init_database() -> None:
    if not database_enabled():
        logger.info("DATABASE_URL is not configured. Running without shared Postgres persistence.")
        return

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS app_users (
                    clerk_user_id TEXT PRIMARY KEY,
                    email TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    image_url TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS processing_jobs (
                    job_id TEXT PRIMARY KEY,
                    clerk_user_id TEXT REFERENCES app_users(clerk_user_id) ON DELETE CASCADE,
                    source_type TEXT NOT NULL,
                    input_name TEXT NOT NULL,
                    num_clips INTEGER NOT NULL,
                    stage TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    results_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    ai_highlights_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_processing_jobs_owner_created
                ON processing_jobs (clerk_user_id, created_at DESC)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_processing_jobs_results_json
                ON processing_jobs USING GIN (results_json)
                """
            )
        conn.commit()


def upsert_user(user: dict[str, Any]) -> None:
    if not database_enabled():
        return

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_users (
                    clerk_user_id,
                    email,
                    first_name,
                    last_name,
                    image_url
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (clerk_user_id)
                DO UPDATE SET
                    email = EXCLUDED.email,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    image_url = EXCLUDED.image_url,
                    updated_at = NOW()
                """,
                (
                    user["id"],
                    user.get("email"),
                    user.get("first_name"),
                    user.get("last_name"),
                    user.get("image_url"),
                ),
            )
        conn.commit()


def create_job_record(
    *,
    job_id: str,
    clerk_user_id: str,
    source_type: str,
    input_name: str,
    num_clips: int,
    stage: str,
    progress: int,
    message: str,
) -> None:
    if not database_enabled():
        return

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO processing_jobs (
                    job_id,
                    clerk_user_id,
                    source_type,
                    input_name,
                    num_clips,
                    stage,
                    progress,
                    message
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_id)
                DO UPDATE SET
                    clerk_user_id = EXCLUDED.clerk_user_id,
                    source_type = EXCLUDED.source_type,
                    input_name = EXCLUDED.input_name,
                    num_clips = EXCLUDED.num_clips,
                    stage = EXCLUDED.stage,
                    progress = EXCLUDED.progress,
                    message = EXCLUDED.message,
                    updated_at = NOW()
                """,
                (job_id, clerk_user_id, source_type, input_name, num_clips, stage, progress, message),
            )
        conn.commit()


def sync_job_status(job_id: str, status_data: dict[str, Any]) -> None:
    if not database_enabled():
        return

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE processing_jobs
                SET
                    stage = %s,
                    progress = %s,
                    message = %s,
                    error = %s,
                    results_json = %s::jsonb,
                    ai_highlights_json = %s::jsonb,
                    completed_at = CASE
                        WHEN %s = 'complete' THEN NOW()
                        ELSE completed_at
                    END,
                    updated_at = NOW()
                WHERE job_id = %s
                """,
                (
                    status_data.get("stage") or status_data.get("status") or "unknown",
                    int(status_data.get("progress", 0) or 0),
                    status_data.get("message", ""),
                    status_data.get("error"),
                    json.dumps(status_data.get("results", []) or []),
                    json.dumps(status_data.get("ai_highlights", []) or []),
                    status_data.get("stage") or status_data.get("status") or "unknown",
                    job_id,
                ),
            )
        conn.commit()


def get_daily_usage(clerk_user_id: str, *, limit: int = 3) -> dict[str, int]:
    if not database_enabled():
        return {"limit": limit, "used": 0, "remaining": limit}

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM processing_jobs
                WHERE clerk_user_id = %s
                  AND created_at >= %s
                  AND created_at < %s
                """,
                (clerk_user_id, day_start, day_end),
            )
            row = cur.fetchone()

    used = int(row[0] if row else 0)
    remaining = max(0, limit - used)
    return {"limit": limit, "used": used, "remaining": remaining}


def get_job_ids_for_user(clerk_user_id: str, *, limit: int) -> list[str]:
    if not database_enabled():
        return []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id
                FROM processing_jobs
                WHERE clerk_user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (clerk_user_id, max(1, limit)),
            )
            rows = cur.fetchall()

    return [str(row[0]) for row in rows]


def get_job_owner(job_id: str) -> Optional[str]:
    if not database_enabled():
        return None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT clerk_user_id FROM processing_jobs WHERE job_id = %s",
                (job_id,),
            )
            row = cur.fetchone()
    return str(row[0]) if row and row[0] else None


def result_file_belongs_to_user(clerk_user_id: str, filename: str) -> bool:
    if not database_enabled():
        return False

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM processing_jobs
                WHERE clerk_user_id = %s
                  AND results_json @> %s::jsonb
                LIMIT 1
                """,
                (clerk_user_id, json.dumps([filename])),
            )
            return cur.fetchone() is not None
