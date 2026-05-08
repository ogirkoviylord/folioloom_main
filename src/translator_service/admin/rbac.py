from enum import StrEnum


class AdminRole(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    VIEWER = "viewer"


class AdminPermission(StrEnum):
    VIEW_OVERVIEW = "view_overview"
    VIEW_INTEGRATIONS = "view_integrations"
    MANAGE_INTEGRATIONS = "manage_integrations"
    VIEW_SERVICE_SETTINGS = "view_service_settings"
    MANAGE_SERVICE_SETTINGS = "manage_service_settings"
    VIEW_OPERATIONS = "view_operations"
    RETRY_JOBS = "retry_jobs"
    CANCEL_JOBS = "cancel_jobs"
    VIEW_SECURITY_EVENTS = "view_security_events"
    VIEW_AUDIT_LOG = "view_audit_log"
    MANAGE_ADMINS = "manage_admins"


_OWNER_PERMISSIONS = frozenset(AdminPermission)
_OPERATOR_PERMISSIONS = frozenset(
    {
        AdminPermission.VIEW_OVERVIEW,
        AdminPermission.VIEW_INTEGRATIONS,
        AdminPermission.VIEW_SERVICE_SETTINGS,
        AdminPermission.VIEW_OPERATIONS,
        AdminPermission.RETRY_JOBS,
        AdminPermission.CANCEL_JOBS,
        AdminPermission.VIEW_SECURITY_EVENTS,
        AdminPermission.VIEW_AUDIT_LOG,
    }
)
_VIEWER_PERMISSIONS = frozenset(
    {
        AdminPermission.VIEW_OVERVIEW,
        AdminPermission.VIEW_INTEGRATIONS,
        AdminPermission.VIEW_SERVICE_SETTINGS,
        AdminPermission.VIEW_OPERATIONS,
        AdminPermission.VIEW_SECURITY_EVENTS,
        AdminPermission.VIEW_AUDIT_LOG,
    }
)

_ROLE_PERMISSIONS = {
    AdminRole.OWNER: _OWNER_PERMISSIONS,
    AdminRole.OPERATOR: _OPERATOR_PERMISSIONS,
    AdminRole.VIEWER: _VIEWER_PERMISSIONS,
}


def has_permission(role: AdminRole, permission: AdminPermission) -> bool:
    return permission in _ROLE_PERMISSIONS[role]
