from dataclasses import dataclass
import asyncio
import inspect
import os

from translator_service.bot.messages import (
    build_cancel_requested_message,
    build_language_selected_message,
    build_language_selection_message,
    build_nothing_to_cancel_message,
    build_pending_translation_message,
    build_start_message,
    build_translation_language_selection_message,
    build_translation_progress_message,
    build_translation_job_status_message,
    get_confirm_translation_text,
    is_confirm_translation_text,
)
from translator_service.bot_translation_service import BotTranslationService
from translator_service.config import Settings
from translator_service.deepseek_client import DeepSeekClient
from translator_service.documents import UnsupportedDocumentError
from translator_service.extractors import TextExtractionError
from translator_service.job_runner import InMemoryTranslationJobRepository
from translator_service.languages import (
    SUPPORTED_TARGET_LANGUAGES,
    find_language_by_button_text,
)
from translator_service.order_estimates import DocumentEstimationNotReadyError
from translator_service.pricing import PricingRules


@dataclass(frozen=True)
class BotRuntimeConfig:
    source_language: str = "auto"
    target_language: str = "en"
    max_fragment_chars: int = 4_000
    max_upload_mb: int = 50


def build_default_pricing_rules() -> PricingRules:
    return PricingRules(
        deepseek_input_usd_per_million_tokens=0.28,
        expected_output_multiplier=1.2,
        service_markup_multiplier=3.0,
        minimum_price_usd=0.10,
    )


def build_polling_started_message() -> str:
    return "Telegram bot polling started. Open Telegram and send /start."


def build_translation_service(config: BotRuntimeConfig) -> BotTranslationService:
    return BotTranslationService(
        job_repository=InMemoryTranslationJobRepository(),
        pricing_rules=build_default_pricing_rules(),
        max_upload_mb=config.max_upload_mb,
        max_fragment_chars=config.max_fragment_chars,
    )


def build_deepseek_translator(settings: Settings) -> DeepSeekClient:
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")

    return DeepSeekClient(
        api_key=api_key,
        model=settings.deepseek_model,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        timeout_seconds=120,
    )


def create_router(
    *,
    service: BotTranslationService,
    translator: DeepSeekClient,
    config: BotRuntimeConfig,
):
    from aiogram import F, Router
    from aiogram.filters import Command
    from aiogram.types import Message

    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        await message.answer(
            build_language_selection_message(),
            reply_markup=_language_keyboard(),
        )

    @router.message(Command("language"))
    async def language(message: Message) -> None:
        await message.answer(
            build_language_selection_message(
                interface_language=service.get_interface_language(message.from_user.id)
            ),
            reply_markup=_language_keyboard(),
        )

    @router.message(F.text.func(_is_language_button_text))
    async def language_text(message: Message) -> None:
        language_option = find_language_by_button_text(message.text)
        if language_option is None:
            await message.answer(
                build_language_selection_message(
                    interface_language=service.get_interface_language(message.from_user.id)
                )
            )
            return

        interface_language = service.get_interface_language(message.from_user.id)
        pending_upload = service.get_pending_upload(message.from_user.id)
        if pending_upload is not None:
            try:
                pending = service.prepare_pending_upload(
                    user_telegram_id=message.from_user.id,
                    target_language=language_option.code,
                )
            except (
                DocumentEstimationNotReadyError,
                TextExtractionError,
                UnsupportedDocumentError,
                ValueError,
            ) as error:
                await message.answer(str(error))
                return

            await message.answer(
                build_pending_translation_message(
                    pending,
                    interface_language=interface_language,
                ),
                reply_markup=_confirm_keyboard(interface_language),
            )
            return

        service.set_interface_language(
            user_telegram_id=message.from_user.id,
            language_code=language_option.code,
        )
        await message.answer(
            build_language_selected_message(
                language_option.button_text,
                interface_language=language_option.code,
            )
        )
        await message.answer(build_start_message(interface_language=language_option.code))

    @router.message(Command("confirm"))
    async def confirm(message: Message) -> None:
        await _confirm_pending_translation(
            message=message,
            service=service,
            translator=translator,
        )

    @router.message(Command("cancel"))
    async def cancel(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        if service.cancel_translation(message.from_user.id):
            await message.answer(build_cancel_requested_message(interface_language))
            return

        await message.answer(build_nothing_to_cancel_message(interface_language))

    @router.message(F.text.func(is_confirm_translation_text))
    async def confirm_text(message: Message) -> None:
        await _confirm_pending_translation(
            message=message,
            service=service,
            translator=translator,
        )

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        pending_upload = service.get_pending_upload(message.from_user.id)
        if pending_upload is not None:
            await message.answer(
                build_translation_language_selection_message(
                    pending_upload.file_name,
                    interface_language=interface_language,
                    source_language_display=pending_upload.source_language_display,
                ),
                reply_markup=_language_keyboard(),
            )
            return

        pending = service.get_pending(message.from_user.id)
        if pending is None:
            await message.answer("Активного ожидающего перевода нет.")
            return

        await message.answer(
            build_pending_translation_message(
                pending,
                interface_language=interface_language,
            ),
            reply_markup=_confirm_keyboard(interface_language),
        )

    @router.message(F.document)
    async def document_upload(message: Message) -> None:
        document = message.document
        bot = message.bot
        file = await bot.get_file(document.file_id)
        downloaded = await bot.download_file(file.file_path)
        content = downloaded.read()

        try:
            pending_upload = service.store_uploaded_document(
                user_telegram_id=message.from_user.id,
                file_name=document.file_name or "document.txt",
                content=content,
                source_language=config.source_language,
            )
        except (
            DocumentEstimationNotReadyError,
            TextExtractionError,
            UnsupportedDocumentError,
            ValueError,
        ) as error:
            await message.answer(str(error))
            return

        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_translation_language_selection_message(
                pending_upload.file_name,
                interface_language=interface_language,
                source_language_display=pending_upload.source_language_display,
            ),
            reply_markup=_language_keyboard(),
        )

    return router


def _confirm_keyboard(interface_language: str = "ru"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=get_confirm_translation_text(interface_language))]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _language_keyboard():
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=language.button_text)]
            for language in SUPPORTED_TARGET_LANGUAGES
        ],
        resize_keyboard=True,
    )


def _is_language_button_text(text: str | None) -> bool:
    return find_language_by_button_text(text) is not None


async def _confirm_pending_translation(
    *,
    message,
    service: BotTranslationService,
    translator: DeepSeekClient,
) -> None:
    interface_language = service.get_interface_language(message.from_user.id)
    pending = service.get_pending(message.from_user.id)
    total_fragments = pending.fragment_count if pending else 0
    progress_message = await message.answer(
        build_translation_progress_message(
            completed_fragments=0,
            total_fragments=total_fragments,
            interface_language=interface_language,
        )
    )
    loop = asyncio.get_running_loop()

    def report_progress(progress: tuple[int, int]) -> None:
        completed_fragments, total = progress
        progress_text = build_translation_progress_message(
            completed_fragments=completed_fragments,
            total_fragments=total,
            interface_language=interface_language,
        )
        _schedule_message_edit(
            loop=loop,
            message=progress_message,
            text=progress_text,
        )

    try:
        job = await asyncio.to_thread(
            service.confirm_pending_translation,
            user_telegram_id=message.from_user.id,
            translator=translator,
            progress_callback=report_progress,
        )
    except ValueError as error:
        await message.answer(str(error))
        return

    await message.answer(
        build_translation_job_status_message(
            job,
            interface_language=interface_language,
        )
    )
    if job.result_file_name and job.result_content:
        from aiogram.types import BufferedInputFile

        await message.answer_document(
            BufferedInputFile(job.result_content, filename=job.result_file_name)
        )


def _schedule_message_edit(*, loop, message, text: str):
    async def edit_message() -> None:
        result = message.edit_text(text)
        if inspect.isawaitable(result):
            await result

    return asyncio.run_coroutine_threadsafe(edit_message(), loop)


async def run_bot() -> None:
    settings = Settings()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    from aiogram import Bot, Dispatcher

    config = BotRuntimeConfig(max_upload_mb=settings.max_upload_mb)
    service = build_translation_service(config)
    translator = build_deepseek_translator(settings)
    dispatcher = Dispatcher()
    dispatcher.include_router(
        create_router(service=service, translator=translator, config=config)
    )
    print(build_polling_started_message(), flush=True)
    await dispatcher.start_polling(Bot(token))


def main() -> None:
    try:
        asyncio.run(run_bot())
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
