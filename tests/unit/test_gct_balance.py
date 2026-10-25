"""Unit tests for the ground contact balance in get_activity and get_activity_splits (activity_management.py)"""
import json

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_workouts_mcp import activity_management
from garmin_workouts_mcp.activity_management import ground_contact_balance


class FakeGarmin:
    def get_activity(self, activity_id):
        return {"activityId": activity_id, "activityName": "Run", "activityTypeDTO": {"typeKey": "running"}, "metadataDTO": {},
                "summaryDTO": {"distance": 5000.0, "groundContactTime": 250.0, "groundContactBalanceLeft": 52.0099983215332}}

    def get_activity_splits(self, activity_id):
        return {"activityId": activity_id, "lapDTOs": [
            {"lapIndex": 1, "distance": 1000.0, "groundContactBalanceLeft": 51.98},
            {"lapIndex": 2, "distance": 1000.0}]}  # a lap without running dynamics


@pytest.fixture
def app():
    activity_management.configure(FakeGarmin())
    application = FastMCP("Test gct balance")
    activity_management.register_tools(application)
    return application


def test_helper_gives_left_and_right_with_the_raw_name():
    assert ground_contact_balance(52.0099983215332) == {"left_percent": 52.0, "right_percent": 48.0, "raw_field": "groundContactBalanceLeft"}
    assert ground_contact_balance(None) is None


@pytest.mark.asyncio
async def test_get_activity_and_splits_return_the_balance(app):
    activity = json.loads((await app.call_tool("get_activity", {"activity_id": 1}))[0][0].text)
    assert activity["ground_contact_balance"] == {"left_percent": 52.0, "right_percent": 48.0, "raw_field": "groundContactBalanceLeft"}
    assert activity["avg_ground_contact_time_ms"] == 250.0
    splits = json.loads((await app.call_tool("get_activity_splits", {"activity_id": 1}))[0][0].text)
    assert splits["laps"][0]["ground_contact_balance"]["left_percent"] == 52.0 and splits["laps"][0]["ground_contact_balance"]["right_percent"] == 48.0
    assert "ground_contact_balance" not in splits["laps"][1]  # no data, no field
