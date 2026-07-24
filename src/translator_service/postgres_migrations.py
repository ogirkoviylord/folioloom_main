from __future__ import annotations

from dataclasses import dataclass

# ruff: noqa: E501
from hashlib import sha256

_MIGRATION_LOCK_KEY = "translator_service.postgres_migrations.runner.v1"
_LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


@dataclass(frozen=True)
class PostgresMigration:
    version: int
    sql_payload: str

    @property
    def checksum(self) -> str:
        return sha256(self.sql_payload.encode("utf-8")).hexdigest()


class PostgresMigrationBootstrapError(RuntimeError):
    """The PostgreSQL scheduler schema cannot be safely migrated or stamped."""


_V1_SCHEDULER_SQL = """
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

_V2_STRICT_DOCX_SQL = """
CREATE TABLE IF NOT EXISTS glossary_snapshot_custody (
    custody_id TEXT PRIMARY KEY,
    snapshot_payload BYTEA NOT NULL,
    snapshot_digest TEXT NOT NULL UNIQUE,
    snapshot_schema_version INTEGER NOT NULL,
    retention_mode TEXT NOT NULL DEFAULT 'retain'
        CHECK (retention_mode = 'retain'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS glossary_approvals (
    approval_id TEXT PRIMARY KEY,
    custody_id TEXT NOT NULL REFERENCES glossary_snapshot_custody(custody_id),
    snapshot_digest TEXT NOT NULL,
    approval_schema_version INTEGER NOT NULL,
    approval_status TEXT NOT NULL
        CHECK (approval_status IN ('approved', 'revoked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    UNIQUE(custody_id, snapshot_digest, approval_schema_version)
);

CREATE TABLE IF NOT EXISTS strict_job_glossary_bindings (
    job_id TEXT PRIMARY KEY REFERENCES translation_jobs(id),
    approval_id TEXT NOT NULL REFERENCES glossary_approvals(approval_id),
    custody_id TEXT NOT NULL REFERENCES glossary_snapshot_custody(custody_id),
    snapshot_digest TEXT NOT NULL,
    binding_schema_version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_V3_STRICT_DOCX_DOCUMENT_AUTHORIZATION_SQL = """
CREATE TABLE IF NOT EXISTS strict_docx_v3_document_custody (
    document_custody_id TEXT PRIMARY KEY,
    source_object_key TEXT NOT NULL UNIQUE,
    source_sha256 TEXT NOT NULL,
    source_size_bytes BIGINT NOT NULL CHECK (source_size_bytes > 0),
    document_kind TEXT NOT NULL CHECK (document_kind = 'docx'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS strict_docx_v3_authorizations (
    authorization_id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL REFERENCES glossary_approvals(approval_id),
    document_custody_id TEXT NOT NULL REFERENCES strict_docx_v3_document_custody(document_custody_id),
    snapshot_digest TEXT NOT NULL,
    authorization_status TEXT NOT NULL CHECK (authorization_status IN ('approved', 'revoked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    UNIQUE(approval_id, document_custody_id, snapshot_digest)
);

CREATE TABLE IF NOT EXISTS strict_docx_v3_job_authorizations (
    job_id TEXT PRIMARY KEY REFERENCES translation_jobs(id),
    authorization_id TEXT NOT NULL REFERENCES strict_docx_v3_authorizations(authorization_id),
    approval_id TEXT NOT NULL REFERENCES glossary_approvals(approval_id),
    document_custody_id TEXT NOT NULL REFERENCES strict_docx_v3_document_custody(document_custody_id),
    snapshot_digest TEXT NOT NULL,
    source_object_key TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_size_bytes BIGINT NOT NULL CHECK (source_size_bytes > 0)
);
"""

MIGRATIONS = (
    PostgresMigration(version=1, sql_payload=_V1_SCHEDULER_SQL),
    PostgresMigration(version=2, sql_payload=_V2_STRICT_DOCX_SQL),
    PostgresMigration(
        version=3, sql_payload=_V3_STRICT_DOCX_DOCUMENT_AUTHORIZATION_SQL
    ),
)

# This is intentionally an enumerated catalog query rather than a one-table probe.
_BASELINE_RELATIONS = (
    "translation_jobs",
    "work_units",
    "work_unit_attempts",
    "scheduler_events",
    "worker_heartbeats",
    "provider_slots",
    "provider_slot_leases",
)
_STRICT_DOCX_RELATIONS = (
    "glossary_snapshot_custody",
    "glossary_approvals",
    "strict_job_glossary_bindings",
)
_V3_STRICT_DOCX_RELATIONS = (
    "strict_docx_v3_document_custody",
    "strict_docx_v3_authorizations",
    "strict_docx_v3_job_authorizations",
)
_PRE_LEDGER_RELATIONS = (
    _BASELINE_RELATIONS + _STRICT_DOCX_RELATIONS + _V3_STRICT_DOCX_RELATIONS
)
_BASELINE_RELATIONS_SQL = """
SELECT relation.relname
FROM pg_catalog.pg_class relation
JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = current_schema()
  AND relation.relkind = 'r'
  AND relation.relname = ANY(%(relation_names)s)
ORDER BY relation.relname
"""

# The catalog query checks all v1 columns, types, nullability and defaults. The
# strings are PostgreSQL's format_type()/pg_get_expr() representation.
_COLUMN_MANIFEST = {
    "translation_jobs": (
        ("id", "text", True, None),
        ("order_id", "text", True, None),
        ("user_id", "text", True, None),
        ("file_id", "text", True, None),
        ("source_object_key", "text", True, None),
        ("file_name", "text", True, None),
        ("document_kind", "text", True, None),
        ("source_language", "text", True, None),
        ("target_language", "text", True, None),
        ("adapter_version", "text", True, None),
        ("prompt_version", "text", True, None),
        ("pricing_snapshot_id", "text", True, None),
        ("translation_policy", "text", False, None),
        ("partial_object_key", "text", False, None),
        ("final_object_key", "text", False, None),
        ("status", "text", True, None),
        ("priority", "integer", True, "0"),
        ("cancel_requested_at", "timestamp with time zone", False, None),
        ("resume_blocked_reason", "text", False, None),
        ("created_at", "timestamp with time zone", True, "now()"),
        ("updated_at", "timestamp with time zone", True, "now()"),
    ),
    "work_units": (
        ("id", "text", True, None),
        ("job_id", "text", True, None),
        ("sequence", "integer", True, None),
        ("source_block_ids_json", "text", True, None),
        ("source_object_key", "text", False, None),
        ("source_text_hash", "text", True, None),
        ("prompt_tier", "text", True, None),
        ("source_language", "text", True, None),
        ("target_language", "text", True, None),
        ("status", "text", True, None),
        ("translated_text", "text", False, None),
        ("worker_id", "text", False, None),
        ("claim_token", "text", False, None),
        ("attempt_count", "integer", True, "0"),
        ("max_attempts", "integer", True, "3"),
        ("available_at", "timestamp with time zone", True, "now()"),
        ("lease_until", "timestamp with time zone", False, None),
        ("prompt_tokens", "integer", True, "0"),
        ("completion_tokens", "integer", True, "0"),
        ("cache_hit_tokens", "integer", True, "0"),
        ("cache_miss_tokens", "integer", True, "0"),
        ("retry_count", "integer", True, "0"),
        ("last_error", "text", False, None),
        ("created_at", "timestamp with time zone", True, "now()"),
        ("updated_at", "timestamp with time zone", True, "now()"),
        ("started_at", "timestamp with time zone", False, None),
        ("completed_at", "timestamp with time zone", False, None),
    ),
    "work_unit_attempts": (
        ("id", "text", True, None),
        ("work_unit_id", "text", True, None),
        ("job_id", "text", True, None),
        ("attempt_number", "integer", True, None),
        ("worker_id", "text", False, None),
        ("claim_token", "text", False, None),
        ("status", "text", True, None),
        ("error_code", "text", False, None),
        ("error_message", "text", False, None),
        ("retry_after_seconds", "integer", True, "0"),
        ("prompt_tokens", "integer", True, "0"),
        ("completion_tokens", "integer", True, "0"),
        ("cache_hit_tokens", "integer", True, "0"),
        ("cache_miss_tokens", "integer", True, "0"),
        ("started_at", "timestamp with time zone", True, "now()"),
        ("finished_at", "timestamp with time zone", True, "now()"),
    ),
    "scheduler_events": (
        ("id", "text", True, None),
        ("job_id", "text", True, None),
        ("work_unit_id", "text", False, None),
        ("event_type", "text", True, None),
        ("payload_json", "text", True, None),
        ("created_at", "timestamp with time zone", True, "now()"),
    ),
    "worker_heartbeats": (
        ("worker_id", "text", True, None),
        ("worker_kind", "text", True, None),
        ("status", "text", True, None),
        ("active_job_id", "text", False, None),
        ("active_work_unit_id", "text", False, None),
        ("started_at", "timestamp with time zone", True, "now()"),
        ("last_seen_at", "timestamp with time zone", True, "now()"),
    ),
    "provider_slots": (
        ("provider_id", "text", True, None),
        ("channel_id", "text", True, None),
        ("slot_index", "integer", True, None),
        ("capacity_source", "text", False, None),
        ("enabled", "boolean", True, "true"),
        ("created_at", "timestamp with time zone", True, "now()"),
        ("updated_at", "timestamp with time zone", True, "now()"),
    ),
    "provider_slot_leases": (
        ("id", "text", True, None),
        ("lease_token", "text", True, None),
        ("provider_id", "text", True, None),
        ("channel_id", "text", True, None),
        ("slot_index", "integer", True, None),
        ("job_id", "text", True, None),
        ("work_unit_id", "text", True, None),
        ("worker_id", "text", True, None),
        ("work_unit_claim_token", "text", True, None),
        ("status", "text", True, None),
        ("acquired_at", "timestamp with time zone", True, "now()"),
        ("lease_until", "timestamp with time zone", True, None),
        ("released_at", "timestamp with time zone", False, None),
        ("release_reason", "text", False, None),
        ("created_at", "timestamp with time zone", True, "now()"),
        ("updated_at", "timestamp with time zone", True, "now()"),
    ),
}

_COLUMN_CATALOG_SQL = """
SELECT table_relation.relname AS table_name, attribute.attname AS column_name,
       pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) AS type_name,
       attribute.attnotnull AS not_null,
       pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid) AS default_expr
FROM pg_catalog.pg_attribute attribute
JOIN pg_catalog.pg_class table_relation ON table_relation.oid = attribute.attrelid
JOIN pg_catalog.pg_namespace namespace ON namespace.oid = table_relation.relnamespace
LEFT JOIN pg_catalog.pg_attrdef default_value ON default_value.adrelid = attribute.attrelid
    AND default_value.adnum = attribute.attnum
WHERE namespace.nspname = current_schema()
  AND table_relation.relname = ANY(%(relation_names)s)
  AND attribute.attnum > 0 AND NOT attribute.attisdropped
ORDER BY table_relation.relname, attribute.attnum
"""

_CONSTRAINT_CATALOG_SQL = """
SELECT table_relation.relname AS table_name, constraint_item.contype,
       pg_catalog.pg_get_constraintdef(constraint_item.oid, true) AS definition
FROM pg_catalog.pg_constraint constraint_item
JOIN pg_catalog.pg_class table_relation ON table_relation.oid = constraint_item.conrelid
JOIN pg_catalog.pg_namespace namespace ON namespace.oid = table_relation.relnamespace
WHERE namespace.nspname = current_schema()
  AND table_relation.relname = ANY(%(relation_names)s)
ORDER BY table_relation.relname, constraint_item.contype, constraint_item.oid
"""
_CONSTRAINT_MANIFEST = (
    ("translation_jobs", "p", "primary key (id)"),
    ("work_units", "p", "primary key (id)"),
    ("work_units", "u", "unique (job_id, sequence)"),
    ("work_unit_attempts", "p", "primary key (id)"),
    ("scheduler_events", "p", "primary key (id)"),
    ("worker_heartbeats", "p", "primary key (worker_id)"),
    ("provider_slots", "p", "primary key (provider_id, channel_id, slot_index)"),
    ("provider_slots", "c", "check ((slot_index >= 0))"),
    ("provider_slot_leases", "p", "primary key (id)"),
    ("provider_slot_leases", "u", "unique (lease_token)"),
    (
        "provider_slot_leases",
        "c",
        "check ((status = any (array['active'::text, 'released'::text, 'expired'::text])))",
    ),
    ("work_units", "f", "foreign key (job_id) references translation_jobs(id)"),
    (
        "work_unit_attempts",
        "f",
        "foreign key (work_unit_id) references work_units(id)",
    ),
    (
        "work_unit_attempts",
        "f",
        "foreign key (job_id) references translation_jobs(id)",
    ),
    (
        "scheduler_events",
        "f",
        "foreign key (job_id) references translation_jobs(id)",
    ),
    (
        "provider_slot_leases",
        "f",
        "foreign key (job_id) references translation_jobs(id)",
    ),
    (
        "provider_slot_leases",
        "f",
        "foreign key (work_unit_id) references work_units(id)",
    ),
    (
        "provider_slot_leases",
        "f",
        "foreign key (provider_id, channel_id, slot_index) references provider_slots(provider_id, channel_id, slot_index)",
    ),
)
_INDEX_CATALOG_SQL = """
SELECT index_relation.relname AS index_name, table_relation.relname AS table_name,
       pg_catalog.pg_get_indexdef(index_relation.oid) AS definition
FROM pg_catalog.pg_index index_item
JOIN pg_catalog.pg_class index_relation ON index_relation.oid = index_item.indexrelid
JOIN pg_catalog.pg_class table_relation ON table_relation.oid = index_item.indrelid
JOIN pg_catalog.pg_namespace namespace ON namespace.oid = table_relation.relnamespace
WHERE namespace.nspname = current_schema()
  AND index_relation.relname IN (
      'provider_slot_leases_active_slot_idx',
      'provider_slot_leases_active_work_unit_idx'
  )
ORDER BY index_relation.relname
"""


def run_postgres_migrations(connection) -> None:
    """Validate or stamp a legacy v1 baseline, then apply all pending immutable migrations."""
    with connection.transaction():
        _acquire_lock(connection)
        _ensure_ledger(connection)
        applied = _read_and_validate_ledger(connection)
        if not applied:
            relation_names = _existing_baseline_relations(connection)
            if relation_names.intersection(
                _STRICT_DOCX_RELATIONS + _V3_STRICT_DOCX_RELATIONS
            ):
                raise PostgresMigrationBootstrapError(
                    "unversioned strict DOCX relation exists without migration ledger"
                )
            if relation_names:
                _validate_legacy_v1_baseline(connection, relation_names)
                _record_migration(connection, MIGRATIONS[0])

    while True:
        with connection.transaction():
            _acquire_lock(connection)
            _ensure_ledger(connection)
            applied = _read_and_validate_ledger(connection)
            pending = next(
                (item for item in MIGRATIONS if item.version not in applied), None
            )
            if pending is None:
                return
            connection.execute(pending.sql_payload)
            _record_migration(connection, pending)


def _acquire_lock(connection) -> None:
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%(migration_lock_key)s))",
        {"migration_lock_key": _MIGRATION_LOCK_KEY},
    )


def _ensure_ledger(connection) -> None:
    connection.execute(_LEDGER_SQL)


def _read_and_validate_ledger(connection) -> dict[int, str]:
    rows = connection.execute(
        "SELECT version, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied = {row["version"]: row["checksum"] for row in rows}
    known_versions = {migration.version for migration in MIGRATIONS}
    if not set(applied).issubset(known_versions):
        raise PostgresMigrationBootstrapError(
            "schema_migrations has an unknown version"
        )
    for expected_version, actual_version in enumerate(sorted(applied), start=1):
        if actual_version != expected_version:
            raise PostgresMigrationBootstrapError(
                "schema_migrations history is non-contiguous"
            )
    for migration in MIGRATIONS:
        if (
            migration.version in applied
            and applied[migration.version] != migration.checksum
        ):
            raise PostgresMigrationBootstrapError("schema_migrations checksum mismatch")
    return applied


def _existing_baseline_relations(connection) -> set[str]:
    rows = connection.execute(
        _BASELINE_RELATIONS_SQL, {"relation_names": list(_PRE_LEDGER_RELATIONS)}
    ).fetchall()
    return {row["relname"] for row in rows}


def _validate_legacy_v1_baseline(connection, relation_names: set[str]) -> None:
    if relation_names != set(_BASELINE_RELATIONS):
        raise PostgresMigrationBootstrapError(
            "legacy scheduler baseline is partial or unknown"
        )
    parameters = {"relation_names": list(_BASELINE_RELATIONS)}
    column_rows = connection.execute(_COLUMN_CATALOG_SQL, parameters).fetchall()
    actual_columns = {table_name: [] for table_name in _BASELINE_RELATIONS}
    for row in column_rows:
        actual_columns[row["table_name"]].append(
            (
                row["column_name"],
                row["type_name"],
                row["not_null"],
                _normalise_default(row["default_expr"]),
            )
        )
    expected_columns = {
        table_name: [
            (name, type_name, not_null, _normalise_default(default))
            for name, type_name, not_null, default in columns
        ]
        for table_name, columns in _COLUMN_MANIFEST.items()
    }
    if actual_columns != expected_columns:
        raise PostgresMigrationBootstrapError(
            "legacy scheduler baseline column manifest mismatch"
        )

    constraints = connection.execute(_CONSTRAINT_CATALOG_SQL, parameters).fetchall()
    actual_constraints = tuple(
        sorted(
            (row["table_name"], row["contype"], _normalise_sql(row["definition"]))
            for row in constraints
        )
    )
    expected_constraints = tuple(
        sorted(
            (table_name, constraint_type, _normalise_sql(definition))
            for table_name, constraint_type, definition in _CONSTRAINT_MANIFEST
        )
    )
    if actual_constraints != expected_constraints:
        raise PostgresMigrationBootstrapError(
            "legacy scheduler baseline constraint manifest mismatch"
        )

    indexes = connection.execute(_INDEX_CATALOG_SQL).fetchall()
    expected_indexes = {
        "provider_slot_leases_active_slot_idx": "on provider_slot_leases using btree (provider_id, channel_id, slot_index) where (status = 'active'::text)",
        "provider_slot_leases_active_work_unit_idx": "on provider_slot_leases using btree (work_unit_id) where (status = 'active'::text)",
    }
    actual_indexes = {
        row["index_name"]: (row["table_name"], _normalise_sql(row["definition"]))
        for row in indexes
    }
    for index_name, definition in expected_indexes.items():
        actual = actual_indexes.get(index_name)
        if (
            actual is None
            or actual[0] != "provider_slot_leases"
            or _normalise_sql(definition) not in actual[1]
        ):
            raise PostgresMigrationBootstrapError(
                "legacy scheduler baseline index manifest mismatch"
            )


def _record_migration(connection, migration: PostgresMigration) -> None:
    connection.execute(
        "INSERT INTO schema_migrations (version, checksum) VALUES (%(version)s, %(checksum)s)",
        {"version": migration.version, "checksum": migration.checksum},
    )


def _normalise_default(value: str | None) -> str | None:
    if value is None:
        return None
    return _normalise_sql(value).removesuffix("::integer").removesuffix("::boolean")


def _normalise_sql(value: str) -> str:
    return " ".join(value.lower().split())
