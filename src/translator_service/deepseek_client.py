from dataclasses import dataclass
import json
import ssl
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
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._transport = transport or _urllib_transport
        self._timeout_seconds = timeout_seconds

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
            raise _request_error_from_url_error(error) from error
        response = _parse_json_response(response_body)

        if status != 200:
            message = _extract_error_message(response)
            raise DeepSeekApiError(f"DeepSeek API returned HTTP {status}: {message}")

        return _parse_chat_result(response)

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        result = self.create_chat_completion(
            system_prompt=_build_translation_prompt(
                source_language=source_language,
                target_language=target_language,
            ),
            user_text=text,
        )
        return result.content


def _build_translation_prompt(*, source_language: str, target_language: str) -> str:
    source_language_name = language_name_for_code(source_language)
    target_language_name = language_name_for_code(target_language)
    return (
        "You are a professional document translator. "
        f"Translate from {source_language_name} to {target_language_name}. "
        "Preserve meaning, paragraph boundaries, numbers, and named entities. "
        "If the input contains <translation_batch> and <translation_block id=\"...\"> "
        "tags, keep those tags and ids exactly as provided, translate only the text "
        "inside each translation_block, and return the same XML structure. "
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
        raise _request_error_from_url_error(error) from error


def _request_error_from_url_error(error: URLError) -> DeepSeekApiError:
    reason = error.reason
    if isinstance(reason, ssl.SSLCertVerificationError):
        return DeepSeekApiError(
            "DeepSeek API request failed because local Python SSL certificates "
            "are not configured. On macOS with python.org Python, run "
            "'Install Certificates.command' from the Python folder, then retry."
        )

    return DeepSeekApiError(f"DeepSeek API request failed: {reason}")
