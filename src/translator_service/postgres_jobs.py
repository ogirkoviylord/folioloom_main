import json
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row

from translator_service.persistent_jobs import (
    JobUsageSummary,
    PersistentTranslationJob,
    PersistentTranslationJobStatus,
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
    WorkUnitPlan,
)


class PostgreSQLTranslationJobStore:
    def __init__(self, dsn: str) -> None:
        self._connection = psycopg.connect(
            dsn,
            autocommit=True,
            row_factory=dict_row,
        )
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
        with self._connection.transaction():
            job_id = self._next_job_id()
            self._connection.execute(
                """
                INSERT INTO translation_jobs (
                    id, order_id, user_id, file_id, file_name, document_kind,
                    source_object_key, source_language, target_language,
                    adapter_version,
                    prompt_version, pricing_snapshot_id, partial_object_key,
                    final_object_key, status, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    NULL, NULL, %s, %s, %s
                )
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
                    now,
                    now,
                ),
            )
        return self._require_job(job_id)

    def attach_job_output(
        self,
        job_id: str,
        *,
        partial_object_key: str | None = None,
        final_object_key: str | None = None,
    ) -> PersistentTranslationJob:
        self._require_job(job_id)
        if partial_object_key is None and final_object_key is None:
            return self._require_job(job_id)

        now = _now()
        assignments = ["updated_at = %s"]
        values: list[object] = [now]
        if partial_object_key is not None:
            assignments.append("partial_object_key = %s")
            values.append(partial_object_key)
        if final_object_key is not None:
            assignments.append("final_object_key = %s")
            values.append(final_object_key)
        values.append(job_id)

        with self._connection.transaction():
            self._connection.execute(
                f"""
                UPDATE translation_jobs
                SET {", ".join(assignments)}
                WHERE id = %s
                """,
                values,
            )
        return self._require_job(job_id)

    def get_job(self, job_id: str) -> PersistentTranslationJob | None:
        row = self._connection.execute(
            "SELECT * FROM translation_jobs WHERE id = %s",
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
        with self._connection.transaction():
            self._connection.executemany(
                """
                INSERT INTO work_units (
                    id, job_id, sequence, source_block_ids_json,
                    source_object_key, source_text_hash, prompt_tier, source_language,
                    target_language, status, prompt_tokens, completion_tokens,
                    cache_hit_tokens, cache_miss_tokens, retry_count,
                    created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    0, 0, 0, 0, 0, %s, %s
                )
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
                        now,
                        now,
                    )
                    for work_unit in work_units
                ],
            )
        return self.list_work_units(job_id)

    def list_work_units(self, job_id: str) -> list[PersistentWorkUnit]:
        rows = self._connection.execute(
            "SELECT * FROM work_units WHERE job_id = %s ORDER BY sequence",
            (job_id,),
        ).fetchall()
        return [_work_unit_from_row(row) for row in rows]

    def claim_next_work_unit(
        self,
        job_id: str,
        *,
        worker_id: str,
    ) -> PersistentWorkUnit | None:
        now = _now()
        with self._connection.transaction():
            job_row = self._connection.execute(
                """
                SELECT * FROM translation_jobs
                WHERE id = %s
                FOR UPDATE
                """,
                (job_id,),
            ).fetchone()
            if job_row is None:
                raise ValueError(f"Translation job does not exist: {job_id}")

            job = _job_from_row(job_row)
            if job.status in {
                PersistentTranslationJobStatus.CANCELLED,
                PersistentTranslationJobStatus.FAILED,
                PersistentTranslationJobStatus.READY,
            }:
                return None

            active = self._connection.execute(
                """
                SELECT id FROM work_units
                WHERE job_id = %s AND status = %s
                LIMIT 1
                """,
                (job_id, PersistentWorkUnitStatus.TRANSLATING.value),
            ).fetchone()
            if active is not None:
                return None

            pending = self._connection.execute(
                """
                SELECT id
                FROM work_units
                WHERE job_id = %s AND status = %s
                ORDER BY sequence
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (job_id, PersistentWorkUnitStatus.PENDING.value),
            ).fetchone()
            if pending is None:
                return None

            unit_id = pending["id"]
            self._connection.execute(
                """
                UPDATE work_units
                SET status = %s, worker_id = %s, started_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    worker_id,
                    now,
                    now,
                    unit_id,
                ),
            )
            self._update_job_status(
                job_id,
                PersistentTranslationJobStatus.TRANSLATING,
                now=now,
            )
        return self._require_work_unit(unit_id)

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
        with self._connection.transaction():
            self._connection.execute(
                """
                UPDATE work_units
                SET status = %s, translated_text = %s, prompt_tokens = %s,
                    completion_tokens = %s, cache_hit_tokens = %s,
                    cache_miss_tokens = %s, completed_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    PersistentWorkUnitStatus.TRANSLATED.value,
                    translated_text,
                    prompt_tokens,
                    completion_tokens,
                    cache_hit_tokens,
                    cache_miss_tokens,
                    now,
                    now,
                    work_unit_id,
                ),
            )
            if self._job_has_no_unfinished_work(work_unit.job_id):
                self._update_job_status(
                    work_unit.job_id,
                    PersistentTranslationJobStatus.READY,
                    now=now,
                )
        return self._require_work_unit(work_unit_id)

    def fail_work_unit(
        self,
        work_unit_id: str,
        *,
        error_message: str,
        retry_count: int,
    ) -> PersistentWorkUnit:
        work_unit = self._require_work_unit(work_unit_id)
        now = _now()
        with self._connection.transaction():
            self._connection.execute(
                """
                UPDATE work_units
                SET status = %s, last_error = %s, retry_count = %s,
                    worker_id = NULL, updated_at = %s
                WHERE id = %s
                """,
                (
                    PersistentWorkUnitStatus.FAILED.value,
                    error_message,
                    retry_count,
                    now,
                    work_unit_id,
                ),
            )
            self._update_job_status(
                work_unit.job_id,
                PersistentTranslationJobStatus.INTERRUPTED,
                now=now,
            )
        return self._require_work_unit(work_unit_id)

    def cancel_job(self, job_id: str) -> PersistentTranslationJob:
        self._require_job(job_id)
        now = _now()
        with self._connection.transaction():
            self._connection.execute(
                """
                UPDATE work_units
                SET status = %s, worker_id = NULL, updated_at = %s
                WHERE job_id = %s AND status = %s
                """,
                (
                    PersistentWorkUnitStatus.PENDING.value,
                    now,
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
        with self._connection.transaction():
            self._connection.execute(
                """
                UPDATE work_units
                SET status = %s, worker_id = NULL, updated_at = %s
                WHERE job_id = %s AND status IN (%s, %s)
                """,
                (
                    PersistentWorkUnitStatus.PENDING.value,
                    now,
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
            WHERE job_id = %s AND status IN (%s, %s)
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

    def reset_schema_for_tests(self) -> None:
        with self._connection.transaction():
            self._connection.execute("DROP TABLE IF EXISTS work_units")
            self._connection.execute("DROP TABLE IF EXISTS translation_jobs")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection.transaction():
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
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS work_units (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES translation_jobs(id),
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
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    UNIQUE(job_id, sequence)
                )
                """
            )

    def _next_job_id(self) -> str:
        self._connection.execute("SELECT pg_advisory_xact_lock(41703001)")
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
            "SELECT * FROM work_units WHERE id = %s",
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
            WHERE job_id = %s AND status IN (%s, %s, %s)
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
            "UPDATE translation_jobs SET status = %s, updated_at = %s WHERE id = %s",
            (status.value, now, job_id),
        )


def _job_from_row(row: dict) -> PersistentTranslationJob:
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
        created_at=_db_time(row["created_at"]),
        updated_at=_db_time(row["updated_at"]),
    )


def _work_unit_from_row(row: dict) -> PersistentWorkUnit:
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
        created_at=_db_time(row["created_at"]),
        updated_at=_db_time(row["updated_at"]),
        started_at=_optional_db_time(row["started_at"]),
        completed_at=_optional_db_time(row["completed_at"]),
    )


def _work_unit_id(job_id: str, sequence: int) -> str:
    return f"{job_id}:unit-{sequence}"


def _now() -> datetime:
    return datetime.now(UTC)


def _db_time(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _optional_db_time(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    return _db_time(value)
