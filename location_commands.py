import logging

from aiogram import Router, types
from aiogram.filters import Command, CommandObject

from user_permission import is_admin
from function import Database

logger = logging.getLogger(__name__)
location_router = Router(name="location_commands")

_db: Database | None = None


def set_db(db: Database):
    global _db
    _db = db


@location_router.message(Command("landmarks"))
async def cmd_landmarks(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return

    landmarks = _db.get_landmarks()
    if not landmarks:
        await message.answer("📍 Нет активных локаций.")
        return

    lines = ["📍 *Активные локации:*\n"]
    for lm in landmarks:
        lm_id, name, lat, lon, radius, address, _, _ = lm
        line = f"*{lm_id}.* {name}\n   📡 {lat}, {lon} (радиус: {radius}м)"
        if address:
            line += f"\n   🏠 {address}"
        lines.append(line)

    await message.answer("\n\n".join(lines), parse_mode="Markdown")


@location_router.message(Command("add_landmark"))
async def cmd_add_landmark(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return

    if not command.args:
        await message.answer(
            "⚠️ Формат: `/add_landmark Название Лат Лон [Радиус]`\n"
            "Пример: `/add_landmark GrayYard 32.7767 -96.7970 300`",
            parse_mode="Markdown",
        )
        return

    parts = command.args.split()
    if len(parts) < 3:
        await message.answer("⚠️ Нужно минимум 3 аргумента: название, широта, долгота.")
        return

    name = parts[0]
    try:
        lat = float(parts[1])
        lon = float(parts[2])
    except ValueError:
        await message.answer("⚠️ Широта и долгота должны быть числами.")
        return

    radius = 200.0
    if len(parts) >= 4:
        try:
            radius = float(parts[3])
        except ValueError:
            pass

    lm_id = _db.add_landmark(
        name=name, latitude=lat, longitude=lon,
        radius_meters=radius, created_by=message.from_user.id,
    )

    if lm_id > 0:
        await message.answer(
            f"✅ Локация добавлена (ID: {lm_id})\n"
            f"📍 {name}: {lat}, {lon} (радиус: {radius}м)"
        )
    else:
        await message.answer("❌ Ошибка при добавлении локации.")


@location_router.message(Command("edit_landmark"))
async def cmd_edit_landmark(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return

    if not command.args:
        await message.answer(
            "⚠️ Формат: `/edit_landmark ID name=Новое radius=500`",
            parse_mode="Markdown",
        )
        return

    parts = command.args.split()
    try:
        lm_id = int(parts[0])
    except ValueError:
        await message.answer("⚠️ Первый аргумент — ID локации (число).")
        return

    kwargs = {}
    for part in parts[1:]:
        if "=" in part:
            key, val = part.split("=", 1)
            key = key.strip().lower()
            if key == "name":
                kwargs["name"] = val
            elif key == "radius":
                try:
                    kwargs["radius_meters"] = float(val)
                except ValueError:
                    pass

    if not kwargs:
        await message.answer("⚠️ Не указаны параметры для изменения. Пример: `name=NewName radius=300`")
        return

    if _db.update_landmark(lm_id, **kwargs):
        await message.answer(f"✅ Локация {lm_id} обновлена.")
    else:
        await message.answer(f"❌ Локация {lm_id} не найдена или не обновлена.")


@location_router.message(Command("remove_landmark"))
async def cmd_remove_landmark(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return

    if not command.args:
        await message.answer("⚠️ Укажите ID локации: `/remove_landmark 1`", parse_mode="Markdown")
        return

    try:
        lm_id = int(command.args.strip())
    except ValueError:
        await message.answer("⚠️ ID должен быть числом.")
        return

    if _db.deactivate_landmark(lm_id):
        await message.answer(f"🗑 Локация {lm_id} удалена.")
    else:
        await message.answer(f"❌ Локация {lm_id} не найдена.")
