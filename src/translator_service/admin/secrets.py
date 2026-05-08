from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretStoreUnavailable(RuntimeError):
    pass


class SecretNotFound(KeyError):
    pass


@dataclass(frozen=True)
class SecretMetadata:
    secret_id: str
    label: str
    kind: str
    fingerprint: str
    masked_value: str
    version: int
    disabled: bool
    created_at: datetime
    updated_at: datetime


class SecretStore(Protocol):
    def put_secret(
        self,
        *,
        secret_id: str,
        label: str,
        kind: str,
        plaintext: str,
        actor_id: str,
    ) -> SecretMetadata:
        pass

    def describe_secret(self, secret_id: str) -> SecretMetadata:
        pass

    def get_secret_value(self, secret_id: str) -> str:
        pass

    def disable_secret(self, secret_id: str, *, actor_id: str) -> SecretMetadata:
        pass


class SQLiteEncryptedSecretStore:
    def __init__(self, db_path: str | Path, *, master_key: str) -> None:
        self._key = _decode_master_key(master_key)
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteEncryptedSecretStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def put_secret(
        self,
        *,
        secret_id: str,
        label: str,
        kind: str,
        plaintext: str,
        actor_id: str,
    ) -> SecretMetadata:
        if not plaintext:
            raise ValueError("Secret value must not be empty")
        now = datetime.now(UTC)
        current = self._connection.execute(
            "SELECT version, created_at FROM admin_secrets WHERE secret_id = ?",
            (secret_id,),
        ).fetchone()
        version = 1 if current is None else int(current["version"]) + 1
        created_at = (
            now if current is None else datetime.fromisoformat(current["created_at"])
        )
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce,
            plaintext.encode("utf-8"),
            secret_id.encode("utf-8"),
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_secrets (
                    secret_id, label, kind, fingerprint, masked_value, version,
                    disabled, algorithm, nonce, ciphertext, created_at,
                    updated_at, updated_by
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(secret_id) DO UPDATE SET
                    label = excluded.label,
                    kind = excluded.kind,
                    fingerprint = excluded.fingerprint,
                    masked_value = excluded.masked_value,
                    version = excluded.version,
                    disabled = 0,
                    algorithm = excluded.algorithm,
                    nonce = excluded.nonce,
                    ciphertext = excluded.ciphertext,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (
                    secret_id,
                    label,
                    kind,
                    _fingerprint(plaintext),
                    _mask_secret(plaintext),
                    version,
                    "aes-256-gcm",
                    base64.b64encode(nonce).decode("ascii"),
                    base64.b64encode(ciphertext).decode("ascii"),
                    created_at.isoformat(),
                    now.isoformat(),
                    actor_id,
                ),
            )
        return self.describe_secret(secret_id)

    def describe_secret(self, secret_id: str) -> SecretMetadata:
        row = self._secret_row(secret_id)
        return _metadata_from_row(row)

    def get_secret_value(self, secret_id: str) -> str:
        row = self._secret_row(secret_id)
        if bool(row["disabled"]):
            raise SecretNotFound(secret_id)
        plaintext = AESGCM(self._key).decrypt(
            base64.b64decode(row["nonce"]),
            base64.b64decode(row["ciphertext"]),
            secret_id.encode("utf-8"),
        )
        return plaintext.decode("utf-8")

    def disable_secret(self, secret_id: str, *, actor_id: str) -> SecretMetadata:
        row = self._secret_row(secret_id)
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                """
                UPDATE admin_secrets
                SET disabled = 1, updated_at = ?, updated_by = ?
                WHERE secret_id = ?
                """,
                (now.isoformat(), actor_id, row["secret_id"]),
            )
        return self.describe_secret(secret_id)

    def _secret_row(self, secret_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM admin_secrets WHERE secret_id = ?",
            (secret_id,),
        ).fetchone()
        if row is None:
            raise SecretNotFound(secret_id)
        return row

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_secrets (
                    secret_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    masked_value TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    algorithm TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    ciphertext TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL
                )
                """
            )


def _decode_master_key(master_key: str) -> bytes:
    if not master_key:
        raise SecretStoreUnavailable("ADMIN_SECRET_MASTER_KEY is not set")
    try:
        decoded = base64.urlsafe_b64decode(master_key.encode("ascii"))
    except Exception as error:
        raise SecretStoreUnavailable("ADMIN_SECRET_MASTER_KEY is invalid") from error
    if len(decoded) != 32:
        raise SecretStoreUnavailable("ADMIN_SECRET_MASTER_KEY must decode to 32 bytes")
    return decoded


def _metadata_from_row(row: sqlite3.Row) -> SecretMetadata:
    return SecretMetadata(
        secret_id=row["secret_id"],
        label=row["label"],
        kind=row["kind"],
        fingerprint=row["fingerprint"],
        masked_value=row["masked_value"],
        version=row["version"],
        disabled=bool(row["disabled"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _fingerprint(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:16]


def _mask_secret(plaintext: str) -> str:
    if len(plaintext) < 8:
        return "****"
    return f"{plaintext[:3]}****{plaintext[-4:]}"
