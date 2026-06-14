from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol

from translator_service.digest_utils import payload_digest
from translator_service.structure_optimizer import PromptTier
from translator_service.translation_policy import (
    TranslationPolicySignatureContext,
    build_translation_policy,
    translation_policy_signature,
    translation_policy_signature_context_payload,
)


class TranslationCache(Protocol):
    def get(
        self,
        *,
        source_texts: tuple[str, ...],
        source_language: str,
        target_language: str,
        prompt_tier: PromptTier,
        signature_context: TranslationPolicySignatureContext | None = None,
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
        signature_context: TranslationPolicySignatureContext | None = None,
    ) -> None:
        pass


@dataclass
class MemoryTranslationCache:
    max_entries: int = 1_000
    _translations: OrderedDict[str, tuple[str, ...]] = field(
        default_factory=OrderedDict
    )

    def get(
        self,
        *,
        source_texts: tuple[str, ...],
        source_language: str,
        target_language: str,
        prompt_tier: PromptTier,
        signature_context: TranslationPolicySignatureContext | None = None,
    ) -> tuple[str, ...] | None:
        key = _cache_key(
            source_texts=source_texts,
            source_language=source_language,
            target_language=target_language,
            prompt_tier=prompt_tier,
            signature_context=signature_context,
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
        signature_context: TranslationPolicySignatureContext | None = None,
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
            signature_context=signature_context,
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
    signature_context: TranslationPolicySignatureContext | None = None,
) -> str:
    payload = {
        "version": 1,
        "source_language": source_language.strip().lower(),
        "target_language": target_language.strip().lower(),
        "translation_policies": _translation_policy_signatures(
            source_texts=source_texts,
            source_language=source_language,
            target_language=target_language,
            prompt_tier=prompt_tier,
            signature_context=signature_context,
        ),
        "prompt_tier": prompt_tier.value,
        "source_texts": [_normalize_text(text) for text in source_texts],
    }
    if signature_context is not None:
        payload["translation_signature_context"] = (
            translation_policy_signature_context_payload(signature_context)
        )
    return payload_digest(payload, compact=False, length=None)


def _translation_policy_signatures(
    *,
    source_texts: tuple[str, ...],
    source_language: str,
    target_language: str,
    prompt_tier: PromptTier,
    signature_context: TranslationPolicySignatureContext | None = None,
) -> tuple[str, ...]:
    return tuple(
        translation_policy_signature(
            build_translation_policy(
                text=text,
                source_language=source_language,
                target_language=target_language,
                prompt_tier=prompt_tier,
            ),
            signature_context=signature_context,
        )
        for text in source_texts
    )


def _normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())
