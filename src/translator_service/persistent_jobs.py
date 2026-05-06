from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
from pathlib import Path
import sqlite3


class PersistentTranslationJobStatus(StrEnum):
    QUEUED = "queued"
    TRANSLATING = "translating"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    READY = "ready"


class PersistentWorkUnitStatus(StrEnum):
    PENDING = "pending"
    TRANSLATING = "translating"
    TRANSLATED = "translated"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    CACHED = "cached"


@dataclass(frozen=True)
class PersistentTranslationJob:
    id: str
    order_id: str
    user_id: str
    file_id: str
    source_object_key: str
    file_name: str
    document_kind: str
    source_language: str
    target_language: str
    adapter_version: str
    prompt_version: str
    pricing_snapshot_id: str
    partial_object_key: str | None
    final_object_key: str | None
    status: PersistentTranslationJobStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WorkUnitPlan:
    sequence: int
    source_block_ids: tuple[str, ...]
    source_text_hash: str
    prompt_tier: str
    source_language: str
    target_language: str
    source_object_key: str | None = None


@dataclass(frozen=True)
class PersistentWorkUnit:
    id: str
    job_id: str
    sequence: int
    source_block_ids: tuple[str, ...]
    source_object_key: str | None
    source_text_hash: str
    prompt_tier: str
    source_language: str
    target_language: str
    status: PersistentWorkUnitStatus
    translated_text: str | None
    worker_id: str | None
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    retry_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class JobUsageSummary:
    job_id: str
    translated_units: int
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    total_tokens: int


class SQLiteTranslationJobStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def create_job(
        self,
        *,
        order_id: str,
        user_id: str,
        file_id: str,
        file_name: str,
        document_kind: str,
        source_language: str,
        target_language: str,
        adapter_version: str,
        prompt_version: str,
        pricing_snapshot_id: str,
        source_object_key: str | None = None,
    ) -> PersistentTranslationJob:
        now = _now()
        job_id = self._next_job_id()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO translation_jobs (
                    id, order_id, user_id, file_id, file_name, document_kind,
                    source_object_key, source_language, target_language,
                    adapter_version,
                    prompt_version, pricing_snapshot_id, partial_object_key,
                    final_object_key, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                """,
                (
                    job_id,
                    order_id,
                    user_id,
                    file_id,
                    file_name,
                    document_kind,
                    source_object_key or file_id,
                    source_language,
                    target_language,
                    adapter_version,
                    prompt_version,
                    pricing_snapshot_id,
                    PersistentTranslationJobStatus.QUEUED.value,
                    _to_db_time(now),
                    _to_db_time(now),
                ),
            )
        return self.get_job(job_id)

    def attach_job_output(
        self,
        job_id: str,
        *,
        partial_object_key: str | None = None,
        final_object_key: str | None = None,
    ) -> PersistentTranslationJob:
        self._require_job(job_id)
        now = _now()
        if partial_object_key is None and final_object_key is None:
            return self._require_job(job_id)

        assignments = ["updated_at = ?"]
        values: list[str | None] = [_to_db_time(now)]
        if partial_object_key is not None:
            assignments.append("partial_object_key = ?")
            values.append(partial_object_key)
        if final_object_key is not None:
            assignments.append("final_object_key = ?")
            values.append(final_object_key)
        values.append(job_id)

        with self._connection:
            self._connection.execute(
                f"""
                UPDATE translation_jobs
                SET {", ".join(assignments)}
                WHERE id = ?
                """,
                tuple(values),
            )
        return self._require_job(job_id)

    def get_job(self, job_id: str) -> PersistentTranslationJob | None:
        row = self._connection.execute(
            "SELECT * FROM translation_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return _job_from_row(row)

    def add_work_units(
        self,
        job_id: str,
        work_units: list[WorkUnitPlan],
    ) -> list[PersistentWorkUnit]:
        self._require_job(job_id)
        now = _now()
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO work_units (
                    id, job_id, sequence, source_block_ids_json,
                    source_object_key, source_text_hash, prompt_tier, source_language,
                    target_language, status, prompt_tokens, completion_tokens,
                    cache_hit_tokens, cache_miss_tokens, retry_count,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, ?, ?)
                """,
                [
                    (
                        _work_unit_id(job_id, work_unit.sequence),
                        job_id,
                        work_unit.sequence,
                        json.dumps(list(work_unit.source_block_ids)),
                        work_unit.source_object_key,
                        work_unit.source_text_hash,
                        work_unit.prompt_tier,
                        work_unit.source_language,
                        work_unit.target_language,
                        PersistentWorkUnitStatus.PENDING.value,
                        _to_db_time(now),
                        _to_db_time(now),
                    )
                    for work_unit in work_units
                ],
            )
        return self.list_work_units(job_id)

    def list_work_units(self, job_id: str) -> list[PersistentWorkUnit]:
        rows = self._connection.execute(
            "SELECT * FROM work_units WHERE job_id = ? ORDER BY sequence",
            (job_id,),
        ).fetchall()
        return [_work_unit_from_row(row) for row in rows]

    def claim_next_work_unit(
        self,
        job_id: str,
        *,
        worker_id: str,
    ) -> PersistentWorkUnit | None:
        job = self._require_job(job_id)
        if job.status in {
            PersistentTranslationJobStatus.CANCELLED,
            PersistentTranslationJobStatus.FAILED,
            PersistentTranslationJobStatus.READY,
        }:
            return None

        active = self._connection.execute(
            """
            SELECT id FROM work_units
            WHERE job_id = ? AND status = ?
            LIMIT 1
            """,
            (job_id, PersistentWorkUnitStatus.TRANSLATING.value),
        ).fetchone()
        if active is not None:
            return None

        row = self._connection.execute(
            """
            SELECT * FROM work_units
            WHERE job_id = ? AND status = ?
            ORDER BY sequence
            LIMIT 1
            """,
            (job_id, PersistentWorkUnitStatus.PENDING.value),
        ).fetchone()
        if row is None:
            return None

        now = _now()
        unit_id = row["id"]
        with self._connection:
            self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, worker_id = ?, started_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    worker_id,
                    _to_db_time(now),
                    _to_db_time(now),
                    unit_id,
                ),
            )
            self._update_job_status(
                job_id,
                PersistentTranslationJobStatus.TRANSLATING,
                now=now,
            )
        return self._get_work_unit(unit_id)

    def complete_work_unit(
        self,
        work_unit_id: str,
        *,
        translated_text: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit_tokens: int,
        cache_miss_tokens: int,
    ) -> PersistentWorkUnit:
        work_unit = self._require_work_unit(work_unit_id)
        now = _now()
        with self._connection:
            self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, translated_text = ?, prompt_tokens = ?,
                    completion_tokens = ?, cache_hit_tokens = ?,
                    cache_miss_tokens = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    PersistentWorkUnitStatus.TRANSLATED.value,
                    translated_text,
                    prompt_tokens,
                    completion_tokens,
                    cache_hit_tokens,
                    cache_miss_tokens,
                    _to_db_time(now),
                    _to_db_time(now),
                    work_unit_id,
                ),
            )
            if self._job_has_no_unfinished_work(work_unit.job_id):
                self._update_job_status(
                    work_unit.job_id,
                    PersistentTranslationJobStatus.READY,
                    now=now,
                )
        return self._get_work_unit(work_unit_id)

    def fail_work_unit(
        self,
        work_unit_id: str,
        *,
        error_message: str,
        retry_count: int,
    ) -> PersistentWorkUnit:
        work_unit = self._require_work_unit(work_unit_id)
        now = _now()
        with self._connection:
            self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, last_error = ?, retry_count = ?,
                    worker_id = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    PersistentWorkUnitStatus.FAILED.value,
                    error_message,
                    retry_count,
                    _to_db_time(now),
                    work_unit_id,
                ),
            )
            self._update_job_status(
                work_unit.job_id,
                PersistentTranslationJobStatus.INTERRUPTED,
                now=now,
            )
        return self._get_work_unit(work_unit_id)

    def cancel_job(self, job_id: str) -> PersistentTranslationJob:
        self._require_job(job_id)
        now = _now()
        with self._connection:
            self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, worker_id = NULL, updated_at = ?
                WHERE job_id = ? AND status = ?
                """,
                (
                    PersistentWorkUnitStatus.PENDING.value,
                    _to_db_time(now),
                    job_id,
                    PersistentWorkUnitStatus.TRANSLATING.value,
                ),
            )
            self._update_job_status(
                job_id,
                PersistentTranslationJobStatus.CANCELLED,
                now=now,
            )
        return self._require_job(job_id)

    def resume_job(self, job_id: str) -> PersistentTranslationJob:
        job = self._require_job(job_id)
        if job.status is PersistentTranslationJobStatus.READY:
            return job

        now = _now()
        with self._connection:
            self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, worker_id = NULL, updated_at = ?
                WHERE job_id = ? AND status IN (?, ?)
                """,
                (
                    PersistentWorkUnitStatus.PENDING.value,
                    _to_db_time(now),
                    job_id,
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    PersistentWorkUnitStatus.FAILED.value,
                ),
            )
            self._update_job_status(
                job_id,
                PersistentTranslationJobStatus.QUEUED,
                now=now,
            )
        return self._require_job(job_id)

    def get_usage_summary(self, job_id: str) -> JobUsageSummary:
        self._require_job(job_id)
        row = self._connection.execute(
            """
            SELECT
                COUNT(*) AS translated_units,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(cache_hit_tokens), 0) AS cache_hit_tokens,
                COALESCE(SUM(cache_miss_tokens), 0) AS cache_miss_tokens
            FROM work_units
            WHERE job_id = ? AND status IN (?, ?)
            """,
            (
                job_id,
                PersistentWorkUnitStatus.TRANSLATED.value,
                PersistentWorkUnitStatus.CACHED.value,
            ),
        ).fetchone()
        prompt_tokens = row["prompt_tokens"]
        completion_tokens = row["completion_tokens"]
        return JobUsageSummary(
            job_id=job_id,
            translated_units=row["translated_units"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit_tokens=row["cache_hit_tokens"],
            cache_miss_tokens=row["cache_miss_tokens"],
            total_tokens=prompt_tokens + completion_tokens,
        )

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_jobs (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    source_object_key TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    document_kind TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    adapter_version TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    pricing_snapshot_id TEXT NOT NULL,
                    partial_object_key TEXT,
                    final_object_key TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS work_units (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    source_block_ids_json TEXT NOT NULL,
                    source_object_key TEXT,
                    source_text_hash TEXT NOT NULL,
                    prompt_tier TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    translated_text TEXT,
                    worker_id TEXT,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    UNIQUE(job_id, sequence),
                    FOREIGN KEY(job_id) REFERENCES translation_jobs(id)
                )
                """
            )

    def _next_job_id(self) -> str:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM translation_jobs"
        ).fetchone()
        return f"job-{row['count'] + 1}"

    def _require_job(self, job_id: str) -> PersistentTranslationJob:
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Translation job does not exist: {job_id}")
        return job

    def _get_work_unit(self, work_unit_id: str) -> PersistentWorkUnit | None:
        row = self._connection.execute(
            "SELECT * FROM work_units WHERE id = ?",
            (work_unit_id,),
        ).fetchone()
        if row is None:
            return None
        return _work_unit_from_row(row)

    def _require_work_unit(self, work_unit_id: str) -> PersistentWorkUnit:
        work_unit = self._get_work_unit(work_unit_id)
        if work_unit is None:
            raise ValueError(f"Work unit does not exist: {work_unit_id}")
        return work_unit

    def _job_has_no_unfinished_work(self, job_id: str) -> bool:
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS count FROM work_units
            WHERE job_id = ? AND status IN (?, ?, ?)
            """,
            (
                job_id,
                PersistentWorkUnitStatus.PENDING.value,
                PersistentWorkUnitStatus.TRANSLATING.value,
                PersistentWorkUnitStatus.FAILED.value,
            ),
        ).fetchone()
        return row["count"] == 0

    def _update_job_status(
        self,
        job_id: str,
        status: PersistentTranslationJobStatus,
        *,
        now: datetime,
    ) -> None:
        self._connection.execute(
            "UPDATE translation_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, _to_db_time(now), job_id),
        )


def _job_from_row(row: sqlite3.Row) -> PersistentTranslationJob:
    return PersistentTranslationJob(
        id=row["id"],
        order_id=row["order_id"],
        user_id=row["user_id"],
        file_id=row["file_id"],
        source_object_key=row["source_object_key"],
        file_name=row["file_name"],
        document_kind=row["document_kind"],
        source_language=row["source_language"],
        target_language=row["target_language"],
        adapter_version=row["adapter_version"],
        prompt_version=row["prompt_version"],
        pricing_snapshot_id=row["pricing_snapshot_id"],
        partial_object_key=row["partial_object_key"],
        final_object_key=row["final_object_key"],
        status=PersistentTranslationJobStatus(row["status"]),
        created_at=_from_db_time(row["created_at"]),
        updated_at=_from_db_time(row["updated_at"]),
    )


def _work_unit_from_row(row: sqlite3.Row) -> PersistentWorkUnit:
    return PersistentWorkUnit(
        id=row["id"],
        job_id=row["job_id"],
        sequence=row["sequence"],
        source_block_ids=tuple(json.loads(row["source_block_ids_json"])),
        source_object_key=row["source_object_key"],
        source_text_hash=row["source_text_hash"],
        prompt_tier=row["prompt_tier"],
        source_language=row["source_language"],
        target_language=row["target_language"],
        status=PersistentWorkUnitStatus(row["status"]),
        translated_text=row["translated_text"],
        worker_id=row["worker_id"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        cache_hit_tokens=row["cache_hit_tokens"],
        cache_miss_tokens=row["cache_miss_tokens"],
        retry_count=row["retry_count"],
        last_error=row["last_error"],
        created_at=_from_db_time(row["created_at"]),
        updated_at=_from_db_time(row["updated_at"]),
        started_at=_optional_db_time(row["started_at"]),
        completed_at=_optional_db_time(row["completed_at"]),
    )


def _work_unit_id(job_id: str, sequence: int) -> str:
    return f"{job_id}:unit-{sequence}"


def _now() -> datetime:
    return datetime.now(UTC)


def _to_db_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_db_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _optional_db_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    return _from_db_time(value)
