import re
import logging
from typing import Optional, Dict, Any
from datetime import datetime
import asyncio

import gspread
from aiogram import Router, types
from aiogram.methods import SetMessageReaction
from aiogram.types import ReactionTypeEmoji
from oauth2client.service_account import ServiceAccountCredentials

from trailer_lifecycle import create_assignment, complete_assignment
from function import Database as _DbClass

# ---------------------------
# Логирование
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("trailer")

# ---------------------------
# Aiogram router
# ---------------------------
router = Router()

_lifecycle_db: _DbClass | None = None


def set_lifecycle_db(db: _DbClass):
    global _lifecycle_db
    _lifecycle_db = db

# ---------------------------
# Google Sheets client
# ---------------------------
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_ID = "11mm30FrLhV62qAlpqEIMxXwYk0vGcesxWYZ-UREh49s"

creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPES)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# ---------------------------
# Общие помощники
# ---------------------------
def normalize_headers(headers):
    """Карта UPPER -> оригинал."""
    return {h.strip().upper(): h for h in headers}

def column_letter_by_header(col_name: str) -> str:
    """A1-буква для колонки по имени заголовка из первой строки."""
    header_row = sheet.row_values(1)
    if col_name not in header_row:
        raise ValueError(f"Column '{col_name}' not found in header row")
    col_idx = header_row.index(col_name) + 1
    result = ""
    while col_idx > 0:
        col_idx, r = divmod(col_idx - 1, 26)
        result = chr(65 + r) + result
    return result

async def send_reaction_safe(msg, success: bool):
    """Ставим лайк/дизлайк в зависимости от результата."""
    emoji = "👍" if success else "👎"
    try:
        await msg.bot(
            SetMessageReaction(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
                is_big=False,
            )
        )
    except Exception as e:
        # Telegram вернёт REACTION_INVALID, если даже 👍/👎 недоступны
        log.warning("Не удалось поставить реакцию: %s", e)


# Разрешаем нормальные символы города и индекса
CITY_LINE_RE = re.compile(r"^[A-Za-z0-9 .&'()-]+,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?$")

# Хвостовая пунктуация, которую срезаем у значений
_PUNCT_TAIL = ",;:"

def _tidy(s: str) -> str:
    return s.strip().strip(_PUNCT_TAIL).strip()

def _format_driver(truck_number: str, driver: str) -> str:
    tn = str(truck_number or "").strip()
    tn = tn.lstrip("#")
    return f"#{tn} {str(driver or '').strip()}".strip()

# ---------------------------
# Регэкспы (терпимые к пунктуации)
# ---------------------------
PATTERN_TWO_LINE = re.compile(
    r"""
    ^\s*#(?P<kind>pick|drop)\s*[,;:]?\s*[\r\n]+
    \s*TRAILER:\s*(?P<trailer>[A-Za-z0-9#/\-_.\s]+?)\s*[,;:]?\s*[\r\n]+
    (?:\s*DATE:\s*(?P<date>[^\r\n]+?)\s*[,;:]?\s*[\r\n]+)?      # опционален
    \s*LOCATION:\s*(?P<line1>[^\r\n]+?)\s*[,;:]?\s*[\r\n]+
    (?P<line2>[^\r\n]+?)\s*[,;:]?\s*[\r\n]+
    \s*TRUCK:\s*(?P<truck>[A-Za-z0-9#\-]+?)\s*[,;:]?\s*[\r\n]+
    \s*DRIVER:\s*(?P<driver>.+?)\s*\Z
    """,
    re.I | re.VERBOSE | re.DOTALL,
)

PATTERN_ONE_LINE = re.compile(
    r"""
    ^\s*#(?P<kind>pick|drop)\s*[,;:]?\s*[\r\n]+
    \s*TRAILER:\s*(?P<trailer>[A-Za-z0-9#/\-_.\s]+?)\s*[,;:]?\s*[\r\n]+
    (?:\s*DATE:\s*(?P<date>[^\r\n]+?)\s*[,;:]?\s*[\r\n]+)?      # опционален
    \s*LOCATION:\s*(?P<loc>[^\r\n]+?)\s*[,;:]?\s*[\r\n]+
    \s*TRUCK:\s*(?P<truck>[A-Za-z0-9#\-]+?)\s*[,;:]?\s*[\r\n]+
    \s*DRIVER:\s*(?P<driver>.+?)\s*\Z
    """,
    re.I | re.VERBOSE | re.DOTALL,
)

# ---------------------------
# Парсер
# ---------------------------
def parse_message(text: str) -> Optional[Dict[str, Any]]:
    """Распарсить блок #pick/#drop без шизофренических регэкспов."""
    if not isinstance(text, str):
        return None

    src = text.strip()
    if not src:
        return None

    # Режем на строки, выкидываем пустые
    raw_lines = src.splitlines()
    lines = [l.rstrip() for l in raw_lines if l.strip()]
    if not lines:
        return None

    first = lines[0].strip().lower()
    if first not in ("#pick", "#drop"):
        return None

    kind = first[1:]  # "pick" / "drop"
    status = "DRIVING" if kind == "pick" else "DROPPED"

    trailer_id = None
    date_str = None
    location = None
    truck_number = None
    driver = None

    i = 1
    while i < len(lines):
        line = lines[i].strip()
        upper = line.upper()

        if upper.startswith("TRAILER:"):
            trailer_id = _tidy(line.split(":", 1)[1])

        elif upper.startswith("DATE:"):
            date_str = _tidy(line.split(":", 1)[1])

        elif upper.startswith("LOCATION:"):
            # первая строка после LOCATION:
            loc_first = line.split(":", 1)[1].strip()
            extra = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if nxt.upper().startswith("TRUCK:"):
                    break
                extra.append(nxt)
                j += 1
            if extra:
                loc_full = loc_first + "\n" + "\n".join(extra)
            else:
                loc_full = loc_first
            location = _tidy(loc_full)
            # не забываем, что цикл while дальше сам увеличит i
        elif upper.startswith("TRUCK:"):
            truck_number = _tidy(line.split(":", 1)[1])

        elif upper.startswith("DRIVER:"):
            driver = _tidy(line.split(":", 1)[1])

        i += 1

    # Легкая валидация
    if not trailer_id or not location or not truck_number or not driver:
        log.warning(
            "Missing required fields in message (trailer=%r, loc=%r, truck=%r, driver=%r):\n%s",
            trailer_id, location, truck_number, driver, text,
        )
        return None

    # Если локация многострочная, вторая строка может быть city+state+zip, можно её проверить
    if "\n" in location:
        addr_lines = location.splitlines()
        city_line = addr_lines[-1].strip()
        if not CITY_LINE_RE.match(city_line):
            log.warning("City line didn't match expected pattern: %r", city_line)

    return {
        "trailer_id": trailer_id,
        "status": status,
        "location": location,
        "truck_number": truck_number,
        "driver": driver,
        "date_str": date_str,
    }


# ---------------------------
# Запись в таблицу (в тред)
# ---------------------------
def update_trailer_sync(
    trailer_id: str,
    status: str,
    location: str,
    truck_number: str,
    driver: str,
    date_str: Optional[str] = None,
) -> bool:
    """Синхронная работа с gspread, вызывается через to_thread."""
    try:
        driver_formatted = _format_driver(truck_number, driver)
        date_out = date_str or datetime.now().strftime("%Y-%m-%d %H:%M")

        records = sheet.get_all_records()
        headers_map = normalize_headers(sheet.row_values(1))

        trailer_col_name = headers_map.get("TRAILER")
        status_col_name = headers_map.get("STATUS")
        location_col_name = headers_map.get("LOCATION")
        driver_col_name = headers_map.get("DRIVER")
        date_col_name = headers_map.get("DATE")

        if not trailer_col_name:
            log.error("Table has no 'TRAILER' column")
            return False

        # поиск строки по колонке TRAILER
        for i, row in enumerate(records, start=2):
            if str(row.get(trailer_col_name, "")).strip().upper() == str(trailer_id).strip().upper():
                updates = []
                if status_col_name:
                    updates.append({
                        "range": f"{column_letter_by_header(status_col_name)}{i}",
                        "values": [[status]]
                    })
                if location_col_name:
                    updates.append({
                        "range": f"{column_letter_by_header(location_col_name)}{i}",
                        "values": [[location]]
                    })
                if driver_col_name:
                    updates.append({
                        "range": f"{column_letter_by_header(driver_col_name)}{i}",
                        "values": [[driver_formatted]]
                    })
                if date_col_name:
                    updates.append({
                        "range": f"{column_letter_by_header(date_col_name)}{i}",
                        "values": [[date_out]]
                    })

                if updates:
                    sheet.batch_update(updates)

                log.info(
                    "Updated trailer=%s status=%s driver=%s date=%s",
                    trailer_id, status, driver_formatted, date_out
                )
                return True

        log.warning("Trailer %s not found", trailer_id)
        return False

    except Exception as e:
        log.exception("Sheet update failed: %s", e)
        return False

async def update_trailer(
    trailer_id: str,
    status: str,
    location: str,
    truck_number: str,
    driver: str,
    date_str: Optional[str] = None,
) -> bool:
    return await asyncio.to_thread(
        update_trailer_sync,
        trailer_id, status, location, truck_number, driver, date_str
    )

# ---------------------------
# Хэндлер
# ---------------------------
# триггерим только если после #pick/#drop сразу перенос строки или конец
_TRIGGER = re.compile(r"^(#pick|#drop)\s*(?:[,;:]?\s*(?:\r?\n|$))", re.I)

@router.message(
    lambda message: isinstance(getattr(message, "text", None), str)
    and _TRIGGER.match(message.text or "")
)
async def handle_message(message: types.Message):
    """Обработка команд #pick/#drop: реакции без спама в чат."""
    try:
        log.info("Got message: %r", message.text)
        parsed = parse_message(message.text)
        if not parsed:
            await send_reaction_safe(message, False)
            return

        ok = await update_trailer(**parsed)
        await send_reaction_safe(message, ok)

        if ok and _lifecycle_db:
            try:
                if parsed["status"] == "DRIVING":
                    a_id = create_assignment(
                        _lifecycle_db,
                        trailer_id=parsed["trailer_id"],
                        truck_number=parsed["truck_number"],
                        driver_name=parsed["driver"],
                        pick_location=parsed["location"],
                        chat_id=message.chat.id,
                    )
                    await message.answer(
                        f"📦 Трейлер `{parsed['trailer_id']}` забран \\#{parsed['truck_number']}\\.\n"
                        f"Когда возвращать? Ответьте:\n"
                        f"`/set_return {parsed['trailer_id']} YYYY\\-MM\\-DD Локация`",
                        parse_mode="MarkdownV2",
                    )
                elif parsed["status"] == "DROPPED":
                    complete_assignment(
                        _lifecycle_db,
                        trailer_id=parsed["trailer_id"],
                        drop_location=parsed["location"],
                    )
            except Exception as e:
                log.error("Lifecycle update failed: %s", e)

    except Exception as e:
        log.exception("Handle message failed: %s", e)
        await send_reaction_safe(message, False)
