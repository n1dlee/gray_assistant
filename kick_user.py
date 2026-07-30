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
        await message.reply("❌ У вас нет прав на эту команду.")
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
        await message.reply("⚠ Укажи ID или сделай reply на сообщение пользователя.\nПример: `/kick_user 123456789`",
                            parse_mode="Markdown")
        return
    if _db is None:
        await message.reply("❌ База данных не инициализирована.")
        return
    if target_id == bot.id:
        await message.reply("🙂 Самого себя кикать не буду.")
        return

    await message.reply(f"🚀 Начинаю удалять пользователя `{target_id}` из групп...", parse_mode="Markdown")

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
            logging.warning(f"Не удалось кикнуть {target_id} из {chat_id}: {e}")
            errors += 1

    await message.reply(
        "✅ Готово.\n"
        f"• Кикнут из: {success}\n"
        f"• Пропущено (бот не админ/нет права ограничивать): {skipped_not_admin}\n"
        f"• Пропущено (цель админ/создатель): {skipped_target_admin}\n"
        f"• Пропущено (цели нет в чате): {skipped_not_member}\n"
        f"• Ошибок: {errors}\n"
        f"• Всего групп в БД: {total}"
    )
