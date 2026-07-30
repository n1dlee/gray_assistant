import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from function import Database
from idle_detector import detect_idle_trailers


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def test_poll_and_idle_pipeline(db):
    """Simulate: positions recorded → idle detection finds idle trailer."""
    trailer_id = "EJGZ_IDLE_INT"
    base_lat, base_lon = 32.7767, -96.7970

    db.upsert_trailer_position(trailer_id, "roadready", base_lat, base_lon)

    for i in range(6):
        lat = base_lat + (i % 2) * 0.00003
        lon = base_lon + (i % 3) * 0.00002
        db.add_position_history(trailer_id, lat, lon)

    results = detect_idle_trailers(db)
    idle_results = [r for r in results if r.trailer_id == trailer_id and r.is_idle]
    assert len(idle_results) == 1
    assert idle_results[0].max_displacement_m < 100
