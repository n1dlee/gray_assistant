import os
import time
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

import aiohttp
from dotenv import load_dotenv

from providers.base import TrailerProvider, TrailerPosition

load_dotenv()
logger = logging.getLogger(__name__)

TOKEN_URL = "https://prodssoidp.skybitz.com/oauth2/token"
SERVICE_URL = os.getenv("SKYBITZ_SERVICE_URL", "https://xml-gen2.skybitz.com")
API_VERSION = "2.76"


@dataclass
class SkyBitzAccount:
    name: str
    client_id: str
    client_secret: str
    _token: Optional[str] = None
    _token_expires: float = 0.0


class SkyBitzProvider(TrailerProvider):
    def __init__(self, accounts: list[SkyBitzAccount] = None):
        if accounts is None:
            accounts = self._load_accounts_from_env()
        self._accounts = accounts

    def provider_name(self) -> str:
        return "skybitz"

    @staticmethod
    def _load_accounts_from_env() -> list[SkyBitzAccount]:
        accounts = []
        for i in range(1, 4):
            client_id = os.getenv(f"SKYBITZ_CLIENT_ID_{i}", "")
            client_secret = os.getenv(f"SKYBITZ_CLIENT_SECRET_{i}", "")
            name = os.getenv(f"SKYBITZ_NAME_{i}", f"skybitz_{i}")
            if client_id and client_secret:
                accounts.append(SkyBitzAccount(
                    name=name, client_id=client_id, client_secret=client_secret,
                ))
        return accounts

    async def fetch_positions(self) -> list[TrailerPosition]:
        all_positions: list[TrailerPosition] = []
        async with aiohttp.ClientSession() as session:
            for account in self._accounts:
                try:
                    positions = await self._fetch_account(session, account)
                    all_positions.extend(positions)
                except Exception as e:
                    logger.error("SkyBitz %s fetch failed: %s", account.name, e)
        logger.info("SkyBitz: fetched %d positions from %d accounts",
                     len(all_positions), len(self._accounts))
        return all_positions

    async def _get_token(self, session: aiohttp.ClientSession,
                         account: SkyBitzAccount) -> Optional[str]:
        if account._token and time.monotonic() < account._token_expires:
            return account._token

        auth = aiohttp.BasicAuth(account.client_id, account.client_secret)
        try:
            async with session.post(
                TOKEN_URL,
                auth=auth,
                data={"grant_type": "client_credentials"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.error("SkyBitz %s: token request HTTP %s", account.name, resp.status)
                    return None
                data = await resp.json()
                account._token = data["access_token"]
                expires_in = data.get("expires_in", 3600)
                account._token_expires = time.monotonic() + expires_in - 60
                return account._token
        except Exception as e:
            logger.error("SkyBitz %s: token request failed: %s", account.name, e)
            return None

    async def _fetch_account(self, session: aiohttp.ClientSession,
                             account: SkyBitzAccount) -> list[TrailerPosition]:
        token = await self._get_token(session, account)
        if not token:
            return []

        params = {
            "accessToken": token,
            "version": API_VERSION,
            "assetid": "ALL",
            "sortby": "1",
            "getJson": "1",
        }
        url = f"{SERVICE_URL}/QueryPositions"
        try:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.warning("SkyBitz %s: HTTP %s", account.name, resp.status)
                    return []
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.error("SkyBitz %s: request error: %s", account.name, e)
            return []

        return self._parse_json(data, account.name)

    def _parse_json(self, data: dict, account_name: str) -> list[TrailerPosition]:
        skybitz = data.get("skybitz", data)
        error = skybitz.get("error", 0)
        if error != 0:
            logger.warning("SkyBitz %s: API error %s: %s",
                           account_name, error, skybitz.get("errorText", ""))
            return []

        gls_list = skybitz.get("gls", [])
        if isinstance(gls_list, dict):
            gls_list = [gls_list]

        results = []
        for gls in gls_list:
            asset = gls.get("asset", {})
            asset_id = asset.get("assetid", "")
            if not asset_id:
                continue

            lat = gls.get("latitude")
            lon = gls.get("longitude")
            if lat is None or lon is None:
                continue

            try:
                lat = float(lat)
                lon = float(lon)
            except (ValueError, TypeError):
                continue

            speed = gls.get("speed")
            if speed is not None:
                try:
                    speed = float(speed)
                except (ValueError, TypeError):
                    speed = None

            battery_str = gls.get("battery", "")
            battery_pct = None
            if isinstance(battery_str, (int, float)):
                battery_pct = float(battery_str)

            idle_info = gls.get("idle", {})
            idle_status = idle_info.get("idlestatus", "") if isinstance(idle_info, dict) else ""

            address = gls.get("address", {})
            city = address.get("city", "") if isinstance(address, dict) else ""
            state = address.get("state", "") if isinstance(address, dict) else ""
            location_parts = [p for p in [city, state] if p]

            time_iso = gls.get("time-iso8601", "")
            updated = datetime.now(timezone.utc)
            if time_iso:
                try:
                    updated = datetime.fromisoformat(time_iso.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            status_parts = []
            msg_type = gls.get("messagetype", "")
            if msg_type:
                status_parts.append(msg_type)
            if idle_status:
                status_parts.append(idle_status)

            results.append(TrailerPosition(
                trailer_id=str(asset_id),
                latitude=lat,
                longitude=lon,
                speed=speed,
                battery_pct=battery_pct,
                raw_status=" | ".join(status_parts) if status_parts else None,
                landmark_state=", ".join(location_parts) if location_parts else None,
                updated_at=updated,
            ))

        logger.info("SkyBitz %s: parsed %d positions", account_name, len(results))
        return results
