from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


class TextExtractionError(ValueError):
    pass


def extract_text_from_txt(content: bytes) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise TextExtractionError("TXT file must contain UTF-8 text") from error

    if not text.strip():
        raise TextExtractionError("TXT file does not contain translatable text")

    return text


def extract_text_from_docx(content: bytes) -> str:
    try:
        with ZipFile(BytesIO(content)) as docx:
            document_xml = docx.read("word/document.xml")
    except (BadZipFile, KeyError) as error:
        raise TextExtractionError(
            "DOCX file does not contain readable document text"
        ) from error

    try:
        document = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as error:
        raise TextExtractionError("DOCX document XML is not readable") from error

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

    text = "\n\n".join(paragraphs)
    if not text.strip():
        raise TextExtractionError("DOCX file does not contain translatable text")

    return text
