import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

try:
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:  # pragma: no cover - exercised only without optional dep
    psycopg = None
    dict_row = None

from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_BINDING_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    ApprovedGlossarySnapshot,
    DeleteJobResult,
    GlossaryApproval,
    JobUsageSummary,
    PersistentSchedulerEvent,
    PersistentTranslationJob,
    PersistentTranslationJobStatus,
    PersistentWorkerHeartbeat,
    PersistentWorkUnit,
    PersistentWorkUnitAttempt,
    PersistentWorkUnitStatus,
    StrictAdmissionResult,
    StrictDocxAdmissionRequest,
    StrictDocxV3AdmissionRequest,
    StrictDocxV3Authorization,
    WorkUnitPlan,
    _attempt_error_code,
    _attempt_error_message,
    _glossary_approval_from_row,
    _job_from_mapping,
    _provider_failure_event_payload,
    _scheduler_event_from_row,
    _strict_admission_validation_error,
    _strict_approval_denial_code,
    _strict_bound_glossary_snapshot_from_row,
    _strict_v3_admission_validation_error,
    _terminal_reason,
    _to_db_time,
    _work_unit_attempt_from_row,
    _work_unit_from_mapping,
    _worker_heartbeat_from_row,
)
from translator_service.provider_failure_diagnostics import ProviderFailureDiagnostic
from translator_service.scheduler import (
    SCHEDULER_FAIR_QUEUE_POLICY,
    ProviderCapacityCap,
    ProviderCapacityDiagnostics,
    ProviderSlot,
    ProviderSlotLease,
    ProviderSlotLeaseStatus,
    SchedulerBackpressureDiagnostics,
    SchedulerClaim,
    SchedulerLimits,
    WorkUnitFailureKind,
    build_provider_capacity_diagnostics,
    build_scheduler_backpressure_diagnostics,
    build_scheduler_queue_policy_diagnostics,
    calculate_retry_decision,
)

_PROVIDER_SLOT_RELEASE_REASONS = {
    "cancelled",
    "completed",
    "lease_expired",
    "released",
    "retryable_failure",
    "terminal_failure",
    "worker_shutdown",
}

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

CREATE TABLE IF NOT EXISTS provider_slots (
    provider_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    slot_index INTEGER NOT NULL,
    capacity_source TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(provider_id, channel_id, slot_index),
    CHECK (slot_index >= 0)
);

CREATE TABLE IF NOT EXISTS provider_slot_leases (
    id TEXT PRIMARY KEY,
    lease_token TEXT NOT NULL UNIQUE,
    provider_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    slot_index INTEGER NOT NULL,
    job_id TEXT NOT NULL REFERENCES translation_jobs(id),
    work_unit_id TEXT NOT NULL REFERENCES work_units(id),
    worker_id TEXT NOT NULL,
    work_unit_claim_token TEXT NOT NULL,
    status TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_until TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ,
    release_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY(provider_id, channel_id, slot_index)
        REFERENCES provider_slots(provider_id, channel_id, slot_index),
    CHECK (status IN ('active', 'released', 'expired'))
);

CREATE UNIQUE INDEX IF NOT EXISTS provider_slot_leases_active_slot_idx
    ON provider_slot_leases(provider_id, channel_id, slot_index)
    WHERE status = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS provider_slot_leases_active_work_unit_idx
    ON provider_slot_leases(work_unit_id)
    WHERE status = 'active';
"""

_CLAIM_ADVISORY_LOCK_KEY = "translator_service.postgres_scheduler.claim"

_STRICT_DOCX_CLAIM_GUARD_SQL = """
      AND NOT EXISTS (
          SELECT 1
          FROM strict_job_glossary_bindings binding
          LEFT JOIN glossary_approvals approval
            ON approval.approval_id = binding.approval_id
          LEFT JOIN glossary_snapshot_custody custody
            ON custody.custody_id = binding.custody_id
          WHERE binding.job_id = {job_id_reference}
            AND (
                approval.approval_id IS NULL
                OR custody.custody_id IS NULL
                OR approval.approval_status IS DISTINCT FROM 'approved'
                OR approval.custody_id IS DISTINCT FROM binding.custody_id
                OR approval.snapshot_digest IS DISTINCT FROM binding.snapshot_digest
                OR custody.snapshot_digest IS DISTINCT FROM binding.snapshot_digest
                OR approval.approval_schema_version IS DISTINCT FROM {approval_schema}
                OR binding.binding_schema_version IS DISTINCT FROM {binding_schema}
                OR custody.snapshot_schema_version IS DISTINCT FROM {snapshot_schema}
                OR custody.retention_mode IS DISTINCT FROM 'retain'
            )
      )
      AND NOT EXISTS (
          SELECT 1
          FROM strict_docx_v3_job_authorizations binding
          LEFT JOIN strict_docx_v3_authorizations authorization
            ON authorization.authorization_id = binding.authorization_id
          LEFT JOIN glossary_approvals approval
            ON approval.approval_id = binding.approval_id
          LEFT JOIN strict_docx_v3_document_custody custody
            ON custody.document_custody_id = binding.document_custody_id
          LEFT JOIN translation_jobs job
            ON job.id = binding.job_id
          WHERE binding.job_id = {job_id_reference}
            AND (
                authorization.authorization_id IS NULL
                OR approval.approval_id IS NULL
                OR custody.document_custody_id IS NULL
                OR job.id IS NULL
                OR authorization.authorization_status IS DISTINCT FROM 'approved'
                OR approval.approval_status IS DISTINCT FROM 'approved'
                OR authorization.approval_id IS DISTINCT FROM binding.approval_id
                OR authorization.document_custody_id
                    IS DISTINCT FROM binding.document_custody_id
                OR authorization.snapshot_digest
                    IS DISTINCT FROM binding.snapshot_digest
                OR approval.snapshot_digest IS DISTINCT FROM binding.snapshot_digest
                OR custody.source_object_key IS DISTINCT FROM binding.source_object_key
                OR custody.source_sha256 IS DISTINCT FROM binding.source_sha256
                OR custody.source_size_bytes IS DISTINCT FROM binding.source_size_bytes
                OR custody.document_kind IS DISTINCT FROM 'docx'
                OR job.document_kind IS DISTINCT FROM 'docx'
                OR job.source_object_key IS DISTINCT FROM binding.source_object_key
            )
      )
"""

_STRICT_DOCX_CANDIDATE_CLAIM_GUARD_SQL = _STRICT_DOCX_CLAIM_GUARD_SQL.format(
    job_id_reference="wu.job_id",
    approval_schema=GLOSSARY_APPROVAL_SCHEMA_VERSION,
    binding_schema=GLOSSARY_BINDING_SCHEMA_VERSION,
    snapshot_schema=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
)

_STRICT_DOCX_UPDATE_CLAIM_GUARD_SQL = _STRICT_DOCX_CLAIM_GUARD_SQL.format(
    job_id_reference="work_units.job_id",
    approval_schema=GLOSSARY_APPROVAL_SCHEMA_VERSION,
    binding_schema=GLOSSARY_BINDING_SCHEMA_VERSION,
    snapshot_schema=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
)

_CLAIM_PERFORMANCE_INDEX_STATEMENT_TEMPLATES = (
    """
    {create_index} IF NOT EXISTS translation_jobs_scheduler_claim_idx
        ON translation_jobs(status, id, user_id, created_at, priority)
        WHERE status IN ('queued', 'translating')
          AND cancel_requested_at IS NULL
    """,
    """
    {create_index} IF NOT EXISTS work_units_scheduler_waiting_order_idx
        ON work_units(job_id, sequence, id)
        WHERE status IN ('pending', 'failed', 'failed_retryable')
    """,
    """
    {create_index} IF NOT EXISTS work_units_scheduler_active_job_idx
        ON work_units(job_id, id)
        WHERE status = 'translating'
    """,
)

_CLAIM_NEXT_SCHEDULED_WORK_UNIT_SQL = f"""
WITH claim_lock AS (
    SELECT pg_advisory_xact_lock(
          hashtext(%(claim_lock_key)s)
    )
),
active_work AS (
    SELECT
      active.job_id,
      active_tj.user_id,
      COUNT(*)::integer AS active_job_units
    FROM claim_lock
    JOIN work_units active
      ON active.status = 'translating'
    JOIN translation_jobs active_tj
      ON active_tj.id = active.job_id
    GROUP BY active.job_id, active_tj.user_id
),
active_by_user AS (
    SELECT
      user_id,
      COALESCE(SUM(active_job_units), 0)::integer AS active_user_units,
      COUNT(*)::integer AS active_user_jobs
    FROM active_work
    GROUP BY user_id
),
active_global AS (
    SELECT COALESCE(SUM(active_job_units), 0)::integer AS active_units
    FROM active_work
),
active_jobs AS (
    SELECT
      tj.id,
      tj.user_id,
      tj.priority,
      tj.created_at
    FROM claim_lock
    JOIN translation_jobs tj
      ON tj.status IN ('queued', 'translating')
     AND tj.cancel_requested_at IS NULL
),
first_waiting_work_units AS (
    SELECT
      active_jobs.id AS job_id,
      active_jobs.user_id,
      active_jobs.priority,
      active_jobs.created_at,
      first_wu.id AS work_unit_id
    FROM active_jobs
    JOIN LATERAL (
        SELECT wu.id
        FROM work_units wu
        WHERE wu.job_id = active_jobs.id
          AND wu.status IN ('pending', 'failed', 'failed_retryable')
        ORDER BY wu.sequence ASC, wu.id ASC
        LIMIT 1
    ) first_wu ON TRUE
),
candidate AS (
    SELECT
      wu.*,
      COALESCE(abu.active_user_units, 0)::integer
        AS queue_policy_active_user_units,
      COALESCE(abu.active_user_jobs, 0)::integer
        AS queue_policy_active_user_jobs,
      COALESCE(aw.active_job_units, 0)::integer
        AS queue_policy_active_job_units,
      active_global.active_units
        AS queue_policy_active_global_units,
      first_wu.priority AS queue_policy_job_priority,
      first_wu.created_at AS queue_policy_job_created_at
    FROM first_waiting_work_units first_wu
    JOIN work_units wu
      ON wu.id = first_wu.work_unit_id
    LEFT JOIN active_work aw
      ON aw.job_id = wu.job_id
    LEFT JOIN active_by_user abu
      ON abu.user_id = first_wu.user_id
    CROSS JOIN active_global
    WHERE wu.status IN ('pending', 'failed', 'failed_retryable')
      AND wu.available_at <= now()
      AND (wu.lease_until IS NULL OR wu.lease_until <= now())
{_STRICT_DOCX_CANDIDATE_CLAIM_GUARD_SQL}
      AND active_global.active_units < %(max_active_units_global)s
      AND COALESCE(aw.active_job_units, 0) < %(max_active_units_per_job)s
      AND COALESCE(abu.active_user_units, 0) < %(max_active_units_per_user)s
      AND (
          COALESCE(abu.active_user_jobs, 0)
          - CASE
              WHEN COALESCE(aw.active_job_units, 0) > 0 THEN 1
              ELSE 0
            END
      ) < %(max_active_jobs_per_user)s
    ORDER BY
      COALESCE(abu.active_user_units, 0) ASC,
      COALESCE(abu.active_user_jobs, 0) ASC,
      COALESCE(aw.active_job_units, 0) ASC,
      CASE
        WHEN %(priority_aging_seconds)s > 0 THEN
          first_wu.priority + FLOOR(
            EXTRACT(EPOCH FROM (now() - first_wu.created_at))
            / GREATEST(%(priority_aging_seconds)s, 1)
          )::integer
        ELSE first_wu.priority
      END DESC,
      first_wu.priority DESC,
      first_wu.created_at ASC,
      first_wu.job_id ASC,
      wu.sequence ASC,
      wu.id ASC
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
{_STRICT_DOCX_UPDATE_CLAIM_GUARD_SQL}
  AND candidate.queue_policy_active_global_units < %(max_active_units_global)s
  AND candidate.queue_policy_active_job_units < %(max_active_units_per_job)s
  AND candidate.queue_policy_active_user_units < %(max_active_units_per_user)s
  AND (
      candidate.queue_policy_active_user_jobs
      - CASE
          WHEN candidate.queue_policy_active_job_units > 0 THEN 1
          ELSE 0
        END
  ) < %(max_active_jobs_per_user)s
  AND EXISTS (
      SELECT 1
      FROM translation_jobs tj
      WHERE tj.id = work_units.job_id
        AND tj.status IN ('queued', 'translating')
        AND tj.cancel_requested_at IS NULL
  )
RETURNING
    work_units.*,
    candidate.queue_policy_active_user_units,
    candidate.queue_policy_active_user_jobs,
    candidate.queue_policy_active_job_units
"""


def initialize_postgres_scheduler_schema(connection) -> None:
    with connection.transaction():
        for statement in SCHEMA_SQL.split(";"):
            statement = statement.strip()
            if statement:
                connection.execute(statement)


def postgres_scheduler_claim_performance_index_statements(
    *,
    concurrently: bool = True,
) -> tuple[str, ...]:
    create_index = "CREATE INDEX CONCURRENTLY" if concurrently else "CREATE INDEX"
    return tuple(
        template.format(create_index=create_index).strip()
        for template in _CLAIM_PERFORMANCE_INDEX_STATEMENT_TEMPLATES
    )


def create_postgres_scheduler_claim_performance_indexes(
    connection,
    *,
    concurrently: bool = True,
) -> None:
    statements = postgres_scheduler_claim_performance_index_statements(
        concurrently=concurrently,
    )
    if concurrently:
        for statement in statements:
            connection.execute(statement)
        return
    with connection.transaction():
        for statement in statements:
            connection.execute(statement)


class PostgresSchedulerStore:
    strict_docx_migration_ready = False
    document_glossary_authoring_migration_ready = False
    document_glossary_lock_attestation_migration_ready = False

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

    def attest_document_glossary_lock(self, *, document_custody_id: str, actor):
        from translator_service.document_glossary_lock_attestation import (
            _attest_postgres_document_glossary_lock,
        )

        return _attest_postgres_document_glossary_lock(self, document_custody_id, actor)

    def read_document_glossary_lock_status(self, *, document_custody_id: str, actor):
        from translator_service.document_glossary_lock_attestation import (
            _read_postgres_document_glossary_lock_status,
        )

        return _read_postgres_document_glossary_lock_status(
            self, document_custody_id, actor
        )

    def create_glossary_approval(
        self,
        *,
        snapshot_payload: bytes,
        snapshot_digest: str,
        snapshot_schema_version: int,
        approval_schema_version: int,
    ) -> GlossaryApproval:
        if (
            not snapshot_payload
            or sha256(snapshot_payload).hexdigest() != snapshot_digest
        ):
            raise ValueError("Invalid glossary snapshot payload")
        if (
            snapshot_schema_version != GLOSSARY_SNAPSHOT_SCHEMA_VERSION
            or approval_schema_version != GLOSSARY_APPROVAL_SCHEMA_VERSION
        ):
            raise ValueError("Unsupported glossary schema version")

        custody_id = f"custody-{uuid4().hex}"
        approval_id = f"approval-{uuid4().hex}"
        with self.connection.transaction():
            custody = self.connection.execute(
                """
                INSERT INTO glossary_snapshot_custody (
                    custody_id, snapshot_payload, snapshot_digest,
                    snapshot_schema_version, retention_mode
                ) VALUES (
                    %(custody_id)s, %(snapshot_payload)s, %(snapshot_digest)s,
                    %(snapshot_schema_version)s, 'retain'
                )
                ON CONFLICT (snapshot_digest) DO UPDATE
                SET snapshot_digest = EXCLUDED.snapshot_digest
                RETURNING custody_id
                """,
                {
                    "custody_id": custody_id,
                    "snapshot_payload": snapshot_payload,
                    "snapshot_digest": snapshot_digest,
                    "snapshot_schema_version": snapshot_schema_version,
                },
            ).fetchone()
            custody_id = custody["custody_id"]
            row = self.connection.execute(
                """
                INSERT INTO glossary_approvals (
                    approval_id, custody_id, snapshot_digest,
                    approval_schema_version, approval_status
                ) VALUES (
                    %(approval_id)s, %(custody_id)s, %(snapshot_digest)s,
                    %(approval_schema_version)s, 'approved'
                )
                ON CONFLICT (custody_id, snapshot_digest, approval_schema_version)
                DO UPDATE SET custody_id = EXCLUDED.custody_id
                RETURNING *
                """,
                {
                    "approval_id": approval_id,
                    "custody_id": custody_id,
                    "snapshot_digest": snapshot_digest,
                    "approval_schema_version": approval_schema_version,
                },
            ).fetchone()
        return _glossary_approval_from_row(
            {**row, "snapshot_schema_version": snapshot_schema_version}
        )

    def revoke_glossary_approval(self, *, approval_id: str) -> GlossaryApproval:
        with self.connection.transaction():
            self._acquire_claim_serialization_lock()
            row = self.connection.execute(
                """
                UPDATE glossary_approvals
                SET approval_status = 'revoked', revoked_at = now()
                WHERE approval_id = %(approval_id)s
                RETURNING *
                """,
                {"approval_id": approval_id},
            ).fetchone()
        if row is None:
            raise ValueError("Glossary approval does not exist")
        return _glossary_approval_from_row(
            {
                **row,
                "snapshot_schema_version": GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            }
        )

    def read_approved_glossary_snapshot(
        self,
        *,
        approval_id: str,
    ) -> ApprovedGlossarySnapshot | None:
        row = self.connection.execute(
            """
            SELECT ga.*, gsc.snapshot_payload, gsc.snapshot_schema_version,
                   gsc.retention_mode,
                   gsc.snapshot_digest AS custody_snapshot_digest
            FROM glossary_approvals ga
            JOIN glossary_snapshot_custody gsc ON gsc.custody_id = ga.custody_id
            WHERE ga.approval_id = %(approval_id)s
            """,
            {"approval_id": approval_id},
        ).fetchone()
        if (
            row is None
            or row["approval_status"] != "approved"
            or row["retention_mode"] != "retain"
            or row["snapshot_digest"] != row["custody_snapshot_digest"]
            or row["approval_schema_version"] != GLOSSARY_APPROVAL_SCHEMA_VERSION
            or row["snapshot_schema_version"] != GLOSSARY_SNAPSHOT_SCHEMA_VERSION
        ):
            return None
        snapshot_payload = bytes(row["snapshot_payload"])
        if sha256(snapshot_payload).hexdigest() != row["snapshot_digest"]:
            return None
        return ApprovedGlossarySnapshot(
            approval=_glossary_approval_from_row(row),
            snapshot_payload=snapshot_payload,
        )

    def read_strict_job_glossary_snapshot(
        self,
        *,
        job_id: str,
    ) -> ApprovedGlossarySnapshot | None:
        row = self.connection.execute(
            """
            SELECT binding.approval_id AS binding_approval_id,
                   binding.custody_id AS binding_custody_id,
                   binding.snapshot_digest AS binding_snapshot_digest,
                   binding.binding_schema_version,
                   approval.*, custody.snapshot_payload,
                   custody.snapshot_schema_version, custody.retention_mode,
                   custody.snapshot_digest AS custody_snapshot_digest,
                   job.document_kind
            FROM strict_job_glossary_bindings binding
            JOIN translation_jobs job ON job.id = binding.job_id
            JOIN glossary_approvals approval
              ON approval.approval_id = binding.approval_id
            JOIN glossary_snapshot_custody custody
              ON custody.custody_id = binding.custody_id
            WHERE binding.job_id = %(job_id)s
            """,
            {"job_id": job_id},
        ).fetchone()
        return _strict_bound_glossary_snapshot_from_row(row)

    def admit_strict_docx_job(
        self,
        request: StrictDocxAdmissionRequest,
    ) -> StrictAdmissionResult:
        denial_code = _strict_admission_validation_error(request)
        if denial_code is not None:
            return StrictAdmissionResult(None, [], denial_code)
        with self.connection.transaction():
            approval = self.connection.execute(
                """
                SELECT ga.*, gsc.snapshot_schema_version,
                       gsc.snapshot_digest AS custody_snapshot_digest,
                       gsc.retention_mode
                FROM glossary_approvals ga
                LEFT JOIN glossary_snapshot_custody gsc
                  ON gsc.custody_id = ga.custody_id
                WHERE ga.approval_id = %(approval_id)s
                FOR UPDATE
                """,
                {"approval_id": request.approval_id},
            ).fetchone()
            denial_code = _strict_approval_denial_code(approval, request)
            if denial_code is not None:
                return StrictAdmissionResult(None, [], denial_code)
            job_id = f"job-{uuid4().hex}"
            job_row = self.connection.execute(
                """
                INSERT INTO translation_jobs (
                    id, order_id, user_id, file_id, file_name, document_kind,
                    source_object_key, source_language, target_language,
                    adapter_version, prompt_version, pricing_snapshot_id,
                    translation_policy, status
                ) VALUES (
                    %(id)s, %(order_id)s, %(user_id)s, %(file_id)s, %(file_name)s,
                    'docx', %(source_object_key)s, %(source_language)s,
                    %(target_language)s, %(adapter_version)s, %(prompt_version)s,
                    %(pricing_snapshot_id)s, %(translation_policy)s, 'queued'
                )
                RETURNING *
                """,
                {
                    "id": job_id,
                    "order_id": request.order_id,
                    "user_id": request.user_id,
                    "file_id": request.file_id,
                    "file_name": request.file_name,
                    "source_object_key": request.source_object_key,
                    "source_language": request.source_language,
                    "target_language": request.target_language,
                    "adapter_version": request.adapter_version,
                    "prompt_version": request.prompt_version,
                    "pricing_snapshot_id": request.pricing_snapshot_id,
                    "translation_policy": request.translation_policy,
                },
            ).fetchone()
            self.connection.execute(
                """
                INSERT INTO strict_job_glossary_bindings (
                    job_id, approval_id, custody_id, snapshot_digest,
                    binding_schema_version
                ) VALUES (
                    %(job_id)s, %(approval_id)s, %(custody_id)s,
                    %(snapshot_digest)s, %(binding_schema_version)s
                )
                """,
                {
                    "job_id": job_id,
                    "approval_id": request.approval_id,
                    "custody_id": approval["custody_id"],
                    "snapshot_digest": approval["snapshot_digest"],
                    "binding_schema_version": request.binding_schema_version,
                },
            )
            for work_unit in request.work_units:
                self.connection.execute(
                    """
                    INSERT INTO work_units (
                        id, job_id, sequence, source_block_ids_json,
                        source_object_key, source_text_hash, prompt_tier,
                        source_language, target_language, status
                    ) VALUES (
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
        return StrictAdmissionResult(
            job=_job_from_mapping(job_row),
            work_units=self.list_work_units(job_id),
            denial_code=None,
        )

    def create_strict_docx_v3_authorization(
        self,
        *,
        approval_id: str,
        source_object_key: str,
        source_sha256: str,
        source_size_bytes: int,
        document_kind: str,
    ) -> StrictDocxV3Authorization:
        if (
            document_kind != "docx"
            or not source_object_key.strip()
            or len(source_sha256) != 64
            or source_size_bytes <= 0
        ):
            raise ValueError("Invalid strict DOCX v3 document custody")
        approved_snapshot = self.read_approved_glossary_snapshot(
            approval_id=approval_id
        )
        if approved_snapshot is None:
            raise ValueError("Strict DOCX v3 requires an approved glossary snapshot")

        with self.connection.transaction():
            custody = self.connection.execute(
                """
                INSERT INTO strict_docx_v3_document_custody (
                    document_custody_id, source_object_key, source_sha256,
                    source_size_bytes, document_kind
                ) VALUES (
                    %(document_custody_id)s, %(source_object_key)s,
                    %(source_sha256)s, %(source_size_bytes)s, 'docx'
                )
                ON CONFLICT (source_object_key) DO UPDATE
                SET source_object_key = EXCLUDED.source_object_key
                WHERE strict_docx_v3_document_custody.source_sha256
                        = EXCLUDED.source_sha256
                  AND strict_docx_v3_document_custody.source_size_bytes
                        = EXCLUDED.source_size_bytes
                  AND strict_docx_v3_document_custody.document_kind
                        = EXCLUDED.document_kind
                RETURNING document_custody_id
                """,
                {
                    "document_custody_id": f"document-custody-{uuid4().hex}",
                    "source_object_key": source_object_key,
                    "source_sha256": source_sha256,
                    "source_size_bytes": source_size_bytes,
                },
            ).fetchone()
            if custody is None:
                raise ValueError("Existing strict DOCX v3 custody does not match")
            row = self.connection.execute(
                """
                INSERT INTO strict_docx_v3_authorizations (
                    authorization_id, approval_id, document_custody_id,
                    snapshot_digest, authorization_status
                ) VALUES (
                    %(authorization_id)s, %(approval_id)s, %(document_custody_id)s,
                    %(snapshot_digest)s, 'approved'
                )
                ON CONFLICT (approval_id, document_custody_id, snapshot_digest)
                DO UPDATE SET approval_id = EXCLUDED.approval_id
                RETURNING authorization_id, approval_id, document_custody_id,
                          snapshot_digest, authorization_status, created_at, revoked_at
                """,
                {
                    "authorization_id": f"v3-authorization-{uuid4().hex}",
                    "approval_id": approval_id,
                    "document_custody_id": custody["document_custody_id"],
                    "snapshot_digest": approved_snapshot.approval.snapshot_digest,
                },
            ).fetchone()
        return self._require_strict_docx_v3_authorization(row["authorization_id"])

    def revoke_strict_docx_v3_authorization(
        self,
        *,
        authorization_id: str,
    ) -> StrictDocxV3Authorization:
        with self.connection.transaction():
            self._acquire_claim_serialization_lock()
            row = self.connection.execute(
                """
                UPDATE strict_docx_v3_authorizations
                SET authorization_status = 'revoked', revoked_at = now()
                WHERE authorization_id = %(authorization_id)s
                RETURNING *
                """,
                {"authorization_id": authorization_id},
            ).fetchone()
        if row is None:
            raise ValueError("Strict DOCX v3 authorization does not exist")
        return self._require_strict_docx_v3_authorization(authorization_id)

    def read_strict_docx_v3_authorization(
        self,
        *,
        authorization_id: str,
    ) -> StrictDocxV3Authorization | None:
        try:
            return self._require_strict_docx_v3_authorization(authorization_id)
        except ValueError:
            return None

    def admit_strict_docx_v3_job(
        self,
        request: StrictDocxV3AdmissionRequest,
    ) -> StrictAdmissionResult:
        denial_code = _strict_v3_admission_validation_error(request)
        if denial_code is not None:
            return StrictAdmissionResult(None, [], denial_code)
        with self.connection.transaction():
            authorization = self.connection.execute(
                """
                SELECT authorization.*, approval.approval_status,
                       approval.snapshot_digest AS approval_snapshot_digest,
                       custody.source_object_key, custody.source_sha256,
                       custody.source_size_bytes, custody.document_kind
                FROM strict_docx_v3_authorizations authorization
                JOIN glossary_approvals approval
                  ON approval.approval_id = authorization.approval_id
                JOIN strict_docx_v3_document_custody custody
                  ON custody.document_custody_id = authorization.document_custody_id
                WHERE authorization.authorization_id = %(authorization_id)s
                FOR UPDATE OF authorization, approval, custody
                """,
                {"authorization_id": request.authorization_id},
            ).fetchone()
            if authorization is None:
                return StrictAdmissionResult(
                    None, [], "strict_docx_v3_authorization_missing"
                )
            if authorization["authorization_status"] != "approved":
                return StrictAdmissionResult(
                    None, [], "strict_docx_v3_authorization_revoked"
                )
            if authorization["approval_status"] != "approved":
                return StrictAdmissionResult(
                    None, [], "strict_docx_v3_approval_revoked"
                )
            if (
                authorization["snapshot_digest"]
                != authorization["approval_snapshot_digest"]
                or authorization["source_object_key"] != request.source_object_key
                or authorization["source_sha256"] != request.source_sha256
                or authorization["source_size_bytes"] != request.source_size_bytes
                or authorization["document_kind"] != request.document_kind
            ):
                return StrictAdmissionResult(
                    None, [], "strict_docx_v3_source_custody_mismatch"
                )
            admission = self.admit_strict_docx_job(
                StrictDocxAdmissionRequest(
                    approval_id=authorization["approval_id"],
                    order_id=request.order_id,
                    user_id=request.user_id,
                    file_id=request.file_id,
                    file_name=request.file_name,
                    document_kind=request.document_kind,
                    source_object_key=request.source_object_key,
                    source_language=request.source_language,
                    target_language=request.target_language,
                    adapter_version=request.adapter_version,
                    prompt_version=request.prompt_version,
                    pricing_snapshot_id=request.pricing_snapshot_id,
                    translation_policy=request.translation_policy,
                    work_units=request.work_units,
                )
            )
            if admission.job is None:
                return admission
            self.connection.execute(
                """
                INSERT INTO strict_docx_v3_job_authorizations (
                    job_id, authorization_id, approval_id, document_custody_id,
                    snapshot_digest, source_object_key, source_sha256, source_size_bytes
                ) VALUES (
                    %(job_id)s, %(authorization_id)s, %(approval_id)s,
                    %(document_custody_id)s, %(snapshot_digest)s,
                    %(source_object_key)s, %(source_sha256)s, %(source_size_bytes)s
                )
                """,
                {
                    "job_id": admission.job.id,
                    "authorization_id": authorization["authorization_id"],
                    "approval_id": authorization["approval_id"],
                    "document_custody_id": authorization["document_custody_id"],
                    "snapshot_digest": authorization["snapshot_digest"],
                    "source_object_key": authorization["source_object_key"],
                    "source_sha256": authorization["source_sha256"],
                    "source_size_bytes": authorization["source_size_bytes"],
                },
            )
        return admission

    def clear_for_tests(self) -> None:
        with self.connection.transaction():
            self.connection.execute("DELETE FROM provider_slot_leases")
            self.connection.execute("DELETE FROM provider_slots")
            self.connection.execute("DELETE FROM scheduler_events")
            self.connection.execute("DELETE FROM work_unit_attempts")
            self.connection.execute("DELETE FROM worker_heartbeats")
            self.connection.execute("DELETE FROM strict_docx_v3_job_authorizations")
            self.connection.execute("DELETE FROM strict_job_glossary_bindings")
            self.connection.execute("DELETE FROM work_units")
            self.connection.execute("DELETE FROM translation_jobs")
            self.connection.execute("DELETE FROM strict_docx_v3_authorizations")
            self.connection.execute("DELETE FROM strict_docx_v3_document_custody")
            self.connection.execute("DELETE FROM glossary_approvals")
            self.connection.execute("DELETE FROM glossary_snapshot_custody")

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

    def list_recent_work_units(
        self,
        job_id: str,
        *,
        limit: int,
    ) -> list[PersistentWorkUnit]:
        safe_limit = max(0, int(limit))
        if safe_limit == 0:
            return []
        rows = self.connection.execute(
            """
            SELECT * FROM work_units
            WHERE job_id = %(job_id)s
            ORDER BY sequence DESC
            LIMIT %(limit)s
            """,
            {"job_id": job_id, "limit": safe_limit},
        ).fetchall()
        return [_work_unit_from_mapping(row) for row in reversed(rows)]

    def get_work_unit(self, work_unit_id: str) -> PersistentWorkUnit | None:
        row = self.connection.execute(
            "SELECT * FROM work_units WHERE id = %(work_unit_id)s",
            {"work_unit_id": work_unit_id},
        ).fetchone()
        if row is None:
            return None
        return _work_unit_from_mapping(row)

    def claim_next_work_unit(
        self,
        job_id: str,
        *,
        worker_id: str,
        max_active_units_per_job: int = 1,
    ) -> PersistentWorkUnit | None:
        with self.connection.transaction():
            self._acquire_claim_serialization_lock()
            job = self.connection.execute(
                """
                SELECT id
                FROM translation_jobs
                WHERE id = %(job_id)s
                  AND status IN ('queued', 'translating')
                  AND cancel_requested_at IS NULL
                FOR UPDATE
                """,
                {"job_id": job_id},
            ).fetchone()
            if job is None:
                return None
            active = self.connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM work_units
                WHERE job_id = %(job_id)s
                  AND status = 'translating'
                """,
                {"job_id": job_id},
            ).fetchone()
            if active["count"] >= max(1, max_active_units_per_job):
                return None
            candidate = self.connection.execute(
                f"""
                SELECT id
                FROM work_units
                WHERE job_id = %(job_id)s
                  AND status = 'pending'
                {_STRICT_DOCX_UPDATE_CLAIM_GUARD_SQL}
                ORDER BY sequence, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                {"job_id": job_id},
            ).fetchone()
            if candidate is None:
                return None
            updated = self.connection.execute(
                f"""
                UPDATE work_units
                SET status = 'translating',
                    worker_id = %(worker_id)s,
                    started_at = COALESCE(started_at, now()),
                    updated_at = now()
                WHERE id = %(work_unit_id)s
                  AND status = 'pending'
                {_STRICT_DOCX_UPDATE_CLAIM_GUARD_SQL}
                RETURNING *
                """,
                {
                    "work_unit_id": candidate["id"],
                    "worker_id": worker_id,
                },
            ).fetchone()
            if updated is None:
                return None
            self.connection.execute(
                """
                UPDATE translation_jobs
                SET status = 'translating', updated_at = now()
                WHERE id = %(job_id)s
                  AND status IN ('queued', 'translating')
                  AND cancel_requested_at IS NULL
                """,
                {"job_id": job_id},
            )
        return _work_unit_from_mapping(updated)

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
                _CLAIM_NEXT_SCHEDULED_WORK_UNIT_SQL,
                {
                    "worker_id": worker_id,
                    "claim_token": claim_token,
                    "claim_lock_key": _CLAIM_ADVISORY_LOCK_KEY,
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
                  AND status IN ('queued', 'translating')
                  AND cancel_requested_at IS NULL
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
                    "queue_policy": SCHEDULER_FAIR_QUEUE_POLICY,
                    "queue_policy_diagnostics": (
                        build_scheduler_queue_policy_diagnostics(
                            active_user_units_before_claim=updated[
                                "queue_policy_active_user_units"
                            ],
                            active_user_jobs_before_claim=updated[
                                "queue_policy_active_user_jobs"
                            ],
                            active_job_units_before_claim=updated[
                                "queue_policy_active_job_units"
                            ],
                            max_active_units_per_job=max_active_units_per_job,
                            max_active_units_per_user=max_active_units_per_user,
                            max_active_jobs_per_user=max_active_jobs_per_user,
                            priority_aging_seconds=priority_aging_seconds,
                        )
                    ),
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

            if not self._finalize_cancel_requested_job_if_idle(
                completed_row["job_id"],
                now=now,
            ) and self._job_has_no_unfinished_work(completed_row["job_id"]):
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
            if (
                not self._finalize_cancel_requested_job_if_idle(
                    work_unit.job_id,
                    now=now,
                )
                and decision.terminal_job_status is not None
            ):
                self._update_job_status(
                    work_unit.job_id,
                    PersistentTranslationJobStatus.INTERRUPTED,
                    now=now,
                )
        return self._require_work_unit(work_unit_id)

    def defer_claimed_work_unit_for_provider_capacity(
        self,
        *,
        work_unit_id: str,
        claim_token: str,
    ) -> PersistentWorkUnit | None:
        now = _now()
        with self.connection.transaction():
            deferred_row = self.connection.execute(
                """
                UPDATE work_units
                SET status = 'pending',
                    worker_id = NULL,
                    claim_token = NULL,
                    lease_until = NULL,
                    attempt_count = GREATEST(0, attempt_count - 1),
                    started_at = CASE
                        WHEN attempt_count <= 1 THEN NULL
                        ELSE started_at
                    END,
                    available_at = %(now)s,
                    updated_at = %(now)s
                WHERE id = %(work_unit_id)s
                  AND claim_token = %(claim_token)s
                  AND status = 'translating'
                RETURNING *
                """,
                {
                    "work_unit_id": work_unit_id,
                    "claim_token": claim_token,
                    "now": now,
                },
            ).fetchone()
            if deferred_row is None:
                return None
            self._record_scheduler_event(
                job_id=deferred_row["job_id"],
                work_unit_id=work_unit_id,
                event_type="work_unit_provider_capacity_deferred",
                payload={"reason": "provider_slot_unavailable"},
                now=now,
            )
            self._finalize_cancel_requested_job_if_idle(
                deferred_row["job_id"],
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

    def delete_job(self, job_id: str) -> DeleteJobResult:
        with self.connection.transaction():
            job = self.connection.execute(
                """
                SELECT 1
                FROM translation_jobs
                WHERE id = %(job_id)s
                FOR UPDATE
                """,
                {"job_id": job_id},
            ).fetchone()
            if job is None:
                return DeleteJobResult(deleted=False, denial_code=None)
            binding = self.connection.execute(
                "SELECT 1 FROM strict_job_glossary_bindings WHERE job_id = %(job_id)s",
                {"job_id": job_id},
            ).fetchone()
            if binding is not None:
                return DeleteJobResult(
                    deleted=False,
                    denial_code="strict_job_non_deletable",
                )
            self.connection.execute(
                "DELETE FROM provider_slot_leases WHERE job_id = %(job_id)s",
                {"job_id": job_id},
            )
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
        return DeleteJobResult(deleted=True, denial_code=None)

    def cancel_job(self, job_id: str) -> PersistentTranslationJob:
        self._require_job(job_id)
        now = _now()
        with self.connection.transaction():
            self.connection.execute(
                """
                SELECT pg_advisory_xact_lock(hashtext(%(claim_lock_key)s))
                """,
                {"claim_lock_key": _CLAIM_ADVISORY_LOCK_KEY},
            )
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
            self.connection.execute(
                """
                UPDATE translation_jobs
                SET status = %(status)s,
                    cancel_requested_at = COALESCE(cancel_requested_at, %(now)s),
                    updated_at = %(now)s
                WHERE id = %(job_id)s
                """,
                {
                    "status": PersistentTranslationJobStatus.CANCELLED.value,
                    "job_id": job_id,
                    "now": now,
                },
            )
        return self._require_job(job_id)

    def request_cancel_job(self, job_id: str) -> PersistentTranslationJob:
        self._require_job(job_id)
        now = _now()
        with self.connection.transaction():
            self.connection.execute(
                """
                SELECT pg_advisory_xact_lock(hashtext(%(claim_lock_key)s))
                """,
                {"claim_lock_key": _CLAIM_ADVISORY_LOCK_KEY},
            )
            self.connection.execute(
                """
                UPDATE translation_jobs
                SET status = %(status)s,
                    cancel_requested_at = COALESCE(cancel_requested_at, %(now)s),
                    updated_at = %(now)s
                WHERE id = %(job_id)s
                """,
                {
                    "status": PersistentTranslationJobStatus.CANCEL_REQUESTED.value,
                    "job_id": job_id,
                    "now": now,
                },
            )
            self._finalize_cancel_requested_job_if_idle(job_id, now=now)
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
                    %(failed_retryable)s,
                    %(failed_terminal)s
                  )
                """,
                {
                    "pending": PersistentWorkUnitStatus.PENDING.value,
                    "translating": PersistentWorkUnitStatus.TRANSLATING.value,
                    "failed": PersistentWorkUnitStatus.FAILED.value,
                    "failed_retryable": (
                        PersistentWorkUnitStatus.FAILED_RETRYABLE.value
                    ),
                    "failed_terminal": PersistentWorkUnitStatus.FAILED_TERMINAL.value,
                    "job_id": job_id,
                    "now": now,
                },
            )
            self.connection.execute(
                """
                UPDATE translation_jobs
                SET status = %(status)s,
                    partial_object_key = NULL,
                    cancel_requested_at = NULL,
                    updated_at = %(now)s
                WHERE id = %(job_id)s
                """,
                {
                    "status": PersistentTranslationJobStatus.QUEUED.value,
                    "job_id": job_id,
                    "now": now,
                },
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

    def mark_job_failed(self, job_id: str) -> PersistentTranslationJob:
        with self.connection.transaction():
            self._update_job_status(
                job_id,
                PersistentTranslationJobStatus.FAILED,
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

    def get_scheduler_backpressure_diagnostics(
        self,
        *,
        provider_id: str | None = None,
        capacity_caps: list[ProviderCapacityCap] | None = None,
        provider_capacity: ProviderCapacityDiagnostics | None = None,
        throttle_available_slots: int | None = None,
        throttle_circuit_state: str | None = None,
        throughput_window_seconds: int = 300,
        now: datetime | None = None,
    ) -> SchedulerBackpressureDiagnostics:
        current_time = now or _now()
        window_seconds = max(1, int(throughput_window_seconds))
        window_start = current_time - timedelta(seconds=window_seconds)
        if provider_capacity is None and provider_id:
            provider_capacity = self.get_provider_capacity_diagnostics(
                provider_id=provider_id,
                capacity_caps=capacity_caps,
                now=current_time,
            )
        row = self.connection.execute(
            """
            SELECT
              (
                SELECT COUNT(*)
                FROM work_units wu
                JOIN translation_jobs tj ON tj.id = wu.job_id
                WHERE tj.status IN ('queued', 'translating')
                  AND tj.cancel_requested_at IS NULL
                  AND wu.status IN ('pending', 'failed', 'failed_retryable')
              ) AS queue_depth_units,
              (
                SELECT COUNT(*)
                FROM work_units wu
                JOIN translation_jobs tj ON tj.id = wu.job_id
                WHERE tj.status IN ('queued', 'translating')
                  AND tj.cancel_requested_at IS NULL
                  AND wu.status IN ('pending', 'failed', 'failed_retryable')
                  AND wu.available_at <= %(now)s
                  AND (wu.lease_until IS NULL OR wu.lease_until <= %(now)s)
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
              ) AS eligible_waiting_units,
              (
                SELECT COUNT(*)
                FROM work_units wu
                JOIN translation_jobs tj ON tj.id = wu.job_id
                WHERE tj.status IN ('queued', 'translating')
                  AND tj.cancel_requested_at IS NULL
                  AND wu.status = 'failed_retryable'
                  AND wu.available_at > %(now)s
              ) AS delayed_retry_units,
              (
                SELECT COUNT(*)
                FROM work_units
                WHERE status = 'translating'
              ) AS active_work_units,
              (
                SELECT COUNT(*)
                FROM work_units wu
                JOIN translation_jobs tj ON tj.id = wu.job_id
                WHERE tj.status IN ('queued', 'translating')
                  AND tj.cancel_requested_at IS NULL
                  AND wu.status = 'failed_retryable'
              ) AS retry_pressure_units,
              (
                SELECT COUNT(*)
                FROM work_units
                WHERE status = 'translating'
                  AND lease_until IS NOT NULL
                  AND lease_until <= %(now)s
              ) AS expired_work_unit_leases,
              (
                SELECT COUNT(*)
                FROM work_units
                WHERE status IN ('translated', 'cached')
                  AND completed_at IS NOT NULL
                  AND completed_at >= %(window_start)s
              ) AS recent_completed_units
            """,
            {
                "now": current_time,
                "window_start": window_start,
            },
        ).fetchone()
        return build_scheduler_backpressure_diagnostics(
            queue_depth_units=row["queue_depth_units"],
            eligible_waiting_units=row["eligible_waiting_units"],
            delayed_retry_units=row["delayed_retry_units"],
            active_work_units=row["active_work_units"],
            retry_pressure_units=row["retry_pressure_units"],
            expired_work_unit_leases=row["expired_work_unit_leases"],
            provider_capacity=provider_capacity,
            throttle_available_slots=throttle_available_slots,
            throttle_circuit_state=throttle_circuit_state,
            recent_completed_units=row["recent_completed_units"],
            throughput_window_seconds=window_seconds,
            now=current_time,
        )

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

    def upsert_provider_slot_inventory(
        self,
        *,
        provider_id: str,
        channel_id: str,
        max_parallel_requests: int,
        capacity_source: str | None = None,
    ) -> list[ProviderSlot]:
        slot_count = max(1, max_parallel_requests)
        now = _now()
        with self.connection.transaction():
            for slot_index in range(slot_count):
                self.connection.execute(
                    """
                    INSERT INTO provider_slots (
                        provider_id, channel_id, slot_index, capacity_source,
                        enabled, created_at, updated_at
                    )
                    VALUES (
                        %(provider_id)s, %(channel_id)s, %(slot_index)s,
                        %(capacity_source)s, TRUE, %(now)s, %(now)s
                    )
                    ON CONFLICT(provider_id, channel_id, slot_index)
                    DO UPDATE SET
                        capacity_source = excluded.capacity_source,
                        enabled = TRUE,
                        updated_at = excluded.updated_at
                    """,
                    {
                        "provider_id": provider_id,
                        "channel_id": channel_id,
                        "slot_index": slot_index,
                        "capacity_source": capacity_source,
                        "now": now,
                    },
                )
            self.connection.execute(
                """
                UPDATE provider_slots
                SET enabled = FALSE, updated_at = %(now)s
                WHERE provider_id = %(provider_id)s
                  AND channel_id = %(channel_id)s
                  AND slot_index >= %(slot_count)s
                """,
                {
                    "provider_id": provider_id,
                    "channel_id": channel_id,
                    "slot_count": slot_count,
                    "now": now,
                },
            )
        return self.list_provider_slots(
            provider_id=provider_id,
            channel_id=channel_id,
        )

    def list_provider_slots(
        self,
        *,
        provider_id: str | None = None,
        channel_id: str | None = None,
    ) -> list[ProviderSlot]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM provider_slots
            WHERE (%(provider_id)s::text IS NULL OR provider_id = %(provider_id)s)
              AND (%(channel_id)s::text IS NULL OR channel_id = %(channel_id)s)
            ORDER BY provider_id, channel_id, slot_index
            """,
            {"provider_id": provider_id, "channel_id": channel_id},
        ).fetchall()
        return [_provider_slot_from_row(row) for row in rows]

    def acquire_provider_slot_lease(
        self,
        *,
        provider_id: str,
        job_id: str,
        work_unit_id: str,
        worker_id: str,
        work_unit_claim_token: str,
        lease_seconds: int,
        channel_id: str | None = None,
        capacity_caps: list[ProviderCapacityCap] | None = None,
    ) -> ProviderSlotLease | None:
        now = _now()
        lease_until = now + timedelta(seconds=max(1, lease_seconds))
        lease_token = uuid4().hex
        safe_capacity_caps = _provider_capacity_caps_for_provider(
            capacity_caps or [],
            provider_id=provider_id,
        )
        with self.connection.transaction():
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%(lock_key)s))",
                {
                    "lock_key": (
                        "translator_service.postgres_scheduler."
                        f"provider_slot_lease.{provider_id}"
                    )
                },
            )
            candidates = self.connection.execute(
                """
                SELECT ps.*
                FROM provider_slots ps
                WHERE ps.provider_id = %(provider_id)s
                  AND (
                    %(channel_id)s::text IS NULL
                    OR ps.channel_id = %(channel_id)s
                  )
                  AND ps.enabled = TRUE
                  AND NOT EXISTS (
                      SELECT 1
                      FROM provider_slot_leases active_lease
                      WHERE active_lease.provider_id = ps.provider_id
                        AND active_lease.channel_id = ps.channel_id
                        AND active_lease.slot_index = ps.slot_index
                        AND active_lease.status = 'active'
                  )
                ORDER BY ps.channel_id, ps.slot_index
                FOR UPDATE SKIP LOCKED
                """,
                {
                    "provider_id": provider_id,
                    "channel_id": channel_id,
                },
            ).fetchall()
            row = None
            for candidate in candidates:
                if not _provider_capacity_caps_allow_candidate(
                    self.connection,
                    provider_id=provider_id,
                    channel_id=candidate["channel_id"],
                    capacity_caps=safe_capacity_caps,
                ):
                    continue
                row = self.connection.execute(
                    """
                INSERT INTO provider_slot_leases (
                    id, lease_token, provider_id, channel_id, slot_index,
                    job_id, work_unit_id, worker_id, work_unit_claim_token,
                    status, acquired_at, lease_until, created_at, updated_at
                )
                VALUES (
                    %(lease_id)s, %(lease_token)s, %(provider_id)s,
                    %(channel_id)s, %(slot_index)s, %(job_id)s,
                    %(work_unit_id)s, %(worker_id)s, %(work_unit_claim_token)s,
                    'active', %(now)s, %(lease_until)s, %(now)s, %(now)s
                )
                RETURNING *
                """,
                    {
                        "lease_id": f"provider-slot-lease-{uuid4().hex}",
                        "lease_token": lease_token,
                        "provider_id": provider_id,
                        "channel_id": candidate["channel_id"],
                        "slot_index": candidate["slot_index"],
                        "job_id": job_id,
                        "work_unit_id": work_unit_id,
                        "worker_id": worker_id,
                        "work_unit_claim_token": work_unit_claim_token,
                        "now": now,
                        "lease_until": lease_until,
                    },
                ).fetchone()
                break
        if row is None:
            return None
        return _provider_slot_lease_from_row(row)

    def release_provider_slot_lease(
        self,
        *,
        lease_token: str,
        work_unit_claim_token: str,
        release_reason: str = "released",
    ) -> ProviderSlotLease | None:
        now = _now()
        safe_release_reason = _provider_slot_release_reason(release_reason)
        with self.connection.transaction():
            row = self.connection.execute(
                """
                SELECT *
                FROM provider_slot_leases
                WHERE lease_token = %(lease_token)s
                  AND work_unit_claim_token = %(work_unit_claim_token)s
                FOR UPDATE
                """,
                {
                    "lease_token": lease_token,
                    "work_unit_claim_token": work_unit_claim_token,
                },
            ).fetchone()
            if row is None:
                return None
            if row["status"] != ProviderSlotLeaseStatus.ACTIVE.value:
                return _provider_slot_lease_from_row(row)
            released = self.connection.execute(
                """
                UPDATE provider_slot_leases
                SET status = 'released',
                    released_at = %(now)s,
                    release_reason = %(release_reason)s,
                    updated_at = %(now)s
                WHERE lease_token = %(lease_token)s
                  AND work_unit_claim_token = %(work_unit_claim_token)s
                  AND status = 'active'
                RETURNING *
                """,
                {
                    "lease_token": lease_token,
                    "work_unit_claim_token": work_unit_claim_token,
                    "release_reason": safe_release_reason,
                    "now": now,
                },
            ).fetchone()
        if released is None:
            return None
        return _provider_slot_lease_from_row(released)

    def recover_expired_provider_slot_leases(self, *, now: datetime) -> int:
        with self.connection.transaction():
            rows = self.connection.execute(
                """
                UPDATE provider_slot_leases
                SET status = 'expired',
                    released_at = %(now)s,
                    release_reason = 'lease_expired',
                    updated_at = %(now)s
                WHERE status = 'active'
                  AND lease_until <= %(now)s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM work_units wu
                      WHERE wu.id = provider_slot_leases.work_unit_id
                        AND wu.claim_token = (
                            provider_slot_leases.work_unit_claim_token
                        )
                        AND wu.status = 'translating'
                        AND wu.lease_until IS NOT NULL
                        AND wu.lease_until > %(now)s
                  )
                RETURNING id
                """,
                {"now": now},
            ).fetchall()
        return len(rows)

    def list_provider_slot_leases(
        self,
        *,
        status: ProviderSlotLeaseStatus | None = None,
        provider_id: str | None = None,
    ) -> list[ProviderSlotLease]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM provider_slot_leases
            WHERE (%(status)s::text IS NULL OR status = %(status)s)
              AND (%(provider_id)s::text IS NULL OR provider_id = %(provider_id)s)
            ORDER BY acquired_at, id
            """,
            {
                "status": status.value if status is not None else None,
                "provider_id": provider_id,
            },
        ).fetchall()
        return [_provider_slot_lease_from_row(row) for row in rows]

    def get_provider_capacity_diagnostics(
        self,
        *,
        provider_id: str,
        capacity_caps: list[ProviderCapacityCap] | None = None,
        now: datetime | None = None,
    ) -> ProviderCapacityDiagnostics:
        current_time = now or _now()
        slots = self.list_provider_slots(provider_id=provider_id)
        active_rows = self.connection.execute(
            """
            SELECT *
            FROM provider_slot_leases
            WHERE provider_id = %(provider_id)s
              AND status = 'active'
            ORDER BY acquired_at, id
            """,
            {"provider_id": provider_id},
        ).fetchall()
        count_rows = self.connection.execute(
            """
            SELECT status, release_reason, COUNT(*) AS count
            FROM provider_slot_leases
            WHERE provider_id = %(provider_id)s
            GROUP BY status, release_reason
            """,
            {"provider_id": provider_id},
        ).fetchall()
        released_count = sum(
            int(row["count"]) for row in count_rows if row["status"] == "released"
        )
        recovered_count = sum(
            int(row["count"])
            for row in count_rows
            if row["status"] == "expired" and row["release_reason"] == "lease_expired"
        )
        return build_provider_capacity_diagnostics(
            provider_id=provider_id,
            slots=slots,
            leases=[_provider_slot_lease_from_row(row) for row in active_rows],
            capacity_caps=capacity_caps or [],
            now=current_time,
            released_lease_count=released_count,
            recovered_expired_lease_count=recovered_count,
        )

    def _require_job(self, job_id: str) -> PersistentTranslationJob:
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Translation job does not exist: {job_id}")
        return job

    def _require_strict_docx_v3_authorization(
        self,
        authorization_id: str,
    ) -> StrictDocxV3Authorization:
        row = self.connection.execute(
            """
            SELECT authorization.*, custody.source_object_key, custody.source_sha256,
                   custody.source_size_bytes, custody.document_kind
            FROM strict_docx_v3_authorizations authorization
            JOIN strict_docx_v3_document_custody custody
              ON custody.document_custody_id = authorization.document_custody_id
            WHERE authorization.authorization_id = %(authorization_id)s
            """,
            {"authorization_id": authorization_id},
        ).fetchone()
        if row is None:
            raise ValueError("Strict DOCX v3 authorization does not exist")
        return StrictDocxV3Authorization(
            authorization_id=row["authorization_id"],
            approval_id=row["approval_id"],
            document_custody_id=row["document_custody_id"],
            snapshot_digest=row["snapshot_digest"],
            source_object_key=row["source_object_key"],
            source_sha256=row["source_sha256"],
            source_size_bytes=row["source_size_bytes"],
            document_kind=row["document_kind"],
            authorization_status=row["authorization_status"],
            created_at=row["created_at"],
            revoked_at=row["revoked_at"],
        )

    def _acquire_claim_serialization_lock(self) -> None:
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%(claim_lock_key)s))",
            {"claim_lock_key": _CLAIM_ADVISORY_LOCK_KEY},
        )

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

    def _job_has_active_work(self, job_id: str) -> bool:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM work_units
            WHERE job_id = %(job_id)s
              AND status = %(translating)s
            """,
            {
                "job_id": job_id,
                "translating": PersistentWorkUnitStatus.TRANSLATING.value,
            },
        ).fetchone()
        return row["count"] > 0

    def _finalize_cancel_requested_job_if_idle(
        self,
        job_id: str,
        *,
        now: datetime,
    ) -> bool:
        job = self._require_job(job_id)
        if job.status is not PersistentTranslationJobStatus.CANCEL_REQUESTED:
            return False
        if self._job_has_active_work(job_id):
            return True
        self._update_job_status(
            job_id,
            PersistentTranslationJobStatus.CANCELLED,
            now=now,
        )
        return True

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


def _provider_slot_from_row(row) -> ProviderSlot:
    return ProviderSlot(
        provider_id=row["provider_id"],
        channel_id=row["channel_id"],
        slot_index=int(row["slot_index"]),
        capacity_source=row["capacity_source"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _provider_slot_lease_from_row(row) -> ProviderSlotLease:
    return ProviderSlotLease(
        lease_id=row["id"],
        lease_token=row["lease_token"],
        provider_id=row["provider_id"],
        channel_id=row["channel_id"],
        slot_index=int(row["slot_index"]),
        job_id=row["job_id"],
        work_unit_id=row["work_unit_id"],
        worker_id=row["worker_id"],
        work_unit_claim_token=row["work_unit_claim_token"],
        status=ProviderSlotLeaseStatus(row["status"]),
        acquired_at=row["acquired_at"],
        lease_until=row["lease_until"],
        released_at=row["released_at"],
        release_reason=row["release_reason"],
    )


def _provider_capacity_caps_for_provider(
    capacity_caps: list[ProviderCapacityCap],
    *,
    provider_id: str,
) -> list[ProviderCapacityCap]:
    safe_caps: list[ProviderCapacityCap] = []
    for cap in capacity_caps:
        if cap.provider_id != provider_id:
            continue
        channel_ids = tuple(
            sorted({channel_id for channel_id in cap.channel_ids if channel_id})
        )
        safe_caps.append(
            ProviderCapacityCap(
                provider_id=provider_id,
                cap_id=cap.cap_id,
                scope=cap.scope,
                max_parallel_requests=max(0, int(cap.max_parallel_requests)),
                channel_ids=channel_ids,
            )
        )
    return safe_caps


def _provider_capacity_caps_allow_candidate(
    connection,
    *,
    provider_id: str,
    channel_id: str,
    capacity_caps: list[ProviderCapacityCap],
) -> bool:
    for cap in capacity_caps:
        if cap.channel_ids and channel_id not in cap.channel_ids:
            continue
        if cap.max_parallel_requests <= 0:
            return False
        if cap.channel_ids:
            row = connection.execute(
                """
                SELECT COUNT(*) AS active_count
                FROM provider_slot_leases
                WHERE provider_id = %(provider_id)s
                  AND status = 'active'
                  AND channel_id = ANY(%(channel_ids)s)
                """,
                {
                    "provider_id": provider_id,
                    "channel_ids": list(cap.channel_ids),
                },
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT COUNT(*) AS active_count
                FROM provider_slot_leases
                WHERE provider_id = %(provider_id)s
                  AND status = 'active'
                """,
                {"provider_id": provider_id},
            ).fetchone()
        if int(row["active_count"]) >= cap.max_parallel_requests:
            return False
    return True


def _provider_slot_release_reason(release_reason: str) -> str:
    if release_reason in _PROVIDER_SLOT_RELEASE_REASONS:
        return release_reason
    return "released"


def _now() -> datetime:
    return datetime.now(UTC)
