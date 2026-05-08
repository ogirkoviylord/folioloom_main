from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.audit import AuditOutcome, SQLiteAdminAuditLog
from translator_service.admin.auth import (
    AdminAuthError,
    AdminSession,
    AdminSessionManager,
)
from translator_service.admin.integration_connections import (
    SQLiteIntegrationConnectionStore,
)
from translator_service.admin.integrations import (
    DEFAULT_AI_PROVIDER_REGISTRY,
    DEFAULT_INTEGRATION_REGISTRY,
    IntegrationRegistry,
)
from translator_service.admin.live import build_live_monitor_snapshot
from translator_service.admin.operations import build_operations_overview
from translator_service.admin.secrets import (
    SecretStoreUnavailable,
    SQLiteEncryptedSecretStore,
)
from translator_service.admin.translation_logs import list_translation_run_summaries
from translator_service.admin.views import (
    admin_page,
    activity_body,
    ai_providers_body,
    billing_body,
    integrations_body,
    live_body,
    login_page,
    logs_body,
    operations_body,
    security_events_body,
    section_body,
    user_detail_body,
    users_body,
)
from translator_service.config import Settings
from translator_service.user_activity import ActivitySurface, SQLiteUserActivityStore

SESSION_COOKIE = "folioloom_admin_session"


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
            secure=False,
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
            title="Integrations",
            active="integrations",
            body=lambda session: integrations_body(
                _integration_summaries(settings),
                csrf_token=session.csrf_token,
                connections=_integration_connection_groups(settings),
            ),
        )

    @router.get("/ai-providers", response_class=HTMLResponse)
    async def ai_providers(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            title="AI Providers",
            active="ai_providers",
            body=lambda session: ai_providers_body(
                _ai_provider_summaries(settings),
                csrf_token=session.csrf_token,
                key_pools=_ai_provider_key_pools(settings),
            ),
        )

    @router.get("/billing", response_class=HTMLResponse)
    async def billing(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            title="Billing",
            active="billing",
            body=billing_body(),
        )

    @router.get("/live", response_class=HTMLResponse)
    async def live(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            title="Live Monitor",
            active="live",
            body=live_body(_live_snapshot(settings)),
        )

    @router.get("/logs", response_class=HTMLResponse)
    async def logs(request: Request) -> Response:
        filters = _log_filters(request)
        return _protected_page(
            request,
            session_manager=session_manager,
            title="Translation Logs",
            active="logs",
            body=logs_body(
                list_translation_run_summaries(
                    settings.translation_run_log_root,
                    **filters,
                ),
                **filters,
            ),
        )

    @router.get("/activity", response_class=HTMLResponse)
    async def activity(request: Request) -> Response:
        filters = _activity_filters(request)
        with _activity_store(settings) as store:
            events = store.list_events(**filters)
        return _protected_page(
            request,
            session_manager=session_manager,
            title="Activity",
            active="activity",
            body=activity_body(events, **filters),
        )

    @router.get("/users", response_class=HTMLResponse)
    async def users(request: Request) -> Response:
        with _activity_store(settings) as store:
            profiles = store.list_user_profiles()
        return _protected_page(
            request,
            session_manager=session_manager,
            title="Users",
            active="users",
            body=users_body(profiles),
        )

    @router.get("/users/{user_id}", response_class=HTMLResponse)
    async def user_detail(user_id: str, request: Request) -> Response:
        with _activity_store(settings) as store:
            profile = store.get_user_profile(user_id)
            events = store.list_events(actor_id=user_id)
        return _protected_page(
            request,
            session_manager=session_manager,
            title=f"User {user_id}",
            active="users",
            body=user_detail_body(profile, events),
        )

    @router.get("/security/events", response_class=HTMLResponse)
    async def security_events(request: Request) -> Response:
        with _activity_store(settings) as store:
            events = store.list_events(surface=ActivitySurface.SECURITY)
        return _protected_page(
            request,
            session_manager=session_manager,
            title="Security",
            active="security",
            body=security_events_body(events),
        )

    @router.get("/operations/jobs", response_class=HTMLResponse)
    async def operations(request: Request) -> Response:
        return _protected_page(
            request,
            session_manager=session_manager,
            title="Operations",
            active="operations",
            body=operations_body(build_operations_overview()),
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

    @router.get("/api/logs")
    async def logs_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json(
            {
                "logs": list_translation_run_summaries(
                    settings.translation_run_log_root,
                    **_log_filters(request),
                )
            }
        )

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
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="ai_provider.key.added",
                target_type="ai_provider_key",
                target_id=key.secret_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={
                    "provider_id": provider_id,
                    "key_id": key.key_id,
                    "fingerprint": key.fingerprint,
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
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="ai_provider.key.removed",
                target_type="ai_provider_key",
                target_id=removed.secret_id,
                outcome=AuditOutcome.SUCCESS,
                metadata={"provider_id": provider_id, "key_id": removed.key_id},
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
        return _json({"overview": build_operations_overview()})

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
        "/overview",
        title="Overview",
        active="overview",
        copy=(
            "Central service status, revenue signals, integration health, "
            "and pending actions will live here."
        ),
    )
    page(
        "/settings",
        title="Settings",
        active="settings",
        copy=(
            "Configurable service parameters will be edited here with validation, "
            "audit history, and restart hints."
        ),
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
    return _registry_summaries(DEFAULT_INTEGRATION_REGISTRY, settings)


def _ai_provider_summaries(settings: Settings):
    return _registry_summaries(DEFAULT_AI_PROVIDER_REGISTRY, settings)


def _ai_provider_key_pools(settings: Settings):
    if not settings.admin_secret_master_key:
        return {}
    try:
        with SQLiteEncryptedSecretStore(
            settings.admin_db_path,
            master_key=settings.admin_secret_master_key,
        ) as secrets:
            with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                return {
                    definition.integration_id: keys.list_keys(
                        definition.integration_id,
                        secret_describer=secrets.describe_secret,
                    )
                    for definition in DEFAULT_AI_PROVIDER_REGISTRY.list_definitions()
                }
    except SecretStoreUnavailable:
        return {}


def _live_snapshot(settings: Settings):
    return build_live_monitor_snapshot(
        settings.translation_run_log_root,
        operations=build_operations_overview(),
    )


def _activity_store(settings: Settings) -> SQLiteUserActivityStore:
    return SQLiteUserActivityStore(settings.admin_db_path)


def _integration_connection_groups(settings: Settings):
    if not settings.admin_secret_master_key:
        return {}
    try:
        with SQLiteEncryptedSecretStore(
            settings.admin_db_path,
            master_key=settings.admin_secret_master_key,
        ) as secrets:
            with SQLiteIntegrationConnectionStore(
                settings.admin_db_path
            ) as connections:
                return {
                    definition.integration_id: connections.list_connections(
                        definition,
                        secret_describer=secrets.describe_secret,
                    )
                    for definition in DEFAULT_INTEGRATION_REGISTRY.list_definitions()
                }
    except SecretStoreUnavailable:
        return {}


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


def _protected_page(
    request: Request,
    *,
    session_manager: AdminSessionManager,
    title: str,
    active: str,
    body: str | Callable[[AdminSession], str],
) -> Response:
    session = _session_or_none(request, session_manager)
    if session is None:
        return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
    rendered_body = body(session) if callable(body) else body
    return _html(
        admin_page(title=title, active=active, session=session, body=rendered_body),
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


def _safe_admin_next(value: str | None) -> bool:
    return bool(value) and value.startswith("/admin/") and not value.startswith("//")


def _log_filters(request: Request) -> dict[str, str | None]:
    return {
        "status": request.query_params.get("status") or None,
        "date_from": request.query_params.get("date_from") or None,
        "date_to": request.query_params.get("date_to") or None,
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
