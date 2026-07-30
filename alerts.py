import os
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from dotenv import load_dotenv

from function import Database

load_dotenv()
logger = logging.getLogger(__name__)

MGMT_GROUP_ID = os.getenv("MGMT_GROUP_ID")

COOLDOWN_MINUTES = {
    "geofence_arrival": 30,
    "geofence_departure": 30,
    "unassigned_at_landmark": 30,
    "idle_30min": 60,
    "overdue_return": 240,
    "theft_risk": 120,
}


async def send_alert(
    bot: Bot,
    db: Database,
    alert_type: str,
    entity_id: str,
    message: str,
) -> bool:
    if not MGMT_GROUP_ID:
        logger.warning("MGMT_GROUP_ID not set, skipping alert")
        return False

    if db.is_alert_suppressed(alert_type, entity_id):
        logger.debug("Alert suppressed: %s / %s", alert_type, entity_id)
        return False

    try:
        await bot.send_message(
            chat_id=int(MGMT_GROUP_ID),
            text=message,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Failed to send alert to MGMT group: %s", e)
        return False

    cooldown = COOLDOWN_MINUTES.get(alert_type, 60)
    suppressed_until = (datetime.utcnow() + timedelta(minutes=cooldown)).strftime("%Y-%m-%d %H:%M:%S")
    db.log_alert(alert_type, entity_id, message, suppressed_until)
    return True
