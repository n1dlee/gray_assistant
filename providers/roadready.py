import os
import logging
from datetime import datetime

import aiohttp
from dotenv import load_dotenv

from providers.base import TrailerProvider, TrailerPosition

load_dotenv()
logger = logging.getLogger(__name__)

ROADREADY_USERNAME = os.getenv("ROADREADY_USERNAME", "")
ROADREADY_PASSWORD = os.getenv("ROADREADY_PASSWORD", "")

AUTH_URL = "https://api.roadreadysystem.com/api/auth"
FLEET_URL = "https://api.roadreadysystem.com/jsonapi/fleet_trailer_states"


class RoadReadyProvider(TrailerProvider):
    def __init__(self, username: str = None, password: str = None):
        self._username = username or ROADREADY_USERNAME
        self._password = password or ROADREADY_PASSWORD
        self._token: str | None = None

    def provider_name(self) -> str:
        return "roadready"

    async def _authenticate(self, session: aiohttp.ClientSession) -> str:
        payload = {
            "username": self._username,
            "password": self._password,
        }
        headers = {
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/json",
        }
        async with session.post(AUTH_URL, json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Road Ready auth failed: {resp.status} {text}")
            token = await resp.text()
            token = token.strip().strip('"')
            if not token:
                raise RuntimeError("Road Ready auth returned empty token")
            self._token = token
            return token

    async def fetch_positions(self) -> list[TrailerPosition]:
        async with aiohttp.ClientSession() as session:
            if not self._token:
                await self._authenticate(session)

            positions = await self._fetch_fleet(session)
            if positions is None:
                await self._authenticate(session)
                positions = await self._fetch_fleet(session)
                if positions is None:
                    return []

            return positions

    async def _fetch_fleet(self, session: aiohttp.ClientSession) -> list[TrailerPosition] | None:
        headers = {
            "Accept": "application/json",
            "Cookie": f"x-auth-token={self._token}",
        }
        try:
            async with session.get(FLEET_URL, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 401:
                    return None
                if resp.status != 200:
                    logger.error("Road Ready fleet request failed: %s", resp.status)
                    return []
                data = await resp.json()
        except Exception as e:
            logger.exception("Road Ready fetch error: %s", e)
            return []

        results = []
        items = data.get("data", []) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("data", [])
        if not isinstance(items, list):
            items = []

        for item in items:
            attrs = item.get("attributes", item)
            trailer_id = str(attrs.get("trailerName", "") or item.get("id", "")).strip()
            if not trailer_id:
                continue

            lat = attrs.get("latitude")
            lon = attrs.get("longitude")
            if lat is None or lon is None:
                continue

            results.append(TrailerPosition(
                trailer_id=trailer_id,
                latitude=float(lat),
                longitude=float(lon),
                speed=None,
                battery_pct=attrs.get("batteryPercentage"),
                raw_status=attrs.get("landmarkTrailerState"),
                landmark_state=attrs.get("landmarkTrailerState"),
                updated_at=datetime.utcnow(),
            ))

        logger.info("Road Ready: fetched %d positions", len(results))
        return results
