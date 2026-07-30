import logging
from dataclasses import dataclass
from typing import Optional

from geofence import haversine_meters
from function import Database

logger = logging.getLogger(__name__)

IDLE_THRESHOLD_METERS = 100
IDLE_WINDOW_MINUTES = 60
MOVEMENT_RESET_METERS = 500
MIN_POINTS_REQUIRED = 2


@dataclass
class IdleResult:
    trailer_id: str
    is_idle: bool
    max_displacement_m: float
    num_points: int
    latest_lat: Optional[float] = None
    latest_lon: Optional[float] = None


def _bounding_box_check(points: list[tuple]) -> bool:
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat_span = max(lats) - min(lats)
    lon_span = max(lons) - min(lons)
    # ~111km per degree lat, ~85km per degree lon at mid-latitudes
    if lat_span * 111_000 > IDLE_THRESHOLD_METERS * 3:
        return False
    if lon_span * 85_000 > IDLE_THRESHOLD_METERS * 3:
        return False
    return True


def check_idle_single(points: list[tuple]) -> Optional[float]:
    if len(points) < MIN_POINTS_REQUIRED:
        return None

    if not _bounding_box_check(points):
        return None

    max_dist = 0.0
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = haversine_meters(points[i][0], points[i][1], points[j][0], points[j][1])
            if d > max_dist:
                max_dist = d
            if max_dist > IDLE_THRESHOLD_METERS:
                return max_dist

    return max_dist


def detect_idle_trailers(db: Database) -> list[IdleResult]:
    positions = db.get_trailer_positions()
    results: list[IdleResult] = []

    seen_trailers = set()
    for pos in positions:
        trailer_id = pos[0]
        if trailer_id in seen_trailers:
            continue
        seen_trailers.add(trailer_id)

        history = db.get_position_history_window(trailer_id, IDLE_WINDOW_MINUTES)
        if len(history) < MIN_POINTS_REQUIRED:
            continue

        points = [(h[0], h[1]) for h in history]
        max_disp = check_idle_single(points)

        if max_disp is None:
            results.append(IdleResult(
                trailer_id=trailer_id,
                is_idle=False,
                max_displacement_m=0,
                num_points=len(points),
            ))
            continue

        latest = history[-1]
        results.append(IdleResult(
            trailer_id=trailer_id,
            is_idle=max_disp <= IDLE_THRESHOLD_METERS,
            max_displacement_m=max_disp,
            num_points=len(points),
            latest_lat=latest[0],
            latest_lon=latest[1],
        ))

    return results


def check_movement_reset(db: Database, trailer_id: str) -> bool:
    history = db.get_position_history_window(trailer_id, IDLE_WINDOW_MINUTES)
    if len(history) < 2:
        return False

    first = history[0]
    last = history[-1]
    dist = haversine_meters(first[0], first[1], last[0], last[1])
    return dist > MOVEMENT_RESET_METERS
