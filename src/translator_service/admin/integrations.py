from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from translator_service.admin.secrets import SecretMetadata, SecretNotFound


class IntegrationCategory(StrEnum):
    AI_PROVIDER = "ai_provider"
    MESSENGER_BOT_CHANNEL = "messenger_bot_channel"
    STORAGE = "storage"
    ANALYTICS = "analytics"
    AUTH = "auth"
    WEBSITE_WIDGET = "website_widget"
    WEBHOOK = "webhook"
    CUSTOM = "custom"


class IntegrationState(StrEnum):
    CONFIGURED = "configured"
    MISSING_SECRET = "missing_secret"
    DISABLED = "disabled"


@dataclass(frozen=True)
class IntegrationSecretRequirement:
    secret_id: str
    label: str
    kind: str
    required: bool = True
    help_text: str = ""


@dataclass(frozen=True)
class IntegrationDefinition:
    integration_id: str
    label: str
    category: IntegrationCategory
    description: str
    secret_requirements: tuple[IntegrationSecretRequirement, ...] = ()
    capabilities: tuple[str, ...] = ()
    docs_url: str | None = None
    help_text: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class IntegrationSecretSummary:
    secret_id: str
    label: str
    kind: str
    required: bool
    configured: bool
    disabled: bool = False
    masked_value: str | None = None
    fingerprint: str | None = None
    version: int | None = None


@dataclass(frozen=True)
class IntegrationSummary:
    integration_id: str
    label: str
    category: IntegrationCategory
    description: str
    state: IntegrationState
    secrets: tuple[IntegrationSecretSummary, ...] = ()
    capabilities: tuple[str, ...] = ()
    docs_url: str | None = None
    help_text: str = ""


SecretDescriber = Callable[[str], SecretMetadata]


class IntegrationRegistry:
    def __init__(self, definitions: Sequence[IntegrationDefinition]) -> None:
        self._definitions = tuple(definitions)
        self._definitions_by_id = {
            definition.integration_id: definition for definition in self._definitions
        }
        if len(self._definitions_by_id) != len(self._definitions):
            raise ValueError("Integration ids must be unique")

    def list_definitions(self) -> tuple[IntegrationDefinition, ...]:
        return self._definitions

    def get_definition(self, integration_id: str) -> IntegrationDefinition:
        return self._definitions_by_id[integration_id]

    def list_summaries(
        self,
        *,
        secret_describer: SecretDescriber | None = None,
    ) -> tuple[IntegrationSummary, ...]:
        return tuple(
            self._summarize_definition(
                definition,
                secret_describer=secret_describer,
            )
            for definition in self._definitions
        )

    def _summarize_definition(
        self,
        definition: IntegrationDefinition,
        *,
        secret_describer: SecretDescriber | None,
    ) -> IntegrationSummary:
        secrets = tuple(
            _summarize_secret_requirement(
                requirement,
                secret_describer=secret_describer,
            )
            for requirement in definition.secret_requirements
        )
        state = _integration_state(definition, secrets)
        return IntegrationSummary(
            integration_id=definition.integration_id,
            label=definition.label,
            category=definition.category,
            description=definition.description,
            state=state,
            secrets=secrets,
            capabilities=definition.capabilities,
            docs_url=definition.docs_url,
            help_text=definition.help_text,
        )


def _summarize_secret_requirement(
    requirement: IntegrationSecretRequirement,
    *,
    secret_describer: SecretDescriber | None,
) -> IntegrationSecretSummary:
    if secret_describer is None:
        return _missing_secret_summary(requirement)
    try:
        metadata = secret_describer(requirement.secret_id)
    except (KeyError, SecretNotFound):
        return _missing_secret_summary(requirement)
    return IntegrationSecretSummary(
        secret_id=requirement.secret_id,
        label=requirement.label,
        kind=requirement.kind,
        required=requirement.required,
        configured=not metadata.disabled,
        disabled=metadata.disabled,
        masked_value=metadata.masked_value,
        fingerprint=metadata.fingerprint,
        version=metadata.version,
    )


def _missing_secret_summary(
    requirement: IntegrationSecretRequirement,
) -> IntegrationSecretSummary:
    return IntegrationSecretSummary(
        secret_id=requirement.secret_id,
        label=requirement.label,
        kind=requirement.kind,
        required=requirement.required,
        configured=False,
    )


def _integration_state(
    definition: IntegrationDefinition,
    secrets: tuple[IntegrationSecretSummary, ...],
) -> IntegrationState:
    if not definition.enabled:
        return IntegrationState.DISABLED
    required_secrets = tuple(secret for secret in secrets if secret.required)
    if any(secret.disabled for secret in required_secrets):
        return IntegrationState.DISABLED
    if any(not secret.configured for secret in required_secrets):
        return IntegrationState.MISSING_SECRET
    return IntegrationState.CONFIGURED


DEFAULT_AI_PROVIDER_REGISTRY = IntegrationRegistry(
    (
        IntegrationDefinition(
            integration_id="deepseek",
            label="DeepSeek",
            category=IntegrationCategory.AI_PROVIDER,
            description="DeepSeek model API used for translation and analysis.",
            secret_requirements=(
                IntegrationSecretRequirement(
                    secret_id="deepseek.api_key",
                    label="DeepSeek API key",
                    kind="api_key",
                    help_text="Server-side API key for DeepSeek requests.",
                ),
            ),
            capabilities=("translation", "text_analysis", "model_provider"),
            docs_url="https://api-docs.deepseek.com/",
        ),
    )
)


DEFAULT_INTEGRATION_REGISTRY = IntegrationRegistry(
    (
        IntegrationDefinition(
            integration_id="telegram",
            label="Telegram",
            category=IntegrationCategory.MESSENGER_BOT_CHANNEL,
            description="Telegram bot channel for document translation workflows.",
            secret_requirements=(
                IntegrationSecretRequirement(
                    secret_id="telegram.bot_token",
                    label="Telegram bot token",
                    kind="bot_token",
                    help_text="BotFather token used to run the Telegram bot.",
                ),
            ),
            capabilities=("bot_channel", "document_uploads", "notifications"),
            docs_url="https://core.telegram.org/bots/api",
        ),
        IntegrationDefinition(
            integration_id="whatsapp",
            label="WhatsApp",
            category=IntegrationCategory.MESSENGER_BOT_CHANNEL,
            description="WhatsApp Business messaging channel shell.",
            secret_requirements=(
                IntegrationSecretRequirement(
                    secret_id="whatsapp.access_token",
                    label="WhatsApp access token",
                    kind="access_token",
                ),
            ),
            capabilities=("bot_channel", "notifications"),
            docs_url="https://developers.facebook.com/docs/whatsapp",
            help_text="Future connector shell for WhatsApp Business messaging.",
        ),
        IntegrationDefinition(
            integration_id="instagram",
            label="Instagram",
            category=IntegrationCategory.MESSENGER_BOT_CHANNEL,
            description="Instagram messaging channel shell.",
            secret_requirements=(
                IntegrationSecretRequirement(
                    secret_id="instagram.access_token",
                    label="Instagram access token",
                    kind="access_token",
                ),
            ),
            capabilities=("messaging_channel", "notifications"),
            docs_url="https://developers.facebook.com/docs/messenger-platform/instagram",
            help_text="Future connector shell for Instagram messaging.",
        ),
        IntegrationDefinition(
            integration_id="discord",
            label="Discord",
            category=IntegrationCategory.MESSENGER_BOT_CHANNEL,
            description="Discord bot channel shell.",
            secret_requirements=(
                IntegrationSecretRequirement(
                    secret_id="discord.bot_token",
                    label="Discord bot token",
                    kind="bot_token",
                ),
            ),
            capabilities=("bot_channel", "notifications"),
            docs_url="https://discord.com/developers/docs/intro",
            help_text="Future connector shell for Discord bot workflows.",
        ),
        IntegrationDefinition(
            integration_id="website_widget",
            label="Website Widget",
            category=IntegrationCategory.WEBSITE_WIDGET,
            description="Embeddable website surface for direct customer workflows.",
            secret_requirements=(
                IntegrationSecretRequirement(
                    secret_id="website_widget.signing_secret",
                    label="Widget signing secret",
                    kind="signing_secret",
                    required=False,
                ),
            ),
            capabilities=("embedded_channel", "lead_capture", "document_uploads"),
            help_text="Future web surface for using the service outside messengers.",
        ),
        IntegrationDefinition(
            integration_id="webhooks",
            label="Webhooks",
            category=IntegrationCategory.WEBHOOK,
            description="Outbound event delivery to external automation systems.",
            secret_requirements=(
                IntegrationSecretRequirement(
                    secret_id="webhooks.signing_secret",
                    label="Webhook signing secret",
                    kind="signing_secret",
                    required=False,
                ),
            ),
            capabilities=("automation", "event_delivery"),
            help_text="Future connector for Zapier, Make, n8n, and custom systems.",
        ),
    )
)
