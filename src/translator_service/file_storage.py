import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePath

from translator_service.json_utils import read_json_file


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
        metadata_path = self._metadata_path_for_key(object_key)

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
        metadata_path.write_text(
            json.dumps(
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
            ),
            encoding="utf-8",
        )
        return stored

    def get_bytes(self, object_key: str) -> bytes:
        return self._path_for_existing_key(object_key).read_bytes()

    def get_metadata(self, object_key: str) -> StoredFile:
        metadata_path = self._metadata_path_for_key(object_key)
        if not metadata_path.exists():
            raise FileNotFoundError(object_key)

        metadata = read_json_file(metadata_path)
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
