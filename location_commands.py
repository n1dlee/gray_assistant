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
        await message.answer("You don't have permission for this command.")
        return

    landmarks = _db.get_landmarks()
    if not landmarks:
        await message.answer("📍 No active landmarks.")
        return

    lines = ["📍 *Active landmarks:*\n"]
    for lm in landmarks:
        lm_id, name, lat, lon, radius, address, _, _ = lm
        line = f"*{lm_id}.* {name}\n   📡 {lat}, {lon} (radius: {radius}m)"
        if address:
            line += f"\n   🏠 {address}"
        lines.append(line)

    await message.answer("\n\n".join(lines), parse_mode="Markdown")


@location_router.message(Command("add_landmark"))
async def cmd_add_landmark(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("You don't have permission for this command.")
        return

    if not command.args:
        await message.answer(
            "⚠️ Format: `/add_landmark Name Lat Lon [Radius]`\n"
            "Example: `/add_landmark GrayYard 32.7767 -96.7970 300`",
            parse_mode="Markdown",
        )
        return

    parts = command.args.split()
    if len(parts) < 3:
        await message.answer("⚠️ Need at least 3 arguments: name, latitude, longitude.")
        return

    name = parts[0]
    try:
        lat = float(parts[1])
        lon = float(parts[2])
    except ValueError:
        await message.answer("⚠️ Latitude and longitude must be numbers.")
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
            f"✅ Landmark added (ID: {lm_id})\n"
            f"📍 {name}: {lat}, {lon} (radius: {radius}m)"
        )
    else:
        await message.answer("❌ Error adding landmark.")


@location_router.message(Command("edit_landmark"))
async def cmd_edit_landmark(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("You don't have permission for this command.")
        return

    if not command.args:
        await message.answer(
            "⚠️ Format: `/edit_landmark ID name=New radius=500`",
            parse_mode="Markdown",
        )
        return

    parts = command.args.split()
    try:
        lm_id = int(parts[0])
    except ValueError:
        await message.answer("⚠️ First argument must be the landmark ID (number).")
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
        await message.answer("⚠️ No parameters given to update. Example: `name=NewName radius=300`")
        return

    if _db.update_landmark(lm_id, **kwargs):
        await message.answer(f"✅ Landmark {lm_id} updated.")
    else:
        await message.answer(f"❌ Landmark {lm_id} not found or not updated.")


@location_router.message(Command("remove_landmark"))
async def cmd_remove_landmark(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("You don't have permission for this command.")
        return

    if not command.args:
        await message.answer("⚠️ Provide a landmark ID: `/remove_landmark 1`", parse_mode="Markdown")
        return

    try:
        lm_id = int(command.args.strip())
    except ValueError:
        await message.answer("⚠️ ID must be a number.")
        return

    if _db.deactivate_landmark(lm_id):
        await message.answer(f"🗑 Landmark {lm_id} removed.")
    else:
        await message.answer(f"❌ Landmark {lm_id} not found.")
