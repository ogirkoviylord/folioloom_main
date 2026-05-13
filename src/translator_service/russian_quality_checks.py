from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from translator_service.russian_quality import RussianQualityTrack


@dataclass(frozen=True)
class RussianQualityIssue:
    code: str
    message: str
    severity: str = "error"
    source_fragment: str | None = None


@dataclass(frozen=True)
class RussianQualityCheckResult:
    issues: tuple[RussianQualityIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


def check_russian_translation_quality(
    *,
    source_text: str,
    translated_text: str,
    source_language: str,
    target_language: str,
    quality_track: RussianQualityTrack | None,
) -> RussianQualityCheckResult:
    if _language_root(target_language) != "ru":
        return RussianQualityCheckResult(issues=())

    issues: list[RussianQualityIssue] = []

    issues.extend(_check_missing_urls(source_text, translated_text))
    issues.extend(_check_missing_placeholders(source_text, translated_text))
    issues.extend(_check_missing_identifiers(source_text, translated_text))
    issues.extend(_check_missing_dates(source_text, translated_text))
    issues.extend(_check_missing_numbers(source_text, translated_text))
    issues.extend(_check_missing_currency_amounts(source_text, translated_text))
    issues.extend(_check_protected_marker_leakage(translated_text))
    issues.extend(_check_provider_commentary(translated_text))
    issues.extend(
        _check_untranslated_source_residue(
            translated_text=translated_text,
            source_language=source_language,
        )
    )

    return RussianQualityCheckResult(issues=tuple(issues))


_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", flags=re.IGNORECASE)
_PROTECTED_MARKER_RE = re.compile(r"ZXQPROTECTED\d+QXZ")
_PLACEHOLDER_RES = (
    re.compile(r"\$\{[^}\n]+\}"),
    re.compile(r"\{\{\s*[^{}\n]+\s*\}\}"),
    re.compile(r"%[A-Z][A-Z0-9_]+%"),
)
_IDENTIFIER_RE = re.compile(r"\b[A-Z]{2,}[A-Z0-9]*(?:-[A-Z0-9]+)+\b")
_NUMBER_RE = re.compile(
    r"(?<![\w-])\d{1,3}(?:[ \u00a0,.\u202f]\d{3})+(?:[,.]\d+)?(?![\w-])"
    r"|(?<![\w-])\d+(?:[,.]\d+)?(?![\w-])"
)
_CURRENCY_AMOUNT_RES = (
    re.compile(
        r"(?P<amount>\d{1,3}(?:[ \u00a0,.\u202f]\d{3})+(?:[,.]\d+)?|\d+(?:[,.]\d+)?)"
        r"\s*(?P<currency>€|\$|£|¥|₽|USD|EUR|GBP|JPY|RUB|CNY|AED|ILS|руб\.?)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?P<currency>€|\$|£|¥|₽|USD|EUR|GBP|JPY|RUB|CNY|AED|ILS|руб\.?)\s*"
        r"(?P<amount>\d{1,3}(?:[ \u00a0,.\u202f]\d{3})+(?:[,.]\d+)?|\d+(?:[,.]\d+)?)",
        flags=re.IGNORECASE,
    ),
)
_ISO_DATE_RE = re.compile(
    r"\b(?P<year>\d{4})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})\b"
)
_TEXT_DATE_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+"
    r"(?P<month>[A-Za-zÀ-ÿА-Яа-яЁёІіЇїЄєҐґ\u0590-\u05ff\u0600-\u06ff.]+)"
    r",?\s+(?P<year>\d{4})\b"
)
_CJK_DATE_RE = re.compile(
    r"\b(?P<year>\d{4})\s*[年년]\s*(?P<month>\d{1,2})\s*[月월]\s*(?P<day>\d{1,2})\s*[日일]?"
)
_PROVIDER_COMMENTARY_RE = re.compile(
    r"^\s*(?:sure,\s*)?(?:here(?:'s| is)(?: the)? translation|translation|"
    r"вот перевод|ниже перевод|готовый перевод|перевод)\s*[:\-–—]",
    flags=re.IGNORECASE,
)

_MONTHS = {
    "january": 1,
    "jan": 1,
    "января": 1,
    "январь": 1,
    "січня": 1,
    "stycznia": 1,
    "enero": 1,
    "janvier": 1,
    "januar": 1,
    "januari": 1,
    "يناير": 1,
    "february": 2,
    "feb": 2,
    "февраля": 2,
    "февраль": 2,
    "лютого": 2,
    "lutego": 2,
    "febrero": 2,
    "février": 2,
    "fevrier": 2,
    "februar": 2,
    "februari": 2,
    "فبراير": 2,
    "march": 3,
    "mar": 3,
    "марта": 3,
    "март": 3,
    "березня": 3,
    "marca": 3,
    "marzo": 3,
    "mars": 3,
    "märz": 3,
    "maerz": 3,
    "maart": 3,
    "مارس": 3,
    "april": 4,
    "apr": 4,
    "апреля": 4,
    "апрель": 4,
    "квітня": 4,
    "kwietnia": 4,
    "abril": 4,
    "avril": 4,
    "אפריל": 4,
    "أبريل": 4,
    "ابريل": 4,
    "may": 5,
    "мая": 5,
    "май": 5,
    "травня": 5,
    "maja": 5,
    "mayo": 5,
    "mai": 5,
    "מאי": 5,
    "במאי": 5,
    "مايو": 5,
    "june": 6,
    "jun": 6,
    "июня": 6,
    "июнь": 6,
    "червня": 6,
    "czerwca": 6,
    "junio": 6,
    "juin": 6,
    "juni": 6,
    "יוני": 6,
    "يونيو": 6,
    "july": 7,
    "jul": 7,
    "июля": 7,
    "июль": 7,
    "липня": 7,
    "lipca": 7,
    "julio": 7,
    "juillet": 7,
    "juli": 7,
    "יולי": 7,
    "يوليو": 7,
    "august": 8,
    "aug": 8,
    "августа": 8,
    "август": 8,
    "серпня": 8,
    "sierpnia": 8,
    "agosto": 8,
    "août": 8,
    "aout": 8,
    "אוגוסט": 8,
    "أغسطس": 8,
    "اغسطس": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "сентября": 9,
    "сентябрь": 9,
    "вересня": 9,
    "września": 9,
    "wrzesnia": 9,
    "septiembre": 9,
    "septembre": 9,
    "september": 9,
    "ספטמבר": 9,
    "سبتمبر": 9,
    "october": 10,
    "oct": 10,
    "октября": 10,
    "октябрь": 10,
    "жовтня": 10,
    "października": 10,
    "pazdziernika": 10,
    "octubre": 10,
    "octobre": 10,
    "oktober": 10,
    "אוקטובר": 10,
    "أكتوبر": 10,
    "اكتوبر": 10,
    "november": 11,
    "nov": 11,
    "ноября": 11,
    "ноябрь": 11,
    "листопада": 11,
    "listopada": 11,
    "noviembre": 11,
    "novembre": 11,
    "november": 11,
    "נובמבר": 11,
    "نوفمبر": 11,
    "december": 12,
    "dec": 12,
    "декабря": 12,
    "декабрь": 12,
    "грудня": 12,
    "grudnia": 12,
    "diciembre": 12,
    "décembre": 12,
    "decembre": 12,
    "dezember": 12,
    "december": 12,
    "דצמבר": 12,
    "ديسمبر": 12,
}


def _language_root(language_code: str) -> str:
    return language_code.strip().lower().replace("_", "-").split("-", 1)[0]


def _check_missing_urls(
    source_text: str,
    translated_text: str,
) -> tuple[RussianQualityIssue, ...]:
    return tuple(
        RussianQualityIssue(
            code="missing_url",
            message="Required URL is missing or changed.",
            source_fragment=url,
        )
        for url in _extract_urls(source_text)
        if url not in translated_text
    )


def _check_missing_placeholders(
    source_text: str,
    translated_text: str,
) -> tuple[RussianQualityIssue, ...]:
    return tuple(
        RussianQualityIssue(
            code="missing_placeholder",
            message="Required placeholder is missing or changed.",
            source_fragment=placeholder,
        )
        for placeholder in _extract_placeholders(source_text)
        if placeholder not in translated_text
    )


def _check_missing_identifiers(
    source_text: str,
    translated_text: str,
) -> tuple[RussianQualityIssue, ...]:
    return tuple(
        RussianQualityIssue(
            code="missing_identifier",
            message="Required identifier is missing or changed.",
            source_fragment=identifier,
        )
        for identifier in _extract_identifiers(source_text)
        if identifier not in translated_text
    )


def _check_missing_dates(
    source_text: str,
    translated_text: str,
) -> tuple[RussianQualityIssue, ...]:
    translated_dates = {date.canonical for date in _extract_dates(translated_text)}
    return tuple(
        RussianQualityIssue(
            code="missing_date",
            message="Required date value is missing or changed.",
            source_fragment=date.source_fragment,
        )
        for date in _extract_dates(source_text)
        if date.canonical not in translated_dates
    )


def _check_missing_numbers(
    source_text: str,
    translated_text: str,
) -> tuple[RussianQualityIssue, ...]:
    source_numbers = _extract_numbers(_mask_non_numeric_invariants(source_text))
    translated_numbers = Counter(
        number.canonical for number in _extract_numbers(_mask_non_numeric_invariants(translated_text))
    )
    issues: list[RussianQualityIssue] = []
    for number in source_numbers:
        if translated_numbers[number.canonical] > 0:
            translated_numbers[number.canonical] -= 1
            continue
        issues.append(
            RussianQualityIssue(
                code="missing_number",
                message="Required numeric value is missing or changed.",
                source_fragment=number.source_fragment,
            )
        )
    return tuple(issues)


def _check_missing_currency_amounts(
    source_text: str,
    translated_text: str,
) -> tuple[RussianQualityIssue, ...]:
    translated_amounts = Counter(
        (amount.currency, amount.canonical_amount)
        for amount in _extract_currency_amounts(translated_text)
    )
    issues: list[RussianQualityIssue] = []
    for amount in _extract_currency_amounts(source_text):
        key = (amount.currency, amount.canonical_amount)
        if translated_amounts[key] > 0:
            translated_amounts[key] -= 1
            continue
        issues.append(
            RussianQualityIssue(
                code="missing_currency_amount",
                message="Required currency amount is missing or changed.",
                source_fragment=amount.source_fragment,
            )
        )
    return tuple(issues)


def _check_protected_marker_leakage(
    translated_text: str,
) -> tuple[RussianQualityIssue, ...]:
    marker = _PROTECTED_MARKER_RE.search(translated_text)
    if marker is None:
        return ()
    return (
        RussianQualityIssue(
            code="protected_marker_leaked",
            message="Internal protected-text marker leaked into final Russian translation.",
            source_fragment=marker.group(0),
        ),
    )


def _check_provider_commentary(
    translated_text: str,
) -> tuple[RussianQualityIssue, ...]:
    commentary = _PROVIDER_COMMENTARY_RE.search(translated_text)
    if commentary is None:
        return ()
    return (
        RussianQualityIssue(
            code="provider_commentary",
            message="Provider commentary wrapper is present in the translation.",
            source_fragment=commentary.group(0).strip(),
        ),
    )


def _check_untranslated_source_residue(
    *,
    translated_text: str,
    source_language: str,
) -> tuple[RussianQualityIssue, ...]:
    language = _language_root(source_language)
    residue_text = _mask_non_language_residue(translated_text)
    if language == "en":
        has_residue = _has_mixed_english_residue(residue_text)
    else:
        residue_pattern = _RESIDUE_PATTERNS.get(language)
        has_residue = bool(residue_pattern and residue_pattern.search(residue_text))
    if not has_residue:
        return ()
    return (
        RussianQualityIssue(
            code="untranslated_source_residue",
            message="Translation contains obvious residue from the source language.",
            source_fragment=language,
        ),
    )


def _extract_urls(text: str) -> tuple[str, ...]:
    return tuple(
        match.group(0).rstrip(".,;:!?")
        for match in _URL_RE.finditer(text)
    )


def _extract_placeholders(text: str) -> tuple[str, ...]:
    placeholders: list[str] = []
    for pattern in _PLACEHOLDER_RES:
        placeholders.extend(match.group(0) for match in pattern.finditer(text))
    return tuple(dict.fromkeys(placeholders))


def _extract_identifiers(text: str) -> tuple[str, ...]:
    masked_text = _mask_spans(text, _URL_RE, *_PLACEHOLDER_RES)
    return tuple(dict.fromkeys(match.group(0) for match in _IDENTIFIER_RE.finditer(masked_text)))


@dataclass(frozen=True)
class _DateValue:
    canonical: str
    source_fragment: str


@dataclass(frozen=True)
class _NumberValue:
    canonical: str
    source_fragment: str


@dataclass(frozen=True)
class _CurrencyAmount:
    currency: str
    canonical_amount: str
    source_fragment: str


def _extract_dates(text: str) -> tuple[_DateValue, ...]:
    dates: list[_DateValue] = []
    for match in _ISO_DATE_RE.finditer(text):
        date = _canonical_date(
            year=match.group("year"),
            month=match.group("month"),
            day=match.group("day"),
        )
        if date is not None:
            dates.append(_DateValue(canonical=date, source_fragment=match.group(0)))

    for match in _TEXT_DATE_RE.finditer(text):
        month_number = _month_number(match.group("month"))
        if month_number is None:
            continue
        date = _canonical_date(
            year=match.group("year"),
            month=str(month_number),
            day=match.group("day"),
        )
        if date is not None:
            dates.append(_DateValue(canonical=date, source_fragment=match.group(0)))

    for match in _CJK_DATE_RE.finditer(text):
        date = _canonical_date(
            year=match.group("year"),
            month=match.group("month"),
            day=match.group("day"),
        )
        if date is not None:
            dates.append(_DateValue(canonical=date, source_fragment=match.group(0)))

    return tuple(dict.fromkeys(dates))


def _extract_numbers(text: str) -> tuple[_NumberValue, ...]:
    numbers: list[_NumberValue] = []
    for match in _NUMBER_RE.finditer(text):
        canonical = _canonical_number(match.group(0))
        if canonical is None:
            continue
        numbers.append(_NumberValue(canonical=canonical, source_fragment=match.group(0)))
    return tuple(numbers)


def _extract_currency_amounts(text: str) -> tuple[_CurrencyAmount, ...]:
    amounts: list[_CurrencyAmount] = []
    masked_text = _mask_non_numeric_invariants(text)
    for pattern in _CURRENCY_AMOUNT_RES:
        for match in pattern.finditer(masked_text):
            canonical_amount = _canonical_number(match.group("amount"))
            if canonical_amount is None:
                continue
            amounts.append(
                _CurrencyAmount(
                    currency=_canonical_currency(match.group("currency")),
                    canonical_amount=canonical_amount,
                    source_fragment=match.group(0).strip(),
                )
            )
    return tuple(dict.fromkeys(amounts))


def _canonical_date(*, year: str, month: str, day: str) -> str | None:
    try:
        year_number = int(year)
        month_number = int(month)
        day_number = int(day)
    except ValueError:
        return None
    if not 1 <= month_number <= 12 or not 1 <= day_number <= 31:
        return None
    return f"{year_number:04d}-{month_number:02d}-{day_number:02d}"


def _month_number(month: str) -> int | None:
    return _MONTHS.get(month.strip().lower().strip("."))


def _canonical_number(value: str) -> str | None:
    compact = (
        value.replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace(" ", "")
        .strip()
    )
    if not compact:
        return None

    if "," in compact and "." in compact:
        decimal_separator = "," if compact.rfind(",") > compact.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        compact = compact.replace(thousands_separator, "")
        compact = compact.replace(decimal_separator, ".")
    elif "," in compact:
        head, tail = compact.rsplit(",", 1)
        compact = f"{head}.{tail}" if len(tail) <= 2 else compact.replace(",", "")
    elif "." in compact:
        head, tail = compact.rsplit(".", 1)
        compact = f"{head}.{tail}" if len(tail) <= 2 else compact.replace(".", "")

    try:
        number = Decimal(compact)
    except InvalidOperation:
        return None
    return format(number.normalize(), "f")


def _canonical_currency(currency: str) -> str:
    normalized = currency.strip().upper().rstrip(".")
    return {
        "€": "EUR",
        "$": "USD",
        "£": "GBP",
        "¥": "JPY",
        "₽": "RUB",
        "РУБ": "RUB",
    }.get(normalized, normalized)


def _mask_non_numeric_invariants(text: str) -> str:
    return _mask_spans(text, _URL_RE, *_PLACEHOLDER_RES, _IDENTIFIER_RE)


def _mask_non_language_residue(text: str) -> str:
    return _mask_spans(text, _URL_RE, *_PLACEHOLDER_RES, _IDENTIFIER_RE, _PROTECTED_MARKER_RE)


def _has_mixed_english_residue(text: str) -> bool:
    if _ENGLISH_NAVIGATION_RESIDUE_RE.fullmatch(text.strip()):
        return True
    if _CYRILLIC_RE.search(text) is None:
        return False

    words = [
        match.group(0).lower().strip("'")
        for match in _ENGLISH_WORD_RE.finditer(text)
    ]
    common_words = [word for word in words if word in _ENGLISH_RESIDUE_WORDS]
    return len(common_words) >= 2


def _mask_spans(text: str, *patterns: re.Pattern[str]) -> str:
    masked = text
    for pattern in patterns:
        masked = pattern.sub(lambda match: " " * len(match.group(0)), masked)
    return masked


_RESIDUE_PATTERNS = {
    "uk": re.compile(r"[іїєґІЇЄҐ]"),
    "zh": re.compile(r"[\u4e00-\u9fff]{2,}"),
    "ja": re.compile(r"[\u3040-\u30ff]{2,}|[\u4e00-\u9fff]{2,}"),
    "ko": re.compile(r"[\uac00-\ud7af]{2,}"),
    "he": re.compile(r"[\u0590-\u05ff]{2,}"),
    "ar": re.compile(r"[\u0600-\u06ff]{2,}"),
}
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_ENGLISH_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z']*\b")
_ENGLISH_NAVIGATION_RESIDUE_RE = re.compile(
    r"(?:chapter\s+[ivxlcdm]+|contents|foreword|list\s+of\s+illustrations)",
    flags=re.IGNORECASE,
)
_ENGLISH_RESIDUE_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "assert",
        "before",
        "chapter",
        "contents",
        "day",
        "foreword",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "in",
        "information",
        "is",
        "it",
        "list",
        "meanwhile",
        "must",
        "next",
        "of",
        "on",
        "scope",
        "she",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "when",
        "while",
        "with",
        "would",
    }
)
