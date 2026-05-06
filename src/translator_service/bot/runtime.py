from dataclasses import dataclass
import asyncio
from datetime import datetime
import inspect
import logging
import os
import time

from translator_service.bot.messages import (
    build_back_to_menu_message,
    build_cancel_requested_message,
    build_help_message,
    build_how_it_works_message,
    build_language_selected_message,
    build_language_selection_message,
    build_nothing_to_cancel_message,
    build_no_pending_translation_message,
    build_pending_translation_message,
    build_start_message,
    build_translation_language_selection_message,
    build_translation_progress_message,
    build_upload_error_message,
    build_upload_prompt_message,
    build_translation_job_status_message,
    get_main_menu_button_text,
    get_back_text,
    get_cancel_text,
    get_confirm_translation_text,
    is_back_text,
    is_cancel_text,
    is_confirm_translation_text,
    is_help_text,
    is_how_it_works_text,
    is_language_menu_text,
    is_main_menu_text,
    is_translate_book_text,
    build_main_menu,
)
from translator_service.bot_translation_service import BotTranslationService, PendingTranslation
from translator_service.config import Settings
from translator_service.deepseek_client import DeepSeekClient
from translator_service.documents import FileTooLargeError, UnsupportedDocumentError
from translator_service.extractors import TextExtractionError
from translator_service.job_runner import InMemoryTranslationJobRepository
from translator_service.languages import (
    SUPPORTED_TARGET_LANGUAGES,
    find_language_by_button_text,
)
from translator_service.order_estimates import DocumentEstimationNotReadyError
from translator_service.pricing import PricingRules
from translator_service.translation_jobs import TranslationProgress


logger = logging.getLogger(__name__)

TRANSLATION_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
TRANSLATION_SPINNER_INTERVAL_SECONDS = 5


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
    from aiogram.types import CallbackQuery, Message

    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        await message.answer(
            build_start_message(
                interface_language=service.get_interface_language(message.from_user.id)
            ),
            reply_markup=_main_menu_keyboard(
                service.get_interface_language(message.from_user.id)
            ),
        )

    @router.message(Command("language"))
    async def language(message: Message) -> None:
        await message.answer(
            build_language_selection_message(
                interface_language=service.get_interface_language(message.from_user.id)
            ),
            reply_markup=_language_keyboard(),
        )

    @router.message(F.text.func(is_main_menu_text))
    async def main_menu(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        service.discard_pending_translation(message.from_user.id)
        await message.answer(
            build_start_message(interface_language=interface_language),
            reply_markup=_main_menu_keyboard(interface_language),
        )

    @router.message(F.text.func(is_translate_book_text))
    async def translate_book(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_upload_prompt_message(interface_language),
            reply_markup=_back_keyboard(interface_language),
        )

    @router.message(F.text.func(is_how_it_works_text))
    async def how_it_works(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_how_it_works_message(interface_language),
            reply_markup=_menu_detail_keyboard(interface_language),
        )

    @router.message(F.text.func(is_help_text))
    async def help_text(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_help_message(interface_language),
            reply_markup=_menu_detail_keyboard(interface_language),
        )

    @router.message(F.text.func(is_language_menu_text))
    async def language_menu(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_language_selection_message(interface_language=interface_language),
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
                await message.answer(build_upload_error_message(error, interface_language))
                return

            await message.answer(
                build_pending_translation_message(
                    pending,
                    interface_language=interface_language,
                ),
                reply_markup=_confirm_keyboard(interface_language, include_back=True),
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
        await message.answer(
            build_start_message(interface_language=language_option.code),
            reply_markup=_main_menu_keyboard(language_option.code),
        )

    @router.message(Command("confirm"))
    async def confirm(message: Message) -> None:
        await _confirm_pending_translation(
            message=message,
            service=service,
            translator=translator,
        )

    @router.message(Command("cancel"))
    async def cancel(message: Message) -> None:
        await _cancel_active_translation(message=message, service=service)

    @router.message(F.text.func(is_cancel_text))
    async def cancel_text(message: Message) -> None:
        await _cancel_active_translation(message=message, service=service)

    @router.callback_query(F.data == "cancel_translation")
    async def cancel_callback(callback: CallbackQuery) -> None:
        interface_language = service.get_interface_language(callback.from_user.id)
        if service.cancel_translation(callback.from_user.id):
            await callback.answer(build_cancel_requested_message(interface_language))
            return

        await callback.answer(
            build_nothing_to_cancel_message(interface_language),
            show_alert=True,
        )

    @router.message(F.text.func(is_back_text))
    async def back_text(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        service.discard_pending_translation(message.from_user.id)
        await message.answer(build_back_to_menu_message(interface_language))
        await message.answer(
            build_start_message(interface_language=interface_language),
            reply_markup=_main_menu_keyboard(interface_language),
        )

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
            await message.answer(build_no_pending_translation_message(interface_language))
            return

        await message.answer(
            build_pending_translation_message(
                pending,
                interface_language=interface_language,
            ),
            reply_markup=_confirm_keyboard(interface_language, include_back=True),
        )

    @router.message(F.document)
    async def document_upload(message: Message) -> None:
        document = message.document
        if _document_exceeds_upload_limit(document, max_upload_mb=config.max_upload_mb):
            error = FileTooLargeError(
                f"File exceeds the upload limit of {config.max_upload_mb} MB"
            )
            interface_language = service.get_interface_language(message.from_user.id)
            await message.answer(build_upload_error_message(error, interface_language))
            return

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
            interface_language = service.get_interface_language(message.from_user.id)
            await message.answer(build_upload_error_message(error, interface_language))
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


def _confirm_keyboard(interface_language: str = "en", *, include_back: bool = False):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    keyboard = [[KeyboardButton(text=get_confirm_translation_text(interface_language))]]
    if include_back:
        keyboard.append([KeyboardButton(text=get_back_text(interface_language))])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _main_menu_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    menu = build_main_menu(interface_language)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=menu[0])],
            [KeyboardButton(text=menu[1]), KeyboardButton(text=menu[2])],
            [KeyboardButton(text=menu[3])],
        ],
        resize_keyboard=True,
    )


def _menu_detail_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    menu = build_main_menu(interface_language)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=menu[0])],
            [KeyboardButton(text=get_main_menu_button_text(interface_language))],
        ],
        resize_keyboard=True,
    )


def _back_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_back_text(interface_language))]],
        resize_keyboard=True,
    )


def _cancel_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_cancel_text(interface_language))]],
        resize_keyboard=True,
    )


def _cancel_inline_keyboard(interface_language: str = "en"):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=get_cancel_text(interface_language),
                    callback_data="cancel_translation",
                )
            ]
        ]
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


def _document_exceeds_upload_limit(document, *, max_upload_mb: int) -> bool:
    file_size = getattr(document, "file_size", None)
    if file_size is None:
        return False
    return int(file_size) > max_upload_mb * 1024 * 1024


async def _confirm_pending_translation(
    *,
    message,
    service: BotTranslationService,
    translator: DeepSeekClient,
) -> None:
    interface_language = service.get_interface_language(message.from_user.id)
    pending = service.get_pending(message.from_user.id)
    total_fragments = pending.fragment_count if pending else 0
    started_at = time.monotonic()
    if pending is not None:
        _print_translation_start(pending)
    progress_stats = {
        "completed": 0,
        "total": total_fragments,
        "estimated_total_seconds": pending.estimated_seconds if pending else None,
        "last_translated_text": None,
        "spinner_index": 0,
        "tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_hit_tokens": 0,
        "cache_miss_tokens": 0,
    }
    progress_message = await message.answer(
        build_translation_progress_message(
            completed_fragments=0,
            total_fragments=total_fragments,
            interface_language=interface_language,
            estimated_total_seconds=pending.estimated_seconds if pending else None,
            elapsed_seconds=0,
            activity_indicator=_next_spinner_frame(-1),
        ),
        reply_markup=_cancel_inline_keyboard(interface_language),
    )
    loop = asyncio.get_running_loop()
    stop_heartbeat = asyncio.Event()

    def report_progress(progress: TranslationProgress | tuple[int, int]) -> None:
        completed_fragments, total = _progress_counts(progress)
        elapsed_seconds = max(1, round(time.monotonic() - started_at))
        estimated_total_seconds = None
        if completed_fragments > 0:
            estimated_total_seconds = round(
                elapsed_seconds / completed_fragments * max(total, completed_fragments)
            )
        last_translated_text = _progress_translated_text(progress)
        progress_stats["completed"] = completed_fragments
        progress_stats["total"] = total
        progress_stats["estimated_total_seconds"] = estimated_total_seconds
        progress_stats["last_translated_text"] = last_translated_text
        progress_stats["spinner_index"] = int(progress_stats["spinner_index"]) + 1
        progress_text = build_translation_progress_message(
            completed_fragments=completed_fragments,
            total_fragments=total,
            interface_language=interface_language,
            estimated_total_seconds=estimated_total_seconds,
            elapsed_seconds=elapsed_seconds,
            last_translated_text=last_translated_text,
            activity_indicator=_next_spinner_frame(
                int(progress_stats["spinner_index"]) - 1
            ),
        )
        if isinstance(progress, TranslationProgress):
            progress_stats["tokens"] += progress.total_tokens
            progress_stats["prompt_tokens"] += progress.prompt_tokens
            progress_stats["completion_tokens"] += progress.completion_tokens
            progress_stats["cache_hit_tokens"] += progress.prompt_cache_hit_tokens
            progress_stats["cache_miss_tokens"] += progress.prompt_cache_miss_tokens
            _print_translation_progress(
                progress=progress,
                elapsed_total_seconds=elapsed_seconds,
            )
        _schedule_message_edit(
            loop=loop,
            message=progress_message,
            text=progress_text,
            reply_markup=_cancel_inline_keyboard(interface_language),
        )

    heartbeat_task = asyncio.create_task(
        _run_translation_progress_heartbeat(
            stop_event=stop_heartbeat,
            loop=loop,
            message=progress_message,
            interface_language=interface_language,
            started_at=started_at,
            progress_stats=progress_stats,
        )
    )
    try:
        job = await asyncio.to_thread(
            service.confirm_pending_translation,
            user_telegram_id=message.from_user.id,
            translator=translator,
            progress_callback=report_progress,
        )
    except ValueError as error:
        stop_heartbeat.set()
        await heartbeat_task
        await message.answer(str(error))
        return
    finally:
        stop_heartbeat.set()

    await heartbeat_task

    _print_translation_summary(
        job_id=job.id,
        file_name=job.file_name,
        result_file_name=job.result_file_name,
        document_kind=job.document_kind.value,
        completed_fragments=progress_stats["completed"],
        total_fragments=int(progress_stats["total"]),
        elapsed_seconds=time.monotonic() - started_at,
        prompt_tokens=progress_stats["prompt_tokens"],
        completion_tokens=progress_stats["completion_tokens"],
        total_tokens=progress_stats["tokens"],
        prompt_cache_hit_tokens=progress_stats["cache_hit_tokens"],
        prompt_cache_miss_tokens=progress_stats["cache_miss_tokens"],
        status=job.status.value,
    )
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


async def _cancel_active_translation(*, message, service: BotTranslationService) -> None:
    interface_language = service.get_interface_language(message.from_user.id)
    if service.cancel_translation(message.from_user.id):
        await message.answer(build_cancel_requested_message(interface_language))
        return

    await message.answer(build_nothing_to_cancel_message(interface_language))


async def _run_translation_progress_heartbeat(
    *,
    stop_event: asyncio.Event,
    loop,
    message,
    interface_language: str,
    started_at: float,
    progress_stats: dict[str, object],
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=TRANSLATION_SPINNER_INTERVAL_SECONDS,
            )
            return
        except asyncio.TimeoutError:
            pass

        progress_stats["spinner_index"] = int(progress_stats["spinner_index"]) + 1
        elapsed_seconds = max(1, round(time.monotonic() - started_at))
        completed_fragments = int(progress_stats["completed"])
        total_fragments = int(progress_stats["total"])
        estimated_total_seconds = progress_stats["estimated_total_seconds"]
        if estimated_total_seconds is None and completed_fragments > 0:
            estimated_total_seconds = round(
                elapsed_seconds
                / completed_fragments
                * max(total_fragments, completed_fragments)
            )
        progress_text = build_translation_progress_message(
            completed_fragments=completed_fragments,
            total_fragments=total_fragments,
            interface_language=interface_language,
            estimated_total_seconds=(
                int(estimated_total_seconds)
                if estimated_total_seconds is not None
                else None
            ),
            elapsed_seconds=elapsed_seconds,
            last_translated_text=(
                str(progress_stats["last_translated_text"])
                if progress_stats["last_translated_text"]
                else None
            ),
            activity_indicator=_next_spinner_frame(
                int(progress_stats["spinner_index"]) - 1
            ),
        )
        _schedule_message_edit(
            loop=loop,
            message=message,
            text=progress_text,
            reply_markup=_cancel_inline_keyboard(interface_language),
        )


def _schedule_message_edit(*, loop, message, text: str, reply_markup=None):
    async def edit_message() -> None:
        bot = getattr(message, "bot", None)
        chat = getattr(message, "chat", None)
        message_id = getattr(message, "message_id", None)
        if bot is not None and chat is not None and message_id is not None:
            await bot.edit_message_text(
                text=text,
                chat_id=chat.id,
                message_id=message_id,
                reply_markup=reply_markup,
            )
            return

        result = message.edit_text(text)
        if inspect.isawaitable(result):
            await result

    future = asyncio.run_coroutine_threadsafe(edit_message(), loop)
    future.add_done_callback(_log_message_edit_error)
    return future


def _log_message_edit_error(future) -> None:
    try:
        future.result()
    except Exception as error:
        message = str(error)
        if "message can't be edited" in message:
            logger.warning("Telegram refused to edit translation progress message: %s", message)
            return
        logger.exception("Failed to edit translation progress message")


def _progress_counts(progress: TranslationProgress | tuple[int, int]) -> tuple[int, int]:
    if isinstance(progress, TranslationProgress):
        return progress.completed_fragments, progress.total_fragments
    return progress


def _progress_translated_text(progress: TranslationProgress | tuple[int, int]) -> str | None:
    if isinstance(progress, TranslationProgress) and progress.translated_text:
        return progress.translated_text
    return None


def _next_spinner_frame(current_index: int) -> str:
    return TRANSLATION_SPINNER_FRAMES[
        (current_index + 1) % len(TRANSLATION_SPINNER_FRAMES)
    ]


def _print_translation_progress(
    *,
    progress: TranslationProgress,
    elapsed_total_seconds: int,
) -> None:
    status = "ok" if progress.success else "failed"
    print(
        "[translation] "
        f"fragment={progress.completed_fragments}/{progress.total_fragments} "
        f"status={status} "
        f"fragment_time={progress.elapsed_seconds:.2f}s "
        f"elapsed={elapsed_total_seconds}s "
        f"tokens={progress.total_tokens} "
        f"prompt_tokens={progress.prompt_tokens} "
        f"completion_tokens={progress.completion_tokens} "
        f"translated_chars={len(progress.translated_text)}",
        flush=True,
    )


def _print_translation_start(
    pending: PendingTranslation,
    *,
    started_at: datetime | None = None,
) -> None:
    started_at = started_at or datetime.now()
    summary = (
        "TRANSLATION STARTED "
        f"started_at={started_at.isoformat(timespec='seconds')} "
        f"file={pending.file_name} "
        f"type={pending.document_format or _file_extension_type(pending.file_name)} "
        f"size_bytes={len(pending.content)} "
        f"characters={pending.character_count} "
        f"source={pending.source_language_display or pending.source_language} "
        f"target={pending.target_language} "
        f"fragments={pending.fragment_count} "
        f"estimated_time={(pending.estimated_seconds or 0)}s "
        f"price=${pending.price_usd:.2f} "
        f"input_tokens={pending.estimated_input_tokens} "
        f"output_tokens={pending.estimated_output_tokens}"
    )
    print(f"\033[94m{summary}\033[0m", flush=True)


def _print_translation_summary(
    *,
    job_id: str,
    file_name: str,
    result_file_name: str | None,
    document_kind: str,
    completed_fragments: int,
    total_fragments: int,
    elapsed_seconds: float,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    prompt_cache_hit_tokens: int,
    prompt_cache_miss_tokens: int,
    status: str,
) -> None:
    average_fragment_time = (
        elapsed_seconds / completed_fragments if completed_fragments > 0 else 0.0
    )
    summary = (
        "TRANSLATION FINISHED "
        f"status={status} "
        f"job_id={job_id} "
        f"file={file_name} "
        f"result={result_file_name or '-'} "
        f"kind={document_kind} "
        f"fragments={completed_fragments}/{total_fragments} "
        f"elapsed={elapsed_seconds:.2f}s "
        f"avg_fragment_time={average_fragment_time:.2f}s "
        f"tokens={total_tokens} "
        f"prompt_tokens={prompt_tokens} "
        f"completion_tokens={completion_tokens} "
        f"cache_hit_tokens={prompt_cache_hit_tokens} "
        f"cache_miss_tokens={prompt_cache_miss_tokens}"
    )
    if status in {"ready", "cancelled"}:
        summary = f"\033[92m{summary}\033[0m"
    print(summary, flush=True)


def _file_extension_type(file_name: str) -> str:
    extension = file_name.rsplit(".", 1)[-1].strip().lower()
    return extension if extension and extension != file_name.lower() else "unknown"


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
