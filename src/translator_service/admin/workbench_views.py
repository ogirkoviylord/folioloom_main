"""Server-rendered Workbench glossary UI (Stage 1 / glossary-first slice).

This module renders the bounded, ephemeral Workbench glossary UI exactly
as described in ``.hermes/workbench_ui_packet/UI_PACKET_S1_GLOSSARY_FIRST.md``.
It is intentionally narrow:

* It owns no business logic — :mod:`workbench_session_state` is the only
  place where state mutates.
* It must never imply that locally-approved terms are authoritative
  glossary approvals. ``ManualGlossaryApproval`` is still an owner-blocker
  (GATE1 audit C1). The README disclosure in the helper rail says so
  verbatim.
* It must never invoke the runner, provider, cache, Telegram, resolver,
  job store, archive, DB or filesystem evidence root (packet §6, §11).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from html import escape
from urllib.parse import quote

from translator_service.admin.workbench_glossary_projection import (
    WorkbenchGlossaryProjection,
    WorkbenchGlossaryProjectionState,
)
from translator_service.admin.workbench_session_state import (
    TERM_TYPES,
    ApprovalState,
    Term,
    TermStatus,
    WorkbenchSessionState,
    empty_workbench_session,
)

# ---------------------------------------------------------------------------
# Stage and copy table (packet §4, §5.4)
# ---------------------------------------------------------------------------


#: Honest placeholder stages (packet §3.2 nav rail + §4.4 future screen).
WORKBENCH_PLACEHOLDER_STAGES: tuple[tuple[str, str], ...] = (
    ("project-library", "Project Library"),
    ("document-setup", "Document Setup"),
    ("ai-suggestions", "Suggestions"),
    ("translate", "Translate"),
    ("review", "Review"),
    ("export", "Export"),
)


#: Exact copy (packet §5.4). Kept as a module-level table so the tests can
#: pin every literal and the implementation stays honest.
WORKBENCH_COPY = {
    "not_injected": ("Select a document in Admin to open it in Workbench."),
    "injected_but_invalid": (
        "This document reference is not available in this slice. "
        "Return to Admin and try again."
    ),
    "stale_injection": ("Document reference is stale. Refresh in Admin and reopen."),
    "glossary_empty": (
        "No terms yet. Add your first term to begin shaping the glossary."
    ),
    "ready_helper": ("Glossary is ready. Lock approved terms so they cannot drift."),
    "not_ready_helper": ("Approve at least one term to mark the glossary as ready."),
    "stale_top_strip": (
        "This document was changed since the glossary was opened. "
        "Reopen from Admin to refresh."
    ),
    "unavailable_inline": (
        "Glossary control is not available right now. Try again in a moment."
    ),
    "conflict_helper": ("One or more terms are in conflict. Resolve them row by row."),
    "not_wired_after_post": (
        "Saving is not wired in this slice. Your changes stay only until you reload."
    ),
    "recovery_stale": (
        "This document was changed since the glossary was opened. "
        "Reopen from Admin to refresh."
    ),
    "recovery_unavailable": (
        "Glossary control is not available right now. Try again in a moment."
    ),
    "recovery_not_wired": (
        "Saving is not wired in this slice. Your terms stay only until you reload."
    ),
    "recovery_invalid": ("This document reference is not valid. Return to Admin."),
    "future_placeholder": (
        "{title} is not part of this slice. It will appear here in a later stage."
    ),
    "locked_row_tooltip": ("Locked. Unlock the term to edit or reject it."),
    "disabled_row_tooltip": (
        "Glossary control is read-only until the document is reopened."
    ),
    "about_this_slice": (
        "This is the first functional slice. Glossary control is local "
        "and resets on reload. Save and provider integration are not "
        "wired yet. Locally-approved terms are not authoritative glossary "
        "approvals (ManualGlossaryApproval is still an owner-blocker)."
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_attr(value: str) -> str:
    return escape(value, quote=True)


def _format_iso(dt: datetime) -> str:
    # Stable, sortable, locale-neutral ISO-8601 (UTC).
    return dt.replace(microsecond=0).astimezone().isoformat()


def _stage_meta(stage: str) -> tuple[str, str]:
    for key, title in WORKBENCH_PLACEHOLDER_STAGES:
        if key == stage:
            return title, WORKBENCH_COPY["future_placeholder"].format(title=title)
    return stage.title(), WORKBENCH_COPY["future_placeholder"].format(
        title=stage.title()
    )


# ---------------------------------------------------------------------------
# CSS (Theme C warm-neutral palette, packet §2)
# ---------------------------------------------------------------------------


def _workbench_css() -> str:
    return """
.workbench {
  color-scheme: light;
  --wb-bg: #FBFAF7;
  --wb-surface: #FFFFFF;
  --wb-ink: #292724;
  --wb-ink-soft: #5B544B;
  --wb-line: #E6E1D6;
  --wb-line-strong: #C9C0AE;
  --wb-accent: #4B3F72;
  --wb-accent-soft: #ECE8F5;
  --wb-warn: #B8863B;
  --wb-warn-soft: #FAEFD9;
  --wb-conflict: #9F624D;
  --wb-conflict-soft: #F4E1D8;
  --wb-disabled: #8A857C;
  --wb-success: #55735A;
  --wb-radius-md: 10px;
  --wb-radius-lg: 14px;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", Inter, sans-serif;
  background: var(--wb-bg);
  color: var(--wb-ink);
  min-height: 100vh;
  display: grid;
  grid-template-rows: 64px 1fr;
}
.workbench a { color: var(--wb-accent); }
.workbench a:focus-visible,
.workbench button:focus-visible,
.workbench input:focus-visible,
.workbench select:focus-visible,
.workbench textarea:focus-visible {
  outline: 2px solid var(--wb-accent);
  outline-offset: 2px;
  border-radius: var(--wb-radius-md);
}
.wb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 24px;
  background: var(--wb-surface);
  border-bottom: 1px solid var(--wb-line);
}
.wb-header__brand {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.wb-header__eyebrow {
  font-size: 0.75rem;
  color: var(--wb-ink-soft);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.wb-header__title {
  font-size: 1.125rem;
  font-weight: 600;
}
.wb-header__chips { display: flex; gap: 8px; align-items: center; }
.wb-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--wb-line-strong);
  background: var(--wb-surface);
  font-size: 0.8125rem;
  color: var(--wb-ink);
}
.wb-chip--ephemeral {
  background: var(--wb-warn-soft);
  border-color: var(--wb-warn);
  color: #6B4D17;
}
.wb-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 340px;
  gap: 0;
}
.wb-nav {
  background: var(--wb-surface);
  border-right: 1px solid var(--wb-line);
  padding: 16px 12px;
  display: grid;
  gap: 4px;
  align-content: start;
}
.wb-nav__link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--wb-radius-md);
  color: var(--wb-ink);
  text-decoration: none;
  font-size: 0.9375rem;
}
.wb-nav__link[aria-current="page"] {
  background: var(--wb-accent-soft);
  color: var(--wb-accent);
  font-weight: 600;
}
.wb-nav__link:hover { background: var(--wb-line); }
.wb-nav__placeholder-tag {
  font-size: 0.6875rem;
  color: var(--wb-ink-soft);
}
.wb-main {
  padding: 24px;
  display: grid;
  gap: 16px;
  align-content: start;
}
.wb-rail {
  background: var(--wb-surface);
  border-left: 1px solid var(--wb-line);
  padding: 24px 20px;
  display: grid;
  gap: 16px;
  align-content: start;
}
.wb-card {
  background: var(--wb-surface);
  border: 1px solid var(--wb-line);
  border-radius: var(--wb-radius-lg);
  padding: 16px 18px;
  box-shadow: 0 1px 0 rgba(22, 32, 42, 0.04);
}
.wb-card h3 { margin: 0 0 8px 0; font-size: 1rem; }
.wb-card p { margin: 0; color: var(--wb-ink-soft); }
.wb-strip {
  border-radius: var(--wb-radius-md);
  padding: 12px 16px;
  font-size: 0.9375rem;
}
.wb-strip--stale { background: var(--wb-warn-soft); color: #6B4D17; }
.wb-strip--unavailable { background: var(--wb-line); color: var(--wb-ink); }
.wb-strip--not-wired {
  background: var(--wb-warn-soft);
  color: #6B4D17;
  border: 1px solid var(--wb-warn);
}
.wb-document-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.wb-document-strip__pair { color: var(--wb-ink); }
.wb-document-strip__pair small {
  display: block;
  color: var(--wb-ink-soft);
  font-size: 0.75rem;
}
.wb-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  padding: 12px 16px;
  background: var(--wb-surface);
  border: 1px solid var(--wb-line);
  border-radius: var(--wb-radius-md);
}
.wb-toolbar__buttons { display: flex; gap: 8px; flex-wrap: wrap; }
.wb-toolbar__filters { display: flex; gap: 4px; margin-left: auto; }
.wb-button {
  appearance: none;
  border: 1px solid var(--wb-line-strong);
  background: var(--wb-surface);
  color: var(--wb-ink);
  border-radius: var(--wb-radius-md);
  padding: 8px 14px;
  font-size: 0.9375rem;
  cursor: pointer;
  font-family: inherit;
}
.wb-button--primary {
  background: var(--wb-accent);
  border-color: var(--wb-accent);
  color: #FFFFFF;
}
.wb-button--secondary { background: var(--wb-surface); }
.wb-button[disabled],
.wb-button[aria-disabled="true"] {
  background: var(--wb-line);
  color: var(--wb-disabled);
  cursor: not-allowed;
  border-color: var(--wb-line);
}
.wb-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 0.75rem;
  border: 1px solid currentColor;
}
.wb-pill--approved {
  color: var(--wb-success);
  background: #ECF3EE;
  border-color: var(--wb-success);
}
.wb-pill--locked {
  color: var(--wb-accent);
  background: var(--wb-accent-soft);
  border-color: var(--wb-accent);
}
.wb-pill--pending {
  color: var(--wb-ink-soft);
  background: var(--wb-line);
  border-color: var(--wb-line-strong);
}
.wb-pill--rejected {
  color: var(--wb-conflict);
  background: var(--wb-conflict-soft);
  border-color: var(--wb-conflict);
}
.wb-pill--conflict {
  color: var(--wb-conflict);
  background: var(--wb-conflict-soft);
  border-color: var(--wb-conflict);
}
.wb-pill--draft {
  color: var(--wb-ink-soft);
  background: var(--wb-line);
  border-color: var(--wb-line-strong);
}
.wb-pill--disabled {
  color: var(--wb-disabled);
  background: var(--wb-line);
  border-color: var(--wb-line-strong);
}
.wb-term-list {
  display: grid;
  gap: 8px;
}
.wb-term {
  background: var(--wb-surface);
  border: 1px solid var(--wb-line);
  border-radius: var(--wb-radius-lg);
  padding: 12px 16px;
  display: grid;
  grid-template-columns: 1.2fr 1.2fr 0.8fr auto;
  gap: 12px;
  align-items: center;
}
.wb-term__col small {
  display: block;
  color: var(--wb-ink-soft);
  font-size: 0.75rem;
}
.wb-term__actions { display: flex; gap: 6px; flex-wrap: wrap; }
.wb-term__selection {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8125rem;
  color: var(--wb-ink-soft);
}
.wb-term__details {
  grid-column: 1 / -1;
  border-top: 1px solid var(--wb-line);
  padding-top: 8px;
  margin-top: 8px;
  color: var(--wb-ink-soft);
  font-size: 0.8125rem;
}
.wb-term__details summary { cursor: pointer; }
.wb-term__details[open] summary { color: var(--wb-ink); margin-bottom: 6px; }
.wb-term-form {
  background: var(--wb-surface);
  border: 1px solid var(--wb-line);
  border-radius: var(--wb-radius-lg);
  padding: 16px 18px;
  display: grid;
  gap: 12px;
}
.wb-term-form__row { display: grid; gap: 6px; }
.wb-term-form__row label { font-size: 0.8125rem; color: var(--wb-ink-soft); }
.wb-term-form__row input,
.wb-term-form__row select,
.wb-term-form__row textarea {
  font: inherit;
  padding: 8px 10px;
  border: 1px solid var(--wb-line-strong);
  border-radius: var(--wb-radius-md);
  background: var(--wb-surface);
  color: var(--wb-ink);
}
.wb-term-form__actions { display: flex; gap: 8px; }
.wb-empty {
  text-align: center;
  padding: 32px 16px;
  color: var(--wb-ink-soft);
  border: 1px dashed var(--wb-line-strong);
  border-radius: var(--wb-radius-lg);
  background: var(--wb-surface);
}
.wb-empty p { margin: 0 0 12px 0; color: var(--wb-ink); }
.wb-recovery {
  background: var(--wb-bg);
  padding: 48px 24px;
  display: grid;
  place-items: center;
}
.wb-recovery__panel {
  max-width: 540px;
  background: var(--wb-surface);
  border: 1px solid var(--wb-line);
  border-radius: var(--wb-radius-lg);
  padding: 24px;
  text-align: center;
}
.wb-recovery__panel h2 { margin: 0 0 8px 0; }
.wb-recovery__panel p { margin: 0 0 16px 0; color: var(--wb-ink-soft); }
.wb-helper-rail__title {
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--wb-ink-soft);
}
.wb-helper-rail__health {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 16px;
}
.wb-helper-rail__health dt { font-size: 0.75rem; color: var(--wb-ink-soft); }
.wb-helper-rail__health dd { margin: 0; font-size: 0.9375rem; }
.wb-helper-rail__about summary { cursor: pointer; font-weight: 600; }
.wb-helper-rail__about p {
  margin-top: 8px;
  font-size: 0.8125rem;
  color: var(--wb-ink-soft);
}
.wb-helper-rail__dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 8px;
  background: var(--wb-disabled);
}
.wb-helper-rail__dot--ready { background: var(--wb-success); }
.wb-helper-rail__dot--not-ready { background: var(--wb-warn); }
.wb-helper-rail__dot--stale { background: var(--wb-warn); }
.wb-helper-rail__dot--unavailable { background: var(--wb-disabled); }
.wb-helper-rail__dot--conflict { background: var(--wb-conflict); }
@media (max-width: 1179px) {
  .workbench .wb-shell { grid-template-columns: 280px minmax(0, 1fr); }
  .workbench .wb-rail { display: none; }
}
@media (max-width: 899px) {
  .workbench .wb-shell { grid-template-columns: 72px minmax(0, 1fr); }
  .workbench .wb-nav__link { justify-content: center; padding: 12px 6px; }
  .workbench .wb-nav__link span { display: none; }
}
"""


# ---------------------------------------------------------------------------
# Status pill (packet §5.1)
# ---------------------------------------------------------------------------


_PILL_CLASS = {
    TermStatus.DRAFT: "wb-pill--draft",
    TermStatus.PENDING: "wb-pill--pending",
    TermStatus.APPROVED: "wb-pill--approved",
    TermStatus.LOCKED: "wb-pill--locked",
    TermStatus.REJECTED: "wb-pill--rejected",
    TermStatus.CONFLICT: "wb-pill--conflict",
}


def _workbench_status_pill(status: TermStatus) -> str:
    label = status.value.capitalize()
    css = _PILL_CLASS.get(status, "wb-pill--draft")
    return (
        f'<span class="wb-pill {css}" aria-label="Status: {label.lower()}">'
        f"{label}</span>"
    )


# ---------------------------------------------------------------------------
# Header, nav, and document strip (packet §3.2, §4.2)
# ---------------------------------------------------------------------------


def _workbench_header(document_id: str, ephemeral_session_id: str) -> str:
    safe_doc = _safe_attr(document_id or "(no document)")
    safe_session = _safe_attr(ephemeral_session_id or "(ephemeral)")
    return f"""
<header class="wb-header" role="banner">
  <div class="wb-header__brand">
    <span class="wb-header__eyebrow">FolioLoom</span>
    <span class="wb-header__title">Workbench</span>
  </div>
  <div class="wb-header__chips">
    <span class="wb-chip" data-chip="document-id">document_id · {safe_doc}</span>
    <span class="wb-chip wb-chip--ephemeral" data-chip="ephemeral-session">
      Not saved · resets on reload · {safe_session}
    </span>
    <a class="wb-chip" href="/admin/overview">Back to Admin</a>
  </div>
</header>
"""


def _workbench_nav(active: str, document_id: str | None) -> str:
    document_qs = f"?document={_safe_attr(document_id)}" if document_id else ""
    glossary_href = f"/admin/workbench/glossary{document_qs}"
    aria_current_attr = ' aria-current="page"' if active == "glossary" else ""
    glossary_link = (
        f'<a class="wb-nav__link" href="{glossary_href}"{aria_current_attr}>'
        "<span>Glossary</span></a>"
    )
    placeholder_links: list[str] = []
    for stage_key, title in WORKBENCH_PLACEHOLDER_STAGES:
        href = f"/admin/workbench/future?stage={_safe_attr(stage_key)}"
        placeholder_links.append(
            f'<a class="wb-nav__link" href="{href}">'
            f"<span>{_safe_attr(title)}</span>"
            '<span class="wb-nav__placeholder-tag" aria-label="placeholder">'
            "not in slice</span></a>"
        )
    return f"""
<nav class="wb-nav" aria-label="Workbench navigation">
  {glossary_link}
  {"".join(placeholder_links)}
</nav>
"""


def _workbench_document_strip(state: WorkbenchSessionState) -> str:
    doc = state.document
    if not doc.document_id:
        # Nothing injected yet — no strip.
        return ""
    src_to_tgt = (
        f"{_safe_attr(doc.source_language)} → {_safe_attr(doc.target_language)}"
    )
    return f"""
<section class="wb-document-strip" data-document-id="{_safe_attr(doc.document_id)}">
  <div class="wb-document-strip__pair">
    <small>Document</small>
    <strong>{_safe_attr(doc.filename or doc.document_id)}</strong>
  </div>
  <div class="wb-document-strip__pair">
    <small>Format</small>
    <span>{_safe_attr(doc.format or "n/a")}</span>
  </div>
  <div class="wb-document-strip__pair">
    <small>Source → Target</small>
    <span>{src_to_tgt}</span>
  </div>
  <div class="wb-document-strip__pair">
    <small>Approval</small>
    {_workbench_status_pill_for_state(state)}
  </div>
</section>
"""


def _workbench_status_pill_for_state(state: WorkbenchSessionState) -> str:
    label_map = {
        ApprovalState.READY: "Ready",
        ApprovalState.NOT_READY: "Not ready",
        ApprovalState.STALE: "Stale",
        ApprovalState.UNAVAILABLE: "Unavailable",
        ApprovalState.CONFLICT: "Conflict",
    }
    css_map = {
        ApprovalState.READY: "wb-pill--approved",
        ApprovalState.NOT_READY: "wb-pill--draft",
        ApprovalState.STALE: "wb-pill--pending",
        ApprovalState.UNAVAILABLE: "wb-pill--disabled",
        ApprovalState.CONFLICT: "wb-pill--conflict",
    }
    state_value = state.approval_state
    label = label_map.get(state_value, "Unknown")
    css = css_map.get(state_value, "wb-pill--draft")
    return (
        f'<span class="wb-pill {css}" '
        f'aria-label="Approval state: {label.lower()}">{label}</span>'
    )


# ---------------------------------------------------------------------------
# Toolbar (packet §4.2)
# ---------------------------------------------------------------------------


def _workbench_toolbar(
    state: WorkbenchSessionState,
    *,
    csrf_token: str,
    active_filter: str = "all",
) -> str:
    disabled_add = state.approval_state in (
        ApprovalState.STALE,
        ApprovalState.UNAVAILABLE,
    )
    no_terms = state.health_snapshot.get("total", 0) == 0
    has_approved = state.health_snapshot.get("approved", 0) > 0
    locked_or_approved = state.approval_state == ApprovalState.READY
    disable_check = no_terms or state.approval_state == ApprovalState.CONFLICT
    disable_lock_all = not has_approved or not locked_or_approved
    check_disabled_attr = ' disabled aria-disabled="true"' if disable_check else ""
    approve_disabled_attr = ' disabled aria-disabled="true"' if no_terms else ""
    lock_disabled_attr = ' disabled aria-disabled="true"' if disable_lock_all else ""
    document_qs = (
        f"?document={quote(state.document.document_id, safe='')}"
        if state.document.document_id
        else ""
    )
    add_control = (
        '<button type="button" class="wb-button wb-button--primary" '
        'data-action="add-term" disabled aria-disabled="true" '
        'aria-controls="wb-add-term-form">Add term</button>'
        if disabled_add
        else (
            '<a class="wb-button wb-button--primary" data-action="add-term" '
            f'href="/admin/workbench/glossary{document_qs}&amp;add=1" '
            'aria-controls="wb-add-term-form">Add term</a>'
        )
    )
    return f"""
<form id="wb-check-selected-form" class="wb-toolbar" method="post"
  action="/admin/workbench/glossary/check{document_qs}">
  <div class="wb-toolbar__buttons">
    {add_control}
    <button type="submit" class="wb-button wb-button--secondary"
      data-action="approve-glossary"{approve_disabled_attr}
      formaction="/admin/workbench/glossary/approve{document_qs}"
      title="Explicitly approve this exact local glossary snapshot">
      Approve current snapshot</button>
    <button type="submit" class="wb-button wb-button--secondary"
      data-action="check-selected"{check_disabled_attr}
      title="Runs a local-only check shape on selected terms">
      Check selected terms</button>
    <button type="submit" class="wb-button wb-button--secondary"
      data-action="lock-all-approved"{lock_disabled_attr}
      formaction="/admin/workbench/glossary/terms/lock-all-approved{document_qs}">
      Lock all approved</button>
  </div>
  <div class="wb-toolbar__filters" role="group" aria-label="Filter terms">
    {_filter_chip("all", "All", active_filter, document_qs)}
    {_filter_chip("approved", "Approved", active_filter, document_qs)}
    {_filter_chip("locked", "Locked", active_filter, document_qs)}
    {_filter_chip("pending", "Pending", active_filter, document_qs)}
  </div>
  <input type="hidden" name="csrf_token" value="{_safe_attr(csrf_token)}">
</form>
"""


def _filter_chip(key: str, label: str, active_filter: str, document_qs: str) -> str:
    safe_label = _safe_attr(label)
    is_active = active_filter == key
    href = f"/admin/workbench/glossary{document_qs}" + (
        "" if key == "all" else f"&filter={key}"
    )
    aria_current = ' aria-current="page"' if is_active else ""
    css = "wb-pill wb-pill--locked" if is_active else "wb-pill wb-pill--pending"
    return f'<a class="{css}" href="{href}"{aria_current}>{safe_label}</a>'


# ---------------------------------------------------------------------------
# Term form (Add / Edit, modal panel)
# ---------------------------------------------------------------------------


def _workbench_term_form(
    *,
    mode: str,
    csrf_token: str,
    document_id: str,
    term: Term | None = None,
) -> str:
    is_edit = mode == "edit"
    document_qs = f"?document={quote(document_id, safe='')}" if document_id else ""
    action = (
        f"/admin/workbench/glossary/terms/{_safe_attr(term.id)}/edit{document_qs}"
        if is_edit and term is not None
        else f"/admin/workbench/glossary/terms/add{document_qs}"
    )
    legend = "Edit term" if is_edit else "Add term"
    source_value = _safe_attr(term.source) if term else ""
    target_value = _safe_attr(term.target) if term else ""
    notes_value = _safe_attr(term.notes) if term else ""
    type_value = term.type if term else "term"
    if type_value not in TERM_TYPES:
        type_value = "term"
    type_options = "".join(
        f'<option value="{_safe_attr(t)}"'
        + (" selected" if t == type_value else "")
        + f">{_safe_attr(t.capitalize())}</option>"
        for t in TERM_TYPES
    )
    panel_id = "wb-add-term-form" if not is_edit else "wb-edit-term-form"
    return f"""
<form id="{panel_id}" class="wb-term-form" method="post" action="{action}">
  <h3>{legend}</h3>
  <div class="wb-term-form__row">
    <label for="{panel_id}-source">Source</label>
    <input id="{panel_id}-source" name="source" required value="{source_value}">
  </div>
  <div class="wb-term-form__row">
    <label for="{panel_id}-target">Target</label>
    <input id="{panel_id}-target" name="target" required value="{target_value}">
  </div>
  <div class="wb-term-form__row">
    <label for="{panel_id}-type">Type</label>
    <select id="{panel_id}-type" name="type">{type_options}</select>
  </div>
  <div class="wb-term-form__row">
    <label for="{panel_id}-notes">Notes</label>
    <textarea id="{panel_id}-notes" name="notes" rows="2">{notes_value}</textarea>
  </div>
  <div class="wb-term-form__actions">
    <button type="submit" class="wb-button wb-button--primary">
      {"Save changes" if is_edit else "Add term"}
    </button>
    <a class="wb-button wb-button--secondary" href="/admin/workbench/glossary">
      Cancel
    </a>
    <input type="hidden" name="csrf_token" value="{_safe_attr(csrf_token)}">
  </div>
</form>
"""


# ---------------------------------------------------------------------------
# Term row
# ---------------------------------------------------------------------------


def _workbench_term_row(
    state: WorkbenchSessionState, term: Term, *, csrf_token: str
) -> str:
    locked = term.status == TermStatus.LOCKED
    is_conflict = term.status == TermStatus.CONFLICT
    row_actions_disabled = state.approval_state in (
        ApprovalState.STALE,
        ApprovalState.UNAVAILABLE,
    )
    # Per-row action affordances (packet §5.3 + §5.4).
    if locked:
        edit_title = WORKBENCH_COPY["locked_row_tooltip"]
        reject_title = WORKBENCH_COPY["locked_row_tooltip"]
        edit_disabled = True
        reject_disabled = True
    elif row_actions_disabled:
        edit_title = WORKBENCH_COPY["disabled_row_tooltip"]
        reject_title = WORKBENCH_COPY["disabled_row_tooltip"]
        edit_disabled = True
        reject_disabled = True
    else:
        edit_title = "Edit this term"
        reject_title = "Reject this term"
        edit_disabled = False
        reject_disabled = is_conflict  # conflict row keeps Reject disabled

    accept_disabled = row_actions_disabled or term.status in (
        TermStatus.APPROVED,
        TermStatus.LOCKED,
    )
    lock_disabled = row_actions_disabled or term.status != TermStatus.APPROVED
    unlock_disabled = row_actions_disabled or term.status != TermStatus.LOCKED
    selection_disabled = (
        row_actions_disabled or state.approval_state == ApprovalState.CONFLICT
    )

    def _attr(name: str, value: str) -> str:
        return f'{name}="{_safe_attr(value)}"'

    def _action(
        *,
        label: str,
        endpoint: str,
        disabled: bool,
        title: str,
        action: str,
    ) -> str:
        cls = "wb-button wb-button--secondary"
        attr_disabled = ' disabled aria-disabled="true"' if disabled else ""
        return (
            f'<form method="post" action="{endpoint}" '
            f'style="display:inline">'
            f'<button type="submit" class="{cls}"'
            f'{attr_disabled} title="{_safe_attr(title)}"'
            f' data-action="{_safe_attr(action)}">'
            f"{_safe_attr(label)}</button>"
            f'<input type="hidden" name="csrf_token" '
            f'value="{_safe_attr(csrf_token)}"></form>'
        )

    document_qs = f"?document={quote(state.document.document_id, safe='')}"
    edit_action = (
        '<button type="button" class="wb-button wb-button--secondary" '
        f'disabled aria-disabled="true" title="{_safe_attr(edit_title)}" '
        'data-action="edit">Edit</button>'
        if edit_disabled
        else (
            '<a class="wb-button wb-button--secondary" '
            f'href="/admin/workbench/glossary{document_qs}&amp;edit={_safe_attr(term.id)}" '  # noqa: E501
            f'title="{_safe_attr(edit_title)}" data-action="edit">Edit</a>'
        )
    )
    accept_a = _action(
        label="Accept",
        endpoint=f"/admin/workbench/glossary/terms/{term.id}/accept",
        disabled=accept_disabled,
        title="Accept this term as locally-approved",
        action="accept",
    )
    reject_a = _action(
        label="Reject",
        endpoint=f"/admin/workbench/glossary/terms/{term.id}/reject",
        disabled=reject_disabled,
        title=reject_title,
        action="reject",
    )
    lock_a = _action(
        label="Lock",
        endpoint=f"/admin/workbench/glossary/terms/{term.id}/lock",
        disabled=lock_disabled,
        title="Lock this approved term so it cannot drift",
        action="lock",
    )
    unlock_a = _action(
        label="Unlock",
        endpoint=f"/admin/workbench/glossary/terms/{term.id}/unlock",
        disabled=unlock_disabled,
        title="Unlock this term so it can be edited or rejected",
        action="unlock",
    )
    last_edited = _format_iso(term.last_edited_at)
    selection_disabled_attr = (
        ' disabled aria-disabled="true"' if selection_disabled else ""
    )
    selection_id = f"wb-term-select-{_safe_attr(term.id)}"
    return f"""
<article class="wb-term" id="wb-term-{_safe_attr(term.id)}"
  data-term-id="{_safe_attr(term.id)}"
  data-status="{_safe_attr(term.status.value)}"
  data-locked="{("true" if locked else "false")}">
  <div class="wb-term__col">
    <small>Source</small>
    <strong>{escape(term.source or "—")}</strong>
  </div>
  <div class="wb-term__col">
    <small>Target</small>
    <strong>{escape(term.target or "—")}</strong>
  </div>
  <div class="wb-term__col">
    <small>Type / status</small>
    <span>{escape(term.type.capitalize())}</span>
    {_workbench_status_pill(term.status)}
  </div>
  <div class="wb-term__actions">
    <label class="wb-term__selection" for="{selection_id}">
      <input id="{selection_id}" type="checkbox" name="selected_term_ids"
        value="{_safe_attr(term.id)}" form="wb-check-selected-form"
        data-term-id="{_safe_attr(term.id)}"{selection_disabled_attr}>
      Select term for local check
    </label>
    {edit_action}
    {accept_a}
    {reject_a}
    {lock_a}
    {unlock_a}
  </div>
  <details class="wb-term__details">
    <summary>Details</summary>
    <p>Notes: {escape(term.notes) or "—"}</p>
    <p>Last edited: <time datetime="{_safe_attr(last_edited)}">
      {_safe_attr(last_edited)}</time></p>
    <p>Signature: <code>{_safe_attr(term.signature)}</code></p>
  </details>
</article>
"""


def _filter_terms(terms: Iterable[Term], active_filter: str) -> list[Term]:
    rows = list(terms)
    if active_filter == "all":
        return rows
    if active_filter == "approved":
        return [t for t in rows if t.status in (TermStatus.APPROVED, TermStatus.LOCKED)]
    return [t for t in rows if t.status.value == active_filter]


def _workbench_glossary_observation(
    projection: WorkbenchGlossaryProjection | None,
) -> str:
    """Render only an injected projection's metadata-safe local shape."""
    if projection is None:
        return ""
    if projection.state == WorkbenchGlossaryProjectionState.FAIL_CLOSED:
        reason = _safe_attr(projection.reason_code or "unavailable")
        return f"""
<section class="wb-card" data-workbench-glossary-observation="fail-closed">
  <h3>Local glossary observation unavailable</h3>
  <p>State: fail closed. Reason: <code>{reason}</code>.</p>
</section>
"""
    return f"""
<section class="wb-card" data-workbench-glossary-observation="local-structural-ready">
  <h3>Local glossary structural observation</h3>
  <p>Selected: {projection.selected_entry_count};
    rendered: {projection.rendered_entry_count};
    omitted: {projection.omitted_entry_count}.</p>
</section>
"""


# ---------------------------------------------------------------------------
# Helper rail (packet §4.2)
# ---------------------------------------------------------------------------


def _workbench_helper_rail(
    state: WorkbenchSessionState,
) -> str:
    if state.health_snapshot.get("total", 0) == 0:
        # Packet §5.3 row "empty terms": helper rail hidden until first
        # term added.
        return ""
    health = state.health_snapshot
    state_label_map = {
        ApprovalState.READY: ("ready", "Glossary is ready"),
        ApprovalState.NOT_READY: ("not-ready", "Not ready"),
        ApprovalState.STALE: ("stale", "Document changed"),
        ApprovalState.UNAVAILABLE: ("unavailable", "Unavailable"),
        ApprovalState.CONFLICT: ("conflict", "Conflicts present"),
    }
    css_key, helper_label = state_label_map.get(
        state.approval_state, ("unavailable", "Unavailable")
    )
    helper_copy = _state_helper_copy(state.approval_state)
    next_action = _helper_next_action(state)
    return f"""
<aside class="wb-rail" aria-label="Workbench helper rail">
  <section class="wb-card wb-helper-rail__health-card">
    <h3><span class="wb-helper-rail__dot wb-helper-rail__dot--{css_key}"
      aria-hidden="true"></span>Glossary health</h3>
    <dl class="wb-helper-rail__health">
      <dt>Total</dt><dd>{int(health.get("total", 0))}</dd>
      <dt>Approved</dt><dd>{int(health.get("approved", 0))}</dd>
      <dt>Locked</dt><dd>{int(health.get("locked", 0))}</dd>
      <dt>Pending</dt><dd>{int(health.get("pending", 0))}</dd>
      <dt>Draft</dt><dd>{int(health.get("draft", 0))}</dd>
      <dt>Rejected</dt><dd>{int(health.get("rejected", 0))}</dd>
      <dt>Conflict</dt><dd>{int(health.get("conflict", 0))}</dd>
    </dl>
  </section>
  <section class="wb-card">
    <h3>{_safe_attr(helper_label)}</h3>
    <p>{_safe_attr(helper_copy)}</p>
    {_helper_next_action_button(next_action)}
  </section>
  <details class="wb-card wb-helper-rail__about">
    <summary>About this slice</summary>
    <p>{_safe_attr(WORKBENCH_COPY["about_this_slice"])}</p>
  </details>
</aside>
"""


def _state_helper_copy(state: ApprovalState) -> str:
    return {
        ApprovalState.READY: WORKBENCH_COPY["ready_helper"],
        ApprovalState.NOT_READY: WORKBENCH_COPY["not_ready_helper"],
        ApprovalState.STALE: WORKBENCH_COPY["stale_top_strip"],
        ApprovalState.UNAVAILABLE: WORKBENCH_COPY["unavailable_inline"],
        ApprovalState.CONFLICT: WORKBENCH_COPY["conflict_helper"],
    }.get(state, WORKBENCH_COPY["not_ready_helper"])


def _helper_next_action(state: WorkbenchSessionState) -> tuple[str, str, str]:
    """Return (label, href, variant) for the helper-rail primary CTA."""
    if state.approval_state == ApprovalState.STALE:
        return ("Reopen latest document", "/admin/workbench-entry", "primary")
    if state.approval_state == ApprovalState.UNAVAILABLE:
        return (
            "Retry",
            f"/admin/workbench/glossary?document={state.document.document_id}",
            "secondary",
        )
    if state.approval_state == ApprovalState.CONFLICT:
        # Deep-link to first conflict term id if any.
        first_conflict = next(
            (t for t in state.terms.values() if t.status == TermStatus.CONFLICT),
            None,
        )
        if first_conflict is not None:
            return (
                "Go to first conflict",
                f"/admin/workbench/glossary?document={state.document.document_id}#wb-term-{first_conflict.id}",
                "primary",
            )
        return ("Add term", "/admin/workbench/glossary", "primary")
    if state.approval_state == ApprovalState.READY:
        has_approved = state.health_snapshot.get("approved", 0) > 0
        if has_approved:
            return ("Lock all approved", "/admin/workbench/glossary", "primary")
        return ("Add term", "/admin/workbench/glossary", "primary")
    return ("Add term", "/admin/workbench/glossary", "primary")


def _helper_next_action_button(action: tuple[str, str, str]) -> str:
    label, href, variant = action
    cls = (
        "wb-button wb-button--primary"
        if variant == "primary"
        else "wb-button wb-button--secondary"
    )
    return f'<a class="{cls}" href="{_safe_attr(href)}">{_safe_attr(label)}</a>'


# ---------------------------------------------------------------------------
# Page wrapper + screens (packet §4)
# ---------------------------------------------------------------------------


def _workbench_page(
    *,
    title: str,
    state: WorkbenchSessionState,
    body: str,
    active: str = "glossary",
    csrf_token: str | None = None,
    not_wired_after_post: bool = False,
) -> str:
    safe_title = _safe_attr(title)
    safe_doc_id = _safe_attr(state.document.document_id or "")
    not_wired_block = ""
    if not_wired_after_post:
        not_wired_block = (
            f'<div class="wb-strip wb-strip--not-wired" '
            f'role="alert" data-not-wired-notice="true">'
            f"{_safe_attr(WORKBENCH_COPY['not_wired_after_post'])}"
            f"</div>"
        )
    stale_top_strip = ""
    if state.approval_state == ApprovalState.STALE:
        stale_top_strip = (
            f'<div class="wb-strip wb-strip--stale" '
            f'role="alert" data-stale-top-strip="true">'
            f"{_safe_attr(WORKBENCH_COPY['stale_top_strip'])}"
            f"</div>"
        )
    unavailable_strip = ""
    if state.approval_state == ApprovalState.UNAVAILABLE:
        unavailable_strip = (
            f'<div class="wb-strip wb-strip--unavailable" '
            f'role="alert" data-unavailable-strip="true">'
            f"{_safe_attr(WORKBENCH_COPY['unavailable_inline'])}"
            f"</div>"
        )
    header = _workbench_header(
        document_id=state.document.document_id,
        ephemeral_session_id=state.session_id,
    )
    nav = _workbench_nav(active, state.document.document_id or None)
    helper_rail = _workbench_helper_rail(state)
    csrf_token = csrf_token or ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} · FolioLoom Workbench</title>
  <style>{_workbench_css()}</style>
</head>
<body class="workbench" data-csrf-token="{_safe_attr(csrf_token)}"
  data-document-id="{safe_doc_id}">
  {header}
  <div class="wb-shell">
    {nav}
    <main class="wb-main" aria-label="Workbench main">
      {stale_top_strip}
      {unavailable_strip}
      {not_wired_block}
      {body}
    </main>
    {helper_rail}
  </div>
</body>
</html>"""


def _filter_chip_from_request(filter_value: str | None) -> str:
    return (
        filter_value
        if filter_value in {"all", "approved", "locked", "pending"}
        else "all"
    )


def render_workbench_select(*, csrf_token: str, injected: bool = False) -> str:
    """Render the Select screen (packet §4.1).

    Args:
        injected: ``True`` when a document id was supplied but rejected.
            Shows the "injected-but-invalid" copy.
    """
    if injected:
        copy = WORKBENCH_COPY["injected_but_invalid"]
        primary_href = "/admin/overview"
        primary_label = "Back to Admin"
    else:
        copy = WORKBENCH_COPY["not_injected"]
        primary_href = "/admin"
        primary_label = "Open Admin"
    body = f"""
<section class="wb-empty" role="region" aria-label="Workbench document picker">
  <p>{_safe_attr(copy)}</p>
  <a class="wb-button wb-button--primary" href="{_safe_attr(primary_href)}">
    {_safe_attr(primary_label)}
  </a>
</section>
"""
    placeholder_state = empty_workbench_session()
    return _workbench_page(
        title="Select document",
        state=placeholder_state,
        body=body,
        active="select",
        csrf_token=csrf_token,
    )


def render_workbench_glossary(
    *,
    state: WorkbenchSessionState,
    csrf_token: str,
    show_add_form: bool = False,
    edit_term_id: str | None = None,
    active_filter: str = "all",
    not_wired_after_post: bool = False,
    glossary_projection: WorkbenchGlossaryProjection | None = None,
    local_check_block_reason: str | None = None,
) -> str:
    """Render the main Glossary screen with an optional local observation."""
    rows = _filter_terms(state.terms.values(), active_filter)
    document_strip = _workbench_document_strip(state)
    toolbar = _workbench_toolbar(
        state, csrf_token=csrf_token, active_filter=active_filter
    )
    if not rows:
        term_list_html = (
            f'<div class="wb-empty">'
            f"<p>{_safe_attr(WORKBENCH_COPY['glossary_empty'])}</p>"
            f"</div>"
        )
    else:
        term_list_html = (
            '<div class="wb-term-list">'
            + "".join(
                _workbench_term_row(state, t, csrf_token=csrf_token) for t in rows
            )
            + "</div>"
        )
    add_form = ""
    if edit_term_id in state.terms:
        add_form = _workbench_term_form(
            mode="edit",
            csrf_token=csrf_token,
            document_id=state.document.document_id,
            term=state.terms[edit_term_id],
        )
    elif show_add_form:
        add_form = _workbench_term_form(
            mode="add",
            csrf_token=csrf_token,
            document_id=state.document.document_id,
            term=None,
        )
    body = (
        document_strip
        + (
            '<section class="wb-card" '  # noqa: E501
            'data-workbench-glossary-observation="fail-closed">'
            "<h3>Local glossary check blocked</h3>"
            f"<p>State: fail closed. Reason: "
            f"<code>{_safe_attr(local_check_block_reason)}</code>.</p>"
            "</section>"
            if local_check_block_reason
            else ""
        )
        + _workbench_glossary_observation(glossary_projection)
        + toolbar
        + add_form
        + term_list_html
    )
    return _workbench_page(
        title="Glossary",
        state=state,
        body=body,
        active="glossary",
        csrf_token=csrf_token,
        not_wired_after_post=not_wired_after_post,
    )


def render_workbench_recovery(
    *,
    reason: str,
    csrf_token: str,
    document_id: str = "",
) -> str:
    """Render the Recovery screen (packet §4.3).

    Reasons: ``stale``, ``unavailable``, ``not-wired``, ``invalid``.
    """
    copy_map = {
        "stale": WORKBENCH_COPY["recovery_stale"],
        "unavailable": WORKBENCH_COPY["recovery_unavailable"],
        "not-wired": WORKBENCH_COPY["recovery_not_wired"],
        "invalid": WORKBENCH_COPY["recovery_invalid"],
    }
    action_map = {
        "stale": ("Reopen latest document", "/admin/workbench-entry"),
        "unavailable": (
            "Retry",
            f"/admin/workbench/glossary?document={_safe_attr(document_id)}",
        ),
        "not-wired": ("Back to Glossary", "/admin/workbench/glossary"),
        "invalid": ("Back to Admin", "/admin/overview"),
    }
    copy = copy_map.get(reason, WORKBENCH_COPY["recovery_invalid"])
    label, href = action_map.get(reason, ("Back to Admin", "/admin/overview"))
    body = f"""
<section class="wb-recovery" role="region" aria-label="Workbench recovery">
  <div class="wb-recovery__panel">
    <h2>{_safe_attr(label)}</h2>
    <p>{_safe_attr(copy)}</p>
    <a class="wb-button wb-button--primary" href="{_safe_attr(href)}">
      {_safe_attr(label)}
    </a>
    <input type="hidden" name="csrf_token" value="{_safe_attr(csrf_token)}">
  </div>
</section>
"""
    placeholder_state = empty_workbench_session()
    return _workbench_page(
        title="Recovery",
        state=placeholder_state,
        body=body,
        active="recovery",
        csrf_token=csrf_token,
    )


def render_workbench_future(
    *,
    stage: str,
    csrf_token: str,
) -> str:
    """Render the Future / placeholder screen (packet §4.4)."""
    title, copy = _stage_meta(stage)
    body = f"""
<section class="wb-empty" role="region" aria-label="Workbench future placeholder">
  <p>{_safe_attr(copy)}</p>
  <a class="wb-button wb-button--secondary" href="/admin/workbench/glossary">
    Back to Glossary
  </a>
</section>
"""
    placeholder_state = empty_workbench_session()
    return _workbench_page(
        title=title,
        state=placeholder_state,
        body=body,
        active="future",
        csrf_token=csrf_token,
    )


def render_workbench_root_redirect(
    *,
    document_id: str | None,
    session: object,
) -> str:
    """Decide which screen the ``/workbench`` root should redirect to.

    Returns the redirect target string. Kept here so the controller can
    stay a thin shell.
    """
    _ = session  # placeholder_state is unused here
    if not document_id:
        return "/admin/workbench/select"
    # We cannot validate the document id from this slice; treat unknown
    # ids as recovery (packet §3.1 root rule).
    if not document_id.strip():
        return "/admin/workbench/recovery?reason=invalid"
    return f"/admin/workbench/glossary?document={_safe_attr(document_id)}"


__all__ = [
    "WORKBENCH_COPY",
    "WORKBENCH_PLACEHOLDER_STAGES",
    "render_workbench_future",
    "render_workbench_glossary",
    "render_workbench_recovery",
    "render_workbench_root_redirect",
    "render_workbench_select",
]
