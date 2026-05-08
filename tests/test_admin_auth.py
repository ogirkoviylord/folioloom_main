import unittest
from datetime import UTC, datetime, timedelta

from translator_service.admin.auth import (
    AdminAuthError,
    AdminSession,
    AdminSessionManager,
)
from translator_service.admin.rbac import AdminRole


class AdminSessionManagerTest(unittest.TestCase):
    def test_owner_password_creates_signed_owner_session(self):
        manager = AdminSessionManager(
            owner_password="owner-pass",
            session_secret="session-secret",
        )

        cookie = manager.login("owner-pass")
        session = manager.load(cookie)

        self.assertEqual(session.actor_id, "bootstrap-owner")
        self.assertEqual(session.role, AdminRole.OWNER)
        self.assertTrue(manager.verify_csrf(session, session.csrf_token))

    def test_wrong_owner_password_is_rejected(self):
        manager = AdminSessionManager(
            owner_password="owner-pass",
            session_secret="session-secret",
        )

        with self.assertRaises(AdminAuthError):
            manager.login("wrong-pass")

    def test_tampered_cookie_is_rejected(self):
        manager = AdminSessionManager(
            owner_password="owner-pass",
            session_secret="session-secret",
        )

        cookie = manager.login("owner-pass")

        with self.assertRaises(AdminAuthError):
            manager.load(cookie + "x")

    def test_expired_session_is_rejected(self):
        manager = AdminSessionManager(
            owner_password="owner-pass",
            session_secret="session-secret",
        )
        expired = AdminSession(
            actor_id="bootstrap-owner",
            role=AdminRole.OWNER,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            csrf_token="csrf-token",
        )

        with self.assertRaises(AdminAuthError):
            manager.load(manager.dump(expired))

    def test_missing_auth_configuration_fails_closed(self):
        manager = AdminSessionManager(owner_password="", session_secret="")

        with self.assertRaises(AdminAuthError):
            manager.login("owner-pass")


if __name__ == "__main__":
    unittest.main()
