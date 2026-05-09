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
from translator_service.admin.provider_health import ProviderHealthSummary
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeReloadRequest,
    AIProviderRuntimeStatus,
)
from translator_service.admin.quality import QualityRunSummary, QualitySampleScore
from translator_service.admin.secret_safety import SecretSafetyItem, SecretSafetyReport
from translator_service.admin.translation_logs import (
    TranslationRunDetails,
    TranslationRunEvent,
    TranslationRunFragmentDetail,
    TranslationRunSummary,
)
from translator_service.user_activity import UserActivityEvent, UserProfile


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
    nav_items = (
        ("overview", "/admin/overview", "Overview"),
        ("integrations", "/admin/integrations", "Integrations"),
        ("ai_providers", "/admin/ai-providers", "AI Providers"),
        ("billing", "/admin/billing", "Billing"),
        ("costs", "/admin/costs", "Costs"),
        ("quality", "/admin/quality", "Quality"),
        ("live", "/admin/live", "Live"),
        ("logs", "/admin/logs", "Logs"),
        ("activity", "/admin/activity", "Activity"),
        ("users", "/admin/users", "Users"),
        ("settings", "/admin/settings", "Settings"),
        ("operations", "/admin/operations/jobs", "Operations"),
        ("security", "/admin/security/events", "Security"),
        ("audit", "/admin/audit", "Audit"),
    )
    nav = "\n".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>'
        for key, href, label in nav_items
    )
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
    <nav>{nav}</nav>
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
          No urgent admin actions right now.
        </div>
        """
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Action Center</h3>
        <p>
          Prioritized operations signals from integrations, translation runs,
          provider keys, token spend, and server health.
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
    return f"""
    <a
      class="action-item action-{escape(severity)}"
      data-action-key="{escape(item.key)}"
      href="{escape(href)}"
    >
      <span class="status">{escape(severity)}</span>
      <span>
        <strong>{escape(item.title)}</strong>
        <small>{escape(item.detail)}</small>
      </span>
    </a>
    """


def _safe_action_href(href: str) -> str:
    if href.startswith("/admin/"):
        return href
    return "/admin/overview"


def _safe_action_severity(severity: str) -> str:
    if severity in {"critical", "warning", "info"}:
        return severity
    return "info"


def settings_body(report: SecretSafetyReport) -> str:
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
      <td><a class="table-action" href="{escape(href)}">Open</a></td>
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


def _ai_provider_card(
    summary: IntegrationSummary,
    *,
    csrf_token: str,
    keys: tuple[AIProviderKeySummary, ...],
    health: ProviderHealthSummary | None,
    runtime: AIProviderRuntimeStatus | None,
    reload_state: AIProviderRuntimeReloadRequest | None,
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
    health_panel = _provider_health_panel(health)
    runtime_panel = _provider_runtime_panel(
        summary.integration_id,
        runtime,
        reload_state,
        csrf_token,
    )
    test_all_form = _ai_provider_test_all_keys_form(
        summary.integration_id,
        csrf_token=csrf_token,
        active_key_count=testable_key_count,
    )
    return f"""
    <article class="integration-card wide-card">
      <div>
        <p class="eyebrow">{escape(summary.category.value.replace("_", " "))}</p>
        <h3>{escape(summary.label)}</h3>
        <span class="status">{active_key_count} active keys</span>
      </div>
      <p>{escape(summary.description)}</p>
      {health_panel}
      {runtime_panel}
      {test_all_form}
      <div class="key-table">{rows}</div>
      <form class="secret-form key-form" method="post"
        action="/admin/ai-providers/{escape(summary.integration_id)}/keys">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label>
          <span>Label</span>
          <input name="label" type="text" placeholder="main" required>
        </label>
        <label>
          <span>API key</span>
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
          <input name="weight" type="number" min="1" value="1" required>
        </label>
        <label>
          <span>Max parallel</span>
          <input
            name="max_parallel_requests"
            type="number"
            min="1"
            value="1"
            required
          >
        </label>
        <button type="submit">Add key</button>
      </form>
    </article>
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
        channels = '<p class="empty-state">No runtime channels reported.</p>'
    else:
        source = runtime.source
        status = runtime.status
        interval = _format_seconds(runtime.reload_interval_seconds)
        last_reload = runtime.last_reloaded_at.isoformat()
        freshness = _runtime_freshness(runtime)
        error = runtime.error or "n/a"
        channels = "\n".join(
            (
                '<span class="status">'
                f"{escape(channel.label)} · weight {channel.weight} · "
                f"parallel {channel.max_parallel_requests}"
                "</span>"
            )
            for channel in runtime.active_channels
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
        <div class="key-table">{channels}</div>
        <form class="secret-form" method="post"
          action="/admin/ai-providers/{escape(provider_id)}/runtime/reload">
          <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
          <button type="submit">Reload now</button>
        </form>
      </div>
    """


def _ai_provider_test_all_keys_form(
    provider_id: str,
    *,
    csrf_token: str,
    active_key_count: int,
) -> str:
    disabled = " disabled" if active_key_count == 0 else ""
    return f"""
      <form class="secret-form" method="post"
        action="/admin/ai-providers/{escape(provider_id)}/keys/test-all">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <button type="submit"{disabled}>Test all active keys</button>
      </form>
    """


def _format_seconds(value: float) -> str:
    if value.is_integer():
        return f"{int(value)}s"
    return f"{value:.1f}s"


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


def _ai_provider_key_row(key: AIProviderKeySummary, csrf_token: str) -> str:
    if is_env_deepseek_key(key):
        return f"""
    <div class="key-row">
      <div>
        <strong>{escape(key.label)}</strong>
        <code>{escape(key.masked_value or "env fallback")}</code>
        <span>configured from environment</span>
      </div>
      <span>source env fallback</span>
      <span>{key.weight} active keys</span>
    </div>
    """
    remove_action = f"/admin/ai-providers/{escape(key.provider_id)}/keys/remove"
    test_action = f"/admin/ai-providers/{escape(key.provider_id)}/keys/test"
    update_action = f"/admin/ai-providers/{escape(key.provider_id)}/keys/update"
    toggle_action_name = "disable" if key.enabled and not key.disabled else "enable"
    toggle_action = (
        f"/admin/ai-providers/{escape(key.provider_id)}/keys/{toggle_action_name}"
    )
    toggle_label = "Disable" if key.enabled and not key.disabled else "Enable"
    enabled_status = "enabled" if key.enabled and not key.disabled else "disabled"
    return f"""
    <div class="key-row">
      <div>
        <strong>{escape(key.label)}</strong>
        <code>{escape(key.masked_value or "missing")}</code>
        <span>{enabled_status}</span>
      </div>
      <form method="post" action="{update_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <input type="hidden" name="key_id" value="{escape(key.key_id)}">
        <label>
          <span>Label</span>
          <input name="label" type="text" value="{escape(key.label)}" required>
        </label>
        <label>
          <span>Weight</span>
          <input name="weight" type="number" min="1" value="{key.weight}" required>
        </label>
        <label>
          <span>Max parallel</span>
          <input
            name="max_parallel_requests"
            type="number"
            min="1"
            value="{key.max_parallel_requests}"
            required
          >
        </label>
        <button type="submit">Save</button>
      </form>
      <span>weight {key.weight}</span>
      <span>parallel {key.max_parallel_requests}</span>
      <form method="post" action="{toggle_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <button type="submit" value="{escape(key.key_id)}" name="key_id">
          {toggle_label}
        </button>
      </form>
      <form method="post" action="{remove_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <button class="danger" type="submit" value="{escape(key.key_id)}" name="key_id">
          Remove
        </button>
      </form>
      <form method="post" action="{test_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <button type="submit" value="{escape(key.key_id)}" name="key_id">
          Test key
        </button>
      </form>
    </div>
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


def quality_body(summary: QualityRunSummary) -> str:
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
      <code>{escape(summary.candidate_path)}</code>
    </section>
    <section class="metrics">{metric_cards}</section>
    {empty_state}
    <section class="panel table-panel">
      <h3>Reference samples</h3>
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
        <tbody>{_quality_rows(summary.rows)}</tbody>
      </table>
    </section>
    """


def _quality_metric(label: str, value: str) -> str:
    return f"""
    <article class="metric">
      <span>{escape(label)}</span>
      <strong>{escape(value)}</strong>
    </article>
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
        <a class="table-action" href="{escape(_safe_cost_log_href(run.log_href))}">
          Logs
        </a>
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


def operations_body(overview: OperationsOverview) -> str:
    metrics = (
        ("Queued", overview.job_counts_by_state.get("queued", 0)),
        ("Running", overview.job_counts_by_state.get("running", 0)),
        ("Failed", overview.job_counts_by_state.get("failed", 0)),
        ("Queue depth", overview.total_queue_depth),
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
        <tbody>{_operation_job_rows(overview)}</tbody>
      </table>
    </section>
    <section class="panel">
      <h3>Workers</h3>
      <p>{len(overview.workers)} workers are currently visible to the admin console.</p>
    </section>
    """


def _operation_job_rows(overview: OperationsOverview) -> str:
    if not overview.jobs:
        return """
        <tr>
          <td colspan="10" class="empty-cell">No persistent jobs found.</td>
        </tr>
        """
    return "\n".join(_operation_job_row(job) for job in overview.jobs)


def _operation_job_row(job) -> str:
    fragments = f"{job.completed_units}/{job.total_units}"
    logs = (
        '<a class="table-action" '
        f'href="{escape(_safe_operation_log_href(job.log_href))}">Logs</a>'
        if job.log_href
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
      <td>{_job_actions(job)}</td>
    </tr>
    """


def _operation_job_times(job) -> str:
    primary = job.started_at or job.created_at
    primary_label = "Started" if job.started_at else "Created"
    return f"""
    <span>{escape(primary_label)} {escape(_format_datetime(primary))}</span>
    <span>Updated {escape(_format_datetime(job.updated_at))}</span>
    """


def _job_actions(job) -> str:
    if job.retryable:
        return '<button type="button" disabled>Retry unavailable</button>'
    if job.cancellable:
        return '<button type="button" disabled>Cancel unavailable</button>'
    return '<button type="button" disabled>No action</button>'


def _safe_operation_log_href(href: str) -> str:
    if href.startswith("/admin/"):
        return href
    return "/admin/logs"


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
) -> str:
    metrics = (
        ("Active translations", snapshot.active_translations, "active_translations"),
        ("Queued", snapshot.queued_translations, "queued_translations"),
        ("Failed today", snapshot.failed_today, "failed_today"),
        ("Tokens today", snapshot.tokens_today, "tokens_today"),
        ("Tokens last hour", snapshot.tokens_last_hour, "tokens_last_hour"),
        (
            "Server health",
            "pending" if not snapshot.server.available else "online",
            "server_health",
        ),
        ("CPU", _percent(snapshot.server.cpu_percent), "server_cpu_percent"),
        ("Memory", _percent(snapshot.server.memory_percent), "server_memory_percent"),
        ("Disk", _percent(snapshot.server.disk_percent), "server_disk_percent"),
        ("Uptime", _duration(snapshot.server.uptime_seconds), "server_uptime"),
    )
    metric_cards = "\n".join(
        f"""
        <article class="metric live-metric">
          <span>{escape(label)}</span>
          <strong data-live-field="{escape(field)}">{value}</strong>
        </article>
        """
        for label, value, field in metrics
    )
    runtime_cards = _live_runtime_cards(runtime_statuses, runtime_reload_states)
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>Live Monitor</h3>
        <p>
          Keep this screen open to watch active translations, queue pressure,
          token spend, failures, and server health.
        </p>
      </div>
      <a class="button-link" href="/admin/live" target="_blank" rel="noreferrer">
        Open monitor
      </a>
    </section>
    <section class="metrics live-grid">{metric_cards}</section>
    <section class="panel">
      <h3>DeepSeek runtime</h3>
      <div class="metric-grid">{runtime_cards}</div>
    </section>
    <section class="panel table-panel">
      <h3>Recent runs</h3>
      <table class="log-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Job</th>
            <th>File</th>
            <th>Direction</th>
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
          <td>${{escapeHtml(run.total_tokens || 0)}}</td>
        </tr>
      `).join("");
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
        else ", ".join(channel.label for channel in status.active_channels)
    )
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
          <td colspan="5" class="empty-cell">No recent runs yet.</td>
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
      <td>{run.total_tokens}</td>
    </tr>
    """


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
        <h3>Translation Logs</h3>
        <p>
          Review translation runs by date, state, file, language direction,
          token usage, and safe error metadata.
        </p>
      </div>
    </section>
    <section class="panel">
      <form class="filter-form" method="get" action="/admin/logs">
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
        <button type="submit">Apply filters</button>
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
        <a class="secondary-action" href="/admin/logs">Back to logs</a>
        <a class="secondary-action" href="/admin/logs/{escape(run_id)}/download">
          Download archive
        </a>
      </div>
    </section>
    <section class="panel">
      <div class="metric-grid">
        {_metric("Job", summary.job_id)}
        {_metric("Status", summary.status)}
        {_metric("Started", _format_datetime(summary.started_at))}
        {_metric("Finished", _format_datetime(summary.finished_at))}
        {_metric("Fragments", str(summary.fragment_count))}
        {_metric("Tokens", str(summary.total_tokens))}
      </div>
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
        <tbody>{fragments}</tbody>
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
        <tbody>{events}</tbody>
      </table>
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
        <button type="submit">Apply filters</button>
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


def _metric(label: str, value: str) -> str:
    return f"""
    <div class="metric-card">
      <span>{escape(label)}</span>
      <strong>{escape(value)}</strong>
    </div>
    """


def _log_row(row: TranslationRunSummary) -> str:
    started = row.started_at.isoformat(timespec="seconds") if row.started_at else "n/a"
    direction = f"{row.source_language} -> {row.target_language}"
    error = row.error_message or ""
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
        <a class="table-action"
          href="/admin/logs/{escape(Path(row.run_dir).name)}">
          Details
        </a>
        <a class="table-action"
          href="/admin/logs/{escape(Path(row.run_dir).name)}/download">
          Download
        </a>
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
        f"""
        <tr>
          <th>{escape(str(key))}</th>
          <td>{escape(_detail_value(value))}</td>
        </tr>
        """
        for key, value in sorted(values.items())
        if value not in (None, "", {}, ())
    )
    if not rows:
        rows = '<tr><td colspan="2" class="empty-cell">No data recorded.</td></tr>'
    return f'<table class="definition-table"><tbody>{rows}</tbody></table>'


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
        <button type="submit">Add connection</button>
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
        return '<span class="status">managed by environment</span>'
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
        <button class="danger" type="submit">Remove</button>
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
.login-screen {
  display: grid;
  grid-template-columns: 1fr;
  place-items: center;
  padding: 24px;
}
.login-panel, .panel, .toolbar-panel, .integration-card, .metric {
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
  min-height: 100vh;
  padding: 24px 18px;
  background: #111827;
  color: #f9fafb;
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.sidebar h1, .workspace h2, .panel h3 { margin: 0; }
.sidebar nav { display: grid; gap: 6px; }
.sidebar a {
  color: #d1d5db;
  text-decoration: none;
  padding: 10px 12px;
  border-radius: 6px;
}
.sidebar a.active, .sidebar a:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.12);
}
.workspace {
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
}
.toolbar-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
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
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px;
}
.integration-card {
  display: grid;
  gap: 14px;
}
.integration-folder {
  padding: 0;
  overflow: hidden;
}
.integration-folder summary {
  list-style: none;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
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
  grid-template-columns: minmax(160px, 1fr) auto auto auto;
  gap: 12px;
  align-items: center;
  border-top: 1px solid var(--line);
  padding-top: 10px;
}
.connection-row {
  grid-template-columns: minmax(160px, 1fr) auto;
}
.connection-form {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  align-items: end;
}
.key-row form { display: block; }
.integration-card code {
  color: var(--muted);
  font-size: 0.85rem;
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
  grid-template-columns: auto minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  padding: 16px 20px;
  color: inherit;
  text-decoration: none;
  border-bottom: 1px solid var(--line);
}
.action-item:last-child { border-bottom: 0; }
.action-item:hover {
  background: #fbfcfd;
}
.action-item span:last-child {
  display: grid;
  gap: 4px;
}
.action-item strong {
  overflow-wrap: anywhere;
}
.action-item small {
  color: var(--muted);
  line-height: 1.45;
}
.action-critical .status {
  color: var(--warn);
  border-color: rgba(163, 61, 42, 0.35);
}
.status {
  width: max-content;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--accent-strong);
  font-size: 0.8rem;
  font-weight: 700;
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
.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 18px;
}
.detail-grid h4,
.table-panel h4 {
  margin: 0 0 12px;
}
.definition-table {
  width: 100%;
  border-collapse: collapse;
}
.definition-table th,
.definition-table td {
  border-bottom: 1px solid var(--line);
  padding: 8px 0;
  text-align: left;
  vertical-align: top;
}
.definition-table th {
  width: 42%;
  color: var(--muted);
  font-size: 0.78rem;
  text-transform: uppercase;
}
.log-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 860px;
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
.error { color: var(--warn); }
@media (max-width: 760px) {
  body { grid-template-columns: 1fr; }
  .sidebar {
    min-height: auto;
    padding: 16px;
  }
  .sidebar nav {
    display: flex;
    overflow-x: auto;
  }
  .sidebar form { display: none; }
  .workspace { padding: 18px; }
  .key-row { grid-template-columns: 1fr; }
}
"""
