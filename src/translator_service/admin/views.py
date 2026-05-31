from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from translator_service.admin.action_center import ActionCenter, ActionItem
from translator_service.admin.ai_provider_keys import AIProviderKeySummary
from translator_service.admin.auth import AdminSession
from translator_service.admin.bootstrap_config import is_env_deepseek_key
from translator_service.admin.costs import (
    BetaSafetyCostSummary,
    CostAnalytics,
    CostRunSummary,
    CostUserSummary,
)
from translator_service.admin.integration_connections import (
    IntegrationConnectionSummary,
)
from translator_service.admin.integrations import (
    IntegrationSecretSummary,
    IntegrationSummary,
)
from translator_service.admin.live import LiveMonitorSnapshot
from translator_service.admin.operations import OperationsOverview
from translator_service.admin.provider_balance import ProviderBalanceSnapshot
from translator_service.admin.provider_health import (
    ProviderHealthSummary,
    _redact_sensitive_text,
)
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeChannel,
    AIProviderRuntimeProviderState,
    AIProviderRuntimeReloadRequest,
    AIProviderRuntimeStatus,
)
from translator_service.admin.provider_validation import AIProviderKeyValidationView
from translator_service.admin.quality import (
    QualityLanguageGroup,
    QualityRunSummary,
    QualitySampleScore,
)
from translator_service.admin.secret_safety import SecretSafetyItem, SecretSafetyReport
from translator_service.admin.settings import AdminSettingValue, SettingValueType
from translator_service.admin.translation_logs import (
    TranslationRunDetails,
    TranslationRunEvent,
    TranslationRunFragmentDetail,
    TranslationRunSummary,
)
from translator_service.admin.translation_trace import (
    TranslationTrace,
    TranslationTraceFact,
    TranslationTraceLink,
    TranslationTraceProviderSignal,
    TranslationTraceTimelineItem,
    trace_href_for_log_href,
    trace_href_for_run_id,
)
from translator_service.admin.upload_safety import (
    UploadSafetyAdminRecord,
    UploadSafetyFilters,
    UploadSafetySummary,
)
from translator_service.user_activity import UserActivityEvent, UserProfile

_PRIMARY_NAV_ITEMS = (
    ("overview", "/admin/overview", "Overview"),
    ("live", "/admin/live", "Live"),
    ("translations", "/admin/translations", "Translations"),
    ("users", "/admin/users", "Users"),
    ("providers", "/admin/ai-providers", "Providers"),
    ("beta_controls", "/admin/beta-controls", "Beta Controls"),
    ("safety", "/admin/upload-safety", "Safety"),
    ("settings", "/admin/settings", "Settings"),
)
_ADVANCED_NAV_ITEMS = (
    ("logs", "/admin/logs", "Logs"),
    ("activity", "/admin/activity", "Activity"),
    ("operations", "/admin/operations/jobs", "Operations"),
    ("audit", "/admin/audit", "Audit"),
    ("integrations", "/admin/integrations", "Integrations"),
    ("billing", "/admin/billing", "Billing"),
    ("costs", "/admin/costs", "Costs"),
    ("quality", "/admin/quality", "Quality"),
    ("security", "/admin/security/events", "Security Events"),
)
_NAV_ACTIVE_ALIASES = {
    "providers": ("ai_providers",),
    "safety": ("upload_safety",),
}
_ACTION_VARIANTS = frozenset(
    {
        "view",
        "copy",
        "refresh",
        "probe",
        "change",
        "danger",
    }
)


def login_page(*, error: str | None = None) -> str:
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Admin Login</title>
  <style>{_css()}</style>
</head>
<body class="login-screen">
  <main class="login-panel">
    <p class="eyebrow">FolioLoom Console</p>
    <h1>Admin Login</h1>
    {error_html}
    <form method="post" action="/admin/login">
      <label>
        Password
        <input name="password" type="password" autocomplete="current-password" required>
      </label>
      <button type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>"""


def admin_page(
    *,
    title: str,
    active: str,
    session: AdminSession,
    body: str,
    environment: str | None = None,
) -> str:
    nav = _admin_nav(active)
    csrf_token = escape(session.csrf_token)
    actor_id = escape(session.actor_id)
    environment_badge = ""
    if environment:
        environment_badge = (
            f'<span class="environment-badge">{escape(environment)}</span>'
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · FolioLoom Console</title>
  <style>{_css()}</style>
</head>
<body>
  <aside class="sidebar">
    <div>
      <p class="eyebrow">FolioLoom</p>
      <h1>Admin Console</h1>
    </div>
    {nav}
    <form method="post" action="/admin/logout">
      <input type="hidden" name="csrf_token" value="{csrf_token}">
      <button type="submit" class="secondary">Sign out</button>
    </form>
  </aside>
  <main class="workspace">
    <header>
      <div>
        <p class="eyebrow">Signed in as {actor_id}</p>
        <h2>{escape(title)}</h2>
      </div>
      {environment_badge}
    </header>
    {body}
  </main>
</body>
</html>"""


def _admin_nav(active: str) -> str:
    primary = "\n".join(_nav_link(item, active) for item in _PRIMARY_NAV_ITEMS)
    advanced = "\n".join(_nav_link(item, active) for item in _ADVANCED_NAV_ITEMS)
    advanced_is_active = any(
        _nav_item_is_active(key, active) for key, _href, _label in _ADVANCED_NAV_ITEMS
    )
    advanced_open = " open" if advanced_is_active else ""
    advanced_class = "nav-section advanced-nav"
    if advanced_is_active:
        advanced_class += " active-group"
    return f"""
    <nav class="sidebar-nav" aria-label="Admin navigation">
      <div class="nav-section primary-nav" aria-label="Primary workflows">
        {primary}
      </div>
      <details class="{advanced_class}"{advanced_open}>
        <summary class="nav-summary">Advanced</summary>
        {advanced}
      </details>
    </nav>
    """


def _nav_link(item: tuple[str, str, str], active: str) -> str:
    key, href, label = item
    class_name = "active" if _nav_item_is_active(key, active) else ""
    return f'<a href="{href}" class="{class_name}">{label}</a>'


def _nav_item_is_active(key: str, active: str) -> bool:
    if key == active:
        return True
    return active in _NAV_ACTIVE_ALIASES.get(key, ())


def _action_link(
    label: str,
    href: str,
    variant: str,
    *,
    compact: bool = False,
    extra_class: str = "",
    target: str | None = None,
    rel: str | None = None,
) -> str:
    safe_variant = _safe_action_variant(variant)
    attrs = [
        f'class="{escape(_action_classes(safe_variant, compact, extra_class))}"',
        f'href="{escape(href)}"',
        f'data-action-variant="{escape(safe_variant)}"',
    ]
    if target:
        attrs.append(f'target="{escape(target)}"')
    if rel:
        attrs.append(f'rel="{escape(rel)}"')
    return f'<a {" ".join(attrs)}>{escape(label)}</a>'


def _action_button(
    label: str,
    variant: str,
    *,
    button_type: str = "submit",
    name: str | None = None,
    value: str | None = None,
    compact: bool = False,
    extra_class: str = "",
    disabled_reason: str | None = None,
) -> str:
    safe_variant = _safe_action_variant(variant)
    attrs = [
        f'class="{escape(_action_classes(safe_variant, compact, extra_class))}"',
        f'type="{escape(button_type)}"',
        f'data-action-variant="{escape(safe_variant)}"',
    ]
    if name is not None:
        attrs.append(f'name="{escape(name)}"')
    if value is not None:
        attrs.append(f'value="{escape(value)}"')
    if disabled_reason:
        attrs.extend(
            (
                "disabled",
                'aria-disabled="true"',
                'data-action-state="disabled"',
                f'data-disabled-reason="{escape(disabled_reason)}"',
            )
        )
        body = (
            f"<span>{escape(label)}</span>"
            " "
            f'<small class="action-disabled-reason">{escape(disabled_reason)}</small>'
        )
    else:
        body = escape(label)
    return f'<button {" ".join(attrs)}>{body}</button>'


def _action_classes(variant: str, compact: bool, extra_class: str) -> str:
    classes = ["action-control", f"action-control-{variant}"]
    if compact:
        classes.append("action-control-compact")
    classes.extend(_safe_class_tokens(extra_class))
    return " ".join(classes)


def _safe_action_variant(variant: str) -> str:
    normalized = variant.strip().lower().replace("_", "-")
    if normalized in _ACTION_VARIANTS:
        return normalized
    return "view"


def _safe_class_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for token in value.split():
        if token.replace("-", "").replace("_", "").isalnum():
            tokens.append(token)
    return tokens


def section_body(title: str, copy: str) -> str:
    return f"""
    <section class="panel">
      <h3>{escape(title)}</h3>
      <p>{escape(copy)}</p>
    </section>
    """


def overview_body(action_center: ActionCenter) -> str:
    if action_center.items:
        rows = "\n".join(_action_item(item) for item in action_center.items)
    else:
        rows = """
        <div class="empty-state">
          Everything quiet. No actionable beta operations items right now.
        </div>
        """
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Triage inbox</h3>
        <p>
          Actionable beta operations items only. Each row explains what
          happened, why it is shown now, what is affected, and the next step.
        </p>
      </div>
    </section>
    <section class="panel action-center">
      <div class="action-list">{rows}</div>
    </section>
    """


def _action_item(item: ActionItem) -> str:
    severity = _safe_action_severity(item.severity)
    href = _safe_action_href(item.href)
    next_action = item.next_action.strip() or "Open"
    return f"""
    <article
      class="action-item action-{escape(severity)}"
      data-action-key="{escape(item.key)}"
    >
      <span class="status">{escape(_action_severity_label(severity))}</span>
      <div class="action-copy">
        <strong>{escape(item.title)}</strong>
        <small>{escape(item.detail)}</small>
        <dl class="action-meta">
          <div>
            <dt>Affected</dt>
            <dd>{escape(item.affected)}</dd>
          </div>
          <div>
            <dt>Why now</dt>
            <dd>{escape(item.reason)}</dd>
          </div>
        </dl>
      </div>
      {_action_link(next_action, href, "view", compact=True, extra_class="action-next")}
      <span class="sr-only">Next step</span>
    </article>
    """


def _safe_action_href(href: str) -> str:
    if href.startswith("/admin/"):
        return href
    return "/admin/overview"


def _safe_action_severity(severity: str) -> str:
    aliases = {
        "critical": "blocked",
        "warning": "watch",
    }
    normalized = aliases.get(severity, severity)
    if normalized in {"info", "watch", "investigate", "action_needed", "blocked"}:
        return normalized
    return "info"


def _action_severity_label(severity: str) -> str:
    return {
        "info": "Info",
        "watch": "Watch",
        "investigate": "Investigate",
        "action_needed": "Action needed",
        "blocked": "Blocked",
    }.get(severity, "Info")


def settings_body(
    report: SecretSafetyReport,
    *,
    beta_allowlist_enabled: bool,
    beta_allowlist_ids: tuple[int, ...],
    beta_safety_settings: tuple[AdminSettingValue, ...] = (),
    csrf_token: str,
) -> str:
    rows = "\n".join(_secret_safety_row(item) for item in report.items)
    if not rows:
        rows = """
        <tr>
          <td class="empty-cell" colspan="6">No configurable secrets registered.</td>
        </tr>
        """
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Secret &amp; Config Safety</h3>
        <p>
          Review configured secrets, provider keys, failed validations, and
          items that need a local check.
        </p>
      </div>
    </section>
    <section class="panel table-panel" id="beta-controls">
      <h3>Closed Beta Allowlist</h3>
      <p>
        Add trusted Telegram numeric user IDs now, then enable enforcement when
        the beta cohort is ready.
      </p>
      {_beta_allowlist_toggle(beta_allowlist_enabled, csrf_token)}
      <form class="secret-form key-form" method="post"
        action="/admin/settings/beta-allowlist/add">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label>
          <span>Telegram user ID</span>
          <input name="telegram_id" type="number" min="1" step="1" required>
        </label>
        {_action_button("Add ID", "change")}
      </form>
      {_beta_allowlist_table(beta_allowlist_ids, csrf_token)}
    </section>
    <section class="panel table-panel" id="beta-safety-controls">
      <h3>Beta Safety Controls</h3>
      <p>
        Live budget guardrails for the closed beta. These values protect beta
        spend and can pause new translation starts without exposing document text.
      </p>
      <form class="secret-form key-form" method="post"
        action="/admin/settings/beta-safety">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        {_beta_safety_setting_inputs(beta_safety_settings)}
        {_action_button("Save beta safety", "change")}
      </form>
    </section>
    <section class="metrics">
      <div class="metric">
        <span>Total</span>
        <strong>{report.total_count}</strong>
      </div>
      <div class="metric">
        <span>Missing</span>
        <strong>{report.missing_count}</strong>
      </div>
      <div class="metric">
        <span>Needs check</span>
        <strong>{report.needs_check_count}</strong>
      </div>
      <div class="metric">
        <span>Failed</span>
        <strong>{report.failed_count}</strong>
      </div>
      <div class="metric">
        <span>Disabled</span>
        <strong>{report.disabled_count}</strong>
      </div>
    </section>
    <section class="panel table-panel">
      <h3>Safety summary</h3>
      <table class="log-table">
        <thead>
          <tr>
            <th>Owner</th>
            <th>Type</th>
            <th>Item</th>
            <th>Status</th>
            <th>Masked value</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """


def _beta_safety_setting_inputs(settings: tuple[AdminSettingValue, ...]) -> str:
    return "\n".join(_beta_safety_setting_input(setting) for setting in settings)


def _beta_safety_setting_input(setting: AdminSettingValue) -> str:
    safe_key = escape(setting.key)
    safe_label = escape(setting.label)
    safe_value = escape(setting.value)
    if setting.value_type is SettingValueType.BOOLEAN:
        checked = " checked" if setting.value.strip().lower() == "true" else ""
        return f"""
        <label>
          <span>{safe_label}</span>
          <input name="{safe_key}"{checked} type="checkbox" value="true">
        </label>
        """
    if setting.value_type is SettingValueType.INTEGER:
        return f"""
        <label>
          <span>{safe_label}</span>
          <input name="{safe_key}" type="number" value="{safe_value}" step="1">
        </label>
        """
    if setting.value_type is SettingValueType.FLOAT:
        return f"""
        <label>
          <span>{safe_label}</span>
          <input name="{safe_key}" type="number" value="{safe_value}" step="0.01">
        </label>
        """
    return f"""
        <label>
          <span>{safe_label}</span>
          <input name="{safe_key}" type="text" value="{safe_value}">
        </label>
    """


def _beta_allowlist_toggle(enabled: bool, csrf_token: str) -> str:
    status = "on" if enabled else "off"
    next_enabled = "false" if enabled else "true"
    label = "Disable allowlist" if enabled else "Enable allowlist"
    variant = "danger" if enabled else "change"
    detail = (
        "Only listed Telegram IDs can start new uploads and translations."
        if enabled
        else "All Telegram users can use the bot while the list is off."
    )
    return f"""
      <div class="key-row">
        <div>
          <strong>Allowlist enforcement: {escape(status)}</strong>
          <span>{escape(detail)}</span>
        </div>
        <form method="post" action="/admin/settings/beta-allowlist/toggle">
          <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
          <input type="hidden" name="enabled" value="{escape(next_enabled)}">
          {_action_button(label, variant, compact=True)}
        </form>
      </div>
    """


def _beta_allowlist_table(ids: tuple[int, ...], csrf_token: str) -> str:
    if not ids:
        return '<p class="empty-state">No Telegram IDs are allowlisted.</p>'
    rows = "\n".join(_beta_allowlist_row(user_id, csrf_token) for user_id in ids)
    return f"""
      <table class="log-table">
        <thead>
          <tr>
            <th>Allowed Telegram IDs</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _beta_allowlist_row(user_id: int, csrf_token: str) -> str:
    safe_id = escape(str(user_id))
    return f"""
      <tr>
        <td><code>{safe_id}</code></td>
        <td>
          <form method="post" action="/admin/settings/beta-allowlist/remove">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
            <input type="hidden" name="telegram_id" value="{safe_id}">
            {_action_button("Remove", "danger", compact=True)}
          </form>
        </td>
      </tr>
    """


def _secret_safety_row(item: SecretSafetyItem) -> str:
    href = _safe_action_href(item.href)
    value = item.masked_value or "not stored"
    return f"""
    <tr>
      <td>{escape(item.owner_label)}</td>
      <td>{escape(item.owner_type)}</td>
      <td>
        <strong>{escape(item.label)}</strong>
        <span>{escape(item.detail)}</span>
      </td>
      <td><span class="status">{escape(item.status.replace("_", " "))}</span></td>
      <td><code>{escape(value)}</code></td>
      <td>{_action_link("Open", href, "view", compact=True)}</td>
    </tr>
    """


def integrations_body(
    summaries: tuple[IntegrationSummary, ...],
    *,
    csrf_token: str,
    connections: dict[str, tuple[IntegrationConnectionSummary, ...]] | None = None,
) -> str:
    cards = "\n".join(
        _integration_card(
            summary,
            csrf_token=csrf_token,
            connections=(connections or {}).get(summary.integration_id, ()),
        )
        for summary in summaries
    )
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Integrations</h3>
        <p>
          Connect user-facing channels, embedded surfaces, webhooks, and
          external automation.
        </p>
      </div>
    </section>
    <section class="grid-list">{cards}</section>
    """


def ai_providers_body(
    summaries: tuple[IntegrationSummary, ...],
    *,
    csrf_token: str,
    key_pools: dict[str, tuple[AIProviderKeySummary, ...]] | None = None,
    health_summaries: tuple[ProviderHealthSummary, ...] = (),
    runtime_statuses: tuple[AIProviderRuntimeStatus, ...] = (),
    runtime_reload_states: tuple[AIProviderRuntimeReloadRequest, ...] = (),
    balance_snapshot: ProviderBalanceSnapshot | None = None,
    balance_stale_seconds: int = 300,
    top_up_url: str = "https://platform.deepseek.com/usage",
) -> str:
    health_by_provider = {health.provider_id: health for health in health_summaries}
    runtime_by_provider = {status.provider_id: status for status in runtime_statuses}
    reload_by_provider = {state.provider_id: state for state in runtime_reload_states}
    cards = "\n".join(
        _ai_provider_card(
            summary,
            csrf_token=csrf_token,
            keys=(key_pools or {}).get(summary.integration_id, ()),
            health=health_by_provider.get(summary.integration_id),
            runtime=runtime_by_provider.get(summary.integration_id),
            reload_state=reload_by_provider.get(summary.integration_id),
            balance_snapshot=balance_snapshot,
            balance_stale_seconds=balance_stale_seconds,
            top_up_url=top_up_url,
        )
        for summary in summaries
    )
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>AI Providers</h3>
        <p>
          Manage model providers, API keys, and provider-level capabilities
          separately from user-facing integrations.
        </p>
      </div>
    </section>
    <section class="grid-list">{cards}</section>
    """


def deepseek_keys_body(
    *,
    csrf_token: str,
    key_pools: dict[str, tuple[AIProviderKeySummary, ...]],
    runtime_reload_states: tuple[AIProviderRuntimeReloadRequest, ...] = (),
    key_validations: dict[str, AIProviderKeyValidationView] | None = None,
) -> str:
    keys = key_pools.get("deepseek", ())
    active_count = sum(
        1
        for key in keys
        if key.enabled and not key.disabled and not is_env_deepseek_key(key)
    )
    disabled_count = sum(
        1
        for key in keys
        if (not key.enabled or key.disabled) and not is_env_deepseek_key(key)
    )
    env_count = sum(1 for key in keys if is_env_deepseek_key(key))
    reload_banner = _deepseek_reload_banner(runtime_reload_states)
    validations = key_validations or {}
    rows = "\n".join(
        _ai_provider_key_row(
            key,
            csrf_token,
            validation=validations.get(key.key_id),
            show_validation=True,
        )
        for key in keys
    )
    if not rows:
        rows = '<p class="empty-state">No DeepSeek keys are configured.</p>'
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>DeepSeek Keys</h3>
        <p>
          Read the DeepSeek key inventory, adjust admin-managed key labels and
          capacity, and keep raw secret values hidden.
        </p>
      </div>
      <div class="toolbar-actions">
        {_action_link("Back to providers", "/admin/ai-providers", "view")}
        {_ai_provider_test_all_keys_form(
            "deepseek",
            csrf_token=csrf_token,
            active_key_count=active_count,
        )}
        {_runtime_reload_form("deepseek", csrf_token)}
      </div>
    </section>
    {reload_banner}
    <section class="metrics">
      {_metric("Ready admin keys", str(active_count))}
      {_metric("Paused admin keys", str(disabled_count))}
      {_metric("Read-only env keys", str(env_count))}
    </section>
    <section class="panel table-panel">
      <h3>Field guide</h3>
      <div class="key-table">
        <div class="key-row compact-row">
          <strong>Ready admin keys</strong>
          <span>encrypted keys added here and currently available for use</span>
        </div>
        <div class="key-row compact-row">
          <strong>Paused admin keys</strong>
          <span>admin-managed keys kept on record but not used while paused</span>
        </div>
        <div class="key-row compact-row">
          <strong>Read-only env keys</strong>
          <span>
            keys supplied by the server environment; shown only as masked
            metadata
          </span>
        </div>
        <div class="key-row compact-row">
          <strong>Weight</strong>
          <span>
            relative share of new requests for this key; higher means more
            traffic
          </span>
        </div>
        <div class="key-row compact-row">
          <strong>Max parallel requests</strong>
          <span>maximum simultaneous DeepSeek requests allowed for this key</span>
        </div>
      </div>
    </section>
    <section class="panel table-panel">
      <h3>Add admin-managed key</h3>
      <p class="helper-text">
        New values are stored encrypted. After saving, this page only shows a
        masked value.
      </p>
      {_ai_provider_key_add_form("deepseek", csrf_token)}
    </section>
    <section class="panel table-panel">
      <h3>Key inventory</h3>
      <p class="helper-text">
        Admin-managed rows are editable. Server environment rows are read-only
        and do not expose raw secrets or secret ids.
      </p>
      <div class="key-list">{rows}</div>
    </section>
    """


def _ai_provider_card(
    summary: IntegrationSummary,
    *,
    csrf_token: str,
    keys: tuple[AIProviderKeySummary, ...],
    health: ProviderHealthSummary | None,
    runtime: AIProviderRuntimeStatus | None,
    reload_state: AIProviderRuntimeReloadRequest | None,
    balance_snapshot: ProviderBalanceSnapshot | None,
    balance_stale_seconds: int,
    top_up_url: str,
) -> str:
    active_key_count = sum(1 for key in keys if key.enabled and not key.disabled)
    testable_key_count = sum(
        1
        for key in keys
        if key.enabled and not key.disabled and not is_env_deepseek_key(key)
    )
    rows = "\n".join(_ai_provider_key_row(key, csrf_token) for key in keys)
    if not rows:
        rows = '<p class="empty-state">No keys configured yet. Test key</p>'
    incident_panel = _provider_incident_panel(
        summary.integration_id,
        keys=keys,
        health=health,
        runtime=runtime,
        reload_state=reload_state,
        balance_snapshot=balance_snapshot,
        balance_stale_seconds=balance_stale_seconds,
    )
    health_panel = _provider_health_panel(health)
    runtime_panel = _provider_runtime_panel(
        summary.integration_id,
        runtime,
        reload_state,
        csrf_token,
    )
    balance_panel = ""
    if summary.integration_id == "deepseek":
        balance_panel = _provider_balance_panel(
            balance_snapshot,
            csrf_token=csrf_token,
            stale_seconds=balance_stale_seconds,
            top_up_url=top_up_url,
        )
    test_all_form = _ai_provider_test_all_keys_form(
        summary.integration_id,
        csrf_token=csrf_token,
        active_key_count=testable_key_count,
    )
    manage_keys_link = ""
    if summary.integration_id == "deepseek":
        manage_keys_link = _action_link(
            "Manage DeepSeek keys",
            "/admin/ai-providers/deepseek/keys",
            "view",
        )
    return f"""
    <article class="integration-card wide-card">
      <div>
        <p class="eyebrow">{escape(summary.category.value.replace("_", " "))}</p>
        <h3>{escape(summary.label)}</h3>
        <span class="status">{active_key_count} active keys</span>
      </div>
      <p>{escape(summary.description)}</p>
      {incident_panel}
      {health_panel}
      {runtime_panel}
      {balance_panel}
      {test_all_form}
      {manage_keys_link}
      <div class="key-table">{rows}</div>
      {_ai_provider_key_add_form(summary.integration_id, csrf_token)}
    </article>
    """


def _provider_incident_panel(
    provider_id: str,
    *,
    keys: tuple[AIProviderKeySummary, ...],
    health: ProviderHealthSummary | None,
    runtime: AIProviderRuntimeStatus | None,
    reload_state: AIProviderRuntimeReloadRequest | None,
    balance_snapshot: ProviderBalanceSnapshot | None,
    balance_stale_seconds: int,
) -> str:
    rows = (
        _provider_incident_row(
            "Keys configured",
            _configured_key_label(keys),
            "Inventory metadata only; raw key values and secret ids stay hidden.",
        ),
        _provider_incident_row(
            "Keys valid",
            _key_validity_label(health, keys),
            "Last validation state from existing safe provider health metadata.",
        ),
        _provider_incident_row(
            "Keys enabled",
            _enabled_key_label(keys),
            "Keys currently allowed for runtime use versus paused/read-only rows.",
        ),
        _provider_incident_row(
            "Runtime sees channels",
            _runtime_channel_visibility_label(runtime),
            "Separates missing usable channels from degraded runtime with channels.",
        ),
        _provider_incident_row(
            "Reload state",
            _runtime_reload_label(reload_state),
            "Whether saved key/settings changes are waiting for bot or worker runtime.",
        ),
        _provider_incident_row(
            "Balance",
            _provider_balance_state_label(
                provider_id,
                balance_snapshot,
                stale_seconds=balance_stale_seconds,
            ),
            "DeepSeek balance metadata only; not a paid billing ledger.",
        ),
        _provider_incident_row(
            "Safe failure categories",
            _safe_provider_failure_category_label(runtime),
            "Provider counters are separated from model-output safety blocks.",
        ),
        _provider_incident_row(
            "Fallback capacity",
            _fallback_capacity_label(runtime),
            "Read-only capacity signal from existing runtime state.",
        ),
    )
    return f"""
      <div class="provider-incident-state">
        <div>
          <h4>Provider incident state</h4>
          <p>
            Read-only diagnosis from existing safe metadata. Probe, change and
            danger actions stay below this section.
          </p>
        </div>
        <div class="incident-state-list">{''.join(rows)}</div>
      </div>
    """


def _provider_incident_row(label: str, value: str, detail: str) -> str:
    return f"""
        <div class="incident-state-row">
          <span>{escape(label)}</span>
          <div>
            <strong>{escape(value)}</strong>
            <small>{escape(detail)}</small>
          </div>
        </div>
    """


def _configured_key_label(keys: tuple[AIProviderKeySummary, ...]) -> str:
    total = len(keys)
    env_count = sum(1 for key in keys if is_env_deepseek_key(key))
    admin_count = total - env_count
    if total == 0:
        return "0 total"
    return f"{total} total / {admin_count} admin / {env_count} env"


def _enabled_key_label(keys: tuple[AIProviderKeySummary, ...]) -> str:
    active = sum(1 for key in keys if key.enabled and not key.disabled)
    paused = len(keys) - active
    return f"{active} active / {paused} paused"


def _key_validity_label(
    health: ProviderHealthSummary | None,
    keys: tuple[AIProviderKeySummary, ...],
) -> str:
    if not keys:
        return "No keys configured"
    if health is None:
        return "Unknown"
    status = health.last_validation_status.strip()
    if not status:
        return "Unknown"
    if status.lower() == "runtime degraded":
        return "not checked"
    return status


def _runtime_channel_visibility_label(
    runtime: AIProviderRuntimeStatus | None,
) -> str:
    if runtime is None:
        return "Unknown"
    active = len(runtime.active_channels)
    degraded = _degraded_runtime_channel_count(runtime)
    if active == 0 or runtime.status == "missing_keys":
        return f"{active} active / missing usable channels"
    if runtime.status in {"degraded", "error", "failed"}:
        return f"{active} active / {degraded} degraded / runtime {runtime.status}"
    return f"{active} active / {degraded} degraded"


def _runtime_reload_label(
    reload_state: AIProviderRuntimeReloadRequest | None,
) -> str:
    if reload_state is None:
        return "No reload requested"
    if reload_state.pending:
        return "Waiting for runtime"
    consumed = (
        reload_state.consumed_at.isoformat(timespec="seconds")
        if reload_state.consumed_at is not None
        else "Unknown"
    )
    return f"Consumed at {consumed}"


def _provider_balance_state_label(
    provider_id: str,
    snapshot: ProviderBalanceSnapshot | None,
    *,
    stale_seconds: int,
) -> str:
    if provider_id != "deepseek":
        return "Unknown"
    if snapshot is None:
        return "Unknown"
    return _balance_status(snapshot, stale_seconds)


def _safe_provider_failure_category_label(
    runtime: AIProviderRuntimeStatus | None,
) -> str:
    if runtime is None:
        return "Unknown"
    channels = runtime.active_channels
    counters = (
        ("rate_limit", sum(channel.total_rate_limit_failures for channel in channels)),
        ("auth", sum(channel.total_auth_failures for channel in channels)),
        ("billing", sum(channel.total_billing_failures for channel in channels)),
        ("timeout", sum(channel.total_timeout_failures for channel in channels)),
        (
            "unavailable",
            sum(channel.total_unavailable_failures for channel in channels),
        ),
        (
            "malformed",
            sum(channel.total_malformed_response_failures for channel in channels),
        ),
        (
            "unsafe_model_output",
            sum(channel.total_unsafe_model_output_failures for channel in channels),
        ),
        (
            "other_provider",
            sum(channel.total_other_provider_failures for channel in channels),
        ),
    )
    visible = [f"{label} {value}" for label, value in counters if value > 0]
    return " / ".join(visible) if visible else "none"


def _fallback_capacity_label(runtime: AIProviderRuntimeStatus | None) -> str:
    if runtime is None:
        return "Unknown"
    if not runtime.active_channels or runtime.status == "missing_keys":
        return "0 slots / 0 usable channels"
    usable_channels = sum(
        1
        for channel in runtime.active_channels
        if channel.health.lower() not in {"disabled", "missing"}
    )
    available_slots = runtime.provider_state.available_slots
    return f"{available_slots} slots / {usable_channels} usable channels"


def _degraded_runtime_channel_count(runtime: AIProviderRuntimeStatus) -> int:
    return sum(
        1
        for channel in runtime.active_channels
        if channel.health.lower() not in {"healthy", "ok", "ready"}
        or bool(channel.error_kind)
        or bool(channel.last_error_excerpt)
    )


def _ai_provider_key_add_form(provider_id: str, csrf_token: str) -> str:
    return f"""
      <form class="secret-form key-form" method="post"
        action="/admin/ai-providers/{escape(provider_id)}/keys">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label>
          <span>Label</span>
          <small class="field-help">
            Owner-facing name, for example main or backup.
          </small>
          <input name="label" type="text" placeholder="main" required>
        </label>
        <label>
          <span>API key</span>
          <small class="field-help">
            Pasted once, stored encrypted, then shown only masked.
          </small>
          <input
            name="value"
            type="password"
            autocomplete="off"
            placeholder="Paste new value"
            required
          >
        </label>
        <label>
          <span>Weight</span>
          <small class="field-help">Relative share of new DeepSeek requests.</small>
          <input name="weight" type="number" min="1" value="1" required>
        </label>
        <label>
          <span>Max parallel requests</span>
          <small class="field-help">Simultaneous requests allowed for this key.</small>
          <input
            name="max_parallel_requests"
            type="number"
            min="1"
            value="1"
            required
          >
        </label>
        {_action_button("Add key", "change")}
      </form>
    """


def _provider_runtime_panel(
    provider_id: str,
    runtime: AIProviderRuntimeStatus | None,
    reload_state: AIProviderRuntimeReloadRequest | None,
    csrf_token: str,
) -> str:
    if runtime is None:
        source = "unknown"
        status = "not reported"
        interval = "n/a"
        last_reload = "n/a"
        freshness = "not reporting"
        error = "n/a"
        provider_state = _runtime_provider_state_row(AIProviderRuntimeProviderState())
        channels = '<p class="empty-state">No runtime channels reported.</p>'
    else:
        source = runtime.source
        status = runtime.status
        interval = _format_seconds(runtime.reload_interval_seconds)
        last_reload = runtime.last_reloaded_at.isoformat()
        freshness = _runtime_freshness(runtime)
        error = _safe_runtime_error_text(runtime.error)
        provider_state = _runtime_provider_state_row(runtime.provider_state)
        channels = "\n".join(
            _runtime_channel_row(channel) for channel in runtime.active_channels
        )
        if not channels:
            channels = '<p class="empty-state">No active runtime channels.</p>'
    reload_label = "No reload requested"
    reload_detail = "n/a"
    if reload_state is not None:
        reload_label = "Reload requested"
        reload_detail = (
            "Waiting for runtime"
            if reload_state.pending
            else f"Consumed at {reload_state.consumed_at.isoformat()}"
        )
    return f"""
      <div class="provider-health">
        <div>
          <h4>Runtime status</h4>
          <span class="status">{escape(status)}</span>
        </div>
        <div class="metric-grid">
          <div class="metric-card">
            <span>Runtime source</span>
            <strong>{escape(source)}</strong>
          </div>
          <div class="metric-card">
            <span>Reload interval</span>
            <strong>{escape(interval)}</strong>
          </div>
          <div class="metric-card">
            <span>Last reload</span>
            <strong>{escape(last_reload)}</strong>
          </div>
          <div class="metric-card">
            <span>Freshness</span>
            <strong>{escape(freshness)}</strong>
          </div>
          <div class="metric-card">
            <span>Runtime error</span>
            <strong>{escape(error)}</strong>
          </div>
          <div class="metric-card">
            <span>{escape(reload_label)}</span>
            <strong>{escape(reload_detail)}</strong>
          </div>
        </div>
        {_provider_processing_summary(runtime)}
        <div class="key-table">{provider_state}{channels}</div>
        {_runtime_reload_form(provider_id, csrf_token, label="Reload now")}
      </div>
    """


def _runtime_reload_form(
    provider_id: str,
    csrf_token: str,
    *,
    label: str = "Reload DeepSeek runtime",
) -> str:
    return f"""
      <form class="secret-form" method="post"
        action="/admin/ai-providers/{escape(provider_id)}/runtime/reload">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        {_action_button(label, "change")}
      </form>
    """


def _deepseek_reload_banner(
    runtime_reload_states: tuple[AIProviderRuntimeReloadRequest, ...],
) -> str:
    state = next(
        (item for item in runtime_reload_states if item.provider_id == "deepseek"),
        None,
    )
    if state is None or not state.pending:
        return ""
    return """
    <section class="panel">
      <h3>DeepSeek runtime reload pending</h3>
      <p>Key changes are saved. Reload runtime so bot and worker capacity use them.</p>
    </section>
    """


def _runtime_provider_state_row(state: AIProviderRuntimeProviderState) -> str:
    adaptive = "enabled" if state.adaptive_enabled else "disabled"
    counters = (
        "ramp/decrease/open "
        f"{state.total_ramp_ups}/{state.total_decreases}/"
        f"{state.total_circuit_opened}"
    )
    return f"""
          <div class="key-row">
            <div>
              <strong>Adaptive throttle</strong>
              <span>{escape(adaptive)}</span>
              <span>circuit {escape(_safe_runtime_text(state.circuit_state))}</span>
              <span>reason {escape(_safe_runtime_error_text(state.last_reason))}</span>
            </div>
            <span>limit {state.current_limit}/{state.max_capacity}</span>
            <span>active {state.active_requests}</span>
            <span>available {state.available_slots}</span>
            <span>
              open for {escape(_format_seconds(state.circuit_open_remaining_seconds))}
            </span>
            <span>{escape(counters)}</span>
          </div>
    """


def _provider_processing_summary(runtime: AIProviderRuntimeStatus | None) -> str:
    if runtime is None:
        cards = (
            (
                "Active key channels",
                "Unknown",
                "Runtime has not reported how many configured channels are usable.",
            ),
            (
                "Active requests",
                "Unknown",
                "Current provider requests are not available yet.",
            ),
            (
                "Available capacity slots",
                "Unknown",
                "Open request slots are not available yet.",
            ),
            (
                "Adaptive limit",
                "Unknown",
                "The adaptive throttle limit is not available yet.",
            ),
            (
                "Cooling/degraded channels",
                "Unknown",
                "Channel health has not been reported by runtime.",
            ),
            (
                "Provider warning counts",
                "Unknown",
                "Rate-limit, auth, billing, and timeout counts are not available yet.",
            ),
        )
    else:
        channels = runtime.active_channels
        active_channels = sum(
            1 for channel in channels if channel.health.lower() != "disabled"
        )
        degraded_channels = sum(
            1
            for channel in channels
            if channel.health.lower() in {"cooling_down", "degraded"}
        )
        rate_limit_count = sum(
            channel.total_rate_limit_failures for channel in channels
        )
        auth_count = sum(channel.total_auth_failures for channel in channels)
        billing_count = sum(channel.total_billing_failures for channel in channels)
        timeout_count = sum(channel.total_timeout_failures for channel in channels)
        unsafe_model_output_count = sum(
            channel.total_unsafe_model_output_failures for channel in channels
        )
        provider_state = runtime.provider_state
        adaptive_state = "on" if provider_state.adaptive_enabled else "off"
        cards = (
            (
                "Active key channels",
                str(active_channels),
                "Configured DeepSeek channels currently available to accept work.",
            ),
            (
                "Active requests",
                str(provider_state.active_requests),
                "Requests currently in flight across the provider runtime.",
            ),
            (
                "Available capacity slots",
                str(provider_state.available_slots),
                "Open request slots after current adaptive throttling.",
            ),
            (
                "Adaptive limit",
                (
                    f"{provider_state.current_limit}/"
                    f"{provider_state.max_capacity} ({adaptive_state})"
                ),
                "Current runtime cap compared with configured maximum capacity.",
            ),
            (
                "Cooling/degraded channels",
                str(degraded_channels),
                "Channels slowed or degraded by recent provider signals.",
            ),
            (
                "Unsafe model outputs",
                str(unsafe_model_output_count),
                (
                    "Model-output safety blocks from translated fragments; "
                    "these do not mean a provider key is broken."
                ),
            ),
            (
                "Provider warning counts",
                (
                    f"429 {rate_limit_count} / auth {auth_count} / "
                    f"billing {billing_count} / timeout {timeout_count}"
                ),
                (
                    "Existing counters for provider rate-limit, auth, billing, "
                    "and timeout signals."
                ),
            ),
        )
    items = "\n".join(
        f"""
          <div class="metric-card">
            <span>{escape(label)}</span>
            <strong>{escape(value)}</strong>
            <small>{escape(detail)}</small>
          </div>
        """
        for label, value, detail in cards
    )
    return f"""
        <div class="processing-summary">
          <div>
            <h4>Processing summary</h4>
            <p>
              Read-only diagnostics from existing DeepSeek runtime data. These
              values explain current processing state; they are not controls or
              production readiness guarantees.
            </p>
          </div>
          <div class="metric-grid">{items}</div>
        </div>
    """


def _runtime_channel_row(channel: AIProviderRuntimeChannel) -> str:
    active = f"active {channel.active_requests}/{channel.max_parallel_requests}"
    counters = (
        "started/ok/temp/perm "
        f"{channel.total_started_requests}/"
        f"{channel.total_successful_requests}/"
        f"{channel.total_temporary_failures}/"
        f"{channel.total_permanent_failures}"
    )
    failure_counters = (
        "429/503/timeout/auth/billing/unsafe "
        f"{channel.total_rate_limit_failures}/"
        f"{channel.total_unavailable_failures}/"
        f"{channel.total_timeout_failures}/"
        f"{channel.total_auth_failures}/"
        f"{channel.total_billing_failures}/"
        f"{channel.total_unsafe_model_output_failures}"
    )
    last_error = escape(_safe_runtime_error_text(channel.last_error_excerpt))
    return f"""
          <div class="key-row">
            <div>
              <strong>{escape(_safe_runtime_text(channel.label))}</strong>
              <span>{escape(channel.health)}</span>
              <span>error_kind {escape(_safe_runtime_text(channel.error_kind))}</span>
              <span>
                last error {last_error}
              </span>
            </div>
            <span>weight {channel.weight}</span>
            <span>parallel {channel.max_parallel_requests}</span>
            <span>{escape(active)}</span>
            <span>
              cooldown {escape(_format_seconds(channel.cooldown_remaining_seconds))}
            </span>
            <span>latency {escape(_format_channel_latency_ms(channel))}</span>
            <span>{escape(counters)}</span>
            <span>{escape(failure_counters)}</span>
          </div>
    """


def _safe_runtime_text(value: str | None) -> str:
    if value is None:
        return "n/a"
    return _redact_sensitive_text(value) or "n/a"


def _safe_runtime_error_text(value: str | None) -> str:
    if value is None or not value.strip():
        return "n/a"
    return "[redacted]"


def _format_latency_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}ms"


def _format_channel_latency_ms(channel: AIProviderRuntimeChannel) -> str:
    value = channel.last_latency_ms
    if value is None:
        value = channel.average_latency_ms
    return _format_latency_ms(value)


def _provider_balance_panel(
    snapshot: ProviderBalanceSnapshot | None,
    *,
    csrf_token: str,
    stale_seconds: int,
    top_up_url: str,
) -> str:
    if snapshot is None:
        status = "not checked"
        rows = '<p class="empty-state">No DeepSeek balance snapshot yet.</p>'
        checked = "n/a"
        success = "n/a"
        error = "n/a"
    else:
        status = _balance_status(snapshot, stale_seconds)
        rows = "\n".join(_balance_metric_row(amount) for amount in snapshot.balances)
        if not rows:
            rows = '<p class="empty-state">No currency balances reported.</p>'
        checked = snapshot.last_checked_at.isoformat(timespec="seconds")
        success = (
            snapshot.last_success_at.isoformat(timespec="seconds")
            if snapshot.last_success_at is not None
            else "n/a"
        )
        error = _safe_runtime_text(snapshot.error_message)
    safe_top_up = _safe_external_href(top_up_url)
    return f"""
      <div class="provider-health">
        <div>
          <h4>DeepSeek account balance</h4>
          <span class="status">{escape(status)}</span>
        </div>
        <div class="metric-grid">
          {rows}
          <div class="metric-card">
            <span>Last checked</span>
            <strong>{escape(checked)}</strong>
          </div>
          <div class="metric-card">
            <span>Last success</span>
            <strong>{escape(success)}</strong>
          </div>
          <div class="metric-card">
            <span>Error</span>
            <strong>{escape(error)}</strong>
          </div>
        </div>
        <form class="secret-form" method="post"
          action="/admin/ai-providers/deepseek/balance/refresh">
          <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
          {_action_button("Refresh balance", "refresh")}
          {_action_link("Open DeepSeek top-up", safe_top_up, "view", rel="noreferrer")}
        </form>
      </div>
    """


def _balance_metric_row(amount) -> str:
    return f"""
      <div class="metric-card">
        <span>{escape(amount.currency)} total</span>
        <strong>{escape(str(amount.total_balance))}</strong>
        <span>
          granted {escape(str(amount.granted_balance))} ·
          top-up {escape(str(amount.topped_up_balance))}
        </span>
      </div>
    """


def _balance_status(snapshot: ProviderBalanceSnapshot, stale_seconds: int) -> str:
    age_seconds = (
        datetime.now(UTC) - snapshot.last_checked_at.astimezone(UTC)
    ).total_seconds()
    if age_seconds > max(1, stale_seconds):
        return "stale"
    return snapshot.status.replace("_", " ")


def _safe_external_href(value: str) -> str:
    if value.startswith("https://"):
        return value
    return "https://platform.deepseek.com/usage"


def _ai_provider_test_all_keys_form(
    provider_id: str,
    *,
    csrf_token: str,
    active_key_count: int,
) -> str:
    disabled_reason = (
        "No active admin-managed keys are available to test."
        if active_key_count == 0
        else None
    )
    button = _action_button(
        "Test all active keys",
        "probe",
        disabled_reason=disabled_reason,
    )
    return f"""
      <form class="secret-form" method="post"
        action="/admin/ai-providers/{escape(provider_id)}/keys/test-all">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        {button}
      </form>
    """


def _format_seconds(value: float) -> str:
    if value.is_integer():
        return f"{int(value)}s"
    return f"{value:.1f}s"


def _format_optional_seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    return _format_seconds(value)


def _runtime_freshness(runtime: AIProviderRuntimeStatus) -> str:
    age_seconds = (
        datetime.now(UTC) - runtime.last_reloaded_at.astimezone(UTC)
    ).total_seconds()
    stale_after = max(120.0, runtime.reload_interval_seconds * 3)
    return "stale" if age_seconds > stale_after else "fresh"


def _provider_health_panel(health: ProviderHealthSummary | None) -> str:
    if health is None:
        return ""
    return f"""
      <div class="provider-health">
        <div>
          <h4>Provider health</h4>
          <span class="status">{escape(health.status.replace("_", " "))}</span>
        </div>
        <div class="metric-grid">
          <div class="metric-card">
            <span>Active keys</span>
            <strong>{health.active_key_count}</strong>
          </div>
          <div class="metric-card">
            <span>Disabled keys</span>
            <strong>{health.disabled_key_count}</strong>
          </div>
          <div class="metric-card">
            <span>Last validation</span>
            <strong>{escape(health.last_validation_status)}</strong>
          </div>
          <div class="metric-card">
            <span>Last error</span>
            <strong>{escape(health.last_error_excerpt)}</strong>
          </div>
        </div>
      </div>
    """


def _ai_provider_key_row(
    key: AIProviderKeySummary,
    csrf_token: str,
    *,
    validation: AIProviderKeyValidationView | None = None,
    show_validation: bool = False,
) -> str:
    if is_env_deepseek_key(key):
        return f"""
    <div class="key-row key-row-readonly">
      <div>
        <strong>{escape(key.label)}</strong>
        <code>{escape(key.masked_value or "server .env")}</code>
        <span>read-only server environment key</span>
        <small class="field-help">
          This key is supplied outside the admin database and cannot be edited
          here.
        </small>
      </div>
      <span>Read-only metadata</span>
      <span>Weight {key.weight}</span>
      <span>Max parallel requests {key.max_parallel_requests}</span>
    </div>
    """
    remove_action = f"/admin/ai-providers/{escape(key.provider_id)}/keys/remove"
    rotate_action = f"/admin/ai-providers/{escape(key.provider_id)}/keys/rotate"
    test_action = f"/admin/ai-providers/{escape(key.provider_id)}/keys/test"
    update_action = f"/admin/ai-providers/{escape(key.provider_id)}/keys/update"
    toggle_action_name = "disable" if key.enabled and not key.disabled else "enable"
    toggle_action = (
        f"/admin/ai-providers/{escape(key.provider_id)}/keys/{toggle_action_name}"
    )
    toggle_label = "Disable" if key.enabled and not key.disabled else "Enable"
    enabled_status = "enabled" if key.enabled and not key.disabled else "disabled"
    validation_html = (
        _ai_provider_key_validation(validation) if show_validation else ""
    )
    toggle_button = _action_button(
        toggle_label,
        "danger" if toggle_label == "Disable" else "change",
        name="key_id",
        value=key.key_id,
    )
    remove_button = _action_button("Remove", "danger", name="key_id", value=key.key_id)
    test_button = _action_button("Test key", "probe", name="key_id", value=key.key_id)
    return f"""
    <div class="key-row">
      <div>
        <strong>{escape(key.label)}</strong>
        <code>{escape(key.masked_value or "missing")}</code>
        <span>Admin-managed key is {enabled_status}</span>
        <small class="field-help">
          Masked value only; the raw secret and secret id stay hidden.
        </small>
        {validation_html}
      </div>
      <form method="post" action="{update_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <input type="hidden" name="key_id" value="{escape(key.key_id)}">
        <label>
          <span>Label</span>
          <small class="field-help">Owner-facing name shown in this inventory.</small>
          <input name="label" type="text" value="{escape(key.label)}" required>
        </label>
        <label>
          <span>Weight</span>
          <small class="field-help">Relative share of new DeepSeek requests.</small>
          <input name="weight" type="number" min="1" value="{key.weight}" required>
        </label>
        <label>
          <span>Max parallel requests</span>
          <small class="field-help">Simultaneous requests allowed for this key.</small>
          <input
            name="max_parallel_requests"
            type="number"
            min="1"
            value="{key.max_parallel_requests}"
            required
          >
        </label>
        {_action_button("Save label", "change")}
      </form>
      <form method="post" action="{rotate_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <input type="hidden" name="key_id" value="{escape(key.key_id)}">
        <label>
          <span>New key value</span>
          <small class="field-help">Replaces the stored encrypted value.</small>
          <input name="value" type="password" autocomplete="new-password">
        </label>
        {_action_button("Rotate", "change")}
      </form>
      <span>Weight {key.weight}</span>
      <span>Max parallel requests {key.max_parallel_requests}</span>
      <form method="post" action="{toggle_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        {toggle_button}
      </form>
      <form method="post" action="{remove_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        {remove_button}
      </form>
      <form method="post" action="{test_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        {test_button}
      </form>
    </div>
    """


def _ai_provider_key_validation(
    validation: AIProviderKeyValidationView | None,
) -> str:
    if validation is None:
        return '<span>Last validation: not checked</span>'
    return f"""
        <span>Last validation: {escape(validation.status)}</span>
        <span>Checked: {escape(validation.checked_at)}</span>
        <span>Last error: {escape(validation.error)}</span>
    """


def billing_body() -> str:
    return """
    <section class="toolbar-panel">
      <div>
        <h3>Billing</h3>
        <p>
          Payment providers, subscriptions, invoices, revenue, refunds,
          webhooks, tax settings, and payout status will live here.
        </p>
      </div>
    </section>
    <section class="panel">
      <h3>Payment providers</h3>
      <p>Stripe and other billing services will be configured inside Billing.</p>
    </section>
    """


def costs_body(analytics: CostAnalytics) -> str:
    metrics = (
        ("Today", analytics.tokens_today, analytics.estimated_cost_today_usd),
        (
            "Last 7 days",
            analytics.tokens_last_7_days,
            analytics.estimated_cost_last_7_days_usd,
        ),
        (
            "Month to date",
            analytics.tokens_month_to_date,
            analytics.estimated_cost_month_to_date_usd,
        ),
    )
    metric_cards = "\n".join(
        f"""
        <article class="metric">
          <span>{escape(label)}</span>
          <strong>{tokens}</strong>
          <span>{escape(_format_usd(cost))}</span>
        </article>
        """
        for label, tokens, cost in metrics
    )
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Token Spend</h3>
        <p>
          Estimated model costs from translation run totals. Billing setup stays
          separate from this usage view.
        </p>
      </div>
    </section>
    <section class="metrics">{metric_cards}</section>
    <section class="panel table-panel">
      <h3>Most expensive runs</h3>
      <table class="log-table">
        <thead>
          <tr>
            <th>Started</th>
            <th>Job</th>
            <th>Order</th>
            <th>User</th>
            <th>File</th>
            <th>Input</th>
            <th>Output</th>
            <th>Total</th>
            <th>Cost</th>
            <th>Logs</th>
          </tr>
        </thead>
        <tbody>{_cost_run_rows(analytics.top_runs)}</tbody>
      </table>
    </section>
    {_beta_safety_cost_panel(analytics.beta_safety)}
    <section class="panel table-panel">
      <h3>Top users (all time)</h3>
      <table class="log-table">
        <thead>
          <tr>
            <th>User</th>
            <th>Input</th>
            <th>Output</th>
            <th>Total tokens</th>
            <th>Cost</th>
          </tr>
        </thead>
        <tbody>{_cost_user_rows(analytics.top_users)}</tbody>
      </table>
    </section>
    """


def _beta_safety_cost_panel(summary: BetaSafetyCostSummary | None) -> str:
    if summary is None:
        return ""
    rows = (
        ("Daily cap", _format_optional_usd(summary.global_daily_cap_usd)),
        ("Daily reserved", _format_usd(summary.global_daily_reserved_usd)),
        ("Daily consumed", _format_usd(summary.global_daily_consumed_usd)),
        ("Daily remaining", _format_optional_usd(summary.global_daily_remaining_usd)),
        ("Monthly cap", _format_optional_usd(summary.global_monthly_cap_usd)),
        ("Monthly reserved", _format_usd(summary.global_monthly_reserved_usd)),
        ("Monthly consumed", _format_usd(summary.global_monthly_consumed_usd)),
        (
            "Monthly remaining",
            _format_optional_usd(summary.global_monthly_remaining_usd),
        ),
        ("Translations paused", "yes" if summary.translations_paused else "no"),
        ("Warning", "yes" if summary.warning else "no"),
    )
    cards = "\n".join(_metric(label, value) for label, value in rows)
    warning = ""
    if summary.warning:
        warning = f"""
        <p class="error">
          {escape(_beta_safety_warning_text(summary))}
        </p>
        """
    return f"""
    <section class="panel">
      <h3>Beta safety budget</h3>
      {warning}
      <div class="metric-grid">{cards}</div>
    </section>
    """


def _format_optional_usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    return _format_usd(value)


def quality_body(summary: QualityRunSummary, *, csrf_token: str) -> str:
    metric_cards = "\n".join(
        (
            _quality_metric(
                "Avg METEOR",
                _format_optional_score(summary.average_meteor),
            ),
            _quality_metric("Avg chrF", _format_optional_score(summary.average_chrf)),
            _quality_metric("Scored", str(summary.scored_samples)),
            _quality_metric("Missing", str(summary.missing_samples)),
            _quality_metric("Extra", str(summary.extra_candidates)),
        )
    )
    empty_state = ""
    if not summary.found:
        empty_state = """
        <section class="panel">
          <h3>No quality run found</h3>
          <p>
            Put model QA outputs in var/quality-runs/latest.jsonl to compare
            candidates against the reference regression corpus.
          </p>
        </section>
        """
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Translation Quality</h3>
        <p>
          METEOR core and chrF scores for the latest offline QA run. Candidate,
          source, and reference text stay out of the admin UI.
        </p>
      </div>
      <div class="toolbar-actions">
        <code>{escape(summary.candidate_path)}</code>
        <form method="post" action="/admin/quality/run">
          <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
          {_action_button("Run quality check", "probe")}
        </form>
      </div>
    </section>
    <section class="metrics">{metric_cards}</section>
    {empty_state}
    {_quality_language_sections(summary.language_groups)}
    """


def _quality_metric(label: str, value: str) -> str:
    return f"""
    <article class="metric">
      <span>{escape(label)}</span>
      <strong>{escape(value)}</strong>
    </article>
    """


def _quality_language_sections(groups: tuple[QualityLanguageGroup, ...]) -> str:
    if not groups:
        return """
        <section class="panel table-panel">
          <h3>Reference samples</h3>
          <p class="empty-state">No reference samples found.</p>
        </section>
        """
    return "\n".join(_quality_language_section(group) for group in groups)


def _quality_language_section(group: QualityLanguageGroup) -> str:
    return f"""
    <section class="panel table-panel">
      <h3>{escape(group.label)}</h3>
      <div class="metric-grid">
        {_metric("Avg METEOR", _format_optional_score(group.average_meteor))}
        {_metric("Avg chrF", _format_optional_score(group.average_chrf))}
        {_metric("Scored", str(group.scored_samples))}
        {_metric("Missing", str(group.missing_samples))}
      </div>
      <table class="log-table">
        <thead>
          <tr>
            <th>Sample</th>
            <th>Category</th>
            <th>Direction</th>
            <th>METEOR</th>
            <th>chrF</th>
            <th>Status</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>{_quality_rows(group.rows)}</tbody>
      </table>
    </section>
    """


def _quality_rows(rows: tuple[QualitySampleScore, ...]) -> str:
    if not rows:
        return """
        <tr>
          <td colspan="7" class="empty-cell">No reference samples found.</td>
        </tr>
        """
    return "\n".join(_quality_row(row) for row in rows)


def _quality_row(row: QualitySampleScore) -> str:
    direction = f"{row.source_language} -> {row.target_language}"
    return f"""
    <tr>
      <td><code>{escape(row.sample_id)}</code></td>
      <td>{escape(row.category)}</td>
      <td>{escape(direction)}</td>
      <td>{escape(_format_optional_score(row.meteor))}</td>
      <td>{escape(_format_optional_score(row.chrf))}</td>
      <td><span class="status">{escape(row.status)}</span></td>
      <td>{escape(row.error or "")}</td>
    </tr>
    """


def _format_optional_score(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def _cost_run_rows(runs: tuple[CostRunSummary, ...]) -> str:
    if not runs:
        return """
        <tr>
          <td colspan="10" class="empty-cell">No cost data found.</td>
        </tr>
        """
    return "\n".join(_cost_run_row(run) for run in runs)


def _cost_run_row(run: CostRunSummary) -> str:
    started = run.started_at.isoformat(timespec="seconds") if run.started_at else "n/a"
    return f"""
    <tr>
      <td>{escape(started)}</td>
      <td><code>{escape(run.job_id)}</code></td>
      <td>{escape(run.order_id or "n/a")}</td>
      <td>{escape(run.user_id or "n/a")}</td>
      <td><strong>{escape(run.file_name)}</strong></td>
      <td>{run.prompt_tokens}</td>
      <td>{run.completion_tokens}</td>
      <td>{run.total_tokens}</td>
      <td>{escape(_format_usd(run.estimated_cost_usd))}</td>
      <td>
        {_action_link("Logs", _safe_cost_log_href(run.log_href), "view", compact=True)}
      </td>
    </tr>
    """


def _cost_user_rows(users: tuple[CostUserSummary, ...]) -> str:
    if not users:
        return """
        <tr>
          <td colspan="5" class="empty-cell">No user spend data found.</td>
        </tr>
        """
    return "\n".join(_cost_user_row(user) for user in users)


def _cost_user_row(user: CostUserSummary) -> str:
    return f"""
    <tr>
      <td>{escape(user.user_id)}</td>
      <td>{user.prompt_tokens}</td>
      <td>{user.completion_tokens}</td>
      <td>{user.total_tokens}</td>
      <td>{escape(_format_usd(user.estimated_cost_usd))}</td>
    </tr>
    """


def _safe_cost_log_href(href: str) -> str:
    if href == "/admin/logs" or (
        href.startswith("/admin/logs/")
        and href.endswith("/download")
        and "://" not in href
        and "\\" not in href
    ):
        return href
    return "/admin/logs"


def _format_usd(value: float) -> str:
    return f"${value:.4f}"


def operations_body(overview: OperationsOverview, *, csrf_token: str = "") -> str:
    metrics = (
        ("Queued", overview.job_counts_by_state.get("queued", 0)),
        ("Running", overview.job_counts_by_state.get("running", 0)),
        ("Failed", overview.job_counts_by_state.get("failed", 0)),
        ("Queue depth", overview.total_queue_depth),
        (
            "Oldest pending",
            _format_optional_seconds(overview.oldest_pending_age_seconds),
        ),
    )
    metric_cards = "\n".join(
        f"""
        <article class="metric">
          <span>{escape(label)}</span>
          <strong>{value}</strong>
        </article>
        """
        for label, value in metrics
    )
    return f"""
    <section class="metrics">{metric_cards}</section>
    <section class="panel table-panel">
      <h3>Jobs</h3>
      <table class="log-table operations-table">
        <thead>
          <tr>
            <th>State</th>
            <th>Job id</th>
            <th>Order id</th>
            <th>Started/updated</th>
            <th>Fragments</th>
            <th>Total tokens</th>
            <th>Worker ids</th>
            <th>Error</th>
            <th>Logs</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>{_operation_job_rows(overview, csrf_token)}</tbody>
      </table>
    </section>
    <section class="panel">
      <h3>Workers</h3>
      <p>{len(overview.workers)} workers are currently visible to the admin console.</p>
    </section>
    """


def _operation_job_rows(overview: OperationsOverview, csrf_token: str) -> str:
    if not overview.jobs:
        return """
        <tr>
          <td colspan="10" class="empty-cell">No persistent jobs found.</td>
        </tr>
        """
    return "\n".join(_operation_job_row(job, csrf_token) for job in overview.jobs)


def _operation_job_row(job, csrf_token: str) -> str:
    fragments = f"{job.completed_units}/{job.total_units}"
    trace_href = trace_href_for_log_href(job.log_href)
    logs = (
        _action_link("Open trace", trace_href, "view", compact=True)
        if trace_href
        else '<span class="muted-text">No run</span>'
    )
    return f"""
    <tr>
      <td><span class="status">{escape(job.state)}</span></td>
      <td><code>{escape(job.id)}</code></td>
      <td>{escape(job.order_id or "n/a")}</td>
      <td>{_operation_job_times(job)}</td>
      <td>{escape(fragments)}</td>
      <td>{job.total_tokens}</td>
      <td>{escape(_format_workers(job.active_worker_ids))}</td>
      <td>{escape(job.error_excerpt or "")}</td>
      <td>{logs}</td>
      <td>{_job_actions(job, csrf_token)}</td>
    </tr>
    """


def _operation_job_times(job) -> str:
    primary = job.started_at or job.created_at
    primary_label = "Started" if job.started_at else "Created"
    return f"""
    <span>{escape(primary_label)} {escape(_format_datetime(primary))}</span>
    <span>Updated {escape(_format_datetime(job.updated_at))}</span>
    """


def _job_actions(job, csrf_token: str) -> str:
    actions = []
    if getattr(job, "pausable", False):
        actions.append(_job_action_form(job.id, "pause", "Pause", csrf_token))
    if job.cancellable:
        actions.append(_job_action_form(job.id, "cancel", "Cancel", csrf_token))
    if getattr(job, "deletable", False):
        actions.append(_job_action_form(job.id, "delete", "Delete", csrf_token))
    if actions:
        return '<div class="job-actions">' + "".join(actions) + "</div>"
    if job.retryable:
        return _action_button(
            "Retry unavailable",
            "change",
            button_type="button",
            disabled_reason="Retry is not available from this console view.",
            compact=True,
        )
    return _action_button(
        "No action",
        "view",
        button_type="button",
        disabled_reason="This job state has no admin action available.",
        compact=True,
    )


def _job_action_form(
    job_id: str,
    action: str,
    label: str,
    csrf_token: str,
) -> str:
    variant = "danger" if action in {"cancel", "delete"} else "change"
    return f"""
    <form method="post" action="/admin/operations/jobs/{escape(job_id)}/{action}">
      <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
      {_action_button(label, variant, compact=True)}
    </form>
    """


def _format_datetime(value) -> str:
    if value is None:
        return "n/a"
    return value.isoformat(timespec="seconds")


def _format_workers(worker_ids: tuple[str, ...]) -> str:
    if not worker_ids:
        return "n/a"
    return ", ".join(worker_ids)


def live_body(
    snapshot: LiveMonitorSnapshot,
    *,
    runtime_statuses: tuple[AIProviderRuntimeStatus, ...] = (),
    runtime_reload_states: tuple[AIProviderRuntimeReloadRequest, ...] = (),
    beta_safety: BetaSafetyCostSummary | None = None,
) -> str:
    metrics = (
        (
            "Active processing",
            snapshot.active_translations,
            "active_translations",
            "Jobs currently running or translating.",
        ),
        (
            "Queued translations",
            snapshot.queued_translations,
            "queued_translations",
            "Jobs waiting for worker or provider capacity.",
        ),
        (
            "Failed today",
            snapshot.failed_today,
            "failed_today",
            "Runs that ended with a failure today.",
        ),
        (
            "Tokens today",
            snapshot.tokens_today,
            "tokens_today",
            "Provider token usage from runs started today.",
        ),
        (
            "Tokens last hour",
            snapshot.tokens_last_hour,
            "tokens_last_hour",
            "Recent token usage for spotting spend spikes.",
        ),
        (
            "Server health",
            "pending" if not snapshot.server.available else "online",
            "server_health",
            "Local CPU, memory, disk, and uptime snapshot.",
        ),
        (
            "CPU",
            _percent(snapshot.server.cpu_percent),
            "server_cpu_percent",
            "Current server CPU load when metrics are available.",
        ),
        (
            "Memory",
            _percent(snapshot.server.memory_percent),
            "server_memory_percent",
            "Current server memory use when metrics are available.",
        ),
        (
            "Disk",
            _percent(snapshot.server.disk_percent),
            "server_disk_percent",
            "Current server disk use when metrics are available.",
        ),
        (
            "Uptime",
            _duration(snapshot.server.uptime_seconds),
            "server_uptime",
            "How long the local process host has been up.",
        ),
    )
    metric_cards = "\n".join(
        f"""
        <article class="metric live-metric">
          <span>{escape(label)}</span>
          <strong data-live-field="{escape(field)}">{value}</strong>
          <small>{escape(help_text)}</small>
        </article>
        """
        for label, value, field, help_text in metrics
    )
    runtime_cards = _live_runtime_cards(runtime_statuses, runtime_reload_states)
    beta_warning = _beta_safety_live_warning(beta_safety)
    monitor_link = _action_link(
        "Open monitor",
        "/admin/live",
        "view",
        target="_blank",
        rel="noreferrer",
    )
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Live Monitor</h3>
        <p>
          Keep this screen open to separate waiting work from active processing,
          provider capacity, token spend, failures, and server health.
        </p>
      </div>
      {monitor_link}
    </section>
    {beta_warning}
    <section class="metrics live-grid">{metric_cards}</section>
    <section class="panel live-guidance">
      <h3>What needs attention</h3>
      <ul>
        <li>Queue growing while active processing stays flat means work is waiting.</li>
        <li>
          Degraded channels, 429s, timeouts, or no provider slots point to
          provider capacity.
        </li>
        <li>
          Failures today above zero need a recent run check before inviting
          more beta users.
        </li>
        <li>
          High disk, memory, or CPU can explain slow workers even when the
          queue is small.
        </li>
      </ul>
    </section>
    <section class="panel">
      <h3>DeepSeek runtime</h3>
      <p>
        Runtime cards show existing provider status only: active request slots,
        key channels, adaptive limit, circuit state, and reload state.
      </p>
      <div class="metric-grid">{runtime_cards}</div>
    </section>
    <section class="panel table-panel">
      <h3>Recent runs</h3>
      <p>
        Recent rows are metadata-only. Progress counts translated fragments,
        ETA is an estimate, and Resources shows active provider requests,
        total request capacity, key channels, and available provider slots.
      </p>
      <table class="log-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Job</th>
            <th>File</th>
            <th>Direction</th>
            <th>Stage</th>
            <th>Progress</th>
            <th>ETA</th>
            <th>Resources</th>
            <th>Tokens</th>
          </tr>
        </thead>
        <tbody data-live-runs>{_live_run_rows(snapshot.recent_runs)}</tbody>
      </table>
    </section>
    <script>
      const formatNumber = (value) => String(value ?? 0);
      const setField = (name, value) => {{
        const node = document.querySelector(`[data-live-field="${{name}}"]`);
        if (node) node.textContent = formatNumber(value);
      }};
      const escapeHtml = (value) => String(value ?? "").replace(
        /[&<>"']/g,
        (char) => ({{
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;"
        }})[char]
      );
      const runRows = (runs) => (runs || []).map((run) => `
        <tr>
          <td><span class="status">${{escapeHtml(run.status || "unknown")}}</span></td>
          <td><code>${{escapeHtml(run.job_id || "unknown")}}</code></td>
          <td><strong>${{escapeHtml(run.file_name || "unknown")}}</strong></td>
          <td>
            ${{escapeHtml(run.source_language || "?")}}
            ->
            ${{escapeHtml(run.target_language || "?")}}
          </td>
          <td>${{escapeHtml(stageLabel(run))}}</td>
          <td>${{progressCell(run)}}</td>
          <td>${{escapeHtml(etaLabel(run))}}</td>
          <td>${{escapeHtml(resourceLabel(run.resource_usage))}}</td>
          <td>${{escapeHtml(run.total_tokens || 0)}}</td>
        </tr>
      `).join("");
      const stageLabel = (run) => run.current_stage || run.status || "unknown";
      const progressLabel = (run) => {{
        const done = run.fragment_count ?? 0;
        const total = run.total_fragment_count ?? 0;
        const percent = run.progress_percent;
        if (total > 0 && percent != null) return `${{done}}/${{total}} · ${{percent}}%`;
        if (total > 0) return `${{done}}/${{total}}`;
        return `${{done}}/?`;
      }};
      const progressPercent = (run) => Math.max(
        0,
        Math.min(100, Number(run.progress_percent ?? 0))
      );
      const progressCell = (run) => `
        <div class="progress-mini">
          <span>${{escapeHtml(progressLabel(run))}}</span>
          <b><i style="width: ${{progressPercent(run)}}%"></i></b>
        </div>
      `;
      const etaLabel = (run) => {{
        if (run.eta_seconds == null) return "n/a";
        if (run.eta_seconds <= 0) return "0m";
        const minutes = Math.ceil(run.eta_seconds / 60);
        if (minutes >= 60) return `${{Math.floor(minutes / 60)}}h ${{minutes % 60}}m`;
        return `${{minutes}}m`;
      }};
      const resourceLabel = (resources) => {{
        if (!resources || !resources.provider) return "n/a";
        const active = resources.active_requests ?? 0;
        const capacity = resources.parallel_capacity ?? 0;
        const channels = resources.active_key_channels ?? 0;
        const slots = resources.available_provider_slots;
        const slotText = slots == null ? "n/a" : slots;
        return `${{active}}/${{capacity}} req · ${{channels}} keys · `
          + `${{slotText}} slots`;
      }};
      async function refreshLiveMonitor() {{
        const response = await fetch("/admin/api/live", {{ cache: "no-store" }});
        if (!response.ok) return;
        const data = await response.json();
        setField("active_translations", data.active_translations);
        setField("queued_translations", data.queued_translations);
        setField("failed_today", data.failed_today);
        setField("tokens_today", data.tokens_today);
        setField("tokens_last_hour", data.tokens_last_hour);
        setField("server_health", data.server?.available ? "online" : "pending");
        setField(
          "server_cpu_percent",
          data.server?.cpu_percent == null ? "n/a" : `${{data.server.cpu_percent}}%`
        );
        setField(
          "server_memory_percent",
          data.server?.memory_percent == null
            ? "n/a"
            : `${{data.server.memory_percent}}%`
        );
        setField(
          "server_disk_percent",
          data.server?.disk_percent == null ? "n/a" : `${{data.server.disk_percent}}%`
        );
        setField(
          "server_uptime",
          data.server?.uptime_seconds == null
            ? "n/a"
            : `${{Math.floor(data.server.uptime_seconds / 3600)}}h`
        );
        const body = document.querySelector("[data-live-runs]");
        if (body) body.innerHTML = runRows(data.recent_runs);
      }}
      setInterval(refreshLiveMonitor, 3000);
    </script>
    """


def _beta_safety_live_warning(summary: BetaSafetyCostSummary | None) -> str:
    if summary is None or not summary.warning:
        return ""
    daily_remaining = escape(
        _format_optional_usd(summary.global_daily_remaining_usd)
    )
    monthly_remaining = escape(
        _format_optional_usd(summary.global_monthly_remaining_usd)
    )
    return f"""
    <section class="panel">
      <h3>{escape(_beta_safety_warning_text(summary))}</h3>
      <p>
        Daily remaining {daily_remaining} and monthly remaining
        {monthly_remaining}.
      </p>
    </section>
    """


def _beta_safety_warning_text(summary: BetaSafetyCostSummary) -> str:
    if summary.translations_paused:
        return "Beta translations are paused"
    if summary.warning_reason == "global_monthly_cap":
        return "Beta safety monthly budget is near its cap"
    return "Beta safety daily budget is near its cap"


def _live_runtime_cards(
    runtime_statuses: tuple[AIProviderRuntimeStatus, ...],
    runtime_reload_states: tuple[AIProviderRuntimeReloadRequest, ...],
) -> str:
    status = next(
        (status for status in runtime_statuses if status.provider_id == "deepseek"),
        None,
    )
    reload_state = next(
        (state for state in runtime_reload_states if state.provider_id == "deepseek"),
        None,
    )
    source = "not reporting" if status is None else status.source
    runtime_state = "not reporting" if status is None else status.status
    freshness = "not reporting" if status is None else _runtime_freshness(status)
    channels = (
        "none"
        if status is None or not status.active_channels
        else ", ".join(
            _safe_runtime_text(channel.label) for channel in status.active_channels
        )
    )
    degraded_channels = 0
    rate_limit_count = 0
    timeout_count = 0
    unsafe_model_output_count = 0
    adaptive_limit = "n/a"
    provider_circuit = "not reporting"
    available_provider_slots = "n/a"
    if status is not None:
        degraded_channels = sum(
            1
            for channel in status.active_channels
            if channel.health.lower() in {"cooling_down", "degraded"}
        )
        rate_limit_count = sum(
            channel.total_rate_limit_failures for channel in status.active_channels
        )
        timeout_count = sum(
            channel.total_timeout_failures for channel in status.active_channels
        )
        unsafe_model_output_count = sum(
            channel.total_unsafe_model_output_failures
            for channel in status.active_channels
        )
        adaptive_limit = (
            f"{status.provider_state.current_limit}/"
            f"{status.provider_state.max_capacity}"
        )
        provider_circuit = _safe_runtime_text(status.provider_state.circuit_state)
        available_provider_slots = str(status.provider_state.available_slots)
    reload_text = (
        "Reload pending"
        if reload_state is not None and reload_state.pending
        else "No reload pending"
    )
    cards = (
        ("Source", source),
        ("Status", runtime_state),
        ("Freshness", freshness),
        ("Channels", channels),
        ("Reload", reload_text),
        ("Degraded channels", str(degraded_channels)),
        ("429 count", str(rate_limit_count)),
        ("Timeout count", str(timeout_count)),
        ("Unsafe model outputs", str(unsafe_model_output_count)),
        ("Adaptive limit", adaptive_limit),
        ("Provider circuit", provider_circuit),
        ("Available provider slots", available_provider_slots),
    )
    return "\n".join(
        f"""
        <div class="metric-card">
          <span>{escape(label)}</span>
          <strong>{escape(value)}</strong>
        </div>
        """
        for label, value in cards
    )


def _live_run_rows(runs: tuple[TranslationRunSummary, ...]) -> str:
    if not runs:
        return """
        <tr>
          <td colspan="9" class="empty-cell">No recent runs yet.</td>
        </tr>
        """
    return "\n".join(_live_run_row(run) for run in runs)


def _live_run_row(run: TranslationRunSummary) -> str:
    direction = f"{run.source_language} -> {run.target_language}"
    return f"""
    <tr>
      <td><span class="status">{escape(run.status)}</span></td>
      <td><code>{escape(run.job_id)}</code></td>
      <td><strong>{escape(run.file_name)}</strong></td>
      <td>{escape(direction)}</td>
      <td>{escape(_stage_label(run))}</td>
      <td>{_progress_mini(run)}</td>
      <td>{escape(_eta_label(run))}</td>
      <td>{escape(_resource_usage_label(run.resource_usage))}</td>
      <td>{run.total_tokens}</td>
    </tr>
    """


def _stage_label(run: TranslationRunSummary) -> str:
    return run.current_stage or run.status


def _progress_mini(run: TranslationRunSummary) -> str:
    return f"""
    <div class="progress-mini">
      <span>{escape(_progress_label(run))}</span>
      <b><i style="width: {_progress_width(run)}%"></i></b>
    </div>
    """


def _progress_bar(run: TranslationRunSummary) -> str:
    return f"""
    <div class="progress-bar" data-detail-progress-bar="progress">
      <i style="width: {_progress_width(run)}%"></i>
    </div>
    """


def _progress_width(run: TranslationRunSummary) -> str:
    if run.progress_percent is None:
        return "0"
    return str(max(0.0, min(100.0, run.progress_percent)))


def _progress_label(run: TranslationRunSummary) -> str:
    if run.total_fragment_count > 0 and run.progress_percent is not None:
        return (
            f"{run.fragment_count}/{run.total_fragment_count} · "
            f"{run.progress_percent}%"
        )
    if run.total_fragment_count > 0:
        return f"{run.fragment_count}/{run.total_fragment_count}"
    return f"{run.fragment_count}/?"


def _eta_label(run: TranslationRunSummary) -> str:
    if run.eta_seconds is None:
        return "n/a"
    return _duration(run.eta_seconds)


def _resource_usage_label(resources: dict) -> str:
    if not resources or not resources.get("provider"):
        return "n/a"
    slots = resources.get("available_provider_slots")
    slot_text = "n/a" if slots is None else str(slots)
    return (
        f"{resources.get('active_requests', 0)}/"
        f"{resources.get('parallel_capacity', 0)} req · "
        f"{resources.get('active_key_channels', 0)} keys · "
        f"{slot_text} slots"
    )


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value}%"


def _duration(value: float | None) -> str:
    if value is None:
        return "n/a"
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def logs_body(
    logs: tuple[TranslationRunSummary, ...],
    *,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    title: str = "Translation Logs",
    form_action: str = "/admin/logs",
) -> str:
    rows = "\n".join(_log_row(row) for row in logs)
    if not rows:
        rows = """
        <tr>
          <td colspan="9" class="empty-cell">No translation logs found.</td>
        </tr>
        """
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>{escape(title)}</h3>
        <p>
          Review translation runs by date, state, file, language direction,
          token usage, and safe error metadata.
        </p>
      </div>
    </section>
    <section class="panel">
      <form class="filter-form" method="get" action="{escape(form_action)}">
        <label>
          <span>Status</span>
          <select name="status">
            {_status_option("all", status, "All")}
            {_status_option("running", status, "Running")}
            {_status_option("ready", status, "Ready")}
            {_status_option("failed", status, "Failed")}
            {_status_option("cancelled", status, "Cancelled")}
            {_status_option("partial", status, "Partial")}
          </select>
        </label>
        <label>
          <span>From</span>
          <input name="date_from" type="date" value="{escape(date_from or "")}">
        </label>
        <label>
          <span>To</span>
          <input name="date_to" type="date" value="{escape(date_to or "")}">
        </label>
        {_action_button("Apply filters", "refresh")}
      </form>
    </section>
    <section class="panel table-panel">
      <table class="log-table">
        <thead>
          <tr>
            <th>Started</th>
            <th>Status</th>
            <th>Job</th>
            <th>File</th>
            <th>Direction</th>
            <th>Fragments</th>
            <th>Tokens</th>
            <th>Error</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """


def log_detail_body(details: TranslationRunDetails) -> str:
    summary = details.summary
    run_id = Path(details.run_dir).name
    events = "\n".join(_run_event_row(event) for event in details.events)
    if not events:
        events = '<tr><td colspan="3" class="empty-cell">No events recorded.</td></tr>'
    fragments = "\n".join(_run_fragment_row(fragment) for fragment in details.fragments)
    if not fragments:
        fragments = """
        <tr>
          <td colspan="9" class="empty-cell">No fragment records found.</td>
        </tr>
        """
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Translation Details</h3>
        <p>
          {escape(summary.file_name)} · {escape(summary.source_language)}
          -> {escape(summary.target_language)} · {escape(summary.status)}
        </p>
      </div>
      <div class="toolbar-actions">
        {_action_link("Back to logs", "/admin/logs", "view")}
        {_action_link("Download archive", f"/admin/logs/{run_id}/download", "copy")}
      </div>
    </section>
    <section class="panel">
      <div class="metric-grid">
        {_metric("Job", summary.job_id, field="job_id")}
        {_metric("Status", summary.status, field="status")}
        {_metric("Stage", _stage_label(summary), field="stage")}
        {_metric("Progress", _progress_label(summary), field="progress")}
        {_metric("ETA", _eta_label(summary), field="eta")}
        {_metric(
            "Started",
            _format_datetime(summary.started_at),
            field="started_at",
        )}
        {_metric(
            "Finished",
            _format_datetime(summary.finished_at),
            field="finished_at",
        )}
        {_metric("Fragments", str(summary.fragment_count), field="fragments")}
        {_metric("Tokens", str(summary.total_tokens), field="tokens")}
      </div>
      {_progress_bar(summary)}
    </section>
    <section class="panel detail-grid">
      <div>
        <h4>Inputs</h4>
        {_definition_table(details.metadata)}
      </div>
      <div>
        <h4>Totals</h4>
        {_definition_table(details.totals)}
      </div>
      <div>
        <h4>Translation Stack</h4>
        {_definition_table(_flatten_detail_dict(details.translation_stack))}
      </div>
      <div>
        <h4>Security</h4>
        {_definition_table(details.security)}
      </div>
    </section>
    <section class="panel table-panel">
      <h4>Fragments</h4>
      <table class="log-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Status</th>
            <th>Blocks</th>
            <th>Tier</th>
            <th>Chars</th>
            <th>Tokens</th>
            <th>Retries</th>
            <th>Elapsed</th>
            <th>Error / warnings</th>
          </tr>
        </thead>
        <tbody data-detail-fragments>{fragments}</tbody>
      </table>
    </section>
    <section class="panel table-panel">
      <h4>Events</h4>
      <table class="log-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Event</th>
            <th>Payload</th>
          </tr>
        </thead>
        <tbody data-detail-events>{events}</tbody>
      </table>
    </section>
    <script>
      (() => {{
        const runId = {json.dumps(run_id, ensure_ascii=False)};
        const escapeHtml = (value) => String(value ?? "").replace(
          /[&<>"']/g,
          (char) => ({{
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
          }})[char]
        );
        const setField = (name, value) => {{
          const node = document.querySelector(`[data-detail-field="${{name}}"]`);
          if (node) node.textContent = String(value ?? "n/a");
        }};
        const progressPercent = (summary) => Math.max(
          0,
          Math.min(100, Number(summary.progress_percent ?? 0))
        );
        const setProgressBar = (summary) => {{
          const bar = document.querySelector('[data-detail-progress-bar="progress"] i');
          if (bar) bar.style.width = `${{progressPercent(summary)}}%`;
        }};
        const durationLabel = (seconds) => {{
          if (seconds == null) return "n/a";
          if (seconds <= 0) return "0m";
          const minutes = Math.ceil(seconds / 60);
          if (minutes >= 60) return `${{Math.floor(minutes / 60)}}h ${{minutes % 60}}m`;
          return `${{minutes}}m`;
        }};
        const progressLabel = (summary) => {{
          const done = summary.fragment_count ?? 0;
          const total = summary.total_fragment_count ?? 0;
          const percent = summary.progress_percent;
          if (total > 0 && percent != null) {{
            return `${{done}}/${{total}} · ${{percent}}%`;
          }}
          if (total > 0) return `${{done}}/${{total}}`;
          return `${{done}}/?`;
        }};
        const eventRows = (events) => (events || []).map((event) => `
          <tr>
            <td>${{escapeHtml(event.timestamp || "n/a")}}</td>
            <td><strong>${{escapeHtml(event.event_type || "unknown")}}</strong></td>
            <td><code>${{escapeHtml(JSON.stringify(event.payload || {{}}))}}</code></td>
          </tr>
        `).join("");
        const fragmentRows = (fragments) => (fragments || []).map((fragment) => {{
          const blocks = (fragment.source_block_ids || []).join(", ") || "n/a";
          const chars = [
            fragment.source_text_chars || 0,
            fragment.translated_text_chars || 0
          ].join(" -> ");
          const tokens = [
            `${{fragment.prompt_tokens || 0}} +`,
            fragment.completion_tokens || 0,
            "=",
            fragment.total_tokens || 0
          ].join(" ");
          const notes = [
            fragment.error_message,
            ...(fragment.warnings || [])
          ].filter(Boolean).join(", ") || "n/a";
          return `
            <tr>
              <td>${{escapeHtml(fragment.sequence || 0)}}</td>
              <td>
                <span class="status">
                  ${{escapeHtml(fragment.status || "unknown")}}
                </span>
              </td>
              <td>${{escapeHtml(blocks)}}</td>
              <td>${{escapeHtml(fragment.prompt_tier || "n/a")}}</td>
              <td>${{escapeHtml(chars)}}</td>
              <td>${{escapeHtml(tokens)}}</td>
              <td>${{escapeHtml(fragment.retry_count || 0)}}</td>
              <td>
                ${{escapeHtml(Number(fragment.elapsed_seconds || 0).toFixed(2))}}s
              </td>
              <td>${{escapeHtml(notes)}}</td>
            </tr>
          `;
        }}).join("");
        async function refreshTranslationDetails() {{
          const detailsUrl = `/admin/api/logs/${{encodeURIComponent(runId)}}`;
          const response = await fetch(detailsUrl, {{
            cache: "no-store"
          }});
          if (!response.ok) return;
          const data = await response.json();
          const details = data.details || {{}};
          const summary = details.summary || {{}};
          setField("status", summary.status || "unknown");
          setField("stage", summary.current_stage || summary.status || "unknown");
          setField("progress", progressLabel(summary));
          setField("eta", durationLabel(summary.eta_seconds));
          setField("finished_at", summary.finished_at || "n/a");
          setField("fragments", summary.fragment_count ?? 0);
          setField("tokens", summary.total_tokens ?? 0);
          setProgressBar(summary);
          const fragmentBody = document.querySelector("[data-detail-fragments]");
          if (fragmentBody && details.fragments) {{
            fragmentBody.innerHTML = fragmentRows(details.fragments);
          }}
          const eventBody = document.querySelector("[data-detail-events]");
          if (eventBody && details.events) {{
            eventBody.innerHTML = eventRows(details.events);
          }}
        }}
        setInterval(refreshTranslationDetails, 3000);
      }})();
    </script>
    """


def translation_trace_body(trace: TranslationTrace) -> str:
    provider = _trace_provider_panel(trace.provider)
    timeline = _trace_timeline(trace.timeline)
    advanced_links = _trace_link_group(trace.advanced_links)
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Translation Failure Trace</h3>
        <p>
          {escape(trace.job_id)} · {escape(trace.status)}
          · {escape(trace.failure_category)}
        </p>
      </div>
      <div class="toolbar-actions">
        {_action_link(trace.next_action.label, trace.next_action.href, "view")}
      </div>
    </section>
    <section class="trace-layout">
      <div class="trace-main">
        <section class="panel">
          <div class="trace-summary-strip">
            <span class="status">{escape(trace.status)}</span>
            <span class="status">{escape(trace.failure_category)}</span>
            <strong>{escape(trace.safe_error_summary)}</strong>
          </div>
        </section>
        <section class="panel detail-grid">
          {_trace_fact_section("Incident", trace.summary_facts)}
          {_trace_fact_section("Document", trace.document_facts)}
          {_trace_fact_section("Choices", trace.choice_facts)}
          {_trace_fact_section("Job", trace.job_facts)}
        </section>
        {timeline}
        {provider}
      </div>
      <aside class="trace-rail">
        <section class="panel">
          <h4>What to check next</h4>
          <p>
            Follow one primary path first, then use the advanced links only
            if the trace does not explain the incident.
          </p>
          {_action_link(trace.next_action.label, trace.next_action.href, "view")}
        </section>
        <section class="panel">
          <h4>Evidence</h4>
          <p>
            Safe metadata only. Evidence packet copy/download is tracked in
            issue #146.
          </p>
        </section>
        <section class="panel">
          <h4>Advanced</h4>
          {advanced_links}
        </section>
      </aside>
    </section>
    """


def activity_body(
    events: tuple[UserActivityEvent, ...],
    *,
    actor_id: str | None = None,
    channel_user_id: str | None = None,
    surface: str | None = None,
    event_type: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    job_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    rows = "\n".join(_activity_row(event) for event in events)
    if not rows:
        rows = """
        <tr>
          <td colspan="8" class="empty-cell">No activity events found.</td>
        </tr>
        """
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Activity</h3>
        <p>
          User commands, buttons, settings, translation lifecycle events, and
          security outcomes collected automatically by the service.
        </p>
      </div>
    </section>
    <section class="panel">
      <form class="filter-form" method="get" action="/admin/activity">
        {_filter_input("actor_id", "User", actor_id)}
        {_filter_input("channel_user_id", "Channel user", channel_user_id)}
        {_filter_input("surface", "Surface", surface)}
        {_filter_input("event_type", "Event", event_type)}
        {_filter_input("action", "Action", action)}
        {_filter_input("outcome", "Outcome", outcome)}
        {_filter_input("job_id", "Job", job_id)}
        <label>
          <span>From</span>
          <input name="date_from" type="date" value="{escape(date_from or "")}">
        </label>
        <label>
          <span>To</span>
          <input name="date_to" type="date" value="{escape(date_to or "")}">
        </label>
        {_action_button("Apply filters", "refresh")}
      </form>
    </section>
    <section class="panel table-panel">
      <table class="log-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>User</th>
            <th>Surface</th>
            <th>Event</th>
            <th>Target</th>
            <th>Outcome</th>
            <th>Job</th>
            <th>Metadata</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """


def users_body(users: tuple[UserProfile, ...]) -> str:
    rows = "\n".join(_user_row(user) for user in users)
    if not rows:
        rows = """
        <tr>
          <td colspan="7" class="empty-cell">No users recorded yet.</td>
        </tr>
        """
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Users</h3>
        <p>
          Per-user settings and security state inferred from activity events.
        </p>
      </div>
    </section>
    <section class="panel table-panel">
      <table class="log-table">
        <thead>
          <tr>
            <th>User</th>
            <th>Channel</th>
            <th>Interface</th>
            <th>Last target</th>
            <th>Preview</th>
            <th>Security</th>
            <th>Last seen</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """


def user_detail_body(
    user: UserProfile | None,
    events: tuple[UserActivityEvent, ...],
) -> str:
    if user is None:
        return section_body(
            "User not found",
            "No activity profile exists for this user.",
        )
    rows = "".join(_activity_row(event, include_user=False) for event in events)
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>{escape(user.user_id)}</h3>
        <p>
          {escape(user.channel)} user {escape(user.channel_user_id)} ·
          security {escape(user.security_state)}
        </p>
      </div>
    </section>
    <section class="panel">
      <div class="metric-grid">
        {_metric("Interface", user.interface_language or "n/a")}
        {_metric("Last target", user.last_target_language or "n/a")}
        {_metric("Progress preview", _bool_label(user.progress_preview_enabled))}
        {_metric("First seen", user.first_seen_at.isoformat(timespec="seconds"))}
      </div>
    </section>
    <section class="panel table-panel">
      <table class="log-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Surface</th>
            <th>Event</th>
            <th>Target</th>
            <th>Outcome</th>
            <th>Job</th>
            <th>Metadata</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """


def security_events_body(events: tuple[UserActivityEvent, ...]) -> str:
    rows = "\n".join(_activity_row(event) for event in events)
    if not rows:
        rows = """
        <tr>
          <td colspan="8" class="empty-cell">No security events recorded yet.</td>
        </tr>
        """
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Security</h3>
        <p>
          Blocked actions, cooldowns, policy trips, and suspicious service
          behavior from the shared activity log.
        </p>
      </div>
    </section>
    <section class="panel table-panel">
      <table class="log-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>User</th>
            <th>Surface</th>
            <th>Event</th>
            <th>Target</th>
            <th>Outcome</th>
            <th>Job</th>
            <th>Metadata</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """


def upload_safety_body(
    summary: UploadSafetySummary,
    records: tuple[UploadSafetyAdminRecord, ...],
    *,
    filters: UploadSafetyFilters,
) -> str:
    rows = "\n".join(_upload_safety_row(record) for record in records)
    if not rows:
        rows = """
        <tr>
          <td colspan="10" class="empty-cell">No upload safety records found.</td>
        </tr>
        """
    top_reason_codes = ", ".join(
        f"{reason}: {count}" for reason, count in summary.top_reason_codes
    )
    if not top_reason_codes:
        top_reason_codes = "n/a"
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Upload Safety</h3>
        <p>
          Metadata-only scanner and upload-safety ledger status for accepted,
          blocked, and failed-closed uploads.
        </p>
      </div>
    </section>
    <section class="panel">
      <div class="metric-grid">
        {_metric("Scanner health", summary.scanner_health)}
        {_metric("Signature DB age", _format_optional_seconds(
            summary.signature_database_age_seconds,
        ))}
        {_metric("Scanned", str(summary.scanned_count))}
        {_metric("Accepted", str(summary.accepted_count))}
        {_metric("Blocked", str(summary.blocked_count))}
        {_metric("Failed closed", str(summary.failed_closed_count))}
        {_metric("Access violations", str(summary.access_violation_count))}
        {_metric("Top reasons", top_reason_codes)}
      </div>
    </section>
    <section class="panel">
      <form class="filter-form" method="get" action="/admin/upload-safety">
        {_filter_input("final_action", "Final action", filters.final_action)}
        {_filter_input("av_verdict", "AV verdict", filters.av_verdict)}
        {_filter_input(
            "container_verdict",
            "Container verdict",
            filters.container_verdict,
        )}
        {_filter_input("reason_code", "Reason", filters.reason_code)}
        {_filter_input("channel_user_id", "Channel user", filters.channel_user_id)}
        {_filter_input("declared_format", "Format", filters.declared_format)}
        <label>
          <span>From</span>
          <input name="date_from" type="date"
            value="{escape(filters.date_from or "")}">
        </label>
        <label>
          <span>To</span>
          <input name="date_to" type="date"
            value="{escape(filters.date_to or "")}">
        </label>
        {_action_button("Apply filters", "refresh")}
      </form>
    </section>
    <section class="panel table-panel">
      <table class="log-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>User</th>
            <th>File / Job</th>
            <th>Format</th>
            <th>Size</th>
            <th>AV</th>
            <th>Container</th>
            <th>Reason</th>
            <th>Action</th>
            <th>Access</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """


def upload_safety_detail_body(record: UploadSafetyAdminRecord | None) -> str:
    if record is None:
        return section_body(
            "Upload safety record not found",
            "No upload safety metadata exists for this id.",
        )
    timeline = "\n".join(
        _upload_safety_timeline_row(event) for event in record.timeline
    )
    if not timeline:
        timeline = """
        <tr>
          <td colspan="3" class="empty-cell">No timeline events found.</td>
        </tr>
        """
    safe_filename = record.sanitized_original_filename or "n/a"
    details = {
        "upload_id": record.upload_id,
        "channel_user_id": record.channel_user_id,
        "declared_format": record.declared_format,
        "detected_format": record.detected_format,
        "size_bytes": record.size_bytes,
        "sanitized_filename": safe_filename,
        "short_hash": record.short_hash or "n/a",
        "scanner": record.scanner_name or "n/a",
        "scanner_version": record.scanner_version or "n/a",
        "signature_database_version": record.signature_database_version or "n/a",
        "av_verdict": record.av_verdict,
        "container_verdict": record.container_verdict,
        "reason_code": record.reason_code,
        "final_action": record.final_action,
        "parser_access_granted": _bool_label(record.parser_access_granted),
        "worker_access_granted": _bool_label(record.worker_access_granted),
        "job_id": record.job_id or "n/a",
    }
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>{escape(record.upload_id)}</h3>
        <p>
          Metadata-only upload safety detail. Raw quarantine files, object
          paths, scanner output, and override actions are not exposed.
        </p>
      </div>
    </section>
    <section class="panel">
      {_definition_table(details)}
    </section>
    <section class="panel table-panel">
      <h3>Timeline</h3>
      <table class="log-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>State</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>{timeline}</tbody>
      </table>
    </section>
    """


def _upload_safety_row(record: UploadSafetyAdminRecord) -> str:
    access = "parser" if record.parser_access_granted else ""
    if record.worker_access_granted:
        access = ", ".join(part for part in (access, "worker") if part)
    if not access:
        access = "none"
    file_or_job = record.sanitized_original_filename or "n/a"
    if record.job_id:
        file_or_job = f"{file_or_job} / {record.job_id}"
    return f"""
      <tr>
        <td><a href="/admin/upload-safety/{escape(record.upload_id)}">
          {escape(_format_datetime(record.created_at))}
        </a></td>
        <td>{escape(record.channel_user_id)}</td>
        <td>{escape(file_or_job)}</td>
        <td>{escape(record.declared_format)} / {escape(record.detected_format)}</td>
        <td>{escape(str(record.size_bytes))}</td>
        <td>{escape(record.av_verdict)}</td>
        <td>{escape(record.container_verdict)}</td>
        <td>{escape(record.reason_code)}</td>
        <td>{escape(record.final_action)}</td>
        <td>{escape(access)}</td>
      </tr>
    """


def _upload_safety_timeline_row(event: object) -> str:
    timestamp = getattr(event, "timestamp", None)
    state = getattr(event, "state", "unknown")
    reason = getattr(event, "reason_code", None) or "n/a"
    return f"""
      <tr>
        <td>{escape(_format_datetime(timestamp))}</td>
        <td>{escape(state)}</td>
        <td>{escape(reason)}</td>
      </tr>
    """


def _filter_input(name: str, label: str, value: str | None) -> str:
    return f"""
    <label>
      <span>{escape(label)}</span>
      <input name="{escape(name)}" type="text" value="{escape(value or "")}">
    </label>
    """


def _activity_row(event: UserActivityEvent, *, include_user: bool = True) -> str:
    created = event.created_at.isoformat(timespec="seconds")
    target = " / ".join(
        part for part in (event.target_type or "", event.target_id or "") if part
    )
    metadata = ", ".join(
        f"{key}: {value}" for key, value in sorted(event.metadata.items())[:4]
    )
    user_cell = f"<td>{_user_link(event.actor_id)}</td>" if include_user else ""
    return f"""
    <tr>
      <td>{escape(created)}</td>
      {user_cell}
      <td>{escape(event.surface)}</td>
      <td>
        <strong>{escape(event.event_type)}</strong>
        <span>{escape(event.action)}</span>
      </td>
      <td>{escape(target or "n/a")}</td>
      <td><span class="status">{escape(event.outcome)}</span></td>
      <td><code>{escape(event.job_id or "")}</code></td>
      <td>{escape(metadata)}</td>
    </tr>
    """


def _user_row(user: UserProfile) -> str:
    return f"""
    <tr>
      <td>{_user_link(user.user_id)}</td>
      <td>{escape(user.channel)} / {escape(user.channel_user_id)}</td>
      <td>{escape(user.interface_language or "n/a")}</td>
      <td>{escape(user.last_target_language or "n/a")}</td>
      <td>{escape(_bool_label(user.progress_preview_enabled))}</td>
      <td><span class="status">{escape(user.security_state)}</span></td>
      <td>{escape(user.last_seen_at.isoformat(timespec="seconds"))}</td>
    </tr>
    """


def _user_link(user_id: str | None) -> str:
    if not user_id:
        return "n/a"
    return f'<a href="/admin/users/{escape(user_id)}">{escape(user_id)}</a>'


def _bool_label(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "enabled" if value else "disabled"


def _metric(label: str, value: str, *, field: str | None = None) -> str:
    field_attribute = (
        f' data-detail-field="{escape(field)}"'
        if field is not None
        else ""
    )
    return f"""
    <div class="metric-card">
      <span>{escape(label)}</span>
      <strong{field_attribute}>{escape(value)}</strong>
    </div>
    """


def _trace_fact_section(
    title: str,
    facts: tuple[TranslationTraceFact, ...],
) -> str:
    return f"""
      <div>
        <h4>{escape(title)}</h4>
        {_definition_table({fact.label: fact.value for fact in facts})}
      </div>
    """


def _trace_timeline(items: tuple[TranslationTraceTimelineItem, ...]) -> str:
    if not items:
        rows = """
        <tr>
          <td colspan="3" class="empty-cell">No safe trace timeline found.</td>
        </tr>
        """
    else:
        rows = "\n".join(_trace_timeline_row(item) for item in items)
    return f"""
    <section class="panel table-panel">
      <h4>Timeline</h4>
      <table class="log-table trace-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Event</th>
            <th>Safe detail</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """


def _trace_timeline_row(item: TranslationTraceTimelineItem) -> str:
    return f"""
    <tr>
      <td>{escape(_format_datetime(item.timestamp))}</td>
      <td><strong>{escape(item.label)}</strong></td>
      <td>{escape(item.detail)}</td>
    </tr>
    """


def _trace_provider_panel(provider: TranslationTraceProviderSignal | None) -> str:
    if provider is None:
        facts = (
            TranslationTraceFact("Provider", "Unknown"),
            TranslationTraceFact("Runtime status", "Unknown"),
            TranslationTraceFact("Failure categories", "Unknown"),
        )
    else:
        facts = (
            TranslationTraceFact("Provider", provider.provider_id),
            TranslationTraceFact("Runtime status", provider.status),
            TranslationTraceFact("Active channels", str(provider.active_channels)),
            TranslationTraceFact("Degraded channels", str(provider.degraded_channels)),
            TranslationTraceFact(
                "Failure categories",
                ", ".join(provider.safe_failure_categories),
            ),
            TranslationTraceFact("Balance status", provider.balance_status),
        )
    return f"""
    <section class="panel">
      <h4>Provider</h4>
      {_definition_table({fact.label: fact.value for fact in facts})}
    </section>
    """


def _trace_link_group(links: tuple[TranslationTraceLink, ...]) -> str:
    return "\n".join(
        _action_link(link.label, link.href, "view", extra_class="trace-link")
        for link in links
    )


def _log_row(row: TranslationRunSummary) -> str:
    started = row.started_at.isoformat(timespec="seconds") if row.started_at else "n/a"
    direction = f"{row.source_language} -> {row.target_language}"
    error = row.error_message or ""
    run_id = Path(row.run_dir).name
    trace_link = _action_link(
        "Open trace",
        trace_href_for_run_id(run_id),
        "view",
        compact=True,
    )
    details_link = _action_link(
        "Details",
        f"/admin/logs/{run_id}",
        "view",
        compact=True,
    )
    return f"""
    <tr>
      <td>{escape(started)}</td>
      <td><span class="status">{escape(row.status)}</span></td>
      <td><code>{escape(row.job_id)}</code></td>
      <td>
        <strong>{escape(row.file_name)}</strong>
        <span>{escape(row.document_kind)}</span>
      </td>
      <td>{escape(direction)}</td>
      <td>{row.fragment_count}</td>
      <td>{row.total_tokens}</td>
      <td>{escape(error)}</td>
      <td>
        {trace_link}
        {details_link}
      </td>
    </tr>
    """


def _run_fragment_row(fragment: TranslationRunFragmentDetail) -> str:
    blocks = ", ".join(fragment.source_block_ids) or "n/a"
    chars = f"{fragment.source_text_chars} -> {fragment.translated_text_chars}"
    tokens = (
        f"{fragment.prompt_tokens} + {fragment.completion_tokens} = "
        f"{fragment.total_tokens}"
    )
    notes = "; ".join(
        item
        for item in (
            fragment.error_message or "",
            ", ".join(fragment.warnings),
        )
        if item
    )
    return f"""
    <tr>
      <td>{fragment.sequence}</td>
      <td><span class="status">{escape(fragment.status)}</span></td>
      <td>{escape(blocks)}</td>
      <td>{escape(fragment.prompt_tier or "n/a")}</td>
      <td>{escape(chars)}</td>
      <td>{escape(tokens)}</td>
      <td>{fragment.retry_count}</td>
      <td>{fragment.elapsed_seconds:.2f}s</td>
      <td>{escape(notes or "n/a")}</td>
    </tr>
    """


def _run_event_row(event: TranslationRunEvent) -> str:
    return f"""
    <tr>
      <td>{escape(_format_datetime(event.timestamp))}</td>
      <td><strong>{escape(event.event_type)}</strong></td>
      <td><code>{escape(_compact_json(event.payload))}</code></td>
    </tr>
    """


def _definition_table(values: dict) -> str:
    rows = "\n".join(
        _definition_row(key, value)
        for key, value in sorted(values.items())
        if value not in (None, "", {}, ())
    )
    if not rows:
        rows = '<tr><td colspan="2" class="empty-cell">No data recorded.</td></tr>'
    return f'<table class="definition-table"><tbody>{rows}</tbody></table>'


def _definition_row(key: object, value: object) -> str:
    return f"""
        <tr>
          <th>{escape(str(key))}</th>
          <td>{_detail_value_html(value)}</td>
        </tr>
        """


def _flatten_detail_dict(values: dict, *, prefix: str = "") -> dict[str, object]:
    flat: dict[str, object] = {}
    for key, value in values.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten_detail_dict(value, prefix=full_key))
        else:
            flat[full_key] = value
    return flat


def _detail_value(value: object) -> str:
    if isinstance(value, (dict, list, tuple)):
        return _compact_json(value)
    return str(value)


def _detail_value_html(value: object) -> str:
    structured = _structured_detail_value(value)
    if structured is not None:
        return f'<pre class="detail-json">{escape(structured)}</pre>'
    return f'<span class="detail-value">{escape(str(value))}</span>'


def _structured_detail_value(value: object) -> str | None:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, (dict, list)):
        return None
    return json.dumps(
        parsed,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _format_datetime(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value is not None else "n/a"


def _status_option(value: str, selected: str | None, label: str) -> str:
    current = selected or "all"
    selected_attr = " selected" if current == value else ""
    return f'<option value="{escape(value)}"{selected_attr}>{escape(label)}</option>'


def _integration_card(
    summary: IntegrationSummary,
    *,
    csrf_token: str,
    connections: tuple[IntegrationConnectionSummary, ...],
) -> str:
    rows = "\n".join(
        _integration_connection_row(connection, csrf_token)
        for connection in connections
    )
    if not rows:
        rows = '<p class="empty-state">No connections configured yet.</p>'
    summary_secret_chips = _integration_summary_secret_chips(summary.secrets)
    fields = "\n".join(_connection_secret_field(secret) for secret in summary.secrets)
    action = f"/admin/integrations/{escape(summary.integration_id)}/connections"
    connection_count = f"{len(connections)} active connection"
    if len(connections) != 1:
        connection_count += "s"
    return f"""
    <details class="integration-card integration-folder">
      <summary>
        <span>
          <span class="eyebrow">
            {escape(summary.category.value.replace("_", " "))}
          </span>
          <strong>{escape(summary.label)}</strong>
        </span>
        <span class="status">{escape(connection_count)}</span>
      </summary>
      <p>{escape(summary.description)}</p>
      {summary_secret_chips}
      <div class="key-table">{rows}</div>
      <form class="secret-form connection-form" method="post" action="{action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label>
          <span>Connection name</span>
          <input name="label" type="text" placeholder="stable" required>
        </label>
        {fields}
        {_action_button("Add connection", "change")}
      </form>
    </details>
    """


def _integration_summary_secret_chips(
    secrets: tuple[IntegrationSecretSummary, ...],
) -> str:
    chips = " ".join(
        _connection_secret_chip(secret)
        for secret in secrets
        if secret.configured and secret.masked_value
    )
    if not chips:
        return ""
    return f'<div class="key-table">{chips}</div>'


def _integration_connection_row(
    connection: IntegrationConnectionSummary,
    csrf_token: str,
) -> str:
    secrets = " ".join(
        _connection_secret_chip(secret) for secret in connection.secret_values
    )
    remove_control = _integration_connection_remove_control(connection, csrf_token)
    return f"""
    <div class="key-row connection-row">
      <div>
        <strong>{escape(connection.label)}</strong>
        {secrets}
      </div>
      {remove_control}
    </div>
    """


def _integration_connection_remove_control(
    connection: IntegrationConnectionSummary,
    csrf_token: str,
) -> str:
    if connection.connection_id == "env-fallback":
        return '<span class="status">read-only</span>'
    remove_action = (
        f"/admin/integrations/{escape(connection.integration_id)}/connections/remove"
    )
    return f"""
      <form method="post" action="{remove_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <input
          type="hidden"
          name="connection_id"
          value="{escape(connection.connection_id)}"
        >
        {_action_button("Remove", "danger")}
      </form>
    """


def _connection_secret_chip(secret: IntegrationSecretSummary) -> str:
    value = secret.masked_value or "missing"
    return f"<code>{escape(secret.label)}: {escape(value)}</code>"


def _connection_secret_field(secret: IntegrationSecretSummary) -> str:
    label = secret.label
    secret_id = secret.secret_id
    return f"""
    <label>
      <span>{escape(label)}</span>
      <input
        name="secret:{escape(secret_id)}"
        type="password"
        autocomplete="off"
        placeholder="Paste secret value"
        required
      >
    </label>
    """


def _css() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --ink: #17202a;
  --muted: #667085;
  --line: #d8dee8;
  --accent: #256f68;
  --accent-strong: #174b46;
  --warn: #a33d2a;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--ink);
  background: var(--bg);
  font-family:
    Inter,
    ui-sans-serif,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
}
body > * { min-width: 0; }
.login-screen {
  display: grid;
  grid-template-columns: 1fr;
  place-items: center;
  padding: 24px;
}
.login-panel, .panel, .toolbar-panel, .integration-card, .metric {
  min-width: 0;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 12px 32px rgba(22, 32, 42, 0.08);
}
.login-panel {
  width: min(420px, 100%);
  padding: 28px;
}
.sidebar {
  min-width: 0;
  min-height: 100vh;
  padding: 24px 18px;
  background: #111827;
  color: #f9fafb;
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.sidebar h1, .workspace h2, .panel h3 { margin: 0; }
.sidebar-nav {
  display: grid;
  gap: 14px;
  min-width: 0;
  max-width: 100%;
}
.primary-nav,
.advanced-nav {
  min-width: 0;
}
.primary-nav,
.advanced-nav[open] {
  display: grid;
  gap: 6px;
}
.advanced-nav {
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
}
.nav-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #d1d5db;
  cursor: pointer;
  padding: 10px 12px;
  border-radius: 6px;
  font-weight: 700;
}
.nav-summary::-webkit-details-marker {
  display: none;
}
.nav-summary::after {
  content: "+";
  color: #9ca3af;
  font-weight: 800;
}
.advanced-nav[open] .nav-summary::after {
  content: "-";
}
.advanced-nav:not([open]) > a {
  display: none;
}
.sidebar a {
  display: block;
  color: #d1d5db;
  text-decoration: none;
  padding: 10px 12px;
  border-radius: 6px;
  white-space: nowrap;
}
.sidebar a.active,
.sidebar a:hover,
.nav-summary:hover,
.advanced-nav.active-group .nav-summary {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.12);
}
.workspace {
  min-width: 0;
  padding: 28px;
  display: grid;
  align-content: start;
  gap: 18px;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.panel, .toolbar-panel, .integration-card, .metric { padding: 20px; }
.panel p, .login-panel p { color: var(--muted); line-height: 1.55; }
.toolbar-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.toolbar-actions .secret-form {
  border-top: 0;
  padding-top: 0;
}
.secondary-action {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 9px 12px;
  color: var(--text);
  background: #ffffff;
  text-decoration: none;
  font-weight: 700;
}
.toolbar-panel h3, .toolbar-panel p, .integration-card h3, .integration-card p {
  margin: 0;
}
.grid-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
  gap: 16px;
  align-items: start;
}
.integration-card {
  display: grid;
  gap: 14px;
  min-width: 0;
}
.integration-folder {
  padding: 0;
  overflow: hidden;
}
.integration-folder summary {
  list-style: none;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: 18px 20px;
  cursor: pointer;
}
.integration-folder summary::-webkit-details-marker { display: none; }
.integration-folder summary::before {
  content: "+";
  color: var(--accent);
  font-weight: 800;
}
.integration-folder[open] summary::before { content: "-"; }
.integration-folder summary span:first-child {
  display: grid;
  gap: 4px;
  min-width: 0;
}
.integration-folder summary > .status {
  justify-self: end;
  max-width: 100%;
}
.integration-folder > p,
.integration-folder > .key-table,
.integration-folder > form {
  margin: 0 20px 18px;
}
.wide-card { grid-column: 1 / -1; }
.integration-card div {
  display: grid;
  gap: 6px;
}
.integration-card p {
  color: var(--muted);
  line-height: 1.5;
}
.secret-list {
  display: grid;
  gap: 12px;
}
.secret-form {
  border-top: 1px solid var(--line);
  padding-top: 12px;
  display: grid;
  gap: 12px;
}
.key-form {
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  align-items: end;
}
.key-table {
  display: grid;
  gap: 8px;
}
.key-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto auto;
  gap: 12px;
  align-items: center;
  border-top: 1px solid var(--line);
  padding-top: 10px;
  min-width: 0;
}
.compact-row {
  grid-template-columns: minmax(160px, 0.5fr) minmax(0, 1fr);
  align-items: start;
}
.key-row-readonly {
  background: #f8fafc;
  border-radius: 8px;
  padding: 10px;
}
.connection-row {
  grid-template-columns: minmax(0, 1fr) auto;
}
.connection-form {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  align-items: end;
}
.key-row form { display: block; }
.integration-card code {
  color: var(--muted);
  font-size: 0.85rem;
  overflow-wrap: anywhere;
  white-space: normal;
}
.helper-text,
.field-help {
  color: var(--muted);
  font-weight: 500;
  line-height: 1.45;
}
.field-help {
  display: block;
  font-size: 0.78rem;
}
.empty-state { color: var(--muted); }
.action-center {
  padding: 0;
  overflow: hidden;
}
.action-list {
  display: grid;
}
.action-list .empty-state {
  padding: 20px;
}
.action-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  padding: 16px 20px;
  color: inherit;
  border-bottom: 1px solid var(--line);
}
.action-item:last-child { border-bottom: 0; }
.action-item:hover {
  background: #fbfcfd;
}
.action-copy {
  display: grid;
  gap: 8px;
  min-width: 0;
}
.action-copy strong {
  overflow-wrap: anywhere;
}
.action-copy small,
.action-meta dd {
  color: var(--muted);
  line-height: 1.45;
}
.action-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}
.action-meta div {
  min-width: 0;
}
.action-meta dt {
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
}
.action-meta dd {
  margin: 2px 0 0;
  overflow-wrap: anywhere;
}
.action-next {
  align-self: center;
  justify-self: end;
  white-space: nowrap;
}
.action-blocked .status,
.action-action_needed .status {
  color: var(--warn);
  border-color: rgba(163, 61, 42, 0.35);
}
.action-investigate .status {
  color: #3730a3;
  border-color: rgba(55, 48, 163, 0.28);
}
.action-watch .status {
  color: #9a5b00;
  border-color: rgba(154, 91, 0, 0.3);
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.status {
  width: fit-content;
  max-width: 100%;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--accent-strong);
  font-size: 0.8rem;
  font-weight: 700;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.environment-badge {
  width: max-content;
  max-width: 100%;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 10px;
  background: #ffffff;
  color: var(--accent-strong);
  font-size: 0.78rem;
  font-weight: 800;
  text-transform: uppercase;
  overflow-wrap: anywhere;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 14px;
}
.metric {
  display: grid;
  gap: 8px;
}
.metric span { color: var(--muted); }
.metric strong { font-size: 1.8rem; }
.eyebrow {
  margin: 0 0 6px;
  color: var(--muted);
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}
.sidebar .eyebrow { color: #9ca3af; }
form { display: grid; gap: 14px; }
label { display: grid; gap: 6px; font-weight: 650; }
input {
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
  font: inherit;
}
select {
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
  background: #ffffff;
  font: inherit;
}
button {
  min-height: 42px;
  border: 0;
  border-radius: 6px;
  padding: 8px 14px;
  background: var(--accent);
  color: #ffffff;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}
button:hover { background: var(--accent-strong); }
button.secondary {
  width: 100%;
  color: #e5e7eb;
  background: rgba(255, 255, 255, 0.12);
}
button.danger {
  color: #ffffff;
  background: var(--warn);
}
.action-control {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: fit-content;
  max-width: 100%;
  min-height: 42px;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 8px 14px;
  color: var(--ink);
  background: #ffffff;
  text-align: center;
  text-decoration: none;
  font: inherit;
  font-weight: 750;
  line-height: 1.2;
  white-space: normal;
  overflow-wrap: anywhere;
  cursor: pointer;
}
.action-control:hover {
  text-decoration: none;
}
.action-control-compact {
  min-height: 34px;
  padding: 6px 10px;
  font-size: 0.88rem;
}
.action-control-view {
  border-color: var(--line);
  color: #174b46;
  background: #ffffff;
}
.action-control-view:hover {
  border-color: #9fb7b4;
  background: #f4faf9;
}
.action-control-copy {
  border-color: #c9c7ee;
  color: #3730a3;
  background: #f7f7ff;
}
.action-control-copy:hover {
  background: #efefff;
}
.action-control-refresh {
  border-color: #adc6ea;
  color: #1f4f86;
  background: #f2f7fd;
}
.action-control-refresh:hover {
  background: #e8f1fb;
}
.action-control-probe {
  border-color: #d2b8e8;
  color: #6d3a91;
  background: #fbf6ff;
}
.action-control-probe:hover {
  background: #f3e8ff;
}
.action-control-change {
  border-color: #256f68;
  color: #ffffff;
  background: var(--accent);
}
.action-control-change:hover {
  background: var(--accent-strong);
}
.action-control-danger {
  border-color: #a33d2a;
  color: #ffffff;
  background: var(--warn);
}
.action-control-danger:hover {
  background: #7f2f21;
}
.action-control[disabled],
.action-control[aria-disabled="true"] {
  border-color: #d8dee8;
  color: #667085;
  background: #eef1f5;
  cursor: not-allowed;
}
.action-control[disabled]:hover,
.action-control[aria-disabled="true"]:hover {
  border-color: #d8dee8;
  background: #eef1f5;
}
.action-control[disabled] {
  display: inline-grid;
  justify-items: center;
}
.action-disabled-reason {
  display: block;
  max-width: 220px;
  color: inherit;
  font-size: 0.72rem;
  font-weight: 600;
  line-height: 1.25;
}
.job-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.job-actions form {
  display: block;
}
.compact-action {
  min-height: 34px;
  padding: 6px 10px;
  font-size: 0.88rem;
}
.button-link {
  min-height: 42px;
  border-radius: 6px;
  padding: 10px 14px;
  background: var(--accent);
  color: #ffffff;
  text-decoration: none;
  font-weight: 700;
}
.button-link:hover { background: var(--accent-strong); }
.table-action {
  color: var(--accent-strong);
  font-weight: 700;
}
.filter-form {
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  align-items: end;
}
.table-panel {
  overflow-x: auto;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}
.metric-card {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfcfd;
}
.metric-card span {
  color: var(--muted);
  font-size: 0.78rem;
  text-transform: uppercase;
}
.metric-card strong {
  min-width: 0;
  overflow-wrap: anywhere;
}
.metric-card small,
.processing-summary p,
.provider-incident-state p,
.incident-state-row small {
  color: var(--muted);
  line-height: 1.45;
}
.processing-summary,
.provider-incident-state {
  display: grid;
  gap: 12px;
  margin: 14px 0;
}
.provider-incident-state {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfcfd;
}
.provider-incident-state h4,
.provider-incident-state p {
  margin: 0;
}
.incident-state-list {
  display: grid;
  border-top: 1px solid var(--line);
}
.incident-state-row {
  display: grid;
  grid-template-columns: minmax(150px, 0.7fr) minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.incident-state-row > span {
  color: var(--muted);
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
}
.incident-state-row div {
  display: grid;
  gap: 4px;
  min-width: 0;
}
.incident-state-row strong {
  overflow-wrap: anywhere;
}
.progress-bar {
  height: 10px;
  margin-top: 14px;
  overflow: hidden;
  border-radius: 999px;
  background: #e6ebf1;
}
.progress-bar i,
.progress-mini i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
}
.progress-mini {
  display: grid;
  gap: 6px;
  min-width: 120px;
}
.progress-mini span {
  color: var(--ink);
  font-size: 0.9rem;
}
.progress-mini b {
  display: block;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: #e6ebf1;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr));
  gap: 18px;
  align-items: start;
}
.detail-grid > div {
  min-width: 0;
}
.detail-grid h4,
.table-panel h4 {
  margin: 0 0 12px;
}
.trace-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 340px);
  gap: 18px;
  align-items: start;
}
.trace-main,
.trace-rail {
  display: grid;
  gap: 18px;
  min-width: 0;
}
.trace-rail {
  position: sticky;
  top: 18px;
}
.trace-summary-strip {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  min-width: 0;
}
.trace-summary-strip strong {
  min-width: 0;
  overflow-wrap: anywhere;
}
.trace-link {
  display: block;
  width: 100%;
  margin-top: 8px;
  overflow-wrap: anywhere;
}
.trace-table {
  min-width: 720px;
}
.definition-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.definition-table tbody {
  display: grid;
}
.definition-table tr {
  display: grid;
  grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.25fr);
  border-bottom: 1px solid var(--line);
}
.definition-table th,
.definition-table td {
  padding: 8px 0;
  text-align: left;
  vertical-align: top;
  min-width: 0;
  overflow-wrap: anywhere;
}
.definition-table th {
  color: var(--muted);
  font-size: 0.78rem;
  text-transform: uppercase;
  padding-right: 12px;
}
.detail-value {
  display: block;
}
.detail-json {
  margin: 0;
  max-width: 100%;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
  font-family:
    ui-monospace,
    SFMono-Regular,
    Menlo,
    Monaco,
    Consolas,
    "Liberation Mono",
    monospace;
  font-size: 0.9rem;
  line-height: 1.4;
}
@media (max-width: 760px) {
  .action-item,
  .action-meta {
    grid-template-columns: 1fr;
  }
  .action-next {
    justify-self: start;
    white-space: normal;
  }
  .trace-layout {
    grid-template-columns: 1fr;
  }
  .trace-rail {
    position: static;
  }
  .incident-state-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }
  .definition-table tr {
    grid-template-columns: 1fr;
    gap: 4px;
    padding: 8px 0;
  }
  .definition-table th,
  .definition-table td {
    padding: 0;
  }
}
.log-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 980px;
}
.log-table th,
.log-table td {
  border-bottom: 1px solid var(--line);
  padding: 10px 8px;
  text-align: left;
  vertical-align: top;
}
.log-table th {
  color: var(--muted);
  font-size: 0.78rem;
  text-transform: uppercase;
}
.log-table td span {
  display: block;
  color: var(--muted);
  font-size: 0.85rem;
}
.log-table td .progress-mini span {
  color: var(--ink);
  font-size: 0.9rem;
}
.empty-cell {
  color: var(--muted);
  text-align: center;
}
.live-grid {
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
}
.live-metric strong {
  font-size: 2rem;
}
.live-metric small {
  color: var(--muted);
  display: block;
  line-height: 1.35;
  margin-top: 8px;
}
.live-guidance ul {
  color: var(--muted);
  line-height: 1.6;
  margin: 12px 0 0;
  padding-left: 20px;
}
.error { color: var(--warn); }
@media (max-width: 760px) {
  body { grid-template-columns: 1fr; }
  .sidebar {
    min-height: auto;
    padding: 16px;
  }
  .sidebar-nav {
    display: grid;
    overflow-x: visible;
    gap: 10px;
    align-items: stretch;
  }
  .sidebar-nav > *,
  .primary-nav a,
  .advanced-nav a,
  .nav-summary {
    min-width: 0;
  }
  .primary-nav,
  .advanced-nav[open] {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 138px), 1fr));
    gap: 6px;
  }
  .sidebar a,
  .nav-summary {
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .advanced-nav {
    padding-top: 0;
    border-top: 0;
  }
  .advanced-nav[open] .nav-summary {
    grid-column: 1 / -1;
  }
  .sidebar form { display: none; }
  .workspace { padding: 18px; }
  .key-row { grid-template-columns: 1fr; }
}
"""
