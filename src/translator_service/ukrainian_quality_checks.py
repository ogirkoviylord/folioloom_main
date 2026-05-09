from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from translator_service.russian_quality import RussianQualityTrack


@dataclass(frozen=True)
class UkrainianQualityIssue:
    code: str
    message: str
    severity: str = "error"
    source_fragment: str | None = None


@dataclass(frozen=True)
class UkrainianQualityCheckResult:
    issues: tuple[UkrainianQualityIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


def check_ukrainian_translation_quality(
    *,
    source_text: str,
    translated_text: str,
    source_language: str,
    target_language: str,
    quality_track: RussianQualityTrack | None,
) -> UkrainianQualityCheckResult:
    if _language_root(target_language) != "uk":
        return UkrainianQualityCheckResult(issues=())

    issues: list[UkrainianQualityIssue] = []
    issues.extend(_check_missing_urls(source_text, translated_text))
    issues.extend(_check_missing_placeholders(source_text, translated_text))
    issues.extend(_check_missing_identifiers(source_text, translated_text))
    issues.extend(_check_missing_dates(source_text, translated_text))
    issues.extend(_check_missing_numbers(source_text, translated_text))
    issues.extend(_check_missing_currency_amounts(source_text, translated_text))
    issues.extend(_check_protected_marker_leakage(translated_text))
    issues.extend(_check_provider_commentary(translated_text))
    issues.extend(_check_ukrainian_calques(translated_text))
    issues.extend(
        _check_untranslated_source_residue(
            translated_text=translated_text,
            source_language=source_language,
        )
    )
    return UkrainianQualityCheckResult(issues=tuple(issues))


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
        r"\s*(?P<currency>€|\$|£|¥|₽|₴|USD|EUR|GBP|JPY|RUB|CNY|UAH|грн\.?)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?P<currency>€|\$|£|¥|₽|₴|USD|EUR|GBP|JPY|RUB|CNY|UAH|грн\.?)\s*"
        r"(?P<amount>\d{1,3}(?:[ \u00a0,.\u202f]\d{3})+(?:[,.]\d+)?|\d+(?:[,.]\d+)?)",
        flags=re.IGNORECASE,
    ),
)
_ISO_DATE_RE = re.compile(
    r"\b(?P<year>\d{4})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})\b"
)
_TEXT_DATE_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+"
    r"(?P<month>[A-Za-zÀ-ÿА-Яа-яЁёІіЇїЄєҐґ.]+)"
    r",?\s+(?P<year>\d{4})\b"
)
_PROVIDER_COMMENTARY_RE = re.compile(
    r"^\s*(?:sure,\s*)?(?:here(?:'s| is)(?: the)? translation|translation|"
    r"ось переклад|от переклад|нижче переклад|готовий переклад|переклад|"
    r"вот перевод|ниже перевод|готовый перевод|перевод)\s*[:\-–—]",
    flags=re.IGNORECASE,
)
_UKRAINIAN_CALQUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bзроби(?:в|ла|ли|ти)\s+рішенн[яія]\b", re.IGNORECASE), "зробив рішення"),
    (re.compile(r"\bприй(?:няв|няла|няли|мати|няти)\s+участь\b", re.IGNORECASE), "прийняв участь"),
    (re.compile(r"\bна\s+протязі\b", re.IGNORECASE), "на протязі"),
    (re.compile(r"\bслідуюч(?:ий|а|е|і|ого|ому|им|их)\b", re.IGNORECASE), "слідуючий"),
    (re.compile(r"\bявля(?:ється|ються|вся|лася|лися)\b", re.IGNORECASE), "являється"),
    (re.compile(r"\bвисокорівнев(?:ий|ого|ому|им|а|е|і|им)\s+огляд", re.IGNORECASE), "високорівневим оглядом"),
)
_RUSSIAN_RESIDUE_RE = re.compile(
    r"\b(?:она|закрыла|дверь|который|которая|которые|является|следующий|"
    r"принял\s+участие|на\s+протяжении|данные|сейчас|выполнить|"
    r"пользователь|настройки)\b",
    flags=re.IGNORECASE,
)

_MONTHS = {
    "january": 1,
    "jan": 1,
    "января": 1,
    "січня": 1,
    "february": 2,
    "feb": 2,
    "февраля": 2,
    "лютого": 2,
    "march": 3,
    "mar": 3,
    "марта": 3,
    "березня": 3,
    "april": 4,
    "apr": 4,
    "апреля": 4,
    "квітня": 4,
    "may": 5,
    "мая": 5,
    "травня": 5,
    "june": 6,
    "jun": 6,
    "июня": 6,
    "червня": 6,
    "july": 7,
    "jul": 7,
    "июля": 7,
    "липня": 7,
    "august": 8,
    "aug": 8,
    "августа": 8,
    "серпня": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "сентября": 9,
    "вересня": 9,
    "october": 10,
    "oct": 10,
    "октября": 10,
    "жовтня": 10,
    "november": 11,
    "nov": 11,
    "ноября": 11,
    "листопада": 11,
    "december": 12,
    "dec": 12,
    "декабря": 12,
    "грудня": 12,
}


def _language_root(language_code: str) -> str:
    return language_code.strip().lower().replace("_", "-").split("-", 1)[0]


def _check_missing_urls(
    source_text: str,
    translated_text: str,
) -> tuple[UkrainianQualityIssue, ...]:
    return tuple(
        UkrainianQualityIssue(
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
) -> tuple[UkrainianQualityIssue, ...]:
    return tuple(
        UkrainianQualityIssue(
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
) -> tuple[UkrainianQualityIssue, ...]:
    return tuple(
        UkrainianQualityIssue(
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
) -> tuple[UkrainianQualityIssue, ...]:
    source_dates = {_canonical_date_value(value) for value in _extract_dates(source_text)}
    translated_dates = {
        _canonical_date_value(value) for value in _extract_dates(translated_text)
    }
    return tuple(
        UkrainianQualityIssue(
            code="missing_date",
            message="Required date is missing or changed.",
            source_fragment=date,
        )
        for date in sorted(source_dates)
        if date not in translated_dates
    )


def _check_missing_numbers(
    source_text: str,
    translated_text: str,
) -> tuple[UkrainianQualityIssue, ...]:
    source_numbers = {_canonical_number(value) for value in _extract_numbers(source_text)}
    translated_numbers = {
        _canonical_number(value) for value in _extract_numbers(translated_text)
    }
    issues: list[UkrainianQualityIssue] = []
    for number in sorted(source_numbers):
        if number not in translated_numbers:
            issues.append(
                UkrainianQualityIssue(
                    code="missing_number",
                    message="Required number is missing or changed.",
                    source_fragment=number,
                )
            )
    return tuple(issues)


def _check_missing_currency_amounts(
    source_text: str,
    translated_text: str,
) -> tuple[UkrainianQualityIssue, ...]:
    source_amounts = {
        _canonical_currency_amount(amount, currency)
        for amount, currency in _extract_currency_amounts(source_text)
    }
    translated_amounts = {
        _canonical_currency_amount(amount, currency)
        for amount, currency in _extract_currency_amounts(translated_text)
    }
    return tuple(
        UkrainianQualityIssue(
            code="missing_currency_amount",
            message="Required currency amount is missing or changed.",
            source_fragment=amount,
        )
        for amount in sorted(source_amounts)
        if amount not in translated_amounts
    )


def _check_protected_marker_leakage(
    translated_text: str,
) -> tuple[UkrainianQualityIssue, ...]:
    if not _PROTECTED_MARKER_RE.search(translated_text):
        return ()
    return (
        UkrainianQualityIssue(
            code="protected_marker_leaked",
            message="Internal protected-text marker leaked into translated output.",
        ),
    )


def _check_provider_commentary(
    translated_text: str,
) -> tuple[UkrainianQualityIssue, ...]:
    if not _PROVIDER_COMMENTARY_RE.search(translated_text):
        return ()
    return (
        UkrainianQualityIssue(
            code="provider_commentary",
            message="Provider commentary wrapper leaked into translated output.",
        ),
    )


def _check_ukrainian_calques(
    translated_text: str,
) -> tuple[UkrainianQualityIssue, ...]:
    issues: list[UkrainianQualityIssue] = []
    for pattern, fragment in _UKRAINIAN_CALQUE_PATTERNS:
        if pattern.search(translated_text):
            issues.append(
                UkrainianQualityIssue(
                    code="ukrainian_calque",
                    message="Avoid Russian calques or unnatural Ukrainian phrasing.",
                    severity="warning",
                    source_fragment=fragment,
                )
            )
    return tuple(issues)


def _check_untranslated_source_residue(
    *,
    translated_text: str,
    source_language: str,
) -> tuple[UkrainianQualityIssue, ...]:
    if _language_root(source_language) != "ru":
        return ()
    match = _RUSSIAN_RESIDUE_RE.search(translated_text)
    if match is None:
        return ()
    return (
        UkrainianQualityIssue(
            code="untranslated_source_residue",
            message="Obvious Russian source residue remains in Ukrainian output.",
            source_fragment=match.group(0),
        ),
    )


def _extract_urls(text: str) -> tuple[str, ...]:
    return tuple(_URL_RE.findall(text))


def _extract_placeholders(text: str) -> tuple[str, ...]:
    values: list[str] = []
    for pattern in _PLACEHOLDER_RES:
        values.extend(match.group(0) for match in pattern.finditer(text))
    return tuple(values)


def _extract_identifiers(text: str) -> tuple[str, ...]:
    return tuple(_IDENTIFIER_RE.findall(text))


def _extract_dates(text: str) -> tuple[tuple[str, str, str], ...]:
    values: list[tuple[str, str, str]] = []
    values.extend(
        (match.group("year"), match.group("month"), match.group("day"))
        for match in _ISO_DATE_RE.finditer(text)
    )
    for match in _TEXT_DATE_RE.finditer(text):
        month = _MONTHS.get(match.group("month").strip(".").lower())
        if month is not None:
            values.append((match.group("year"), str(month), match.group("day")))
    return tuple(values)


def _extract_numbers(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _NUMBER_RE.finditer(text))


def _extract_currency_amounts(text: str) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for pattern in _CURRENCY_AMOUNT_RES:
        values.extend(
            (match.group("amount"), match.group("currency"))
            for match in pattern.finditer(text)
        )
    return tuple(values)


def _canonical_date_value(value: tuple[str, str, str]) -> str:
    year, month, day = value
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _canonical_number(value: str) -> str:
    normalized = (
        value.replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    if normalized.count(".") > 1:
        parts = normalized.split(".")
        normalized = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return str(Decimal(normalized).normalize())
    except InvalidOperation:
        return normalized


def _canonical_currency_amount(amount: str, currency: str) -> str:
    return f"{_canonical_number(amount)}:{currency.strip().lower()}"
