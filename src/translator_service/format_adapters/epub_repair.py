from __future__ import annotations

import re
from dataclasses import dataclass
from html.entities import name2codepoint
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from translator_service.extractors import TextExtractionError, validate_archive_members


@dataclass(frozen=True)
class EpubRepairAction:
    kind: str
    file_name: str
    count: int = 1


@dataclass(frozen=True)
class EpubRepairReport:
    actions: tuple[EpubRepairAction, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def repaired(self) -> bool:
        return bool(self.actions)


@dataclass(frozen=True)
class RepairedEpub:
    content: bytes
    report: EpubRepairReport


def repair_epub_for_processing(content: bytes) -> RepairedEpub:
    try:
        source = BytesIO(content)
        target = BytesIO()
        actions: list[EpubRepairAction] = []
        with ZipFile(source) as source_epub:
            validate_archive_members(source_epub)
            _validate_epub_member_paths(source_epub)
            with ZipFile(target, "w") as target_epub:
                for item in source_epub.infolist():
                    data = source_epub.read(item)
                    if _is_repairable_epub_xml_part(item.filename):
                        data, item_actions = repair_epub_xml_part(
                            data,
                            file_name=item.filename,
                        )
                        actions.extend(item_actions)
                    target_epub.writestr(item, data)
        return RepairedEpub(
            content=target.getvalue(),
            report=EpubRepairReport(actions=tuple(actions)),
        )
    except BadZipFile as error:
        raise TextExtractionError(
            "EPUB file does not contain readable book text"
        ) from error


def repair_epub_xml_part(
    content: bytes,
    *,
    file_name: str,
) -> tuple[bytes, tuple[EpubRepairAction, ...]]:
    _reject_custom_xml_entities(content)

    repaired = content
    actions: list[EpubRepairAction] = []

    repaired, doctype_count = _strip_external_doctype(repaired)
    if doctype_count:
        actions.append(
            EpubRepairAction(
                kind="strip_external_doctype",
                file_name=file_name,
                count=doctype_count,
            )
        )

    repaired, simple_doctype_count = _strip_simple_html_doctype(repaired)
    if simple_doctype_count:
        actions.append(
            EpubRepairAction(
                kind="strip_simple_doctype",
                file_name=file_name,
                count=simple_doctype_count,
            )
        )

    repaired, entity_count = _replace_html_named_entities(repaired)
    if entity_count:
        actions.append(
            EpubRepairAction(
                kind="replace_named_entities",
                file_name=file_name,
                count=entity_count,
            )
        )

    return repaired, tuple(actions)


def normalize_epub_xml_part_for_xml(content: bytes) -> bytes:
    repaired, _ = repair_epub_xml_part(content, file_name="")
    return repaired


def _validate_epub_member_paths(epub: ZipFile) -> None:
    for member in epub.infolist():
        if _is_unsafe_epub_member_path(member.filename):
            raise TextExtractionError("EPUB archive contains unsafe file path")


def _is_unsafe_epub_member_path(file_name: str) -> bool:
    if not file_name or "\\" in file_name:
        return True
    path = PurePosixPath(file_name)
    if path.is_absolute():
        return True
    return ".." in path.parts


def _is_repairable_epub_xml_part(file_name: str) -> bool:
    return file_name.lower().endswith((".xhtml", ".html", ".htm", ".ncx"))


def _reject_custom_xml_entities(content: bytes) -> None:
    if _XML_ENTITY_PATTERN.search(content):
        raise TextExtractionError("Document XML entities are not supported")


def _strip_external_doctype(content: bytes) -> tuple[bytes, int]:
    return _EXTERNAL_DOCTYPE_PATTERN.subn(b"", content, count=1)


def _strip_simple_html_doctype(content: bytes) -> tuple[bytes, int]:
    return _SIMPLE_HTML_DOCTYPE_PATTERN.subn(b"", content, count=1)


def _replace_html_named_entities(content: bytes) -> tuple[bytes, int]:
    replacement_count = 0

    def replacement(match: re.Match[bytes]) -> bytes:
        nonlocal replacement_count
        entity_name = match.group(1)
        if entity_name in _XML_PREDEFINED_ENTITY_NAMES:
            return match.group(0)
        codepoint = name2codepoint.get(entity_name.decode("ascii"))
        if codepoint is None:
            return match.group(0)
        replacement_count += 1
        return f"&#{codepoint};".encode("ascii")

    repaired = _HTML_NAMED_ENTITY_PATTERN.sub(replacement, content)
    return repaired, replacement_count


_XML_ENTITY_PATTERN = re.compile(br"<!ENTITY", re.IGNORECASE)
_EXTERNAL_DOCTYPE_PATTERN = re.compile(
    br"""<!DOCTYPE\s+[A-Za-z_:][A-Za-z0-9_.:-]*\s+"""
    br"""(?:PUBLIC\s+(?:"[^"]*"|'[^']*')\s+(?:"[^"]*"|'[^']*')"""
    br"""|SYSTEM\s+(?:"[^"]*"|'[^']*'))\s*>""",
    re.IGNORECASE,
)
_SIMPLE_HTML_DOCTYPE_PATTERN = re.compile(br"<!DOCTYPE\s+html\s*>", re.IGNORECASE)
_HTML_NAMED_ENTITY_PATTERN = re.compile(br"&([A-Za-z][A-Za-z0-9]+);")
_XML_PREDEFINED_ENTITY_NAMES = frozenset({b"amp", b"lt", b"gt", b"quot", b"apos"})
