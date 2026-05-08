from __future__ import annotations

from html import escape

from translator_service.admin.ai_provider_keys import AIProviderKeySummary
from translator_service.admin.auth import AdminSession
from translator_service.admin.integration_connections import (
    IntegrationConnectionSummary,
)
from translator_service.admin.integrations import (
    IntegrationSecretSummary,
    IntegrationSummary,
)
from translator_service.admin.live import LiveMonitorSnapshot
from translator_service.admin.operations import OperationsOverview
from translator_service.admin.translation_logs import TranslationRunSummary
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
) -> str:
    nav_items = (
        ("overview", "/admin/overview", "Overview"),
        ("integrations", "/admin/integrations", "Integrations"),
        ("ai_providers", "/admin/ai-providers", "AI Providers"),
        ("billing", "/admin/billing", "Billing"),
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
) -> str:
    cards = "\n".join(
        _ai_provider_card(
            summary,
            csrf_token=csrf_token,
            keys=(key_pools or {}).get(summary.integration_id, ()),
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
) -> str:
    rows = "\n".join(_ai_provider_key_row(key, csrf_token) for key in keys)
    if not rows:
        rows = '<p class="empty-state">No keys configured yet.</p>'
    return f"""
    <article class="integration-card wide-card">
      <div>
        <p class="eyebrow">{escape(summary.category.value.replace("_", " "))}</p>
        <h3>{escape(summary.label)}</h3>
        <span class="status">{len(keys)} active keys</span>
      </div>
      <p>{escape(summary.description)}</p>
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


def _ai_provider_key_row(key: AIProviderKeySummary, csrf_token: str) -> str:
    remove_action = f"/admin/ai-providers/{escape(key.provider_id)}/keys/remove"
    return f"""
    <div class="key-row">
      <div>
        <strong>{escape(key.label)}</strong>
        <code>{escape(key.masked_value or "missing")}</code>
      </div>
      <span>weight {key.weight}</span>
      <span>parallel {key.max_parallel_requests}</span>
      <form method="post" action="{remove_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <input type="hidden" name="key_id" value="{escape(key.key_id)}">
        <button class="danger" type="submit">Remove</button>
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
    <section class="panel">
      <h3>Jobs</h3>
      <p>{len(overview.jobs)} jobs are currently visible to the admin console.</p>
    </section>
    <section class="panel">
      <h3>Workers</h3>
      <p>{len(overview.workers)} workers are currently visible to the admin console.</p>
    </section>
    """


def live_body(snapshot: LiveMonitorSnapshot) -> str:
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
        const body = document.querySelector("[data-live-runs]");
        if (body) body.innerHTML = runRows(data.recent_runs);
      }}
      setInterval(refreshLiveMonitor, 3000);
    </script>
    """


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


def logs_body(
    logs: tuple[TranslationRunSummary, ...],
    *,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    rows = "\n".join(_log_row(row) for row in logs)
    if not rows:
        rows = """
        <tr>
          <td colspan="8" class="empty-cell">No translation logs found.</td>
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
          </tr>
        </thead>
        <tbody>{rows}</tbody>
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
        return section_body("User not found", "No activity profile exists for this user.")
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
        <tbody>{"".join(_activity_row(event, include_user=False) for event in events)}</tbody>
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
    </tr>
    """


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


def _integration_connection_row(
    connection: IntegrationConnectionSummary,
    csrf_token: str,
) -> str:
    remove_action = (
        f"/admin/integrations/{escape(connection.integration_id)}/connections/remove"
    )
    secrets = " ".join(
        _connection_secret_chip(secret) for secret in connection.secret_values
    )
    return f"""
    <div class="key-row connection-row">
      <div>
        <strong>{escape(connection.label)}</strong>
        {secrets}
      </div>
      <form method="post" action="{remove_action}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <input
          type="hidden"
          name="connection_id"
          value="{escape(connection.connection_id)}"
        >
        <button class="danger" type="submit">Remove</button>
      </form>
    </div>
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
}
.panel, .toolbar-panel, .integration-card, .metric { padding: 20px; }
.panel p, .login-panel p { color: var(--muted); line-height: 1.55; }
.toolbar-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
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
.status {
  width: max-content;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--accent-strong);
  font-size: 0.8rem;
  font-weight: 700;
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
