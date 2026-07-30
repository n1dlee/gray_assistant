import os
import sys
import sqlite3
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from function import Database


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    return Database(path)


def test_add_landmark(db):
    lm_id = db.add_landmark("TestYard", 32.77, -96.79, 200, "Dallas, TX", 12345)
    assert lm_id > 0


def test_get_landmarks(db):
    db.add_landmark("A", 1.0, 2.0)
    db.add_landmark("B", 3.0, 4.0)
    db.add_landmark("C", 5.0, 6.0)
    landmarks = db.get_landmarks()
    assert len(landmarks) == 3
    assert landmarks[0][1] == "A"
    assert landmarks[1][1] == "B"
    assert landmarks[2][1] == "C"


def test_deactivate_landmark(db):
    lm_id = db.add_landmark("ToRemove", 10.0, 20.0)
    assert lm_id > 0
    db.deactivate_landmark(lm_id)
    landmarks = db.get_landmarks()
    assert len(landmarks) == 0


def test_upsert_trailer_position(db):
    db.upsert_trailer_position("EJGZ001", "roadready", 32.0, -96.0, 55.0, "InMotion")
    positions = db.get_trailer_positions()
    assert len(positions) == 1
    assert positions[0][0] == "EJGZ001"
    assert positions[0][2] == 32.0

    db.upsert_trailer_position("EJGZ001", "roadready", 33.0, -97.0, 0.0, "Stopped")
    positions = db.get_trailer_positions()
    assert len(positions) == 1
    assert positions[0][2] == 33.0
    assert positions[0][5] == "Stopped"


def test_add_position_history(db):
    for i in range(10):
        db.add_position_history("TRUCK1", 32.0 + i * 0.001, -96.0)

    history = db.get_position_history_window("TRUCK1", minutes=30)
    assert len(history) == 10

    history_other = db.get_position_history_window("TRUCK_NONEXIST", minutes=30)
    assert len(history_other) == 0


def test_create_assignment(db):
    a_id = db.create_assignment("EJGZ001", "22203", "John", "Dallas, TX", -100)
    assert a_id > 0
    assignment = db.get_active_assignment("EJGZ001")
    assert assignment is not None
    assert assignment[1] == "EJGZ001"
    assert assignment[2] == "22203"
    assert assignment[3] == "John"
    assert assignment[10] == "PICKED"


def test_update_assignment_status(db):
    a_id = db.create_assignment("EJGZ002", "22237", "Jane", "Houston, TX")
    db.update_assignment_status(a_id, "RETURNED", drop_time="2026-06-14 12:00:00")
    assignment = db.get_active_assignment("EJGZ002")
    assert assignment is None


def test_get_overdue_assignments(db):
    a1 = db.create_assignment("EJGZ_LATE", "111", "Driver1", "Loc1")
    past = (datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    db.set_return_deadline(a1, past, "ReturnLoc1")

    a2 = db.create_assignment("EJGZ_OK", "222", "Driver2", "Loc2")
    future = (datetime.utcnow() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    db.set_return_deadline(a2, future, "ReturnLoc2")

    overdue = db.get_overdue_assignments()
    assert len(overdue) == 1
    assert overdue[0][1] == "EJGZ_LATE"


def test_log_alert_and_suppression(db):
    future = (datetime.utcnow() + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
    db.log_alert("idle_30min", "TRUCK1", "Truck idle", future)
    assert db.is_alert_suppressed("idle_30min", "TRUCK1") is True

    past = (datetime.utcnow() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    db.log_alert("idle_30min", "TRUCK2", "Truck idle", past)
    assert db.is_alert_suppressed("idle_30min", "TRUCK2") is False


def test_add_geofence_event(db):
    lm_id = db.add_landmark("Yard", 32.0, -96.0)
    ev_id = db.add_geofence_event("EJGZ001", lm_id, "arrival", 32.001, -96.001)
    assert ev_id > 0

    last = db.get_last_geofence_event("EJGZ001", lm_id)
    assert last is not None
    assert last[3] == "arrival"
    assert last[1] == "EJGZ001"


def test_get_last_geofence_event_none(db):
    result = db.get_last_geofence_event("NONEXIST", 999)
    assert result is None
