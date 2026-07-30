import os
import sys
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aioresponses import aioresponses
from providers.roadready import RoadReadyProvider, AUTH_URL, FLEET_URL


@pytest.fixture
def provider():
    return RoadReadyProvider(username="testuser", password="testpass")


@pytest.mark.asyncio
async def test_roadready_auth_success(provider):
    with aioresponses() as m:
        m.post(AUTH_URL, body='"test-token-abc"')
        m.get(FLEET_URL, payload={"data": []})

        positions = await provider.fetch_positions()
        assert provider._token == "test-token-abc"
        assert positions == []


@pytest.mark.asyncio
async def test_roadready_auth_failure(provider):
    with aioresponses() as m:
        m.post(AUTH_URL, status=401, body="Unauthorized")

        with pytest.raises(RuntimeError, match="auth failed"):
            await provider.fetch_positions()


@pytest.mark.asyncio
async def test_roadready_fetch_positions(provider):
    fleet_data = {
        "data": [
            {
                "id": "123",
                "attributes": {
                    "trailerName": "EJGZ381046",
                    "latitude": 32.77,
                    "longitude": -96.79,
                    "batteryPercentage": 90,
                    "landmarkTrailerState": "InMotion",
                },
            },
            {
                "id": "456",
                "attributes": {
                    "trailerName": "EJGZ381090",
                    "latitude": 33.45,
                    "longitude": -97.12,
                    "batteryPercentage": 45,
                    "landmarkTrailerState": "Stopped",
                },
            },
        ]
    }
    with aioresponses() as m:
        m.post(AUTH_URL, body='"tok123"')
        m.get(FLEET_URL, payload=fleet_data)

        positions = await provider.fetch_positions()
        assert len(positions) == 2
        assert positions[0].trailer_id == "EJGZ381046"
        assert positions[0].latitude == 32.77
        assert positions[0].battery_pct == 90
        assert positions[1].trailer_id == "EJGZ381090"
        assert positions[1].raw_status == "Stopped"


@pytest.mark.asyncio
async def test_roadready_reauth_on_401(provider):
    fleet_data = {"data": [{"id": "1", "attributes": {
        "trailerName": "EJGZ001", "latitude": 32.0, "longitude": -96.0,
    }}]}

    with aioresponses() as m:
        m.post(AUTH_URL, body='"old-token"')
        m.get(FLEET_URL, status=401)
        m.post(AUTH_URL, body='"new-token"')
        m.get(FLEET_URL, payload=fleet_data)

        positions = await provider.fetch_positions()
        assert len(positions) == 1
        assert provider._token == "new-token"


@pytest.mark.asyncio
async def test_roadready_empty_fleet(provider):
    with aioresponses() as m:
        m.post(AUTH_URL, body='"tok"')
        m.get(FLEET_URL, payload={"data": []})

        positions = await provider.fetch_positions()
        assert positions == []
