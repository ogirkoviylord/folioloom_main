from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
from typing import Protocol

from translator_service.structure_optimizer import PromptTier
from translator_service.text_analysis import detect_text_type
from translator_service.translation_profiles import target_language_policy_signature


class TranslationCache(Protocol):
    def get(
        self,
        *,
        source_texts: tuple[str, ...],
        source_language: str,
        target_language: str,
        prompt_tier: PromptTier,
    ) -> tuple[str, ...] | None:
        pass

    def put(
        self,
        *,
        source_texts: tuple[str, ...],
        translated_texts: tuple[str, ...],
        source_language: str,
        target_language: str,
        prompt_tier: PromptTier,
    ) -> None:
        pass


@dataclass
class MemoryTranslationCache:
    max_entries: int = 1_000
    _translations: OrderedDict[str, tuple[str, ...]] = field(default_factory=OrderedDict)

    def get(
        self,
        *,
        source_texts: tuple[str, ...],
        source_language: str,
        target_language: str,
        prompt_tier: PromptTier,
    ) -> tuple[str, ...] | None:
        key = _cache_key(
            source_texts=source_texts,
            source_language=source_language,
            target_language=target_language,
            prompt_tier=prompt_tier,
        )
        cached = self._translations.get(key)
        if cached is not None:
            self._translations.move_to_end(key)
        return cached

    def put(
        self,
        *,
        source_texts: tuple[str, ...],
        translated_texts: tuple[str, ...],
        source_language: str,
        target_language: str,
        prompt_tier: PromptTier,
    ) -> None:
        if len(source_texts) != len(translated_texts):
            raise ValueError("Cached translation must preserve source block count")
        if self.max_entries <= 0:
            return
        key = _cache_key(
            source_texts=source_texts,
            source_language=source_language,
            target_language=target_language,
            prompt_tier=prompt_tier,
        )
        self._translations[key] = translated_texts
        self._translations.move_to_end(key)
        while len(self._translations) > self.max_entries:
            self._translations.popitem(last=False)


def _cache_key(
    *,
    source_texts: tuple[str, ...],
    source_language: str,
    target_language: str,
    prompt_tier: PromptTier,
) -> str:
    payload = {
        "version": 1,
        "source_language": source_language.strip().lower(),
        "target_language": target_language.strip().lower(),
        "target_language_policy": target_language_policy_signature(target_language),
        "source_text_policy": _source_text_policy_signature(source_texts),
        "prompt_tier": prompt_tier.value,
        "source_texts": [_normalize_text(text) for text in source_texts],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_text_policy_signature(source_texts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(detect_text_type(text).value for text in source_texts)


def _normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())
