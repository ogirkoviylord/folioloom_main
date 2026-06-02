from __future__ import annotations

import html
import json
import re
from base64 import b64encode
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from translator_service.format_adapters.contracts import FormatAdapterPlan
from translator_service.format_adapters.docx import plan_docx_translation
from translator_service.format_adapters.epub import (
    assemble_epub_content_from_block_translations,
    plan_epub_translation,
)
from translator_service.format_adapters.txt import plan_txt_translation

READER_STATUS_DONE = "done"
READER_STATUS_MISSING = "missing"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_EPUB_TEXT_EXTENSIONS = (".xhtml", ".html", ".htm")
_EPUB_SAFE_IMAGE_MEDIA_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_EPUB_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", flags=re.IGNORECASE)
_EPUB_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", flags=re.IGNORECASE)
_EPUB_ATTR_RE = re.compile(
    r"""(?P<name>[\w:.-]+)\s*=\s*(?P<quote>["'])(?P<value>.*?)(?P=quote)""",
    flags=re.DOTALL,
)


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


@dataclass(frozen=True)
class EpubChapterPreview:
    sequence: int
    file_name: str
    source_xhtml: str
    translated_xhtml: str


def build_reader_document(
    *,
    plan: FormatAdapterPlan,
    translated_by_block_id: Mapping[str, str] | None = None,
    source_name: str = "Document",
    generated_at: datetime | None = None,
) -> ReaderDocument:
    translations = translated_by_block_id or {}
    sections: list[ReaderSection] = []
    section_blocks: list[ReaderBlock] = []
    current_source_file_name: str | None = None
    current_section_title = "Document"
    sequence = 0

    def flush_section() -> None:
        nonlocal section_blocks, current_source_file_name, current_section_title
        if not section_blocks:
            return
        sections.append(
            ReaderSection(
                id=f"section-{len(sections) + 1}",
                title=current_section_title,
                source_file_name=current_source_file_name,
                blocks=tuple(section_blocks),
            )
        )
        section_blocks = []

    for unit in plan.units:
        for block in unit.blocks:
            source_file_name = _metadata_value(block.metadata, "file_name")
            section_title = source_file_name or "Document"
            if section_blocks and source_file_name != current_source_file_name:
                flush_section()
            current_source_file_name = source_file_name
            current_section_title = section_title
            sequence += 1
            translated_text = translations.get(block.source_block_id)
            status = (
                READER_STATUS_DONE
                if translated_text is not None
                else READER_STATUS_MISSING
            )
            section_blocks.append(
                ReaderBlock(
                    sequence=sequence,
                    source_block_id=block.source_block_id,
                    kind=block.kind.value,
                    group_id=block.group_id,
                    metadata=block.metadata,
                    source_text=block.text,
                    translated_text=translated_text,
                    status=status,
                )
            )
    flush_section()
    if not sections:
        sections.append(
            ReaderSection(
                id="section-1",
                title="Document",
                source_file_name=None,
                blocks=(),
            )
        )
    timestamp = generated_at or datetime.now(UTC)
    return ReaderDocument(
        document_format=plan.document_format.value,
        adapter_version=plan.adapter_version,
        source_name=source_name,
        generated_at=timestamp.isoformat(),
        sections=tuple(sections),
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


def build_epub_reader_document(
    *,
    content: bytes,
    translated_by_block_id: Mapping[str, str] | None = None,
    source_name: str = "Document",
    max_fragment_chars: int = 5_000,
    generated_at: datetime | None = None,
) -> ReaderDocument:
    plan = plan_epub_translation(
        content=content,
        max_fragment_chars=max_fragment_chars,
    )
    return build_reader_document(
        plan=plan,
        translated_by_block_id=translated_by_block_id,
        source_name=source_name,
        generated_at=generated_at,
    )


def build_docx_reader_document(
    *,
    content: bytes,
    translated_by_block_id: Mapping[str, str] | None = None,
    source_name: str = "Document",
    max_fragment_chars: int = 5_000,
    generated_at: datetime | None = None,
) -> ReaderDocument:
    plan = plan_docx_translation(
        content=content,
        max_fragment_chars=max_fragment_chars,
    )
    return build_reader_document(
        plan=plan,
        translated_by_block_id=translated_by_block_id,
        source_name=source_name,
        generated_at=generated_at,
    )


def build_epub_chapter_previews(
    *,
    content: bytes,
    document: ReaderDocument,
    translated_by_block_id: Mapping[str, str] | None = None,
) -> tuple[EpubChapterPreview, ...]:
    translations = dict(translated_by_block_id or {})
    translated_content = assemble_epub_content_from_block_translations(
        source_content=content,
        translated_by_block_id=translations,
    )
    source_files = _ordered_epub_text_files(document)
    previews: list[EpubChapterPreview] = []
    with ZipFile(BytesIO(content)) as source_epub, ZipFile(
        BytesIO(translated_content)
    ) as translated_epub:
        for sequence, file_name in enumerate(source_files, start=1):
            previews.append(
                EpubChapterPreview(
                    sequence=sequence,
                    file_name=file_name,
                    source_xhtml=_prepare_epub_preview_xhtml(
                        epub=source_epub,
                        file_name=file_name,
                    ),
                    translated_xhtml=_prepare_epub_preview_xhtml(
                        epub=translated_epub,
                        file_name=file_name,
                    ),
                )
            )
    return tuple(previews)


def render_reader_html(document: ReaderDocument) -> str:
    section_html = "\n".join(_render_section(section) for section in document.sections)
    return _render_reader_page(document=document, body_html=section_html)


def render_epub_reader_html(
    *,
    document: ReaderDocument,
    chapter_previews: tuple[EpubChapterPreview, ...],
) -> str:
    preview_html = "\n".join(
        _render_epub_chapter_preview(preview) for preview in chapter_previews
    )
    block_report_html = "\n".join(
        _render_section(section) for section in document.sections
    )
    return _render_reader_page(
        document=document,
        body_html=f"""    <section class="chapter-previews">
      <h2>Chapter previews</h2>
{preview_html}
    </section>
    <section class="block-report">
      <h2>Block report</h2>
{block_report_html}
    </section>""",
        extra_css="""
    .chapter-preview {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin: 0 0 16px;
      overflow: hidden;
    }
    .chapter-head {
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      padding: 8px 10px;
    }
    .preview-columns {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      min-height: 320px;
    }
    .preview-pane { padding: 10px; }
    .preview-pane + .preview-pane { border-left: 1px solid var(--line); }
    .preview-frame {
      background: #ffffff;
      border: 1px solid var(--line);
      height: 320px;
      width: 100%;
    }
    @media (max-width: 760px) {
      .preview-columns { grid-template-columns: 1fr; }
      .preview-pane + .preview-pane {
        border-left: 0;
        border-top: 1px solid var(--line);
      }
    }
""",
    )


def render_docx_reader_html(document: ReaderDocument) -> str:
    structure_html = "\n".join(
        _render_docx_structure_section(section) for section in document.sections
    )
    block_report_html = "\n".join(
        _render_section(section) for section in document.sections
    )
    return _render_reader_page(
        document=document,
        body_html=f"""    <section class="docx-structure-preview">
      <h2>DOCX structure preview</h2>
{structure_html}
    </section>
    <section class="block-report">
      <h2>Block report</h2>
{block_report_html}
    </section>""",
        extra_css="""
    .docx-structure-preview {
      margin-bottom: 22px;
    }
    .docx-structure-section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin: 0 0 16px;
      overflow: hidden;
    }
    .docx-section-head {
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      padding: 8px 10px;
    }
    .docx-structure-item + .docx-structure-item {
      border-top: 1px solid var(--line);
    }
    .docx-structure-meta {
      align-items: center;
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      font-size: 12px;
      gap: 8px 12px;
      padding: 8px 10px 0;
    }
    .docx-preview-pane {
      padding: 10px;
    }
    .docx-preview-pane + .docx-preview-pane {
      border-left: 1px solid var(--line);
    }
    .docx-paragraph {
      margin: 0 0 10px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .docx-heading {
      font-size: 18px;
      font-weight: 650;
    }
    .docx-list-item {
      padding-left: 18px;
      position: relative;
    }
    .docx-list-item::before {
      content: "*";
      left: 4px;
      position: absolute;
    }
    .docx-table-like {
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
    }
    .docx-table-row {
      padding: 7px 8px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .docx-table-row + .docx-table-row {
      border-top: 1px solid var(--line);
    }
    @media (max-width: 760px) {
      .docx-preview-pane + .docx-preview-pane {
        border-left: 0;
        border-top: 1px solid var(--line);
      }
    }
""",
    )


def _render_reader_page(
    *,
    document: ReaderDocument,
    body_html: str,
    extra_css: str = "",
) -> str:
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
      --mixed: #5a5f69;
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
    .status-mixed {{ color: var(--mixed); font-weight: 650; }}
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
{extra_css}
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
{body_html}
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


def generate_epub_reader_html_from_path(
    *,
    source_path: Path,
    translated_by_block_id: Mapping[str, str] | None = None,
    max_fragment_chars: int = 5_000,
    generated_at: datetime | None = None,
) -> str:
    reject_runtime_var_path(source_path)
    content = source_path.read_bytes()
    document = build_epub_reader_document(
        content=content,
        translated_by_block_id=translated_by_block_id,
        source_name=source_path.name,
        max_fragment_chars=max_fragment_chars,
        generated_at=generated_at,
    )
    chapter_previews = build_epub_chapter_previews(
        content=content,
        document=document,
        translated_by_block_id=translated_by_block_id,
    )
    return render_epub_reader_html(
        document=document,
        chapter_previews=chapter_previews,
    )


def generate_docx_reader_html_from_path(
    *,
    source_path: Path,
    translated_by_block_id: Mapping[str, str] | None = None,
    max_fragment_chars: int = 5_000,
    generated_at: datetime | None = None,
) -> str:
    reject_runtime_var_path(source_path)
    document = build_docx_reader_document(
        content=source_path.read_bytes(),
        translated_by_block_id=translated_by_block_id,
        source_name=source_path.name,
        max_fragment_chars=max_fragment_chars,
        generated_at=generated_at,
    )
    return render_docx_reader_html(document)


def _render_epub_chapter_preview(preview: EpubChapterPreview) -> str:
    file_name = _escape(preview.file_name)
    source_srcdoc = _escape(preview.source_xhtml)
    translated_srcdoc = _escape(preview.translated_xhtml)
    return f"""      <article class="chapter-preview" data-file-name="{file_name}">
        <div class="chapter-head">#{preview.sequence} {file_name}</div>
        <div class="preview-columns">
          <div class="preview-pane">
            <div class="pane-title">Source XHTML</div>
            <iframe
              class="preview-frame"
              sandbox=""
              referrerpolicy="no-referrer"
              srcdoc="{source_srcdoc}"
            ></iframe>
          </div>
          <div class="preview-pane">
            <div class="pane-title">Translated XHTML</div>
            <iframe
              class="preview-frame"
              sandbox=""
              referrerpolicy="no-referrer"
              srcdoc="{translated_srcdoc}"
            ></iframe>
          </div>
        </div>
      </article>"""


def _render_docx_structure_section(section: ReaderSection) -> str:
    items_html = "\n".join(
        _render_docx_structure_item(blocks)
        for blocks in _docx_structure_block_groups(section.blocks)
    )
    return f"""      <article class="docx-structure-section">
        <div class="docx-section-head">{_escape(section.title)}</div>
{items_html}
      </article>"""


def _docx_structure_block_groups(
    blocks: tuple[ReaderBlock, ...],
) -> tuple[tuple[ReaderBlock, ...], ...]:
    groups: list[tuple[ReaderBlock, ...]] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.kind in {"list", "table"} and block.group_id:
            end = index + 1
            while (
                end < len(blocks)
                and blocks[end].kind == block.kind
                and blocks[end].group_id == block.group_id
            ):
                end += 1
            groups.append(tuple(blocks[index:end]))
            index = end
            continue
        groups.append((block,))
        index += 1
    return tuple(groups)


def _render_docx_structure_item(blocks: tuple[ReaderBlock, ...]) -> str:
    first = blocks[0]
    block_ids = ", ".join(block.source_block_id for block in blocks)
    sequence_label = (
        f"#{first.sequence}"
        if len(blocks) == 1
        else f"#{first.sequence}-#{blocks[-1].sequence}"
    )
    group_label = (
        f"<span>group_id: {_escape(first.group_id)}</span>" if first.group_id else ""
    )
    status = _docx_structure_status(blocks)
    escaped_block_ids = _escape(block_ids)
    return f"""        <div class="docx-structure-item"
          data-source-block-id="{escaped_block_ids}">
          <div class="docx-structure-meta">
            <span>{_escape(sequence_label)}</span>
            <span>{_escape(first.kind)}</span>
            {group_label}
            <span class="status-{_escape(status)}">{_escape(status)}</span>
          </div>
          <div class="columns">
            <div class="docx-preview-pane">
              <div class="pane-title">Source</div>
{_render_docx_structure_content(blocks=blocks, translated=False)}
            </div>
            <div class="docx-preview-pane">
              <div class="pane-title">Translation</div>
{_render_docx_structure_content(blocks=blocks, translated=True)}
            </div>
          </div>
        </div>"""


def _docx_structure_status(blocks: tuple[ReaderBlock, ...]) -> str:
    statuses = {block.status for block in blocks}
    if statuses == {READER_STATUS_DONE}:
        return READER_STATUS_DONE
    if statuses == {READER_STATUS_MISSING}:
        return READER_STATUS_MISSING
    return "mixed"


def _render_docx_structure_content(
    *,
    blocks: tuple[ReaderBlock, ...],
    translated: bool,
) -> str:
    kind = blocks[0].kind
    if kind == "table":
        rows = "\n".join(
            "                "
            f'<div class="docx-table-row">'
            f"{_escape(_docx_preview_text(block, translated=translated))}</div>"
            for block in blocks
        )
        return f"""              <div class="docx-table-like">
{rows}
              </div>"""

    paragraphs = "\n".join(
        _render_docx_paragraph_preview(block=block, translated=translated)
        for block in blocks
    )
    return f"""              <div class="docx-flow">
{paragraphs}
              </div>"""


def _render_docx_paragraph_preview(*, block: ReaderBlock, translated: bool) -> str:
    classes = ["docx-paragraph"]
    if block.kind == "heading":
        classes.append("docx-heading")
    if block.kind == "list":
        classes.append("docx-list-item")
    return (
        f'                <div class="{" ".join(classes)}">'
        f"{_escape(_docx_preview_text(block, translated=translated))}</div>"
    )


def _docx_preview_text(block: ReaderBlock, *, translated: bool) -> str:
    if not translated:
        return block.source_text
    if block.translated_text is not None:
        return block.translated_text
    return "[missing translation]"


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


def _ordered_epub_text_files(document: ReaderDocument) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for section in document.sections:
        file_name = section.source_file_name
        if (
            file_name is not None
            and file_name.lower().endswith(_EPUB_TEXT_EXTENSIONS)
            and file_name not in seen
        ):
            ordered.append(file_name)
            seen.add(file_name)
    return tuple(ordered)


def _prepare_epub_preview_xhtml(*, epub: ZipFile, file_name: str) -> str:
    xhtml = _read_zip_text(epub, file_name)
    xhtml = _inline_epub_stylesheets(epub=epub, file_name=file_name, xhtml=xhtml)
    xhtml = _inline_epub_raster_images(epub=epub, file_name=file_name, xhtml=xhtml)
    return _inject_epub_preview_csp(xhtml)


def _inline_epub_stylesheets(*, epub: ZipFile, file_name: str, xhtml: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = _html_tag_attrs(tag)
        if attrs.get("rel", "").lower() != "stylesheet":
            return tag
        href = attrs.get("href")
        if not href:
            return tag
        resource_name = _resolve_epub_resource_name(
            file_name=file_name,
            reference=href,
            epub=epub,
        )
        if resource_name is None:
            return tag
        css = _read_zip_text(epub, resource_name)
        return f"<style>{_safe_style_text(css)}</style>"

    return _EPUB_LINK_TAG_RE.sub(replace, xhtml)


def _inline_epub_raster_images(*, epub: ZipFile, file_name: str, xhtml: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = _html_tag_attrs(tag)
        src = attrs.get("src")
        if not src:
            return tag
        resource_name = _resolve_epub_resource_name(
            file_name=file_name,
            reference=src,
            epub=epub,
        )
        if resource_name is None:
            return tag
        media_type = _safe_epub_image_media_type(resource_name)
        if media_type is None:
            return tag
        encoded = b64encode(epub.read(resource_name)).decode("ascii")
        data_uri = f"data:{media_type};base64,{encoded}"
        return _replace_html_attr(tag=tag, name="src", value=data_uri)

    return _EPUB_IMG_TAG_RE.sub(replace, xhtml)


def _inject_epub_preview_csp(xhtml: str) -> str:
    csp = (
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src &#39;none&#39;; img-src data:; '
        'style-src &#39;unsafe-inline&#39;">'
    )
    head_match = re.search(r"<head\b[^>]*>", xhtml, flags=re.IGNORECASE)
    if head_match is None:
        return f"{csp}\n{xhtml}"
    return f"{xhtml[: head_match.end()]}{csp}{xhtml[head_match.end():]}"


def _read_zip_text(epub: ZipFile, file_name: str) -> str:
    return epub.read(file_name).decode("utf-8", errors="replace")


def _html_tag_attrs(tag: str) -> dict[str, str]:
    return {
        match.group("name").lower(): html.unescape(match.group("value"))
        for match in _EPUB_ATTR_RE.finditer(tag)
    }


def _replace_html_attr(*, tag: str, name: str, value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group("name").lower() != name.lower():
            return match.group(0)
        quote = match.group("quote")
        return f'{match.group("name")}={quote}{_escape(value)}{quote}'

    return _EPUB_ATTR_RE.sub(replace, tag)


def _safe_style_text(css: str) -> str:
    return css.replace("</", "<\\/")


def _resolve_epub_resource_name(
    *,
    file_name: str,
    reference: str,
    epub: ZipFile,
) -> str | None:
    if _is_external_epub_reference(reference):
        return None
    resource_reference = reference.split("#", 1)[0].split("?", 1)[0]
    if not resource_reference:
        return None
    base_path = PurePosixPath(file_name).parent
    candidate = _normalize_epub_resource_name(str(base_path / resource_reference))
    if candidate in epub.namelist():
        return candidate
    fallback = _normalize_epub_resource_name(resource_reference)
    if fallback in epub.namelist():
        return fallback
    return None


def _normalize_epub_resource_name(value: str) -> str:
    parts: list[str] = []
    for part in PurePosixPath(value).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _is_external_epub_reference(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        lowered.startswith("//")
        or lowered.startswith("http:")
        or lowered.startswith("https:")
        or lowered.startswith("data:")
        or lowered.startswith("javascript:")
        or lowered.startswith("mailto:")
    )


def _safe_epub_image_media_type(file_name: str) -> str | None:
    return _EPUB_SAFE_IMAGE_MEDIA_TYPES.get(PurePosixPath(file_name).suffix.lower())


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _metadata_value(metadata: tuple[tuple[str, str], ...], key: str) -> str | None:
    for metadata_key, value in metadata:
        if metadata_key == key and value:
            return value
    return None


def reject_runtime_var_path(path: Path) -> None:
    resolved = path.resolve()
    runtime_var = (_REPO_ROOT / "var").resolve()
    if resolved == runtime_var or resolved.is_relative_to(runtime_var):
        raise ValueError("Internal reader refuses runtime var/ paths")
