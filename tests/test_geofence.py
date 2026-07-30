import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from geofence import haversine_meters, is_inside_landmark, check_geofence_events
from function import Database


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def test_haversine_zero_distance():
    assert haversine_meters(40.7128, -74.0060, 40.7128, -74.0060) == 0.0


def test_haversine_known_distance():
    dist = haversine_meters(40.7128, -74.0060, 34.0522, -118.2437)
    assert abs(dist - 3_940_000) < 50_000


def test_haversine_short_distance():
    dist = haversine_meters(32.7767, -96.7970, 32.7780, -96.7970)
    assert dist < 200
    assert dist > 100


def test_inside_landmark():
    assert is_inside_landmark(32.7767, -96.7970, 32.7770, -96.7970, 200) is True


def test_outside_landmark():
    assert is_inside_landmark(32.7767, -96.7970, 32.7800, -96.7970, 200) is False


def test_arrival_detection(db):
    lm_id = db.add_landmark("Yard", 32.7770, -96.7970, 200)
    positions = [("EJGZ001", "roadready", 32.7771, -96.7971, None, None, None)]
    landmarks = db.get_landmarks()

    events = check_geofence_events(positions, landmarks, db)
    assert len(events) == 1
    assert events[0].event_type == "arrival"
    assert events[0].trailer_id == "EJGZ001"


def test_departure_detection(db):
    lm_id = db.add_landmark("Yard", 32.7770, -96.7970, 200)
    db.add_geofence_event("EJGZ001", lm_id, "arrival", 32.7771, -96.7971)

    positions = [("EJGZ001", "roadready", 33.0000, -97.0000, None, None, None)]
    landmarks = db.get_landmarks()

    events = check_geofence_events(positions, landmarks, db)
    assert len(events) == 1
    assert events[0].event_type == "departure"


def test_no_event_when_still_inside(db):
    lm_id = db.add_landmark("Yard", 32.7770, -96.7970, 200)
    db.add_geofence_event("EJGZ001", lm_id, "arrival", 32.7771, -96.7971)

    positions = [("EJGZ001", "roadready", 32.7772, -96.7972, None, None, None)]
    landmarks = db.get_landmarks()

    events = check_geofence_events(positions, landmarks, db)
    assert len(events) == 0


def test_no_event_when_still_outside(db):
    lm_id = db.add_landmark("Yard", 32.7770, -96.7970, 200)
    db.add_geofence_event("EJGZ001", lm_id, "departure", 33.0, -97.0)

    positions = [("EJGZ001", "roadready", 34.0, -98.0, None, None, None)]
    landmarks = db.get_landmarks()

    events = check_geofence_events(positions, landmarks, db)
    assert len(events) == 0


def test_multiple_landmarks(db):
    db.add_landmark("YardA", 32.7770, -96.7970, 200)
    db.add_landmark("YardB", 32.7770, -96.7975, 200)

    positions = [("EJGZ001", "roadready", 32.7771, -96.7972, None, None, None)]
    landmarks = db.get_landmarks()

    events = check_geofence_events(positions, landmarks, db)
    assert len(events) == 2
    assert all(e.event_type == "arrival" for e in events)


def test_unassigned_trailer_at_landmark(db):
    db.add_landmark("Yard", 32.7770, -96.7970, 200)
    positions = [("EJGZ_UNKNOWN", "roadready", 32.7771, -96.7971, None, None, None)]
    landmarks = db.get_landmarks()

    events = check_geofence_events(positions, landmarks, db)
    assert len(events) == 1
    assert events[0].has_assignment is False
