import os
import sys
import pytest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from providers.base import TrailerPosition


def test_trailer_position_creation():
    pos = TrailerPosition(
        trailer_id="EJGZ001",
        latitude=32.77,
        longitude=-96.79,
        speed=55.0,
        battery_pct=85.0,
        raw_status="InMotion",
    )
    assert pos.trailer_id == "EJGZ001"
    assert pos.latitude == 32.77
    assert pos.longitude == -96.79
    assert pos.speed == 55.0
    assert pos.battery_pct == 85.0
    assert pos.raw_status == "InMotion"
    assert isinstance(pos.updated_at, datetime)


def test_trailer_position_defaults():
    pos = TrailerPosition(
        trailer_id="EJGZ002",
        latitude=33.0,
        longitude=-97.0,
    )
    assert pos.speed is None
    assert pos.battery_pct is None
    assert pos.raw_status is None
    assert pos.landmark_state is None
    assert isinstance(pos.updated_at, datetime)
