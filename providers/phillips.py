import os
import logging
from datetime import datetime, timezone
from typing import Optional

from aiohttp import web
from dotenv import load_dotenv

from providers.base import TrailerProvider, TrailerPosition

load_dotenv()
logger = logging.getLogger(__name__)

PHILLIPS_WEBHOOK_SECRET = os.getenv("PHILLIPS_WEBHOOK_SECRET", "")


def _find_sensor(sensors: list, sensor_type: str) -> Optional[dict]:
    for sensor in sensors:
        if isinstance(sensor, dict) and sensor.get("type") == sensor_type:
            return sensor
    return None


def _parse_timestamp(value: Optional[str]) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def parse_report(payload: dict) -> Optional[TrailerPosition]:
    trailer_id = payload.get("asset_id")
    summary = payload.get("summary") or {}

    lat = summary.get("latitude")
    lon = summary.get("longitude")
    if not trailer_id or lat is None or lon is None:
        return None

    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        return None

    speed = summary.get("speed_IC_MI_PER_HR")
    if speed is not None:
        try:
            speed = float(speed)
        except (ValueError, TypeError):
            speed = None

    internal_sensors = payload.get("internal_sensors") or []
    peripheral_sensors = payload.get("peripheral_sensors") or []

    battery_pct = None
    power = _find_sensor(internal_sensors, "power-sensor")
    if power:
        battery = power.get("battery") or {}
        battery_pct = battery.get("remaining_capacity")
        if battery_pct is not None:
            try:
                battery_pct = float(battery_pct)
            except (ValueError, TypeError):
                battery_pct = None

    status_parts = []
    event_name = payload.get("event_name")
    if event_name:
        status_parts.append(str(event_name))
    if summary.get("is_trip"):
        status_parts.append("MOVING")
    else:
        status_parts.append("STOPPED")

    cargo = _find_sensor(peripheral_sensors, "cargo-sensor")
    if cargo and cargo.get("cargo_state"):
        status_parts.append(f"Cargo: {cargo['cargo_state']}")

    door = _find_sensor(peripheral_sensors, "door-sensor")
    if door and door.get("door_state"):
        status_parts.append(f"Door: {door['door_state']}")

    brake_health = _find_sensor(peripheral_sensors, "Brake_Health")
    if brake_health and brake_health.get("alert(s)"):
        status_parts.append(f"Brake alert: {', '.join(brake_health['alert(s)'])}")

    updated_at = _parse_timestamp(summary.get("updated_timestamp") or payload.get("event_datetime"))

    return TrailerPosition(
        trailer_id=str(trailer_id),
        latitude=lat,
        longitude=lon,
        speed=speed,
        battery_pct=battery_pct,
        raw_status=" | ".join(status_parts) if status_parts else None,
        landmark_state=summary.get("geofence_name"),
        updated_at=updated_at,
    )


class PhillipsProvider(TrailerProvider):
    def __init__(self):
        self._positions: dict[str, TrailerPosition] = {}

    def provider_name(self) -> str:
        return "phillips"

    def ingest_report(self, payload: dict) -> Optional[TrailerPosition]:
        position = parse_report(payload)
        if position is None:
            logger.warning("Phillips: skipped report with missing asset_id/lat/lon")
            return None
        self._positions[position.trailer_id] = position
        return position

    async def fetch_positions(self) -> list[TrailerPosition]:
        return list(self._positions.values())


def _is_authorized(request: web.Request) -> bool:
    if not PHILLIPS_WEBHOOK_SECRET:
        return True
    auth_header = request.headers.get("Authorization", "")
    return auth_header == f"Bearer {PHILLIPS_WEBHOOK_SECRET}"


def create_webhook_app(provider: PhillipsProvider) -> web.Application:
    async def handle_push(request: web.Request) -> web.Response:
        if not _is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        reports = body if isinstance(body, list) else [body]
        ingested = 0
        for report in reports:
            if isinstance(report, dict) and provider.ingest_report(report) is not None:
                ingested += 1

        return web.json_response({"status": "ok", "ingested": ingested}, status=200)

    app = web.Application()
    app.router.add_post("/phillips/push", handle_push)
    return app
