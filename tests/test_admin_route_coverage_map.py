from __future__ import annotations

import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol, cast

from fastapi.routing import APIRoute, APIRouter

from translator_service.admin.routes import create_admin_router
from translator_service.config import Settings

"""
Admin route coverage map for GitHub #722.

Confirmed:
- Route inventory is checked against create_admin_router() in this file.
- Current admin sessions are owner-only because AdminSessionManager.login()
  creates actor_id="bootstrap-owner" and role=AdminRole.OWNER.
- Route-level RBAC enforcement is currently absent: routes.py does not import or
  call AdminPermission / has_permission.
- Current session, CSRF, and audit guard coverage below is source-inspected
  metadata for the current owner-only implementation.

Assumptions:
- This map describes the local source tree only; it does not verify deployed
  bind address, SSH tunnel, or public exposure state.

TBD:
- Future named-admin / role-based permission policy is not approved here.
  Ambiguous future permissions are intentionally marked TBD instead of encoded
  as enforcement expectations.

Unknown:
- Runtime deployment topology and external admin exposure state are not tested
  by this metadata-only route map.
"""

ROUTE_LEVEL_RBAC_ABSENT = (
    "absent: routes.py does not use AdminPermission/has_permission"
)
READ_ONLY_AUDIT_NOT_APPLICABLE = "not_applicable_read_only"

ROUTE_COVERAGE_MAP = (
    {
        "method": "GET",
        "path": "/admin/",
        "handler": "root",
        "sensitivity": "public_redirect",
        "mutating": False,
        "destructive": False,
        "session_guard": "none: redirects to /admin/overview",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OVERVIEW",
    },
    {
        "method": "GET",
        "path": "/admin/login",
        "handler": "login_form",
        "sensitivity": "public_auth",
        "mutating": False,
        "destructive": False,
        "session_guard": "none: public login form",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_AUTH_SESSION",
    },
    {
        "method": "POST",
        "path": "/admin/login",
        "handler": "login",
        "sensitivity": "public_auth_session_issuance",
        "mutating": True,
        "destructive": False,
        "session_guard": (
            "none: validates owner password and issues signed owner cookie"
        ),
        "csrf_guard": "none_current_login_behavior",
        "audit_coverage": "none_current_behavior",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_AUTH_SESSION",
    },
    {
        "method": "POST",
        "path": "/admin/logout",
        "handler": "logout",
        "sensitivity": "owner_session_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "none_current_behavior",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_AUTH_SESSION",
    },
    {
        "method": "GET",
        "path": "/admin/integrations",
        "handler": "integrations",
        "sensitivity": "integration_config_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_INTEGRATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/overview",
        "handler": "overview",
        "sensitivity": "owner_overview_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OVERVIEW",
    },
    {
        "method": "GET",
        "path": "/admin/documents",
        "handler": "documents",
        "sensitivity": "owner_document_catalog_metadata_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _owner_session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_DOCUMENT_INTAKE",
    },
    {
        "method": "POST",
        "path": "/admin/documents/upload",
        "handler": "documents_upload",
        "sensitivity": "owner_document_original_storage_and_registry_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _owner_session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "none_current_behavior",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "MANAGE_DOCUMENT_INTAKE",
    },
    {
        "method": "POST",
        "path": "/admin/documents/select",
        "handler": "documents_select",
        "sensitivity": "owner_document_workbench_selection_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _owner_session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "none_current_behavior",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "MANAGE_DOCUMENT_INTAKE",
    },
    {
        "method": "GET",
        "path": "/admin/ai-providers",
        "handler": "ai_providers",
        "sensitivity": "provider_config_and_capacity_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_INTEGRATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/ai-providers/deepseek/keys",
        "handler": "deepseek_keys",
        "sensitivity": "provider_key_metadata_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_INTEGRATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/billing",
        "handler": "billing",
        "sensitivity": "billing_shell_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_BILLING_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/costs",
        "handler": "costs",
        "sensitivity": "cost_and_usage_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/quality",
        "handler": "quality",
        "sensitivity": "quality_summary_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/internal-reader",
        "handler": "internal_reader",
        "sensitivity": "reader_fixture_and_run_metadata_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_READER_EXPLORER_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/internal-reader/preview",
        "handler": "internal_reader_preview",
        "sensitivity": "raw_fixture_or_mapping_preview_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none before report generation",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_READER_EXPLORER_VIEW",
    },
    {
        "method": "POST",
        "path": "/admin/quality/run",
        "handler": "run_quality",
        "sensitivity": "quality_run_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: quality.run success/failure",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_QUALITY_RUN_MUTATION",
    },
    {
        "method": "GET",
        "path": "/admin/settings",
        "handler": "settings_page",
        "sensitivity": "service_settings_and_secret_safety_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_SERVICE_SETTINGS",
    },
    {
        "method": "GET",
        "path": "/admin/beta-controls",
        "handler": "beta_controls",
        "sensitivity": "beta_control_settings_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_SERVICE_SETTINGS",
    },
    {
        "method": "POST",
        "path": "/admin/settings/beta-allowlist/toggle",
        "handler": "toggle_beta_allowlist",
        "sensitivity": "beta_allowlist_settings_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: settings.beta_allowlist.enabled_changed",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "MANAGE_SERVICE_SETTINGS",
    },
    {
        "method": "POST",
        "path": "/admin/settings/beta-allowlist/add",
        "handler": "add_beta_allowlist_id",
        "sensitivity": "beta_allowlist_settings_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": (
            "helper: _save_beta_allowlist_ids settings.beta_allowlist.added"
        ),
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "MANAGE_SERVICE_SETTINGS",
    },
    {
        "method": "POST",
        "path": "/admin/settings/beta-allowlist/remove",
        "handler": "remove_beta_allowlist_id",
        "sensitivity": "beta_allowlist_settings_mutation",
        "mutating": True,
        "destructive": True,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": (
            "helper: _save_beta_allowlist_ids settings.beta_allowlist.removed"
        ),
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "MANAGE_SERVICE_SETTINGS",
    },
    {
        "method": "POST",
        "path": "/admin/settings/beta-allowlist",
        "handler": "save_beta_allowlist",
        "sensitivity": "beta_allowlist_settings_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": (
            "helper: _save_beta_allowlist_ids settings.beta_allowlist.updated"
        ),
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "MANAGE_SERVICE_SETTINGS",
    },
    {
        "method": "POST",
        "path": "/admin/settings/beta-safety",
        "handler": "save_beta_safety_settings",
        "sensitivity": "beta_safety_settings_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: settings.beta_safety.updated",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "MANAGE_SERVICE_SETTINGS",
    },
    {
        "method": "GET",
        "path": "/admin/live",
        "handler": "live",
        "sensitivity": "live_runtime_state_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/logs",
        "handler": "logs",
        "sensitivity": "translation_run_metadata_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/translations",
        "handler": "translations",
        "sensitivity": "translation_operations_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/logs/{run_id}",
        "handler": "log_detail",
        "sensitivity": "translation_run_details_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none before detail lookup",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/logs/{run_id}/text-diagnostics",
        "handler": "log_text_diagnostics",
        "sensitivity": "raw_text_diagnostics_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none before diagnostics lookup",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_RAW_DIAGNOSTICS_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/logs/{run_id}/reader",
        "handler": "log_reader",
        "sensitivity": "raw_translation_reader_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none before reader lookup",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_RAW_DIAGNOSTICS_VIEW",
    },
    {
        "method": "POST",
        "path": "/admin/logs/{run_id}/reader/review-mark",
        "handler": "save_log_reader_review_mark",
        "sensitivity": "reader_review_mark_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "none_current_behavior",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_RAW_DIAGNOSTICS_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/translations/{run_id}/trace",
        "handler": "translation_trace",
        "sensitivity": "translation_trace_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none before trace lookup",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/logs/{run_id}/download",
        "handler": "download_log",
        "sensitivity": "raw_diagnostics_archive_download",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none before archive build",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_RAW_DIAGNOSTICS_DOWNLOAD",
    },
    {
        "method": "GET",
        "path": "/admin/activity",
        "handler": "activity",
        "sensitivity": "user_activity_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_USER_ACTIVITY_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/users",
        "handler": "users",
        "sensitivity": "user_profile_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_USER_ACTIVITY_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/users/{user_id}",
        "handler": "user_detail",
        "sensitivity": "user_profile_detail_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_USER_ACTIVITY_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/security/events",
        "handler": "security_events",
        "sensitivity": "security_event_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_SECURITY_EVENTS",
    },
    {
        "method": "GET",
        "path": "/admin/upload-safety",
        "handler": "upload_safety",
        "sensitivity": "upload_safety_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_SECURITY_EVENTS",
    },
    {
        "method": "GET",
        "path": "/admin/upload-safety/{upload_id}",
        "handler": "upload_safety_detail",
        "sensitivity": "upload_safety_detail_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_SECURITY_EVENTS",
    },
    {
        "method": "GET",
        "path": "/admin/operations/jobs",
        "handler": "operations",
        "sensitivity": "job_queue_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "POST",
        "path": "/admin/operations/jobs/{job_id}/{action}",
        "handler": "operate_job",
        "sensitivity": "job_state_mutation",
        "mutating": True,
        "destructive": True,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "helper: _apply_admin_job_action",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "CANCEL_JOBS/TBD_PAUSE_DELETE_JOB",
    },
    {
        "method": "GET",
        "path": "/admin/api/integrations",
        "handler": "integrations_api",
        "sensitivity": "integration_config_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_INTEGRATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/api/ai-providers",
        "handler": "ai_providers_api",
        "sensitivity": "provider_config_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_INTEGRATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/api/ai-providers/runtime",
        "handler": "ai_provider_runtime_api",
        "sensitivity": "provider_runtime_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_INTEGRATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/api/ai-providers/deepseek/balance",
        "handler": "deepseek_balance_api",
        "sensitivity": "provider_balance_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_INTEGRATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/api/costs",
        "handler": "costs_api",
        "sensitivity": "cost_and_usage_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/api/quality",
        "handler": "quality_api",
        "sensitivity": "quality_summary_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/api/logs",
        "handler": "logs_api",
        "sensitivity": "translation_run_metadata_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/api/logs/{run_id}",
        "handler": "log_detail_api",
        "sensitivity": "translation_run_details_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/api/activity",
        "handler": "activity_api",
        "sensitivity": "user_activity_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_USER_ACTIVITY_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/api/users",
        "handler": "users_api",
        "sensitivity": "user_profile_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_USER_ACTIVITY_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/api/live",
        "handler": "live_api",
        "sensitivity": "live_runtime_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "POST",
        "path": "/admin/api/integrations/{integration_id}/secrets/{secret_id}",
        "handler": "save_integration_secret",
        "sensitivity": "secret_write",
        "mutating": True,
        "destructive": False,
        "session_guard": "helper: _save_registry_secret -> _session_or_none",
        "csrf_guard": "helper: _save_registry_secret -> session_manager.verify_csrf",
        "audit_coverage": "helper: _save_registry_secret integration.secret.replaced",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "MANAGE_INTEGRATIONS",
    },
    {
        "method": "POST",
        "path": "/admin/api/ai-providers/{provider_id}/secrets/{secret_id}",
        "handler": "save_ai_provider_secret",
        "sensitivity": "provider_secret_write",
        "mutating": True,
        "destructive": False,
        "session_guard": "helper: _save_registry_secret -> _session_or_none",
        "csrf_guard": "helper: _save_registry_secret -> session_manager.verify_csrf",
        "audit_coverage": "helper: _save_registry_secret ai_provider.secret.replaced",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_SECRET_MANAGE",
    },
    {
        "method": "POST",
        "path": "/admin/integrations/{integration_id}/connections",
        "handler": "add_integration_connection",
        "sensitivity": "integration_connection_secret_write",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: integration.connection.added",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "MANAGE_INTEGRATIONS",
    },
    {
        "method": "POST",
        "path": "/admin/integrations/{integration_id}/connections/remove",
        "handler": "remove_integration_connection",
        "sensitivity": "integration_connection_delete",
        "mutating": True,
        "destructive": True,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: integration.connection.removed",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "MANAGE_INTEGRATIONS",
    },
    {
        "method": "POST",
        "path": "/admin/ai-providers/{provider_id}/keys",
        "handler": "add_ai_provider_key",
        "sensitivity": "provider_key_secret_write",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: ai_provider.key.added",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_KEY_MANAGE",
    },
    {
        "method": "POST",
        "path": "/admin/ai-providers/deepseek/balance/refresh",
        "handler": "refresh_deepseek_balance_route",
        "sensitivity": "provider_external_balance_probe",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: ai_provider.balance.refreshed",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_PROBE",
    },
    {
        "method": "POST",
        "path": "/admin/ai-providers/{provider_id}/keys/remove",
        "handler": "remove_ai_provider_key",
        "sensitivity": "provider_key_delete",
        "mutating": True,
        "destructive": True,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: ai_provider.key.removed",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_KEY_MANAGE",
    },
    {
        "method": "POST",
        "path": "/admin/ai-providers/{provider_id}/keys/update",
        "handler": "update_ai_provider_key",
        "sensitivity": "provider_key_metadata_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: ai_provider.key.updated",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_KEY_MANAGE",
    },
    {
        "method": "POST",
        "path": "/admin/ai-providers/{provider_id}/keys/rotate",
        "handler": "rotate_ai_provider_key",
        "sensitivity": "provider_key_secret_rotation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: ai_provider.key.rotated",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_KEY_MANAGE",
    },
    {
        "method": "POST",
        "path": "/admin/ai-providers/{provider_id}/keys/disable",
        "handler": "disable_ai_provider_key",
        "sensitivity": "provider_key_runtime_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "helper: _set_ai_provider_key_enabled -> _session_or_none",
        "csrf_guard": (
            "helper: _set_ai_provider_key_enabled -> session_manager.verify_csrf"
        ),
        "audit_coverage": (
            "helper: _set_ai_provider_key_enabled ai_provider.key.disabled"
        ),
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_KEY_MANAGE",
    },
    {
        "method": "POST",
        "path": "/admin/ai-providers/{provider_id}/keys/enable",
        "handler": "enable_ai_provider_key",
        "sensitivity": "provider_key_runtime_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "helper: _set_ai_provider_key_enabled -> _session_or_none",
        "csrf_guard": (
            "helper: _set_ai_provider_key_enabled -> session_manager.verify_csrf"
        ),
        "audit_coverage": (
            "helper: _set_ai_provider_key_enabled ai_provider.key.enabled"
        ),
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_KEY_MANAGE",
    },
    {
        "method": "POST",
        "path": "/admin/ai-providers/{provider_id}/keys/test",
        "handler": "test_ai_provider_key",
        "sensitivity": "provider_external_key_probe",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: ai_provider.key.tested when key is found",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_PROBE",
    },
    {
        "method": "POST",
        "path": "/admin/ai-providers/{provider_id}/keys/test-all",
        "handler": "test_all_ai_provider_keys",
        "sensitivity": "provider_external_key_pool_probe",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: ai_provider.keys.tested",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_PROBE",
    },
    {
        "method": "POST",
        "path": "/admin/ai-providers/{provider_id}/runtime/reload",
        "handler": "request_ai_provider_runtime_reload",
        "sensitivity": "provider_runtime_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "direct: ai_provider.runtime.reload_requested",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_PROVIDER_RUNTIME_MANAGE",
    },
    {
        "method": "GET",
        "path": "/admin/api/operations/overview",
        "handler": "operations_api",
        "sensitivity": "job_queue_api_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_OPERATIONS",
    },
    {
        "method": "GET",
        "path": "/admin/audit",
        "handler": "handler",
        "sensitivity": "audit_placeholder_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "helper: page -> _protected_page",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "VIEW_AUDIT_LOG",
    },
    {
        "method": "GET",
        "path": "/admin/workbench-entry",
        "handler": "workbench_entry",
        "sensitivity": "owner_only_redirect",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_ENTRY",
    },
    {
        "method": "GET",
        "path": "/admin/workbench/",
        "handler": "workbench_root",
        "sensitivity": "workbench_shell_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/workbench/select",
        "handler": "workbench_select",
        "sensitivity": "workbench_shell_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/workbench/recovery",
        "handler": "workbench_recovery",
        "sensitivity": "workbench_shell_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/workbench/glossary",
        "handler": "workbench_glossary",
        "sensitivity": "workbench_glossary_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_VIEW",
    },
    {
        "method": "GET",
        "path": "/admin/workbench/future",
        "handler": "workbench_future",
        "sensitivity": "workbench_placeholder_read",
        "mutating": False,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "not_applicable_read_only",
        "audit_coverage": READ_ONLY_AUDIT_NOT_APPLICABLE,
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_VIEW",
    },
    {
        "method": "POST",
        "path": "/admin/workbench/glossary/terms/add",
        "handler": "workbench_term_add",
        "sensitivity": "workbench_glossary_local_ephemeral_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "local_only_ephemeral",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_MUTATE",
    },
    {
        "method": "POST",
        "path": "/admin/workbench/glossary/terms/{term_id}/edit",
        "handler": "workbench_term_edit",
        "sensitivity": "workbench_glossary_local_ephemeral_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "local_only_ephemeral",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_MUTATE",
    },
    {
        "method": "POST",
        "path": "/admin/workbench/glossary/terms/{term_id}/accept",
        "handler": "workbench_term_accept",
        "sensitivity": "workbench_glossary_mutation_not_wired",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "local_only_not_wired",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_MUTATE",
    },
    {
        "method": "POST",
        "path": "/admin/workbench/glossary/terms/{term_id}/delete",
        "handler": "workbench_term_delete",
        "sensitivity": "workbench_glossary_local_ephemeral_mutation",
        "mutating": True,
        "destructive": True,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "local_only_ephemeral",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_MUTATE",
    },
    {
        "method": "POST",
        "path": "/admin/workbench/glossary/terms/{term_id}/reject",
        "handler": "workbench_term_reject",
        "sensitivity": "workbench_glossary_mutation_not_wired",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "local_only_not_wired",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_MUTATE",
    },
    {
        "method": "POST",
        "path": "/admin/workbench/glossary/terms/{term_id}/lock",
        "handler": "workbench_term_lock",
        "sensitivity": "workbench_glossary_local_ephemeral_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "local_only_ephemeral",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_MUTATE",
    },
    {
        "method": "POST",
        "path": "/admin/workbench/glossary/terms/{term_id}/unlock",
        "handler": "workbench_term_unlock",
        "sensitivity": "workbench_glossary_mutation_not_wired",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "local_only_not_wired",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_MUTATE",
    },
    {
        "method": "POST",
        "path": "/admin/workbench/glossary/terms/lock-all-approved",
        "handler": "workbench_lock_all_approved",
        "sensitivity": "workbench_glossary_local_ephemeral_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "local_only_ephemeral",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_MUTATE",
    },
    {
        "method": "POST",
        "path": "/admin/workbench/glossary/approve",
        "handler": "workbench_approve_glossary",
        "sensitivity": "workbench_glossary_local_ephemeral_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "local_only_ephemeral",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_MUTATE",
    },
    {
        "method": "POST",
        "path": "/admin/workbench/glossary/check",
        "handler": "workbench_check_selected",
        "sensitivity": "workbench_glossary_local_ephemeral_mutation",
        "mutating": True,
        "destructive": False,
        "session_guard": "direct: _session_or_none",
        "csrf_guard": "direct: session_manager.verify_csrf",
        "audit_coverage": "local_only_ephemeral",
        "route_level_rbac": ROUTE_LEVEL_RBAC_ABSENT,
        "future_permission": "TBD_WORKBENCH_MUTATE",
    },
)


class _RouteInventoryEntry(Protocol):
    methods: set[str]
    name: str
    path: str


class _EffectiveRouteContext(Protocol):
    original_route: object


def _router_api_routes(router: APIRouter) -> Iterator[_RouteInventoryEntry]:
    """Yield effective API routes across FastAPI router storage layouts."""
    for route in router.routes:
        if isinstance(route, APIRoute):
            yield route
            continue

        effective_route_contexts = getattr(route, "effective_route_contexts", None)
        if not callable(effective_route_contexts):
            continue
        iter_contexts = cast(Callable[[], Iterator[object]], effective_route_contexts)
        for raw_context in iter_contexts():
            context = cast(_EffectiveRouteContext, raw_context)
            if isinstance(context.original_route, APIRoute):
                yield cast(_RouteInventoryEntry, raw_context)


class AdminRouteCoverageMapTest(unittest.TestCase):
    def test_route_coverage_map_matches_current_router_inventory(self) -> None:
        router = create_admin_router(
            Settings(
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
            )
        )
        actual = {
            (method, route.path): route.name
            for route in _router_api_routes(router)
            for method in route.methods
            if method not in {"HEAD", "OPTIONS"}
        }
        mapped = {
            (entry["method"], entry["path"]): entry["handler"]
            for entry in ROUTE_COVERAGE_MAP
        }

        self.assertEqual(len(actual), 84)
        self.assertEqual(sum(1 for method, _path in actual if method == "POST"), 36)
        self.assertEqual(actual, mapped)

    def test_mutating_destructive_and_sensitive_routes_are_classified(self) -> None:
        mutating = [entry for entry in ROUTE_COVERAGE_MAP if entry["mutating"]]
        destructive = [entry for entry in ROUTE_COVERAGE_MAP if entry["destructive"]]
        tbd_permissions = {
            entry["future_permission"]
            for entry in ROUTE_COVERAGE_MAP
            if str(entry["future_permission"]).startswith("TBD")
        }

        quality_run_entry = next(
            entry
            for entry in ROUTE_COVERAGE_MAP
            if (entry["method"], entry["path"]) == ("POST", "/admin/quality/run")
        )

        self.assertEqual(len(mutating), 36)
        self.assertEqual(len(destructive), 5)
        self.assertIn("TBD_RAW_DIAGNOSTICS_VIEW", tbd_permissions)
        self.assertIn("TBD_PROVIDER_KEY_MANAGE", tbd_permissions)
        self.assertIn("TBD_USER_ACTIVITY_VIEW", tbd_permissions)
        self.assertIn("TBD_QUALITY_RUN_MUTATION", tbd_permissions)
        self.assertTrue(quality_run_entry["mutating"])
        self.assertEqual(quality_run_entry["sensitivity"], "quality_run_mutation")
        self.assertEqual(
            quality_run_entry["future_permission"],
            "TBD_QUALITY_RUN_MUTATION",
        )
        self.assertNotEqual(quality_run_entry["future_permission"], "VIEW_OPERATIONS")

        glossary_entries = {
            entry["path"]: entry
            for entry in ROUTE_COVERAGE_MAP
            if entry["method"] == "POST"
            and entry["path"]
            in {
                "/admin/workbench/glossary/terms/add",
                "/admin/workbench/glossary/terms/{term_id}/edit",
                "/admin/workbench/glossary/approve",
                "/admin/workbench/glossary/check",
                "/admin/workbench/glossary/terms/{term_id}/delete",
            }
        }
        self.assertEqual(len(glossary_entries), 5)
        for path, entry in glossary_entries.items():
            with self.subTest(glossary_route=path):
                self.assertEqual(
                    entry["sensitivity"],
                    "workbench_glossary_local_ephemeral_mutation",
                )
                self.assertEqual(entry["audit_coverage"], "local_only_ephemeral")
                self.assertTrue(entry["mutating"])
                self.assertEqual(entry["future_permission"], "TBD_WORKBENCH_MUTATE")
        self.assertTrue(
            glossary_entries["/admin/workbench/glossary/terms/{term_id}/delete"][
                "destructive"
            ]
        )

        for entry in ROUTE_COVERAGE_MAP:
            with self.subTest(route=(entry["method"], entry["path"])):
                self.assertTrue(entry["sensitivity"])
                self.assertTrue(entry["future_permission"])
                self.assertEqual(entry["mutating"], entry["method"] == "POST")
                if entry["destructive"]:
                    self.assertTrue(entry["mutating"])

    def test_current_owner_only_guards_and_absent_route_level_rbac_are_mapped(
        self,
    ) -> None:
        routes_source = Path("src/translator_service/admin/routes.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("AdminPermission", routes_source)
        self.assertNotIn("has_permission", routes_source)

        public_or_login_paths = {
            ("GET", "/admin/"),
            ("GET", "/admin/login"),
            ("POST", "/admin/login"),
        }
        current_no_audit_mutations = {
            ("POST", "/admin/login"),
            ("POST", "/admin/logout"),
            ("POST", "/admin/logs/{run_id}/reader/review-mark"),
            ("POST", "/admin/documents/upload"),
            ("POST", "/admin/documents/select"),
        }

        for entry in ROUTE_COVERAGE_MAP:
            route_key = (entry["method"], entry["path"])
            with self.subTest(route=route_key):
                self.assertEqual(entry["route_level_rbac"], ROUTE_LEVEL_RBAC_ABSENT)
                if route_key not in public_or_login_paths:
                    self.assertNotIn(
                        "none", str(entry["session_guard"]).split(":", 1)[0]
                    )
                if entry["method"] == "POST" and route_key != ("POST", "/admin/login"):
                    self.assertIn("csrf", str(entry["csrf_guard"]).lower())
                if entry["mutating"] and route_key not in current_no_audit_mutations:
                    self.assertNotIn("none", str(entry["audit_coverage"]).lower())


if __name__ == "__main__":
    unittest.main()
