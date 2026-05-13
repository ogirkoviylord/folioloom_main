from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

_SQLITE_BUSY_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class AIProviderRuntimeChannel:
    label: str
    weight: int
    max_parallel_requests: int
    active_requests: int = 0
    health: str = "healthy"
    cooldown_remaining_seconds: float = 0.0
    total_started_requests: int = 0
    total_successful_requests: int = 0
    total_temporary_failures: int = 0
    total_permanent_failures: int = 0
    total_rate_limit_failures: int = 0
    total_unavailable_failures: int = 0
    total_timeout_failures: int = 0
    total_malformed_response_failures: int = 0
    total_auth_failures: int = 0
    total_billing_failures: int = 0
    total_other_provider_failures: int = 0
    average_latency_ms: float | None = None
    last_latency_ms: float | None = None
    error_kind: str | None = None
    last_error_excerpt: str | None = None

    def __repr__(self) -> str:
        error_kind = self.error_kind if self.error_kind is None else "<redacted>"
        last_error_excerpt = (
            self.last_error_excerpt if self.last_error_excerpt is None else "<redacted>"
        )
        return (
            "AIProviderRuntimeChannel("
            f"label={self.label!r}, "
            f"weight={self.weight!r}, "
            f"max_parallel_requests={self.max_parallel_requests!r}, "
            f"active_requests={self.active_requests!r}, "
            f"health={self.health!r}, "
            f"cooldown_remaining_seconds={self.cooldown_remaining_seconds!r}, "
            f"total_started_requests={self.total_started_requests!r}, "
            f"total_successful_requests={self.total_successful_requests!r}, "
            f"total_temporary_failures={self.total_temporary_failures!r}, "
            f"total_permanent_failures={self.total_permanent_failures!r}, "
            f"total_rate_limit_failures={self.total_rate_limit_failures!r}, "
            f"total_unavailable_failures={self.total_unavailable_failures!r}, "
            f"total_timeout_failures={self.total_timeout_failures!r}, "
            "total_malformed_response_failures="
            f"{self.total_malformed_response_failures!r}, "
            f"total_auth_failures={self.total_auth_failures!r}, "
            f"total_billing_failures={self.total_billing_failures!r}, "
            "total_other_provider_failures="
            f"{self.total_other_provider_failures!r}, "
            f"average_latency_ms={self.average_latency_ms!r}, "
            f"last_latency_ms={self.last_latency_ms!r}, "
            f"error_kind={error_kind!r}, "
            f"last_error_excerpt={last_error_excerpt!r})"
        )


@dataclass(frozen=True)
class AIProviderRuntimeProviderState:
    adaptive_enabled: bool = False
    current_limit: int = 1
    max_capacity: int = 1
    active_requests: int = 0
    available_slots: int = 1
    circuit_state: str = "closed"
    circuit_open_remaining_seconds: float = 0.0
    last_reason: str | None = None
    total_ramp_ups: int = 0
    total_decreases: int = 0
    total_circuit_opened: int = 0

    def __repr__(self) -> str:
        last_reason = self.last_reason if self.last_reason is None else "<redacted>"
        return (
            "AIProviderRuntimeProviderState("
            f"adaptive_enabled={self.adaptive_enabled!r}, "
            f"current_limit={self.current_limit!r}, "
            f"max_capacity={self.max_capacity!r}, "
            f"active_requests={self.active_requests!r}, "
            f"available_slots={self.available_slots!r}, "
            f"circuit_state={self.circuit_state!r}, "
            "circuit_open_remaining_seconds="
            f"{self.circuit_open_remaining_seconds!r}, "
            f"last_reason={last_reason!r}, "
            f"total_ramp_ups={self.total_ramp_ups!r}, "
            f"total_decreases={self.total_decreases!r}, "
            f"total_circuit_opened={self.total_circuit_opened!r})"
        )


@dataclass(frozen=True)
class AIProviderRuntimeStatus:
    provider_id: str
    source: str
    status: str
    reload_interval_seconds: float
    last_reloaded_at: datetime
    active_channels: tuple[AIProviderRuntimeChannel, ...]
    provider_state: AIProviderRuntimeProviderState = AIProviderRuntimeProviderState()
    error: str | None = None


@dataclass(frozen=True)
class AIProviderRuntimeReloadRequest:
    request_id: str
    provider_id: str
    actor_id: str
    requested_at: datetime
    consumed_at: datetime | None = None

    @property
    def pending(self) -> bool:
        return self.consumed_at is None


class SQLiteAIProviderRuntimeStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            timeout=_SQLITE_BUSY_TIMEOUT_SECONDS,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            f"PRAGMA busy_timeout = {int(_SQLITE_BUSY_TIMEOUT_SECONDS * 1000)}"
        )
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteAIProviderRuntimeStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def record_status(
        self,
        *,
        provider_id: str,
        source: str,
        status: str,
        reload_interval_seconds: float,
        active_channels: tuple[AIProviderRuntimeChannel, ...],
        error: str | None,
        provider_state: AIProviderRuntimeProviderState | None = None,
    ) -> AIProviderRuntimeStatus:
        now = datetime.now(UTC)
        payload = json.dumps(
            [
                {
                    "label": channel.label,
                    "weight": _int_at_least(channel.weight, minimum=1, default=1),
                    "max_parallel_requests": _int_at_least(
                        channel.max_parallel_requests,
                        minimum=1,
                        default=1,
                    ),
                    "active_requests": _int_at_least(
                        channel.active_requests,
                        minimum=0,
                        default=0,
                    ),
                    "health": _string_or_default(channel.health, "healthy"),
                    "cooldown_remaining_seconds": _float_at_least(
                        channel.cooldown_remaining_seconds,
                        minimum=0.0,
                        default=0.0,
                    ),
                    "total_started_requests": _int_at_least(
                        channel.total_started_requests,
                        minimum=0,
                        default=0,
                    ),
                    "total_successful_requests": _int_at_least(
                        channel.total_successful_requests,
                        minimum=0,
                        default=0,
                    ),
                    "total_temporary_failures": _int_at_least(
                        channel.total_temporary_failures,
                        minimum=0,
                        default=0,
                    ),
                    "total_permanent_failures": _int_at_least(
                        channel.total_permanent_failures,
                        minimum=0,
                        default=0,
                    ),
                    "total_rate_limit_failures": _int_at_least(
                        channel.total_rate_limit_failures,
                        minimum=0,
                        default=0,
                    ),
                    "total_unavailable_failures": _int_at_least(
                        channel.total_unavailable_failures,
                        minimum=0,
                        default=0,
                    ),
                    "total_timeout_failures": _int_at_least(
                        channel.total_timeout_failures,
                        minimum=0,
                        default=0,
                    ),
                    "total_malformed_response_failures": _int_at_least(
                        channel.total_malformed_response_failures,
                        minimum=0,
                        default=0,
                    ),
                    "total_auth_failures": _int_at_least(
                        channel.total_auth_failures,
                        minimum=0,
                        default=0,
                    ),
                    "total_billing_failures": _int_at_least(
                        channel.total_billing_failures,
                        minimum=0,
                        default=0,
                    ),
                    "total_other_provider_failures": _int_at_least(
                        channel.total_other_provider_failures,
                        minimum=0,
                        default=0,
                    ),
                    "average_latency_ms": _optional_float(channel.average_latency_ms),
                    "last_latency_ms": _optional_float(channel.last_latency_ms),
                    "error_kind": _optional_string(channel.error_kind),
                    "last_error_excerpt": _optional_string(
                        channel.last_error_excerpt,
                    ),
                }
                for channel in active_channels
            ],
            sort_keys=True,
        )
        provider_state_payload = json.dumps(
            _provider_state_to_payload(
                provider_state or AIProviderRuntimeProviderState()
            ),
            sort_keys=True,
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_ai_provider_runtime_status (
                    provider_id, source, status, reload_interval_seconds,
                    active_channels_json, provider_state_json, error,
                    last_reloaded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    source = excluded.source,
                    status = excluded.status,
                    reload_interval_seconds = excluded.reload_interval_seconds,
                    active_channels_json = excluded.active_channels_json,
                    provider_state_json = excluded.provider_state_json,
                    error = excluded.error,
                    last_reloaded_at = excluded.last_reloaded_at
                """,
                (
                    provider_id,
                    source,
                    status,
                    max(0.0, float(reload_interval_seconds)),
                    payload,
                    provider_state_payload,
                    error,
                    now.isoformat(),
                ),
            )
        status_summary = self.get_status(provider_id)
        if status_summary is None:
            raise RuntimeError("Runtime status was not recorded")
        return status_summary

    def get_status(self, provider_id: str) -> AIProviderRuntimeStatus | None:
        row = self._connection.execute(
            """
            SELECT *
            FROM admin_ai_provider_runtime_status
            WHERE provider_id = ?
            """,
            (provider_id,),
        ).fetchone()
        if row is None:
            return None
        return _status_from_row(row)

    def request_reload(
        self,
        *,
        provider_id: str,
        actor_id: str,
    ) -> AIProviderRuntimeReloadRequest:
        request = AIProviderRuntimeReloadRequest(
            request_id=uuid4().hex,
            provider_id=provider_id,
            actor_id=actor_id,
            requested_at=datetime.now(UTC),
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_ai_provider_runtime_reload_requests (
                    request_id, provider_id, actor_id, requested_at, consumed_at
                )
                VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    request.request_id,
                    request.provider_id,
                    request.actor_id,
                    request.requested_at.isoformat(),
                ),
            )
        return request

    def consume_reload_request(
        self,
        provider_id: str,
    ) -> AIProviderRuntimeReloadRequest | None:
        row = self._connection.execute(
            """
            SELECT *
            FROM admin_ai_provider_runtime_reload_requests
            WHERE provider_id = ? AND consumed_at IS NULL
            ORDER BY datetime(requested_at), rowid
            LIMIT 1
            """,
            (provider_id,),
        ).fetchone()
        if row is None:
            return None
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                """
                UPDATE admin_ai_provider_runtime_reload_requests
                SET consumed_at = ?
                WHERE request_id = ?
                """,
                (now.isoformat(), row["request_id"]),
            )
        return AIProviderRuntimeReloadRequest(
            request_id=row["request_id"],
            provider_id=row["provider_id"],
            actor_id=row["actor_id"],
            requested_at=datetime.fromisoformat(row["requested_at"]),
            consumed_at=now,
        )

    def get_reload_state(
        self,
        provider_id: str,
    ) -> AIProviderRuntimeReloadRequest | None:
        row = self._connection.execute(
            """
            SELECT *
            FROM admin_ai_provider_runtime_reload_requests
            WHERE provider_id = ?
            ORDER BY datetime(requested_at) DESC, rowid DESC
            LIMIT 1
            """,
            (provider_id,),
        ).fetchone()
        if row is None:
            return None
        consumed_at = row["consumed_at"]
        return AIProviderRuntimeReloadRequest(
            request_id=row["request_id"],
            provider_id=row["provider_id"],
            actor_id=row["actor_id"],
            requested_at=datetime.fromisoformat(row["requested_at"]),
            consumed_at=(
                datetime.fromisoformat(consumed_at) if consumed_at is not None else None
            ),
        )

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_ai_provider_runtime_status (
                    provider_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reload_interval_seconds REAL NOT NULL,
                    active_channels_json TEXT NOT NULL,
                    provider_state_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    last_reloaded_at TEXT NOT NULL
                )
                """
            )
            status_columns = {
                row["name"]
                for row in self._connection.execute(
                    "PRAGMA table_info(admin_ai_provider_runtime_status)"
                ).fetchall()
            }
            if "provider_state_json" not in status_columns:
                self._connection.execute(
                    """
                    ALTER TABLE admin_ai_provider_runtime_status
                    ADD COLUMN provider_state_json TEXT NOT NULL DEFAULT '{}'
                    """
                )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_ai_provider_runtime_reload_requests (
                    request_id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    consumed_at TEXT
                )
                """
            )


def _status_from_row(row: sqlite3.Row) -> AIProviderRuntimeStatus:
    return AIProviderRuntimeStatus(
        provider_id=row["provider_id"],
        source=row["source"],
        status=row["status"],
        reload_interval_seconds=float(row["reload_interval_seconds"]),
        last_reloaded_at=datetime.fromisoformat(row["last_reloaded_at"]),
        active_channels=tuple(
            _channel_from_payload(item)
            for item in json.loads(row["active_channels_json"])
        ),
        provider_state=_provider_state_from_payload(
            json.loads(row["provider_state_json"] or "{}")
        ),
        error=row["error"],
    )


def _provider_state_to_payload(
    provider_state: AIProviderRuntimeProviderState,
) -> dict[str, object]:
    return {
        "adaptive_enabled": bool(provider_state.adaptive_enabled),
        "current_limit": _int_at_least(
            provider_state.current_limit,
            minimum=1,
            default=1,
        ),
        "max_capacity": _int_at_least(
            provider_state.max_capacity,
            minimum=1,
            default=1,
        ),
        "active_requests": _int_at_least(
            provider_state.active_requests,
            minimum=0,
            default=0,
        ),
        "available_slots": _int_at_least(
            provider_state.available_slots,
            minimum=0,
            default=1,
        ),
        "circuit_state": _string_or_default(
            provider_state.circuit_state,
            "closed",
        ),
        "circuit_open_remaining_seconds": _float_at_least(
            provider_state.circuit_open_remaining_seconds,
            minimum=0.0,
            default=0.0,
        ),
        "last_reason": _optional_string(provider_state.last_reason),
        "total_ramp_ups": _int_at_least(
            provider_state.total_ramp_ups,
            minimum=0,
            default=0,
        ),
        "total_decreases": _int_at_least(
            provider_state.total_decreases,
            minimum=0,
            default=0,
        ),
        "total_circuit_opened": _int_at_least(
            provider_state.total_circuit_opened,
            minimum=0,
            default=0,
        ),
    }


def _provider_state_from_payload(item: object) -> AIProviderRuntimeProviderState:
    payload = item if isinstance(item, dict) else {}
    return AIProviderRuntimeProviderState(
        adaptive_enabled=bool(payload.get("adaptive_enabled", False)),
        current_limit=_int_at_least(
            payload.get("current_limit", 1),
            minimum=1,
            default=1,
        ),
        max_capacity=_int_at_least(
            payload.get("max_capacity", 1),
            minimum=1,
            default=1,
        ),
        active_requests=_int_at_least(
            payload.get("active_requests", 0),
            minimum=0,
            default=0,
        ),
        available_slots=_int_at_least(
            payload.get("available_slots", 1),
            minimum=0,
            default=1,
        ),
        circuit_state=_string_or_default(
            payload.get("circuit_state", "closed"),
            "closed",
        ),
        circuit_open_remaining_seconds=_float_at_least(
            payload.get("circuit_open_remaining_seconds", 0.0),
            minimum=0.0,
            default=0.0,
        ),
        last_reason=_optional_string(payload.get("last_reason")),
        total_ramp_ups=_int_at_least(
            payload.get("total_ramp_ups", 0),
            minimum=0,
            default=0,
        ),
        total_decreases=_int_at_least(
            payload.get("total_decreases", 0),
            minimum=0,
            default=0,
        ),
        total_circuit_opened=_int_at_least(
            payload.get("total_circuit_opened", 0),
            minimum=0,
            default=0,
        ),
    )


def _channel_from_payload(item: object) -> AIProviderRuntimeChannel:
    payload = item if isinstance(item, dict) else {}
    return AIProviderRuntimeChannel(
        label=str(payload.get("label", "")),
        weight=_int_at_least(payload.get("weight", 1), minimum=1, default=1),
        max_parallel_requests=_int_at_least(
            payload.get("max_parallel_requests", 1),
            minimum=1,
            default=1,
        ),
        active_requests=_int_at_least(
            payload.get("active_requests", 0),
            minimum=0,
            default=0,
        ),
        health=_string_or_default(payload.get("health", "healthy"), "healthy"),
        cooldown_remaining_seconds=_float_at_least(
            payload.get("cooldown_remaining_seconds", 0.0),
            minimum=0.0,
            default=0.0,
        ),
        total_started_requests=_int_at_least(
            payload.get("total_started_requests", 0),
            minimum=0,
            default=0,
        ),
        total_successful_requests=_int_at_least(
            payload.get("total_successful_requests", 0),
            minimum=0,
            default=0,
        ),
        total_temporary_failures=_int_at_least(
            payload.get("total_temporary_failures", 0),
            minimum=0,
            default=0,
        ),
        total_permanent_failures=_int_at_least(
            payload.get("total_permanent_failures", 0),
            minimum=0,
            default=0,
        ),
        total_rate_limit_failures=_int_at_least(
            payload.get("total_rate_limit_failures", 0),
            minimum=0,
            default=0,
        ),
        total_unavailable_failures=_int_at_least(
            payload.get("total_unavailable_failures", 0),
            minimum=0,
            default=0,
        ),
        total_timeout_failures=_int_at_least(
            payload.get("total_timeout_failures", 0),
            minimum=0,
            default=0,
        ),
        total_malformed_response_failures=_int_at_least(
            payload.get("total_malformed_response_failures", 0),
            minimum=0,
            default=0,
        ),
        total_auth_failures=_int_at_least(
            payload.get("total_auth_failures", 0),
            minimum=0,
            default=0,
        ),
        total_billing_failures=_int_at_least(
            payload.get("total_billing_failures", 0),
            minimum=0,
            default=0,
        ),
        total_other_provider_failures=_int_at_least(
            payload.get("total_other_provider_failures", 0),
            minimum=0,
            default=0,
        ),
        average_latency_ms=_optional_float(payload.get("average_latency_ms")),
        last_latency_ms=_optional_float(payload.get("last_latency_ms")),
        error_kind=_optional_string(payload.get("error_kind")),
        last_error_excerpt=_optional_string(payload.get("last_error_excerpt")),
    )


def _int_at_least(value: object, *, minimum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _float_at_least(value: object, *, minimum: float, default: float) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        return default
    return max(minimum, parsed)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_or_default(value: object, default: str) -> str:
    if value is None:
        return default
    parsed = str(value)
    return parsed if parsed else default
