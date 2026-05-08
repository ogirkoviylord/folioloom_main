import unittest

from translator_service.admin.rbac import AdminPermission, AdminRole, has_permission


class AdminRbacTest(unittest.TestCase):
    def test_owner_has_all_mvp_permissions(self):
        for permission in AdminPermission:
            self.assertTrue(has_permission(AdminRole.OWNER, permission))

    def test_operator_can_view_and_operate_but_not_manage_secrets(self):
        self.assertTrue(
            has_permission(AdminRole.OPERATOR, AdminPermission.VIEW_OPERATIONS)
        )
        self.assertTrue(has_permission(AdminRole.OPERATOR, AdminPermission.RETRY_JOBS))
        self.assertTrue(has_permission(AdminRole.OPERATOR, AdminPermission.CANCEL_JOBS))
        self.assertFalse(
            has_permission(AdminRole.OPERATOR, AdminPermission.MANAGE_INTEGRATIONS)
        )
        self.assertFalse(
            has_permission(
                AdminRole.OPERATOR,
                AdminPermission.MANAGE_SERVICE_SETTINGS,
            )
        )

    def test_viewer_is_read_only(self):
        self.assertTrue(has_permission(AdminRole.VIEWER, AdminPermission.VIEW_OVERVIEW))
        self.assertTrue(
            has_permission(AdminRole.VIEWER, AdminPermission.VIEW_AUDIT_LOG)
        )
        self.assertFalse(has_permission(AdminRole.VIEWER, AdminPermission.RETRY_JOBS))
        self.assertFalse(has_permission(AdminRole.VIEWER, AdminPermission.CANCEL_JOBS))


if __name__ == "__main__":
    unittest.main()
