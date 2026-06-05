import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from translator_service.provider_failure_diagnostics import ProviderFailureDiagnostic
from translator_service.scheduler import (
    SCHEDULER_FAIR_QUEUE_POLICY,
    SchedulerClaim,
    SchedulerLimits,
    WorkUnitFailureKind,
    build_scheduler_queue_policy_diagnostics,
    calculate_retry_decision,
)


class PersistentTranslationJobStatus(StrEnum):
    QUEUED = "queued"
    TRANSLATING = "translating"
    ASSEMBLING = "assembling"
    PARTIAL = "partial"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    READY = "ready"
    EXPIRED = "expired"


class PersistentWorkUnitStatus(StrEnum):
    PENDING = "pending"
    TRANSLATING = "translating"
    TRANSLATED = "translated"
    FAILED = "failed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
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
    translation_policy: str | None
    partial_object_key: str | None
    final_object_key: str | None
    status: PersistentTranslationJobStatus
    priority: int
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
    claim_token: str | None
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    attempt_count: int
    max_attempts: int
    retry_count: int
    last_error: str | None
    available_at: datetime
    lease_until: datetime | None
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


@dataclass(frozen=True)
class PersistentWorkUnitAttempt:
    id: str
    work_unit_id: str
    job_id: str
    attempt_number: int
    worker_id: str | None
    claim_token: str | None
    status: str
    error_code: str | None
    error_message: str | None
    retry_after_seconds: int
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True)
class PersistentSchedulerEvent:
    id: str
    job_id: str
    work_unit_id: str | None
    event_type: str
    payload_json: str
    created_at: datetime


@dataclass(frozen=True)
class PersistentWorkerHeartbeat:
    worker_id: str
    worker_kind: str
    status: str
    active_job_id: str | None
    active_work_unit_id: str | None
    started_at: datetime
    last_seen_at: datetime


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
        translation_policy: str | None = None,
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
                    prompt_version, pricing_snapshot_id, translation_policy,
                    partial_object_key,
                    final_object_key, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
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
                    translation_policy,
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

    def mark_job_assembled(
        self,
        job_id: str,
        *,
        partial: bool,
    ) -> PersistentTranslationJob:
        status = (
            PersistentTranslationJobStatus.PARTIAL
            if partial
            else PersistentTranslationJobStatus.READY
        )
        with self._connection:
            self._update_job_status(job_id, status, now=_now())
        return self._require_job(job_id)

    def mark_job_interrupted(self, job_id: str) -> PersistentTranslationJob:
        with self._connection:
            self._update_job_status(
                job_id,
                PersistentTranslationJobStatus.INTERRUPTED,
                now=_now(),
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

    def delete_job(self, job_id: str) -> bool:
        if self.get_job(job_id) is None:
            return False

        with self._connection:
            self._connection.execute(
                "DELETE FROM work_unit_attempts WHERE job_id = ?",
                (job_id,),
            )
            self._connection.execute(
                "DELETE FROM scheduler_events WHERE job_id = ?",
                (job_id,),
            )
            self._connection.execute(
                "DELETE FROM work_units WHERE job_id = ?",
                (job_id,),
            )
            self._connection.execute(
                "DELETE FROM translation_jobs WHERE id = ?",
                (job_id,),
            )
        return True

    def list_jobs_by_status(
        self,
        status: PersistentTranslationJobStatus,
        *,
        limit: int = 50,
    ) -> list[PersistentTranslationJob]:
        rows = self._connection.execute(
            """
            SELECT * FROM translation_jobs
            WHERE status = ?
            ORDER BY datetime(updated_at), id
            LIMIT ?
            """,
            (status.value, max(1, limit)),
        ).fetchall()
        return [_job_from_row(row) for row in rows]

    def list_jobs_for_user(
        self,
        user_id: str,
        *,
        limit: int = 10,
    ) -> list[PersistentTranslationJob]:
        rows = self._connection.execute(
            """
            SELECT * FROM translation_jobs
            WHERE user_id = ?
            ORDER BY datetime(updated_at) DESC, id DESC
            LIMIT ?
            """,
            (user_id, max(1, limit)),
        ).fetchall()
        return [_job_from_row(row) for row in rows]

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

    def get_work_unit(self, work_unit_id: str) -> PersistentWorkUnit | None:
        return self._get_work_unit(work_unit_id)

    def claim_next_work_unit(
        self,
        job_id: str,
        *,
        worker_id: str,
        max_active_units_per_job: int = 1,
    ) -> PersistentWorkUnit | None:
        job = self._require_job(job_id)
        if job.status in {
            PersistentTranslationJobStatus.PAUSED,
            PersistentTranslationJobStatus.CANCELLED,
            PersistentTranslationJobStatus.FAILED,
            PersistentTranslationJobStatus.READY,
        }:
            return None

        active = self._connection.execute(
            """
            SELECT COUNT(*) AS count FROM work_units
            WHERE job_id = ? AND status = ?
            """,
            (job_id, PersistentWorkUnitStatus.TRANSLATING.value),
        ).fetchone()
        if active["count"] >= max(1, max_active_units_per_job):
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
                    cache_miss_tokens = ?, claim_token = NULL,
                    lease_until = NULL, worker_id = NULL,
                    completed_at = ?, updated_at = ?
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

    def claim_next_scheduled_work_unit(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        limits: SchedulerLimits,
    ) -> SchedulerClaim | None:
        now = _now()
        max_active_units_global = max(1, limits.max_active_units_global)
        max_active_units_per_job = max(1, limits.max_active_units_per_job)
        max_active_units_per_user = max(1, limits.max_active_units_per_user)
        max_active_jobs_per_user = max(1, limits.max_active_jobs_per_user)
        priority_aging_seconds = max(0, limits.priority_aging_seconds)
        active_global = self._connection.execute(
            """
            SELECT COUNT(*) AS count FROM work_units
            WHERE status = ?
            """,
            (PersistentWorkUnitStatus.TRANSLATING.value,),
        ).fetchone()
        if active_global["count"] >= max_active_units_global:
            return None

        row = self._connection.execute(
            """
            SELECT
              wu.*,
              (
                  SELECT COUNT(*)
                  FROM work_units active
                  JOIN translation_jobs active_tj ON active_tj.id = active.job_id
                  WHERE active_tj.user_id = tj.user_id
                    AND active.status = ?
              ) AS queue_policy_active_user_units,
              (
                  SELECT COUNT(DISTINCT active.job_id)
                  FROM work_units active
                  JOIN translation_jobs active_tj ON active_tj.id = active.job_id
                  WHERE active_tj.user_id = tj.user_id
                    AND active.status = ?
              ) AS queue_policy_active_user_jobs,
              (
                  SELECT COUNT(*)
                  FROM work_units active
                  WHERE active.job_id = wu.job_id
                    AND active.status = ?
              ) AS queue_policy_active_job_units
            FROM work_units wu
            JOIN translation_jobs tj ON tj.id = wu.job_id
            WHERE tj.status IN (?, ?)
              AND wu.status IN (?, ?, ?)
              AND (wu.available_at IS NULL OR datetime(wu.available_at) <= datetime(?))
              AND (wu.lease_until IS NULL OR datetime(wu.lease_until) <= datetime(?))
              AND (
                  SELECT COUNT(*)
                  FROM work_units active
                  WHERE active.job_id = wu.job_id
                    AND active.status = ?
              ) < ?
              AND (
                  SELECT COUNT(*)
                  FROM work_units active
                  JOIN translation_jobs active_tj ON active_tj.id = active.job_id
                  WHERE active_tj.user_id = tj.user_id
                    AND active.status = ?
              ) < ?
              AND (
                  SELECT COUNT(DISTINCT active.job_id)
                  FROM work_units active
                  JOIN translation_jobs active_tj ON active_tj.id = active.job_id
                  WHERE active_tj.user_id = tj.user_id
                    AND active.job_id <> wu.job_id
                    AND active.status = ?
              ) < ?
              AND NOT EXISTS (
                  SELECT 1 FROM work_units earlier
                  WHERE earlier.job_id = wu.job_id
                    AND earlier.sequence < wu.sequence
                    AND earlier.status IN (?, ?, ?)
              )
            ORDER BY
              (
                  SELECT COUNT(*)
                  FROM work_units active
                  JOIN translation_jobs active_tj ON active_tj.id = active.job_id
                  WHERE active_tj.user_id = tj.user_id
                    AND active.status = ?
              ) ASC,
              (
                  SELECT COUNT(DISTINCT active.job_id)
                  FROM work_units active
                  JOIN translation_jobs active_tj ON active_tj.id = active.job_id
                  WHERE active_tj.user_id = tj.user_id
                    AND active.status = ?
              ) ASC,
              (
                  SELECT COUNT(*)
                  FROM work_units active
                  WHERE active.job_id = wu.job_id
                    AND active.status = ?
              ) ASC,
              CASE
                WHEN ? > 0 THEN tj.priority + CAST(
                    ((julianday(?) - julianday(tj.created_at)) * 86400.0 / ?)
                    AS INTEGER
                )
                ELSE tj.priority
              END DESC,
              tj.priority DESC,
              datetime(tj.created_at) ASC,
              tj.id ASC,
              wu.sequence ASC,
              wu.id ASC
            LIMIT 1
            """,
            (
                PersistentWorkUnitStatus.TRANSLATING.value,
                PersistentWorkUnitStatus.TRANSLATING.value,
                PersistentWorkUnitStatus.TRANSLATING.value,
                PersistentTranslationJobStatus.QUEUED.value,
                PersistentTranslationJobStatus.TRANSLATING.value,
                PersistentWorkUnitStatus.PENDING.value,
                PersistentWorkUnitStatus.FAILED.value,
                PersistentWorkUnitStatus.FAILED_RETRYABLE.value,
                _to_db_time(now),
                _to_db_time(now),
                PersistentWorkUnitStatus.TRANSLATING.value,
                max_active_units_per_job,
                PersistentWorkUnitStatus.TRANSLATING.value,
                max_active_units_per_user,
                PersistentWorkUnitStatus.TRANSLATING.value,
                max_active_jobs_per_user,
                PersistentWorkUnitStatus.PENDING.value,
                PersistentWorkUnitStatus.FAILED.value,
                PersistentWorkUnitStatus.FAILED_RETRYABLE.value,
                PersistentWorkUnitStatus.TRANSLATING.value,
                PersistentWorkUnitStatus.TRANSLATING.value,
                PersistentWorkUnitStatus.TRANSLATING.value,
                priority_aging_seconds,
                _to_db_time(now),
                max(1, priority_aging_seconds),
            ),
        ).fetchone()
        if row is None:
            return None

        claim_token = uuid4().hex
        lease_until = now + timedelta(seconds=max(1, lease_seconds))
        now_text = _to_db_time(now)
        with self._connection:
            updated = self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, worker_id = ?, claim_token = ?,
                    lease_until = ?, attempt_count = attempt_count + 1,
                    started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ?
                  AND status IN (?, ?, ?)
                  AND (available_at IS NULL OR datetime(available_at) <= datetime(?))
                  AND (lease_until IS NULL OR datetime(lease_until) <= datetime(?))
                  AND (
                      SELECT COUNT(*)
                      FROM work_units active
                      WHERE active.status = ?
                  ) < ?
                  AND (
                      SELECT COUNT(*)
                      FROM work_units active
                      WHERE active.job_id = work_units.job_id
                        AND active.status = ?
                  ) < ?
                  AND (
                      SELECT COUNT(*)
                      FROM work_units active
                      JOIN translation_jobs active_tj
                        ON active_tj.id = active.job_id
                      WHERE active_tj.user_id = (
                          SELECT candidate_tj.user_id
                          FROM translation_jobs candidate_tj
                          WHERE candidate_tj.id = work_units.job_id
                      )
                        AND active.status = ?
                  ) < ?
                  AND (
                      SELECT COUNT(DISTINCT active.job_id)
                      FROM work_units active
                      JOIN translation_jobs active_tj
                        ON active_tj.id = active.job_id
                      WHERE active_tj.user_id = (
                          SELECT candidate_tj.user_id
                          FROM translation_jobs candidate_tj
                          WHERE candidate_tj.id = work_units.job_id
                      )
                        AND active.job_id <> work_units.job_id
                        AND active.status = ?
                  ) < ?
                  AND EXISTS (
                      SELECT 1 FROM translation_jobs tj
                      WHERE tj.id = work_units.job_id
                        AND tj.status IN (?, ?)
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM work_units earlier
                      WHERE earlier.job_id = work_units.job_id
                        AND earlier.sequence < work_units.sequence
                        AND earlier.status IN (?, ?, ?)
                  )
                """,
                (
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    worker_id,
                    claim_token,
                    _to_db_time(lease_until),
                    now_text,
                    now_text,
                    row["id"],
                    PersistentWorkUnitStatus.PENDING.value,
                    PersistentWorkUnitStatus.FAILED.value,
                    PersistentWorkUnitStatus.FAILED_RETRYABLE.value,
                    now_text,
                    now_text,
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    max_active_units_global,
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    max_active_units_per_job,
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    max_active_units_per_user,
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    max_active_jobs_per_user,
                    PersistentTranslationJobStatus.QUEUED.value,
                    PersistentTranslationJobStatus.TRANSLATING.value,
                    PersistentWorkUnitStatus.PENDING.value,
                    PersistentWorkUnitStatus.FAILED.value,
                    PersistentWorkUnitStatus.FAILED_RETRYABLE.value,
                ),
            )
            if updated.rowcount != 1:
                return None
            self._update_job_status(
                row["job_id"],
                PersistentTranslationJobStatus.TRANSLATING,
                now=now,
            )
            self._record_scheduler_event(
                job_id=row["job_id"],
                work_unit_id=row["id"],
                event_type="work_unit_claimed",
                payload={
                    "worker_id": worker_id,
                    "claim_token": claim_token,
                    "lease_until": _to_db_time(lease_until),
                    "queue_policy": SCHEDULER_FAIR_QUEUE_POLICY,
                    "queue_policy_diagnostics": build_scheduler_queue_policy_diagnostics(
                        active_user_units_before_claim=row[
                            "queue_policy_active_user_units"
                        ],
                        active_user_jobs_before_claim=row[
                            "queue_policy_active_user_jobs"
                        ],
                        active_job_units_before_claim=row[
                            "queue_policy_active_job_units"
                        ],
                        max_active_units_per_job=max_active_units_per_job,
                        max_active_units_per_user=max_active_units_per_user,
                        max_active_jobs_per_user=max_active_jobs_per_user,
                        priority_aging_seconds=priority_aging_seconds,
                    ),
                },
                now=now,
            )
        claimed = self._require_work_unit(row["id"])
        return SchedulerClaim(
            job_id=claimed.job_id,
            work_unit_id=claimed.id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_until=lease_until,
            attempt_number=claimed.attempt_count,
            source_object_key=claimed.source_object_key,
        )

    def complete_claimed_work_unit(
        self,
        *,
        work_unit_id: str,
        claim_token: str,
        translated_text: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit_tokens: int,
        cache_miss_tokens: int,
    ) -> PersistentWorkUnit:
        work_unit = self._require_work_unit(work_unit_id)
        now = _now()
        with self._connection:
            updated = self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, translated_text = ?, prompt_tokens = ?,
                    completion_tokens = ?, cache_hit_tokens = ?,
                    cache_miss_tokens = ?, claim_token = NULL,
                    lease_until = NULL, worker_id = NULL,
                    completed_at = ?, updated_at = ?
                WHERE id = ?
                  AND claim_token = ?
                  AND status = ?
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
                    claim_token,
                    PersistentWorkUnitStatus.TRANSLATING.value,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Stale work-unit claim: {work_unit_id}")
            completed = self._require_work_unit(work_unit_id)
            if self._job_has_no_unfinished_work(work_unit.job_id):
                self._update_job_status(
                    work_unit.job_id,
                    PersistentTranslationJobStatus.READY,
                    now=now,
                )
            job = self._require_job(completed.job_id)
            if (
                job.status is PersistentTranslationJobStatus.READY
                and job.final_object_key is None
            ):
                self._update_job_status(
                    completed.job_id,
                    PersistentTranslationJobStatus.ASSEMBLING,
                    now=now,
                )
            self._record_scheduler_event(
                job_id=completed.job_id,
                work_unit_id=work_unit_id,
                event_type="work_unit_completed",
                payload={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cache_hit_tokens": cache_hit_tokens,
                    "cache_miss_tokens": cache_miss_tokens,
                },
                now=now,
            )
        return self._require_work_unit(work_unit_id)

    def fail_claimed_work_unit(
        self,
        *,
        work_unit_id: str,
        claim_token: str,
        failure_kind: WorkUnitFailureKind,
        error_message: str,
        retry_base_delay_seconds: int,
        retry_max_delay_seconds: int,
        provider_failure_diagnostic: ProviderFailureDiagnostic | None = None,
    ) -> PersistentWorkUnit:
        work_unit = self._require_work_unit(work_unit_id)
        now = _now()
        decision = calculate_retry_decision(
            failure_kind=failure_kind,
            attempt_count=work_unit.attempt_count,
            max_attempts=work_unit.max_attempts,
            now=now,
            base_delay_seconds=retry_base_delay_seconds,
            max_delay_seconds=retry_max_delay_seconds,
        )
        retry_after_seconds = max(
            0,
            int((decision.available_at - now).total_seconds()),
        )
        safe_error_message = _attempt_error_message(
            error_message,
            provider_failure_diagnostic=provider_failure_diagnostic,
        )
        attempt_error_code = _attempt_error_code(
            failure_kind,
            provider_failure_diagnostic=provider_failure_diagnostic,
        )
        terminal_reason = _terminal_reason(
            failure_kind=failure_kind,
            retryable=decision.retryable,
            attempt_count=work_unit.attempt_count,
            max_attempts=work_unit.max_attempts,
        )
        with self._connection:
            updated = self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, last_error = ?, worker_id = NULL,
                    claim_token = NULL, lease_until = NULL, available_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND claim_token = ?
                  AND status = ?
                """,
                (
                    decision.next_status.value,
                    safe_error_message,
                    _to_db_time(decision.available_at),
                    _to_db_time(now),
                    work_unit_id,
                    claim_token,
                    PersistentWorkUnitStatus.TRANSLATING.value,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Stale work-unit claim: {work_unit_id}")
            self._insert_attempt(
                work_unit=work_unit,
                status=decision.next_status.value,
                error_code=attempt_error_code,
                error_message=safe_error_message,
                retry_after_seconds=retry_after_seconds,
                finished_at=now,
            )
            event_type = (
                "work_unit_retry_scheduled"
                if decision.retryable
                else "work_unit_failed_terminal"
            )
            self._record_scheduler_event(
                job_id=work_unit.job_id,
                work_unit_id=work_unit.id,
                event_type=event_type,
                payload={
                    "failure_kind": failure_kind.value,
                    "retry_after_seconds": retry_after_seconds,
                    "terminal_reason": terminal_reason,
                    **_provider_failure_event_payload(
                        provider_failure_diagnostic,
                        retry_after_seconds=retry_after_seconds,
                        terminal_reason=terminal_reason,
                        attempt_number=work_unit.attempt_count,
                    ),
                },
                now=now,
            )
            if decision.terminal_job_status is not None:
                self._update_job_status(
                    work_unit.job_id,
                    PersistentTranslationJobStatus.INTERRUPTED,
                    now=now,
                )
        return self._require_work_unit(work_unit_id)

    def recover_expired_leases(
        self,
        *,
        now: datetime,
        retry_base_delay_seconds: int,
        retry_max_delay_seconds: int,
    ) -> int:
        expired = self._connection.execute(
            """
            SELECT id FROM work_units
            WHERE status = ? AND lease_until IS NOT NULL
              AND datetime(lease_until) <= datetime(?)
            ORDER BY datetime(lease_until)
            """,
            (PersistentWorkUnitStatus.TRANSLATING.value, _to_db_time(now)),
        ).fetchall()
        for row in expired:
            work_unit = self._require_work_unit(row["id"])
            self.fail_claimed_work_unit(
                work_unit_id=work_unit.id,
                claim_token=work_unit.claim_token or "",
                failure_kind=WorkUnitFailureKind.LEASE_EXPIRED,
                error_message="work unit lease expired",
                retry_base_delay_seconds=retry_base_delay_seconds,
                retry_max_delay_seconds=retry_max_delay_seconds,
            )
        return len(expired)

    def list_work_unit_attempts(
        self,
        work_unit_id: str,
    ) -> list[PersistentWorkUnitAttempt]:
        rows = self._connection.execute(
            """
            SELECT * FROM work_unit_attempts
            WHERE work_unit_id = ?
            ORDER BY attempt_number, datetime(finished_at), id
            """,
            (work_unit_id,),
        ).fetchall()
        return [_work_unit_attempt_from_row(row) for row in rows]

    def list_scheduler_events(self, job_id: str) -> list[PersistentSchedulerEvent]:
        rows = self._connection.execute(
            """
            SELECT * FROM scheduler_events
            WHERE job_id = ?
            ORDER BY created_at, id
            """,
            (job_id,),
        ).fetchall()
        return [_scheduler_event_from_row(row) for row in rows]

    def record_worker_heartbeat(
        self,
        *,
        worker_id: str,
        worker_kind: str,
        status: str,
        active_job_id: str | None,
        active_work_unit_id: str | None,
    ) -> PersistentWorkerHeartbeat:
        now = _now()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO worker_heartbeats (
                    worker_id, worker_kind, status, active_job_id,
                    active_work_unit_id, started_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    worker_kind = excluded.worker_kind,
                    status = excluded.status,
                    active_job_id = excluded.active_job_id,
                    active_work_unit_id = excluded.active_work_unit_id,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    worker_id,
                    worker_kind,
                    status,
                    active_job_id,
                    active_work_unit_id,
                    _to_db_time(now),
                    _to_db_time(now),
                ),
            )
        heartbeat = self.get_worker_heartbeat(worker_id)
        if heartbeat is None:
            raise ValueError(f"Worker heartbeat was not stored: {worker_id}")
        return heartbeat

    def get_worker_heartbeat(
        self,
        worker_id: str,
    ) -> PersistentWorkerHeartbeat | None:
        row = self._connection.execute(
            "SELECT * FROM worker_heartbeats WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
        if row is None:
            return None
        return _worker_heartbeat_from_row(row)

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
                    worker_id = NULL, claim_token = NULL, lease_until = NULL,
                    updated_at = ?
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
                SET status = ?, worker_id = NULL, claim_token = NULL,
                    lease_until = NULL, updated_at = ?
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

    def pause_job(self, job_id: str) -> PersistentTranslationJob:
        self._require_job(job_id)
        now = _now()
        with self._connection:
            self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, worker_id = NULL, claim_token = NULL,
                    lease_until = NULL, updated_at = ?
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
                PersistentTranslationJobStatus.PAUSED,
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
                SET status = ?, worker_id = NULL, claim_token = NULL,
                    lease_until = NULL, updated_at = ?
                WHERE job_id = ? AND status IN (?, ?, ?)
                """,
                (
                    PersistentWorkUnitStatus.PENDING.value,
                    _to_db_time(now),
                    job_id,
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    PersistentWorkUnitStatus.FAILED.value,
                    PersistentWorkUnitStatus.FAILED_RETRYABLE.value,
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
                    translation_policy TEXT,
                    partial_object_key TEXT,
                    final_object_key TEXT,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            _ensure_column(
                self._connection,
                table_name="translation_jobs",
                column_name="translation_policy",
                definition="translation_policy TEXT",
            )
            _ensure_column(
                self._connection,
                table_name="translation_jobs",
                column_name="priority",
                definition="priority INTEGER NOT NULL DEFAULT 0",
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
                    claim_token TEXT,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    available_at TEXT,
                    lease_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    UNIQUE(job_id, sequence),
                    FOREIGN KEY(job_id) REFERENCES translation_jobs(id)
                )
                """
            )
            _ensure_column(
                self._connection,
                table_name="work_units",
                column_name="claim_token",
                definition="claim_token TEXT",
            )
            _ensure_column(
                self._connection,
                table_name="work_units",
                column_name="attempt_count",
                definition="attempt_count INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                self._connection,
                table_name="work_units",
                column_name="max_attempts",
                definition="max_attempts INTEGER NOT NULL DEFAULT 3",
            )
            _ensure_column(
                self._connection,
                table_name="work_units",
                column_name="available_at",
                definition="available_at TEXT",
            )
            _ensure_column(
                self._connection,
                table_name="work_units",
                column_name="lease_until",
                definition="lease_until TEXT",
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS work_unit_attempts (
                    id TEXT PRIMARY KEY,
                    work_unit_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    worker_id TEXT,
                    claim_token TEXT,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    retry_after_seconds INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    FOREIGN KEY(work_unit_id) REFERENCES work_units(id),
                    FOREIGN KEY(job_id) REFERENCES translation_jobs(id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduler_events (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    work_unit_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES translation_jobs(id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_heartbeats (
                    worker_id TEXT PRIMARY KEY,
                    worker_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active_job_id TEXT,
                    active_work_unit_id TEXT,
                    started_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
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
            WHERE job_id = ? AND status IN (?, ?, ?, ?)
            """,
            (
                job_id,
                PersistentWorkUnitStatus.PENDING.value,
                PersistentWorkUnitStatus.TRANSLATING.value,
                PersistentWorkUnitStatus.FAILED.value,
                PersistentWorkUnitStatus.FAILED_RETRYABLE.value,
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

    def _insert_attempt(
        self,
        *,
        work_unit: PersistentWorkUnit,
        status: str,
        error_code: str | None,
        error_message: str | None,
        retry_after_seconds: int,
        finished_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO work_unit_attempts (
                id, work_unit_id, job_id, attempt_number, worker_id, claim_token,
                status, error_code, error_message, retry_after_seconds,
                prompt_tokens, completion_tokens, cache_hit_tokens,
                cache_miss_tokens, started_at, finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"attempt-{uuid4().hex}",
                work_unit.id,
                work_unit.job_id,
                work_unit.attempt_count,
                work_unit.worker_id,
                work_unit.claim_token,
                status,
                error_code,
                error_message,
                retry_after_seconds,
                work_unit.prompt_tokens,
                work_unit.completion_tokens,
                work_unit.cache_hit_tokens,
                work_unit.cache_miss_tokens,
                _to_db_time(work_unit.started_at or finished_at),
                _to_db_time(finished_at),
            ),
        )

    def _record_scheduler_event(
        self,
        *,
        job_id: str,
        work_unit_id: str | None,
        event_type: str,
        payload: dict[str, object],
        now: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO scheduler_events (
                id, job_id, work_unit_id, event_type, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"event-{uuid4().hex}",
                job_id,
                work_unit_id,
                event_type,
                json.dumps(payload, sort_keys=True),
                _to_db_time(now),
            ),
        )


def _attempt_error_code(
    failure_kind: WorkUnitFailureKind,
    *,
    provider_failure_diagnostic: ProviderFailureDiagnostic | None,
) -> str:
    if provider_failure_diagnostic is not None:
        return provider_failure_diagnostic.failure_category.value
    return failure_kind.value


def _attempt_error_message(
    error_message: str,
    *,
    provider_failure_diagnostic: ProviderFailureDiagnostic | None,
) -> str:
    if provider_failure_diagnostic is not None:
        return (
            "provider failure: "
            f"{provider_failure_diagnostic.failure_category.value}"
        )
    return error_message


def _terminal_reason(
    *,
    failure_kind: WorkUnitFailureKind,
    retryable: bool,
    attempt_count: int,
    max_attempts: int,
) -> str | None:
    if retryable:
        return None
    if (
        failure_kind is WorkUnitFailureKind.RETRYABLE_PROVIDER
        and attempt_count >= max_attempts
    ):
        return "max_attempts_reached"
    return failure_kind.value


def _provider_failure_event_payload(
    provider_failure_diagnostic: ProviderFailureDiagnostic | None,
    *,
    retry_after_seconds: int,
    terminal_reason: str | None,
    attempt_number: int,
) -> dict[str, object]:
    if provider_failure_diagnostic is None:
        return {}
    return {
        "provider_failure": provider_failure_diagnostic.to_safe_payload(
            retry_after_seconds=retry_after_seconds,
            terminal_reason=terminal_reason,
            attempt_number=attempt_number,
        )
    }


def _job_from_mapping(row) -> PersistentTranslationJob:
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
        translation_policy=row["translation_policy"],
        partial_object_key=row["partial_object_key"],
        final_object_key=row["final_object_key"],
        status=PersistentTranslationJobStatus(row["status"]),
        priority=row["priority"],
        created_at=_from_db_time(row["created_at"]),
        updated_at=_from_db_time(row["updated_at"]),
    )


def _job_from_row(row: sqlite3.Row) -> PersistentTranslationJob:
    return _job_from_mapping(row)


def _work_unit_from_mapping(row) -> PersistentWorkUnit:
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
        claim_token=row["claim_token"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        cache_hit_tokens=row["cache_hit_tokens"],
        cache_miss_tokens=row["cache_miss_tokens"],
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        retry_count=row["retry_count"],
        last_error=row["last_error"],
        available_at=(
            _from_db_time(row["available_at"])
            if row["available_at"]
            else _from_db_time(row["created_at"])
        ),
        lease_until=(
            _from_db_time(row["lease_until"]) if row["lease_until"] else None
        ),
        created_at=_from_db_time(row["created_at"]),
        updated_at=_from_db_time(row["updated_at"]),
        started_at=_optional_db_time(row["started_at"]),
        completed_at=_optional_db_time(row["completed_at"]),
    )


def _work_unit_from_row(row: sqlite3.Row) -> PersistentWorkUnit:
    return _work_unit_from_mapping(row)


def _work_unit_attempt_from_row(row: sqlite3.Row) -> PersistentWorkUnitAttempt:
    return PersistentWorkUnitAttempt(
        id=row["id"],
        work_unit_id=row["work_unit_id"],
        job_id=row["job_id"],
        attempt_number=row["attempt_number"],
        worker_id=row["worker_id"],
        claim_token=row["claim_token"],
        status=row["status"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        retry_after_seconds=row["retry_after_seconds"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        cache_hit_tokens=row["cache_hit_tokens"],
        cache_miss_tokens=row["cache_miss_tokens"],
        started_at=_from_db_time(row["started_at"]),
        finished_at=_from_db_time(row["finished_at"]),
    )


def _scheduler_event_from_row(row: sqlite3.Row) -> PersistentSchedulerEvent:
    return PersistentSchedulerEvent(
        id=row["id"],
        job_id=row["job_id"],
        work_unit_id=row["work_unit_id"],
        event_type=row["event_type"],
        payload_json=row["payload_json"],
        created_at=_from_db_time(row["created_at"]),
    )


def _worker_heartbeat_from_row(row: sqlite3.Row) -> PersistentWorkerHeartbeat:
    return PersistentWorkerHeartbeat(
        worker_id=row["worker_id"],
        worker_kind=row["worker_kind"],
        status=row["status"],
        active_job_id=row["active_job_id"],
        active_work_unit_id=row["active_work_unit_id"],
        started_at=_from_db_time(row["started_at"]),
        last_seen_at=_from_db_time(row["last_seen_at"]),
    )


def _work_unit_id(job_id: str, sequence: int) -> str:
    return f"{job_id}:unit-{sequence}"


def _now() -> datetime:
    return datetime.now(UTC)


def _to_db_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _ensure_column(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name in columns:
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")


def _from_db_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _optional_db_time(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    return _from_db_time(value)
