# kick_user.py
import logging
from typing import Optional

from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.enums import ChatMemberStatus  # <-- ВАЖНО: enum из aiogram.enums

from user_permission import is_admin
from function import Database

kick_router = Router()
_db: Optional[Database] = None

def set_db(db: Database) -> None:
    global _db
    _db = db

@kick_router.message(Command("kick_user"))
async def cmd_kick_user(message: types.Message, bot: Bot):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.reply("❌ You don't have permission for this command.")
        return

    # цель: reply приоритетнее, иначе аргумент
    target_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 2 and parts[1].isdigit():
            target_id = int(parts[1])

    if not target_id:
        await message.reply("⚠ Provide an ID or reply to the user's message.\nExample: `/kick_user 123456789`",
                            parse_mode="Markdown")
        return
    if _db is None:
        await message.reply("❌ Database not initialized.")
        return
    if target_id == bot.id:
        await message.reply("🙂 Not going to kick myself.")
        return

    await message.reply(f"🚀 Removing user `{target_id}` from groups...", parse_mode="Markdown")

    chat_ids = _db.get_all_drivers()  # список чатов-водителей из БД
    total = len(chat_ids)
    success = 0
    skipped_not_admin = 0
    skipped_target_admin = 0
    skipped_not_member = 0
    errors = 0

    for chat_id in chat_ids:
        try:
            # права бота
            me = await bot.get_chat_member(chat_id, bot.id)
            if me.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
                skipped_not_admin += 1
                continue
            if me.status == ChatMemberStatus.ADMINISTRATOR:
                if not getattr(me, "can_restrict_members", False):
                    skipped_not_admin += 1
                    continue

            # статус цели
            target = await bot.get_chat_member(chat_id, target_id)
            if target.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
                skipped_target_admin += 1
                continue
            if target.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                # его уже нет в чате — пропускаем как «не участник»
                skipped_not_member += 1
                continue

            # кик (бан+разбан, чтобы можно было вернуться, если надо)
            await bot.ban_chat_member(chat_id, target_id)
            await bot.unban_chat_member(chat_id, target_id)
            success += 1

        except Exception as e:
            logging.warning(f"Failed to kick {target_id} from {chat_id}: {e}")
            errors += 1

    await message.reply(
        "✅ Done.\n"
        f"• Kicked from: {success}\n"
        f"• Skipped (bot not admin/no restrict permission): {skipped_not_admin}\n"
        f"• Skipped (target is admin/creator): {skipped_target_admin}\n"
        f"• Skipped (target not in chat): {skipped_not_member}\n"
        f"• Errors: {errors}\n"
        f"• Total groups in DB: {total}"
    )
