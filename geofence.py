import math
import logging
from dataclasses import dataclass
from typing import Optional

from function import Database

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_000


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_inside_landmark(lat: float, lon: float, lm_lat: float, lm_lon: float,
                       radius_meters: float) -> bool:
    return haversine_meters(lat, lon, lm_lat, lm_lon) <= radius_meters


@dataclass
class GeofenceEvent:
    trailer_id: str
    landmark_id: int
    landmark_name: str
    event_type: str  # "arrival" or "departure"
    latitude: float
    longitude: float
    has_assignment: bool = True


def check_geofence_events(
    positions: list[tuple],
    landmarks: list[tuple],
    db: Database,
) -> list[GeofenceEvent]:
    events: list[GeofenceEvent] = []

    for pos in positions:
        trailer_id, _provider, lat, lon, _speed, _raw, _updated = pos
        if lat is None or lon is None:
            continue

        for lm in landmarks:
            lm_id, lm_name, lm_lat, lm_lon, lm_radius = lm[0], lm[1], lm[2], lm[3], lm[4]

            inside_now = is_inside_landmark(lat, lon, lm_lat, lm_lon, lm_radius)
            last_event = db.get_last_geofence_event(trailer_id, lm_id)

            was_inside = False
            if last_event:
                was_inside = last_event[3] == "arrival"

            if inside_now and not was_inside:
                assignment = db.get_active_assignment(trailer_id)
                db.add_geofence_event(trailer_id, lm_id, "arrival", lat, lon)
                events.append(GeofenceEvent(
                    trailer_id=trailer_id,
                    landmark_id=lm_id,
                    landmark_name=lm_name,
                    event_type="arrival",
                    latitude=lat,
                    longitude=lon,
                    has_assignment=assignment is not None,
                ))

            elif not inside_now and was_inside:
                db.add_geofence_event(trailer_id, lm_id, "departure", lat, lon)
                events.append(GeofenceEvent(
                    trailer_id=trailer_id,
                    landmark_id=lm_id,
                    landmark_name=lm_name,
                    event_type="departure",
                    latitude=lat,
                    longitude=lon,
                    has_assignment=True,
                ))

    return events
