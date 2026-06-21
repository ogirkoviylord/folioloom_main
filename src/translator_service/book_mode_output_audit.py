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
# Explicit #766 policy: short Latin/foreign title labels remain acceptable only
# when they match a narrow, known non-English title phrase. Everything else in
# EPUB navigation/title/body-heading surfaces stays fail-closed.
_INTENTIONAL_LATIN_FOREIGN_TITLE_PHRASES = {
    "quo warranto",
}
_GUTENBERG_LEGAL_NAME_PATTERNS = (
    re.compile(
        r"\bProject\s+Gutenberg\s+Literary\s+Archive\s+Foundation\b",
        flags=re.IGNORECASE,
    ),
    re.compile(r"\bProject\s+Gutenberg(?:-tm)?\b", flags=re.IGNORECASE),
    re.compile(
        r"\bLiterary\s+Archive\s+Foundation\b",
        flags=re.IGNORECASE,
    ),
)
_GUTENBERG_LEGAL_BACKMATTER_RE = re.compile(
    r"\b(?:project\s+gutenberg|gutenberg-tm|literary\s+archive\s+foundation)\b",
    flags=re.IGNORECASE,
)
_LEGAL_BACKMATTER_TERMS = {
    "agreement",
    "boilerplate",
    "copy",
    "copyright",
    "distribute",
    "distribution",
    "donation",
    "donations",
    "ebook",
    "foundation",
    "license",
    "permission",
    "refund",
    "terms",
    "trademark",
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


def has_english_navigation_heading_residue(
    *,
    translated_text: str,
    target_language: str,
    block_id: str = "epub:surface-check",
    block_kind: str = "navigation",
    metadata: tuple[tuple[str, str], ...] = (),
    expected_latin_terms: Iterable[str] = (),
) -> bool:
    result = audit_book_mode_output(
        chunks=(
            BookModeAuditChunk(
                block_id=block_id,
                translated_text=translated_text,
                block_kind=block_kind,
                metadata=metadata,
            ),
        ),
        target_language=target_language,
        expected_latin_terms=expected_latin_terms,
    )
    return any(
        finding.code == "english_navigation_heading_residue"
        and finding.category == "navigation_heading"
        for finding in result.findings
    )


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

        is_navigation_or_heading = _is_navigation_or_heading_chunk(chunk)
        is_epub_title_allowlist_surface = (
            _is_epub_intentional_latin_foreign_title_surface(chunk)
        )
        stats = _chunk_language_stats(
            chunk.translated_text,
            expected_latin_terms=expected_terms,
            allow_intentional_latin_foreign_titles=is_epub_title_allowlist_surface,
        )

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

        if _has_gutenberg_legal_backmatter_residue(
            translated_text=chunk.translated_text,
            stats=stats,
        ):
            findings.append(
                _finding(
                    code="gutenberg_legal_backmatter_residue",
                    message=(
                        "Project Gutenberg/legal backmatter contains broad "
                        "English residue outside the narrow legal-name "
                        "preservation policy."
                    ),
                    target_root=target_root,
                    chunk=chunk,
                    category="legal_backmatter",
                    stats=stats,
                    severity="error",
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
    title_case_latin_word_count: int = 0

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
    allow_intentional_latin_foreign_titles: bool = False,
) -> _ChunkLanguageStats:
    protected_marker_count = len(_PROTECTED_MARKER_RE.findall(text))
    masked = _mask_non_residue_text(
        text,
        expected_latin_terms=expected_latin_terms,
        allow_intentional_latin_foreign_titles=allow_intentional_latin_foreign_titles,
    )
    latin_observations = tuple(_meaningful_latin_word_observations(masked))
    latin_words = tuple(
        word for word, _is_uppercase, _is_title_case in latin_observations
    )
    cyrillic_word_count = len(_CYRILLIC_WORD_RE.findall(masked))
    return _ChunkLanguageStats(
        latin_words=latin_words,
        cyrillic_word_count=cyrillic_word_count,
        protected_marker_count=protected_marker_count,
        uppercase_latin_word_count=sum(
            1
            for _word, is_uppercase, _is_title_case in latin_observations
            if is_uppercase
        ),
        title_case_latin_word_count=sum(
            1
            for _word, _is_uppercase, is_title_case in latin_observations
            if is_title_case
        ),
    )


def _mask_non_residue_text(
    text: str,
    *,
    expected_latin_terms: tuple[str, ...],
    allow_intentional_latin_foreign_titles: bool = False,
) -> str:
    masked = _PROVIDER_COMMENTARY_RE.sub(" ", text)
    if allow_intentional_latin_foreign_titles:
        masked = _mask_intentional_latin_foreign_title_phrases(masked)
    masked = _mask_gutenberg_legal_names(masked)
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


def _mask_intentional_latin_foreign_title_phrases(text: str) -> str:
    masked = text
    for phrase in sorted(
        _INTENTIONAL_LATIN_FOREIGN_TITLE_PHRASES,
        key=len,
        reverse=True,
    ):
        pattern = re.compile(
            rf"(?<![A-Za-z]){re.escape(phrase)}(?![A-Za-z])",
            flags=re.IGNORECASE,
        )
        candidate = pattern.sub(" ", masked)
        if candidate != masked and not _has_latin_residue_outside_title_allowlist(
            candidate
        ):
            masked = candidate
    return masked


def _mask_gutenberg_legal_names(text: str) -> str:
    masked = text
    for pattern in _GUTENBERG_LEGAL_NAME_PATTERNS:
        masked = pattern.sub(" ", masked)
    return masked


def _has_latin_residue_outside_title_allowlist(text: str) -> bool:
    masked = text
    for pattern in _MASK_RES:
        masked = pattern.sub(" ", masked)
    if _meaningful_latin_word_observations(masked):
        return True
    return any(
        match.group(0).lower() == "a" for match in _LATIN_WORD_RE.finditer(masked)
    )


def _meaningful_latin_word_observations(
    text: str,
) -> tuple[tuple[str, bool, bool], ...]:
    words: list[tuple[str, bool, bool]] = []
    for match in _LATIN_WORD_RE.finditer(text):
        raw_word = match.group(0).strip("'’")
        title_word = raw_word
        word = raw_word.lower()
        if word.endswith("'s") or word.endswith("’s"):
            word = word[:-2]
            title_word = raw_word[:-2]
        if len(word) < 2:
            continue
        if word in _TECHNICAL_LATIN_WORDS:
            continue
        if _ROMAN_NUMERAL_RE.fullmatch(word):
            continue
        words.append((word, raw_word.isupper(), title_word.istitle()))
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


def _is_epub_intentional_latin_foreign_title_surface(
    chunk: BookModeAuditChunk,
) -> bool:
    kind = chunk.block_kind.strip().lower().replace("-", "_")
    block_id = chunk.block_id.lower()
    metadata = {
        key.strip().lower(): value.strip().lower()
        for key, value in chunk.metadata
    }
    surface = metadata.get("surface", "")
    aux_kind = metadata.get("epub_aux_kind", "")

    if block_id.startswith(
        (
            "epub:aux:ncx:",
            "epub:surface-ncx:",
            "epub:aux:surface-ncx:",
            "epub:aux:xhtml-title:",
            "epub:surface-xhtml-title:",
            "epub:aux:surface-xhtml-title:",
            "epub:aux:xhtml-navigation:",
            "epub:surface-xhtml-navigation:",
            "epub:aux:surface-pre-final:",
            "epub:aux:surface-xhtml-navigation:",
        )
    ):
        return True
    if block_id.startswith("epub:surface-xhtml-body-heading:"):
        return True
    if not block_id.startswith("epub:"):
        return False
    if surface in {"toc_ncx", "xhtml_title", "xhtml_navigation"}:
        return True
    if surface == "xhtml_body_heading" and kind == "heading":
        return True
    return aux_kind in {"ncx_text", "xhtml_title", "xhtml_navigation"}


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
            or stats.title_case_latin_word_count >= 2
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


def _has_gutenberg_legal_backmatter_residue(
    *,
    translated_text: str,
    stats: _ChunkLanguageStats,
) -> bool:
    if not _GUTENBERG_LEGAL_BACKMATTER_RE.search(translated_text):
        return False
    if stats.latin_word_count < 4 or stats.english_function_word_count < 2:
        return False
    return any(word in _LEGAL_BACKMATTER_TERMS for word in stats.latin_words)


def _finding(
    *,
    code: str,
    message: str,
    target_root: str,
    chunk: BookModeAuditChunk,
    category: str,
    stats: _ChunkLanguageStats,
    severity: str = "warning",
) -> BookModeAuditFinding:
    return BookModeAuditFinding(
        code=code,
        message=message,
        target_language=target_root,
        chunk_id=chunk.block_id,
        chunk_kind=chunk.block_kind,
        category=category,
        severity=severity,
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
