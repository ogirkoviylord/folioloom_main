#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

KNOWN_TABLES = (
    "translation_jobs",
    "work_units",
    "work_unit_attempts",
    "scheduler_events",
    "worker_heartbeats",
)


@dataclass(frozen=True)
class DatabaseSettings:
    user: str
    database: str
    password: str


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        values[key] = value
    return values


def database_settings_from_env(env: dict[str, str]) -> DatabaseSettings:
    dsn = env.get("POSTGRES_DSN") or env.get("DATABASE_URL") or ""
    parsed = urlparse(dsn)
    if parsed.scheme.startswith("postgres") and parsed.path:
        return DatabaseSettings(
            user=unquote(parsed.username or env.get("POSTGRES_USER") or "translator"),
            database=unquote(
                parsed.path.lstrip("/") or env.get("POSTGRES_DB") or "translator"
            ),
            password=unquote(
                parsed.password or env.get("POSTGRES_PASSWORD") or "translator"
            ),
        )
    return DatabaseSettings(
        user=env.get("POSTGRES_USER") or "translator",
        database=env.get("POSTGRES_DB") or "translator",
        password=env.get("POSTGRES_PASSWORD") or "translator",
    )


def storage_archive_name(storage_root: Path) -> str:
    if storage_root.is_absolute():
        return storage_root.name
    return storage_root.as_posix().rstrip("/")


def host_runtime_path(path: Path) -> Path:
    """Map compose container runtime paths back to the host ./var directory."""
    path_text = path.as_posix()
    for container_prefix in ("/data", "/app/var"):
        if path_text == container_prefix:
            return Path("var")
        if path_text.startswith(f"{container_prefix}/"):
            return Path("var") / path_text[len(container_prefix) + 1 :]
    return path


def count_files(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_backup_counts(
    *,
    row_counts: dict[str, int],
    storage_file_count: int,
    allow_empty_database: bool,
) -> None:
    if allow_empty_database:
        return
    if storage_file_count > 0 and row_counts.get("translation_jobs", 0) == 0:
        raise RuntimeError(
            "database dump looks empty while object storage contains files; "
            "rerun with --allow-empty-database only if this is expected"
        )


def build_compose_exec_command(
    *,
    compose_command: str,
    compose_file: Path,
    service: str,
    password: str,
    executable: str,
    arguments: list[str],
) -> list[str]:
    command = shlex.split(compose_command)
    command.extend(["-f", str(compose_file), "exec", "-T"])
    if password:
        command.extend(["-e", f"PGPASSWORD={password}"])
    command.extend([service, executable])
    command.extend(arguments)
    return command


def run_command(command: list[str], *, stdout_path: Path | None = None) -> str:
    if stdout_path is None:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout
    with stdout_path.open("wb") as output:
        subprocess.run(command, check=True, stdout=output)
    return ""


def dump_database(
    *,
    compose_command: str,
    compose_file: Path,
    service: str,
    settings: DatabaseSettings,
    output_path: Path,
) -> None:
    command = build_compose_exec_command(
        compose_command=compose_command,
        compose_file=compose_file,
        service=service,
        password=settings.password,
        executable="pg_dump",
        arguments=[
            "-U",
            settings.user,
            "-d",
            settings.database,
            "--no-owner",
            "--no-privileges",
        ],
    )
    run_command(command, stdout_path=output_path)


def fetch_row_counts(
    *,
    compose_command: str,
    compose_file: Path,
    service: str,
    settings: DatabaseSettings,
) -> dict[str, int]:
    sql = " union all ".join(
        f"select '{table}=' || count(*) from public.{table}" for table in KNOWN_TABLES
    )
    command = build_compose_exec_command(
        compose_command=compose_command,
        compose_file=compose_file,
        service=service,
        password=settings.password,
        executable="psql",
        arguments=[
            "-U",
            settings.user,
            "-d",
            settings.database,
            "-At",
            "-c",
            sql,
        ],
    )
    output = run_command(command)
    counts: dict[str, int] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        counts[key] = int(value)
    return counts


def archive_storage(*, storage_root: Path, output_path: Path) -> None:
    if not storage_root.exists():
        raise FileNotFoundError(f"Object storage root not found: {storage_root}")
    with tarfile.open(output_path, "w:gz") as archive:
        archive.add(storage_root, arcname=storage_archive_name(storage_root))


def archive_runtime_files(
    *,
    storage_root: Path,
    admin_db_path: Path,
    output_path: Path,
) -> None:
    if not storage_root.exists():
        raise FileNotFoundError(f"Object storage root not found: {storage_root}")
    if not admin_db_path.exists():
        raise FileNotFoundError(f"Admin database not found: {admin_db_path}")
    storage_root = storage_root.resolve()
    admin_db_path = admin_db_path.resolve()
    runtime_root = _runtime_archive_root(storage_root, admin_db_path)
    archive_base = runtime_root.parent
    with tarfile.open(output_path, "w:gz") as archive:
        archive.add(runtime_root, arcname=runtime_root.relative_to(archive_base))


def _runtime_archive_base(storage_root: Path, admin_db_path: Path) -> Path:
    return _runtime_archive_root(storage_root, admin_db_path).parent


def _runtime_archive_root(storage_root: Path, admin_db_path: Path) -> Path:
    storage_root = storage_root.resolve()
    admin_db_path = admin_db_path.resolve()
    common_root = Path(
        os.path.commonpath(
            [
                str(storage_root),
                str(admin_db_path),
            ]
        )
    )
    if common_root.name == "var":
        return common_root
    return common_root


def write_manifest(
    *,
    manifest_path: Path,
    created_at: datetime,
    env_file: Path,
    compose_file: Path,
    postgres_service: str,
    db_settings: DatabaseSettings,
    runtime_root: Path,
    storage_root: Path,
    admin_db_path: Path,
    row_counts: dict[str, int],
    storage_file_count: int,
    db_dump_path: Path,
    files_archive_path: Path,
) -> None:
    manifest = {
        "created_at": created_at.isoformat(),
        "env_file": str(env_file),
        "compose_file": str(compose_file),
        "postgres_service": postgres_service,
        "postgres_user": db_settings.user,
        "postgres_database": db_settings.database,
        "runtime_root": str(runtime_root),
        "object_storage_root": str(storage_root),
        "admin_db_path": str(admin_db_path),
        "row_counts": row_counts,
        "storage_file_count": storage_file_count,
        "database_dump": {
            "path": str(db_dump_path),
            "size_bytes": db_dump_path.stat().st_size,
            "sha256": sha256_file(db_dump_path),
        },
        "files_archive": {
            "path": str(files_archive_path),
            "size_bytes": files_archive_path.stat().st_size,
            "sha256": sha256_file(files_archive_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _manifest_artifact_path(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return manifest_path.parent / path


def _verify_manifest_artifact(
    *,
    manifest_path: Path,
    manifest: dict[str, object],
    key: str,
) -> None:
    artifact = manifest.get(key)
    if not isinstance(artifact, dict):
        raise RuntimeError(f"manifest is missing {key}")
    raw_path = artifact.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise RuntimeError(f"manifest {key} path is missing")
    path = _manifest_artifact_path(manifest_path, raw_path)
    if not path.exists():
        raise RuntimeError(f"backup artifact does not exist: {path}")
    expected_size = artifact.get("size_bytes")
    if expected_size is not None and path.stat().st_size != expected_size:
        raise RuntimeError(
            f"size mismatch for {path}: {path.stat().st_size} != {expected_size}"
        )
    expected_hash = artifact.get("sha256")
    if isinstance(expected_hash, str) and sha256_file(path) != expected_hash:
        raise RuntimeError(f"sha256 mismatch for {path}")


def _verify_runtime_archive_contains_admin_db(
    *,
    manifest_path: Path,
    manifest: dict[str, object],
) -> None:
    raw_admin_db_path = manifest.get("admin_db_path")
    if not isinstance(raw_admin_db_path, str) or not raw_admin_db_path:
        return
    artifact = manifest.get("files_archive")
    if not isinstance(artifact, dict):
        raise RuntimeError("manifest is missing files_archive")
    raw_archive_path = artifact.get("path")
    if not isinstance(raw_archive_path, str) or not raw_archive_path:
        raise RuntimeError("manifest files_archive path is missing")
    archive_path = _manifest_artifact_path(manifest_path, raw_archive_path)
    admin_db_member = raw_admin_db_path.strip("/")
    with tarfile.open(archive_path, "r:gz") as archive:
        names = set(archive.getnames())
        if admin_db_member not in names:
            raise RuntimeError(
                f"runtime archive is missing admin.sqlite3: {admin_db_member}"
            )
        member = archive.getmember(admin_db_member)
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RuntimeError(
                "runtime archive admin.sqlite3 is not a file: "
                f"{admin_db_member}"
            )
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
            handle.write(extracted.read())
            handle.flush()
            connection = sqlite3.connect(handle.name)
            try:
                result = connection.execute("PRAGMA integrity_check").fetchone()
            finally:
                connection.close()
            if result is None or result[0] != "ok":
                raise RuntimeError(
                    "runtime archive admin.sqlite3 failed integrity_check"
                )


def verify_backup_manifest(
    manifest_path: Path,
    *,
    allow_empty_database: bool,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row_counts = manifest.get("row_counts")
    if not isinstance(row_counts, dict):
        raise RuntimeError("manifest row_counts is missing")
    storage_file_count = int(manifest.get("storage_file_count") or 0)
    validate_backup_counts(
        row_counts={str(key): int(value) for key, value in row_counts.items()},
        storage_file_count=storage_file_count,
        allow_empty_database=allow_empty_database,
    )
    _verify_manifest_artifact(
        manifest_path=manifest_path,
        manifest=manifest,
        key="database_dump",
    )
    _verify_manifest_artifact(
        manifest_path=manifest_path,
        manifest=manifest,
        key="files_archive",
    )
    _verify_runtime_archive_contains_admin_db(
        manifest_path=manifest_path,
        manifest=manifest,
    )


def run_backup(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    env_file = Path(args.env_file)
    compose_file = Path(args.compose_file)
    output_dir = Path(args.output_dir)
    env = parse_env_file(env_file)
    storage_root = host_runtime_path(
        Path(
            args.storage_root
            or env.get("OBJECT_STORAGE_ROOT")
            or "var/object-storage"
        )
    )
    admin_db_path = host_runtime_path(
        Path(args.admin_db_path or env.get("ADMIN_DB_PATH") or "var/admin.sqlite3")
    )
    runtime_root = _runtime_archive_root(storage_root, admin_db_path)
    db_settings = database_settings_from_env(env)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")

    output_dir.mkdir(parents=True, exist_ok=True)
    db_dump_path = output_dir / f"folioloom-db-{timestamp}.sql"
    files_archive_path = output_dir / f"folioloom-files-{timestamp}.tgz"
    manifest_path = output_dir / f"folioloom-backup-{timestamp}.manifest.json"

    dump_database(
        compose_command=args.compose_command,
        compose_file=compose_file,
        service=args.postgres_service,
        settings=db_settings,
        output_path=db_dump_path,
    )
    row_counts = fetch_row_counts(
        compose_command=args.compose_command,
        compose_file=compose_file,
        service=args.postgres_service,
        settings=db_settings,
    )
    archive_runtime_files(
        storage_root=storage_root,
        admin_db_path=admin_db_path,
        output_path=files_archive_path,
    )
    storage_file_count = count_files(storage_root)
    validate_backup_counts(
        row_counts=row_counts,
        storage_file_count=storage_file_count,
        allow_empty_database=args.allow_empty_database,
    )
    write_manifest(
        manifest_path=manifest_path,
        created_at=datetime.now(UTC),
        env_file=env_file,
        compose_file=compose_file,
        postgres_service=args.postgres_service,
        db_settings=db_settings,
        runtime_root=runtime_root,
        storage_root=storage_root,
        admin_db_path=admin_db_path,
        row_counts=row_counts,
        storage_file_count=storage_file_count,
        db_dump_path=db_dump_path,
        files_archive_path=files_archive_path,
    )
    return db_dump_path, files_archive_path, manifest_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a FolioLoom PostgreSQL and object-storage backup."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--compose-file", default="docker-compose.yml")
    parser.add_argument("--compose-command", default="docker compose")
    parser.add_argument("--postgres-service", default="postgres")
    parser.add_argument("--storage-root", default="")
    parser.add_argument("--admin-db-path", default="")
    parser.add_argument("--output-dir", default="folioloom_exports")
    parser.add_argument(
        "--allow-empty-database",
        action="store_true",
        help=(
            "Allow backups where object storage has files but translation_jobs "
            "is empty."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        db_dump_path, files_archive_path, manifest_path = run_backup(args)
    except Exception as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        return 1

    green = "\033[32m"
    reset = "\033[0m"
    print(f"{green}FolioLoom backup created successfully{reset}")
    print(f"Database dump: {db_dump_path}")
    print(f"Files archive:  {files_archive_path}")
    print(f"Manifest:       {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
