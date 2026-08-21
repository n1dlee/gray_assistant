import os
import logging
from typing import Optional

import aiohttp
from dotenv import load_dotenv

from geofence import haversine_meters

load_dotenv()
logger = logging.getLogger(__name__)

PROXIMITY_THRESHOLD_MILES = 20
PROXIMITY_THRESHOLD_M = PROXIMITY_THRESHOLD_MILES * 1609.344

TTELD_PROVIDER_TOKEN = os.getenv("TTELD_PROVIDER_TOKEN", "")
FLEETS = [
    {
        "name": "GRAY",
        "usdot": os.getenv("TTELD_USDOT", ""),
        "api_key": os.getenv("TTELD_API_KEY", ""),
    },
    {
        "name": "OMEGA",
        "usdot": os.getenv("TTELD_OMEGA_USDOT", ""),
        "api_key": os.getenv("TTELD_OMEGA_API_KEY", ""),
    },
]


async def _fetch_truck_positions(session: aiohttp.ClientSession,
                                 fleet: dict) -> list[tuple[str, float, float]]:
    if not fleet["api_key"] or not fleet["usdot"]:
        return []
    url = f"https://read.tteld.com/api/v2/units-by-usdot/{fleet['usdot']}"
    headers = {
        "x-api-key": fleet["api_key"],
        "provider-token": TTELD_PROVIDER_TOKEN,
    }
    try:
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            results = []
            for unit in data.get("units", []):
                coords = unit.get("coordinates", {})
                lat = coords.get("lat")
                lng = coords.get("lng")
                truck = str(unit.get("truck_number", "")).strip()
                if lat is not None and lng is not None and truck:
                    results.append((truck, float(lat), float(lng)))
            return results
    except Exception as e:
        logger.error("Failed to fetch %s fleet: %s", fleet["name"], e)
        return []


async def get_all_truck_positions() -> list[tuple[str, float, float]]:
    all_trucks = []
    async with aiohttp.ClientSession() as session:
        for fleet in FLEETS:
            trucks = await _fetch_truck_positions(session, fleet)
            all_trucks.extend(trucks)
    return all_trucks


async def find_nearest_truck(trailer_lat: float, trailer_lon: float
                             ) -> Optional[tuple[str, float]]:
    trucks = await get_all_truck_positions()
    if not trucks:
        return None

    best_truck = None
    best_dist = float("inf")
    for truck_id, t_lat, t_lon in trucks:
        dist = haversine_meters(trailer_lat, trailer_lon, t_lat, t_lon)
        if dist < best_dist:
            best_dist = dist
            best_truck = truck_id

    if best_truck is not None:
        return (best_truck, best_dist)
    return None


async def is_trailer_with_our_driver(trailer_lat: float, trailer_lon: float
                                     ) -> tuple[bool, Optional[str], float]:
    result = await find_nearest_truck(trailer_lat, trailer_lon)
    if result is None:
        return (False, None, 0.0)
    truck_id, distance = result
    is_with_driver = distance <= PROXIMITY_THRESHOLD_M
    return (is_with_driver, truck_id, distance)
