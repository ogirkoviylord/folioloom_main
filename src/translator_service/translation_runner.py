from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from xml.etree import ElementTree
from zipfile import ZipFile

from translator_service.extractors import TextExtractionError, extract_text_from_txt
from translator_service.text_analysis import split_text_into_fragments
from translator_service.translation_jobs import TextTranslator, translate_text_fragments


@dataclass(frozen=True)
class TranslatedDocument:
    file_name: str
    content_type: str
    content: bytes
    fragment_count: int


def translate_txt_document(
    *,
    file_name: str,
    content: bytes,
    source_language: str,
    target_language: str,
    max_fragment_chars: int,
    translator: TextTranslator,
) -> TranslatedDocument:
    text = extract_text_from_txt(content)
    fragments = split_text_into_fragments(text, max_fragment_chars=max_fragment_chars)
    translation = translate_text_fragments(
        fragments=fragments,
        source_language=source_language,
        target_language=target_language,
        translator=translator,
    )

    return TranslatedDocument(
        file_name=_translated_txt_file_name(file_name, target_language),
        content_type="text/plain; charset=utf-8",
        content=translation.assembled_text.encode("utf-8"),
        fragment_count=len(translation.fragments),
    )


def translate_docx_document(
    *,
    file_name: str,
    content: bytes,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
) -> TranslatedDocument:
    paragraphs = _extract_docx_paragraphs(content)
    translation = translate_text_fragments(
        fragments=paragraphs,
        source_language=source_language,
        target_language=target_language,
        translator=translator,
    )
    translated_content = _replace_docx_paragraphs(
        content,
        [fragment.translated_text for fragment in translation.fragments],
    )

    return TranslatedDocument(
        file_name=_translated_file_name(file_name, target_language, "docx"),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=translated_content,
        fragment_count=len(translation.fragments),
    )


def _translated_txt_file_name(file_name: str, target_language: str) -> str:
    return _translated_file_name(file_name, target_language, "txt")


def _translated_file_name(file_name: str, target_language: str, extension: str) -> str:
    path = PurePath(file_name)
    stem = path.stem if path.suffix else file_name
    return f"{stem}.{target_language}.{extension}"


def _extract_docx_paragraphs(content: bytes) -> list[str]:
    document = _read_docx_document_xml(content)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []

    for paragraph in document.findall(".//w:p", namespace):
        pieces = [
            text_node.text or ""
            for text_node in paragraph.findall(".//w:t", namespace)
        ]
        paragraph_text = "".join(pieces).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    if not paragraphs:
        raise TextExtractionError("DOCX file does not contain translatable text")

    return paragraphs


def _replace_docx_paragraphs(content: bytes, translated_paragraphs: list[str]) -> bytes:
    document = _read_docx_document_xml(content)
    namespace_uri = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    namespace = {"w": namespace_uri}
    ElementTree.register_namespace("w", namespace_uri)
    translated_iter = iter(translated_paragraphs)

    for paragraph in document.findall(".//w:p", namespace):
        text_nodes = paragraph.findall(".//w:t", namespace)
        if not text_nodes:
            continue

        original_text = "".join(text_node.text or "" for text_node in text_nodes).strip()
        if not original_text:
            continue

        translated_text = next(translated_iter)
        text_nodes[0].text = translated_text
        for text_node in text_nodes[1:]:
            text_node.text = ""

    document_xml = ElementTree.tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
    )
    return _replace_docx_file(content, "word/document.xml", document_xml)


def _read_docx_document_xml(content: bytes) -> ElementTree.Element:
    try:
        with ZipFile(BytesIO(content)) as docx:
            document_xml = docx.read("word/document.xml")
    except Exception as error:
        raise TextExtractionError(
            "DOCX file does not contain readable document text"
        ) from error

    try:
        return ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as error:
        raise TextExtractionError("DOCX document XML is not readable") from error


def _replace_docx_file(content: bytes, file_name: str, replacement: bytes) -> bytes:
    source = BytesIO(content)
    target = BytesIO()

    with ZipFile(source) as source_docx, ZipFile(target, "w") as target_docx:
        for item in source_docx.infolist():
            data = replacement if item.filename == file_name else source_docx.read(item)
            target_docx.writestr(item, data)

    return target.getvalue()
