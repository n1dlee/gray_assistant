import os
import sys
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from function import Database
from idle_detector import (
    check_idle_single,
    detect_idle_trailers,
    check_movement_reset,
    IdleResult,
    IDLE_THRESHOLD_METERS,
)


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def test_idle_no_movement(db):
    """6 points within 10m over 30 min → idle."""
    base_lat, base_lon = 32.7767, -96.7970
    points = []
    for i in range(6):
        lat = base_lat + (i % 2) * 0.00005  # ~5m jitter
        lon = base_lon + (i % 3) * 0.00003
        points.append((lat, lon))

    max_disp = check_idle_single(points)
    assert max_disp is not None
    assert max_disp <= IDLE_THRESHOLD_METERS


def test_not_idle_moving():
    """6 points each 1km apart → not idle."""
    points = []
    base_lat = 32.7767
    for i in range(6):
        points.append((base_lat + i * 0.009, -96.7970))  # ~1km per step

    max_disp = check_idle_single(points)
    # bounding box prefilter should reject, returning None
    assert max_disp is None


def test_idle_gps_drift():
    """6 points with 20-50m jitter → still idle (within 100m threshold)."""
    base_lat, base_lon = 40.7128, -74.0060
    offsets = [
        (0.0, 0.0),
        (0.00018, 0.00012),   # ~25m
        (-0.00015, 0.00020),  # ~30m
        (0.00025, -0.00010),  # ~30m
        (-0.00020, -0.00015), # ~30m
        (0.00010, 0.00025),   # ~30m
    ]
    points = [(base_lat + dlat, base_lon + dlon) for dlat, dlon in offsets]

    max_disp = check_idle_single(points)
    assert max_disp is not None
    assert max_disp <= IDLE_THRESHOLD_METERS


def test_insufficient_data():
    """Only 1 point → not enough data, returns None."""
    points = [(32.7767, -96.7970)]
    max_disp = check_idle_single(points)
    assert max_disp is None


def test_bounding_box_prefilter():
    """Points spread over 500m → bounding box rejects, no Haversine."""
    points = [
        (32.7767, -96.7970),
        (32.7767, -96.7910),  # ~500m east
        (32.7800, -96.7970),
        (32.7800, -96.7910),
    ]
    max_disp = check_idle_single(points)
    assert max_disp is None


def test_suppression_after_alert(db):
    """After logging idle alert with suppression, is_alert_suppressed returns True."""
    future = (datetime.utcnow() + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
    db.log_alert("idle_30min", "EJGZ001", "test idle alert", future)
    assert db.is_alert_suppressed("idle_30min", "EJGZ001") is True


def test_suppression_reset_on_movement(db):
    """Movement resets suppression, allowing new alerts."""
    future = (datetime.utcnow() + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
    db.log_alert("idle_30min", "EJGZ_MOVE", "idle alert", future)
    assert db.is_alert_suppressed("idle_30min", "EJGZ_MOVE") is True

    db.clear_alert_suppression("idle_30min", "EJGZ_MOVE")
    assert db.is_alert_suppressed("idle_30min", "EJGZ_MOVE") is False
