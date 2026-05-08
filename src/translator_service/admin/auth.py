from __future__ import annotations

import base64
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from translator_service.admin.rbac import AdminRole


class AdminAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdminSession:
    actor_id: str
    role: AdminRole
    expires_at: datetime
    csrf_token: str


class AdminSessionManager:
    def __init__(
        self,
        *,
        owner_password: str,
        session_secret: str,
        ttl_seconds: int = 8 * 60 * 60,
    ) -> None:
        self._owner_password = owner_password
        self._session_secret = session_secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds

    def login(self, password: str) -> str:
        if not self._owner_password or not self._session_secret:
            raise AdminAuthError("Admin authentication is not configured")
        if not hmac.compare_digest(password, self._owner_password):
            raise AdminAuthError("Invalid admin password")
        session = AdminSession(
            actor_id="bootstrap-owner",
            role=AdminRole.OWNER,
            expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl_seconds),
            csrf_token=secrets.token_urlsafe(32),
        )
        return self.dump(session)

    def dump(self, session: AdminSession) -> str:
        if not self._session_secret:
            raise AdminAuthError("Admin authentication is not configured")
        payload = {
            "actor_id": session.actor_id,
            "role": session.role.value,
            "expires_at": session.expires_at.isoformat(),
            "csrf_token": session.csrf_token,
        }
        encoded_payload = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        signature = hmac.new(
            self._session_secret,
            encoded_payload.encode("ascii"),
            sha256,
        ).hexdigest()
        return f"{encoded_payload}.{signature}"

    def load(self, cookie_value: str | None) -> AdminSession:
        if not cookie_value:
            raise AdminAuthError("Missing admin session")
        if not self._session_secret:
            raise AdminAuthError("Admin authentication is not configured")
        try:
            encoded_payload, signature = cookie_value.split(".", 1)
        except ValueError as error:
            raise AdminAuthError("Malformed admin session") from error
        expected_signature = hmac.new(
            self._session_secret,
            encoded_payload.encode("ascii"),
            sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise AdminAuthError("Invalid admin session signature")
        try:
            payload = json.loads(base64.urlsafe_b64decode(encoded_payload))
            session = AdminSession(
                actor_id=payload["actor_id"],
                role=AdminRole(payload["role"]),
                expires_at=datetime.fromisoformat(payload["expires_at"]),
                csrf_token=payload["csrf_token"],
            )
        except Exception as error:
            raise AdminAuthError("Invalid admin session payload") from error
        if session.expires_at <= datetime.now(UTC):
            raise AdminAuthError("Expired admin session")
        return session

    def verify_csrf(self, session: AdminSession, token: str | None) -> bool:
        return bool(token) and hmac.compare_digest(session.csrf_token, token)
