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

