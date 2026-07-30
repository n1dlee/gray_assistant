import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from trailer import parse_message


def test_parse_pick_standard():
    text = """#pick
TRAILER: EJGZ381046
LOCATION: 123 Main St
Dallas, TX 75201
TRUCK: 22203
DRIVER: John Smith"""

    result = parse_message(text)
    assert result is not None
    assert result["trailer_id"] == "EJGZ381046"
    assert result["status"] == "DRIVING"
    assert result["truck_number"] == "22203"
    assert result["driver"] == "John Smith"
    assert "Dallas" in result["location"]


def test_parse_drop_standard():
    text = """#drop
TRAILER: EJGZ381090
LOCATION: 456 Oak Ave, Houston, TX 77001
TRUCK: 22237
DRIVER: Jane Doe"""

    result = parse_message(text)
    assert result is not None
    assert result["status"] == "DROPPED"
    assert result["trailer_id"] == "EJGZ381090"


def test_parse_with_date():
    text = """#pick
TRAILER: EJGZ145286
DATE: 2026-06-14
LOCATION: 789 Pine Rd, Austin, TX 78701
TRUCK: 22262
DRIVER: Bob Wilson"""

    result = parse_message(text)
    assert result is not None
    assert result["date_str"] == "2026-06-14"


def test_parse_multiline_location():
    text = """#pick
TRAILER: SS006051
LOCATION: 100 Industrial Blvd
Suite 200
Chicago, IL 60601
TRUCK: 22267
DRIVER: Mike Johnson"""

    result = parse_message(text)
    assert result is not None
    assert "\n" in result["location"]
    assert "100 Industrial" in result["location"]
    assert "Chicago" in result["location"]


def test_parse_missing_driver():
    text = """#pick
TRAILER: EJGZ001
LOCATION: Some Place, TX 75001
TRUCK: 22203"""

    result = parse_message(text)
    assert result is None


def test_parse_extra_whitespace():
    text = """  #pick

TRAILER:   EJGZ381046
LOCATION:    123 Main St, Dallas, TX 75201
TRUCK:    22203
DRIVER:    John Smith  """

    result = parse_message(text)
    assert result is not None
    assert result["trailer_id"] == "EJGZ381046"
    assert result["truck_number"] == "22203"
    assert result["driver"] == "John Smith"
