from dataclasses import dataclass
import json
import socket
import ssl
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from translator_service.languages import language_name_for_code


class Transport(Protocol):
    def __call__(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        pass


@dataclass(frozen=True)
class DeepSeekUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


@dataclass(frozen=True)
class DeepSeekChatResult:
    content: str
    usage: DeepSeekUsage


class DeepSeekApiError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        transport: Transport | None = None,
        timeout_seconds: float = 60.0,
        retry_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._transport = transport or _urllib_transport
        self._timeout_seconds = timeout_seconds
        self._retry_attempts = max(1, retry_attempts)
        self._retry_delay_seconds = max(0.0, retry_delay_seconds)
        self._last_usage: DeepSeekUsage | None = None

    @property
    def last_usage(self) -> DeepSeekUsage | None:
        return self._last_usage

    def create_chat_completion(
        self,
        *,
        system_prompt: str,
        user_text: str,
    ) -> DeepSeekChatResult:
        body = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "stream": False,
                "thinking": {"type": "disabled"},
                "temperature": 0.2,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        status, response_body = self._send_with_retries(body)
        response = _parse_json_response(response_body)

        if status != 200:
            message = _extract_error_message(response)
            raise DeepSeekApiError(f"DeepSeek API returned HTTP {status}: {message}")

        return _parse_chat_result(response)

    def _send_with_retries(self, body: bytes) -> tuple[int, bytes]:
        last_error: DeepSeekApiError | None = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                status, response_body = self._transport(
                    url=f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    body=body,
                    timeout_seconds=self._timeout_seconds,
                )
            except URLError as error:
                if isinstance(error.reason, ssl.SSLCertVerificationError):
                    raise _request_error_from_url_error(error) from error
                last_error = _request_error_from_url_error(error)
            except _TRANSIENT_NETWORK_ERRORS as error:
                last_error = DeepSeekApiError(
                    f"DeepSeek API request failed while reading response: {error}"
                )
            else:
                if _is_retryable_http_status(status) and attempt < self._retry_attempts:
                    last_error = DeepSeekApiError(
                        f"DeepSeek API returned temporary HTTP {status}"
                    )
                    self._sleep_before_retry(attempt)
                    continue
                return status, response_body

            if attempt < self._retry_attempts:
                self._sleep_before_retry(attempt)
                continue

        if last_error is None:
            raise DeepSeekApiError("DeepSeek API request failed")
        raise DeepSeekApiError(
            f"{last_error} after {self._retry_attempts} attempts"
        ) from last_error

    def _sleep_before_retry(self, attempt: int) -> None:
        if self._retry_delay_seconds <= 0:
            return
        time.sleep(self._retry_delay_seconds * attempt)

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        result = self.create_chat_completion(
            system_prompt=_build_translation_prompt(
                source_language=source_language,
                target_language=target_language,
            ),
            user_text=text,
        )
        self._last_usage = result.usage
        return result.content


def _build_translation_prompt(*, source_language: str, target_language: str) -> str:
    source_language_name = language_name_for_code(source_language)
    target_language_name = language_name_for_code(target_language)
    source_instruction = (
        f"Translate every human language in the input to {target_language_name}. "
        "Do not leave text untranslated just because it is in a secondary source "
        "language. "
        if source_language.strip().lower() == "auto"
        else f"Translate from {source_language_name} to {target_language_name}. "
        "If the input contains text in another human language, translate that "
        f"text to {target_language_name} too. "
    )
    return (
        "You are a professional document translator. "
        f"{source_instruction}"
        "Preserve meaning, paragraph boundaries, numbers, and named entities. "
        "Keep ZXQPROTECTED...QXZ protected markers exactly unchanged. "
        "If the input contains <translation_batch> and <translation_block id=\"...\"> "
        "tags, keep those tags, ids, and source_language attributes exactly as "
        "provided. Treat a source_language attribute as a per-block source-language "
        "hint, translate only the text inside each translation_block, and return the "
        "same XML structure. "
        "Do not transliterate source-language words into the target script as a "
        "substitute for translation; translate the meaning. "
        "If the source contains a pangram or orthographic sample, translate it as "
        "a meaningful letter/orthography test instead of producing nonsense. "
        "Never include notes, explanations, warnings, apologies, alternatives, or "
        "phrases such as 'Here is the translation' anywhere in the output. "
        "Return only the translated text without commentary."
    )



def _parse_chat_result(response: dict) -> DeepSeekChatResult:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise DeepSeekApiError("DeepSeek response did not contain message content") from error

    if not isinstance(content, str) or not content.strip():
        raise DeepSeekApiError("DeepSeek response message content is empty")

    usage = response.get("usage") or {}
    return DeepSeekChatResult(
        content=content,
        usage=DeepSeekUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            prompt_cache_hit_tokens=int(usage.get("prompt_cache_hit_tokens", 0)),
            prompt_cache_miss_tokens=int(usage.get("prompt_cache_miss_tokens", 0)),
        ),
    )


def _parse_json_response(response_body: bytes) -> dict:
    try:
        parsed = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeepSeekApiError("DeepSeek response was not valid JSON") from error

    if not isinstance(parsed, dict):
        raise DeepSeekApiError("DeepSeek response JSON was not an object")

    return parsed


def _extract_error_message(response: dict) -> str:
    error = response.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    return "unknown error"


def _urllib_transport(
    *,
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout_seconds: float,
) -> tuple[int, bytes]:
    request = Request(url=url, headers=headers, data=body, method="POST")

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()
    except URLError as error:
        raise error


_TRANSIENT_NETWORK_ERRORS = (
    TimeoutError,
    socket.timeout,
    ssl.SSLError,
    OSError,
)


def _is_retryable_http_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


def _request_error_from_url_error(error: URLError) -> DeepSeekApiError:
    reason = error.reason
    if isinstance(reason, ssl.SSLCertVerificationError):
        return DeepSeekApiError(
            "DeepSeek API request failed because local Python SSL certificates "
            "are not configured. On macOS with python.org Python, run "
            "'Install Certificates.command' from the Python folder, then retry."
        )

    return DeepSeekApiError(f"DeepSeek API request failed: {reason}")
