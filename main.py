import os
import time
import asyncio
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from aiogram.exceptions import (
    TelegramRetryAfter,
    TelegramForbiddenError,
    TelegramBadRequest,
)

from function import Database, HELP_MESSAGE, get_truck_number, is_driver_group
from tracker import router as tracker_router
from fleet import router as fleet_router
from kick_user import kick_router, set_db
from user_permission import (
    user_permission_router,
    get_admin_ids,
    get_allowed_user_ids,
)
from trailer import router as trailer_data_router
from location_commands import location_router, set_db as set_location_db
from trailer_commands import trailer_cmd_router, set_db as set_trailer_cmd_db, set_registry as set_trailer_cmd_registry
from trailer import set_lifecycle_db
from providers.skybitz import SkyBitzProvider
from providers.fus1on import Fus1onProvider
from providers.phillips import PhillipsProvider, create_webhook_app
from aiohttp import web
from providers.registry import ProviderRegistry
from scheduler import setup_scheduler as setup_main_scheduler, poll_trailer_positions


load_dotenv(override=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_PATH = os.getenv("DATABASE_PATH", "logistics_bot.db")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
db = Database(DATABASE_PATH)


class AdminStates(StatesGroup):
    broadcast_type = State()
    broadcast_text = State()
    broadcast_photo = State()
    broadcast_caption = State()
    broadcast_video = State()
    broadcast_video_caption = State()
    broadcast_pdf = State()
    broadcast_pdf_caption = State()


def is_admin_user(user_id: int) -> bool:
    return user_id in get_admin_ids() or user_id in get_allowed_user_ids()


def get_broadcast_type_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Text only", callback_data="broadcast_text")
    builder.button(text="🖼 Photo with caption", callback_data="broadcast_photo")
    builder.button(text="🎥 Video with caption", callback_data="broadcast_video")
    builder.button(text="📄 PDF with caption", callback_data="broadcast_pdf")
    builder.button(text="❌ Cancel", callback_data="cancel_action")
    builder.adjust(2)
    return builder.as_markup()


def get_cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="cancel_action")
    return builder.as_markup()


# -----------------------------
# Broadcast rate limit: 20 per minute
# -----------------------------
BROADCAST_PER_MINUTE = 20
BROADCAST_INTERVAL_SECONDS = (60.0 / BROADCAST_PER_MINUTE) + 0.10  # + запас

_broadcast_lock = asyncio.Lock()
_last_broadcast_sent_at = 0.0


async def broadcast_throttle():
    """
    Глобальный лимит для broadcast: не чаще 20 сообщений в минуту.
    Это 1 отправка примерно каждые 3 секунды.
    """
    global _last_broadcast_sent_at

    async with _broadcast_lock:
        now = time.monotonic()
        wait_for = (_last_broadcast_sent_at + BROADCAST_INTERVAL_SECONDS) - now
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        _last_broadcast_sent_at = time.monotonic()


async def broadcast_send(
    chat_id: int,
    send_fn,
    max_retries: int = 2,
):
    """
    Универсальная отправка с:
    - throttling 20 per minute
    - обработкой RetryAfter
    - понятными ошибками
    """
    attempts = 0
    while True:
        attempts += 1
        await broadcast_throttle()

        try:
            await send_fn()
            return True

        except TelegramRetryAfter as e:
            # Telegram говорит "подожди N секунд"
            sleep_for = float(e.retry_after) + 1.0
            logger.warning(f"RetryAfter for chat {chat_id}, sleeping {sleep_for:.1f}s")
            await asyncio.sleep(sleep_for)

            if attempts >= max_retries + 1:
                logger.error(f"Retry limit reached for chat {chat_id}")
                return False

        except (TelegramForbiddenError, TelegramBadRequest) as e:
            # Бот заблокирован, чата нет, нет доступа и так далее
            logger.error(f"Chat {chat_id} unreachable: {e}")
            return False

        except Exception as e:
            logger.error(f"Error sending to chat {chat_id}: {e}")
            return False


async def broadcast_to_driver_chats_text(message_text: str) -> tuple[int, int]:
    """
    Текстовая рассылка всем chat_id из БД.
    Важно: без get_chat, потому что он и убивал тебя по лимитам.
    """
    driver_chats = db.get_all_drivers()
    successful, failed = 0, 0

    for chat_id in driver_chats:
        ok = await broadcast_send(
            chat_id=chat_id,
            send_fn=lambda cid=chat_id: bot.send_message(chat_id=cid, text=message_text),
        )
        if ok:
            successful += 1
        else:
            failed += 1

    return successful, failed


async def broadcast_to_driver_chats_photo(photo_id: str, caption: str | None) -> tuple[int, int]:
    driver_chats = db.get_all_drivers()
    successful, failed = 0, 0

    for chat_id in driver_chats:
        ok = await broadcast_send(
            chat_id=chat_id,
            send_fn=lambda cid=chat_id: bot.send_photo(
                chat_id=cid,
                photo=photo_id,
                caption=caption,
            ),
        )
        if ok:
            successful += 1
        else:
            failed += 1

    return successful, failed


async def broadcast_to_driver_chats_video(video_id: str, caption: str | None) -> tuple[int, int]:
    driver_chats = db.get_all_drivers()
    successful, failed = 0, 0

    for chat_id in driver_chats:
        ok = await broadcast_send(
            chat_id=chat_id,
            send_fn=lambda cid=chat_id: bot.send_video(
                chat_id=cid,
                video=video_id,
                caption=caption,
            ),
        )
        if ok:
            successful += 1
        else:
            failed += 1

    return successful, failed


async def broadcast_to_driver_chats_pdf(pdf_file_id: str, caption: str | None) -> tuple[int, int]:
    driver_chats = db.get_all_drivers()
    successful, failed = 0, 0

    for chat_id in driver_chats:
        ok = await broadcast_send(
            chat_id=chat_id,
            send_fn=lambda cid=chat_id: bot.send_document(
                chat_id=cid,
                document=pdf_file_id,
                caption=caption,
            ),
        )
        if ok:
            successful += 1
        else:
            failed += 1

    return successful, failed


# -----------------------------
# Commands
# -----------------------------
@router.message(Command("start"))
async def cmd_start(message: Message):
    user_name = message.from_user.first_name

    if message.chat.type != "private":
        # Тут title уже есть в message.chat, без get_chat
        if not is_driver_group(message.chat.title):
            await message.answer("This bot only works in driver groups.")
            return

        truck_number = get_truck_number(message.chat.title)
        if truck_number:
            db.add_driver_chat(message.chat.id, truck_number)
            await message.answer(f"Chat added to driver groups (Truck #{truck_number})")

    await message.answer(f"Hi, {user_name}!\nUse /help to see the available commands.")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_MESSAGE, parse_mode="MarkdownV2")


@router.message(Command("join"))
async def cmd_join(message: Message):
    if not is_admin_user(message.from_user.id):
        await message.answer("You don't have permission to use this command.")
        return

    if message.chat.type == "private":
        await message.answer("This command must be used in a group.")
        return

    # Тут title уже есть, не нужен get_chat
    if not is_driver_group(message.chat.title):
        await message.answer("This bot can only be added to driver groups.")
        return

    truck_number = get_truck_number(message.chat.title)
    if truck_number and db.add_driver_chat(message.chat.id, truck_number):
        await message.answer(f"Group added successfully (Truck #{truck_number})")
    else:
        await message.answer("This group is already added, or an error occurred.")


@router.message(Command("drivers"))
async def cmd_drivers(message: Message):
    if not is_admin_user(message.from_user.id):
        await message.answer("You don't have permission to use this command.")
        return

    driver_chats = db.get_all_drivers()
    if not driver_chats:
        await message.answer("The driver group list is empty.")
        return

    # Здесь get_chat допустим, потому что это не broadcast, а редкая команда.
    result = "📋 Driver group list:\n\n"
    for chat_id in driver_chats:
        try:
            chat = await bot.get_chat(chat_id)
            if is_driver_group(chat.title):
                result += f"• {chat.title}\n"
        except Exception as e:
            logger.error(f"Error getting chat info {chat_id}: {e}")

    await message.answer(result)


# -----------------------------
# Broadcast flow
# -----------------------------
@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if not is_admin_user(message.from_user.id):
        await message.answer("You don't have permission to use this command.")
        return

    await message.answer("Choose a broadcast type:", reply_markup=get_broadcast_type_keyboard())
    await state.set_state(AdminStates.broadcast_type)


@router.callback_query(F.data == "broadcast_text")
async def process_broadcast_text_type(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Enter the broadcast message text:", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.broadcast_text)
    await callback.answer()


@router.callback_query(F.data == "broadcast_photo")
async def process_broadcast_photo_type(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Send the photo to broadcast:", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.broadcast_photo)
    await callback.answer()


@router.callback_query(F.data == "broadcast_video")
async def process_broadcast_video_type(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Send the video to broadcast:", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.broadcast_video)
    await callback.answer()


@router.callback_query(F.data == "broadcast_pdf")
async def process_broadcast_pdf_type(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Send the PDF file to broadcast:", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.broadcast_pdf)
    await callback.answer()


@router.message(AdminStates.broadcast_text)
async def process_broadcast_text(message: Message, state: FSMContext):
    successful, failed = await broadcast_to_driver_chats_text(message.text)
    await message.answer(
        "📊 Broadcast results:\n"
        f"✅ Sent successfully: {successful}\n"
        f"❌ Failed: {failed}"
    )
    await state.clear()


@router.message(AdminStates.broadcast_photo, F.photo)
async def process_broadcast_photo(message: Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer(
        "Now enter a caption for the photo (or send /skip to broadcast without one):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(AdminStates.broadcast_caption)


@router.message(AdminStates.broadcast_photo)
async def process_invalid_photo(message: Message):
    await message.answer("Please send a photo.")


@router.message(AdminStates.broadcast_caption)
async def process_broadcast_caption(message: Message, state: FSMContext):
    data = await state.get_data()
    photo_id = data.get("photo_id")
    caption = None if message.text == "/skip" else message.text

    successful, failed = await broadcast_to_driver_chats_photo(photo_id, caption)

    await message.answer(
        "📊 Photo broadcast results:\n"
        f"✅ Sent successfully: {successful}\n"
        f"❌ Failed: {failed}"
    )
    await state.clear()


@router.message(AdminStates.broadcast_video, F.video)
async def process_broadcast_video_file(message: Message, state: FSMContext):
    await state.update_data(video_id=message.video.file_id)
    await message.answer(
        "Enter a caption for the video (or send /skip to broadcast without one):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(AdminStates.broadcast_video_caption)


@router.message(AdminStates.broadcast_video)
async def process_invalid_video(message: Message):
    await message.answer("Please send a video file.")


@router.message(AdminStates.broadcast_video_caption)
async def process_video_caption(message: Message, state: FSMContext):
    data = await state.get_data()
    video_id = data.get("video_id")
    caption = None if message.text == "/skip" else message.text

    successful, failed = await broadcast_to_driver_chats_video(video_id, caption)

    await message.answer(
        "📊 Video broadcast results:\n"
        f"✅ Sent successfully: {successful}\n"
        f"❌ Failed: {failed}"
    )
    await state.clear()


@router.message(AdminStates.broadcast_pdf, F.document)
async def process_broadcast_pdf_file(message: Message, state: FSMContext):
    doc = message.document

    if doc.mime_type != "application/pdf" and not (doc.file_name or "").lower().endswith(".pdf"):
        await message.answer("Please send an actual PDF file.")
        return

    await state.update_data(pdf_file_id=doc.file_id)
    await message.answer(
        "Enter a caption for the PDF (or send /skip to broadcast without one):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(AdminStates.broadcast_pdf_caption)


@router.message(AdminStates.broadcast_pdf)
async def process_invalid_pdf(message: Message):
    await message.answer("Please send the PDF as a document.")


@router.message(AdminStates.broadcast_pdf_caption)
async def process_broadcast_pdf_caption(message: Message, state: FSMContext):
    data = await state.get_data()
    pdf_file_id = data.get("pdf_file_id")
    caption = None if message.text == "/skip" else message.text

    successful, failed = await broadcast_to_driver_chats_pdf(pdf_file_id, caption)

    await message.answer(
        "📊 PDF broadcast results:\n"
        f"✅ Sent successfully: {successful}\n"
        f"❌ Failed: {failed}"
    )
    await state.clear()


@router.callback_query(F.data == "cancel_action")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await callback.message.edit_text("Action cancelled.")
    await callback.answer()


async def start_phillips_webhook(provider: PhillipsProvider):
    port = int(os.getenv("PHILLIPS_WEBHOOK_PORT", "8443"))
    app = create_webhook_app(provider)
    runner = web.AppRunner(app)
    await runner.setup()
    # bound to localhost only — Caddy terminates TLS on the public port and proxies here
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    logger.info(f"Phillips webhook listening on 127.0.0.1:{port}")


async def main():
    dp.include_router(router)
    dp.include_router(tracker_router)
    dp.include_router(fleet_router)
    dp.include_router(user_permission_router)

    set_db(db)
    set_location_db(db)
    set_trailer_cmd_db(db)
    set_lifecycle_db(db)
    dp.include_router(kick_router)
    dp.include_router(trailer_data_router)
    dp.include_router(location_router)
    dp.include_router(trailer_cmd_router)

    registry = ProviderRegistry()
    registry.register(Fus1onProvider())
    registry.register(SkyBitzProvider())
    phillips_provider = PhillipsProvider()
    registry.register(phillips_provider)
    set_trailer_cmd_registry(registry)

    setup_main_scheduler(bot, db, registry)
    await start_phillips_webhook(phillips_provider)

    logger.info("Initial trailer position poll...")
    await poll_trailer_positions(db, registry)

    while True:
        try:
            logger.info("Запуск polling...")
            await dp.start_polling(bot)
            break  # aiogram handled SIGINT/SIGTERM and returned cleanly — stop, don't restart
        except Exception as e:
            logger.exception(f"Ошибка polling: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
