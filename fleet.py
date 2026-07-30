import os
import re
import time
import aiohttp
from dotenv import load_dotenv
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from user_permission import is_admin

load_dotenv()

router = Router()

TTELD_USDOT = os.getenv("TTELD_USDOT", "3589205")
TTELD_API_KEY = os.getenv("TTELD_API_KEY", "")
TTELD_PROVIDER_TOKEN = os.getenv("TTELD_PROVIDER_TOKEN", "")
TTELD_API_URL = f"https://read.tteld.com/api/v2/units-by-usdot/{TTELD_USDOT}"

TRUCKS_PER_PAGE = 10
CACHE_TTL = 120

_cache_data = []
_cache_time = 0.0


def _sort_key(v: dict) -> tuple:
    raw = re.sub(r'[^0-9]', '', str(v.get("truck_number", "")))
    return (0, int(raw)) if raw else (1, str(v.get("truck_number", "")))


async def get_all_units_data() -> list:
    global _cache_data, _cache_time

    if _cache_data and (time.monotonic() - _cache_time) < CACHE_TTL:
        return _cache_data

    if not TTELD_API_KEY:
        return _cache_data or []

    headers = {
        "x-api-key": TTELD_API_KEY,
        "provider-token": TTELD_PROVIDER_TOKEN,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(TTELD_API_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
                data = await resp.json()
                items = data.get("units", [])
                _cache_data = sorted(items, key=_sort_key)
                _cache_time = time.monotonic()
                return _cache_data
    except Exception:
        return _cache_data or []


def format_truck_data(vehicles: list, page: int = 0) -> str:
    start = page * TRUCKS_PER_PAGE
    end = start + TRUCKS_PER_PAGE
    selected = vehicles[start:end]

    if not selected:
        return "Нет данных на этой странице."

    lines = []
    for v in selected:
        unit = str(v.get("truck_number", "")).strip()
        coords = v.get("coordinates", {})
        lat = coords.get("lat")
        lon = coords.get("lng")

        if not unit or lat is None or lon is None:
            continue

        lines.append(
            f"🚛 *Unit {unit}*\n"
            f"📍 {lat}, {lon}\n"
            f"🔗 [Google Maps](https://www.google.com/maps?q={lat},{lon})"
        )

    return "\n\n".join(lines) if lines else "Нет данных с координатами."


def get_pagination_keyboard(page: int, total: int):
    buttons = []
    if (page + 1) * TRUCKS_PER_PAGE < total:
        buttons.append(InlineKeyboardButton(text="➡️ Следующая", callback_data=f"fleet_page:{page + 1}"))
    if page > 0:
        buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"fleet_page:{page - 1}"))

    if buttons:
        return InlineKeyboardMarkup(inline_keyboard=[buttons])
    return None


@router.message(Command("fleet"))
async def cmd_fleet(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав для использования этой команды.")
        return

    vehicles = await get_all_units_data()
    total = len(vehicles)

    if not total:
        await message.answer("❌ Не удалось получить данные с TTELD API.")
        return

    text = format_truck_data(vehicles, page=0)
    keyboard = get_pagination_keyboard(0, total)
    total_pages = (total + TRUCKS_PER_PAGE - 1) // TRUCKS_PER_PAGE

    await message.answer(
        f"📋 *Флот ({total} траков, стр. 1/{total_pages})*\n\n{text}",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("fleet_page:"))
async def callback_fleet_page(callback: types.CallbackQuery):
    page = int(callback.data.split(":")[1])
    vehicles = await get_all_units_data()
    total = len(vehicles)
    total_pages = (total + TRUCKS_PER_PAGE - 1) // TRUCKS_PER_PAGE

    text = format_truck_data(vehicles, page)
    keyboard = get_pagination_keyboard(page, total)

    await callback.message.edit_text(
        f"📋 *Флот ({total} траков, стр. {page + 1}/{total_pages})*\n\n{text}",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    await callback.answer()
