import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePath


class StoredFileKind(StrEnum):
    QUARANTINE = "quarantine"
    ORIGINAL = "original"
    INTERMEDIATE = "intermediate"
    PARTIAL = "partial"
    FINAL = "final"


@dataclass(frozen=True)
class StoredFile:
    object_key: str
    kind: StoredFileKind
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


class ObjectPublishError(Exception):
    """An object could not be safely published with its metadata."""


class LocalObjectStorage:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def put_bytes(
        self,
        *,
        kind: StoredFileKind,
        file_name: str,
        content_type: str,
        content: bytes,
    ) -> StoredFile:
        if not content:
            raise ValueError("Stored file content must not be empty")

        created_at = datetime.now(UTC)
        digest = sha256(content).hexdigest()
        safe_file_name = _safe_file_name(file_name)
        object_key = f"{kind.value}/{digest[:16]}-{safe_file_name}"
        path = self._path_for_key(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

        stored = StoredFile(
            object_key=object_key,
            kind=kind,
            file_name=PurePath(file_name).name,
            content_type=content_type,
            size_bytes=len(content),
            sha256=digest,
            created_at=created_at,
        )
        self._write_metadata(stored)
        return stored

    def put_bytes_if_absent(
        self,
        *,
        kind: StoredFileKind,
        file_name: str,
        content_type: str,
        content: bytes,
    ) -> tuple[StoredFile, bool]:
        """Store content without replacing an existing object at the same key."""
        if not content:
            raise ValueError("Stored file content must not be empty")

        created_at = datetime.now(UTC)
        digest = sha256(content).hexdigest()
        safe_file_name = _safe_file_name(file_name)
        object_key = f"{kind.value}/{digest[:16]}-{safe_file_name}"
        path = self._path_for_key(object_key)
        stored = StoredFile(
            object_key=object_key,
            kind=kind,
            file_name=PurePath(file_name).name,
            content_type=content_type,
            size_bytes=len(content),
            sha256=digest,
            created_at=created_at,
        )

        with self._liveness_lock(object_key):
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(
                    path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
            except FileExistsError:
                # The creator publishes bytes and metadata under this lock, so
                # a reuser cannot observe the object/metadata visibility gap.
                self._require_matching_content(path, stored)
                try:
                    existing = self.get_metadata(object_key)
                except (
                    FileNotFoundError,
                    OSError,
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    self._write_metadata(stored)
                    existing = stored
                else:
                    if not self._metadata_matches_content(existing, stored):
                        self._write_metadata(stored)
                        existing = stored
                self._retention_path_for_key(object_key).touch(exist_ok=True)
                return existing, False
            with os.fdopen(descriptor, "wb") as object_file:
                object_file.write(content)
            self._write_metadata(stored)
            return stored, True

    def get_bytes(self, object_key: str) -> bytes:
        return self._path_for_existing_key(object_key).read_bytes()

    def get_metadata(self, object_key: str) -> StoredFile:
        metadata_path = self._metadata_path_for_key(object_key)
        if not metadata_path.exists():
            raise FileNotFoundError(object_key)

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return StoredFile(
            object_key=metadata["object_key"],
            kind=StoredFileKind(metadata["kind"]),
            file_name=metadata["file_name"],
            content_type=metadata["content_type"],
            size_bytes=int(metadata["size_bytes"]),
            sha256=metadata["sha256"],
            created_at=datetime.fromisoformat(metadata["created_at"]),
        )

    def exists(self, object_key: str) -> bool:
        try:
            path = self._path_for_key(object_key)
        except ValueError:
            return False
        return path.exists() and self._metadata_path_for_key(object_key).exists()

    def delete(self, object_key: str) -> bool:
        existed = self.exists(object_key)
        if not existed:
            return False

        self._path_for_key(object_key).unlink(missing_ok=True)
        self._metadata_path_for_key(object_key).unlink(missing_ok=True)
        return True

    def delete_if_unretained(self, object_key: str) -> bool:
        """Delete a creator-owned object only when no reuser retained it."""
        with self._liveness_lock(object_key):
            if self._retention_path_for_key(object_key).exists():
                return False
            return self.delete(object_key)

    def _write_metadata(self, stored: StoredFile) -> None:
        metadata_path = self._metadata_path_for_key(stored.object_key)
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{metadata_path.name}.",
                suffix=".tmp",
                dir=metadata_path.parent,
            )
            temporary_path = Path(temporary_name)
            payload = json.dumps(
                {
                    "object_key": stored.object_key,
                    "kind": stored.kind.value,
                    "file_name": stored.file_name,
                    "content_type": stored.content_type,
                    "size_bytes": stored.size_bytes,
                    "sha256": stored.sha256,
                    "created_at": stored.created_at.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            with os.fdopen(descriptor, "wb") as metadata_file:
                metadata_file.write(payload)
                metadata_file.flush()
                os.fsync(metadata_file.fileno())
            os.replace(temporary_path, metadata_path)
            temporary_path = None
        except OSError as error:
            raise ObjectPublishError("metadata publication failed") from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _metadata_matches_content(existing: StoredFile, stored: StoredFile) -> bool:
        return (
            existing.object_key == stored.object_key
            and existing.kind is stored.kind
            and existing.size_bytes == stored.size_bytes
            and existing.sha256 == stored.sha256
        )

    def _require_matching_content(self, path: Path, stored: StoredFile) -> None:
        try:
            content = path.read_bytes()
        except OSError as error:
            raise ObjectPublishError("existing object could not be read") from error
        if (
            len(content) != stored.size_bytes
            or sha256(content).hexdigest() != stored.sha256
        ):
            raise ObjectPublishError("existing object content does not match")

    @contextmanager
    def _liveness_lock(self, object_key: str):
        lock_path = self._path_for_key(f"{object_key}.intake.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _retention_path_for_key(self, object_key: str) -> Path:
        return self._path_for_key(f"{object_key}.intake.retained")

    def _path_for_existing_key(self, object_key: str) -> Path:
        path = self._path_for_key(object_key)
        if not path.exists():
            raise FileNotFoundError(object_key)
        return path

    def _metadata_path_for_key(self, object_key: str) -> Path:
        return self._path_for_key(f"{object_key}.metadata.json")

    def _path_for_key(self, object_key: str) -> Path:
        parts = object_key.split("/")
        if (
            object_key.startswith("/")
            or not parts
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError(f"Invalid object key: {object_key}")

        root = self._root.resolve()
        path = root.joinpath(*parts).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"Object key escapes storage root: {object_key}")
        return path


def _safe_file_name(file_name: str) -> str:
    base_name = PurePath(file_name).name.strip()
    if not base_name:
        return "file"

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name)
    safe = re.sub(r"_+", "_", safe).strip("._")
    return safe or "file"
