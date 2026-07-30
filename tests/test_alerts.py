import os
import sys
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from function import Database


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def test_alert_not_suppressed_first_time(db):
    assert db.is_alert_suppressed("idle_30min", "TRUCK_NEW") is False


def test_alert_suppressed_within_cooldown(db):
    future = (datetime.utcnow() + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
    db.log_alert("idle_30min", "TRUCK1", "Idle alert", future)
    assert db.is_alert_suppressed("idle_30min", "TRUCK1") is True


def test_alert_sent_after_cooldown(db):
    past = (datetime.utcnow() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    db.log_alert("idle_30min", "TRUCK1", "Idle alert", past)
    assert db.is_alert_suppressed("idle_30min", "TRUCK1") is False


def test_different_entities_not_suppressed(db):
    future = (datetime.utcnow() + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
    db.log_alert("idle_30min", "TRUCK_A", "Idle A", future)

    assert db.is_alert_suppressed("idle_30min", "TRUCK_A") is True
    assert db.is_alert_suppressed("idle_30min", "TRUCK_B") is False
