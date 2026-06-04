import json
from datetime import UTC, datetime
from uuid import uuid4

try:
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:  # pragma: no cover - exercised only without optional dep
    psycopg = None
    dict_row = None

from translator_service.persistent_jobs import (
    JobUsageSummary,
    PersistentSchedulerEvent,
    PersistentTranslationJob,
    PersistentTranslationJobStatus,
    PersistentWorkerHeartbeat,
    PersistentWorkUnit,
    PersistentWorkUnitAttempt,
    PersistentWorkUnitStatus,
    WorkUnitPlan,
    _attempt_error_code,
    _attempt_error_message,
    _job_from_mapping,
    _provider_failure_event_payload,
    _scheduler_event_from_row,
    _terminal_reason,
    _to_db_time,
    _work_unit_attempt_from_row,
    _work_unit_from_mapping,
    _worker_heartbeat_from_row,
)
from translator_service.provider_failure_diagnostics import ProviderFailureDiagnostic
from translator_service.scheduler import (
    SchedulerClaim,
    SchedulerLimits,
    WorkUnitFailureKind,
    calculate_retry_decision,
)

SCHEMA_SQL = """
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
    cancel_requested_at TIMESTAMPTZ,
    resume_blocked_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
    claim_token TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_until TIMESTAMPTZ,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE(job_id, sequence)
);

CREATE TABLE IF NOT EXISTS work_unit_attempts (
    id TEXT PRIMARY KEY,
    work_unit_id TEXT NOT NULL REFERENCES work_units(id),
    job_id TEXT NOT NULL REFERENCES translation_jobs(id),
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
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scheduler_events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES translation_jobs(id),
    work_unit_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    worker_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    active_job_id TEXT,
    active_work_unit_id TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def initialize_postgres_scheduler_schema(connection) -> None:
    with connection.transaction():
        for statement in SCHEMA_SQL.split(";"):
            statement = statement.strip()
            if statement:
                connection.execute(statement)


class PostgresSchedulerStore:
    def __init__(self, dsn: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required to use PostgresSchedulerStore")
        self.connection = psycopg.connect(
            dsn,
            autocommit=True,
            row_factory=dict_row,
        )

    def close(self) -> None:
        self.connection.close()

    def clear_for_tests(self) -> None:
        with self.connection.transaction():
            self.connection.execute("DELETE FROM scheduler_events")
            self.connection.execute("DELETE FROM work_unit_attempts")
            self.connection.execute("DELETE FROM worker_heartbeats")
            self.connection.execute("DELETE FROM work_units")
            self.connection.execute("DELETE FROM translation_jobs")

    def create_job(self, **kwargs) -> PersistentTranslationJob:
        with self.connection.transaction():
            row = self.connection.execute(
                """
                INSERT INTO translation_jobs (
                    id, order_id, user_id, file_id, file_name, document_kind,
                    source_object_key, source_language, target_language,
                    adapter_version, prompt_version, pricing_snapshot_id,
                    translation_policy, status
                )
                VALUES (
                    %(id)s, %(order_id)s, %(user_id)s, %(file_id)s, %(file_name)s,
                    %(document_kind)s, %(source_object_key)s, %(source_language)s,
                    %(target_language)s, %(adapter_version)s, %(prompt_version)s,
                    %(pricing_snapshot_id)s, %(translation_policy)s, %(status)s
                )
                RETURNING *
                """,
                {
                    **kwargs,
                    "id": f"job-{uuid4().hex}",
                    "source_object_key": kwargs.get("source_object_key")
                    or kwargs["file_id"],
                    "translation_policy": kwargs.get("translation_policy"),
                    "status": PersistentTranslationJobStatus.QUEUED.value,
                },
            ).fetchone()
        return _job_from_mapping(row)

    def get_job(self, job_id: str) -> PersistentTranslationJob | None:
        row = self.connection.execute(
            "SELECT * FROM translation_jobs WHERE id = %(job_id)s",
            {"job_id": job_id},
        ).fetchone()
        if row is None:
            return None
        return _job_from_mapping(row)

    def add_work_units(
        self,
        job_id: str,
        work_units: list[WorkUnitPlan],
    ) -> list[PersistentWorkUnit]:
        with self.connection.transaction():
            for work_unit in work_units:
                self.connection.execute(
                    """
                    INSERT INTO work_units (
                        id, job_id, sequence, source_block_ids_json,
                        source_object_key, source_text_hash, prompt_tier,
                        source_language, target_language, status
                    )
                    VALUES (
                        %(id)s, %(job_id)s, %(sequence)s,
                        %(source_block_ids_json)s, %(source_object_key)s,
                        %(source_text_hash)s, %(prompt_tier)s,
                        %(source_language)s, %(target_language)s, 'pending'
                    )
                    """,
                    {
                        "id": f"{job_id}:unit-{work_unit.sequence}",
                        "job_id": job_id,
                        "sequence": work_unit.sequence,
                        "source_block_ids_json": json.dumps(
                            list(work_unit.source_block_ids)
                        ),
                        "source_object_key": work_unit.source_object_key,
                        "source_text_hash": work_unit.source_text_hash,
                        "prompt_tier": work_unit.prompt_tier,
                        "source_language": work_unit.source_language,
                        "target_language": work_unit.target_language,
                    },
                )
        return self.list_work_units(job_id)

    def list_work_units(self, job_id: str) -> list[PersistentWorkUnit]:
        rows = self.connection.execute(
            """
            SELECT * FROM work_units
            WHERE job_id = %(job_id)s
            ORDER BY sequence
            """,
            {"job_id": job_id},
        ).fetchall()
        return [_work_unit_from_mapping(row) for row in rows]

    def get_work_unit(self, work_unit_id: str) -> PersistentWorkUnit | None:
        row = self.connection.execute(
            "SELECT * FROM work_units WHERE id = %(work_unit_id)s",
            {"work_unit_id": work_unit_id},
        ).fetchone()
        if row is None:
            return None
        return _work_unit_from_mapping(row)

    def claim_next_scheduled_work_unit(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        limits: SchedulerLimits,
    ) -> SchedulerClaim | None:
        max_active_units_global = max(1, limits.max_active_units_global)
        max_active_units_per_job = max(1, limits.max_active_units_per_job)
        max_active_units_per_user = max(1, limits.max_active_units_per_user)
        max_active_jobs_per_user = max(1, limits.max_active_jobs_per_user)
        priority_aging_seconds = max(0, limits.priority_aging_seconds)
        with self.connection.transaction():
            claim_token = uuid4().hex
            updated = self.connection.execute(
                """
                WITH claim_lock AS (
                    SELECT pg_advisory_xact_lock(
                        hashtext('translator_service.postgres_scheduler.claim')
                    )
                ),
                candidate AS (
                    SELECT wu.*
                    FROM work_units wu
                    JOIN translation_jobs tj ON tj.id = wu.job_id
                    CROSS JOIN claim_lock
                    WHERE tj.status IN ('queued', 'translating')
                      AND tj.cancel_requested_at IS NULL
                      AND wu.status IN ('pending', 'failed', 'failed_retryable')
                      AND wu.available_at <= now()
                      AND (wu.lease_until IS NULL OR wu.lease_until <= now())
                      AND (
                          SELECT COUNT(*)
                          FROM work_units active
                          WHERE active.status = 'translating'
                      ) < %(max_active_units_global)s
                      AND (
                          SELECT COUNT(*)
                          FROM work_units active
                          WHERE active.job_id = wu.job_id
                            AND active.status = 'translating'
                      ) < %(max_active_units_per_job)s
                      AND (
                          SELECT COUNT(*)
                          FROM work_units active
                          JOIN translation_jobs active_tj
                            ON active_tj.id = active.job_id
                          WHERE active_tj.user_id = tj.user_id
                            AND active.status = 'translating'
                      ) < %(max_active_units_per_user)s
                      AND (
                          SELECT COUNT(DISTINCT active.job_id)
                          FROM work_units active
                          JOIN translation_jobs active_tj
                            ON active_tj.id = active.job_id
                          WHERE active_tj.user_id = tj.user_id
                            AND active.job_id <> wu.job_id
                            AND active.status = 'translating'
                      ) < %(max_active_jobs_per_user)s
                      AND NOT EXISTS (
                          SELECT 1
                          FROM work_units earlier
                          WHERE earlier.job_id = wu.job_id
                            AND earlier.sequence < wu.sequence
                            AND earlier.status IN (
                                'pending',
                                'failed',
                                'failed_retryable'
                            )
                      )
                    ORDER BY
                      (
                          SELECT COUNT(*)
                          FROM work_units active
                          JOIN translation_jobs active_tj
                            ON active_tj.id = active.job_id
                          WHERE active_tj.user_id = tj.user_id
                            AND active.status = 'translating'
                      ) ASC,
                      (
                          SELECT COUNT(DISTINCT active.job_id)
                          FROM work_units active
                          JOIN translation_jobs active_tj
                            ON active_tj.id = active.job_id
                          WHERE active_tj.user_id = tj.user_id
                            AND active.status = 'translating'
                      ) ASC,
                      (
                          SELECT COUNT(*)
                          FROM work_units active
                          WHERE active.job_id = wu.job_id
                            AND active.status = 'translating'
                      ) ASC,
                      CASE
                        WHEN %(priority_aging_seconds)s > 0 THEN
                          tj.priority + FLOOR(
                            EXTRACT(EPOCH FROM (now() - tj.created_at))
                            / GREATEST(%(priority_aging_seconds)s, 1)
                          )::integer
                        ELSE tj.priority
                      END DESC,
                      tj.priority DESC,
                      tj.created_at ASC,
                      wu.sequence ASC
                    FOR UPDATE OF wu SKIP LOCKED
                    LIMIT 1
                )
                UPDATE work_units
                SET status = 'translating',
                    worker_id = %(worker_id)s,
                    claim_token = %(claim_token)s,
                    lease_until = now() + (%(lease_seconds)s || ' seconds')::interval,
                    attempt_count = work_units.attempt_count + 1,
                    started_at = COALESCE(work_units.started_at, now()),
                    updated_at = now()
                FROM candidate
                WHERE work_units.id = candidate.id
                  AND work_units.status IN ('pending', 'failed', 'failed_retryable')
                  AND work_units.available_at <= now()
                  AND (
                      work_units.lease_until IS NULL
                      OR work_units.lease_until <= now()
                  )
                  AND (
                      SELECT COUNT(*)
                      FROM work_units active
                      WHERE active.status = 'translating'
                  ) < %(max_active_units_global)s
                  AND (
                      SELECT COUNT(*)
                      FROM work_units active
                      WHERE active.job_id = work_units.job_id
                        AND active.status = 'translating'
                  ) < %(max_active_units_per_job)s
                  AND (
                      SELECT COUNT(*)
                      FROM work_units active
                      JOIN translation_jobs active_tj
                        ON active_tj.id = active.job_id
                      JOIN translation_jobs candidate_tj
                        ON candidate_tj.id = work_units.job_id
                      WHERE active_tj.user_id = candidate_tj.user_id
                        AND active.status = 'translating'
                  ) < %(max_active_units_per_user)s
                  AND (
                      SELECT COUNT(DISTINCT active.job_id)
                      FROM work_units active
                      JOIN translation_jobs active_tj
                        ON active_tj.id = active.job_id
                      JOIN translation_jobs candidate_tj
                        ON candidate_tj.id = work_units.job_id
                      WHERE active_tj.user_id = candidate_tj.user_id
                        AND active.job_id <> work_units.job_id
                        AND active.status = 'translating'
                  ) < %(max_active_jobs_per_user)s
                  AND EXISTS (
                      SELECT 1
                      FROM translation_jobs tj
                      WHERE tj.id = work_units.job_id
                        AND tj.status IN ('queued', 'translating')
                        AND tj.cancel_requested_at IS NULL
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM work_units earlier
                      WHERE earlier.job_id = work_units.job_id
                        AND earlier.sequence < work_units.sequence
                        AND earlier.status IN (
                            'pending',
                            'failed',
                            'failed_retryable'
                        )
                  )
                RETURNING work_units.*
                """,
                {
                    "worker_id": worker_id,
                    "claim_token": claim_token,
                    "lease_seconds": max(1, lease_seconds),
                    "max_active_units_global": max_active_units_global,
                    "max_active_units_per_job": max_active_units_per_job,
                    "max_active_units_per_user": max_active_units_per_user,
                    "max_active_jobs_per_user": max_active_jobs_per_user,
                    "priority_aging_seconds": priority_aging_seconds,
                },
            ).fetchone()
            if updated is None:
                return None
            self.connection.execute(
                """
                UPDATE translation_jobs
                SET status = 'translating', updated_at = now()
                WHERE id = %(job_id)s
                """,
                {"job_id": updated["job_id"]},
            )
            self._record_scheduler_event(
                job_id=updated["job_id"],
                work_unit_id=updated["id"],
                event_type="work_unit_claimed",
                payload={
                    "worker_id": worker_id,
                    "claim_token": claim_token,
                    "lease_until": _to_db_time(updated["lease_until"]),
                },
                now=_now(),
            )
        return SchedulerClaim(
            job_id=updated["job_id"],
            work_unit_id=updated["id"],
            worker_id=worker_id,
            claim_token=claim_token,
            lease_until=updated["lease_until"],
            attempt_number=updated["attempt_count"],
            source_object_key=updated["source_object_key"],
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
        now = _now()
        with self.connection.transaction():
            completed_row = self.connection.execute(
                """
                UPDATE work_units
                SET status = 'translated',
                    translated_text = %(translated_text)s,
                    prompt_tokens = %(prompt_tokens)s,
                    completion_tokens = %(completion_tokens)s,
                    cache_hit_tokens = %(cache_hit_tokens)s,
                    cache_miss_tokens = %(cache_miss_tokens)s,
                    worker_id = NULL,
                    claim_token = NULL,
                    lease_until = NULL,
                    completed_at = %(now)s,
                    updated_at = %(now)s
                WHERE id = %(work_unit_id)s
                  AND claim_token = %(claim_token)s
                  AND status = 'translating'
                RETURNING *
                """,
                {
                    "work_unit_id": work_unit_id,
                    "claim_token": claim_token,
                    "translated_text": translated_text,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cache_hit_tokens": cache_hit_tokens,
                    "cache_miss_tokens": cache_miss_tokens,
                    "now": now,
                },
            ).fetchone()
            if completed_row is None:
                raise ValueError(f"Stale work-unit claim: {work_unit_id}")

            if self._job_has_no_unfinished_work(completed_row["job_id"]):
                job = self._require_job(completed_row["job_id"])
                next_status = (
                    PersistentTranslationJobStatus.READY
                    if job.final_object_key
                    else PersistentTranslationJobStatus.ASSEMBLING
                )
                self._update_job_status(completed_row["job_id"], next_status, now=now)

            self._record_scheduler_event(
                job_id=completed_row["job_id"],
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
        now = _now()
        with self.connection.transaction():
            work_unit_row = self.connection.execute(
                """
                SELECT *
                FROM work_units
                WHERE id = %(work_unit_id)s
                  AND claim_token = %(claim_token)s
                  AND status = 'translating'
                FOR UPDATE
                """,
                {"work_unit_id": work_unit_id, "claim_token": claim_token},
            ).fetchone()
            if work_unit_row is None:
                raise ValueError(f"Stale work-unit claim: {work_unit_id}")

            work_unit = _work_unit_from_mapping(work_unit_row)
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
            updated_row = self.connection.execute(
                """
                UPDATE work_units
                SET status = %(status)s,
                    last_error = %(error_message)s,
                    worker_id = NULL,
                    claim_token = NULL,
                    lease_until = NULL,
                    available_at = %(available_at)s,
                    updated_at = %(now)s
                WHERE id = %(work_unit_id)s
                  AND claim_token = %(claim_token)s
                  AND status = 'translating'
                RETURNING *
                """,
                {
                    "status": decision.next_status.value,
                    "error_message": safe_error_message,
                    "available_at": decision.available_at,
                    "now": now,
                    "work_unit_id": work_unit_id,
                    "claim_token": claim_token,
                },
            ).fetchone()
            if updated_row is None:
                raise ValueError(f"Stale work-unit claim: {work_unit_id}")

            self._insert_attempt(
                work_unit=work_unit,
                status=decision.next_status.value,
                error_code=attempt_error_code,
                error_message=safe_error_message,
                retry_after_seconds=retry_after_seconds,
                finished_at=now,
            )
            self._record_scheduler_event(
                job_id=work_unit.job_id,
                work_unit_id=work_unit.id,
                event_type=(
                    "work_unit_retry_scheduled"
                    if decision.retryable
                    else "work_unit_failed_terminal"
                ),
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

        assignments = ["updated_at = %(now)s"]
        values = {
            "job_id": job_id,
            "now": _now(),
            "partial_object_key": partial_object_key,
            "final_object_key": final_object_key,
        }
        if partial_object_key is not None:
            assignments.append("partial_object_key = %(partial_object_key)s")
        if final_object_key is not None:
            assignments.append("final_object_key = %(final_object_key)s")

        with self.connection.transaction():
            self.connection.execute(
                f"""
                UPDATE translation_jobs
                SET {", ".join(assignments)}
                WHERE id = %(job_id)s
                """,
                values,
            )
        return self._require_job(job_id)

    def list_jobs_by_status(
        self,
        status: PersistentTranslationJobStatus,
        *,
        limit: int = 50,
    ) -> list[PersistentTranslationJob]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM translation_jobs
            WHERE status = %(status)s
            ORDER BY updated_at, id
            LIMIT %(limit)s
            """,
            {"status": status.value, "limit": max(1, limit)},
        ).fetchall()
        return [_job_from_mapping(row) for row in rows]

    def list_jobs_for_user(
        self,
        user_id: str,
        *,
        limit: int = 10,
    ) -> list[PersistentTranslationJob]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM translation_jobs
            WHERE user_id = %(user_id)s
            ORDER BY updated_at DESC, id DESC
            LIMIT %(limit)s
            """,
            {"user_id": user_id, "limit": max(1, limit)},
        ).fetchall()
        return [_job_from_mapping(row) for row in rows]

    def delete_job(self, job_id: str) -> bool:
        if self.get_job(job_id) is None:
            return False
        with self.connection.transaction():
            self.connection.execute(
                "DELETE FROM work_unit_attempts WHERE job_id = %(job_id)s",
                {"job_id": job_id},
            )
            self.connection.execute(
                "DELETE FROM scheduler_events WHERE job_id = %(job_id)s",
                {"job_id": job_id},
            )
            self.connection.execute(
                "DELETE FROM work_units WHERE job_id = %(job_id)s",
                {"job_id": job_id},
            )
            self.connection.execute(
                "DELETE FROM translation_jobs WHERE id = %(job_id)s",
                {"job_id": job_id},
            )
        return True

    def cancel_job(self, job_id: str) -> PersistentTranslationJob:
        self._require_job(job_id)
        now = _now()
        with self.connection.transaction():
            self.connection.execute(
                """
                UPDATE work_units
                SET status = %(pending)s,
                    worker_id = NULL,
                    claim_token = NULL,
                    lease_until = NULL,
                    updated_at = %(now)s
                WHERE job_id = %(job_id)s AND status = %(translating)s
                """,
                {
                    "pending": PersistentWorkUnitStatus.PENDING.value,
                    "translating": PersistentWorkUnitStatus.TRANSLATING.value,
                    "job_id": job_id,
                    "now": now,
                },
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
        with self.connection.transaction():
            self.connection.execute(
                """
                UPDATE work_units
                SET status = %(pending)s,
                    worker_id = NULL,
                    claim_token = NULL,
                    lease_until = NULL,
                    updated_at = %(now)s
                WHERE job_id = %(job_id)s AND status = %(translating)s
                """,
                {
                    "pending": PersistentWorkUnitStatus.PENDING.value,
                    "translating": PersistentWorkUnitStatus.TRANSLATING.value,
                    "job_id": job_id,
                    "now": now,
                },
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
        with self.connection.transaction():
            self.connection.execute(
                """
                UPDATE work_units
                SET status = %(pending)s,
                    worker_id = NULL,
                    claim_token = NULL,
                    lease_until = NULL,
                    updated_at = %(now)s
                WHERE job_id = %(job_id)s
                  AND status IN (
                    %(translating)s,
                    %(failed)s,
                    %(failed_retryable)s
                  )
                """,
                {
                    "pending": PersistentWorkUnitStatus.PENDING.value,
                    "translating": PersistentWorkUnitStatus.TRANSLATING.value,
                    "failed": PersistentWorkUnitStatus.FAILED.value,
                    "failed_retryable": (
                        PersistentWorkUnitStatus.FAILED_RETRYABLE.value
                    ),
                    "job_id": job_id,
                    "now": now,
                },
            )
            self._update_job_status(
                job_id,
                PersistentTranslationJobStatus.QUEUED,
                now=now,
            )
        return self._require_job(job_id)

    def mark_job_interrupted(self, job_id: str) -> PersistentTranslationJob:
        with self.connection.transaction():
            self._update_job_status(
                job_id,
                PersistentTranslationJobStatus.INTERRUPTED,
                now=_now(),
            )
        return self._require_job(job_id)

    def get_usage_summary(self, job_id: str) -> JobUsageSummary:
        self._require_job(job_id)
        row = self.connection.execute(
            """
            SELECT
                COUNT(*) AS translated_units,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(cache_hit_tokens), 0) AS cache_hit_tokens,
                COALESCE(SUM(cache_miss_tokens), 0) AS cache_miss_tokens
            FROM work_units
            WHERE job_id = %(job_id)s
              AND status IN (%(translated)s, %(cached)s)
            """,
            {
                "job_id": job_id,
                "translated": PersistentWorkUnitStatus.TRANSLATED.value,
                "cached": PersistentWorkUnitStatus.CACHED.value,
            },
        ).fetchone()
        prompt_tokens = int(row["prompt_tokens"])
        completion_tokens = int(row["completion_tokens"])
        return JobUsageSummary(
            job_id=job_id,
            translated_units=int(row["translated_units"]),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit_tokens=int(row["cache_hit_tokens"]),
            cache_miss_tokens=int(row["cache_miss_tokens"]),
            total_tokens=prompt_tokens + completion_tokens,
        )

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
        with self.connection.transaction():
            self._update_job_status(job_id, status, now=_now())
        return self._require_job(job_id)

    def list_work_unit_attempts(
        self,
        work_unit_id: str,
    ) -> list[PersistentWorkUnitAttempt]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM work_unit_attempts
            WHERE work_unit_id = %(work_unit_id)s
            ORDER BY attempt_number, finished_at, id
            """,
            {"work_unit_id": work_unit_id},
        ).fetchall()
        return [_work_unit_attempt_from_row(row) for row in rows]

    def list_scheduler_events(self, job_id: str) -> list[PersistentSchedulerEvent]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM scheduler_events
            WHERE job_id = %(job_id)s
            ORDER BY created_at, id
            """,
            {"job_id": job_id},
        ).fetchall()
        return [_scheduler_event_from_row(row) for row in rows]

    def recover_expired_leases(
        self,
        *,
        now: datetime,
        retry_base_delay_seconds: int,
        retry_max_delay_seconds: int,
    ) -> int:
        with self.connection.transaction():
            expired_rows = self.connection.execute(
                """
                SELECT id, claim_token
                FROM work_units
                WHERE status = 'translating'
                  AND lease_until IS NOT NULL
                  AND lease_until <= %(now)s
                ORDER BY lease_until, id
                FOR UPDATE SKIP LOCKED
                """,
                {"now": now},
            ).fetchall()
            for row in expired_rows:
                try:
                    self.fail_claimed_work_unit(
                        work_unit_id=row["id"],
                        claim_token=row["claim_token"],
                        failure_kind=WorkUnitFailureKind.LEASE_EXPIRED,
                        error_message="work unit lease expired",
                        retry_base_delay_seconds=retry_base_delay_seconds,
                        retry_max_delay_seconds=retry_max_delay_seconds,
                    )
                except ValueError:
                    continue
        return len(expired_rows)

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
        with self.connection.transaction():
            self.connection.execute(
                """
                INSERT INTO worker_heartbeats (
                    worker_id, worker_kind, status, active_job_id,
                    active_work_unit_id, started_at, last_seen_at
                )
                VALUES (
                    %(worker_id)s, %(worker_kind)s, %(status)s,
                    %(active_job_id)s, %(active_work_unit_id)s, %(now)s, %(now)s
                )
                ON CONFLICT(worker_id) DO UPDATE SET
                    worker_kind = excluded.worker_kind,
                    status = excluded.status,
                    active_job_id = excluded.active_job_id,
                    active_work_unit_id = excluded.active_work_unit_id,
                    last_seen_at = excluded.last_seen_at
                """,
                {
                    "worker_id": worker_id,
                    "worker_kind": worker_kind,
                    "status": status,
                    "active_job_id": active_job_id,
                    "active_work_unit_id": active_work_unit_id,
                    "now": now,
                },
            )
        heartbeat = self.get_worker_heartbeat(worker_id)
        if heartbeat is None:
            raise ValueError(f"Worker heartbeat was not stored: {worker_id}")
        return heartbeat

    def get_worker_heartbeat(
        self,
        worker_id: str,
    ) -> PersistentWorkerHeartbeat | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM worker_heartbeats
            WHERE worker_id = %(worker_id)s
            """,
            {"worker_id": worker_id},
        ).fetchone()
        if row is None:
            return None
        return _worker_heartbeat_from_row(row)

    def _require_job(self, job_id: str) -> PersistentTranslationJob:
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Translation job does not exist: {job_id}")
        return job

    def _require_work_unit(self, work_unit_id: str) -> PersistentWorkUnit:
        work_unit = self.get_work_unit(work_unit_id)
        if work_unit is None:
            raise ValueError(f"Work unit does not exist: {work_unit_id}")
        return work_unit

    def _job_has_no_unfinished_work(self, job_id: str) -> bool:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM work_units
            WHERE job_id = %(job_id)s
              AND status IN (
                  %(pending)s,
                  %(translating)s,
                  %(failed)s,
                  %(failed_retryable)s
              )
            """,
            {
                "job_id": job_id,
                "pending": PersistentWorkUnitStatus.PENDING.value,
                "translating": PersistentWorkUnitStatus.TRANSLATING.value,
                "failed": PersistentWorkUnitStatus.FAILED.value,
                "failed_retryable": PersistentWorkUnitStatus.FAILED_RETRYABLE.value,
            },
        ).fetchone()
        return row["count"] == 0

    def _update_job_status(
        self,
        job_id: str,
        status: PersistentTranslationJobStatus,
        *,
        now: datetime,
    ) -> None:
        self.connection.execute(
            """
            UPDATE translation_jobs
            SET status = %(status)s, updated_at = %(now)s
            WHERE id = %(job_id)s
            """,
            {"status": status.value, "now": now, "job_id": job_id},
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
        self.connection.execute(
            """
            INSERT INTO work_unit_attempts (
                id, work_unit_id, job_id, attempt_number, worker_id, claim_token,
                status, error_code, error_message, retry_after_seconds,
                prompt_tokens, completion_tokens, cache_hit_tokens,
                cache_miss_tokens, started_at, finished_at
            )
            VALUES (
                %(id)s, %(work_unit_id)s, %(job_id)s, %(attempt_number)s,
                %(worker_id)s, %(claim_token)s, %(status)s, %(error_code)s,
                %(error_message)s, %(retry_after_seconds)s, %(prompt_tokens)s,
                %(completion_tokens)s, %(cache_hit_tokens)s, %(cache_miss_tokens)s,
                %(started_at)s, %(finished_at)s
            )
            """,
            {
                "id": f"attempt-{uuid4().hex}",
                "work_unit_id": work_unit.id,
                "job_id": work_unit.job_id,
                "attempt_number": work_unit.attempt_count,
                "worker_id": work_unit.worker_id,
                "claim_token": work_unit.claim_token,
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "retry_after_seconds": retry_after_seconds,
                "prompt_tokens": work_unit.prompt_tokens,
                "completion_tokens": work_unit.completion_tokens,
                "cache_hit_tokens": work_unit.cache_hit_tokens,
                "cache_miss_tokens": work_unit.cache_miss_tokens,
                "started_at": work_unit.started_at or finished_at,
                "finished_at": finished_at,
            },
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
        self.connection.execute(
            """
            INSERT INTO scheduler_events (
                id, job_id, work_unit_id, event_type, payload_json, created_at
            )
            VALUES (
                %(id)s, %(job_id)s, %(work_unit_id)s, %(event_type)s,
                %(payload_json)s, %(created_at)s
            )
            """,
            {
                "id": f"event-{uuid4().hex}",
                "job_id": job_id,
                "work_unit_id": work_unit_id,
                "event_type": event_type,
                "payload_json": json.dumps(payload, sort_keys=True),
                "created_at": now,
            },
        )


def _now() -> datetime:
    return datetime.now(UTC)
