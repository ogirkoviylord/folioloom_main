from __future__ import annotations

import html
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from translator_service.format_adapters.contracts import FormatAdapterPlan
from translator_service.format_adapters.txt import plan_txt_translation

READER_STATUS_DONE = "done"
READER_STATUS_MISSING = "missing"
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ReaderBlock:
    sequence: int
    source_block_id: str
    kind: str
    group_id: str | None
    metadata: tuple[tuple[str, str], ...]
    source_text: str
    translated_text: str | None
    status: str


@dataclass(frozen=True)
class ReaderSection:
    id: str
    title: str
    source_file_name: str | None
    blocks: tuple[ReaderBlock, ...]


@dataclass(frozen=True)
class ReaderDocument:
    document_format: str
    adapter_version: str
    source_name: str
    generated_at: str
    sections: tuple[ReaderSection, ...]


def build_reader_document(
    *,
    plan: FormatAdapterPlan,
    translated_by_block_id: Mapping[str, str] | None = None,
    source_name: str = "Document",
    generated_at: datetime | None = None,
) -> ReaderDocument:
    translations = translated_by_block_id or {}
    blocks: list[ReaderBlock] = []
    for unit in plan.units:
        for block in unit.blocks:
            translated_text = translations.get(block.source_block_id)
            status = (
                READER_STATUS_DONE
                if translated_text is not None
                else READER_STATUS_MISSING
            )
            blocks.append(
                ReaderBlock(
                    sequence=len(blocks) + 1,
                    source_block_id=block.source_block_id,
                    kind=block.kind.value,
                    group_id=block.group_id,
                    metadata=block.metadata,
                    source_text=block.text,
                    translated_text=translated_text,
                    status=status,
                )
            )
    timestamp = generated_at or datetime.now(UTC)
    return ReaderDocument(
        document_format=plan.document_format.value,
        adapter_version=plan.adapter_version,
        source_name=source_name,
        generated_at=timestamp.isoformat(),
        sections=(
            ReaderSection(
                id="document",
                title="Document",
                source_file_name=None,
                blocks=tuple(blocks),
            ),
        ),
    )


def build_txt_reader_document(
    *,
    content: bytes,
    translated_by_block_id: Mapping[str, str] | None = None,
    source_name: str = "Document",
    max_fragment_chars: int = 5_000,
    generated_at: datetime | None = None,
) -> ReaderDocument:
    plan = plan_txt_translation(
        content=content,
        max_fragment_chars=max_fragment_chars,
    )
    return build_reader_document(
        plan=plan,
        translated_by_block_id=translated_by_block_id,
        source_name=source_name,
        generated_at=generated_at,
    )


def render_reader_html(document: ReaderDocument) -> str:
    section_html = "\n".join(_render_section(section) for section in document.sections)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(document.source_name)} before/after reader</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --ink: #1e2428;
      --muted: #66727a;
      --line: #d8dedf;
      --done: #0f6b4f;
      --missing: #9a5b00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 20px 24px 14px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 20px;
      font-weight: 650;
      letter-spacing: 0;
    }}
    .meta {{
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
    }}
    main {{ padding: 18px 24px 28px; }}
    h2 {{ font-size: 16px; margin: 0 0 12px; }}
    .block {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin: 0 0 12px;
      overflow: hidden;
    }}
    .block-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }}
    .status-done {{ color: var(--done); font-weight: 650; }}
    .status-missing {{ color: var(--missing); font-weight: 650; }}
    .columns {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      min-height: 96px;
    }}
    .pane {{ padding: 12px; }}
    .pane + .pane {{ border-left: 1px solid var(--line); }}
    .pane-title {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      margin-bottom: 6px;
      text-transform: uppercase;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }}
    .metadata {{
      border-top: 1px solid var(--line);
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      gap: 6px 12px;
      padding: 8px 10px;
      font-size: 12px;
    }}
    @media (max-width: 760px) {{
      .columns {{ grid-template-columns: 1fr; }}
      .pane + .pane {{
        border-left: 0;
        border-top: 1px solid var(--line);
      }}
      main, header {{ padding-left: 14px; padding-right: 14px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_escape(document.source_name)}</h1>
    <div class="meta">
      <span>Format: {_escape(document.document_format)}</span>
      <span>Adapter: {_escape(document.adapter_version)}</span>
      <span>Generated: {_escape(document.generated_at)}</span>
    </div>
  </header>
  <main>
{section_html}
  </main>
</body>
</html>
"""


def load_translation_mapping(path: Path) -> dict[str, str]:
    reject_runtime_var_path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Translation mapping JSON must be an object")
    mapping: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Translation mapping keys and values must be strings")
        mapping[key] = value
    return mapping


def generate_txt_reader_html_from_path(
    *,
    source_path: Path,
    translated_by_block_id: Mapping[str, str] | None = None,
    max_fragment_chars: int = 5_000,
    generated_at: datetime | None = None,
) -> str:
    reject_runtime_var_path(source_path)
    document = build_txt_reader_document(
        content=source_path.read_bytes(),
        translated_by_block_id=translated_by_block_id,
        source_name=source_path.name,
        max_fragment_chars=max_fragment_chars,
        generated_at=generated_at,
    )
    return render_reader_html(document)


def _render_section(section: ReaderSection) -> str:
    blocks_html = "\n".join(_render_block(block) for block in section.blocks)
    return f"""    <section>
      <h2>{_escape(section.title)}</h2>
{blocks_html}
    </section>"""


def _render_block(block: ReaderBlock) -> str:
    block_id = _escape(block.source_block_id)
    block_kind = _escape(block.kind)
    translated = block.translated_text if block.translated_text is not None else ""
    metadata = "".join(
        f"<span>{_escape(key)}: {_escape(value)}</span>"
        for key, value in block.metadata
        if value
    )
    if block.group_id:
        metadata = f"<span>group_id: {_escape(block.group_id)}</span>{metadata}"
    status_class = f"status-{_escape(block.status)}"
    return f"""      <article class="block" data-source-block-id="{block_id}">
        <div class="block-head">
          <span>#{block.sequence} {block_id} · {block_kind}</span>
          <span class="{status_class}">{_escape(block.status)}</span>
        </div>
        <div class="columns">
          <div class="pane">
            <div class="pane-title">Source</div>
            <pre>{_escape(block.source_text)}</pre>
          </div>
          <div class="pane">
            <div class="pane-title">Translation</div>
            <pre>{_escape(translated)}</pre>
          </div>
        </div>
        <div class="metadata">{metadata}</div>
      </article>"""


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def reject_runtime_var_path(path: Path) -> None:
    resolved = path.resolve()
    runtime_var = (_REPO_ROOT / "var").resolve()
    if resolved == runtime_var or resolved.is_relative_to(runtime_var):
        raise ValueError("Internal reader refuses runtime var/ paths")
