from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class BookModeAuditChunk:
    block_id: str
    translated_text: str
    block_kind: str = "plain"
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class BookModeAuditFinding:
    code: str
    message: str
    target_language: str
    chunk_id: str
    chunk_kind: str
    category: str
    severity: str = "warning"
    latin_word_count: int = 0
    cyrillic_word_count: int = 0
    protected_marker_count: int = 0
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class BookModeAuditResult:
    target_language: str
    findings: tuple[BookModeAuditFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings


_CYRILLIC_TARGETS = {"ru", "uk"}
_CYRILLIC_WORD_RE = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]+")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
_PROTECTED_MARKER_RE = re.compile(r"ZXQPROTECTED\d+QXZ")
_PROVIDER_COMMENTARY_RE = re.compile(
    r"^\s*(?:sure,\s*)?(?:here(?:'s| is)(?: the)? translation|"
    r"translation|translated text|вот перевод|ниже перевод|готовый перевод|"
    r"перевод|ось переклад|от переклад|нижче переклад|готовий переклад|"
    r"переклад)\s*[:\-–—]",
    flags=re.IGNORECASE,
)
_MASK_RES = (
    re.compile(r"```.*?```", flags=re.DOTALL),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"https?://[^\s<>\]\)\"']+", flags=re.IGNORECASE),
    re.compile(
        r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s<>\]\)\"']*)?",
        flags=re.IGNORECASE,
    ),
    re.compile(r"</?[A-Za-z][^<>\n]*?>"),
    re.compile(r"\$\{[^}\n]+\}"),
    re.compile(r"\{\{\s*[^{}\n]+\s*\}\}"),
    re.compile(r"%[A-Z][A-Z0-9_]+%"),
    re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}"),
    re.compile(r"ZXQPROTECTED\d+QXZ"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*="),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\([^()\n]*\)"),
    re.compile(r"\b(?:print|return)\s*\([^()\n]*\)"),
    re.compile(r'"[A-Za-z_][A-Za-z0-9_-]*"\s*:'),
    re.compile(r"\b[A-Z]{2,}_[A-Z0-9_]+\b"),
    re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b"),
    re.compile(r"\b(?=[A-Za-z0-9]*\d)(?:[A-Z][a-z]?\d*){2,}\b"),
    re.compile(r"\b[A-Za-z]{1,4}\d+\b"),
)
_TECHNICAL_LATIN_WORDS = {
    "api",
    "css",
    "docx",
    "epub",
    "html",
    "http",
    "https",
    "id",
    "ids",
    "isbn",
    "json",
    "md",
    "ncx",
    "opf",
    "txt",
    "url",
    "urls",
    "xml",
    "xhtml",
}
_ENGLISH_FUNCTION_WORDS = {
    "about",
    "after",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "before",
    "being",
    "but",
    "by",
    "could",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "here",
    "his",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "not",
    "of",
    "on",
    "or",
    "over",
    "shall",
    "she",
    "should",
    "that",
    "the",
    "their",
    "there",
    "these",
    "they",
    "this",
    "those",
    "to",
    "under",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "will",
    "with",
    "without",
    "would",
    "you",
}
_NAVIGATION_WORDS = {
    "afterword",
    "appendix",
    "bibliography",
    "book",
    "chapter",
    "contents",
    "copyright",
    "cover",
    "epilogue",
    "foreword",
    "introduction",
    "navigation",
    "notes",
    "page",
    "part",
    "prologue",
    "section",
    "title",
    "toc",
    "volume",
}
_NAVIGATION_KINDS = {
    "heading",
    "nav",
    "navigation",
    "section_title",
    "title",
    "toc",
}
_LANGUAGE_METADATA_KEYS = {
    "dc:language",
    "lang",
    "language",
    "target_language",
    "xml:lang",
}
_LANGUAGE_NAME_ROOTS = {
    "english": "en",
    "russian": "ru",
    "ukrainian": "uk",
}
_ROMAN_NUMERAL_RE = re.compile(r"^[ivxlcdm]+$", flags=re.IGNORECASE)


def audit_book_mode_output(
    *,
    chunks: Iterable[BookModeAuditChunk],
    target_language: str,
    expected_latin_terms: Iterable[str] = (),
) -> BookModeAuditResult:
    target_root = _language_root(target_language)
    expected_terms = tuple(
        term.strip() for term in expected_latin_terms if term.strip()
    )
    findings: list[BookModeAuditFinding] = []

    for chunk in chunks:
        findings.extend(
            _audit_language_metadata(
                chunk=chunk,
                target_root=target_root,
            )
        )
        if target_root not in _CYRILLIC_TARGETS:
            continue

        stats = _chunk_language_stats(
            chunk.translated_text,
            expected_latin_terms=expected_terms,
        )
        is_navigation_or_heading = _is_navigation_or_heading_chunk(chunk)

        if _PROVIDER_COMMENTARY_RE.search(chunk.translated_text):
            findings.append(
                _finding(
                    code="provider_commentary_wrapper",
                    message="Provider commentary wrapper appears in book-mode output.",
                    target_root=target_root,
                    chunk=chunk,
                    category="provider_output",
                    stats=stats,
                )
            )

        if is_navigation_or_heading and _has_heading_navigation_residue(stats):
            findings.append(
                _finding(
                    code="english_navigation_heading_residue",
                    message=(
                        "English heading or navigation residue remains in "
                        "Cyrillic output."
                    ),
                    target_root=target_root,
                    chunk=chunk,
                    category="navigation_heading",
                    stats=stats,
                )
            )
            continue

        if _has_suspicious_all_english_chunk(stats):
            findings.append(
                _finding(
                    code="suspicious_all_english_chunk",
                    message=(
                        "Book-mode chunk is suspiciously all English for a "
                        "Cyrillic target."
                    ),
                    target_root=target_root,
                    chunk=chunk,
                    category="language_mix",
                    stats=stats,
                )
            )
            continue

        if _has_untranslated_english_residue(stats):
            findings.append(
                _finding(
                    code="untranslated_source_residue",
                    message=(
                        "English source residue remains in Cyrillic "
                        "book-mode output."
                    ),
                    target_root=target_root,
                    chunk=chunk,
                    category="language_mix",
                    stats=stats,
                )
            )

    return BookModeAuditResult(
        target_language=target_root,
        findings=tuple(findings),
    )


@dataclass(frozen=True)
class _ChunkLanguageStats:
    latin_words: tuple[str, ...]
    cyrillic_word_count: int
    protected_marker_count: int
    uppercase_latin_word_count: int = 0

    @property
    def latin_word_count(self) -> int:
        return len(self.latin_words)

    @property
    def english_function_word_count(self) -> int:
        return sum(1 for word in self.latin_words if word in _ENGLISH_FUNCTION_WORDS)


def _audit_language_metadata(
    *,
    chunk: BookModeAuditChunk,
    target_root: str,
) -> tuple[BookModeAuditFinding, ...]:
    if target_root not in _CYRILLIC_TARGETS:
        return ()

    findings: list[BookModeAuditFinding] = []
    for key, value in chunk.metadata:
        normalized_key = key.strip().lower()
        if (
            normalized_key not in _LANGUAGE_METADATA_KEYS
            and not normalized_key.endswith(":lang")
        ):
            continue
        observed_root = _language_root(value)
        if observed_root and observed_root != target_root:
            findings.append(
                BookModeAuditFinding(
                    code="language_metadata_mismatch",
                    message="Language metadata does not match the Cyrillic target.",
                    target_language=target_root,
                    chunk_id=chunk.block_id,
                    chunk_kind=chunk.block_kind,
                    category="language_metadata",
                    severity="warning",
                    details=(
                        ("language_key", normalized_key),
                        ("observed_language_root", observed_root),
                        ("expected_language_root", target_root),
                    ),
                )
            )
    return tuple(findings)


def _chunk_language_stats(
    text: str,
    *,
    expected_latin_terms: tuple[str, ...],
) -> _ChunkLanguageStats:
    protected_marker_count = len(_PROTECTED_MARKER_RE.findall(text))
    masked = _mask_non_residue_text(text, expected_latin_terms=expected_latin_terms)
    latin_observations = tuple(_meaningful_latin_word_observations(masked))
    latin_words = tuple(word for word, _is_uppercase in latin_observations)
    cyrillic_word_count = len(_CYRILLIC_WORD_RE.findall(masked))
    return _ChunkLanguageStats(
        latin_words=latin_words,
        cyrillic_word_count=cyrillic_word_count,
        protected_marker_count=protected_marker_count,
        uppercase_latin_word_count=sum(
            1 for _word, is_uppercase in latin_observations if is_uppercase
        ),
    )


def _mask_non_residue_text(
    text: str,
    *,
    expected_latin_terms: tuple[str, ...],
) -> str:
    masked = _PROVIDER_COMMENTARY_RE.sub(" ", text)
    for term in sorted(expected_latin_terms, key=len, reverse=True):
        masked = re.sub(
            rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])",
            " ",
            masked,
            flags=re.IGNORECASE,
        )
    for pattern in _MASK_RES:
        masked = pattern.sub(" ", masked)
    return masked


def _meaningful_latin_word_observations(text: str) -> tuple[tuple[str, bool], ...]:
    words: list[tuple[str, bool]] = []
    for match in _LATIN_WORD_RE.finditer(text):
        raw_word = match.group(0).strip("'’")
        word = raw_word.lower()
        if word.endswith("'s") or word.endswith("’s"):
            word = word[:-2]
        if len(word) < 2:
            continue
        if word in _TECHNICAL_LATIN_WORDS:
            continue
        if _ROMAN_NUMERAL_RE.fullmatch(word):
            continue
        words.append((word, raw_word.isupper()))
    return tuple(words)


def _is_navigation_or_heading_chunk(chunk: BookModeAuditChunk) -> bool:
    kind = chunk.block_kind.strip().lower().replace("-", "_")
    if kind in _NAVIGATION_KINDS:
        return True

    block_id = chunk.block_id.lower()
    if block_id.startswith("epub:aux:ncx:"):
        return True
    if block_id.startswith("epub:aux:xhtml-title:"):
        return True
    if block_id.startswith("epub:aux:xhtml-navigation:"):
        return True

    metadata = {
        key.strip().lower(): value.strip().lower()
        for key, value in chunk.metadata
    }
    aux_kind = metadata.get("epub_aux_kind", "")
    role = metadata.get("role", "")
    return aux_kind in {"ncx_text", "xhtml_title", "xhtml_navigation"} or role in {
        "heading",
        "navigation",
        "toc",
    }


def _has_heading_navigation_residue(stats: _ChunkLanguageStats) -> bool:
    if stats.latin_word_count < 1:
        return False
    has_navigation_word = any(word in _NAVIGATION_WORDS for word in stats.latin_words)
    if stats.cyrillic_word_count == 0:
        return stats.latin_word_count >= 2 or has_navigation_word
    return has_navigation_word or _has_high_confidence_mixed_heading_residue(stats)


def _has_high_confidence_mixed_heading_residue(stats: _ChunkLanguageStats) -> bool:
    return (
        stats.latin_word_count >= 2
        and stats.cyrillic_word_count <= 6
        and (
            stats.uppercase_latin_word_count >= 2
            or stats.english_function_word_count >= 1
        )
    )


def _has_suspicious_all_english_chunk(stats: _ChunkLanguageStats) -> bool:
    return (
        stats.cyrillic_word_count == 0
        and stats.latin_word_count >= 4
        and stats.english_function_word_count >= 2
    )


def _has_untranslated_english_residue(stats: _ChunkLanguageStats) -> bool:
    return (
        stats.cyrillic_word_count > 0
        and stats.latin_word_count >= 4
        and stats.english_function_word_count >= 2
    )


def _finding(
    *,
    code: str,
    message: str,
    target_root: str,
    chunk: BookModeAuditChunk,
    category: str,
    stats: _ChunkLanguageStats,
) -> BookModeAuditFinding:
    return BookModeAuditFinding(
        code=code,
        message=message,
        target_language=target_root,
        chunk_id=chunk.block_id,
        chunk_kind=chunk.block_kind,
        category=category,
        latin_word_count=stats.latin_word_count,
        cyrillic_word_count=stats.cyrillic_word_count,
        protected_marker_count=stats.protected_marker_count,
        details=(
            ("reason", code),
            ("latin_word_count", str(stats.latin_word_count)),
            ("cyrillic_word_count", str(stats.cyrillic_word_count)),
            ("protected_marker_count", str(stats.protected_marker_count)),
        ),
    )


def _language_root(language_code: str) -> str:
    normalized = language_code.strip().lower().replace("_", "-")
    if not normalized:
        return ""
    root = normalized.split("-", 1)[0]
    return _LANGUAGE_NAME_ROOTS.get(root, root)
