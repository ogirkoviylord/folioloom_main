from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from translator_service.admin.action_center import build_action_center
from translator_service.admin.ai_provider_keys import (
    AIProviderKeySummary,
    SQLiteAIProviderKeyStore,
)
from translator_service.admin.audit import AuditOutcome, SQLiteAdminAuditLog
from translator_service.admin.auth import (
    AdminAuthError,
    AdminSession,
    AdminSessionManager,
)
from translator_service.admin.beta_safety_settings import (
    beta_safety_setting_definitions_from_settings,
    load_beta_safety_limits,
)
from translator_service.admin.bootstrap_config import (
    apply_ai_provider_key_bootstrap,
    apply_integration_bootstrap,
    apply_integration_connection_bootstrap,
    env_bootstrap_config,
)
from translator_service.admin.costs import (
    build_beta_safety_cost_summary,
    build_cost_analytics,
)
from translator_service.admin.integration_connections import (
    SQLiteIntegrationConnectionStore,
)
from translator_service.admin.integrations import (
    DEFAULT_AI_PROVIDER_REGISTRY,
    DEFAULT_INTEGRATION_REGISTRY,
    IntegrationRegistry,
)
from translator_service.admin.live import (
    ServerHealthSnapshot,
    build_live_monitor_snapshot,
)
from translator_service.admin.operations import (
    build_persistent_operations_overview,
)
from translator_service.admin.provider_balance import (
    ProviderBalanceSnapshot,
    get_cached_deepseek_balance,
    refresh_deepseek_balance,
)
from translator_service.admin.provider_health import (
    _redact_sensitive_text,
    build_provider_health,
)
from translator_service.admin.provider_probe import validate_ai_provider_key
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeProviderState,
    SQLiteAIProviderRuntimeStore,
)
from translator_service.admin.provider_validation import SQLiteAIProviderValidationStore
from translator_service.admin.quality import build_quality_run_summary
from translator_service.admin.quality_runner import QualityRunResult, write_quality_run
from translator_service.admin.secret_safety import build_secret_safety_report
from translator_service.admin.secrets import (
    SecretNotFound,
    SecretStoreUnavailable,
    SQLiteEncryptedSecretStore,
)
from translator_service.admin.settings import SettingValueType, SQLiteAdminSettingsStore
from translator_service.admin.translation_logs import (
    TranslationRunDetails,
    TranslationRunFragmentDetail,
    TranslationRunSummary,
    TranslationWorkUnitDiagnostic,
    build_translation_run_archive,
    get_translation_run_details,
    list_translation_run_summaries,
)
from translator_service.admin.translation_progress import (
    overlay_translation_run_details,
    overlay_translation_run_summaries,
)
from translator_service.admin.translation_trace import build_translation_trace
from translator_service.admin.upload_safety import (
    UPLOAD_SAFETY_ACTIVITY_EVENT_TYPE,
    UploadSafetyFilters,
    upload_safety_read_model_from_activity_events,
)
from translator_service.admin.views import (
    activity_body,
    admin_page,
    ai_providers_body,
    billing_body,
    costs_body,
    deepseek_keys_body,
    integrations_body,
    internal_reader_body,
    live_body,
    log_detail_body,
    login_page,
    logs_body,
    operations_body,
    overview_body,
    quality_body,
    section_body,
    security_events_body,
    settings_body,
    translation_reader_body,
    translation_text_diagnostics_body,
    translation_trace_body,
    upload_safety_body,
    upload_safety_detail_body,
    user_detail_body,
    users_body,
)
from translator_service.beta_access import (
    BETA_ALLOWLIST_ENABLED_SETTING,
    BETA_ALLOWLIST_SETTING,
    format_telegram_id_list,
    load_beta_access_policy,
    parse_telegram_id_list,
)
from translator_service.beta_safety_store import SQLiteBetaSafetyStore
from translator_service.config import Settings
from translator_service.file_storage import LocalObjectStorage
from translator_service.internal_reader import (
    generate_docx_reader_html_from_path,
    generate_epub_reader_html_from_path,
    generate_txt_reader_html_from_path,
    load_translation_mapping,
    reject_runtime_var_path,
)
from translator_service.persistent_job_store import (
    open_persistent_job_store,
    sqlite_store_exists,
)
from translator_service.translation_run_logs import (
    finish_running_translation_runs_for_job,
)
from translator_service.user_activity import (
    ActivityActorType,
    ActivityOutcome,
    ActivitySurface,
    SQLiteUserActivityStore,
    UserActivityEvent,
    UserActivityEventInput,
)

SESSION_COOKIE = "folioloom_admin_session"
_UPLOAD_SAFETY_EVENT_PAGE_SIZE = 500
_FAILED_TRANSLATION_STATUSES = frozenset({"failed", "interrupted", "error"})
_REPO_ROOT = Path(__file__).resolve().parents[3]
_INTERNAL_READER_FORMAT_AUTO = "auto"
_INTERNAL_READER_SUPPORTED_FORMATS = ("txt", "docx", "epub")
_INTERNAL_READER_FORMAT_BY_SUFFIX = {
    ".txt": "txt",
    ".docx": "docx",
    ".epub": "epub",
}


def create_admin_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/admin", include_in_schema=False)
    session_manager = AdminSessionManager(
        owner_password=settings.admin_owner_password,
        session_secret=settings.admin_session_secret,
    )

    @router.get("/", response_class=HTMLResponse)
    async def root() -> Response:
        return RedirectResponse("/admin/overview", status_code=HTTPStatus.SEE_OTHER)

    @router.get("/login", response_class=HTMLResponse)
    async def login_form() -> HTMLResponse:
        return _html(login_page())

    @router.post("/login", response_class=HTMLResponse)
    async def login(request: Request) -> Response:
        form = await _urlencoded_form(request)
        try:
            cookie_value = session_manager.login(form.get("password", ""))
        except AdminAuthError:
            return _html(
                login_page(error="Invalid admin credentials."),
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        response = RedirectResponse(
            "/admin/overview",
            status_code=HTTPStatus.SEE_OTHER,
        )
        response.set_cookie(
            SESSION_COOKIE,
            cookie_value,
            httponly=True,
            secure=settings.admin_cookie_secure,
            samesite="lax",
            path="/admin",
        )
        return response

    @router.post("/logout")
    async def logout(request: Request) -> Response:
        session = _session_or_none(request, session_manager)
        form = await _urlencoded_form(request)
        if session is None or not session_manager.verify_csrf(
            session,
            form.get("csrf_token"),
        ):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        response = RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        response.delete_cookie(SESSION_COOKIE, path="/admin")
        return response

    @router.get("/integrations", response_class=HTMLResponse)
    async def integrations(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Integrations",
            active="integrations",
            body=lambda session: integrations_body(
                _integration_summaries(settings),
                csrf_token=session.csrf_token,
                connections=_integration_connection_groups(settings),
            ),
        )

    @router.get("/overview", response_class=HTMLResponse)
    async def overview(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Overview",
            active="overview",
            body=lambda session: overview_body(_overview_action_center(settings)),
        )

    @router.get("/ai-providers", response_class=HTMLResponse)
    async def ai_providers(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="AI Providers",
            active="ai_providers",
            body=lambda session: ai_providers_body(
                _ai_provider_summaries(settings),
                csrf_token=session.csrf_token,
                key_pools=_ai_provider_key_pools(settings),
                health_summaries=_ai_provider_health(settings),
                runtime_statuses=_ai_provider_runtime_statuses(settings),
                runtime_reload_states=_ai_provider_runtime_reload_states(settings),
                balance_snapshot=_deepseek_balance_snapshot(settings),
                balance_stale_seconds=settings.admin_deepseek_balance_stale_seconds,
                top_up_url=settings.admin_deepseek_top_up_url,
            ),
        )

    @router.get("/ai-providers/deepseek/keys", response_class=HTMLResponse)
    async def deepseek_keys(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="DeepSeek Keys",
            active="ai_providers",
            body=lambda session: deepseek_keys_body(
                csrf_token=session.csrf_token,
                key_pools=(
                    key_pools := _ai_provider_key_pools(settings)
                ),
                runtime_reload_states=_ai_provider_runtime_reload_states(settings),
                key_validations=dict(
                    _ai_provider_key_validation_views(
                        settings,
                        "deepseek",
                        keys=key_pools.get("deepseek", ()),
                    )
                ),
            ),
        )

    @router.get("/billing", response_class=HTMLResponse)
    async def billing(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Billing",
            active="billing",
            body=billing_body(),
        )

    @router.get("/costs", response_class=HTMLResponse)
    async def costs(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Costs",
            active="costs",
            body=lambda session: costs_body(_cost_analytics(settings)),
        )

    @router.get("/quality", response_class=HTMLResponse)
    async def quality(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Quality",
            active="quality",
            body=lambda session: quality_body(
                _quality_run_summary(),
                csrf_token=session.csrf_token,
            ),
        )

    @router.get("/internal-reader", response_class=HTMLResponse)
    async def internal_reader(request: Request) -> Response:
        source_value = _internal_reader_requested_source(request)
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Internal Reader",
            active="reader",
            body=lambda session: internal_reader_body(
                source_options=_internal_reader_source_options(),
                selected_source=source_value,
                mapping_path=request.query_params.get("mapping", ""),
                source_format=request.query_params.get(
                    "format",
                    _INTERNAL_READER_FORMAT_AUTO,
                ),
                max_fragment_chars=_bounded_int(
                    request.query_params.get("max_fragment_chars"),
                    default=5000,
                    maximum=100000,
                ),
            ),
        )

    @router.get("/internal-reader/preview", response_class=HTMLResponse)
    async def internal_reader_preview(request: Request) -> Response:
        if _session_or_none(request, session_manager) is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        source_value = _internal_reader_requested_source(request)
        mapping_value = request.query_params.get("mapping", "")
        requested_format = request.query_params.get(
            "format",
            _INTERNAL_READER_FORMAT_AUTO,
        )
        max_fragment_chars = _bounded_int(
            request.query_params.get("max_fragment_chars"),
            default=5000,
            maximum=100000,
        )
        try:
            html = _internal_reader_report_html(
                source_value=source_value,
                mapping_value=mapping_value,
                requested_format=requested_format,
                max_fragment_chars=max_fragment_chars,
            )
        except ValueError as exc:
            session = _session_or_none(request, session_manager)
            if session is None:
                return RedirectResponse(
                    "/admin/login",
                    status_code=HTTPStatus.SEE_OTHER,
                )
            return _html(
                admin_page(
                    title="Internal Reader",
                    active="reader",
                    session=session,
                    environment=settings.environment,
                    body=internal_reader_body(
                        source_options=_internal_reader_source_options(),
                        selected_source=source_value,
                        mapping_path=mapping_value,
                        source_format=requested_format,
                        max_fragment_chars=max_fragment_chars,
                        error=str(exc),
                    ),
                ),
                status_code=HTTPStatus.BAD_REQUEST,
                headers={"Cache-Control": "no-store"},
            )
        return _html(
            html,
            headers={
                "Cache-Control": "no-store",
                "X-Robots-Tag": "noindex",
            },
        )

    @router.post("/quality/run")
    async def run_quality(request: Request) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            result = _run_quality_check(settings)
        except RuntimeError as error:
            with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
                audit.record(
                    actor_id=session.actor_id,
                    role=session.role,
                    action="quality.run",
                    target_type="quality_run",
                    target_id=str(_quality_run_path()),
                    outcome=AuditOutcome.FAILURE,
                    metadata={"error": str(error)},
                )
            return _html(str(error), status_code=HTTPStatus.BAD_REQUEST)
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="quality.run",
                target_type="quality_run",
                target_id=result.candidate_path,
                outcome=(
                    AuditOutcome.SUCCESS
                    if result.failed_samples == 0
                    else AuditOutcome.FAILURE
                ),
                metadata={
                    "total_samples": result.total_samples,
                    "translated_samples": result.translated_samples,
                    "failed_samples": result.failed_samples,
                },
            )
        return RedirectResponse("/admin/quality", status_code=HTTPStatus.SEE_OTHER)

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Settings",
            active="settings",
            body=lambda session: settings_body(
                _secret_safety_report(settings),
                beta_allowlist_enabled=_beta_allowlist_policy(settings).enabled,
                beta_allowlist_ids=_beta_allowlist_ids(settings),
                beta_safety_settings=_beta_safety_setting_values(settings),
                csrf_token=session.csrf_token,
            ),
        )

    @router.get("/beta-controls", response_class=HTMLResponse)
    async def beta_controls(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Beta Controls",
            active="beta_controls",
            body=lambda session: settings_body(
                _secret_safety_report(settings),
                beta_allowlist_enabled=_beta_allowlist_policy(settings).enabled,
                beta_allowlist_ids=_beta_allowlist_ids(settings),
                beta_safety_settings=_beta_safety_setting_values(settings),
                csrf_token=session.csrf_token,
            ),
        )

    @router.post("/settings/beta-allowlist/toggle")
    async def toggle_beta_allowlist(request: Request) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        enabled = form.get("enabled") == "true"
        with SQLiteAdminSettingsStore(settings.admin_db_path) as store:
            store.set_value(
                BETA_ALLOWLIST_ENABLED_SETTING,
                "true" if enabled else "false",
                changed_by=session.actor_id,
            )
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="settings.beta_allowlist.enabled_changed",
                target_type="setting",
                target_id=BETA_ALLOWLIST_ENABLED_SETTING.key,
                outcome=AuditOutcome.SUCCESS,
                metadata={"enabled": enabled},
            )
        return RedirectResponse("/admin/settings", status_code=HTTPStatus.SEE_OTHER)

    @router.post("/settings/beta-allowlist/add")
    async def add_beta_allowlist_id(request: Request) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            telegram_id = _single_telegram_id(form.get("telegram_id", ""))
        except ValueError as error:
            return _html(str(error), status_code=HTTPStatus.BAD_REQUEST)

        ids = sorted({*_beta_allowlist_ids(settings), telegram_id})
        _save_beta_allowlist_ids(
            settings,
            ids,
            actor_id=session.actor_id,
            role=session.role,
            audit_action="settings.beta_allowlist.added",
        )
        return RedirectResponse("/admin/settings", status_code=HTTPStatus.SEE_OTHER)

    @router.post("/settings/beta-allowlist/remove")
    async def remove_beta_allowlist_id(request: Request) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            telegram_id = _single_telegram_id(form.get("telegram_id", ""))
        except ValueError as error:
            return _html(str(error), status_code=HTTPStatus.BAD_REQUEST)

        ids = [
            user_id
            for user_id in _beta_allowlist_ids(settings)
            if user_id != telegram_id
        ]
        _save_beta_allowlist_ids(
            settings,
            ids,
            actor_id=session.actor_id,
            role=session.role,
            audit_action="settings.beta_allowlist.removed",
        )
        return RedirectResponse("/admin/settings", status_code=HTTPStatus.SEE_OTHER)

    @router.post("/settings/beta-allowlist")
    async def save_beta_allowlist(request: Request) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        ids = parse_telegram_id_list(form.get("telegram_ids", ""))
        _save_beta_allowlist_ids(
            settings,
            ids,
            actor_id=session.actor_id,
            role=session.role,
            audit_action="settings.beta_allowlist.updated",
        )
        return RedirectResponse("/admin/settings", status_code=HTTPStatus.SEE_OTHER)

    @router.post("/settings/beta-safety")
    async def save_beta_safety_settings(request: Request) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        definitions = beta_safety_setting_definitions_from_settings(settings)
        try:
            values = [
                (definition, _form_setting_value(definition, form))
                for definition in definitions
            ]
            with SQLiteAdminSettingsStore(settings.admin_db_path) as store:
                store.set_values(values, changed_by=session.actor_id)
        except ValueError as error:
            return _html(str(error), status_code=HTTPStatus.BAD_REQUEST)
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="settings.beta_safety.updated",
                target_type="setting_group",
                target_id="beta_safety",
                outcome=AuditOutcome.SUCCESS,
                metadata={"keys": [definition.key for definition, _value in values]},
            )
        return RedirectResponse("/admin/settings", status_code=HTTPStatus.SEE_OTHER)

    @router.get("/live", response_class=HTMLResponse)
    async def live(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Live Monitor",
            active="live",
            body=lambda session: live_body(
                _live_snapshot(settings),
                runtime_statuses=_ai_provider_runtime_statuses(settings),
                runtime_reload_states=_ai_provider_runtime_reload_states(settings),
                beta_safety=_beta_safety_cost_summary(settings),
            ),
        )

    @router.get("/logs", response_class=HTMLResponse)
    async def logs(request: Request) -> Response:
        filters = _log_filters(request)
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Translation Logs",
            active="logs",
            body=lambda session: logs_body(
                _translation_run_summaries(settings, **filters),
                **filters,
            ),
        )

    @router.get("/translations", response_class=HTMLResponse)
    async def translations(request: Request) -> Response:
        filters = _log_filters(request)
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Translations",
            active="translations",
            body=lambda session: logs_body(
                _translation_run_summaries(settings, **filters),
                title="Translations",
                form_action="/admin/translations",
                **filters,
            ),
        )

    @router.get("/logs/{run_id}", response_class=HTMLResponse)
    async def log_detail(run_id: str, request: Request) -> Response:
        if _session_or_none(request, session_manager) is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        details = _translation_run_details(settings, run_id)
        if details is None:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Translation Details",
            active="logs",
            body=log_detail_body(details),
        )

    @router.get("/logs/{run_id}/text-diagnostics", response_class=HTMLResponse)
    async def log_text_diagnostics(run_id: str, request: Request) -> Response:
        if _session_or_none(request, session_manager) is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        details = _translation_run_details(settings, run_id)
        if details is None:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        limit = _bounded_int(request.query_params.get("limit"), default=25, maximum=100)
        start_sequence = _sequence_from_page_or_query(
            page_value=request.query_params.get("page"),
            sequence_value=request.query_params.get("sequence"),
            limit=limit,
        )
        show_invisibles = _query_flag(request.query_params.get("show_invisibles"))
        search_query = _query_text(request.query_params.get("q"), maximum=200)
        indent_preview = _query_flag(request.query_params.get("indent_preview"))
        qa_filter = _query_choice(
            request.query_params.get("qa"),
            choices={
                "all",
                "issues",
                "empty_source",
                "missing_translation",
                "length_mismatch",
                "paragraph_mismatch",
                "indent",
            },
            default="all",
        )
        rows = _translation_text_diagnostics(
            settings,
            job_id=details.summary.job_id,
            start_sequence=start_sequence,
            limit=limit,
        )
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Translation Text Diagnostics",
            active="logs",
            body=translation_text_diagnostics_body(
                details,
                rows,
                run_id=run_id,
                start_sequence=start_sequence,
                limit=limit,
                show_invisibles=show_invisibles,
                search_query=search_query,
                indent_preview=indent_preview,
                qa_filter=qa_filter,
            ),
        )

    @router.get("/logs/{run_id}/reader", response_class=HTMLResponse)
    async def log_reader(run_id: str, request: Request) -> Response:
        if _session_or_none(request, session_manager) is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        details = _translation_run_details(settings, run_id)
        if details is None:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        limit = _bounded_int(
            request.query_params.get("limit"),
            default=100,
            maximum=500,
        )
        start_sequence = _sequence_from_page_or_query(
            page_value=request.query_params.get("page"),
            sequence_value=request.query_params.get("sequence"),
            limit=limit,
        )
        show_invisibles = _query_flag(request.query_params.get("show_invisibles"))
        sync_scroll = _query_flag(request.query_params.get("sync"), default=True)
        search_query = _query_text(request.query_params.get("q"), maximum=200)
        search_hits_only = bool(search_query) and _query_flag(
            request.query_params.get("search_hits")
        )
        pane_mode = _query_choice(
            request.query_params.get("pane_mode"),
            choices={"split", "original", "translation"},
            default="split",
        )
        indent_preview = _query_flag(request.query_params.get("indent_preview"))
        qa_filter = _query_choice(
            request.query_params.get("qa"),
            choices={
                "all",
                "issues",
                "empty_source",
                "missing_translation",
                "length_mismatch",
                "paragraph_mismatch",
                "indent",
            },
            default="all",
        )
        rows = _translation_text_diagnostics(
            settings,
            job_id=details.summary.job_id,
            start_sequence=start_sequence,
            limit=limit,
        )
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Translation Reader",
            active="logs",
            body=translation_reader_body(
                details,
                rows,
                run_id=run_id,
                start_sequence=start_sequence,
                limit=limit,
                show_invisibles=show_invisibles,
                sync_scroll=sync_scroll,
                search_query=search_query,
                search_hits_only=search_hits_only,
                pane_mode=pane_mode,
                indent_preview=indent_preview,
                qa_filter=qa_filter,
            ),
        )

    @router.get("/translations/{run_id}/trace", response_class=HTMLResponse)
    async def translation_trace(run_id: str, request: Request) -> Response:
        if _session_or_none(request, session_manager) is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        details = _translation_run_details(settings, run_id)
        if details is None:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        activity_events: tuple[UserActivityEvent, ...] = ()
        if details.summary.job_id:
            with _activity_store(settings) as store:
                activity_events = store.list_events(
                    job_id=details.summary.job_id,
                    limit=25,
                )
        trace = build_translation_trace(
            details,
            operations=_operations_overview(settings),
            activity_events=activity_events,
            runtime_statuses=_ai_provider_runtime_statuses(settings),
            balance_snapshot=_deepseek_balance_snapshot(settings),
        )
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Translation Trace",
            active="translations",
            body=translation_trace_body(trace),
        )

    @router.get("/logs/{run_id}/download")
    async def download_log(run_id: str, request: Request) -> Response:
        if _session_or_none(request, session_manager) is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        archive = build_translation_run_archive(
            settings.translation_run_log_root,
            run_id,
        )
        if archive is None:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        return Response(
            archive.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{_download_file_name(archive.file_name)}"'
                ),
                "Cache-Control": "no-store",
            },
        )

    @router.get("/activity", response_class=HTMLResponse)
    async def activity(request: Request) -> Response:
        filters = _activity_filters(request)
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Activity",
            active="activity",
            body=lambda session: _activity_body(settings, filters),
        )

    @router.get("/users", response_class=HTMLResponse)
    async def users(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Users",
            active="users",
            body=lambda session: _users_body(settings),
        )

    @router.get("/users/{user_id}", response_class=HTMLResponse)
    async def user_detail(user_id: str, request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title=f"User {user_id}",
            active="users",
            body=lambda session: _user_detail_body(settings, user_id),
        )

    @router.get("/security/events", response_class=HTMLResponse)
    async def security_events(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Security",
            active="security",
            body=lambda session: _security_events_body(settings),
        )

    @router.get("/upload-safety", response_class=HTMLResponse)
    async def upload_safety(request: Request) -> Response:
        filters = _upload_safety_filters(request)
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Upload Safety",
            active="upload_safety",
            body=lambda session: _upload_safety_body(settings, filters),
        )

    @router.get("/upload-safety/{upload_id}", response_class=HTMLResponse)
    async def upload_safety_detail(request: Request, upload_id: str) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Upload Safety Detail",
            active="upload_safety",
            body=lambda session: _upload_safety_detail_body(settings, upload_id),
        )

    @router.get("/operations/jobs", response_class=HTMLResponse)
    async def operations(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            environment=settings.environment,
            title="Operations",
            active="operations",
            body=lambda session: operations_body(
                _operations_overview(settings),
                csrf_token=session.csrf_token,
            ),
        )

    @router.post("/operations/jobs/{job_id}/{action}")
    async def operate_job(job_id: str, action: str, request: Request) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        if action not in {"pause", "cancel", "delete"}:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)

        status_code = _apply_admin_job_action(
            settings,
            job_id=job_id,
            action=action,
            actor_id=session.actor_id,
            role=session.role,
        )
        if status_code != HTTPStatus.SEE_OTHER:
            return _html("Unable to update job", status_code=status_code)
        return RedirectResponse(
            "/admin/operations/jobs",
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.get("/api/integrations")
    async def integrations_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json(
            {
                "integrations": _integration_summaries(settings),
                "connections": _integration_connection_groups(settings),
            }
        )

    @router.get("/api/ai-providers")
    async def ai_providers_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json({"providers": _ai_provider_summaries(settings)})

    @router.get("/api/ai-providers/runtime")
    async def ai_provider_runtime_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json({"providers": _ai_provider_runtime_payloads(settings)})

    @router.get("/api/ai-providers/deepseek/balance")
    async def deepseek_balance_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json({"balance": _deepseek_balance_payload(settings)})

    @router.get("/api/costs")
    async def costs_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json(_cost_analytics(settings))

    @router.get("/api/quality")
    async def quality_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json({"quality": _quality_run_summary()})

    @router.get("/api/logs")
    async def logs_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json(
            {
                "logs": _translation_run_summaries(
                    settings,
                    **_log_filters(request),
                )
            }
        )

    @router.get("/api/logs/{run_id}")
    async def log_detail_api(run_id: str, request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        details = _translation_run_details(settings, run_id)
        if details is None:
            return _json({"error": "not_found"}, status_code=HTTPStatus.NOT_FOUND)
        return _json({"details": details})

    @router.get("/api/activity")
    async def activity_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        with _activity_store(settings) as store:
            events = store.list_events(**_activity_filters(request))
        return _json({"events": events})

    @router.get("/api/users")
    async def users_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        with _activity_store(settings) as store:
            users = store.list_user_profiles()
        return _json({"users": users})

    @router.get("/api/live")
    async def live_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json(_live_snapshot(settings))

    @router.post("/api/integrations/{integration_id}/secrets/{secret_id}")
    async def save_integration_secret(
        integration_id: str,
        secret_id: str,
        request: Request,
    ) -> Response:
        return await _save_registry_secret(
            integration_id=integration_id,
            secret_id=secret_id,
            request=request,
            session_manager=session_manager,
            settings=settings,
            registry=DEFAULT_INTEGRATION_REGISTRY,
            audit_action="integration.secret.replaced",
        )

    @router.post("/api/ai-providers/{provider_id}/secrets/{secret_id}")
    async def save_ai_provider_secret(
        provider_id: str,
        secret_id: str,
        request: Request,
    ) -> Response:
        return await _save_registry_secret(
            integration_id=provider_id,
            secret_id=secret_id,
            request=request,
            session_manager=session_manager,
            settings=settings,
            registry=DEFAULT_AI_PROVIDER_REGISTRY,
            audit_action="ai_provider.secret.replaced",
        )

    @router.post("/integrations/{integration_id}/connections")
    async def add_integration_connection(
        integration_id: str,
        request: Request,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            definition = DEFAULT_INTEGRATION_REGISTRY.get_definition(integration_id)
        except KeyError:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        secret_values = {
            key.removeprefix("secret:"): value
            for key, value in form.items()
            if key.startswith("secret:")
        }
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as secrets:
                with SQLiteIntegrationConnectionStore(
                    settings.admin_db_path
                ) as connections:
                    connection = connections.add_connection(
                        definition=definition,
                        label=form.get("label", "").strip() or "unnamed",
                        secret_values=secret_values,
                        actor_id=session.actor_id,
                        secret_store=secrets,
                    )
        except (SecretStoreUnavailable, ValueError):
            return _html("Secret store unavailable", status_code=HTTPStatus.BAD_REQUEST)
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="integration.connection.added",
                target_type="integration_connection",
                target_id=connection.connection_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={
                    "integration_id": integration_id,
                    "connection_id": connection.connection_id,
                },
            )
        return RedirectResponse(
            "/admin/integrations",
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.post("/integrations/{integration_id}/connections/remove")
    async def remove_integration_connection(
        integration_id: str,
        request: Request,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            definition = DEFAULT_INTEGRATION_REGISTRY.get_definition(integration_id)
        except KeyError:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as secrets:
                with SQLiteIntegrationConnectionStore(
                    settings.admin_db_path
                ) as connections:
                    removed = connections.remove_connection(
                        definition=definition,
                        connection_id=form.get("connection_id", ""),
                        actor_id=session.actor_id,
                        secret_store=secrets,
                    )
        except (KeyError, SecretStoreUnavailable):
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="integration.connection.removed",
                target_type="integration_connection",
                target_id=removed.connection_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={
                    "integration_id": integration_id,
                    "connection_id": removed.connection_id,
                },
            )
        return RedirectResponse(
            "/admin/integrations",
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.post("/ai-providers/{provider_id}/keys")
    async def add_ai_provider_key(
        provider_id: str,
        request: Request,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            DEFAULT_AI_PROVIDER_REGISTRY.get_definition(provider_id)
        except KeyError:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as secrets:
                with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                    key = keys.add_key(
                        provider_id=provider_id,
                        label=form.get("label", "").strip() or "unnamed",
                        plaintext=form.get("value", ""),
                        actor_id=session.actor_id,
                        secret_store=secrets,
                        weight=int(form.get("weight", "1") or "1"),
                        max_parallel_requests=int(
                            form.get("max_parallel_requests", "1") or "1"
                        ),
                    )
        except (SecretStoreUnavailable, ValueError):
            return _html("Secret store unavailable", status_code=HTTPStatus.BAD_REQUEST)
        _request_ai_provider_runtime_reload(
            settings,
            provider_id=provider_id,
            actor_id=session.actor_id,
        )
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="ai_provider.key.added",
                target_type="ai_provider_key",
                target_id=key.key_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={
                    "provider_id": provider_id,
                    "key_id": key.key_id,
                    "fingerprint": key.fingerprint,
                    "runtime_reload_requested": True,
                },
            )
        return RedirectResponse(
            _ai_provider_keys_redirect(provider_id),
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.post("/ai-providers/deepseek/balance/refresh")
    async def refresh_deepseek_balance_route(request: Request) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        snapshot = refresh_deepseek_balance(settings)
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="ai_provider.balance.refreshed",
                target_type="ai_provider",
                target_id="deepseek",
                outcome=(
                    AuditOutcome.SUCCESS
                    if snapshot.status in {"available", "unavailable"}
                    else AuditOutcome.FAILURE
                ),
                metadata={
                    "provider_id": "deepseek",
                    "status": snapshot.status,
                    "is_available": snapshot.is_available,
                    "currency_count": len(snapshot.balances),
                    "error_code": snapshot.error_code,
                },
            )
        return RedirectResponse(
            "/admin/ai-providers",
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.post("/ai-providers/{provider_id}/keys/remove")
    async def remove_ai_provider_key(
        provider_id: str,
        request: Request,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as secrets:
                with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                    removed = keys.remove_key(
                        provider_id=provider_id,
                        key_id=form.get("key_id", ""),
                        actor_id=session.actor_id,
                        secret_store=secrets,
                    )
        except (KeyError, SecretStoreUnavailable):
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        _request_ai_provider_runtime_reload(
            settings,
            provider_id=provider_id,
            actor_id=session.actor_id,
        )
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="ai_provider.key.removed",
                target_type="ai_provider_key",
                target_id=removed.key_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={
                    "provider_id": provider_id,
                    "key_id": removed.key_id,
                    "runtime_reload_requested": True,
                },
            )
        return RedirectResponse(
            _ai_provider_keys_redirect(provider_id),
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.post("/ai-providers/{provider_id}/keys/update")
    async def update_ai_provider_key(
        provider_id: str,
        request: Request,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            DEFAULT_AI_PROVIDER_REGISTRY.get_definition(provider_id)
        except KeyError:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as secrets:
                with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                    updated = keys.update_key(
                        provider_id=provider_id,
                        key_id=form.get("key_id", ""),
                        label=form.get("label", ""),
                        weight=int(form.get("weight", "1") or "1"),
                        max_parallel_requests=int(
                            form.get("max_parallel_requests", "1") or "1"
                        ),
                        actor_id=session.actor_id,
                        secret_describer=secrets.describe_secret,
                    )
        except (KeyError, SecretStoreUnavailable):
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        except ValueError:
            return _html("Invalid key settings", status_code=HTTPStatus.BAD_REQUEST)
        _request_ai_provider_runtime_reload(
            settings,
            provider_id=provider_id,
            actor_id=session.actor_id,
        )
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="ai_provider.key.updated",
                target_type="ai_provider_key",
                target_id=updated.key_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={
                    "provider_id": provider_id,
                    "key_id": updated.key_id,
                    "label": updated.label,
                    "weight": updated.weight,
                    "max_parallel_requests": updated.max_parallel_requests,
                    "runtime_reload_requested": True,
                },
            )
        return RedirectResponse(
            _ai_provider_keys_redirect(provider_id),
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.post("/ai-providers/{provider_id}/keys/rotate")
    async def rotate_ai_provider_key(
        provider_id: str,
        request: Request,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            DEFAULT_AI_PROVIDER_REGISTRY.get_definition(provider_id)
        except KeyError:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as secrets:
                with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                    rotated = keys.rotate_key(
                        provider_id=provider_id,
                        key_id=form.get("key_id", ""),
                        plaintext=form.get("value", ""),
                        actor_id=session.actor_id,
                        secret_store=secrets,
                    )
        except ValueError as error:
            return _html(str(error), status_code=HTTPStatus.BAD_REQUEST)
        except (KeyError, SecretStoreUnavailable):
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        _request_ai_provider_runtime_reload(
            settings,
            provider_id=provider_id,
            actor_id=session.actor_id,
        )
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="ai_provider.key.rotated",
                target_type="ai_provider_key",
                target_id=rotated.key_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={
                    "provider_id": provider_id,
                    "key_id": rotated.key_id,
                    "fingerprint": rotated.fingerprint,
                    "runtime_reload_requested": True,
                },
            )
        return RedirectResponse(
            _ai_provider_keys_redirect(provider_id),
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.post("/ai-providers/{provider_id}/keys/disable")
    async def disable_ai_provider_key(
        provider_id: str,
        request: Request,
    ) -> Response:
        return await _set_ai_provider_key_enabled(
            provider_id,
            request,
            enabled=False,
        )

    @router.post("/ai-providers/{provider_id}/keys/enable")
    async def enable_ai_provider_key(
        provider_id: str,
        request: Request,
    ) -> Response:
        return await _set_ai_provider_key_enabled(
            provider_id,
            request,
            enabled=True,
        )

    async def _set_ai_provider_key_enabled(
        provider_id: str,
        request: Request,
        *,
        enabled: bool,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            DEFAULT_AI_PROVIDER_REGISTRY.get_definition(provider_id)
        except KeyError:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as secrets:
                with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                    key = keys.set_key_enabled(
                        provider_id=provider_id,
                        key_id=form.get("key_id", ""),
                        enabled=enabled,
                        actor_id=session.actor_id,
                        secret_describer=secrets.describe_secret,
                    )
        except (KeyError, SecretNotFound, SecretStoreUnavailable):
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        action = "enabled" if enabled else "disabled"
        _request_ai_provider_runtime_reload(
            settings,
            provider_id=provider_id,
            actor_id=session.actor_id,
        )
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action=f"ai_provider.key.{action}",
                target_type="ai_provider_key",
                target_id=key.key_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={
                    "provider_id": provider_id,
                    "key_id": key.key_id,
                    "runtime_reload_requested": True,
                },
            )
        return RedirectResponse(
            _ai_provider_keys_redirect(provider_id),
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.post("/ai-providers/{provider_id}/keys/test")
    async def test_ai_provider_key(
        provider_id: str,
        request: Request,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            DEFAULT_AI_PROVIDER_REGISTRY.get_definition(provider_id)
        except KeyError:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        key_id = form.get("key_id", "")
        audited_key_id: str | None = None
        status = "failed"
        error: str | None = None
        response_status = HTTPStatus.SEE_OTHER
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as secrets:
                with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                    key = keys.get_key(
                        provider_id,
                        key_id,
                        secret_describer=secrets.describe_secret,
                    )
                    audited_key_id = key.key_id
                    status, error = _test_ai_provider_key(
                        provider_id,
                        key,
                        secret_store=secrets,
                        settings=settings,
                    )
                    if status != "provider_check_passed":
                        response_status = HTTPStatus.BAD_REQUEST
        except KeyError:
            error = "Key was not found."
            response_status = HTTPStatus.NOT_FOUND
        except (SecretNotFound, SecretStoreUnavailable, ValueError):
            error = "Key secret is unavailable."
            response_status = HTTPStatus.BAD_REQUEST
        if audited_key_id is not None:
            with SQLiteAIProviderValidationStore(settings.admin_db_path) as validations:
                validations.record_result(
                    provider_id=provider_id,
                    key_id=audited_key_id,
                    status=status,
                    error=error,
                    actor_id=session.actor_id,
                )
            with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
                audit.record(
                    actor_id=session.actor_id,
                    role=session.role,
                    action="ai_provider.key.tested",
                    target_type="ai_provider_key",
                    target_id=audited_key_id,
                    outcome=(
                        AuditOutcome.SUCCESS
                        if status == "provider_check_passed"
                        else AuditOutcome.FAILURE
                    ),
                    metadata={
                        "provider_id": provider_id,
                        "key_id": audited_key_id,
                        "status": status,
                    },
                )
        if response_status != HTTPStatus.SEE_OTHER:
            return _html(error or "Unable to test key", status_code=response_status)
        return RedirectResponse(
            _ai_provider_keys_redirect(provider_id),
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.post("/ai-providers/{provider_id}/keys/test-all")
    async def test_all_ai_provider_keys(
        provider_id: str,
        request: Request,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            DEFAULT_AI_PROVIDER_REGISTRY.get_definition(provider_id)
        except KeyError:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)

        guard = _ai_provider_test_all_guard(settings, provider_id)
        if guard is not None:
            message, metadata = guard
            with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
                audit.record(
                    actor_id=session.actor_id,
                    role=session.role,
                    action="ai_provider.keys.tested",
                    target_type="ai_provider",
                    target_id=provider_id,
                    outcome=AuditOutcome.FAILURE,
                    metadata={
                        "provider_id": provider_id,
                        "status": "paused",
                        **metadata,
                    },
                )
            return _html(message, status_code=HTTPStatus.CONFLICT)

        results: list[tuple[str, str, str | None]] = []
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as secrets:
                with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                    key_summaries = keys.list_keys(
                        provider_id,
                        secret_describer=secrets.describe_secret,
                    )
                    for key in key_summaries:
                        if not key.enabled or key.disabled:
                            continue
                        status, error = _test_ai_provider_key(
                            provider_id,
                            key,
                            secret_store=secrets,
                            settings=settings,
                        )
                        results.append((key.key_id, status, error))
        except (SecretStoreUnavailable, ValueError):
            return _html(
                "Key secret is unavailable.",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        if not results:
            return _html("No active keys to test", status_code=HTTPStatus.BAD_REQUEST)

        with SQLiteAIProviderValidationStore(settings.admin_db_path) as validations:
            for key_id, status, error in results:
                validations.record_result(
                    provider_id=provider_id,
                    key_id=key_id,
                    status=status,
                    error=error,
                    actor_id=session.actor_id,
                )

        passed = sum(1 for _, status, _ in results if status == "provider_check_passed")
        failed = len(results) - passed
        status = "provider_check_passed" if failed == 0 else "failed"
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="ai_provider.keys.tested",
                target_type="ai_provider",
                target_id=provider_id,
                outcome=AuditOutcome.SUCCESS if failed == 0 else AuditOutcome.FAILURE,
                metadata={
                    "provider_id": provider_id,
                    "status": status,
                    "passed": passed,
                    "failed": failed,
                },
            )
        return RedirectResponse(
            _ai_provider_keys_redirect(provider_id),
            status_code=HTTPStatus.SEE_OTHER,
        )

    @router.post("/ai-providers/{provider_id}/runtime/reload")
    async def request_ai_provider_runtime_reload(
        provider_id: str,
        request: Request,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        try:
            DEFAULT_AI_PROVIDER_REGISTRY.get_definition(provider_id)
        except KeyError:
            return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
        with SQLiteAIProviderRuntimeStore(settings.admin_db_path) as runtime:
            runtime.request_reload(
                provider_id=provider_id,
                actor_id=session.actor_id,
            )
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="ai_provider.runtime.reload_requested",
                target_type="ai_provider",
                target_id=provider_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={"provider_id": provider_id},
            )
        return RedirectResponse(
            "/admin/ai-providers",
            status_code=HTTPStatus.SEE_OTHER,
        )

    async def _save_registry_secret(
        *,
        integration_id: str,
        secret_id: str,
        request: Request,
        session_manager: AdminSessionManager,
        settings: Settings,
        registry: IntegrationRegistry,
        audit_action: str,
    ) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _json({"error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN)
        requirement = _secret_requirement(registry, integration_id, secret_id)
        if requirement is None:
            return _json({"error": "not_found"}, status_code=HTTPStatus.NOT_FOUND)
        value = form.get("value", "")
        if not value:
            return _json(
                {"error": "missing_secret_value"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as store:
                metadata = store.put_secret(
                    secret_id=secret_id,
                    label=requirement.label,
                    kind=requirement.kind,
                    plaintext=value,
                    actor_id=session.actor_id,
                )
        except SecretStoreUnavailable:
            return _json(
                {"error": "secret_store_unavailable"},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action=audit_action,
                target_type="integration_secret",
                target_id=secret_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={
                    "integration_id": integration_id,
                    "secret_id": secret_id,
                    "fingerprint": metadata.fingerprint,
                    "version": metadata.version,
                },
            )
        if _safe_admin_next(form.get("next")):
            return RedirectResponse(form["next"], status_code=HTTPStatus.SEE_OTHER)
        return _json({"secret": metadata})

    @router.get("/api/operations/overview")
    async def operations_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json({"overview": _operations_overview(settings)})

    def page(
        path: str,
        *,
        title: str,
        active: str,
        copy: str,
    ) -> None:
        async def handler(request: Request) -> Response:
            return _protected_page(
                request,
                session_manager=session_manager,
                environment=settings.environment,
                title=title,
                active=active,
                body=section_body(title, copy),
            )

        router.add_api_route(
            path,
            handler,
            methods=["GET"],
            response_class=HTMLResponse,
        )

    page(
        "/audit",
        title="Audit",
        active="audit",
        copy=(
            "Every sensitive admin change will be visible here with actor, "
            "outcome, reason, and redacted metadata."
        ),
    )
    return router


async def _urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _session_or_none(
    request: Request,
    session_manager: AdminSessionManager,
) -> AdminSession | None:
    try:
        return session_manager.load(request.cookies.get(SESSION_COOKIE))
    except AdminAuthError:
        return None


def _integration_summaries(settings: Settings):
    return apply_integration_bootstrap(
        _registry_summaries(DEFAULT_INTEGRATION_REGISTRY, settings),
        env_bootstrap_config(),
    )


def _ai_provider_summaries(settings: Settings):
    return _registry_summaries(DEFAULT_AI_PROVIDER_REGISTRY, settings)


def _ai_provider_key_pools(settings: Settings):
    bootstrap_config = env_bootstrap_config()
    if not settings.admin_secret_master_key:
        return apply_ai_provider_key_bootstrap({}, bootstrap_config)
    try:
        with SQLiteEncryptedSecretStore(
            settings.admin_db_path,
            master_key=settings.admin_secret_master_key,
        ) as secrets:
            with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                key_pools = {
                    definition.integration_id: keys.list_keys(
                        definition.integration_id,
                        secret_describer=secrets.describe_secret,
                    )
                    for definition in DEFAULT_AI_PROVIDER_REGISTRY.list_definitions()
                }
    except SecretStoreUnavailable:
        return apply_ai_provider_key_bootstrap({}, bootstrap_config)
    return apply_ai_provider_key_bootstrap(key_pools, bootstrap_config)


def _ai_provider_health(settings: Settings):
    summaries = _ai_provider_summaries(settings)
    validation_metadata = _ai_provider_validation_metadata(settings)
    runtime_statuses = _ai_provider_runtime_statuses(settings)
    bootstrap_config = env_bootstrap_config()
    if not settings.admin_secret_master_key:
        return build_provider_health(
            summaries,
            apply_ai_provider_key_bootstrap({}, bootstrap_config),
            validation_metadata,
            runtime_statuses=runtime_statuses,
        )
    try:
        with SQLiteEncryptedSecretStore(
            settings.admin_db_path,
            master_key=settings.admin_secret_master_key,
        ) as secrets:
            with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                key_pools = {
                    definition.integration_id: keys.list_keys(
                        definition.integration_id,
                        secret_describer=secrets.describe_secret,
                        include_removed=True,
                    )
                    for definition in DEFAULT_AI_PROVIDER_REGISTRY.list_definitions()
                }
    except SecretStoreUnavailable:
        key_pools = {}
    key_pools = apply_ai_provider_key_bootstrap(key_pools, bootstrap_config)
    return build_provider_health(
        summaries,
        key_pools,
        validation_metadata,
        runtime_statuses=runtime_statuses,
    )


def _ai_provider_validation_metadata(settings: Settings):
    with SQLiteAIProviderValidationStore(settings.admin_db_path) as validations:
        return validations.latest_by_provider()


def _ai_provider_key_validation_views(
    settings: Settings,
    provider_id: str,
    *,
    keys=(),
):
    with SQLiteAIProviderValidationStore(settings.admin_db_path) as validations:
        return validations.latest_by_key(
            provider_id,
            key_updated_at={key.key_id: key.updated_at for key in keys},
        )


def _ai_provider_runtime_statuses(settings: Settings):
    with SQLiteAIProviderRuntimeStore(settings.admin_db_path) as runtime:
        return tuple(
            status
            for definition in DEFAULT_AI_PROVIDER_REGISTRY.list_definitions()
            if (status := runtime.get_status(definition.integration_id)) is not None
        )


def _ai_provider_runtime_reload_states(settings: Settings):
    with SQLiteAIProviderRuntimeStore(settings.admin_db_path) as runtime:
        return tuple(
            state
            for definition in DEFAULT_AI_PROVIDER_REGISTRY.list_definitions()
            if (state := runtime.get_reload_state(definition.integration_id))
            is not None
        )


def _ai_provider_test_all_guard(
    settings: Settings,
    provider_id: str,
) -> tuple[str, dict[str, int | str]] | None:
    with SQLiteAIProviderRuntimeStore(settings.admin_db_path) as runtime:
        status = runtime.get_status(provider_id)
    provider_state = (
        status.provider_state
        if status is not None
        else AIProviderRuntimeProviderState()
    )
    active_requests = max(
        provider_state.active_requests,
        sum(channel.active_requests for channel in status.active_channels)
        if status is not None
        else 0,
    )
    active_translations, active_translation_state = _active_translation_metadata(
        settings
    )
    if (
        active_requests <= 0
        and active_translations <= 0
        and active_translation_state != "unknown"
    ):
        return None
    available_slots = provider_state.available_slots
    current_limit = provider_state.current_limit
    message = (
        "Test all active provider keys is paused while translations or provider "
        f"requests are active. Active translations: {active_translations}; "
        f"active provider requests: {active_requests}; "
        f"available provider slots: {available_slots}; "
        f"adaptive limit: {current_limit}. Try again when active translations "
        "and provider requests return to 0."
    )
    return (
        message,
        {
            "active_translations": active_translations,
            "active_translation_state": active_translation_state,
            "active_provider_requests": active_requests,
            "available_provider_slots": available_slots,
            "provider_current_limit": current_limit,
        },
    )


def _active_translation_metadata(settings: Settings) -> tuple[int, str]:
    try:
        operations = _operations_overview(settings)
        snapshot = build_live_monitor_snapshot(
            settings.translation_run_log_root,
            operations=operations,
            server=ServerHealthSnapshot(),
        )
        return (snapshot.active_translations, "known")
    except Exception:
        return 0, "unknown"


def _ai_provider_runtime_payloads(settings: Settings):
    statuses = {
        status.provider_id: status for status in _ai_provider_runtime_statuses(settings)
    }
    reload_states = {
        state.provider_id: state
        for state in _ai_provider_runtime_reload_states(settings)
    }
    now = datetime.now(UTC)
    payloads = []
    for definition in DEFAULT_AI_PROVIDER_REGISTRY.list_definitions():
        status = statuses.get(definition.integration_id)
        reload_state = reload_states.get(definition.integration_id)
        payloads.append(
            _ai_provider_runtime_payload(
                definition.integration_id,
                status=status,
                reload_state=reload_state,
                now=now,
            )
        )
    return payloads


def _ai_provider_runtime_payload(
    provider_id: str,
    *,
    status,
    reload_state,
    now: datetime,
):
    if status is None:
        return {
            "provider_id": provider_id,
            "source": "not_reporting",
            "status": "not_reporting",
            "freshness": "not_reporting",
            "last_reported_at": None,
            "reload_interval_seconds": None,
            "active_channels": [],
            "provider_state": _ai_provider_runtime_provider_state_payload(
                AIProviderRuntimeProviderState()
            ),
            "error": None,
            "reload_pending": bool(reload_state and reload_state.pending),
            "reload_requested_by": (
                reload_state.actor_id if reload_state is not None else None
            ),
            "reload_requested_at": (
                reload_state.requested_at.isoformat()
                if reload_state is not None
                else None
            ),
            "reload_consumed_at": (
                reload_state.consumed_at.isoformat()
                if reload_state is not None and reload_state.consumed_at is not None
                else None
            ),
        }
    age_seconds = (now - status.last_reloaded_at.astimezone(UTC)).total_seconds()
    stale_after = max(120.0, status.reload_interval_seconds * 3)
    return {
        "provider_id": provider_id,
        "source": status.source,
        "status": status.status,
        "freshness": "stale" if age_seconds > stale_after else "fresh",
        "last_reported_at": status.last_reloaded_at.isoformat(),
        "reload_interval_seconds": status.reload_interval_seconds,
        "active_channels": [
            _ai_provider_runtime_channel_payload(channel)
            for channel in status.active_channels
        ],
        "provider_state": _ai_provider_runtime_provider_state_payload(
            status.provider_state
        ),
        "error": _safe_runtime_error_text(status.error),
        "reload_pending": bool(reload_state and reload_state.pending),
        "reload_requested_by": (
            reload_state.actor_id if reload_state is not None else None
        ),
        "reload_requested_at": (
            reload_state.requested_at.isoformat() if reload_state is not None else None
        ),
        "reload_consumed_at": (
            reload_state.consumed_at.isoformat()
            if reload_state is not None and reload_state.consumed_at is not None
            else None
        ),
    }


def _ai_provider_runtime_provider_state_payload(state):
    return {
        "adaptive_enabled": state.adaptive_enabled,
        "current_limit": state.current_limit,
        "max_capacity": state.max_capacity,
        "active_requests": state.active_requests,
        "available_slots": state.available_slots,
        "circuit_state": _safe_runtime_text(state.circuit_state),
        "circuit_open_remaining_seconds": state.circuit_open_remaining_seconds,
        "last_reason": _safe_runtime_error_text(state.last_reason),
        "total_ramp_ups": state.total_ramp_ups,
        "total_decreases": state.total_decreases,
        "total_circuit_opened": state.total_circuit_opened,
    }


def _ai_provider_runtime_channel_payload(channel):
    return {
        "label": _safe_runtime_text(channel.label),
        "weight": channel.weight,
        "max_parallel_requests": channel.max_parallel_requests,
        "active_requests": channel.active_requests,
        "health": channel.health,
        "cooldown_remaining_seconds": channel.cooldown_remaining_seconds,
        "total_started_requests": channel.total_started_requests,
        "total_successful_requests": channel.total_successful_requests,
        "total_temporary_failures": channel.total_temporary_failures,
        "total_permanent_failures": channel.total_permanent_failures,
        "total_rate_limit_failures": channel.total_rate_limit_failures,
        "total_unavailable_failures": channel.total_unavailable_failures,
        "total_timeout_failures": channel.total_timeout_failures,
        "total_malformed_response_failures": (
            channel.total_malformed_response_failures
        ),
        "total_auth_failures": channel.total_auth_failures,
        "total_billing_failures": channel.total_billing_failures,
        "total_other_provider_failures": channel.total_other_provider_failures,
        "total_unsafe_model_output_failures": (
            channel.total_unsafe_model_output_failures
        ),
        "average_latency_ms": channel.average_latency_ms,
        "last_latency_ms": channel.last_latency_ms,
        "error_kind": _safe_runtime_text(channel.error_kind),
        "last_error_excerpt": _safe_runtime_error_text(channel.last_error_excerpt),
    }


def _safe_runtime_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _redact_sensitive_text(value)


def _safe_runtime_error_text(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return "[redacted]"


def _deepseek_balance_snapshot(settings: Settings) -> ProviderBalanceSnapshot | None:
    return get_cached_deepseek_balance(settings)


def _deepseek_balance_payload(settings: Settings):
    snapshot = _deepseek_balance_snapshot(settings)
    if snapshot is None:
        return {"provider_id": "deepseek", "status": "not_checked"}
    return {
        "provider_id": snapshot.provider_id,
        "status": snapshot.status,
        "is_available": snapshot.is_available,
        "balances": [
            {
                "currency": amount.currency,
                "total_balance": str(amount.total_balance),
                "granted_balance": str(amount.granted_balance),
                "topped_up_balance": str(amount.topped_up_balance),
            }
            for amount in snapshot.balances
        ],
        "last_checked_at": snapshot.last_checked_at.isoformat(),
        "last_success_at": (
            snapshot.last_success_at.isoformat()
            if snapshot.last_success_at is not None
            else None
        ),
        "error_code": snapshot.error_code,
        "error_message": (
            _safe_runtime_text(snapshot.error_message)
            if snapshot.error_message is not None
            else None
        ),
    }


def _ai_provider_keys_redirect(provider_id: str) -> str:
    if provider_id == "deepseek":
        return "/admin/ai-providers/deepseek/keys"
    return "/admin/ai-providers"


def _request_ai_provider_runtime_reload(
    settings: Settings,
    *,
    provider_id: str,
    actor_id: str,
) -> None:
    with SQLiteAIProviderRuntimeStore(settings.admin_db_path) as runtime:
        runtime.request_reload(provider_id=provider_id, actor_id=actor_id)


def _overview_action_center(settings: Settings):
    bootstrap_config = env_bootstrap_config()
    integration_summaries = _integration_summaries(settings)
    integration_connections = _integration_connection_groups(settings)
    ai_provider_key_pools = _ai_provider_key_pools(settings)
    operations = _operations_overview(settings)
    live_snapshot = _live_snapshot(settings, operations=operations)
    secret_safety_report = _secret_safety_report(settings)
    return build_action_center(
        integration_summaries=integration_summaries,
        integration_connections=integration_connections,
        failed_today=live_snapshot.failed_today,
        failed_translation_runs=_overview_failed_translation_runs(
            settings,
            now=live_snapshot.generated_at,
        ),
        tokens_today=live_snapshot.tokens_today,
        disk_percent=live_snapshot.server.disk_percent,
        queued_translations=live_snapshot.queued_translations,
        oldest_pending_age_seconds=operations.oldest_pending_age_seconds,
        deepseek_key_count=_deepseek_key_count(ai_provider_key_pools),
        secret_safety_issue_count=secret_safety_report.issue_count,
        bootstrap_config=bootstrap_config,
        runtime_statuses=_ai_provider_runtime_statuses(settings),
        runtime_reload_states=_ai_provider_runtime_reload_states(settings),
        deepseek_balance_snapshot=_deepseek_balance_snapshot(settings),
        deepseek_low_balance_threshold=_decimal_setting(
            settings.admin_deepseek_low_balance_threshold
        ),
        deepseek_low_balance_currency=settings.admin_deepseek_low_balance_currency,
        deepseek_balance_stale_seconds=settings.admin_deepseek_balance_stale_seconds,
        beta_safety=_beta_safety_cost_summary(settings),
    )


def _decimal_setting(value: str) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _overview_failed_translation_runs(settings: Settings, *, now: datetime):
    today = now.astimezone(UTC).date()
    return tuple(
        run
        for run in list_translation_run_summaries(
            settings.translation_run_log_root,
            limit=25,
            now=now,
        )
        if run.status in _FAILED_TRANSLATION_STATUSES
        and run.started_at is not None
        and run.started_at.astimezone(UTC).date() == today
    )


def _secret_safety_report(settings: Settings):
    bootstrap_config = env_bootstrap_config()
    return build_secret_safety_report(
        integration_summaries=_integration_summaries(settings),
        integration_connections=_integration_connection_groups(settings),
        ai_provider_key_pools=_ai_provider_all_key_pools(settings),
        provider_health_summaries=_ai_provider_health(settings),
        bootstrap_config=bootstrap_config,
    )


def _ai_provider_all_key_pools(settings: Settings):
    bootstrap_config = env_bootstrap_config()
    if not settings.admin_secret_master_key:
        return apply_ai_provider_key_bootstrap({}, bootstrap_config)
    try:
        with SQLiteEncryptedSecretStore(
            settings.admin_db_path,
            master_key=settings.admin_secret_master_key,
        ) as secrets:
            with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                key_pools = {
                    definition.integration_id: keys.list_keys(
                        definition.integration_id,
                        secret_describer=secrets.describe_secret,
                        include_removed=True,
                    )
                    for definition in DEFAULT_AI_PROVIDER_REGISTRY.list_definitions()
                }
    except SecretStoreUnavailable:
        return apply_ai_provider_key_bootstrap({}, bootstrap_config)
    return apply_ai_provider_key_bootstrap(key_pools, bootstrap_config)


def _deepseek_key_count(ai_provider_key_pools) -> int:
    return sum(
        1
        for key in ai_provider_key_pools.get("deepseek", ())
        if key.enabled and not key.disabled
    )


def _live_snapshot(settings: Settings, *, operations=None):
    active_operations = (
        operations if operations is not None else _operations_overview(settings)
    )
    return build_live_monitor_snapshot(
        settings.translation_run_log_root,
        operations=active_operations,
        runtime_statuses=_ai_provider_runtime_statuses(settings),
    )


def _operations_overview(settings: Settings):
    return build_persistent_operations_overview(
        settings.persistent_jobs_db_path,
        settings.translation_run_log_root,
        scheduler_backend=settings.scheduler_backend,
        postgres_dsn=settings.postgres_dsn,
    )


def _apply_admin_job_action(
    settings: Settings,
    *,
    job_id: str,
    action: str,
    actor_id: str,
    role: str,
) -> HTTPStatus:
    store = open_persistent_job_store(settings)
    object_keys: set[str] = set()
    try:
        job = store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND
        if action == "pause":
            updated = store.pause_job(job_id)
            status = "paused"
            message = "Translation paused by admin."
        elif action == "cancel":
            updated = store.cancel_job(job_id)
            status = "cancelled"
            message = "Translation cancelled by admin."
        elif action == "delete":
            updated = job
            object_keys = _job_object_keys(store, job)
            if not store.delete_job(job_id):
                return HTTPStatus.NOT_FOUND
            status = "deleted"
            message = "Translation deleted by admin."
        else:
            return HTTPStatus.NOT_FOUND
    finally:
        store.close()

    finish_running_translation_runs_for_job(
        settings.translation_run_log_root,
        job_id=job_id,
        status="cancelled" if action in {"cancel", "delete"} else "paused",
        error_message=message,
    )
    _record_admin_translation_action(
        settings,
        job=updated,
        action=action,
        actor_id=actor_id,
        role=role,
        status=status,
        notification_message=message,
    )
    if action == "delete":
        _delete_job_objects(settings, object_keys)
    return HTTPStatus.SEE_OTHER


def _job_object_keys(store, job) -> set[str]:
    object_keys = {
        key
        for key in (
            job.source_object_key,
            job.partial_object_key,
            job.final_object_key,
        )
        if key
    }
    object_keys.update(
        unit.source_object_key
        for unit in store.list_work_units(job.id)
        if unit.source_object_key
    )
    return object_keys


def _delete_job_objects(settings: Settings, object_keys: set[str]) -> None:
    if not object_keys:
        return
    storage = LocalObjectStorage(settings.object_storage_root)
    for object_key in object_keys:
        storage.delete(object_key)


def _record_admin_translation_action(
    settings: Settings,
    *,
    job,
    action: str,
    actor_id: str,
    role: str,
    status: str,
    notification_message: str,
) -> None:
    channel, channel_user_id = _split_channel_user_id(job.user_id)
    metadata = {
        "admin_actor_id": actor_id,
        "file_name": job.file_name,
        "document_kind": job.document_kind,
        "source_language": job.source_language,
        "target_language": job.target_language,
        "notification_message": notification_message,
        "status": status,
    }
    with _activity_store(settings) as activity:
        activity.record_event(
            UserActivityEventInput(
                actor_type=ActivityActorType.ADMIN,
                actor_id=actor_id,
                surface=ActivitySurface.ADMIN,
                event_type=f"translation.admin_{status}",
                action=action,
                outcome=ActivityOutcome.SUCCESS,
                channel=channel,
                channel_user_id=channel_user_id,
                target_type="translation_job",
                target_id=job.id,
                job_id=job.id,
                order_id=job.order_id,
                metadata=metadata,
            )
        )
    with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
        audit.record(
            actor_id=actor_id,
            role=role,
            action=f"translation_job.{action}",
            target_type="translation_job",
            target_id=job.id,
            outcome=AuditOutcome.SUCCESS,
            metadata=metadata,
        )


def _split_channel_user_id(user_id: str) -> tuple[str | None, str | None]:
    if ":" not in user_id:
        return None, user_id
    channel, channel_user_id = user_id.split(":", 1)
    return channel or None, channel_user_id or None


def _cost_analytics(settings: Settings):
    analytics = build_cost_analytics(settings.translation_run_log_root)
    return type(analytics)(
        tokens_today=analytics.tokens_today,
        tokens_last_7_days=analytics.tokens_last_7_days,
        tokens_month_to_date=analytics.tokens_month_to_date,
        estimated_cost_today_usd=analytics.estimated_cost_today_usd,
        estimated_cost_last_7_days_usd=analytics.estimated_cost_last_7_days_usd,
        estimated_cost_month_to_date_usd=analytics.estimated_cost_month_to_date_usd,
        top_runs=analytics.top_runs,
        top_users=analytics.top_users,
        beta_safety=_beta_safety_cost_summary(settings),
    )


def _beta_safety_cost_summary(settings: Settings):
    with SQLiteAdminSettingsStore(settings.admin_db_path) as settings_store:
        limits = load_beta_safety_limits(settings_store, settings)
    with SQLiteBetaSafetyStore(settings.admin_db_path) as beta_store:
        summary = beta_store.get_budget_summary(now=datetime.now(UTC))
    return build_beta_safety_cost_summary(summary, limits)


def _beta_safety_setting_values(settings: Settings):
    definitions = beta_safety_setting_definitions_from_settings(settings)
    with SQLiteAdminSettingsStore(settings.admin_db_path) as store:
        return tuple(store.get_value(definition) for definition in definitions)


def _form_setting_value(definition, form: dict[str, str]) -> str:
    if definition.value_type is SettingValueType.BOOLEAN:
        return "true" if form.get(definition.key) == "true" else "false"
    if definition.key not in form:
        raise ValueError(f"Missing setting: {definition.key}")
    return form[definition.key].strip()


def _beta_allowlist_ids(settings: Settings) -> tuple[int, ...]:
    return tuple(sorted(_beta_allowlist_policy(settings).allowed_telegram_ids))


def _beta_allowlist_policy(settings: Settings):
    return load_beta_access_policy(settings)


def _single_telegram_id(raw: str) -> int:
    ids = parse_telegram_id_list(raw)
    if len(ids) != 1:
        raise ValueError("Enter exactly one positive numeric Telegram user ID.")
    return ids[0]


def _save_beta_allowlist_ids(
    settings: Settings,
    ids,
    *,
    actor_id: str,
    role: str,
    audit_action: str,
) -> None:
    normalized_ids = tuple(ids)
    with SQLiteAdminSettingsStore(settings.admin_db_path) as store:
        store.set_value(
            BETA_ALLOWLIST_SETTING,
            format_telegram_id_list(normalized_ids),
            changed_by=actor_id,
        )
    with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
        audit.record(
            actor_id=actor_id,
            role=role,
            action=audit_action,
            target_type="setting",
            target_id=BETA_ALLOWLIST_SETTING.key,
            outcome=AuditOutcome.SUCCESS,
            metadata={"telegram_id_count": len(normalized_ids)},
        )


def _quality_run_summary():
    return build_quality_run_summary(_quality_run_path())


def _quality_run_path() -> Path:
    return Path("var") / "quality-runs" / "latest.jsonl"


def _run_quality_check(settings: Settings) -> QualityRunResult:
    from translator_service.bot.runtime import build_deepseek_translator

    return write_quality_run(
        _quality_run_path(),
        translator=build_deepseek_translator(settings),
    )


def _activity_store(settings: Settings) -> SQLiteUserActivityStore:
    return SQLiteUserActivityStore(settings.admin_db_path)


def _activity_body(settings: Settings, filters: dict[str, str | None]) -> str:
    with _activity_store(settings) as store:
        events = store.list_events(**filters)
    return activity_body(events, **filters)


def _users_body(settings: Settings) -> str:
    with _activity_store(settings) as store:
        profiles = store.list_user_profiles()
    return users_body(profiles)


def _user_detail_body(settings: Settings, user_id: str) -> str:
    with _activity_store(settings) as store:
        profile = store.get_user_profile(user_id)
        events = store.list_events(actor_id=user_id)
    translations = _user_translation_summaries(settings, user_id, events)
    return user_detail_body(profile, events, translations=translations)


def _translation_run_summaries(
    settings: Settings,
    **filters,
) -> tuple[TranslationRunSummary, ...]:
    current_time = filters.get("now") or datetime.now(UTC)
    summaries = list_translation_run_summaries(
        settings.translation_run_log_root,
        **{**filters, "now": current_time},
    )
    return overlay_translation_run_summaries(
        summaries,
        operations=_operations_overview(settings),
        now=current_time,
    )


def _translation_run_details(
    settings: Settings,
    run_id: str,
) -> TranslationRunDetails | None:
    details = get_translation_run_details(
        settings.translation_run_log_root,
        run_id,
    )
    if details is None:
        return None
    details = overlay_translation_run_details(
        details,
        operations=_operations_overview(settings),
    )
    details = replace(
        details,
        summary=replace(
            details.summary,
            error_message=_safe_work_unit_error_summary(details.summary.error_message),
        ),
    )
    if not details.fragments:
        fragments = _translation_work_unit_fragments(
            settings,
            job_id=details.summary.job_id,
        )
        if fragments:
            details = replace(details, fragments=fragments)
    diagnostic = _translation_work_unit_diagnostic(
        settings,
        job_id=details.summary.job_id,
    )
    if diagnostic is None:
        return details
    return replace(details, work_unit_diagnostic=diagnostic)


def _translation_work_unit_fragments(
    settings: Settings,
    *,
    job_id: str,
) -> tuple[TranslationRunFragmentDetail, ...]:
    if not job_id or not _persistent_job_store_readable(settings):
        return ()
    store = open_persistent_job_store(settings)
    try:
        units = sorted(
            store.list_work_units(job_id),
            key=lambda unit: getattr(unit, "sequence", 0),
        )
    finally:
        store.close()
    return tuple(_translation_work_unit_fragment(unit) for unit in units)


def _translation_work_unit_fragment(unit: object) -> TranslationRunFragmentDetail:
    translated_text = getattr(unit, "translated_text", None) or ""
    prompt_tokens = max(0, int(getattr(unit, "prompt_tokens", 0) or 0))
    completion_tokens = max(0, int(getattr(unit, "completion_tokens", 0) or 0))
    return TranslationRunFragmentDetail(
        sequence=max(0, int(getattr(unit, "sequence", 0) or 0)),
        status=_status_value(getattr(unit, "status", "unknown")),
        elapsed_seconds=_work_unit_elapsed_seconds(unit),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        prompt_cache_hit_tokens=max(
            0,
            int(getattr(unit, "cache_hit_tokens", 0) or 0),
        ),
        prompt_cache_miss_tokens=max(
            0,
            int(getattr(unit, "cache_miss_tokens", 0) or 0),
        ),
        retry_count=max(0, int(getattr(unit, "retry_count", 0) or 0)),
        cache_hit=bool(getattr(unit, "cache_hit_tokens", 0) or 0),
        prompt_tier=getattr(unit, "prompt_tier", None),
        source_text_hash=getattr(unit, "source_text_hash", None),
        translated_text_hash=None,
        source_text_chars=0,
        translated_text_chars=len(translated_text),
        source_block_ids=tuple(getattr(unit, "source_block_ids", ()) or ()),
        warnings=(),
        error_message=_safe_work_unit_error_summary(getattr(unit, "last_error", None)),
    )


def _work_unit_elapsed_seconds(unit: object) -> float:
    started_at = getattr(unit, "started_at", None)
    completed_at = getattr(unit, "completed_at", None)
    if started_at is None or completed_at is None:
        return 0.0
    try:
        return max(0.0, round((completed_at - started_at).total_seconds(), 2))
    except (AttributeError, TypeError):
        return 0.0


def _translation_text_diagnostics(
    settings: Settings,
    *,
    job_id: str,
    start_sequence: int,
    limit: int,
) -> tuple[dict[str, object], ...]:
    if not job_id or not _persistent_job_store_readable(settings):
        return ()
    store = open_persistent_job_store(settings)
    storage = LocalObjectStorage(settings.object_storage_root)
    try:
        units = store.list_work_units(job_id)
        selected = [
            unit
            for unit in units
            if unit.sequence >= start_sequence
        ][:limit]
        rows = []
        for unit in selected:
            rows.append(
                {
                    "sequence": unit.sequence,
                    "status": getattr(unit.status, "value", str(unit.status)),
                    "source_block_ids": unit.source_block_ids,
                    "source_text": _diagnostic_source_text(storage, unit),
                    "translated_text": unit.translated_text or "",
                    "attempt_count": unit.attempt_count,
                    "max_attempts": unit.max_attempts,
                    "last_error": (
                        _redact_sensitive_text(unit.last_error)
                        if unit.last_error
                        else None
                    ),
                }
            )
        return tuple(rows)
    finally:
        store.close()


def _translation_work_unit_diagnostic(
    settings: Settings,
    *,
    job_id: str,
) -> TranslationWorkUnitDiagnostic | None:
    if not job_id or not _persistent_job_store_readable(settings):
        return None
    store = open_persistent_job_store(settings)
    try:
        units = sorted(
            store.list_work_units(job_id),
            key=lambda unit: getattr(unit, "sequence", 0),
        )
    finally:
        store.close()
    selected = _select_diagnostic_work_unit(units)
    if selected is None:
        return None
    last_error = getattr(selected, "last_error", None)
    return TranslationWorkUnitDiagnostic(
        sequence=getattr(selected, "sequence", 0),
        status=_status_value(getattr(selected, "status", "unknown")),
        source_block_ids=tuple(getattr(selected, "source_block_ids", ()) or ()),
        attempt_count=max(0, int(getattr(selected, "attempt_count", 0) or 0)),
        max_attempts=max(0, int(getattr(selected, "max_attempts", 0) or 0)),
        last_error=_safe_work_unit_error_summary(last_error),
        updated_at=getattr(selected, "updated_at", None),
    )


def _persistent_job_store_readable(settings: Settings) -> bool:
    if settings.scheduler_backend == "sqlite":
        db_path = settings.persistent_jobs_db_path
        return db_path != ":memory:" and sqlite_store_exists(db_path)
    return settings.scheduler_backend == "postgres"


def _select_diagnostic_work_unit(units: list[object]) -> object | None:
    status_priority = (
        {"failed_terminal", "failed"},
        {"failed_retryable"},
        {"translating"},
        {"pending", "queued"},
    )
    for statuses in status_priority:
        for unit in units:
            if _status_value(getattr(unit, "status", "unknown")) in statuses:
                return unit
    return None


def _status_value(status: object) -> str:
    return getattr(status, "value", str(status))


def _safe_work_unit_error_summary(error: object | None) -> str | None:
    if error is None:
        return None
    redacted = _redact_sensitive_text(str(error))
    normalized = " ".join(redacted.split())
    known_safe = {
        "retryable provider failure",
        "source object missing",
        "source object not found",
        "source object key rejected",
        "source object unavailable",
    }
    if normalized in known_safe:
        return normalized
    return "error recorded; open text diagnostics"


def _diagnostic_source_text(storage: LocalObjectStorage, unit) -> str:
    object_key = getattr(unit, "source_object_key", None)
    if not object_key:
        return "[source object missing]"
    try:
        return storage.get_bytes(object_key).decode("utf-8", errors="replace")
    except FileNotFoundError:
        return "[source object not found]"
    except ValueError:
        return "[source object key rejected]"
    except OSError:
        return "[source object unavailable]"


def _user_translation_summaries(
    settings: Settings,
    user_id: str,
    events: tuple[UserActivityEvent, ...],
) -> tuple[TranslationRunSummary, ...]:
    job_ids = {event.job_id for event in events if event.job_id}
    run_ids = {
        Path(event.translation_run_dir).name
        for event in events
        if event.translation_run_dir
    }
    rows: list[TranslationRunSummary] = []
    seen_run_ids: set[str] = set()
    for summary in _translation_run_summaries(settings, limit=500):
        run_id = Path(summary.run_dir).name
        if (
            summary.user_id != user_id
            and summary.job_id not in job_ids
            and run_id not in run_ids
        ):
            continue
        if run_id in seen_run_ids:
            continue
        rows.append(summary)
        seen_run_ids.add(run_id)
        if len(rows) >= 25:
            break
    return tuple(rows)


def _security_events_body(settings: Settings) -> str:
    with _activity_store(settings) as store:
        events = store.list_events(surface=ActivitySurface.SECURITY)
    return security_events_body(events)


def _upload_safety_read_model(settings: Settings):
    with _activity_store(settings) as store:
        events = _upload_safety_activity_events(store)
    return upload_safety_read_model_from_activity_events(
        events,
        job_file_names_by_event_id=_upload_safety_job_file_names(settings, events),
    )


def _upload_safety_job_file_names(
    settings: Settings,
    events: tuple[UserActivityEvent, ...],
) -> dict[str, str]:
    missing_file_events = tuple(
        event
        for event in events
        if event.job_id
        and not (
            event.metadata.get("sanitized_original_filename")
            or event.metadata.get("original_file_name")
            or event.metadata.get("file_name")
        )
    )
    if not missing_file_events:
        return {}

    job_rows = _upload_safety_read_job_rows(
        settings,
        tuple({event.job_id for event in missing_file_events if event.job_id}),
    )
    file_names: dict[str, str] = {}
    for event in missing_file_events:
        if not event.job_id:
            continue
        job_row = job_rows.get(event.job_id)
        if job_row is None:
            continue
        user_id, file_name = job_row
        if file_name and _upload_safety_event_matches_job_user(event, user_id):
            file_names[event.id] = file_name
    return file_names


def _upload_safety_read_job_rows(
    settings: Settings,
    job_ids: tuple[str, ...],
) -> dict[str, tuple[str, str]]:
    if not job_ids:
        return {}
    if settings.scheduler_backend == "sqlite":
        return _upload_safety_read_sqlite_job_rows(
            settings.persistent_jobs_db_path,
            job_ids,
        )
    if settings.scheduler_backend == "postgres":
        return _upload_safety_read_postgres_job_rows(settings.postgres_dsn, job_ids)
    return {}


def _upload_safety_read_sqlite_job_rows(
    db_path: str,
    job_ids: tuple[str, ...],
) -> dict[str, tuple[str, str]]:
    if db_path == ":memory:" or not sqlite_store_exists(db_path):
        return {}
    placeholders = ", ".join("?" for _ in job_ids)
    try:
        connection = sqlite3.connect(_sqlite_read_only_uri(db_path), uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                f"""
                SELECT id, user_id, file_name
                FROM translation_jobs
                WHERE id IN ({placeholders})
                """,
                job_ids,
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return {}
    return {
        str(row["id"]): (str(row["user_id"]), str(row["file_name"]))
        for row in rows
        if row["id"] is not None
    }


def _sqlite_read_only_uri(db_path: str) -> str:
    path = Path(db_path).resolve().as_posix()
    return f"file:{quote(path, safe='/:')}?mode=ro"


def _upload_safety_read_postgres_job_rows(
    postgres_dsn: str,
    job_ids: tuple[str, ...],
) -> dict[str, tuple[str, str]]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError:
        return {}

    params = {f"job_id_{index}": job_id for index, job_id in enumerate(job_ids)}
    placeholders = ", ".join(f"%({key})s" for key in params)
    try:
        with psycopg.connect(
            postgres_dsn,
            autocommit=True,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                f"""
                SELECT id, user_id, file_name
                FROM translation_jobs
                WHERE id IN ({placeholders})
                """,
                params,
            ).fetchall()
    except Exception:
        return {}
    return {
        str(row["id"]): (str(row["user_id"]), str(row["file_name"]))
        for row in rows
        if row.get("id") is not None
    }


def _upload_safety_event_matches_job_user(
    event: UserActivityEvent,
    job_user_id: str,
) -> bool:
    return job_user_id in _upload_safety_event_user_ids(event)


def _upload_safety_event_user_ids(event: UserActivityEvent) -> set[str]:
    user_ids: set[str] = set()
    if event.actor_id:
        user_ids.add(event.actor_id)
        if event.actor_id.isdecimal():
            user_ids.add(f"telegram:{event.actor_id}")
    if event.channel == "telegram" and event.channel_user_id:
        user_ids.add(f"telegram:{event.channel_user_id}")
    return user_ids


def _upload_safety_activity_events(
    store: SQLiteUserActivityStore,
) -> tuple[UserActivityEvent, ...]:
    events: list[UserActivityEvent] = []
    offset = 0
    while True:
        page = store.list_events(
            surface=ActivitySurface.SECURITY,
            event_type=UPLOAD_SAFETY_ACTIVITY_EVENT_TYPE,
            limit=_UPLOAD_SAFETY_EVENT_PAGE_SIZE,
            offset=offset,
        )
        if not page:
            break
        events.extend(page)
        if len(page) < _UPLOAD_SAFETY_EVENT_PAGE_SIZE:
            break
        offset += len(page)
    return tuple(events)


def _upload_safety_body(settings: Settings, filters: UploadSafetyFilters) -> str:
    read_model = _upload_safety_read_model(settings)
    records = read_model.list_records(filters)
    return upload_safety_body(
        read_model.summarize(filters),
        records,
        filters=filters,
    )


def _upload_safety_detail_body(settings: Settings, upload_id: str) -> str:
    read_model = _upload_safety_read_model(settings)
    return upload_safety_detail_body(read_model.get_record(upload_id))


def _integration_connection_groups(settings: Settings):
    bootstrap_config = env_bootstrap_config()
    if not settings.admin_secret_master_key:
        return apply_integration_connection_bootstrap({}, bootstrap_config)
    try:
        with SQLiteEncryptedSecretStore(
            settings.admin_db_path,
            master_key=settings.admin_secret_master_key,
        ) as secrets:
            with SQLiteIntegrationConnectionStore(
                settings.admin_db_path
            ) as connections:
                groups = {
                    definition.integration_id: connections.list_connections(
                        definition,
                        secret_describer=secrets.describe_secret,
                    )
                    for definition in DEFAULT_INTEGRATION_REGISTRY.list_definitions()
                }
    except SecretStoreUnavailable:
        groups = {}
    return apply_integration_connection_bootstrap(groups, bootstrap_config)


def _registry_summaries(registry: IntegrationRegistry, settings: Settings):
    if not settings.admin_secret_master_key:
        return registry.list_summaries()
    try:
        with SQLiteEncryptedSecretStore(
            settings.admin_db_path,
            master_key=settings.admin_secret_master_key,
        ) as store:
            return registry.list_summaries(secret_describer=store.describe_secret)
    except SecretStoreUnavailable:
        return registry.list_summaries()


def _secret_requirement(
    registry: IntegrationRegistry,
    integration_id: str,
    secret_id: str,
):
    try:
        definition = registry.get_definition(integration_id)
    except KeyError:
        return None
    for requirement in definition.secret_requirements:
        if requirement.secret_id == secret_id:
            return requirement
    return None


def _test_ai_provider_key(
    provider_id: str,
    key: AIProviderKeySummary,
    *,
    secret_store: SQLiteEncryptedSecretStore,
    settings: Settings,
) -> tuple[str, str | None]:
    if not key.enabled or key.disabled:
        return "failed", "Key is disabled or unavailable."
    try:
        plaintext = secret_store.get_secret_value(key.secret_id)
    except (SecretNotFound, ValueError):
        return "failed", "Key secret is unavailable."
    probe = validate_ai_provider_key(
        provider_id,
        plaintext,
        base_url=settings.deepseek_base_url,
        timeout_seconds=settings.admin_provider_probe_timeout_seconds,
    )
    error = probe.error
    if probe.status == "failed" and error is None:
        error = "Key secret is empty."
    return probe.status, error


def _protected_page(
    request: Request,
    *,
    session_manager: AdminSessionManager,
    environment: str,
    title: str,
    active: str,
    body: str | Callable[[AdminSession], str],
) -> Response:
    session = _session_or_none(request, session_manager)
    if session is None:
        return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
    rendered_body = body(session) if callable(body) else body
    return _html(
        admin_page(
            title=title,
            active=active,
            session=session,
            body=rendered_body,
            environment=environment,
        ),
        headers={"Cache-Control": "no-store"},
    )


def _html(
    body: str,
    *,
    status_code: int | HTTPStatus = HTTPStatus.OK,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    return HTMLResponse(body, status_code=int(status_code), headers=headers)


def _json(
    payload: object,
    *,
    status_code: int | HTTPStatus = HTTPStatus.OK,
) -> JSONResponse:
    return JSONResponse(jsonable_encoder(payload), status_code=int(status_code))


def _download_file_name(value: str) -> str:
    return value.replace("\\", "_").replace("/", "_").replace('"', "_")


def _safe_admin_next(value: str | None) -> bool:
    return bool(value) and value.startswith("/admin/") and not value.startswith("//")


def _internal_reader_requested_source(request: Request) -> str:
    selected_source = request.query_params.get("source_select", "").strip()
    manual_source = request.query_params.get("source", "").strip()
    return selected_source or manual_source


def _internal_reader_source_options() -> tuple[tuple[str, str], ...]:
    sample_root = _REPO_ROOT / "test_samples"
    if not sample_root.exists():
        return ()
    options: list[tuple[str, str]] = []
    for path in sorted(sample_root.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _INTERNAL_READER_FORMAT_BY_SUFFIX:
            continue
        relative = path.relative_to(_REPO_ROOT).as_posix()
        options.append((relative, relative))
    return tuple(options)


def _internal_reader_report_html(
    *,
    source_value: str,
    mapping_value: str,
    requested_format: str,
    max_fragment_chars: int,
) -> str:
    source_path = _internal_reader_local_file(source_value, label="Source")
    source_format = _internal_reader_source_format(source_path, requested_format)
    translations = None
    if mapping_value.strip():
        mapping_path = _internal_reader_local_file(
            mapping_value,
            label="Translation mapping",
        )
        try:
            translations = load_translation_mapping(mapping_path)
        except ValueError as exc:
            raise ValueError(f"Invalid translation mapping: {exc}") from exc
        except OSError as exc:
            raise ValueError("Translation mapping could not be read.") from exc
    try:
        if source_format == "epub":
            return generate_epub_reader_html_from_path(
                source_path=source_path,
                translated_by_block_id=translations,
                max_fragment_chars=max_fragment_chars,
            )
        if source_format == "docx":
            return generate_docx_reader_html_from_path(
                source_path=source_path,
                translated_by_block_id=translations,
                max_fragment_chars=max_fragment_chars,
            )
        return generate_txt_reader_html_from_path(
            source_path=source_path,
            translated_by_block_id=translations,
            max_fragment_chars=max_fragment_chars,
        )
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError("Source file could not be read.") from exc


def _internal_reader_local_file(value: str, *, label: str) -> Path:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{label} path is required.")
    path = Path(stripped).expanduser()
    if not path.is_absolute():
        path = _REPO_ROOT / path
    try:
        resolved = path.resolve(strict=False)
        reject_runtime_var_path(resolved)
    except ValueError as exc:
        raise ValueError(f"{label} path is not allowed: {exc}") from exc
    if not resolved.exists():
        raise ValueError(f"{label} file was not found.")
    if not resolved.is_file():
        raise ValueError(f"{label} path must point to a file.")
    return resolved


def _internal_reader_source_format(source_path: Path, requested_format: str) -> str:
    if requested_format not in (
        _INTERNAL_READER_FORMAT_AUTO,
        *_INTERNAL_READER_SUPPORTED_FORMATS,
    ):
        supported = ", ".join(
            (_INTERNAL_READER_FORMAT_AUTO, *_INTERNAL_READER_SUPPORTED_FORMATS)
        )
        raise ValueError(f"Unsupported source format; use one of: {supported}.")
    if requested_format != _INTERNAL_READER_FORMAT_AUTO:
        return requested_format
    detected = _INTERNAL_READER_FORMAT_BY_SUFFIX.get(source_path.suffix.lower())
    if detected is None:
        supported = ", ".join(_INTERNAL_READER_SUPPORTED_FORMATS)
        raise ValueError(
            "Cannot auto-detect source format from extension; "
            f"use an explicit format: {supported}."
        )
    return detected


def _log_filters(request: Request) -> dict[str, str | int | None]:
    return {
        "status": request.query_params.get("status") or None,
        "date_from": request.query_params.get("date_from") or None,
        "date_to": request.query_params.get("date_to") or None,
        "limit": _safe_limit(request.query_params.get("limit")),
    }


def _activity_filters(request: Request) -> dict[str, str | None]:
    return {
        "actor_id": request.query_params.get("actor_id") or None,
        "channel_user_id": request.query_params.get("channel_user_id") or None,
        "surface": request.query_params.get("surface") or None,
        "event_type": request.query_params.get("event_type") or None,
        "action": request.query_params.get("action") or None,
        "outcome": request.query_params.get("outcome") or None,
        "job_id": request.query_params.get("job_id") or None,
        "date_from": request.query_params.get("date_from") or None,
        "date_to": request.query_params.get("date_to") or None,
    }


def _upload_safety_filters(request: Request) -> UploadSafetyFilters:
    return UploadSafetyFilters(
        date_from=request.query_params.get("date_from") or None,
        date_to=request.query_params.get("date_to") or None,
        final_action=request.query_params.get("final_action") or None,
        av_verdict=request.query_params.get("av_verdict") or None,
        container_verdict=request.query_params.get("container_verdict") or None,
        reason_code=request.query_params.get("reason_code") or None,
        channel_user_id=request.query_params.get("channel_user_id") or None,
        declared_format=request.query_params.get("declared_format") or None,
    )


def _safe_limit(value: str | None) -> int:
    if value is None:
        return 100
    try:
        return max(1, min(int(value), 500))
    except ValueError:
        return 100


def _positive_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return max(1, int(value))
    except ValueError:
        return default


def _optional_positive_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return max(1, int(value))
    except ValueError:
        return None


def _sequence_from_page_or_query(
    *,
    page_value: str | None,
    sequence_value: str | None,
    limit: int,
) -> int:
    page = _optional_positive_int(page_value)
    if page is not None:
        return ((page - 1) * max(1, limit)) + 1
    return _positive_int(sequence_value, default=1)


def _query_flag(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _query_text(value: str | None, *, maximum: int) -> str:
    if value is None:
        return ""
    return value.strip()[:maximum]


def _query_choice(
    value: str | None,
    *,
    choices: set[str],
    default: str,
) -> str:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in choices:
        return normalized
    return default


def _bounded_int(value: str | None, *, default: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        return max(1, min(int(value), maximum))
    except ValueError:
        return default
