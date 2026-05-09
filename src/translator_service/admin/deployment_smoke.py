from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from translator_service.admin.secrets import (
    SecretStoreUnavailable,
    SQLiteEncryptedSecretStore,
)
from translator_service.ai_provider_runtime import load_ai_provider_runtime_keys
from translator_service.config import Settings


class AdminDeploymentCheckError(RuntimeError):
    pass


def check_admin_runtime_configuration(
    settings: Settings,
    *,
    require_admin_provider_keys: bool = False,
    require_existing_admin_db: bool = False,
) -> dict[str, Any]:
    _validate_required_admin_settings(settings)
    db_path = Path(settings.admin_db_path)
    if require_existing_admin_db and not db_path.exists():
        raise AdminDeploymentCheckError(f"ADMIN_DB_PATH does not exist: {db_path}")
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_secret_store(db_path, settings.admin_secret_master_key)

    active_keys = load_ai_provider_runtime_keys(settings, provider_id="deepseek")
    if require_admin_provider_keys and not active_keys:
        raise AdminDeploymentCheckError(
            "No active DeepSeek admin provider keys found in ADMIN_DB_PATH"
        )

    _record_probe(db_path)
    return {
        "status": "ok",
        "admin_db_path": str(db_path),
        "deepseek_active_key_count": len(active_keys),
        "checked_at": datetime.now(UTC).isoformat(),
    }


def _validate_required_admin_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("ADMIN_DB_PATH", settings.admin_db_path),
            ("ADMIN_OWNER_PASSWORD", settings.admin_owner_password),
            ("ADMIN_SESSION_SECRET", settings.admin_session_secret),
            ("ADMIN_SECRET_MASTER_KEY", settings.admin_secret_master_key),
        )
        if not value
    ]
    if missing:
        raise AdminDeploymentCheckError(
            "Missing production admin configuration: " + ", ".join(missing)
        )
    if len(settings.admin_session_secret) < 16:
        raise AdminDeploymentCheckError("ADMIN_SESSION_SECRET is too short")
    if len(settings.admin_owner_password) < 12:
        raise AdminDeploymentCheckError("ADMIN_OWNER_PASSWORD is too short")


def _validate_secret_store(db_path: Path, master_key: str) -> None:
    try:
        with SQLiteEncryptedSecretStore(db_path, master_key=master_key):
            pass
    except SecretStoreUnavailable as error:
        raise AdminDeploymentCheckError(str(error)) from error


def _record_probe(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_deployment_smoke_checks (
                    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checked_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO admin_deployment_smoke_checks (checked_at) VALUES (?)",
                (datetime.now(UTC).isoformat(),),
            )
    finally:
        connection.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify deployed admin runtime configuration."
    )
    parser.add_argument(
        "--require-admin-provider-keys",
        action="store_true",
        help="Fail unless at least one active DeepSeek key is stored in admin DB.",
    )
    parser.add_argument(
        "--require-existing-admin-db",
        action="store_true",
        help="Fail if ADMIN_DB_PATH does not already exist.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = check_admin_runtime_configuration(
            Settings(),
            require_admin_provider_keys=args.require_admin_provider_keys,
            require_existing_admin_db=args.require_existing_admin_db,
        )
    except Exception as error:
        print(f"Admin deployment smoke check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
