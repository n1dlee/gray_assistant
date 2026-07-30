import time
import logging
from datetime import datetime

from aiogram import Router, types
from aiogram.filters import Command, CommandObject

from user_permission import is_admin
from function import Database
from trailer_lifecycle import set_return_deadline, get_overdue_returns
from providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)
trailer_cmd_router = Router(name="trailer_commands")

_db: Database | None = None
_registry: ProviderRegistry | None = None

CACHE_TTL_SEC = 20 * 60
_last_poll_time: float = 0.0


def set_db(db: Database):
    global _db
    _db = db


def set_registry(registry: ProviderRegistry):
    global _registry
    _registry = registry


async def _ensure_fresh_data():
    global _last_poll_time
    if _registry is None:
        return
    if time.monotonic() - _last_poll_time < CACHE_TTL_SEC:
        return

    try:
        positions = await _registry.get_all_positions()
        for pos in positions:
            _db.upsert_trailer_position(
                trailer_id=pos.trailer_id,
                provider=pos.provider_name or "unknown",
                latitude=pos.latitude,
                longitude=pos.longitude,
                speed=pos.speed,
                raw_status=pos.raw_status,
            )
        _last_poll_time = time.monotonic()
        logger.info("On-demand trailer poll: %d positions refreshed", len(positions))
    except Exception as e:
        logger.error("On-demand trailer poll failed: %s", e)


@trailer_cmd_router.message(Command("trailers"))
async def cmd_trailers(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return

    assignments = _db.get_active_assignments()
    if not assignments:
        await message.answer("Нет активных назначений трейлеров.")
        return

    lines = ["*Активные назначения трейлеров:*\n"]
    for a in assignments[:20]:
        a_id, trailer_id, truck, driver, _, pick_time, ret_loc, ret_deadline, _, _, status, _, _ = a
        line = f"*{trailer_id}* — {status}"
        if truck:
            line += f" | Трак: #{truck}"
        if driver:
            line += f" | {driver}"
        if ret_deadline:
            line += f"\n   Возврат до: {ret_deadline}"
        lines.append(line)

    await message.answer("\n\n".join(lines), parse_mode="Markdown")


@trailer_cmd_router.message(Command("trailer"))
async def cmd_trailer_detail(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return

    if not command.args:
        await message.answer("Укажите ID трейлера: `/trailer EJGZ381046`", parse_mode="Markdown")
        return

    raw_input = command.args.strip()
    trailer_id = raw_input.upper()

    await _ensure_fresh_data()

    assignment = _db.get_active_assignment(trailer_id)
    if not assignment:
        assignment = _db.get_active_assignment(raw_input)

    position = _db.get_trailer_position(trailer_id)
    if not position:
        position = _db.get_trailer_position(raw_input)

    if not assignment and not position:
        if raw_input.isdigit() and len(raw_input) <= 5:
            await message.answer(
                f"`{raw_input}` похож на номер трака, а не трейлера.\n"
                f"Для траков используйте: `/location {raw_input}`",
                parse_mode="Markdown",
            )
        else:
            all_positions = _db.get_trailer_positions()
            known_ids = [p[0] for p in all_positions]
            matches = [t for t in known_ids if trailer_id in t.upper()]
            if matches:
                match_list = ", ".join(f"`{m}`" for m in matches[:10])
                await message.answer(
                    f"Трейлер `{raw_input}` не найден.\n"
                    f"Похожие: {match_list}",
                    parse_mode="Markdown",
                )
            else:
                await message.answer(
                    f"Трейлер `{raw_input}` не найден.",
                    parse_mode="Markdown",
                )
        return

    lines = [f"*Трейлер: {trailer_id}*\n"]

    if position:
        _, provider, lat, lon, speed, raw_status, updated = position
        lines.append(f"Позиция: {lat}, {lon}")
        lines.append(f"[Google Maps](https://www.google.com/maps?q={lat},{lon})")
        lines.append(f"Провайдер: {provider}")
        if speed is not None:
            lines.append(f"Скорость: {speed}")
        if raw_status:
            lines.append(f"Статус: {raw_status}")
        lines.append(f"Обновлено: {updated}")

    if assignment:
        lines.append("")
        a_id, _, truck, driver, pick_loc, pick_time, ret_loc, ret_deadline, _, _, status, _, _ = assignment
        lines.append(f"*Назначение:* {status}")
        if truck:
            lines.append(f"Трак: #{truck}")
        if driver:
            lines.append(f"Водитель: {driver}")
        if pick_loc:
            lines.append(f"Pickup: {pick_loc}")
        if pick_time:
            lines.append(f"Забран: {pick_time}")
        if ret_deadline:
            lines.append(f"Возврат до: {ret_deadline}")
        if ret_loc:
            lines.append(f"Возврат в: {ret_loc}")

    await message.answer("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)


@trailer_cmd_router.message(Command("set_return"))
async def cmd_set_return(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return

    if not command.args:
        await message.answer(
            "Формат: `/set_return TRAILER_ID ДАТА [ЛОКАЦИЯ]`\n"
            "Пример: `/set_return EJGZ381046 2026-06-20 Dallas, TX`",
            parse_mode="Markdown",
        )
        return

    parts = command.args.split(None, 2)
    if len(parts) < 2:
        await message.answer("Нужно минимум: trailer_id и дата.")
        return

    trailer_id = parts[0].strip()
    date_str = parts[1].strip()
    location = parts[2].strip() if len(parts) > 2 else None

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await message.answer("Формат даты: `YYYY-MM-DD`", parse_mode="Markdown")
        return

    assignment = _db.get_active_assignment(trailer_id)
    if not assignment:
        await message.answer(f"Нет активного назначения для `{trailer_id}`.", parse_mode="Markdown")
        return

    ok = set_return_deadline(_db, assignment[0], date_str, location)
    if ok:
        msg = f"Дедлайн возврата установлен:\n{trailer_id}\n{date_str}"
        if location:
            msg += f"\n{location}"
        await message.answer(msg)
    else:
        await message.answer("Ошибка при установке дедлайна.")


@trailer_cmd_router.message(Command("overdue"))
async def cmd_overdue(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return

    overdue = get_overdue_returns(_db)
    if not overdue:
        await message.answer("Нет просроченных возвратов.")
        return

    lines = ["*Просроченные возвраты:*\n"]
    for a in overdue:
        _, trailer_id, truck, driver, _, _, ret_loc, ret_deadline, _, _, status, _, _ = a
        line = f"*{trailer_id}*\n   Дедлайн: {ret_deadline}"
        if truck:
            line += f"\n   Трак: #{truck}"
        if driver:
            line += f"\n   {driver}"
        if ret_loc:
            line += f"\n   Возврат в: {ret_loc}"
        lines.append(line)

    await message.answer("\n\n".join(lines), parse_mode="Markdown")
