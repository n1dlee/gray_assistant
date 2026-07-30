import os
import aiohttp
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

from aiogram import Router, types
from aiogram.filters import CommandObject, Command
from user_permission import is_admin

load_dotenv()

router = Router()

TTELD_PROVIDER_TOKEN = os.getenv("TTELD_PROVIDER_TOKEN", "")

GRAY_USDOT = os.getenv("TTELD_USDOT", "3589205")
GRAY_API_KEY = os.getenv("TTELD_API_KEY", "")

OMEGA_USDOT = os.getenv("TTELD_OMEGA_USDOT", "3663222")
OMEGA_API_KEY = os.getenv("TTELD_OMEGA_API_KEY", "")


def _normalize(s: str) -> str:
    return s.lstrip("#").strip()


def _fmt_time(iso_str: str) -> str:
    if not iso_str:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%m/%d/%Y %H:%M UTC")
    except Exception:
        return iso_str


def _format_vehicle(v: dict) -> str:
    unit = str(v.get("truck_number", "")).strip()
    coords = v.get("coordinates", {})
    lat = coords.get("lat")
    lng = coords.get("lng")
    vin = v.get("vin", "N/A")
    updated = _fmt_time(v.get("timestamp", ""))
    fuel = v.get("fuelLevelPercent")

    if lat is None or lng is None:
        return f"⚠ Координаты не найдены для Unit {unit}"

    lines = [
        f"🆔 <b>Unit:</b> {unit}",
        f"🚗 <b>VIN:</b> {vin}",
        f"📍 <b>Координаты:</b> {lat}, {lng}",
        f"🕒 <b>Обновлено:</b> {updated}",
    ]
    if fuel is not None:
        lines.append(f"⛽ <b>Топливо:</b> {fuel:.0f}%")
    lines.append(
        f'\n🔗 <a href="https://www.google.com/maps?q={lat},{lng}">Открыть в Google Maps</a>'
    )
    return "\n".join(lines)


def _match_unit(v: dict, query: str) -> bool:
    unit_raw = str(v.get("truck_number", "")).strip()
    return _normalize(query) == unit_raw


async def _fetch_fleet(api_key: str, usdot: str) -> Optional[list]:
    if not api_key:
        return None
    url = f"https://read.tteld.com/api/v2/units-by-usdot/{usdot}"
    headers = {
        "x-api-key": api_key,
        "provider-token": TTELD_PROVIDER_TOKEN,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status >= 400:
                    return None
                data = await resp.json()
                return data.get("units", [])
    except Exception:
        return None


async def _handle_location(message: types.Message, command: CommandObject,
                           api_key: str, usdot: str, fleet_name: str):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для использования этой команды.")
        return

    if not command.args:
        await message.answer(
            f"⚠ Укажи номер юнита. Пример: <code>/{fleet_name.lower()} 22203</code>",
            parse_mode="HTML",
        )
        return

    query = command.args.strip()

    vehicles = await _fetch_fleet(api_key, usdot)
    if vehicles is None:
        await message.answer(f"❌ Ошибка при запросе к TTELD API ({fleet_name}). Попробуй позже.")
        return

    for v in vehicles:
        if _match_unit(v, query):
            await message.answer(_format_vehicle(v), parse_mode="HTML", disable_web_page_preview=True)
            return

    await message.answer(
        f"🚫 Юнит <code>{query}</code> не найден в {fleet_name}.\n"
        f"Всего активных траков: {len(vehicles)}",
        parse_mode="HTML",
    )


@router.message(Command(commands=["location"]))
async def cmd_location(message: types.Message, command: CommandObject):
    await _handle_location(message, command, GRAY_API_KEY, GRAY_USDOT, "GRAY")


@router.message(Command(commands=["omega"]))
async def cmd_omega(message: types.Message, command: CommandObject):
    await _handle_location(message, command, OMEGA_API_KEY, OMEGA_USDOT, "OMEGA")
