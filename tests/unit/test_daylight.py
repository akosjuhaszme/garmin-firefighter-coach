"""
Unit tests for the daylight tool (daylight.py)

Reference values come from the independent `astral` library (checked once for five places and seven dates: the largest
difference was two minutes, in an arctic edge case, everything else within one minute); the calculation is expected to be within
two minutes of them.
"""
import datetime
import json
from zoneinfo import ZoneInfo

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_workouts_mcp import daylight

BUDAPEST = (47.4979, 19.0402, ZoneInfo("Europe/Budapest"))


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


@pytest.mark.parametrize("day, sunrise, sunset", [
    ("2026-06-21", "04:46", "20:44"),  # summer solstice, summer time
    ("2026-12-21", "07:28", "15:54"),  # winter solstice, winter time
])
def test_budapest_matches_the_reference_times(day, sunrise, sunset):
    row = daylight.daylight_for_day(datetime.date.fromisoformat(day), *BUDAPEST)
    assert abs(_minutes(row["sunrise"]) - _minutes(sunrise)) <= 2
    assert abs(_minutes(row["sunset"]) - _minutes(sunset)) <= 2
    assert _minutes(row["civil_dawn"]) < _minutes(row["sunrise"]) < _minutes(row["solar_noon"]) < _minutes(row["sunset"]) < _minutes(row["civil_dusk"])


def test_clock_change_is_included():
    before = daylight.daylight_for_day(datetime.date(2026, 10, 24), *BUDAPEST)  # last day of summer time
    after = daylight.daylight_for_day(datetime.date(2026, 10, 25), *BUDAPEST)  # clocks go back that night
    assert before["utc_offset_hours"] == 2 and after["utc_offset_hours"] == 1
    assert 55 <= _minutes(before["sunrise"]) - _minutes(after["sunrise"]) <= 62


def test_wake_up_time_is_sunrise_minus_the_chosen_minutes():
    row = daylight.daylight_for_day(datetime.date(2026, 10, 26), *BUDAPEST, minutes_before=45)
    assert _minutes(row["sunrise"]) - _minutes(row["wake_up_before_sunrise"]) == 45


def test_no_sunrise_in_the_polar_summer():
    row = daylight.daylight_for_day(datetime.date(2026, 6, 21), 80.0, 15.0, ZoneInfo("Europe/Oslo"))
    assert row["sunrise"] is None and row["sunset"] is None and "does not rise" in row["note"]
    assert "wake_up_before_sunrise" not in row


async def _call(app, args):
    return (await app.call_tool("get_daylight", args))[0][0].text


@pytest.fixture
def app():
    application = FastMCP("t")
    daylight.register_tools(application)
    return application


@pytest.mark.asyncio
async def test_tool_returns_several_days(app):
    data = json.loads(await _call(app, {"date": "2026-10-23", "days": 3, "latitude": 47.5, "longitude": 19.0, "timezone": "Europe/Budapest"}))
    assert [d["date"] for d in data["days"]] == ["2026-10-23", "2026-10-24", "2026-10-25"]
    assert data["timezone"] == "Europe/Budapest" and data["days"][0]["wake_up_before_sunrise"]


@pytest.mark.asyncio
async def test_tool_uses_the_environment_and_checks_input(app, monkeypatch):
    for name in ("GARMIN_COACH_LATITUDE", "GARMIN_COACH_LONGITUDE", "GARMIN_COACH_TIMEZONE"):
        monkeypatch.delenv(name, raising=False)
    assert "give latitude, longitude and timezone" in await _call(app, {"date": "2026-10-23"})
    monkeypatch.setenv("GARMIN_COACH_LATITUDE", "47.5")
    monkeypatch.setenv("GARMIN_COACH_LONGITUDE", "19.0")
    monkeypatch.setenv("GARMIN_COACH_TIMEZONE", "Europe/Budapest")
    assert json.loads(await _call(app, {"date": "2026-10-23"}))["days"][0]["sunrise"]
    for args, fragment in (
        ({"days": 40}, "days must be"), ({"timezone": "Mars/Base"}, "unknown time zone"), ({"date": "tomorrow"}, "YYYY-MM-DD"),
        ({"latitude": 95}, "latitude must be"), ({"minutes_before": 900}, "minutes_before"),
    ):
        assert fragment in await _call(app, args)
