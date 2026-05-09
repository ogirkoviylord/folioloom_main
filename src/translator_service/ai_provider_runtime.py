from __future__ import annotations

from dataclasses import dataclass, field

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.secrets import (
    SecretNotFound,
    SecretStoreUnavailable,
    SQLiteEncryptedSecretStore,
)
from translator_service.config import Settings


@dataclass(frozen=True)
class AIProviderRuntimeKey:
    provider_id: str
    key_id: str
    label: str
    api_key: str = field(repr=False)
    weight: int = 1
    max_parallel_requests: int = 1


def load_ai_provider_runtime_keys(
    settings: Settings,
    *,
    provider_id: str,
) -> tuple[AIProviderRuntimeKey, ...]:
    if not settings.admin_secret_master_key:
        return ()
    try:
        with SQLiteEncryptedSecretStore(
            settings.admin_db_path,
            master_key=settings.admin_secret_master_key,
        ) as secrets:
            with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                summaries = keys.list_keys(
                    provider_id,
                    secret_describer=secrets.describe_secret,
                )
                runtime_keys: list[AIProviderRuntimeKey] = []
                for summary in summaries:
                    if not summary.enabled or summary.disabled:
                        continue
                    try:
                        plaintext = secrets.get_secret_value(summary.secret_id)
                    except SecretNotFound:
                        continue
                    runtime_keys.append(
                        AIProviderRuntimeKey(
                            provider_id=summary.provider_id,
                            key_id=summary.key_id,
                            label=summary.label,
                            api_key=plaintext,
                            weight=summary.weight,
                            max_parallel_requests=summary.max_parallel_requests,
                        )
                    )
    except SecretStoreUnavailable:
        return ()
    return tuple(runtime_keys)
