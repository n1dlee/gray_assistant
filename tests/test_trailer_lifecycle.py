import os
import sys
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from function import Database
from trailer_lifecycle import create_assignment, complete_assignment, set_return_deadline, get_overdue_returns


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def test_create_assignment_from_pick(db):
    a_id = create_assignment(db, "EJGZ001", "22203", "John", "Dallas, TX", -100)
    assert a_id > 0
    assignment = db.get_active_assignment("EJGZ001")
    assert assignment is not None
    assert assignment[10] == "PICKED"
    assert assignment[2] == "22203"
    assert assignment[3] == "John"


def test_complete_assignment_on_drop(db):
    create_assignment(db, "EJGZ002", "22237", "Jane", "Houston, TX")
    ok = complete_assignment(db, "EJGZ002", "Austin, TX")
    assert ok is True
    assignment = db.get_active_assignment("EJGZ002")
    assert assignment is None


def test_set_return_deadline(db):
    a_id = create_assignment(db, "EJGZ003", "22262", "Bob", "LA")
    deadline = "2026-06-20"
    ok = set_return_deadline(db, a_id, deadline, "Chicago, IL")
    assert ok is True

    assignment = db.get_active_assignment("EJGZ003")
    assert assignment is not None
    assert assignment[7] == deadline
    assert assignment[6] == "Chicago, IL"


def test_overdue_check_returns_expired(db):
    a_id = create_assignment(db, "EJGZ_LATE", "111", "Driver1", "Loc1")
    past = (datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    set_return_deadline(db, a_id, past, "ReturnLoc")

    overdue = get_overdue_returns(db)
    assert len(overdue) == 1
    assert overdue[0][1] == "EJGZ_LATE"


def test_overdue_check_ignores_returned(db):
    a_id = create_assignment(db, "EJGZ_RETURNED", "222", "Driver2", "Loc2")
    past = (datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    set_return_deadline(db, a_id, past, "ReturnLoc")
    complete_assignment(db, "EJGZ_RETURNED")

    overdue = get_overdue_returns(db)
    assert len(overdue) == 0


def test_double_pick_same_trailer(db):
    a1 = create_assignment(db, "EJGZ_DUP", "111", "Driver1", "Loc1")
    a2 = create_assignment(db, "EJGZ_DUP", "222", "Driver2", "Loc2")

    assert a1 != a2
    assert a2 > 0
    assignment = db.get_active_assignment("EJGZ_DUP")
    assert assignment is not None
    assert assignment[2] == "222"


def test_drop_without_pick(db):
    ok = complete_assignment(db, "EJGZ_NOPICK")
    assert ok is False
