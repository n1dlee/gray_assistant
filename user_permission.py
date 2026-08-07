# user_permission.py
"""
Роутер управления доступом (через .env)

Команды:
  /add_user <id|@username>     — добавить пользователя в ALLOWED_USER_IDS
  /remove_user <id|@username>  — удалить пользователя из ALLOWED_USER_IDS

Требует:
  pip install aiogram python-dotenv

В .env:
  BOT_TOKEN=...
  ADMIN_IDS=12345,67890
  ALLOWED_USER_IDS=111,222,333   # можно пусто
"""

import os
import asyncio
from typing import Optional, Tuple

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv, set_key

# ---------- init ----------
ENV_PATH = os.getenv("ENV_PATH", ".env")
load_dotenv(ENV_PATH, override=False)

user_permission_router = Router(name="user_permission")
_env_lock = asyncio.Lock()  # защита от гонок при одновременной записи


# ---------- helpers ----------
def _parse_ids(csv_str: str) -> set[int]:
    ids: set[int] = set()
    if not csv_str:
        return ids
    for chunk in csv_str.split(","):
        s = chunk.strip()
        # допускаем только целые положительные ID телеграма
        if s.isdigit():
            ids.add(int(s))
    return ids


def _ids_to_csv(ids: set[int]) -> str:
    return ",".join(str(x) for x in sorted(ids))


def get_admin_ids() -> set[int]:
    from dotenv import load_dotenv
    load_dotenv(override=True)
    return {
        int(x.strip())
        for x in os.getenv("ADMIN_IDS", "").split(",")
        if x.strip().isdigit()
    }


def get_allowed_user_ids() -> set[int]:
    from dotenv import load_dotenv
    load_dotenv(override=True)
    return {
        int(x.strip())
        for x in os.getenv("ALLOWED_USER_IDS", "").split(",")
        if x.strip().isdigit()
    }


def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids() or user_id in get_allowed_user_ids()



async def _update_env_variable(key: str, new_value: str) -> None:
    """Атомично обновляет .env и текущее окружение процесса."""
    async with _env_lock:
        set_key(ENV_PATH, key, new_value)     # записали на диск
        os.environ[key] = new_value           # обновили env в процессе
        load_dotenv(ENV_PATH, override=True)  # чтобы будущие getenv читали новое


def _is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in get_admin_ids())


async def _resolve_target_id(message: Message) -> Tuple[Optional[int], Optional[str]]:
    """
    Определяем пользователя:
      1) reply → author
      2) числовой ID из аргумента
      3) @username через get_chat
    """
    # 1) reply
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, f"{u.full_name} ({u.id})"

    # 2) аргумент
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    if arg:
        if arg.isdigit():
            return int(arg), f"user_id {arg}"
        if arg.startswith("@") and len(arg) > 1:
            try:
                chat = await message.bot.get_chat(arg)
                if chat and chat.id:
                    label = f"{chat.full_name or chat.username or chat.id} ({chat.id})"
                    return chat.id, label
            except Exception:
                return None, None

    return None, None


def is_user_allowed(user_id: int) -> bool:
    """Проверка допуска по ALLOWED_USER_IDS."""
    return user_id in get_allowed_user_ids()


# ---------- commands ----------
@user_permission_router.message(Command("add_user"))
async def cmd_add_user(message: Message):
    if not _is_admin(message):
        await message.reply("❌ You don't have permission for this command.")
        return

    target_id, label = await _resolve_target_id(message)
    if not target_id:
        await message.reply("⚠️ Provide an ID, @username, or reply to a message.")
        return

    allowed = get_allowed_user_ids()
    if target_id in allowed:
        await message.reply(f"⚠️ Already in the list: {label}")
        return

    allowed.add(target_id)
    await _update_env_variable("ALLOWED_USER_IDS", _ids_to_csv(allowed))
    await message.reply(f"✅ Access granted: {label}")


@user_permission_router.message(Command("remove_user"))
async def cmd_remove_user(message: Message):
    if not _is_admin(message):
        await message.reply("❌ You don't have permission for this command.")
        return

    target_id, label = await _resolve_target_id(message)
    if not target_id:
        await message.reply("⚠️ Provide an ID, @username, or reply to a message.")
        return

    allowed = get_allowed_user_ids()
    if target_id not in allowed:
        await message.reply(f"⚠️ User not found in the list: {label}")
        return

    allowed.remove(target_id)
    await _update_env_variable("ALLOWED_USER_IDS", _ids_to_csv(allowed))
    await message.reply(f"🗑 Access removed: {label}")
