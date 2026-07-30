import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from dotenv import load_dotenv

from providers.base import TrailerProvider, TrailerPosition

load_dotenv()
logger = logging.getLogger(__name__)

FUS1ON_AUTH_URL = os.getenv("FUSION_AUTH_URL", "https://authqa.fus1on.com/oauth/token")
FUS1ON_API_URL = os.getenv("FUSION_API_URL", "https://apiqa.fus1on.com")
FUS1ON_CLIENT_ID = os.getenv("FUSION_CLIENT_ID", "")
FUS1ON_CLIENT_SECRET = os.getenv("FUSION_CLIENT_SECRET", "")
FUS1ON_USERNAME = os.getenv("FUSION_USERNAME", "")
FUS1ON_PASSWORD = os.getenv("FUSION_PASSWORD", "")


class Fus1onProvider(TrailerProvider):
    def __init__(self):
        self._token: Optional[str] = None
        self._token_expires: float = 0.0

    def provider_name(self) -> str:
        return "fus1on"

    async def _get_token(self, session: aiohttp.ClientSession) -> Optional[str]:
        if self._token and time.monotonic() < self._token_expires:
            return self._token

        payload = {
            "grant_type": "password",
            "client_id": FUS1ON_CLIENT_ID,
            "client_secret": FUS1ON_CLIENT_SECRET,
            "audience": FUS1ON_API_URL,
            "scope": "offline_access",
            "username": FUS1ON_USERNAME,
            "password": FUS1ON_PASSWORD,
        }
        try:
            async with session.post(
                FUS1ON_AUTH_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Fus1on auth failed: HTTP %s — %s", resp.status, text[:200])
                    return None
                data = await resp.json()
                self._token = data["access_token"]
                expires_in = data.get("expires_in", 86400)
                self._token_expires = time.monotonic() + expires_in - 300
                return self._token
        except Exception as e:
            logger.error("Fus1on auth request failed: %s", e)
            return None

    async def fetch_positions(self) -> list[TrailerPosition]:
        if not FUS1ON_CLIENT_ID:
            return []

        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            if not token:
                return []

            url = f"{FUS1ON_API_URL}/jsonapi/fleet_trailer_states"
            params = {
                "includeSensorState": "true",
                "includeIdlingDetails": "true",
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
            try:
                async with session.get(url, params=params, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 401:
                        self._token = None
                        self._token_expires = 0
                        logger.warning("Fus1on: 401, token expired")
                        return []
                    if resp.status != 200:
                        logger.error("Fus1on fleet request: HTTP %s", resp.status)
                        return []
                    data = await resp.json()
            except Exception as e:
                logger.error("Fus1on fleet request failed: %s", e)
                return []

        return self._parse_fleet(data)

    def _parse_fleet(self, data: dict) -> list[TrailerPosition]:
        items = data.get("data", [])
        if not isinstance(items, list):
            return []

        results = []
        for item in items:
            attrs = item.get("attributes", {})
            trailer_name = attrs.get("trailerName", "")
            if not trailer_name:
                continue

            lat = attrs.get("latitude")
            lon = attrs.get("longitude")
            if lat is None or lon is None:
                continue

            try:
                lat = float(lat)
                lon = float(lon)
            except (ValueError, TypeError):
                continue

            battery = attrs.get("batteryPercentage")
            if battery is not None:
                try:
                    battery = float(battery)
                except (ValueError, TypeError):
                    battery = None

            motion = attrs.get("motion", {})
            motion_val = motion.get("value", "") if isinstance(motion, dict) else ""
            landmark_state = attrs.get("landmarkTrailerState", "")

            status_parts = []
            if landmark_state:
                status_parts.append(landmark_state)
            if motion_val:
                status_parts.append(motion_val)

            last_event = attrs.get("lastEvent", {})
            event_date = ""
            if isinstance(last_event, dict):
                event_date = last_event.get("messageDate", "")

            updated = datetime.now(timezone.utc)
            if event_date:
                for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%m-%d-%Y %H:%M:%S"):
                    try:
                        updated = datetime.strptime(event_date, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue

            results.append(TrailerPosition(
                trailer_id=str(trailer_name),
                latitude=lat,
                longitude=lon,
                speed=None,
                battery_pct=battery,
                raw_status=" | ".join(status_parts) if status_parts else None,
                landmark_state=landmark_state or None,
                updated_at=updated,
            ))

        logger.info("Fus1on: fetched %d positions", len(results))
        return results
